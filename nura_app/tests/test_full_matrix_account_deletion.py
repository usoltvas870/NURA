import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import (
    FullReportTelegramDelivery,
    Order,
    PaymentAttempt,
    PaymentEvent,
    Report,
    ReportGenerationJob,
    User,
)
from core.services.account_deletion import AccountDeletionService


async def _seed(
    factory: async_sessionmaker[AsyncSession], user: User
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, tuple[uuid.UUID, ...]]:
    now = datetime.now(timezone.utc)
    async with factory() as session:
        artifact = b"%PDF-" + b"d" * 2048
        report = Report(
            id=uuid.uuid4(),
            user_id=user.id,
            report_type="full",
            token="retention-report",
            matrix_data={"secret": "remove"},
            generation_state="completed",
            artifact_bytes=artifact,
            artifact_sha256=hashlib.sha256(artifact).hexdigest(),
            artifact_size_bytes=len(artifact),
            artifact_mime_type="application/pdf",
            artifact_completed_at=now,
        )
        session.add(report)
        await session.flush()
        order = Order(id=uuid.uuid4(), public_id="retention-order", user_id=user.id, telegram_id_snapshot=user.telegram_id, product_code="full_matrix", amount_kopecks=89_000, currency="RUB", status="paid", report_id=report.id, idempotency_key="retention-order-key", paid_at=now, checkout_token="remove-me", checkout_expires_at=now + timedelta(minutes=1), retain_until=now + timedelta(days=365 * 5))
        session.add(order)
        await session.flush()
        report.order_id = order.id
        attempt = PaymentAttempt(id=uuid.uuid4(), order_id=order.id, provider="yookassa", provider_payment_id="retention-payment", idempotency_key="retention-attempt-key", status="succeeded", amount_kopecks=89_000, currency="RUB", fiscal_email="receipt@example.test", confirmation_url="https://provider.test/pii", provider_metadata={"email": "remove", "product_code": "full_matrix"}, paid_at=now, retain_until=order.retain_until)
        session.add(attempt)
        await session.flush()
        order.active_payment_id = attempt.id
        event = PaymentEvent(id=uuid.uuid4(), provider="yookassa", provider_event_type="payment.succeeded", provider_object_id="retention-payment", provider_payment_id="retention-payment", order_id=order.id, payment_attempt_id=attempt.id, dedup_key="retention-event", provider_status="succeeded", verified=True, processing_status="processed", attempt_count=1, processed_at=now, retryable=False, payload_fingerprint="a" * 64, retain_until=order.retain_until)
        session.add(event)
        session.add(ReportGenerationJob(id=uuid.uuid4(), report_id=report.id))
        delivery_ids = tuple(uuid.uuid4() for _ in range(3))
        session.add_all(
            (
                FullReportTelegramDelivery(
                    id=delivery_ids[0],
                    report_id=report.id,
                    order_id=order.id,
                    user_id=user.id,
                    delivery_reason="automatic",
                    request_key="automatic",
                    artifact_sha256=report.artifact_sha256,
                    artifact_size_bytes=report.artifact_size_bytes,
                ),
                FullReportTelegramDelivery(
                    id=delivery_ids[1],
                    report_id=report.id,
                    order_id=order.id,
                    user_id=user.id,
                    delivery_reason="manual",
                    request_key="stale-manual",
                    status="sending",
                    attempt_count=1,
                    claimed_at=now - timedelta(hours=1),
                    artifact_sha256=report.artifact_sha256,
                    artifact_size_bytes=report.artifact_size_bytes,
                ),
                FullReportTelegramDelivery(
                    id=delivery_ids[2],
                    report_id=report.id,
                    order_id=order.id,
                    user_id=user.id,
                    delivery_reason="manual",
                    request_key="completed-manual",
                    status="completed",
                    retryable=False,
                    attempt_count=1,
                    sent_at=now,
                    telegram_document_message_id=987,
                    telegram_file_id="historical-file-id",
                    artifact_sha256=report.artifact_sha256,
                    artifact_size_bytes=report.artifact_size_bytes,
                ),
            )
        )
        await session.commit()
        return order.id, attempt.id, event.id, delivery_ids


@pytest.mark.asyncio
async def test_account_deletion_retains_anonymized_full_matrix_financial_rows(db_engine, test_user):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    order_id, attempt_id, event_id, delivery_ids = await _seed(factory, test_user)
    service = AccountDeletionService(factory)
    await service.delete(test_user.id)
    await service.delete(test_user.id)
    async with factory() as session:
        assert await session.get(User, test_user.id) is None
        assert (await session.execute(select(Report))).scalars().all() == []
        assert (await session.execute(select(ReportGenerationJob))).scalars().all() == []
        assert (await session.execute(select(FullReportTelegramDelivery))).scalars().all() == []
        stored_deliveries = [
            await session.get(FullReportTelegramDelivery, delivery_id)
            for delivery_id in delivery_ids
        ]
        assert all(delivery is None for delivery in stored_deliveries)
        order = await session.get(Order, order_id)
        attempt = await session.get(PaymentAttempt, attempt_id)
        event = await session.get(PaymentEvent, event_id)
        assert order and attempt and event
        assert order.user_id is None and order.report_id is None and order.checkout_token is None
        assert order.anonymized_at and order.retain_until and order.anonymization_reason == "account_deleted"
        assert order.customer_reference_hash != hashlib.sha256(str(test_user.id).encode()).hexdigest()
        assert attempt.confirmation_url is None and attempt.provider_metadata == {"product_code": "full_matrix"}
        assert attempt.fiscal_email == "receipt@example.test"
        assert attempt.anonymized_at and event.anonymized_at


@pytest.mark.asyncio
async def test_account_deletion_rolls_back_retention_mutations_on_failure(db_engine, test_user, monkeypatch):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    order_id, _, _, delivery_ids = await _seed(factory, test_user)
    original_delete = AsyncSession.delete

    async def fail_user_delete(self, instance):
        if isinstance(instance, User):
            raise RuntimeError("injected_delete_failure")
        await original_delete(self, instance)

    monkeypatch.setattr(AsyncSession, "delete", fail_user_delete)
    with pytest.raises(RuntimeError, match="injected_delete_failure"):
        await AccountDeletionService(factory).delete(test_user.id)
    async with factory() as session:
        assert await session.get(User, test_user.id) is not None
        order = await session.get(Order, order_id)
        assert order and order.user_id == test_user.id and order.anonymized_at is None
        stored_deliveries = [
            await session.get(FullReportTelegramDelivery, delivery_id)
            for delivery_id in delivery_ids
        ]
        assert all(delivery is not None for delivery in stored_deliveries)


@pytest.mark.asyncio
async def test_account_deletion_retry_clears_redis_after_post_commit_failure(
    db_engine, test_user
):
    class FailOnceRedis:
        def __init__(self) -> None:
            self.calls = 0
            self.deleted: tuple[str, ...] = ()

        async def delete(self, *keys: str) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("redis_temporarily_unavailable")
            self.deleted = keys

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    redis = FailOnceRedis()
    service = AccountDeletionService(factory, redis)
    with pytest.raises(RuntimeError, match="redis_temporarily_unavailable"):
        await service.delete(test_user.id)
    async with factory() as session:
        assert await session.get(User, test_user.id) is None
    await service.delete(test_user.id)
    assert redis.calls == 2 and len(redis.deleted) == 2
