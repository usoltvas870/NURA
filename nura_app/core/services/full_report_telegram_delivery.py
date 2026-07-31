"""Durable Telegram delivery of persisted full-report text followed by its PDF."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from bot.utils.formatting import escape_telegram_html, split_telegram_html_message
from core.config import settings
from core.models import (
    FullReportTelegramDelivery,
    FullReportTelegramDeliveryState,
    Order,
    OrderStatus,
    Report,
    ReportGenerationState,
    ReportType,
    User,
)
from core.repositories.full_report_telegram_delivery import (
    PRELAUNCH_FULL_REPORT_DELIVERY_FORMAT,
    FullReportTelegramDeliveryRepository,
)
from core.repositories.report import PRELAUNCH_FULL_REPORT_AUDIT_KEY
from core.services.telegram_report_delivery import TelegramDeliveryError, TelegramDocumentAdapter
from core.services.telegram_sandbox import (
    SandboxTelegramRecipientBlocked,
    require_telegram_recipient_allowed,
)


def _require_sandbox_recipient(chat_id: int) -> None:
    try:
        require_telegram_recipient_allowed(chat_id)
    except SandboxTelegramRecipientBlocked as error:
        raise TelegramDeliveryError(error.code, retryable=False) from error


class FullReportTelegramDeliveryService:
    _TEXT_SECTIONS = (
        ("Главный архетип", "main_archetype"),
        ("Сильные стороны", "strengths"),
        ("Теневая сторона", "shadow_side"),
        ("Отношения и взаимодействие", "relationship_dynamics"),
        ("Деньги и реализация", "financial_scenario"),
        ("Повторяющиеся сценарии", "recurring_mistakes"),
        ("Внутренние конфликты", "internal_conflicts"),
        ("Жизненные циклы", "life_cycles"),
        ("Кармический хвост", "karmic_tail_analysis"),
        ("Родовые программы", "ancestral_programs"),
        ("Предназначение", "life_purpose"),
        ("Жизненные периоды и прогноз", "life_forecast"),
        ("Психологические блоки", "psychological_blocks"),
        ("Карта здоровья", "health_analysis"),
        ("Практические рекомендации на семь дней", "ai_recommendations"),
    )

    def __init__(self, session_factory, adapter: TelegramDocumentAdapter | None = None) -> None:
        self._session_factory = session_factory
        self._deliveries = FullReportTelegramDeliveryRepository(session_factory)
        self._adapter = adapter or TelegramDocumentAdapter()

    async def enqueue_automatic(self, report_id: uuid.UUID) -> uuid.UUID | None:
        existing = await self._deliveries.get_existing_for_report(report_id)
        if existing is not None:
            return existing.id
        subject = await self._subject(report_id)
        if subject is None:
            return None
        report, user, order = subject
        if order is None:
            return None
        if not self._valid_artifact(report, report.artifact_bytes):
            return None
        row = await self._deliveries.get_or_create(
            report_id=report.id, order_id=order.id, user_id=user.id,
            reason="automatic", request_key="automatic", artifact_sha256=report.artifact_sha256,
            artifact_size_bytes=report.artifact_size_bytes, chat_id=user.telegram_id,
        )
        return row.id

    async def enqueue_manual(self, user_id: uuid.UUID, report_id: uuid.UUID, request_key: str) -> uuid.UUID | None:
        if not request_key:
            return None
        subject = await self._subject(report_id, user_id)
        if subject is None:
            return None
        report, user, order = subject
        if not self._valid_artifact(report, report.artifact_bytes):
            return None
        prelaunch_delivery = order is None
        row = await self._deliveries.get_or_create(
            report_id=report.id,
            order_id=order.id if order is not None else None,
            user_id=user.id,
            reason="manual", request_key=hashlib.sha256(request_key.encode()).hexdigest(),
            artifact_sha256=report.artifact_sha256, artifact_size_bytes=report.artifact_size_bytes,
            chat_id=user.telegram_id,
            delivery_format_version=(
                PRELAUNCH_FULL_REPORT_DELIVERY_FORMAT
                if prelaunch_delivery
                else "full-text-pdf-v1"
            ),
        )
        return row.id

    async def deliver(self, delivery_id: uuid.UUID, claimed_attempt: int | None = None) -> None:
        attempt = claimed_attempt
        if attempt is None:
            attempt = await self._deliveries.claim(delivery_id, datetime.now(timezone.utc))
        elif not await self._deliveries.owns_attempt(delivery_id, attempt):
            return
        if attempt is None:
            return
        delivery = await self._deliveries.get(delivery_id)
        if delivery is None:
            return
        try:
            delivery = await self._ensure_text_snapshot(delivery, attempt)
            if delivery is None:
                return
            chunks = self._snapshot_chunks(delivery)
            message_ids = list(delivery.text_message_ids or [])
            if len(message_ids) > len(chunks):
                raise TelegramDeliveryError("invalid_full_report_text_snapshot", retryable=False)
            if delivery.text_status != "sent":
                for chunk in chunks[len(message_ids):]:
                    async with self._locked_subject(
                        delivery.report_id, delivery.user_id,
                        delivery_id=delivery_id, attempt=attempt,
                    ) as subject:
                        if subject is None or not subject[1].telegram_id:
                            await self._deliveries.cancel(delivery_id, attempt)
                            return
                        _require_sandbox_recipient(subject[1].telegram_id)
                        # A paid-order lock fences one external call at a time. This
                        # prevents post-refund sends without a multipart-wide DB lock.
                        message_ids.append(await self._adapter.send_message(subject[1].telegram_id, chunk))
                        if not await self._deliveries.save_text_progress(delivery_id, attempt, message_ids):
                            return
                if not await self._deliveries.mark_text_sent(delivery_id, attempt, message_ids):
                    return

            delivery = await self._deliveries.get(delivery_id)
            if delivery is None:
                return
            if delivery.document_status != "sent":
                async with self._locked_subject(
                    delivery.report_id, delivery.user_id,
                    delivery_id=delivery_id, attempt=attempt,
                ) as subject:
                    if subject is None or not subject[1].telegram_id:
                        await self._deliveries.cancel(delivery_id, attempt)
                        return
                    report, user, _order = subject
                    _require_sandbox_recipient(user.telegram_id)
                    caption = "<b>Полный отчёт NURA в PDF</b>\nСохрани его, чтобы возвращаться к разбору в удобный момент."
                    file_id = await self._deliveries.get_canonical_file_id(report.id)
                    if file_id:
                        try:
                            document = await self._adapter.send_document_by_file_id(user.telegram_id, file_id, caption)
                        except TelegramDeliveryError as error:
                            if error.code != "invalid_file_id":
                                raise
                            document = await self._upload_artifact(report, report.artifact_bytes, user.telegram_id, caption)
                    else:
                        document = await self._upload_artifact(report, report.artifact_bytes, user.telegram_id, caption)
                    if not await self._deliveries.mark_document_sent(
                        delivery_id, attempt, message_id=document.message_id, file_id=document.file_id
                    ):
                        return

            # Completion has its own final entitlement check. The external boundary
            # remains at-least-once: a crash after Telegram accepts a send but before
            # the adjacent progress commit can still duplicate that one message.
            async with self._locked_subject(
                delivery.report_id, delivery.user_id,
                delivery_id=delivery_id, attempt=attempt,
            ) as subject:
                if subject is None:
                    await self._deliveries.cancel(delivery_id, attempt)
                    return
                await self._deliveries.complete(delivery_id, attempt)
        except TelegramDeliveryError as error:
            await self._deliveries.fail(delivery_id, attempt, error.code, retryable=error.retryable)
            raise

    async def _ensure_text_snapshot(self, delivery, attempt: int):
        if delivery.text_chunks_snapshot is not None:
            return delivery
        subject = await self._subject(delivery.report_id, delivery.user_id)
        if subject is None:
            await self._deliveries.cancel(delivery.id, attempt)
            return None
        chunks = self.render_text_chunks(subject[0].ai_analysis)
        digest = hashlib.sha256(
            json.dumps(chunks, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return await self._deliveries.ensure_text_snapshot(
            delivery.id, attempt, chunks=chunks, payload_sha256=digest
        )

    @classmethod
    def render_text_chunks(cls, analysis: object) -> list[str]:
        if not isinstance(analysis, dict):
            raise TelegramDeliveryError("invalid_full_report_analysis", retryable=False)
        chunks = [
            "<b>Твой полный разбор готов</b>\n\n"
            "Ниже — сохранённый текст отчёта. После него придёт PDF-версия."
        ]
        for title, key in cls._TEXT_SECTIONS:
            value = analysis.get(key)
            if not isinstance(value, str) or not value.strip():
                raise TelegramDeliveryError("invalid_full_report_analysis", retryable=False)
            chunks.extend(split_telegram_html_message(
                f"<b>{title}</b>\n{escape_telegram_html(value.strip())}"
            ))
        return chunks

    @staticmethod
    def _snapshot_chunks(delivery) -> list[str]:
        chunks = delivery.text_chunks_snapshot
        if (
            not isinstance(chunks, list) or not chunks
            or any(not isinstance(chunk, str) or not chunk for chunk in chunks)
            or delivery.total_text_chunks != len(chunks)
            or not isinstance(delivery.text_payload_sha256, str)
        ):
            raise TelegramDeliveryError("invalid_full_report_text_snapshot", retryable=False)
        digest = hashlib.sha256(
            json.dumps(chunks, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if digest != delivery.text_payload_sha256:
            raise TelegramDeliveryError("invalid_full_report_text_snapshot", retryable=False)
        return chunks

    async def _upload_artifact(self, report: Report, artifact: bytes | None, chat_id: int, caption: str):
        if not self._valid_artifact(report, artifact):
            raise TelegramDeliveryError("invalid_full_report_artifact", retryable=False)
        return await self._adapter.send_document_from_artifact(chat_id, artifact, "NURA-full-matrix.pdf", caption)

    async def _subject(self, report_id: uuid.UUID, user_id: uuid.UUID | None = None):
        async with self._session_factory() as session:
            report = await session.get(Report, report_id)
            if report is None or report.report_type != ReportType.FULL.value or report.generation_state != ReportGenerationState.COMPLETED:
                return None
            if user_id is not None and report.user_id != user_id:
                return None
            user = await session.get(User, report.user_id)
            order = await session.get(Order, report.order_id) if report.order_id else None
            paid_subject = bool(
                user
                and user.account_status == "active"
                and user.has_matrix
                and order
                and order.status == OrderStatus.PAID
            )
            prelaunch_subject = self._is_prelaunch_subject(report, user, order)
            if not paid_subject and not prelaunch_subject:
                return None
            return report, user, order

    @asynccontextmanager
    async def _locked_subject(
        self,
        report_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        *,
        delivery_id: uuid.UUID | None = None,
        attempt: int | None = None,
    ) -> AsyncIterator[tuple[Report, User, Order | None] | None]:
        async with self._session_factory() as session:
            order_id = await session.scalar(select(Report.order_id).where(Report.id == report_id))
            order = None
            if order_id is not None:
                order = (
                    await session.execute(
                        select(Order)
                        .where(Order.id == order_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
            if delivery_id is not None:
                owns_attempt = await session.scalar(
                    select(FullReportTelegramDelivery.id).where(
                        FullReportTelegramDelivery.id == delivery_id,
                        FullReportTelegramDelivery.status
                        == FullReportTelegramDeliveryState.SENDING,
                        FullReportTelegramDelivery.attempt_count == attempt,
                    )
                )
                if owns_attempt is None:
                    yield None
                    return
            report = await session.get(Report, report_id)
            user = await session.get(User, report.user_id) if report else None
            paid_subject = bool(
                report
                and user
                and user.account_status == "active"
                and user.has_matrix
                and order
                and order.report_id == report.id
                and order.status == OrderStatus.PAID
            )
            prelaunch_subject = self._is_prelaunch_subject(report, user, order)
            eligible = bool(
                report
                and report.report_type == ReportType.FULL.value
                and report.generation_state == ReportGenerationState.COMPLETED
                and (user_id is None or report.user_id == user_id)
                and (paid_subject or prelaunch_subject)
            )
            yield (report, user, order) if eligible else None

    @staticmethod
    def _is_prelaunch_subject(
        report: Report | None,
        user: User | None,
        order: Order | None,
    ) -> bool:
        metadata = report.generation_metadata if report is not None else None
        return bool(
            settings.is_owner_prelaunch
            and not settings.payments_enabled
            and order is None
            and report is not None
            and report.report_type == ReportType.FULL.value
            and report.generation_state == ReportGenerationState.COMPLETED
            and isinstance(metadata, dict)
            and PRELAUNCH_FULL_REPORT_AUDIT_KEY in metadata
            and user is not None
            and user.account_status == "active"
            and user.telegram_id
            and user.telegram_id in settings.prelaunch_telegram_allowed_ids
        )

    @staticmethod
    def _valid_artifact(report: Report, artifact: bytes | None) -> bool:
        return bool(artifact and artifact.startswith(b"%PDF-") and len(artifact) == report.artifact_size_bytes and report.artifact_mime_type == "application/pdf" and report.artifact_sha256 == hashlib.sha256(artifact).hexdigest() and len(artifact) <= settings.telegram_document_max_bytes)


@dataclass(frozen=True)
class FullReportDeliveryReconciliationResult:
    missing_created: int = 0
    canceled_ineligible: int = 0
    claimed: int = 0
    dispatched: int = 0
    conflicts: int = 0
    errors: int = 0


class FullReportDeliveryReconciler:
    """Repair and dispatch durable full-report deliveries without Telegram I/O."""

    def __init__(self, session_factory, dispatch: Callable[[uuid.UUID, int], None] | None = None) -> None:
        self._service = FullReportTelegramDeliveryService(session_factory)
        self._deliveries = self._service._deliveries
        self._dispatch = dispatch or self._dispatch_task

    @staticmethod
    def _dispatch_task(delivery_id: uuid.UUID, attempt: int) -> None:
        from core.tasks import deliver_full_report
        deliver_full_report.delay(str(delivery_id), attempt)

    async def reconcile_batch(self, *, now: datetime, limit: int) -> FullReportDeliveryReconciliationResult:
        counters = {"missing_created": 0, "canceled_ineligible": 0, "claimed": 0, "dispatched": 0, "conflicts": 0, "errors": 0}
        for delivery_id in await self._deliveries.list_ineligible_active_ids(limit):
            counters["canceled_ineligible" if await self._deliveries.cancel(delivery_id) else "conflicts"] += 1
        for report_id in await self._deliveries.list_missing_automatic_report_ids(limit):
            try:
                delivery_id = await self._service.enqueue_automatic(report_id)
            except Exception:
                counters["errors"] += 1
                continue
            if delivery_id is not None:
                counters["missing_created"] += 1
        for delivery_id in await self._deliveries.list_reconcilable_ids(now, limit):
            attempt = await self._deliveries.claim(delivery_id, now)
            if attempt is None:
                counters["conflicts"] += 1
                continue
            counters["claimed"] += 1
            try:
                self._dispatch(delivery_id, attempt)
            except Exception:
                counters["errors"] += 1
            else:
                counters["dispatched"] += 1
        return FullReportDeliveryReconciliationResult(**counters)
