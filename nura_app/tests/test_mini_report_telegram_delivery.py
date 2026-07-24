import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from core.models import (
    MiniReportGeneration,
    Report,
    ReportType,
    TelegramReportDelivery,
    User,
)
from core.repositories.telegram_report_delivery import (
    TelegramReportDeliveryRepository,
)
from core.services.report import ReportService
from core.services.telegram_report_delivery import (
    MiniReportTelegramDeliveryService,
    TelegramDeliveryError,
    TelegramDocument,
    TelegramDocumentAdapter,
)


ANALYSIS = {
    "main_archetype": "<b>Сила</b>",
    "core_strength": "Внутренняя опора",
    "emotional_conflict": "Конфликт",
    "relationship_pattern": "Паттерн",
    "financial_block": "Блок",
}


class FakeAdapter:
    def __init__(
        self,
        *,
        fail_message_number: int | None = None,
        document_error: TelegramDeliveryError | None = None,
    ) -> None:
        self.messages: list[str] = []
        self.documents = 0
        self.fail_message_number = fail_message_number
        self.document_error = document_error

    async def send_message(self, chat_id: int, text: str) -> int:
        next_number = len(self.messages) + 1
        if next_number == self.fail_message_number:
            raise TelegramDeliveryError("telegram_network_failure", retryable=True)
        self.messages.append(text)
        return len(self.messages)

    async def send_document(
        self,
        chat_id: int,
        content: bytes,
        filename: str,
        caption: str,
    ) -> TelegramDocument:
        self.documents += 1
        if self.document_error is not None:
            raise self.document_error
        assert filename == "NURA-mini-report.pdf"
        assert str(chat_id) not in filename
        assert "01.01.2000" not in filename
        return TelegramDocument(message_id=100)


