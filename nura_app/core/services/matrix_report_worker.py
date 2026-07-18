import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import (
    Report,
    ReportGenerationJob,
    ReportGenerationJobState,
    ReportGenerationState,
    ReportPaymentState,
    ReportType,
    User,
)
from core.repositories.report_lifecycle import (
    REPORT_GENERATION_ERROR_CATEGORIES,
    ReportGenerationErrorCategory,
    ReportGenerationJobRepository,
    ReportLifecycleRepository,
)
from core.services.matrix_report_generator import (
    MatrixReportGenerationError,
    MatrixReportGenerator,
    MatrixReportGeneratorResult,
)


MATRIX_GENERATION_RETRYABLE_ERRORS = frozenset(
    {
        ReportGenerationErrorCategory.AI_TIMEOUT,
        ReportGenerationErrorCategory.AI_PROVIDER_UNAVAILABLE,
        ReportGenerationErrorCategory.STORAGE_FAILED,
        ReportGenerationErrorCategory.UNKNOWN_INTERNAL,
    }
)


class GenerationDisposition(str, Enum):
    COMPLETED = "completed"
    IDEMPOTENT_COMPLETED = "idempotent_completed"
    RETRYABLE_FAILURE = "retryable_failure"
    TERMINAL_FAILURE = "terminal_failure"


@dataclass(frozen=True)
class WorkerResult:
    disposition: GenerationDisposition
    error_category: str | None = None

    @classmethod
    def completed(cls) -> "WorkerResult":
        return cls(GenerationDisposition.COMPLETED)

    @classmethod
    def idempotent_completed(cls) -> "WorkerResult":
        return cls(GenerationDisposition.IDEMPOTENT_COMPLETED)

    @classmethod
    def retryable(cls, error_category: str) -> "WorkerResult":
        return cls(GenerationDisposition.RETRYABLE_FAILURE, error_category)

    @classmethod
    def terminal(cls, error_category: str) -> "WorkerResult":
        return cls(GenerationDisposition.TERMINAL_FAILURE, error_category)


