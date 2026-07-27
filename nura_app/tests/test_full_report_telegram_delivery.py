"""Isolated application tests for durable full-report Telegram delivery."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from core.models import (
    FullReportTelegramDelivery,
    Order,
    PaymentAttempt,
    PaymentEvent,
    Report,
    ReportGenerationJob,
    ReportGenerationState,
    ReportPaymentState,
    ReportType,
    User,
)
from core.repositories.full_report_telegram_delivery import FullReportTelegramDeliveryRepository
from core.services.full_report_telegram_delivery import FullReportTelegramDeliveryService
from core.services.full_report_telegram_delivery import FullReportDeliveryReconciler
from core.services.telegram_report_delivery import (
    TelegramDeliveryError,
    TelegramDocument,
    TelegramDocumentAdapter,
)
from core.tasks import deliver_full_report


class FakeSender:
    def __init__(
        self,
        error: TelegramDeliveryError | None = None,
        *,
        file_id_error: TelegramDeliveryError | None = None,
        returned_file_id: str | None = "file-101",
    ) -> None:
        self.error = error
        self.file_id_error = file_id_error
        self.returned_file_id = returned_file_id
        self.calls: list[str] = []
        self.send_by_file_id_calls = 0
        self.send_by_artifact_calls = 0
        self.requested_file_id: str | None = None
        self.filename: str | None = None

    async def send_document_from_artifact(
        self, chat_id: int, content: bytes, filename: str, caption: str
    ) -> TelegramDocument:
        self.calls.append("artifact")
        self.send_by_artifact_calls += 1
        self.filename = filename
        if self.error:
            raise self.error
        return TelegramDocument(
            message_id=101,
            file_id=self.returned_file_id,
            transport="artifact_upload",
        )

    async def send_document_by_file_id(
        self, chat_id: int, file_id: str, caption: str
    ) -> TelegramDocument:
        self.calls.append("file_id")
        self.send_by_file_id_calls += 1
        self.requested_file_id = file_id
        if self.file_id_error:
            raise self.file_id_error
        return TelegramDocument(
            message_id=202, file_id=file_id, transport="file_id"
        )


class TransactionSpyRepository:
    def __init__(self, inner, calls: list[str], *, fail_complete: bool = False):
        self._inner = inner
        self._calls = calls
        self._fail_complete = fail_complete

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    async def claim(self, delivery_id: uuid.UUID, now: datetime) -> int | None:
        self._calls.append("claim_tx_open")
        attempt = await self._inner.claim(delivery_id, now)
        self._calls.append("claim_tx_committed")
        return attempt

    async def complete(
        self,
        delivery_id: uuid.UUID,
        attempt: int,
        *,
        message_id: int,
        file_id: str | None,
    ) -> bool:
        self._calls.append("terminal_tx_open")
        if self._fail_complete:
            self._calls.append("terminal_tx_rollback")
            raise RuntimeError("injected_terminal_commit_failure")
        completed = await self._inner.complete(
            delivery_id, attempt, message_id=message_id, file_id=file_id
        )
        self._calls.append("terminal_tx_committed")
        return completed

    async def fail(
        self,
        delivery_id: uuid.UUID,
        attempt: int,
        code: str,
        *,
        retryable: bool,
    ) -> bool:
        self._calls.append("failure_tx_open")
        failed = await self._inner.fail(
            delivery_id, attempt, code, retryable=retryable
        )
        self._calls.append("failure_tx_committed")
        return failed


class OrderedSender(FakeSender):
    def __init__(self, calls: list[str], error: TelegramDeliveryError | None = None):
        super().__init__(error)
        self._ordered_calls = calls

    async def send_document_from_artifact(
        self, chat_id: int, content: bytes, filename: str, caption: str
    ) -> TelegramDocument:
        self._ordered_calls.append("telegram_send_started")
        try:
            return await super().send_document_from_artifact(
                chat_id, content, filename, caption
            )
        finally:
            self._ordered_calls.append("telegram_send_finished")


@pytest.fixture
def db_factory(db_engine) -> async_sessionmaker:
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


async def _seed(factory: async_sessionmaker, *, order_status: str = "paid") -> tuple[uuid.UUID, uuid.UUID]:
    user_id, report_id = uuid.uuid4(), uuid.uuid4()
    artifact = b"%PDF-" + b"x" * 2048
    now = datetime.now(timezone.utc)
    async with factory() as session:
        user = User(
            id=user_id,
            telegram_id=int(user_id.int % 2_000_000_000),
            has_matrix=True,
        )
        report = Report(
            id=report_id, user_id=user_id, token=uuid.uuid4().hex,
            report_type=ReportType.FULL.value,
            payment_state=ReportPaymentState.PAYMENT_CONFIRMED,
            generation_state=ReportGenerationState.COMPLETED,
            artifact_bytes=artifact, artifact_sha256=hashlib.sha256(artifact).hexdigest(),
            artifact_size_bytes=len(artifact), artifact_mime_type="application/pdf",
        )
        order = Order(
            id=uuid.uuid4(), public_id=uuid.uuid4().hex, user_id=user_id,
            product_code="full_matrix", amount_kopecks=89_000, currency="RUB",
            status=order_status, report_id=report_id, idempotency_key=uuid.uuid4().hex,
            paid_at=now if order_status in {"paid", "refunded"} else None,
        )
        report.order_id = order.id
        session.add_all((user, report, order))
        await session.commit()
    return user_id, report_id


@pytest.mark.asyncio
async def test_automatic_delivery_is_idempotent_and_sends_canonical_artifact(db_factory) -> None:
    user_id, report_id = await _seed(db_factory)
    sender = FakeSender()
    service = FullReportTelegramDeliveryService(db_factory, sender)

    first = await service.enqueue_automatic(report_id)
    second = await service.enqueue_automatic(report_id)
    assert first == second
    await service.deliver(first)
    await service.deliver(first)

    assert sender.calls == ["artifact"]
    assert sender.filename == "NURA-full-matrix.pdf"
    async with db_factory() as session:
        delivery = await session.get(FullReportTelegramDelivery, first)
        report = await session.get(Report, report_id)
        assert delivery.status == "completed"
        assert (delivery.telegram_document_message_id, delivery.telegram_file_id) == (101, "file-101")
        assert report.generation_state == "completed"


@pytest.mark.asyncio
async def test_sqlite_model_rejects_non_hex_artifact_sha256(db_factory) -> None:
    user_id, report_id = await _seed(db_factory)
    async with db_factory() as session:
        report = await session.get(Report, report_id)
        order = (
            await session.execute(select(Order).where(Order.report_id == report_id))
        ).scalar_one()
        session.add(
            FullReportTelegramDelivery(
                id=uuid.uuid4(),
                report_id=report_id,
                order_id=order.id,
                user_id=user_id,
                delivery_reason="automatic",
                request_key="automatic",
                artifact_sha256="g" * 64,
                artifact_size_bytes=report.artifact_size_bytes,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_claim_stale_attempt_is_fenced_and_retryability_is_typed(db_factory) -> None:
    _user_id, report_id = await _seed(db_factory)
    repository = FullReportTelegramDeliveryRepository(db_factory)
    delivery = await FullReportTelegramDeliveryService(db_factory).enqueue_automatic(report_id)
    now = datetime.now(timezone.utc)
    assert await repository.claim(delivery, now) == 1
    assert await repository.claim(delivery, now) is None
    stale = now + timedelta(seconds=settings.telegram_delivery_claim_timeout_seconds + 1)
    assert await repository.claim(delivery, stale) == 2
    assert not await repository.complete(delivery, 1, message_id=1, file_id="stale")
    assert await repository.fail(delivery, 2, "telegram_network_failure", retryable=True)
    assert await repository.claim(delivery, stale) == 3
    assert await repository.fail(delivery, 3, "telegram_forbidden", retryable=False)
    assert await repository.claim(delivery, stale) is None


@pytest.mark.asyncio
async def test_retryable_sender_failure_does_not_mutate_report_or_order(db_factory) -> None:
    _user_id, report_id = await _seed(db_factory)
    sender = FakeSender(TelegramDeliveryError("telegram_network_failure", retryable=True))
    service = FullReportTelegramDeliveryService(db_factory, sender)
    delivery_id = await service.enqueue_automatic(report_id)
    with pytest.raises(TelegramDeliveryError):
        await service.deliver(delivery_id)
    async with db_factory() as session:
        delivery = await session.get(FullReportTelegramDelivery, delivery_id)
        report = await session.get(Report, report_id)
        order = (await session.execute(select(Order).where(Order.report_id == report_id))).scalar_one()
        assert delivery.status == "failed" and delivery.retryable
        assert report.generation_state == "completed" and order.status == "paid"


@pytest.mark.asyncio
async def test_telegram_send_is_between_committed_claim_and_terminal_transactions(
    db_factory,
) -> None:
    _user_id, report_id = await _seed(db_factory)
    calls: list[str] = []
    service = FullReportTelegramDeliveryService(db_factory, OrderedSender(calls))
    service._deliveries = TransactionSpyRepository(service._deliveries, calls)
    delivery_id = await service.enqueue_automatic(report_id)

    await service.deliver(delivery_id)

    assert calls == [
        "claim_tx_open",
        "claim_tx_committed",
        "telegram_send_started",
        "telegram_send_finished",
        "terminal_tx_open",
        "terminal_tx_committed",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("retryable", [True, False])
async def test_sender_failure_is_persisted_in_a_new_terminal_transaction(
    db_factory, retryable: bool
) -> None:
    _user_id, report_id = await _seed(db_factory)
    calls: list[str] = []
    error = TelegramDeliveryError("typed_failure", retryable=retryable)
    service = FullReportTelegramDeliveryService(
        db_factory, OrderedSender(calls, error)
    )
    service._deliveries = TransactionSpyRepository(service._deliveries, calls)
    delivery_id = await service.enqueue_automatic(report_id)

    with pytest.raises(TelegramDeliveryError):
        await service.deliver(delivery_id)

    assert calls == [
        "claim_tx_open",
        "claim_tx_committed",
        "telegram_send_started",
        "telegram_send_finished",
        "failure_tx_open",
        "failure_tx_committed",
    ]


@pytest.mark.asyncio
async def test_send_before_commit_crash_window_is_fenced_and_recoverable(
    db_factory,
) -> None:
    user_id, report_id = await _seed(db_factory)
    calls: list[str] = []
    sender = OrderedSender(calls)
    service = FullReportTelegramDeliveryService(db_factory, sender)
    repository = FullReportTelegramDeliveryRepository(db_factory)
    service._deliveries = TransactionSpyRepository(
        repository, calls, fail_complete=True
    )
    delivery_id = await service.enqueue_automatic(report_id)

    with (
        patch("core.services.report.ReportService.generate_pdf", new=AsyncMock()) as pdf,
        patch("core.services.matrix.MatrixService.calculate") as matrix,
        patch(
            "core.services.matrix_report_generator.DefaultMatrixReportGenerator.generate",
            new=AsyncMock(),
        ) as ai,
        patch(
            "core.services.full_matrix_checkout.FullMatrixCheckoutService.start_checkout",
            new=AsyncMock(),
        ) as payment,
        pytest.raises(RuntimeError, match="injected_terminal_commit_failure"),
    ):
        await service.deliver(delivery_id)

    pdf.assert_not_awaited()
    matrix.assert_not_called()
    ai.assert_not_awaited()
    payment.assert_not_awaited()
    async with db_factory() as session:
        delivery = await session.get(FullReportTelegramDelivery, delivery_id)
        report = await session.get(Report, report_id)
        order = (
            await session.execute(select(Order).where(Order.report_id == report_id))
        ).scalar_one()
        assert delivery.status == "sending" and delivery.attempt_count == 1
        assert report.generation_state == "completed"
        assert order.status == "paid"
        assert (await session.get(User, user_id)).has_matrix is True
        assert await session.scalar(select(func.count()).select_from(Report)) == 1
        assert await session.scalar(
            select(func.count()).select_from(ReportGenerationJob)
        ) == 0
        assert await session.scalar(select(func.count()).select_from(Order)) == 1
        assert await session.scalar(select(func.count()).select_from(PaymentAttempt)) == 0
        assert await session.scalar(select(func.count()).select_from(PaymentEvent)) == 0

    stale = datetime.now(timezone.utc) + timedelta(
        seconds=settings.telegram_delivery_claim_timeout_seconds + 1
    )
    second_attempt = await repository.claim(delivery_id, stale)
    assert second_attempt == 2
    recovery_sender = FakeSender(returned_file_id="recovered-file-id")
    recovery = FullReportTelegramDeliveryService(db_factory, recovery_sender)
    await recovery.deliver(delivery_id, claimed_attempt=second_attempt)
    assert recovery_sender.calls == ["artifact"]


async def _seed_canonical_file_id(
    factory: async_sessionmaker, report_id: uuid.UUID, file_id: str
) -> None:
    repository = FullReportTelegramDeliveryRepository(factory)
    async with factory() as session:
        report = await session.get(Report, report_id)
        order = (await session.execute(select(Order).where(Order.report_id == report_id))).scalar_one()
    row = await repository.get_or_create(
        report_id=report_id,
        order_id=order.id,
        user_id=report.user_id,
        reason="manual",
        request_key="canonical-seed",
        artifact_sha256=report.artifact_sha256,
        artifact_size_bytes=report.artifact_size_bytes,
        chat_id=123,
    )
    assert await repository.claim(row.id, datetime.now(timezone.utc)) == 1
    assert await repository.complete(row.id, 1, message_id=77, file_id=file_id)


@pytest.mark.asyncio
async def test_manual_resend_reuses_canonical_file_id_without_upload(db_factory) -> None:
    user_id, report_id = await _seed(db_factory)
    await _seed_canonical_file_id(db_factory, report_id, "old-file-id")
    sender = FakeSender()
    service = FullReportTelegramDeliveryService(db_factory, sender)
    delivery_id = await service.enqueue_manual(user_id, report_id, "new-request")
    await service.deliver(delivery_id)

    assert sender.calls == ["file_id"]
    assert sender.requested_file_id == "old-file-id"
    assert sender.send_by_artifact_calls == 0
    async with db_factory() as session:
        delivery = await session.get(FullReportTelegramDelivery, delivery_id)
        assert delivery.status == "completed"
        assert delivery.telegram_file_id == "old-file-id"
        assert delivery.telegram_document_message_id == 202


@pytest.mark.asyncio
async def test_invalid_file_id_falls_back_once_and_updates_canonical_id(db_factory) -> None:
    user_id, report_id = await _seed(db_factory)
    await _seed_canonical_file_id(db_factory, report_id, "old-file-id")
    sender = FakeSender(
        file_id_error=TelegramDeliveryError("invalid_file_id", retryable=False),
        returned_file_id="new-file-id",
    )
    service = FullReportTelegramDeliveryService(db_factory, sender)
    first_id = await service.enqueue_manual(user_id, report_id, "fallback-request")
    await service.deliver(first_id)
    assert sender.calls == ["file_id", "artifact"]

    second_sender = FakeSender()
    second_service = FullReportTelegramDeliveryService(db_factory, second_sender)
    second_id = await second_service.enqueue_manual(user_id, report_id, "next-request")
    await second_service.deliver(second_id)
    assert second_sender.calls == ["file_id"]
    assert second_sender.requested_file_id == "new-file-id"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    ["telegram_network_failure", "telegram_retry_after", "telegram_provider_failure"],
)
async def test_retryable_file_id_error_never_uploads_artifact(db_factory, code: str) -> None:
    user_id, report_id = await _seed(db_factory)
    await _seed_canonical_file_id(db_factory, report_id, "old-file-id")
    sender = FakeSender(
        file_id_error=TelegramDeliveryError(code, retryable=True)
    )
    service = FullReportTelegramDeliveryService(db_factory, sender)
    delivery_id = await service.enqueue_manual(user_id, report_id, code)
    with pytest.raises(TelegramDeliveryError):
        await service.deliver(delivery_id)
    assert sender.calls == ["file_id"]
    async with db_factory() as session:
        delivery = await session.get(FullReportTelegramDelivery, delivery_id)
        assert delivery.status == "failed" and delivery.retryable


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["telegram_forbidden", "telegram_chat_not_found"])
async def test_non_retryable_file_id_error_never_uploads_artifact(
    db_factory, code: str
) -> None:
    user_id, report_id = await _seed(db_factory)
    await _seed_canonical_file_id(db_factory, report_id, "old-file-id")
    sender = FakeSender(
        file_id_error=TelegramDeliveryError(code, retryable=False)
    )
    service = FullReportTelegramDeliveryService(db_factory, sender)
    delivery_id = await service.enqueue_manual(user_id, report_id, code)
    with pytest.raises(TelegramDeliveryError):
        await service.deliver(delivery_id)
    assert sender.calls == ["file_id"]
    async with db_factory() as session:
        delivery = await session.get(FullReportTelegramDelivery, delivery_id)
        assert delivery.status == "failed" and not delivery.retryable


@pytest.mark.asyncio
async def test_upload_success_without_returned_file_id_is_safe(db_factory) -> None:
    _user_id, report_id = await _seed(db_factory)
    sender = FakeSender(returned_file_id=None)
    service = FullReportTelegramDeliveryService(db_factory, sender)
    delivery_id = await service.enqueue_automatic(report_id)
    await service.deliver(delivery_id)
    async with db_factory() as session:
        delivery = await session.get(FullReportTelegramDelivery, delivery_id)
        assert delivery.status == "completed"
        assert delivery.telegram_file_id is None


@pytest.mark.asyncio
async def test_invalid_old_file_id_with_no_new_id_does_not_resurrect_old_id(
    db_factory,
) -> None:
    user_id, report_id = await _seed(db_factory)
    await _seed_canonical_file_id(db_factory, report_id, "old-file-id")
    fallback_sender = FakeSender(
        file_id_error=TelegramDeliveryError("invalid_file_id", retryable=False),
        returned_file_id=None,
    )
    service = FullReportTelegramDeliveryService(db_factory, fallback_sender)
    first_id = await service.enqueue_manual(user_id, report_id, "invalidate-old")
    await service.deliver(first_id)
    assert fallback_sender.calls == ["file_id", "artifact"]

    next_sender = FakeSender(returned_file_id=None)
    next_service = FullReportTelegramDeliveryService(db_factory, next_sender)
    next_id = await next_service.enqueue_manual(user_id, report_id, "after-null")
    await next_service.deliver(next_id)
    assert next_sender.calls == ["artifact"]


def test_production_mapper_distinguishes_invalid_file_id() -> None:
    error = TelegramBadRequest(
        MagicMock(), "Bad Request: wrong file identifier/HTTP URL specified"
    )
    invalid = TelegramDocumentAdapter._classify(error, file_id_transport=True)
    ordinary = TelegramDocumentAdapter._classify(error, file_id_transport=False)
    assert (invalid.code, invalid.retryable) == ("invalid_file_id", False)
    assert (ordinary.code, ordinary.retryable) == ("telegram_bad_request", False)
    chat_missing = TelegramDocumentAdapter._classify(
        TelegramBadRequest(MagicMock(), "Bad Request: chat not found"),
        file_id_transport=True,
    )
    assert (chat_missing.code, chat_missing.retryable) == (
        "telegram_chat_not_found",
        False,
    )


@pytest.mark.asyncio
async def test_manual_resend_is_idempotent_without_domain_side_effects(db_factory) -> None:
    user_id, report_id = await _seed(db_factory)
    await _seed_canonical_file_id(db_factory, report_id, "canonical-file-id")
    service = FullReportTelegramDeliveryService(db_factory, FakeSender())

    first = await service.enqueue_manual(user_id, report_id, "same-request")
    duplicate = await service.enqueue_manual(user_id, report_id, "same-request")
    assert first == duplicate
    await service.deliver(first)
    await service.deliver(duplicate)
    next_delivery = await service.enqueue_manual(user_id, report_id, "next-request")
    assert next_delivery != first

    async with db_factory() as session:
        counts = {}
        for model in (
            Report,
            ReportGenerationJob,
            Order,
            PaymentAttempt,
            PaymentEvent,
        ):
            counts[model.__name__] = int(
                (await session.execute(select(func.count()).select_from(model))).scalar_one()
            )
        deliveries = (
            await session.execute(
                select(FullReportTelegramDelivery).where(
                    FullReportTelegramDelivery.report_id == report_id,
                    FullReportTelegramDelivery.delivery_reason == "manual",
                )
            )
        ).scalars().all()
    assert counts == {
        "Report": 1,
        "ReportGenerationJob": 0,
        "Order": 1,
        "PaymentAttempt": 0,
        "PaymentEvent": 0,
    }
    assert {row.id for row in deliveries} == {
        first,
        next_delivery,
        next(row.id for row in deliveries if row.request_key == "canonical-seed"),
    }


@pytest.mark.asyncio
async def test_refund_and_missing_telegram_identity_block_send(db_factory) -> None:
    user_id, report_id = await _seed(db_factory)
    service = FullReportTelegramDeliveryService(db_factory, FakeSender())
    async with db_factory() as session:
        order = (
            await session.execute(select(Order).where(Order.report_id == report_id))
        ).scalar_one()
        order.status = "refunded"
        order.refunded_at = datetime.now(timezone.utc)
        await session.commit()
    assert await service.enqueue_manual(user_id, report_id, "refunded") is None

    async with db_factory() as session:
        order = (
            await session.execute(select(Order).where(Order.report_id == report_id))
        ).scalar_one()
        user = await session.get(User, user_id)
        order.status = "paid"
        order.refunded_at = None
        user.telegram_id = None
        await session.commit()
    delivery_id = await service.enqueue_automatic(report_id)
    assert delivery_id is not None
    await service.deliver(delivery_id)
    assert service._adapter.calls == []
    async with db_factory() as session:
        delivery = await session.get(FullReportTelegramDelivery, delivery_id)
        assert delivery.status == "canceled"


@pytest.mark.asyncio
async def test_refund_after_claim_is_rechecked_before_first_telegram_call(
    db_factory,
) -> None:
    _user_id, report_id = await _seed(db_factory)
    await _seed_canonical_file_id(db_factory, report_id, "canonical-file-id")
    sender = FakeSender()
    service = FullReportTelegramDeliveryService(db_factory, sender)
    delivery_id = await service.enqueue_automatic(report_id)
    original = service._deliveries.get_canonical_file_id

    async def refund_then_read(current_report_id: uuid.UUID) -> str | None:
        async with db_factory() as session:
            order = (
                await session.execute(
                    select(Order).where(Order.report_id == current_report_id)
                )
            ).scalar_one()
            order.status = "refunded"
            order.refunded_at = datetime.now(timezone.utc)
            await session.commit()
        return await original(current_report_id)

    service._deliveries.get_canonical_file_id = refund_then_read
    await service.deliver(delivery_id)

    assert sender.calls == []
    async with db_factory() as session:
        delivery = await session.get(FullReportTelegramDelivery, delivery_id)
        assert delivery.status == "canceled"


@pytest.mark.asyncio
async def test_refund_during_invalid_file_id_flow_blocks_artifact_fallback(
    db_factory,
) -> None:
    user_id, report_id = await _seed(db_factory)
    await _seed_canonical_file_id(db_factory, report_id, "old-file-id")

    class RefundDuringFallbackSender(FakeSender):
        async def send_document_by_file_id(
            self, chat_id: int, file_id: str, caption: str
        ) -> TelegramDocument:
            self.calls.append("file_id")
            self.send_by_file_id_calls += 1
            async with db_factory() as session:
                order = (
                    await session.execute(
                        select(Order).where(Order.report_id == report_id)
                    )
                ).scalar_one()
                order.status = "refunded"
                order.refunded_at = datetime.now(timezone.utc)
                await session.commit()
            raise TelegramDeliveryError("invalid_file_id", retryable=False)

    sender = RefundDuringFallbackSender()
    service = FullReportTelegramDeliveryService(db_factory, sender)
    delivery_id = await service.enqueue_manual(user_id, report_id, "refund-race")
    await service.deliver(delivery_id)

    assert sender.calls == ["file_id"]
    assert sender.send_by_artifact_calls == 0
    async with db_factory() as session:
        delivery = await session.get(FullReportTelegramDelivery, delivery_id)
        report = await session.get(Report, report_id)
        assert delivery.status == "canceled"
        assert report.generation_state == "completed"


@pytest.mark.asyncio
async def test_full_delivery_reconciliation_repairs_once_and_ignores_terminals(
    db_factory,
) -> None:
    _user_id, report_id = await _seed(db_factory)
    dispatched: list[tuple[uuid.UUID, int]] = []
    reconciler = FullReportDeliveryReconciler(
        db_factory, dispatch=lambda delivery_id, attempt: dispatched.append(
            (delivery_id, attempt)
        )
    )
    now = datetime.now(timezone.utc)

    first = await reconciler.reconcile_batch(now=now, limit=50)
    second = await reconciler.reconcile_batch(now=now, limit=50)

    assert (first.missing_created, first.claimed, first.dispatched) == (1, 1, 1)
    assert (second.missing_created, second.claimed, second.dispatched) == (0, 0, 0)
    assert len(dispatched) == 1
    delivery_id, attempt = dispatched[0]
    repository = FullReportTelegramDeliveryRepository(db_factory)
    assert await repository.complete(
        delivery_id, attempt, message_id=900, file_id="reconciled-file"
    )
    third = await reconciler.reconcile_batch(
        now=now + timedelta(hours=1), limit=50
    )
    assert third.claimed == 0 and third.dispatched == 0


@pytest.mark.asyncio
async def test_reconciliation_cancels_refunded_and_reclaims_retryable_only(
    db_factory,
) -> None:
    user_id, report_id = await _seed(db_factory)
    service = FullReportTelegramDeliveryService(db_factory, FakeSender())
    refunded_id = await service.enqueue_automatic(report_id)
    async with db_factory() as session:
        order = (
            await session.execute(select(Order).where(Order.report_id == report_id))
        ).scalar_one()
        order.status = "refunded"
        order.refunded_at = datetime.now(timezone.utc)
        await session.commit()
    dispatched: list[tuple[uuid.UUID, int]] = []
    reconciler = FullReportDeliveryReconciler(
        db_factory, dispatch=lambda delivery_id, attempt: dispatched.append(
            (delivery_id, attempt)
        )
    )
    result = await reconciler.reconcile_batch(
        now=datetime.now(timezone.utc), limit=50
    )
    assert result.canceled_ineligible == 1 and dispatched == []
    async with db_factory() as session:
        assert (await session.get(FullReportTelegramDelivery, refunded_id)).status == "canceled"

    _user2, report2 = await _seed(db_factory)
    retryable_id = await service.enqueue_automatic(report2)
    repository = FullReportTelegramDeliveryRepository(db_factory)
    attempt = await repository.claim(retryable_id, datetime.now(timezone.utc))
    assert await repository.fail(
        retryable_id, attempt, "network", retryable=True
    )
    result = await reconciler.reconcile_batch(
        now=datetime.now(timezone.utc) + timedelta(seconds=301), limit=50
    )
    assert result.claimed == 1 and dispatched[-1] == (retryable_id, 2)


def test_full_delivery_task_retries_typed_retryable_error_with_bounded_delay() -> None:
    error = TelegramDeliveryError(
        "telegram_retry_after", retryable=True, retry_after=9999
    )
    delivery_id = str(uuid.uuid4())
    with (
        patch.object(
            FullReportTelegramDeliveryService,
            "deliver",
            new=AsyncMock(side_effect=error),
        ),
        patch.object(
            deliver_full_report,
            "retry",
            return_value=RuntimeError("retry"),
        ) as retry,
        pytest.raises(RuntimeError, match="retry"),
    ):
        deliver_full_report.run(delivery_id, claimed_attempt=7)
    assert retry.call_args.kwargs["countdown"] == 300
    assert retry.call_args.kwargs["args"] == (delivery_id,)
    assert retry.call_args.kwargs["kwargs"] == {}


@pytest.mark.asyncio
async def test_reconciliation_respects_retryable_failure_recovery_window(
    db_factory,
) -> None:
    _user_id, report_id = await _seed(db_factory)
    service = FullReportTelegramDeliveryService(db_factory, FakeSender())
    delivery_id = await service.enqueue_automatic(report_id)
    repository = FullReportTelegramDeliveryRepository(db_factory)
    failed_at = datetime.now(timezone.utc)
    attempt = await repository.claim(delivery_id, failed_at)
    assert await repository.fail(
        delivery_id, attempt, "telegram_retry_after", retryable=True
    )
    dispatched: list[tuple[uuid.UUID, int]] = []
    reconciler = FullReportDeliveryReconciler(
        db_factory,
        dispatch=lambda item, current_attempt: dispatched.append(
            (item, current_attempt)
        ),
    )

    early = await reconciler.reconcile_batch(
        now=failed_at + timedelta(seconds=299), limit=10
    )
    due = await reconciler.reconcile_batch(
        now=failed_at + timedelta(seconds=301), limit=10
    )

    assert early.claimed == 0 and early.dispatched == 0
    assert due.claimed == 1 and due.dispatched == 1
    assert dispatched == [(delivery_id, 2)]


def test_full_delivery_task_does_not_retry_non_retryable_error() -> None:
    error = TelegramDeliveryError("telegram_forbidden", retryable=False)
    with (
        patch.object(
            FullReportTelegramDeliveryService,
            "deliver",
            new=AsyncMock(side_effect=error),
        ),
        patch.object(deliver_full_report, "retry") as retry,
    ):
        deliver_full_report.run(str(uuid.uuid4()))
    retry.assert_not_called()
