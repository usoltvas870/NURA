import hashlib
import html
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import (
    Order,
    OrderStatus,
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
from core.services.prompt_governance import (
    ResolvedPromptBundle,
    finalize_generation_metadata,
    input_hash,
    resolve_active_bundle,
    resolve_pinned_bundle,
)
from core.services.report import ReportService


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

        prompt_bundle = await self._resolve_prompt_bundle(report_id)
        from core.config import settings

        prompt_pin = prompt_bundle.pin("report.full")
        prompt_pin["requested_model"] = settings.deepseek_model

        claimed = await self._claim(report_id, prompt_pin)
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
                prompt_bundle=prompt_bundle,
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
            artifact = await self._render_artifact(generator_result, generation_input)
            persisted = await self._persist_success(report_id, generator_result, artifact)
        except Exception:
            return WorkerResult.retryable(
                ReportGenerationErrorCategory.UNKNOWN_INTERNAL
            )

        if persisted == "entitlement_revoked":
            return WorkerResult.terminal(
                ReportGenerationErrorCategory.ENTITLEMENT_REVOKED
            )
        if persisted != "persisted":
            return WorkerResult.retryable(
                ReportGenerationErrorCategory.UNKNOWN_INTERNAL
            )

        return WorkerResult.completed()

    async def _resolve_prompt_bundle(self, report_id: uuid.UUID) -> ResolvedPromptBundle:
        async with self._session_factory() as session:
            report = await session.get(Report, report_id)
            if report is None:
                await session.rollback()
                raise RuntimeError("report_not_found")
            if isinstance(report.generation_metadata, dict):
                bundle = resolve_pinned_bundle(
                    "report.full", report.generation_metadata
                )
                await session.rollback()
                return bundle
            bundle = resolve_active_bundle("report.full")
            await session.rollback()
            return bundle

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

    async def _claim(
        self, report_id: uuid.UUID, generation_metadata: dict
    ) -> WorkerResult:
        async with self._session_factory() as session:
            repository = ReportGenerationJobRepository(session)
            outcome, report, _ = await repository.claim_generation_run(
                report_id, _now(), generation_metadata
            )
            if outcome == "claimed":
                await session.commit()
                return WorkerResult.completed()
            if outcome == "generation_already_completed":
                await session.rollback()
                return WorkerResult.idempotent_completed()
            if outcome == "generation_already_terminal":
                entitlement_revoked = (
                    report is not None
                    and report.generation_error_category
                    == ReportGenerationErrorCategory.ENTITLEMENT_REVOKED
                )
                await session.rollback()
                if entitlement_revoked:
                    return WorkerResult.terminal(
                        ReportGenerationErrorCategory.ENTITLEMENT_REVOKED
                    )
                return WorkerResult.terminal(ReportGenerationErrorCategory.UNKNOWN_INTERNAL)
            if outcome == "entitlement_revoked":
                await session.rollback()
                return WorkerResult.terminal(
                    ReportGenerationErrorCategory.ENTITLEMENT_REVOKED
                )
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

            if report.order_id is not None:
                order = await session.get(Order, report.order_id)
                if order is None or order.status != OrderStatus.PAID:
                    await session.rollback()
                    return None

            if (
                report_type != ReportType.FULL.value
                or payment_state != ReportPaymentState.PAYMENT_CONFIRMED
                or (payment_id is None and report.order_id is None)
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
        artifact: bytes,
    ) -> str:
        async with self._session_factory() as session:
            order_id = await session.scalar(
                select(Report.order_id).where(Report.id == report_id)
            )
            if order_id is not None:
                order = await session.get(Order, order_id, with_for_update=True)
                if order is None or order.status != OrderStatus.PAID:
                    await ReportLifecycleRepository(
                        session
                    ).revoke_unfinished_order_report(report_id, _now())
                    await session.commit()
                    return "entitlement_revoked"
            report = await session.get(Report, report_id, with_for_update=True)
            if report is None:
                await session.rollback()
                return "conflict"
            if (
                report.payment_state != ReportPaymentState.PAYMENT_CONFIRMED
                or report.generation_state != ReportGenerationState.RUNNING
            ):
                revoked = (
                    report.generation_error_category
                    == ReportGenerationErrorCategory.ENTITLEMENT_REVOKED
                )
                await session.rollback()
                return "entitlement_revoked" if revoked else "conflict"
            repository = ReportGenerationJobRepository(session)
            job = await repository.get_by_report_and_type(report_id)
            if job is None or job.state != ReportGenerationJobState.QUEUED:
                await session.rollback()
                return "conflict"

            report.matrix_data = generator_result.matrix_data
            report.ai_analysis = generator_result.ai_analysis
            report.kitchen_analysis = generator_result.kitchen_analysis
            pin = report.generation_metadata
            if not isinstance(pin, dict):
                raise RuntimeError("report_prompt_pin_missing")
            details = generator_result.generation_details or {}
            generation_source = details.get("generation_source")
            if generation_source not in {"provider", "fallback"}:
                generation_source = "fallback"
            provider = details.get("provider")
            model = details.get("model")
            report.generation_metadata = finalize_generation_metadata(
                pin,
                provider=provider if isinstance(provider, str) else None,
                model=model if isinstance(model, str) else None,
                generation_source=generation_source,
                structured_input_hash=input_hash(generator_result.matrix_data),
                components=(
                    details.get("components")
                    if isinstance(details.get("components"), dict)
                    else None
                ),
            )
            report.artifact_bytes = artifact
            report.artifact_sha256 = hashlib.sha256(artifact).hexdigest()
            report.artifact_size_bytes = len(artifact)
            report.artifact_mime_type = "application/pdf"
            now = _now()
            report.artifact_completed_at = now
            ReportLifecycleRepository.mark_report_completed(report, now)
            repository.mark_job_completed(job, now)
            await session.commit()
            return "persisted"

    @staticmethod
    async def _render_artifact(
        result: MatrixReportGeneratorResult, generation_input: _GenerationInput
    ) -> bytes:
        report_data = {
            "matrix": result.matrix_data,
            "analysis": result.ai_analysis,
            "kitchen_analysis": result.kitchen_analysis,
            "user_name": generation_input.user_name,
            "token": generation_input.report_token,
        }
        try:
            rendered_html = ReportService.generate_html_report(report_data, template_name="full_report_v2.html")
        except Exception:
            # Existing generator persistence is the source of truth. This safe renderer
            # keeps delivery available if a legacy result lacks an optional template field.
            rendered_html = "<html><body><h1>Полная Матрица — NURA</h1><pre>%s</pre></body></html>" % html.escape(
                json.dumps(report_data, ensure_ascii=False, indent=2, default=str)
            )
        pdf = await ReportService.generate_pdf(rendered_html)
        if not pdf.startswith(b"%PDF-") or len(pdf) < 1024:
            raise ValueError("invalid_full_report_pdf")
        return pdf

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