async def _seed_delivery_subject(
    factory: async_sessionmaker,
    *,
    analysis: dict | None = None,
    telegram_id: int | None = -1,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    user_id, report_id, generation_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    if telegram_id == -1:
        telegram_id = int(user_id.int % 2_000_000_000)
    async with factory() as session:
        session.add(User(id=user_id, telegram_id=telegram_id, username="name"))
        session.add(
            Report(
                id=report_id,
                user_id=user_id,
                report_type=ReportType.MINI.value,
                token=uuid.uuid4().hex,
                matrix_data={"center": 8},
                ai_analysis=analysis if analysis is not None else ANALYSIS,
            )
        )
        session.add(
            MiniReportGeneration(
                id=generation_id,
                user_id=user_id,
                fingerprint="f" * 64,
                generation_version="mini-v1",
                status="completed",
                report_id=report_id,
            )
        )
        await session.commit()
    return user_id, report_id, generation_id


@pytest.fixture
def db_factory(db_engine) -> async_sessionmaker:
    return async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.mark.asyncio
async def test_delivery_sends_saved_report_once(db_factory) -> None:
    user_id, report_id, generation_id = await _seed_delivery_subject(db_factory)
    adapter = FakeAdapter()
    service = MiniReportTelegramDeliveryService(db_factory, adapter)
    service._mini_pdf = AsyncMock(  # type: ignore[method-assign]
        return_value=b"%PDF-" + b"x" * 2000
    )

    with (
        patch(
            "core.services.telegram_report_delivery.ReportService.generate_pdf",
            new_callable=AsyncMock,
        ) as generate_pdf,
        patch(
            "core.services.telegram_report_delivery.MiniReportGenerationRepository.finalize_result",
            new_callable=AsyncMock,
        ) as finalize_result,
    ):
        await service.deliver(
            generation_id=generation_id,
            user_id=user_id,
            report_id=report_id,
        )
        await service.deliver(
            generation_id=generation_id,
            user_id=user_id,
            report_id=report_id,
        )

    assert adapter.documents == 1
    assert "&lt;b&gt;Сила&lt;/b&gt;" in "\n".join(adapter.messages)
    generate_pdf.assert_not_awaited()
    finalize_result.assert_not_awaited()
    async with db_factory() as session:
        delivery = (await session.execute(select(TelegramReportDelivery))).scalar_one()
        assert delivery.status == "delivered"
        assert delivery.text_status == "sent"
        assert delivery.document_status == "sent"
        assert delivery.document_message_id == 100
        assert delivery.text_message_ids == [1]


@pytest.mark.asyncio
async def test_partial_text_retry_resumes_after_confirmed_chunk(db_factory) -> None:
    long_analysis = {**ANALYSIS, "core_strength": "А" * 5000}
    user_id, report_id, generation_id = await _seed_delivery_subject(
        db_factory,
        analysis=long_analysis,
    )
    first_adapter = FakeAdapter(fail_message_number=2)
    first_service = MiniReportTelegramDeliveryService(db_factory, first_adapter)
    first_service._mini_pdf = AsyncMock(  # type: ignore[method-assign]
        return_value=b"%PDF-" + b"x" * 2000
    )

    with pytest.raises(TelegramDeliveryError, match="telegram_network_failure"):
        await first_service.deliver(
            generation_id=generation_id,
            user_id=user_id,
            report_id=report_id,
        )

    async with db_factory() as session:
        delivery = (await session.execute(select(TelegramReportDelivery))).scalar_one()
        assert delivery.status == "partially_delivered"
        assert delivery.text_status == "pending"
        assert delivery.text_message_ids == [1]

    retry_adapter = FakeAdapter()
    retry_service = MiniReportTelegramDeliveryService(db_factory, retry_adapter)
    retry_service._mini_pdf = AsyncMock(  # type: ignore[method-assign]
        return_value=b"%PDF-" + b"x" * 2000
    )
    await retry_service.deliver(
        generation_id=generation_id,
        user_id=user_id,
        report_id=report_id,
    )

    assert len(first_adapter.messages) == 1
    assert retry_adapter.messages
    assert first_adapter.messages[0] not in retry_adapter.messages
    assert retry_adapter.documents == 1


@pytest.mark.asyncio
async def test_pdf_failure_preserves_sent_text_and_retry_sends_only_pdf(
    db_factory,
) -> None:
    user_id, report_id, generation_id = await _seed_delivery_subject(db_factory)
    first_adapter = FakeAdapter(
        document_error=TelegramDeliveryError(
            "telegram_network_failure",
            retryable=True,
        )
    )
    first_service = MiniReportTelegramDeliveryService(db_factory, first_adapter)
    first_service._mini_pdf = AsyncMock(  # type: ignore[method-assign]
        return_value=b"%PDF-" + b"x" * 2000
    )

    with pytest.raises(TelegramDeliveryError):
        await first_service.deliver(
            generation_id=generation_id,
            user_id=user_id,
            report_id=report_id,
        )

    retry_adapter = FakeAdapter()
    retry_service = MiniReportTelegramDeliveryService(db_factory, retry_adapter)
    retry_service._mini_pdf = AsyncMock(  # type: ignore[method-assign]
        return_value=b"%PDF-" + b"x" * 2000
    )
    await retry_service.deliver(
        generation_id=generation_id,
        user_id=user_id,
        report_id=report_id,
    )

    assert len(first_adapter.messages) == 1
    assert retry_adapter.messages == []
    assert retry_adapter.documents == 1


@pytest.mark.asyncio
async def test_claim_is_atomic_and_stale_attempt_is_fenced(db_factory) -> None:
    user_id, report_id, generation_id = await _seed_delivery_subject(db_factory)
    repository = TelegramReportDeliveryRepository(db_factory)
    delivery = await repository.get_or_create(
        generation_id=generation_id,
        user_id=user_id,
        report_id=report_id,
    )
    now = datetime.now(timezone.utc)

    first, second = await __import__("asyncio").gather(
        repository.claim(delivery.id, now=now),
        repository.claim(delivery.id, now=now),
    )
    assert sorted(value for value in (first, second) if value is not None) == [1]

    stale_time = now + timedelta(
        seconds=settings.telegram_delivery_claim_timeout_seconds + 1
    )
    new_attempt = await repository.claim(delivery.id, now=stale_time)
    assert new_attempt == 2
    assert await repository.save_text_progress(delivery.id, 1, [10]) is False
    assert await repository.save_text_progress(delivery.id, 2, [20]) is True


@pytest.mark.asyncio
async def test_stale_takeover_uses_post_claim_progress_snapshot(db_factory) -> None:
    user_id, report_id, generation_id = await _seed_delivery_subject(db_factory)
    stale_claimed_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.telegram_delivery_claim_timeout_seconds + 1
    )
    delivery_id = uuid.uuid4()
    async with db_factory() as session:
        session.add(
            TelegramReportDelivery(
                id=delivery_id,
                user_id=user_id,
                report_id=report_id,
                mini_report_generation_id=generation_id,
                status="delivering",
                attempt_count=1,
                claimed_at=stale_claimed_at,
            )
        )
        await session.commit()

    adapter = FakeAdapter()
    service = MiniReportTelegramDeliveryService(db_factory, adapter)
    repository = service._deliveries
    real_claim = repository.claim

    async def save_receipt_then_claim(delivery_id: uuid.UUID, *, now: datetime):
        assert await repository.save_text_progress(delivery_id, 1, [777]) is True
        return await real_claim(delivery_id, now=now)

    service._deliveries.claim = save_receipt_then_claim  # type: ignore[method-assign]
    service._mini_pdf = AsyncMock(  # type: ignore[method-assign]
        return_value=b"%PDF-" + b"x" * 2000
    )
    await service.deliver(
        generation_id=generation_id,
        user_id=user_id,
        report_id=report_id,
    )

    assert adapter.messages == []
    assert adapter.documents == 1
    async with db_factory() as session:
        delivery = await session.get(TelegramReportDelivery, delivery_id)
        assert delivery.text_message_ids == [777]
        assert delivery.status == "delivered"


