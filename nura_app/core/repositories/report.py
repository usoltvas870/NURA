import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.config import settings
from core.models import (
    MiniReportGeneration,
    MiniReportGenerationState,
    Order,
    OrderStatus,
    Report,
    ReportGenerationState,
    ReportType,
    User,
)
from core.repositories.base import SQLAlchemyRepository


PRELAUNCH_FULL_REPORT_AUDIT_KEY = "prelaunch_operator_audit"


class ReportRepository(SQLAlchemyRepository[Report]):
    def __init__(self, session_factory: async_sessionmaker):
        super().__init__(session_factory, Report)

    async def get_by_token(self, token: str) -> Report | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Report).where(Report.token == token)
            )
            return result.scalar_one_or_none()

    async def get_by_user_id(self, user_id: uuid.UUID) -> list[Report]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Report).where(Report.user_id == user_id)
            )
            return list(result.scalars().all())

    async def list_completed_mini_for_user(
        self, user_id: uuid.UUID, *, offset: int, limit: int
    ) -> tuple[list[Report], int]:
        """Return only mini reports that have a completed durable generation."""
        filters = (
            Report.user_id == user_id,
            Report.report_type == ReportType.MINI.value,
            MiniReportGeneration.user_id == user_id,
            MiniReportGeneration.status == MiniReportGenerationState.COMPLETED,
            MiniReportGeneration.report_id == Report.id,
        )
        async with self._session_factory() as session:
            rows = await session.execute(
                select(Report)
                .join(MiniReportGeneration, MiniReportGeneration.report_id == Report.id)
                .where(*filters)
                .order_by(desc(Report.created_at))
                .offset(offset)
                .limit(limit)
            )
            total = await session.execute(
                select(func.count())
                .select_from(Report)
                .join(MiniReportGeneration, MiniReportGeneration.report_id == Report.id)
                .where(*filters)
            )
            return list(rows.scalars().all()), int(total.scalar_one())

    async def get_completed_mini_for_user(
        self, user_id: uuid.UUID, report_id: uuid.UUID
    ) -> Report | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Report)
                .join(MiniReportGeneration, MiniReportGeneration.report_id == Report.id)
                .where(
                    Report.id == report_id,
                    Report.user_id == user_id,
                    Report.report_type == ReportType.MINI.value,
                    MiniReportGeneration.user_id == user_id,
                    MiniReportGeneration.status == MiniReportGenerationState.COMPLETED,
                )
            )
            return result.scalar_one_or_none()

    async def store_mini_pdf_if_absent(
        self, report_id: uuid.UUID, user_id: uuid.UUID, artifact: bytes
    ) -> Report | None:
        """Persist one canonical mini PDF and return the winning report snapshot."""
        async with self._session_factory() as session:
            await session.execute(
                update(Report)
                .where(
                    Report.id == report_id,
                    Report.user_id == user_id,
                    Report.report_type == ReportType.MINI.value,
                    Report.artifact_bytes.is_(None),
                )
                .values(
                    artifact_bytes=artifact,
                    artifact_sha256=hashlib.sha256(artifact).hexdigest(),
                    artifact_size_bytes=len(artifact),
                    artifact_mime_type="application/pdf",
                    artifact_completed_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
            return await session.get(Report, report_id)

    async def list_completed_full_for_user(self, user_id: uuid.UUID) -> list[Report]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Report).outerjoin(Order, Report.order_id == Order.id).where(
                Report.user_id == user_id, Report.report_type == ReportType.FULL.value,
                Report.generation_state == ReportGenerationState.COMPLETED,
                Report.artifact_bytes.is_not(None),
                or_(
                    (Order.user_id == user_id) & (Order.status == OrderStatus.PAID),
                    Report.order_id.is_(None),
                ),
                )
            )
            reports = list(result.scalars().all())
            return [
                report
                for report in reports
                if report.order_id is not None
                or (
                    isinstance(report.generation_metadata, dict)
                    and PRELAUNCH_FULL_REPORT_AUDIT_KEY
                    in report.generation_metadata
                )
            ]

    async def get_completed_full_for_user(self, user_id: uuid.UUID, report_id: uuid.UUID) -> Report | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Report).outerjoin(Order, Report.order_id == Order.id).where(
                Report.id == report_id, Report.user_id == user_id, Report.report_type == ReportType.FULL.value,
                Report.generation_state == ReportGenerationState.COMPLETED, Report.artifact_bytes.is_not(None),
                or_(
                    (Order.user_id == user_id) & (Order.status == OrderStatus.PAID),
                    Report.order_id.is_(None),
                ),
                )
            )
            report = result.scalar_one_or_none()
            if (
                report is not None
                and report.order_id is None
                and (
                    not isinstance(report.generation_metadata, dict)
                    or PRELAUNCH_FULL_REPORT_AUDIT_KEY
                    not in report.generation_metadata
                )
            ):
                return None
            return report

    async def get_by_user_id_and_type(
        self, user_id: uuid.UUID, report_type: ReportType
    ) -> Report | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Report).where(
                    Report.user_id == user_id,
                    Report.report_type == report_type.value,
                ).order_by(desc(Report.created_at)).limit(1)
            )
            return result.scalar_one_or_none()

    async def create(
        self,
        user_id: uuid.UUID,
        report_type: ReportType,
        token: str,
        matrix_data: dict[str, Any] | None = None,
        ai_analysis: dict[str, Any] | None = None,
        kitchen_analysis: dict[str, Any] | None = None,
        generation_metadata: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
    ) -> Report:
        if expires_at is None:
            expires_at = datetime.now(timezone.utc) + timedelta(
                days=settings.report_token_ttl_days
            )
        report = Report(
            id=uuid.uuid4(),
            user_id=user_id,
            report_type=report_type.value,
            token=token,
            matrix_data=matrix_data,
            ai_analysis=ai_analysis,
            kitchen_analysis=kitchen_analysis,
            generation_metadata=generation_metadata,
            expires_at=expires_at,
        )
        return await self.add(report)

    async def create_or_get_prelaunch_full_request(
        self,
        *,
        user_id: uuid.UUID,
        token: str,
        prompt_metadata: dict[str, Any],
        actor: str,
        reason: str,
        request_key: str,
        requested_at: datetime,
    ) -> tuple[Report | None, bool, bool]:
        """Persist one audited owner-prelaunch generation request per user."""
        operation = {
            "action": "generate",
            "actor": actor,
            "reason": reason,
            "requested_at": requested_at.isoformat(),
            "request_key_sha256": hashlib.sha256(
                request_key.encode("utf-8")
            ).hexdigest(),
        }
        async with self._session_factory() as session:
            user = await session.scalar(
                select(User).where(User.id == user_id).with_for_update()
            )
            if user is None:
                return None, False, False
            existing_rows = (
                await session.execute(
                    select(Report)
                    .where(
                        Report.user_id == user_id,
                        Report.report_type == ReportType.FULL.value,
                    )
                    .order_by(desc(Report.created_at))
                    .with_for_update()
                )
            ).scalars().all()
            for existing in existing_rows:
                metadata = existing.generation_metadata
                reusable = existing.generation_state in {
                    ReportGenerationState.PENDING_DISPATCH,
                    ReportGenerationState.RUNNING,
                    ReportGenerationState.FAILED_RETRYABLE,
                } or (
                    existing.generation_state == ReportGenerationState.COMPLETED
                    and existing.artifact_bytes is not None
                )
                if reusable:
                    current_operation = {
                        **operation,
                        "action": (
                            "resend"
                            if existing.generation_state
                            == ReportGenerationState.COMPLETED
                            else "generation_request"
                        ),
                    }
                    updated_metadata = (
                        dict(metadata) if isinstance(metadata, dict) else {}
                    )
                    current_audit = updated_metadata.get(
                        PRELAUNCH_FULL_REPORT_AUDIT_KEY
                    )
                    if isinstance(current_audit, dict):
                        audit = dict(current_audit)
                        operations = [
                            dict(item)
                            for item in audit.get("operations", [])
                            if isinstance(item, dict)
                        ]
                        if not operations and all(
                            key in audit
                            for key in ("actor", "reason", "requested_at")
                        ):
                            operations.append(
                                {
                                    "actor": audit["actor"],
                                    "reason": audit["reason"],
                                    "requested_at": audit["requested_at"],
                                }
                            )
                    else:
                        audit = dict(current_operation)
                        operations = []
                    operation_created = not any(
                        item.get("request_key_sha256")
                        == current_operation["request_key_sha256"]
                        for item in operations
                    )
                    if operation_created:
                        operations.append(current_operation)
                    audit["operations"] = operations
                    updated_metadata[PRELAUNCH_FULL_REPORT_AUDIT_KEY] = audit
                    existing.generation_metadata = updated_metadata
                    await session.commit()
                    await session.refresh(existing)
                    session.expunge(existing)
                    return existing, False, operation_created

            metadata = dict(prompt_metadata)
            metadata[PRELAUNCH_FULL_REPORT_AUDIT_KEY] = {
                **operation,
                "operations": [operation],
            }
            report = Report(
                id=uuid.uuid4(),
                user_id=user_id,
                report_type=ReportType.FULL.value,
                token=token,
                generation_metadata=metadata,
                generation_state=ReportGenerationState.PENDING_DISPATCH,
                generation_enqueued_at=requested_at,
                expires_at=None,
            )
            session.add(report)
            await session.commit()
            await session.refresh(report)
            session.expunge(report)
            return report, True, True

    async def claim_prelaunch_full_generation(
        self, report_id: uuid.UUID, *, now: datetime
    ) -> Report | None:
        async with self._session_factory() as session:
            report = await session.get(Report, report_id, with_for_update=True)
            metadata = report.generation_metadata if report is not None else None
            if (
                report is None
                or report.report_type != ReportType.FULL.value
                or not isinstance(metadata, dict)
                or PRELAUNCH_FULL_REPORT_AUDIT_KEY not in metadata
            ):
                await session.rollback()
                return None
            if report.generation_state == ReportGenerationState.COMPLETED:
                await session.commit()
                await session.refresh(report)
                session.expunge(report)
                return report
            if report.generation_state not in {
                ReportGenerationState.PENDING_DISPATCH,
                ReportGenerationState.FAILED_RETRYABLE,
            }:
                await session.rollback()
                return None
            report.generation_state = ReportGenerationState.RUNNING
            report.generation_started_at = now
            report.generation_attempts += 1
            report.generation_failed_at = None
            report.generation_error_category = None
            await session.commit()
            await session.refresh(report)
            session.expunge(report)
            return report

    async def mark_prelaunch_full_dispatch_failed(
        self,
        report_id: uuid.UUID,
        *,
        now: datetime,
    ) -> None:
        async with self._session_factory() as session:
            report = await session.get(Report, report_id, with_for_update=True)
            metadata = report.generation_metadata if report is not None else None
            if (
                report is None
                or report.generation_state
                not in {
                    ReportGenerationState.PENDING_DISPATCH,
                    ReportGenerationState.FAILED_RETRYABLE,
                }
                or not isinstance(metadata, dict)
                or PRELAUNCH_FULL_REPORT_AUDIT_KEY not in metadata
            ):
                await session.rollback()
                return
            report.generation_state = ReportGenerationState.FAILED_RETRYABLE
            report.generation_failed_at = now
            report.generation_error_category = "prelaunch_dispatch_failed"
            await session.commit()

    async def mark_prelaunch_full_dispatched(
        self,
        report_id: uuid.UUID,
        *,
        now: datetime,
    ) -> None:
        async with self._session_factory() as session:
            report = await session.get(Report, report_id, with_for_update=True)
            if (
                report is None
                or report.generation_state
                not in {
                    ReportGenerationState.PENDING_DISPATCH,
                    ReportGenerationState.FAILED_RETRYABLE,
                }
            ):
                await session.rollback()
                return
            report.generation_state = ReportGenerationState.PENDING_DISPATCH
            report.generation_enqueued_at = now
            report.generation_failed_at = None
            report.generation_error_category = None
            await session.commit()

    async def complete_prelaunch_full_generation(
        self,
        report_id: uuid.UUID,
        *,
        matrix_data: dict[str, Any],
        ai_analysis: dict[str, Any],
        kitchen_analysis: dict[str, Any],
        generation_metadata: dict[str, Any],
        artifact: bytes,
        now: datetime,
    ) -> Report | None:
        async with self._session_factory() as session:
            report = await session.get(Report, report_id, with_for_update=True)
            existing_metadata = (
                report.generation_metadata if report is not None else None
            )
            audit = (
                existing_metadata.get(PRELAUNCH_FULL_REPORT_AUDIT_KEY)
                if isinstance(existing_metadata, dict)
                else None
            )
            if (
                report is None
                or report.generation_state != ReportGenerationState.RUNNING
                or not isinstance(audit, dict)
            ):
                await session.rollback()
                return None
            final_metadata = dict(generation_metadata)
            final_metadata[PRELAUNCH_FULL_REPORT_AUDIT_KEY] = audit
            report.matrix_data = matrix_data
            report.ai_analysis = ai_analysis
            report.kitchen_analysis = kitchen_analysis
            report.generation_metadata = final_metadata
            report.artifact_bytes = artifact
            report.artifact_sha256 = hashlib.sha256(artifact).hexdigest()
            report.artifact_size_bytes = len(artifact)
            report.artifact_mime_type = "application/pdf"
            report.artifact_completed_at = now
            report.generation_state = ReportGenerationState.COMPLETED
            report.generated_at = now
            report.generation_error_category = None
            await session.commit()
            await session.refresh(report)
            session.expunge(report)
            return report

    async def fail_prelaunch_full_generation(
        self,
        report_id: uuid.UUID,
        *,
        error_category: str,
        now: datetime,
    ) -> None:
        async with self._session_factory() as session:
            report = await session.get(Report, report_id, with_for_update=True)
            if (
                report is None
                or report.generation_state != ReportGenerationState.RUNNING
            ):
                await session.rollback()
                return
            report.generation_state = ReportGenerationState.FAILED_RETRYABLE
            report.generation_failed_at = now
            report.generation_error_category = error_category[:128]
            await session.commit()

    async def recover_stalled_prelaunch_full_generations(
        self,
        *,
        now: datetime,
        pending_before: datetime,
        running_before: datetime,
        limit: int,
    ) -> list[uuid.UUID]:
        """Atomically make stalled audited prelaunch reports dispatchable."""
        async with self._session_factory() as session:
            candidates = (
                await session.execute(
                    select(Report)
                    .where(
                        Report.report_type == ReportType.FULL.value,
                        Report.order_id.is_(None),
                        or_(
                            (
                                Report.generation_state
                                == ReportGenerationState.PENDING_DISPATCH
                            )
                            & or_(
                                Report.generation_enqueued_at.is_(None),
                                Report.generation_enqueued_at <= pending_before,
                            ),
                            (
                                Report.generation_state
                                == ReportGenerationState.RUNNING
                            )
                            & or_(
                                Report.generation_started_at.is_(None),
                                Report.generation_started_at <= running_before,
                            ),
                        ),
                    )
                    .order_by(Report.created_at)
                    .limit(min(limit * 4, 400))
                    .with_for_update(skip_locked=True)
                )
            ).scalars().all()
            recovered: list[uuid.UUID] = []
            for report in candidates:
                metadata = report.generation_metadata
                if (
                    not isinstance(metadata, dict)
                    or PRELAUNCH_FULL_REPORT_AUDIT_KEY not in metadata
                ):
                    continue
                report.generation_state = ReportGenerationState.PENDING_DISPATCH
                report.generation_enqueued_at = now
                report.generation_started_at = None
                report.generation_error_category = None
                recovered.append(report.id)
                if len(recovered) >= limit:
                    break
            await session.commit()
            return recovered

    async def delete_by_user_id(self, user_id: uuid.UUID) -> None:
        async with self._session_factory() as session:
            await session.execute(delete(Report).where(Report.user_id == user_id))
            await session.commit()

    @staticmethod
    def is_expired(report: Report, now: datetime | None = None) -> bool:
        if now is None:
            now = datetime.now(timezone.utc)
        expires_at = report.expires_at
        if expires_at is None:
            return False
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at < now
