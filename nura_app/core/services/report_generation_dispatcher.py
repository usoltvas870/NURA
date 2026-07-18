import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Protocol

from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import ReportGenerationJobState
from core.repositories.report_lifecycle import (
    REPORT_GENERATION_ERROR_CATEGORIES,
    ReportGenerationErrorCategory,
    ReportGenerationJobRepository,
)
from core.services.report_lifecycle import ReportLifecycleService


class PublishDisposition(str, Enum):
    ACCEPTED = "accepted"
    RETRYABLE_FAILURE = "retryable_failure"
    TERMINAL_FAILURE = "terminal_failure"


@dataclass(frozen=True)
class PublishResult:
    disposition: PublishDisposition
    error_category: str | None = None

    @classmethod
    def accepted(cls) -> "PublishResult":
        return cls(PublishDisposition.ACCEPTED)

    @classmethod
    def retryable(cls, error_category: str) -> "PublishResult":
        return cls(PublishDisposition.RETRYABLE_FAILURE, error_category)

    @classmethod
    def terminal(cls, error_category: str) -> "PublishResult":
        return cls(PublishDisposition.TERMINAL_FAILURE, error_category)


class ReportGenerationPublisher(Protocol):
    async def publish(
        self, *, job_id: uuid.UUID, report_id: uuid.UUID, task_id: str
    ) -> PublishResult: ...


@dataclass(frozen=True)
class DispatchBatchResult:
    selected: int = 0
    claimed: int = 0
    published: int = 0
    retryable_failed: int = 0
    terminal_failed: int = 0
    claim_conflicts: int = 0


def report_generation_task_id(job_id: uuid.UUID) -> str:
    digest = hashlib.sha256(
        b"nura-report-generation-v1:" + job_id.bytes
    ).hexdigest()[:40]
    return f"nura-report-v1-{digest}"


class ReportGenerationDispatcher:
    """Short-transaction dispatcher with an injected publisher boundary."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        publisher: ReportGenerationPublisher,
        base_retry_delay: timedelta = timedelta(seconds=30),
        max_retry_delay: timedelta = timedelta(minutes=5),
    ):
        self._session_factory = session_factory
        self._publisher = publisher
        self._base_retry_delay = base_retry_delay
        self._max_retry_delay = max_retry_delay

    async def dispatch_batch(
        self, *, now: datetime, limit: int
    ) -> DispatchBatchResult:
        async with self._session_factory() as selection_session:
            jobs = await ReportGenerationJobRepository(
                selection_session
            ).list_dispatchable_jobs(now, limit)
            selected = [(job.id, job.report_id) for job in jobs]
            await selection_session.rollback()

        counters = {
            "selected": len(selected),
            "claimed": 0,
            "published": 0,
            "retryable_failed": 0,
            "terminal_failed": 0,
            "claim_conflicts": 0,
        }
        for job_id, report_id in selected:
            claimed = await self._claim(job_id, now)
            if not claimed:
                counters["claim_conflicts"] += 1
                continue
            counters["claimed"] += 1
            task_id = report_generation_task_id(job_id)
            try:
                result = await self._publisher.publish(
                    job_id=job_id, report_id=report_id, task_id=task_id
                )
            except Exception:
                result = PublishResult.retryable(
                    ReportGenerationErrorCategory.DISPATCH_FAILED
                )

            if result.disposition == PublishDisposition.ACCEPTED:
                if await self._mark_published(report_id, task_id, now):
                    counters["published"] += 1
                else:
                    counters["retryable_failed"] += 1
            elif result.disposition == PublishDisposition.RETRYABLE_FAILURE:
                await self._mark_retryable(job_id, now, result.error_category)
                counters["retryable_failed"] += 1
            else:
                await self._mark_terminal(report_id, now, result.error_category)
                counters["terminal_failed"] += 1
        return DispatchBatchResult(**counters)

    async def _claim(self, job_id: uuid.UUID, now: datetime) -> bool:
        async with self._session_factory() as session:
            repository = ReportGenerationJobRepository(session)
            outcome = await repository.claim_job_for_dispatch(job_id, now)
            await session.commit()
            return outcome == "claimed"

    async def _mark_published(
        self, report_id: uuid.UUID, task_id: str, now: datetime
    ) -> bool:
        async with self._session_factory() as session:
            try:
                await ReportLifecycleService(session).mark_generation_queued(
                    report_id, task_id, now
                )
                await session.commit()
                return True
            except Exception:
                await session.rollback()
                return False

    async def _mark_retryable(
        self, job_id: uuid.UUID, now: datetime, category: str | None
    ) -> None:
        safe_category = self._safe_category(
            category, ReportGenerationErrorCategory.DISPATCH_FAILED
        )
        async with self._session_factory() as session:
            try:
                repository = ReportGenerationJobRepository(session)
                job = await repository.get_by_id(job_id)
                if job is None or job.state != ReportGenerationJobState.DISPATCHING:
                    await session.rollback()
                    return
                delay = self._retry_delay(job.attempts)
                repository.mark_job_failed_retryable(
                    job, safe_category, now + delay, now
                )
                await session.commit()
            except Exception:
                await session.rollback()
                return

    async def _mark_terminal(
        self, report_id: uuid.UUID, now: datetime, category: str | None
    ) -> None:
        safe_category = self._safe_category(
            category, ReportGenerationErrorCategory.UNKNOWN_INTERNAL
        )
        async with self._session_factory() as session:
            try:
                await ReportLifecycleService(session).mark_dispatch_terminal(
                    report_id, safe_category, now
                )
                await session.commit()
            except Exception:
                await session.rollback()

    def _retry_delay(self, attempts: int) -> timedelta:
        multiplier = 2 ** min(attempts, 4)
        return min(self._base_retry_delay * multiplier, self._max_retry_delay)

    @staticmethod
    def _safe_category(category: str | None, fallback: str) -> str:
        if category in REPORT_GENERATION_ERROR_CATEGORIES:
            return category
        return fallback
