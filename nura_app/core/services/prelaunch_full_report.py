"""Audited owner-only full-report generation without payment entitlement."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from core.config import settings
from core.models import ReportGenerationState
from core.repositories.report import ReportRepository
from core.repositories.user import UserRepository
from core.services.full_report_telegram_delivery import (
    FullReportTelegramDeliveryService,
)
from core.services.prompt_governance import resolve_active_bundle
from core.services.report import ReportService
from core.services.telegram_sandbox import telegram_user_is_allowed


_REQUEST_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,64}$")


class PrelaunchFullReportError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PrelaunchFullReportRequestResult:
    report_id: uuid.UUID
    status: str
    generation_dispatched: bool = False
    delivery_dispatched: bool = False


class PrelaunchFullReportService:
    def __init__(
        self,
        session_factory,
        *,
        dispatch_generation: Callable[[uuid.UUID], None] | None = None,
        dispatch_delivery: Callable[[uuid.UUID], None] | None = None,
    ) -> None:
        self._reports = ReportRepository(session_factory)
        self._users = UserRepository(session_factory)
        self._deliveries = FullReportTelegramDeliveryService(session_factory)
        self._dispatch_generation = (
            dispatch_generation or self._dispatch_generation_task
        )
        self._dispatch_delivery = dispatch_delivery or self._dispatch_delivery_task

    @staticmethod
    def _require_mode() -> None:
        if (
            not settings.is_owner_prelaunch
            or settings.payments_enabled
            or settings.test_mode
            or settings.enable_internal_payment_shortcut
        ):
            raise PrelaunchFullReportError("prelaunch_full_report_unavailable")

    @staticmethod
    def _dispatch_generation_task(report_id: uuid.UUID) -> None:
        from core.tasks import generate_prelaunch_full_report

        generate_prelaunch_full_report.delay(str(report_id))

    @staticmethod
    def _dispatch_delivery_task(delivery_id: uuid.UUID) -> None:
        from core.tasks import deliver_full_report

        deliver_full_report.delay(str(delivery_id))

    async def _dispatch_generation_or_record_failure(
        self, report_id: uuid.UUID
    ) -> None:
        try:
            self._dispatch_generation(report_id)
        except Exception:
            await self._reports.mark_prelaunch_full_dispatch_failed(
                report_id,
                now=datetime.now(timezone.utc),
            )
            raise
        await self._reports.mark_prelaunch_full_dispatched(
            report_id,
            now=datetime.now(timezone.utc),
        )

    async def request(
        self,
        *,
        user_id: uuid.UUID,
        actor: str,
        reason: str,
        request_key: str,
    ) -> PrelaunchFullReportRequestResult:
        self._require_mode()
        actor = actor.strip()
        reason = reason.strip()
        if not actor or len(actor) > 64:
            raise PrelaunchFullReportError("prelaunch_operator_invalid")
        if not 5 <= len(reason) <= 256:
            raise PrelaunchFullReportError("prelaunch_reason_invalid")
        if not _REQUEST_KEY_PATTERN.fullmatch(request_key):
            raise PrelaunchFullReportError("prelaunch_request_key_invalid")

        user = await self._users.get(user_id)
        if user is None:
            raise PrelaunchFullReportError("prelaunch_user_not_found")
        if not user.telegram_id or not telegram_user_is_allowed(user.telegram_id):
            raise PrelaunchFullReportError("prelaunch_owner_not_allowed")
        if not user.birth_date:
            raise PrelaunchFullReportError("prelaunch_birth_date_required")

        bundle = resolve_active_bundle("report.full")
        prompt_metadata = bundle.pin("report.full")
        prompt_metadata["requested_model"] = settings.deepseek_model
        report, created, operation_created = (
            await self._reports.create_or_get_prelaunch_full_request(
            user_id=user.id,
            token=ReportService.generate_token(),
            prompt_metadata=prompt_metadata,
            actor=actor,
            reason=reason,
            request_key=request_key,
            requested_at=datetime.now(timezone.utc),
            )
        )
        if report is None:
            raise PrelaunchFullReportError("prelaunch_user_not_found")

        if created:
            await self._dispatch_generation_or_record_failure(report.id)
            return PrelaunchFullReportRequestResult(
                report_id=report.id,
                status="generation_queued",
                generation_dispatched=True,
            )

        if (
            report.generation_state == ReportGenerationState.COMPLETED
            and report.artifact_bytes
        ):
            delivery_id = await self._deliveries.enqueue_manual(
                user.id,
                report.id,
                f"prelaunch-resend:{request_key}",
            )
            if delivery_id is None:
                raise PrelaunchFullReportError("prelaunch_delivery_unavailable")
            if operation_created:
                self._dispatch_delivery(delivery_id)
            return PrelaunchFullReportRequestResult(
                report_id=report.id,
                status="delivery_queued",
                delivery_dispatched=operation_created,
            )

        if report.generation_state == ReportGenerationState.FAILED_RETRYABLE:
            await self._dispatch_generation_or_record_failure(report.id)
            return PrelaunchFullReportRequestResult(
                report_id=report.id,
                status="generation_queued",
                generation_dispatched=True,
            )

        return PrelaunchFullReportRequestResult(
            report_id=report.id,
            status="generation_in_progress",
        )

    async def reconcile_stalled_generations(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> dict[str, int]:
        self._require_mode()
        report_ids = (
            await self._reports.recover_stalled_prelaunch_full_generations(
                now=now,
                pending_before=now - timedelta(minutes=2),
                running_before=now - timedelta(minutes=30),
                limit=limit,
            )
        )
        dispatched = 0
        errors = 0
        for report_id in report_ids:
            try:
                self._dispatch_generation(report_id)
                dispatched += 1
            except Exception:
                errors += 1
        return {
            "selected": len(report_ids),
            "dispatched": dispatched,
            "errors": errors,
        }

    async def claim_generation(self, report_id: uuid.UUID):
        self._require_mode()
        report = await self._reports.claim_prelaunch_full_generation(
            report_id, now=datetime.now(timezone.utc)
        )
        if report is None:
            return None
        user = await self._users.get(report.user_id)
        if (
            user is None
            or not user.telegram_id
            or not telegram_user_is_allowed(user.telegram_id)
            or not user.birth_date
        ):
            await self._reports.fail_prelaunch_full_generation(
                report_id,
                error_category="prelaunch_subject_ineligible",
                now=datetime.now(timezone.utc),
            )
            return None
        return (
            report,
            user,
            report.generation_state != ReportGenerationState.COMPLETED,
        )

    async def ensure_initial_delivery(self, report_id: uuid.UUID) -> uuid.UUID:
        self._require_mode()
        report = await self._reports.get(report_id)
        if (
            report is None
            or report.generation_state != ReportGenerationState.COMPLETED
            or not report.artifact_bytes
        ):
            raise PrelaunchFullReportError("prelaunch_delivery_unavailable")
        delivery_id = await self._deliveries.enqueue_manual(
            report.user_id,
            report.id,
            f"prelaunch-initial:{hashlib.sha256(str(report.id).encode()).hexdigest()}",
        )
        if delivery_id is None:
            raise PrelaunchFullReportError("prelaunch_delivery_unavailable")
        self._dispatch_delivery(delivery_id)
        return delivery_id

    async def complete_generation(
        self,
        report_id: uuid.UUID,
        *,
        matrix_data: dict[str, Any],
        ai_analysis: dict[str, Any],
        kitchen_analysis: dict[str, Any],
        generation_metadata: dict[str, Any],
        artifact: bytes,
    ):
        self._require_mode()
        report = await self._reports.complete_prelaunch_full_generation(
            report_id,
            matrix_data=matrix_data,
            ai_analysis=ai_analysis,
            kitchen_analysis=kitchen_analysis,
            generation_metadata=generation_metadata,
            artifact=artifact,
            now=datetime.now(timezone.utc),
        )
        if report is None:
            raise PrelaunchFullReportError("prelaunch_generation_conflict")
        await self.ensure_initial_delivery(report.id)
        return report

    async def fail_generation(self, report_id: uuid.UUID, code: str) -> None:
        await self._reports.fail_prelaunch_full_generation(
            report_id,
            error_category=code,
            now=datetime.now(timezone.utc),
        )