@dataclass(frozen=True)
class _GenerationInput:
    birth_date: str
    user_name: str
    report_token: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MatrixReportGenerationWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        generator: MatrixReportGenerator,
    ):
        self._session_factory = session_factory
        self._generator = generator

    async def process(self, *, job_id: uuid.UUID, report_id: uuid.UUID) -> WorkerResult:
        job_valid = await self._validate_job(job_id, report_id)
        if not job_valid:
            return WorkerResult.terminal(ReportGenerationErrorCategory.UNKNOWN_INTERNAL)

        claimed = await self._claim(report_id)
        if claimed.disposition != GenerationDisposition.COMPLETED:
            return claimed

        generation_input = await self._load_generation_input(report_id)
        if generation_input is None:
            return WorkerResult.terminal(ReportGenerationErrorCategory.UNKNOWN_INTERNAL)

        try:
            generator_result = await self._generator.generate(
                birth_date=generation_input.birth_date,
                user_name=generation_input.user_name,
                report_token=generation_input.report_token,
            )
        except MatrixReportGenerationError as error:
            raw_category = error.error_category
            if raw_category in MATRIX_GENERATION_RETRYABLE_ERRORS:
                await self._mark_retryable_failure(report_id, raw_category)
                return WorkerResult.retryable(raw_category)
            safe_terminal = self._safe_category_default(
                raw_category, ReportGenerationErrorCategory.UNKNOWN_INTERNAL
            )
            await self._mark_terminal_failure(report_id, safe_terminal)
            return WorkerResult.terminal(safe_terminal)
        except Exception:
            await self._mark_retryable_failure(
                report_id,
                ReportGenerationErrorCategory.UNKNOWN_INTERNAL,
            )
            return WorkerResult.retryable(ReportGenerationErrorCategory.UNKNOWN_INTERNAL)

        try:
            persisted = await self._persist_success(report_id, generator_result)
        except Exception:
            return WorkerResult.retryable(
                ReportGenerationErrorCategory.UNKNOWN_INTERNAL
            )

        if not persisted:
            return WorkerResult.retryable(
                ReportGenerationErrorCategory.UNKNOWN_INTERNAL
            )

        return WorkerResult.completed()

    async def _validate_job(
        self, job_id: uuid.UUID, report_id: uuid.UUID
    ) -> bool:
        async with self._session_factory() as session:
            job = await session.get(ReportGenerationJob, job_id)
            if job is None:
                await session.rollback()
                return False
            valid = (
                job.report_id == report_id
                and job.job_type == "full_report"
            )
            await session.rollback()
            return valid

    async def _claim(self, report_id: uuid.UUID) -> WorkerResult:
        async with self._session_factory() as session:
            repository = ReportGenerationJobRepository(session)
            outcome, report, _ = await repository.claim_generation_run(
                report_id, _now()
            )
            if outcome == "claimed":
                await session.commit()
                return WorkerResult.completed()
            if outcome == "generation_already_completed":
                await session.rollback()
                return WorkerResult.idempotent_completed()
            if outcome == "generation_already_terminal":
                await session.rollback()
                return WorkerResult.terminal(ReportGenerationErrorCategory.UNKNOWN_INTERNAL)
            if outcome == "generation_already_running":
                await session.rollback()
                return WorkerResult.retryable(
                    ReportGenerationErrorCategory.DISPATCH_CLAIM_EXPIRED
                )
            if outcome == "report_not_paid":
                await session.rollback()
                return WorkerResult.terminal(ReportGenerationErrorCategory.UNKNOWN_INTERNAL)
            await session.rollback()
            return WorkerResult.terminal(ReportGenerationErrorCategory.UNKNOWN_INTERNAL)

    async def _load_generation_input(
        self, report_id: uuid.UUID
    ) -> _GenerationInput | None:
        async with self._session_factory() as session:
            report = await session.get(Report, report_id)
            if report is None:
                await session.rollback()
                return None
            report_type = report.report_type
            payment_state = report.payment_state
            payment_id = report.payment_id
            generation_state = report.generation_state
            report_token = report.token
            user_id = report.user_id

            if (
                report_type != ReportType.FULL.value
                or payment_state != ReportPaymentState.PAYMENT_CONFIRMED
                or payment_id is None
                or generation_state != ReportGenerationState.RUNNING
            ):
                await session.rollback()
                return None

            user = await session.get(User, user_id)
            if user is None or not user.birth_date:
                await session.rollback()
                return None

            result = _GenerationInput(
                birth_date=user.birth_date,
                user_name=user.first_name or user.username or "пользователь",
                report_token=report_token,
            )
            await session.rollback()
            return result

    async def _persist_success(
        self,
        report_id: uuid.UUID,
        generator_result: MatrixReportGeneratorResult,
    ) -> bool:
        async with self._session_factory() as session:
            report = await session.get(Report, report_id, with_for_update=True)
            if report is None:
                await session.rollback()
                return False
            if (
                report.payment_state != ReportPaymentState.PAYMENT_CONFIRMED
                or report.generation_state != ReportGenerationState.RUNNING
            ):
                await session.rollback()
                return False
            repository = ReportGenerationJobRepository(session)
            job = await repository.get_by_report_and_type(report_id)
            if job is None or job.state != ReportGenerationJobState.QUEUED:
                await session.rollback()
                return False

            report.matrix_data = generator_result.matrix_data
            report.ai_analysis = generator_result.ai_analysis
            report.kitchen_analysis = generator_result.kitchen_analysis
            now = _now()
            ReportLifecycleRepository.mark_report_completed(report, now)
            repository.mark_job_completed(job, now)
            await session.commit()
            return True

    async def _mark_retryable_failure(
        self,
        report_id: uuid.UUID,
        error_category: str,
    ) -> None:
        async with self._session_factory() as session:
            report = await session.get(Report, report_id, with_for_update=True)
            if report is None:
                await session.rollback()
                return
            valid_states = {
                ReportGenerationState.RUNNING,
                ReportGenerationState.FAILED_RETRYABLE,
            }
            if report.generation_state not in valid_states:
                await session.rollback()
                return
            repository = ReportGenerationJobRepository(session)
            job = await repository.get_by_report_and_type(report_id)
            if job is None:
                await session.rollback()
                return
            job_valid_states = {
                ReportGenerationJobState.QUEUED,
                ReportGenerationJobState.FAILED_RETRYABLE,
            }
            if job.state not in job_valid_states:
                await session.rollback()
                return
            now = _now()
            attempts = report.generation_attempts
            delay = min(
                timedelta(seconds=30) * (2 ** min(attempts, 4)),
                timedelta(minutes=5),
            )
            safe_category = self._safe_retryable_category(error_category)
            ReportLifecycleRepository.mark_report_failed_retryable(
                report, safe_category, now
            )
            repository.mark_job_failed_retryable(job, safe_category, now + delay, now)
            await session.commit()

    async def _mark_terminal_failure(
        self,
        report_id: uuid.UUID,
        error_category: str,
    ) -> None:
        async with self._session_factory() as session:
            report = await session.get(Report, report_id, with_for_update=True)
            if report is None:
                await session.rollback()
                return
            if report.generation_state == ReportGenerationState.FAILED_TERMINAL:
                await session.rollback()
                return
            valid_states = {
                ReportGenerationState.RUNNING,
                ReportGenerationState.FAILED_RETRYABLE,
            }
            if report.generation_state not in valid_states:
                await session.rollback()
                return
            repository = ReportGenerationJobRepository(session)
            job = await repository.get_by_report_and_type(report_id)
            if job is None:
                await session.rollback()
                return
            now = _now()
            safe_category = self._safe_category_default(
                error_category,
                ReportGenerationErrorCategory.UNKNOWN_INTERNAL,
            )
            ReportLifecycleRepository.mark_report_failed_terminal(
                report, safe_category, now
            )
            repository.mark_job_failed_terminal(job, safe_category, now)
            await session.commit()

    @staticmethod
    def _safe_retryable_category(category: str) -> str:
        if category in MATRIX_GENERATION_RETRYABLE_ERRORS:
            return category
        return ReportGenerationErrorCategory.UNKNOWN_INTERNAL

    @staticmethod
    def _safe_category_default(category: str, fallback: str) -> str:
        if category in REPORT_GENERATION_ERROR_CATEGORIES:
            return category
        return fallback