@pytest.mark.asyncio
async def test_non_retryable_failure_without_progress_is_terminal(
    db_factory,
) -> None:
    user_id, report_id, generation_id = await _seed_delivery_subject(
        db_factory,
        telegram_id=None,
    )
    service = MiniReportTelegramDeliveryService(db_factory, FakeAdapter())

    with pytest.raises(TelegramDeliveryError, match="delivery_subject_missing"):
        await service.deliver(
            generation_id=generation_id,
            user_id=user_id,
            report_id=report_id,
        )

    async with db_factory() as session:
        delivery = (await session.execute(select(TelegramReportDelivery))).scalar_one()
        assert delivery.status == "failed"

    repository = TelegramReportDeliveryRepository(db_factory)
    assert await repository.claim(
        delivery.id,
        now=datetime.now(timezone.utc),
    ) is None


@pytest.mark.asyncio
async def test_non_retryable_partial_failure_is_terminal_for_duplicate_task(
    db_factory,
) -> None:
    user_id, report_id, generation_id = await _seed_delivery_subject(db_factory)
    blocked_adapter = FakeAdapter(
        document_error=TelegramDeliveryError(
            "telegram_forbidden",
            retryable=False,
        )
    )
    service = MiniReportTelegramDeliveryService(db_factory, blocked_adapter)
    service._mini_pdf = AsyncMock(  # type: ignore[method-assign]
        return_value=b"%PDF-" + b"x" * 2000
    )
    with pytest.raises(TelegramDeliveryError, match="telegram_forbidden"):
        await service.deliver(
            generation_id=generation_id,
            user_id=user_id,
            report_id=report_id,
        )

    duplicate_adapter = FakeAdapter()
    duplicate_service = MiniReportTelegramDeliveryService(
        db_factory,
        duplicate_adapter,
    )
    await duplicate_service.deliver(
        generation_id=generation_id,
        user_id=user_id,
        report_id=report_id,
    )

    assert duplicate_adapter.messages == []
    assert duplicate_adapter.documents == 0
    async with db_factory() as session:
        delivery = (await session.execute(select(TelegramReportDelivery))).scalar_one()
        assert delivery.status == "partially_delivered"
        assert delivery.retryable is False


