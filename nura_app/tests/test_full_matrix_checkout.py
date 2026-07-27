import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from core.models import Order, OrderStatus, PaymentAttempt, PaymentEvent, Report, ReportGenerationJob, User
from core.services.full_matrix_checkout import FullMatrixCheckoutService


@pytest.fixture(autouse=True)
def receipt_settings(monkeypatch):
    monkeypatch.setattr(settings, "yookassa_receipt_enabled", True)
    monkeypatch.setattr(settings, "yookassa_receipt_vat_code", "test_vat")
    monkeypatch.setattr(settings, "yookassa_receipt_payment_mode", "test_mode")
    monkeypatch.setattr(settings, "yookassa_receipt_payment_subject", "test_subject")


class FakeYooKassa:
    def __init__(self) -> None:
        self.created: list[tuple[str, dict]] = []
        self.remote: dict = {}
        self.get_calls = 0

    async def create_payment(self, *, idempotency_key: str, payload: dict) -> dict:
        self.created.append((idempotency_key, payload))
        number = len(self.created)
        self.remote = {
            "id": f"fake-yookassa-{number}",
            "status": "pending",
            "paid": False,
            "amount": {"value": "890.00", "currency": "RUB"},
            "metadata": payload["metadata"],
            "confirmation": {"confirmation_url": f"https://yookassa.test/pay/{number}"},
        }
        return self.remote

    async def get_payment(self, provider_payment_id: str) -> dict:
        self.get_calls += 1
        assert provider_payment_id == self.remote["id"]
        return self.remote


@pytest.mark.asyncio
async def test_verified_success_creates_one_report_and_dispatch_job(db_engine, test_user):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    provider = FakeYooKassa()
    service = FullMatrixCheckoutService(factory, provider)

    created = await service.create_or_get_order(user_id=test_user.id)
    assert created.status == "created"
    url = await service.start_checkout(created.checkout_token, "Buyer@Example.Test ")
    assert url == "https://yookassa.test/pay/1"
    assert provider.created[0][1]["amount"] == {"value": "890.00", "currency": "RUB"}
    assert provider.created[0][1]["save_payment_method"] is False
    assert provider.created[0][1]["receipt"] == {
        "customer": {"email": "buyer@example.test"},
        "items": [{
            "description": "Полная Матрица судьбы",
            "quantity": "1.00",
            "amount": {"value": "890.00", "currency": "RUB"},
            "vat_code": "test_vat",
            "payment_mode": "test_mode",
            "payment_subject": "test_subject",
        }],
    }

    provider.remote.update({"status": "succeeded", "paid": True})
    payload = {"event": "payment.succeeded", "object": {"id": "fake-yookassa-1"}}
    assert (await service.process_webhook(payload))["result"] == "activated"
    assert (await service.process_webhook(payload))["result"] == "already_processed"
    assert provider.get_calls == 1

    async with factory() as session:
        order = (await session.execute(select(Order))).scalar_one()
        attempt = (await session.execute(select(PaymentAttempt))).scalar_one()
        report = (await session.execute(select(Report))).scalar_one()
        job = (await session.execute(select(ReportGenerationJob))).scalar_one()
        assert order.status == OrderStatus.PAID
        assert (await session.get(User, test_user.id)).has_matrix is True
        assert order.report_id == report.id and report.order_id == order.id
        assert attempt.status == "succeeded"
        assert attempt.fiscal_email == "buyer@example.test"
        assert job.report_id == report.id
        assert len((await session.execute(select(PaymentEvent))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_client_cannot_tamper_price_and_canceled_attempt_can_retry(db_engine, test_user):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    provider = FakeYooKassa()
    service = FullMatrixCheckoutService(factory, provider)
    order = await service.create_or_get_order(user_id=test_user.id)
    await service.start_checkout(order.checkout_token, "buyer@example.test")
    provider.remote.update({"status": "canceled", "paid": False})
    await service.process_webhook({"event": "payment.canceled", "object": {"id": "fake-yookassa-1"}})
    assert await service.start_checkout(order.checkout_token, "buyer@example.test") == "https://yookassa.test/pay/2"
    async with factory() as session:
        attempts = (await session.execute(select(PaymentAttempt).order_by(PaymentAttempt.created_at))).scalars().all()
        assert len(attempts) == 2
        assert {attempt.amount_kopecks for attempt in attempts} == {89_000}
        assert all(attempt.currency == "RUB" for attempt in attempts)


@pytest.mark.asyncio
async def test_missing_receipt_configuration_or_invalid_email_does_not_call_provider(db_engine, test_user, monkeypatch):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    provider = FakeYooKassa()
    service = FullMatrixCheckoutService(factory, provider)
    order = await service.create_or_get_order(user_id=test_user.id)
    monkeypatch.setattr(settings, "yookassa_receipt_enabled", False)
    with pytest.raises(ValueError, match="yookassa_receipt_enabled_required"):
        await service.start_checkout(order.checkout_token, "buyer@example.test")
    assert provider.created == []
    monkeypatch.setattr(settings, "yookassa_receipt_enabled", True)
    with pytest.raises(ValueError, match="checkout_email_invalid"):
        await service.start_checkout(order.checkout_token, "not-an-email")
    assert provider.created == []
    async with factory() as session:
        persisted = (await session.execute(select(Order))).scalar_one()
        persisted.amount_kopecks = 1
        await session.commit()
    with pytest.raises(ValueError, match="receipt_item_mismatch"):
        await service.start_checkout(order.checkout_token, "buyer@example.test")
    assert provider.created == []


@pytest.mark.asyncio
async def test_pending_checkout_rejects_a_different_fiscal_email(db_engine, test_user):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    provider = FakeYooKassa()
    service = FullMatrixCheckoutService(factory, provider)
    order = await service.create_or_get_order(user_id=test_user.id)
    await service.start_checkout(order.checkout_token, "buyer@example.test")
    with pytest.raises(ValueError, match="checkout_email_conflict"):
        await service.start_checkout(order.checkout_token, "other@example.test")
    assert len(provider.created) == 1
