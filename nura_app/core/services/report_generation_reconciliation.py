import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker

from core.repositories.report_lifecycle import (
    ReportGenerationJobRepository,
)
from core.services.full_report_telegram_delivery import FullReportDeliveryReconciler

logger = logging.getLogger(__name__)

_MAX_DISPATCH_ATTEMPTS = 5
_MAX_GENERATION_ATTEMPTS = 3
_DEFAULT_STALE_DISPATCHING = timedelta(minutes=2)
_DEFAULT_STALE_QUEUED = timedelta(minutes=10)
_DEFAULT_STALE_RUNNING = timedelta(minutes=30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ReconciliationBatchResult:
    inspected: int = 0
    dispatch_claims_recovered: int = 0
    queued_recovered: int = 0
    running_recovered: int = 0
    retries_promoted: int = 0
    terminalized: int = 0
    missing_jobs_repaired: int = 0
    completed_pairs_repaired: int = 0
    full_deliveries_created: int = 0
    full_deliveries_canceled: int = 0
    full_deliveries_claimed: int = 0
    full_deliveries_dispatched: int = 0
    conflicts: int = 0
    errors: int = 0


class ReportGenerationReconciler:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        *,
        dispatch_claim_stale_before: timedelta = _DEFAULT_STALE_DISPATCHING,
        queued_stale_before: timedelta = _DEFAULT_STALE_QUEUED,
        running_stale_before: timedelta = _DEFAULT_STALE_RUNNING,
        max_dispatch_attempts: int = _MAX_DISPATCH_ATTEMPTS,
        max_generation_attempts: int = _MAX_GENERATION_ATTEMPTS,
        delivery_dispatch=None,
    ):
        self._session_factory = session_factory
        self._dispatch_stale = dispatch_claim_stale_before
        self._queued_stale = queued_stale_before
        self._running_stale = running_stale_before
        self._max_dispatch_attempts = max_dispatch_attempts
        self._max_generation_attempts = max_generation_attempts
        self._full_deliveries = FullReportDeliveryReconciler(
            session_factory, dispatch=delivery_dispatch
        )

    async def reconcile_batch(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> ReconciliationBatchResult:
        counters: dict[str, int] = {
            "inspected": 0,
            "dispatch_claims_recovered": 0,
            "queued_recovered": 0,
            "running_recovered": 0,
            "retries_promoted": 0,
            "terminalized": 0,
            "missing_jobs_repaired": 0,
            "completed_pairs_repaired": 0,
            "full_deliveries_created": 0,
            "full_deliveries_canceled": 0,
            "full_deliveries_claimed": 0,
            "full_deliveries_dispatched": 0,
            "conflicts": 0,
            "errors": 0,
        }

        dispatch_stale = now - self._dispatch_stale
        queued_stale = now - self._queued_stale
        running_stale = now - self._running_stale

        await self._recover_stale_dispatching(counters, dispatch_stale, now, limit)
        await self._recover_stale_queued(counters, queued_stale, now, limit)
        await self._recover_stale_running(counters, running_stale, now, limit)
        await self._promote_due_retries(counters, now, limit)
        await self._repair_missing_jobs(counters, limit)
        await self._repair_completed_pairs(counters, now, limit)
        delivery_result = await self._full_deliveries.reconcile_batch(
            now=now, limit=limit
        )
        counters["full_deliveries_created"] = delivery_result.missing_created
        counters["full_deliveries_canceled"] = delivery_result.canceled_ineligible
        counters["full_deliveries_claimed"] = delivery_result.claimed
        counters["full_deliveries_dispatched"] = delivery_result.dispatched
        counters["conflicts"] += delivery_result.conflicts
        counters["errors"] += delivery_result.errors

        return ReconciliationBatchResult(**counters)

    async def _recover_stale_dispatching(
        self,
        counters: dict[str, int],
        stale_before: datetime,
        now: datetime,
        limit: int,
    ) -> None:
        async with self._session_factory() as session:
            try:
                repo = ReportGenerationJobRepository(session)
                jobs = await repo.list_stale_dispatching_jobs(stale_before, limit)
                counters["inspected"] += len(jobs)
            except Exception:
                await session.rollback()
                counters["errors"] += 1
                return

        for job_id, report_id in jobs:
            async with self._session_factory() as session:
                try:
                    repo = ReportGenerationJobRepository(session)
                    next_at = now + timedelta(seconds=30)
                    recovered = await repo.mark_stale_dispatch_claim_retryable(
                        job_id,
                        stale_before,
                        now,
                        next_at,
                    )
                    await session.commit()
                    if recovered:
                        counters["dispatch_claims_recovered"] += 1
                    else:
                        counters["conflicts"] += 1
                except Exception:
                    await session.rollback()
                    counters["errors"] += 1

    async def _recover_stale_queued(
        self,
        counters: dict[str, int],
        stale_before: datetime,
        now: datetime,
        limit: int,
    ) -> None:
        async with self._session_factory() as session:
            try:
                repo = ReportGenerationJobRepository(session)
                pairs = await repo.list_stale_queued_pairs(stale_before, limit)
                counters["inspected"] += len(pairs)
            except Exception:
                await session.rollback()
                counters["errors"] += 1
                return

        for _job_id, report_id in pairs:
            async with self._session_factory() as session:
                try:
                    repo = ReportGenerationJobRepository(session)
                    next_at = now + timedelta(seconds=30)
                    recovered = await repo.mark_stale_queued_generation_retryable(
                        report_id,
                        stale_before,
                        now,
                        next_at,
                    )
                    await session.commit()
                    if recovered:
                        counters["queued_recovered"] += 1
                    else:
                        counters["conflicts"] += 1
                except Exception:
                    await session.rollback()
                    counters["errors"] += 1

    async def _recover_stale_running(
        self,
        counters: dict[str, int],
        stale_before: datetime,
        now: datetime,
        limit: int,
    ) -> None:
        async with self._session_factory() as session:
            try:
                repo = ReportGenerationJobRepository(session)
                report_ids = await repo.list_stale_running_pairs(stale_before, limit)
                counters["inspected"] += len(report_ids)
            except Exception:
                await session.rollback()
                counters["errors"] += 1
                return

        for report_id in report_ids:
            async with self._session_factory() as session:
                try:
                    repo = ReportGenerationJobRepository(session)
                    next_at = now + timedelta(seconds=30)
                    recovered = await repo.mark_stale_running_generation_retryable(
                        report_id,
                        stale_before,
                        now,
                        next_at,
                    )
                    await session.commit()
                    if recovered:
                        counters["running_recovered"] += 1
                    else:
                        counters["conflicts"] += 1
                except Exception:
                    await session.rollback()
                    counters["errors"] += 1

    async def _promote_due_retries(
        self,
        counters: dict[str, int],
        now: datetime,
        limit: int,
    ) -> None:
        async with self._session_factory() as session:
            try:
                repo = ReportGenerationJobRepository(session)
                pairs = await repo.list_due_failed_retryable_pairs(
                    now,
                    self._max_dispatch_attempts,
                    self._max_generation_attempts,
                    limit,
                )
                counters["inspected"] += len(pairs)
            except Exception:
                await session.rollback()
                counters["errors"] += 1
                return

        for _job_id, report_id, dispatch_attempts, gen_attempts in pairs:
            async with self._session_factory() as session:
                try:
                    repo = ReportGenerationJobRepository(session)
                    if (
                        dispatch_attempts >= self._max_dispatch_attempts
                        or gen_attempts >= self._max_generation_attempts
                    ):
                        terminalized = await repo.terminalize_exhausted_pair(
                            report_id, now
                        )
                        await session.commit()
                        if terminalized:
                            counters["terminalized"] += 1
                        else:
                            counters["conflicts"] += 1
                    else:
                        promoted = await repo.promote_failed_retryable_to_pending(
                            report_id, now
                        )
                        await session.commit()
                        if promoted:
                            counters["retries_promoted"] += 1
                        else:
                            counters["conflicts"] += 1
                except Exception:
                    await session.rollback()
                    counters["errors"] += 1

    async def _repair_missing_jobs(
        self,
        counters: dict[str, int],
        limit: int,
    ) -> None:
        async with self._session_factory() as session:
            try:
                repo = ReportGenerationJobRepository(session)
                report_ids = await repo.list_missing_job_paid_reports(limit)
                counters["inspected"] += len(report_ids)
            except Exception:
                await session.rollback()
                counters["errors"] += 1
                return

        for report_id in report_ids:
            async with self._session_factory() as session:
                try:
                    repo = ReportGenerationJobRepository(session)
                    repaired = await repo.repair_missing_full_report_job(report_id)
                    await session.commit()
                    if repaired:
                        counters["missing_jobs_repaired"] += 1
                    else:
                        counters["conflicts"] += 1
                except Exception:
                    await session.rollback()
                    counters["errors"] += 1

    async def _repair_completed_pairs(
        self,
        counters: dict[str, int],
        now: datetime,
        limit: int,
    ) -> None:
        async with self._session_factory() as session:
            try:
                repo = ReportGenerationJobRepository(session)
                report_ids = await repo.list_completed_report_active_job_pairs(limit)
                counters["inspected"] += len(report_ids)
            except Exception:
                await session.rollback()
                counters["errors"] += 1
                return

        for report_id in report_ids:
            async with self._session_factory() as session:
                try:
                    repo = ReportGenerationJobRepository(session)
                    repaired = await repo.repair_completed_pair(report_id, now)
                    await session.commit()
                    if repaired:
                        counters["completed_pairs_repaired"] += 1
                    else:
                        counters["conflicts"] += 1
                except Exception:
                    await session.rollback()
                    counters["errors"] += 1


def build_report_generation_reconciler() -> ReportGenerationReconciler:
    from core.database import get_async_sessionmaker

    session_factory = get_async_sessionmaker()
    return ReportGenerationReconciler(session_factory)