@pytest.mark.asyncio
async def test_subject_mismatch_and_missing_report_never_send(db_factory) -> None:
    user_id, report_id, generation_id = await _seed_delivery_subject(db_factory)
    adapter = FakeAdapter()
    service = MiniReportTelegramDeliveryService(db_factory, adapter)

    with pytest.raises(TelegramDeliveryError, match="delivery_subject_mismatch"):
        await service.deliver(
            generation_id=generation_id,
            user_id=uuid.uuid4(),
            report_id=report_id,
        )
    assert adapter.messages == []
    assert adapter.documents == 0

    async with db_factory() as session:
        report = await session.get(Report, report_id)
        await session.delete(report)
        await session.commit()
    with pytest.raises(TelegramDeliveryError, match="delivery_subject_missing"):
        await service.deliver(
            generation_id=generation_id,
            user_id=user_id,
            report_id=report_id,
        )
    assert adapter.documents == 0


@pytest.mark.asyncio
async def test_invalid_and_oversize_pdf_are_non_retryable_before_document_send(
    db_factory,
    monkeypatch,
) -> None:
    user_id, report_id, generation_id = await _seed_delivery_subject(
        db_factory,
        analysis={},
    )
    adapter = FakeAdapter()
    service = MiniReportTelegramDeliveryService(db_factory, adapter)

    with pytest.raises(TelegramDeliveryError) as invalid_error:
        await service.deliver(
            generation_id=generation_id,
            user_id=user_id,
            report_id=report_id,
        )
    assert invalid_error.value.retryable is False
    assert adapter.documents == 0

    oversize_user_id, oversize_report_id, oversize_generation_id = (
        await _seed_delivery_subject(db_factory)
    )
    async with db_factory() as session:
        report = await session.get(Report, oversize_report_id)
        report.ai_analysis = ANALYSIS
        await session.commit()
    monkeypatch.setattr(settings, "telegram_document_max_bytes", 1024)
    with patch.object(
        ReportService,
        "generate_pdf",
        new_callable=AsyncMock,
        return_value=b"%PDF-" + b"x" * 2000,
    ):
        with pytest.raises(TelegramDeliveryError) as oversize_error:
            await MiniReportTelegramDeliveryService(
                db_factory,
                adapter,
            ).deliver(
                generation_id=oversize_generation_id,
                user_id=oversize_user_id,
                report_id=oversize_report_id,
            )
    assert oversize_error.value.code == "mini_pdf_oversize"
    assert oversize_error.value.retryable is False
    assert adapter.documents == 0


def test_telegram_error_classification_uses_aiogram_types() -> None:
    method = MagicMock()
    retry_after = TelegramDocumentAdapter._classify(
        TelegramRetryAfter(method, "retry", retry_after=37)
    )
    network = TelegramDocumentAdapter._classify(
        TelegramNetworkError(method, "network")
    )
    forbidden = TelegramDocumentAdapter._classify(
        TelegramForbiddenError(method, "blocked")
    )
    bad_request = TelegramDocumentAdapter._classify(
        TelegramBadRequest(method, "bad")
    )

    assert (retry_after.retryable, retry_after.retry_after) == (True, 37)
    assert network.retryable is True
    assert forbidden.retryable is False
    assert bad_request.retryable is False


@pytest.mark.asyncio
async def test_actual_mini_pdf_is_valid_and_contains_cyrillic(db_factory) -> None:
    user_id, report_id, _generation_id = await _seed_delivery_subject(db_factory)
    async with db_factory() as session:
        report = await session.get(Report, report_id)
        pdf = await MiniReportTelegramDeliveryService._mini_pdf(report)

    assert user_id
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1024
