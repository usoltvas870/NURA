"""Disposable PostgreSQL proof for pre-provider PaymentEvent claims.

Run only against a throw-away database that has already been upgraded to the
current Alembic head.  The harness deliberately uses eight independently
scheduled webhook calls and a local fake provider; it never contacts YooKassa.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import psycopg2
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
NURA_APP_ROOT = REPO_ROOT / "nura_app"
if str(NURA_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(NURA_APP_ROOT))

from core.models import Order, PaymentAttempt, PaymentEvent, Report, ReportGenerationJob, User  # noqa: E402
from core.config import settings  # noqa: E402
from core.services.full_matrix_checkout import FullMatrixCheckoutService, _now  # noqa: E402
from core.services.account_deletion import AccountDeletionService  # noqa: E402


def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+asyncpg://"):
        return url
    raise ValueError("DATABASE_URL must use PostgreSQL")


_URL = ""


def _probe_disposable_database() -> None:
    """Fail early if the supplied disposable PostgreSQL database is unreachable."""
    with psycopg2.connect(_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")


class FakeProvider:
    def __init__(self, remote: dict, timeout: bool = False) -> None:
        self.remote = remote
        self.timeout = timeout
        self.lookups = 0
        self.creates = 0

    async def create_payment(self, *, idempotency_key: str, payload: dict) -> dict:
        self.creates += 1
        await asyncio.sleep(0.03)
        return {
            **self.remote,
            "id": "race-created-payment",
            "confirmation": {"confirmation_url": "https://provider.test/race"},
            "metadata": payload["metadata"],
        }

    async def get_payment(self, provider_payment_id: str) -> dict:
        assert provider_payment_id == self.remote["id"]
        self.lookups += 1
        await asyncio.sleep(0.03)
        if self.timeout:
            raise TimeoutError("fake provider timeout")
        return self.remote


async def _seed(factory: async_sessionmaker[AsyncSession], provider: FakeProvider) -> tuple[FullMatrixCheckoutService, dict]:
    async with factory() as session:
        user = User(id=uuid.uuid4(), telegram_id=987654321, username="race", first_name="Race", birth_date="01.01.2000")
        session.add(user)
        await session.commit()
    service = FullMatrixCheckoutService(factory, provider)
    await service.create_or_get_order(user_id=user.id)
    # Create the attempt without a real provider call.
    async with factory() as session:
        order = (await session.execute(select(Order))).scalar_one()
        attempt = PaymentAttempt(id=uuid.uuid4(), order_id=order.id, provider="yookassa", provider_payment_id=provider.remote["id"], idempotency_key=uuid.uuid4().hex, status="pending", amount_kopecks=89_000, currency="RUB", fiscal_email="race@example.test", provider_metadata={"product_code": "full_matrix", "order_id": order.public_id}, test_mode=False)
        session.add(attempt)
        await session.flush()
        order.active_payment_id = attempt.id
        order.status = "pending"
        await session.commit()
        body = {"event": "payment.succeeded", "object": {"id": provider.remote["id"], "status": "succeeded"}}
        provider.remote["metadata"] = {"product_code": "full_matrix", "order_id": order.public_id}
        return service, body


async def _reset(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        await session.execute(text("TRUNCATE payment_events, report_generation_jobs, reports, payment_attempts, orders, users CASCADE"))
        await session.commit()


async def _wave(service: FullMatrixCheckoutService, body: dict) -> list[dict]:
    barrier = asyncio.Barrier(8)

    async def worker() -> dict:
        await barrier.wait()
        return await service.process_webhook(body)

    return await asyncio.gather(*(worker() for _ in range(8)))


async def _order_and_attempt_race(factory: async_sessionmaker[AsyncSession]) -> list[tuple[str, bool]]:
    await _reset(factory)
    async with factory() as session:
        user = User(id=uuid.uuid4(), telegram_id=444444444, username="order-race", first_name="Race", birth_date="01.01.2000")
        session.add(user)
        await session.commit()
    provider = FakeProvider({"id": "unused", "status": "pending", "paid": False, "amount": {"value": "890.00", "currency": "RUB"}, "test": False})
    service = FullMatrixCheckoutService(factory, provider)
    barrier = asyncio.Barrier(8)

    async def order_worker():
        await barrier.wait()
        return await service.create_or_get_order(user_id=user.id)

    orders = await asyncio.gather(*(order_worker() for _ in range(8)))
    token = orders[0].checkout_token
    assert token is not None
    barrier = asyncio.Barrier(8)

    async def attempt_worker() -> str:
        await barrier.wait()
        return await service.start_checkout(token, "race@example.test")

    urls = await asyncio.gather(*(attempt_worker() for _ in range(8)))
    async with factory() as session:
        rows = (await session.execute(select(Order))).scalars().all()
        attempts = (await session.execute(select(PaymentAttempt))).scalars().all()
        paid = rows[0]
        paid.status = "paid"
        paid.paid_at = _now()
        await session.commit()
    repeat = await service.create_or_get_order(user_id=user.id)
    return [
        ("order race has one canonical order", len(rows) == 1 and len({x.checkout_token for x in orders}) == 1),
        ("attempt race has one provider create", len(attempts) == 1 and provider.creates == 1 and len(set(urls)) == 1),
        ("paid order is not duplicated", repeat.status == "paid" and repeat.checkout_token is None),
    ]


async def _counts(factory: async_sessionmaker[AsyncSession]) -> tuple[Order, PaymentAttempt, PaymentEvent, int, int]:
    async with factory() as session:
        return (
            (await session.execute(select(Order))).scalar_one(),
            (await session.execute(select(PaymentAttempt))).scalar_one(),
            (await session.execute(select(PaymentEvent))).scalar_one(),
            int((await session.execute(select(func.count()).select_from(Report))).scalar_one()),
            int((await session.execute(select(func.count()).select_from(ReportGenerationJob))).scalar_one()),
        )


async def _retention_proof(factory: async_sessionmaker[AsyncSession]) -> tuple[str, bool]:
    await _reset(factory)
    now = _now()
    async with factory() as session:
        user = User(id=uuid.uuid4(), telegram_id=555555555, username="retention", first_name="Retention", birth_date="01.01.2000", has_matrix=True)
        session.add(user)
        await session.flush()
        report = Report(id=uuid.uuid4(), user_id=user.id, report_type="full", token="retention-proof", matrix_data={"remove": True})
        session.add(report)
        await session.flush()
        order = Order(id=uuid.uuid4(), public_id="retention-proof-order", user_id=user.id, telegram_id_snapshot=user.telegram_id, product_code="full_matrix", amount_kopecks=89_000, currency="RUB", status="paid", report_id=report.id, idempotency_key="retention-proof-key", paid_at=now, checkout_token="remove", retain_until=now + timedelta(days=365 * 5))
        session.add(order)
        await session.flush()
        report.order_id = order.id
        attempt = PaymentAttempt(id=uuid.uuid4(), order_id=order.id, provider="yookassa", provider_payment_id="retention-proof-payment", idempotency_key="retention-proof-attempt", status="succeeded", amount_kopecks=89_000, currency="RUB", fiscal_email="receipt@example.test", confirmation_url="https://provider.test/remove", provider_metadata={"email": "remove", "product_code": "full_matrix"}, paid_at=now, retain_until=order.retain_until)
        session.add(attempt)
        await session.flush()
        order.active_payment_id = attempt.id
        event = PaymentEvent(id=uuid.uuid4(), provider="yookassa", provider_event_type="payment.succeeded", provider_object_id="retention-proof-payment", provider_payment_id="retention-proof-payment", order_id=order.id, payment_attempt_id=attempt.id, dedup_key="retention-proof-event", provider_status="succeeded", verified=True, processing_status="processed", attempt_count=1, processed_at=now, retryable=False, payload_fingerprint="b" * 64, retain_until=order.retain_until)
        session.add(event)
        session.add(ReportGenerationJob(id=uuid.uuid4(), report_id=report.id))
        await session.commit()
        user_id, order_id, attempt_id, event_id = user.id, order.id, attempt.id, event.id
    await AccountDeletionService(factory).delete(user_id)
    await AccountDeletionService(factory).delete(user_id)
    async with factory() as session:
        order = await session.get(Order, order_id)
        attempt = await session.get(PaymentAttempt, attempt_id)
        event = await session.get(PaymentEvent, event_id)
        passed = (
            await session.get(User, user_id) is None
            and order is not None and order.user_id is None and order.report_id is None
            and order.customer_reference_hash is not None and order.anonymized_at is not None
            and attempt is not None and attempt.confirmation_url is None
            and attempt.provider_metadata == {"product_code": "full_matrix"}
            and attempt.fiscal_email == "receipt@example.test"
            and event is not None and event.anonymized_at is not None
        )
    return "account deletion retains anonymized financial records", passed


async def main() -> bool:
    global _URL
    _URL = os.environ.get("DATABASE_URL", "")
    if not _URL:
        print("FATAL: DATABASE_URL is required")
        return False
    _probe_disposable_database()
    settings.yookassa_receipt_enabled = True
    settings.yookassa_receipt_vat_code = "test_vat"
    settings.yookassa_receipt_payment_mode = "test_mode"
    settings.yookassa_receipt_payment_subject = "test_subject"
    engine = create_async_engine(_async_url(_URL), pool_size=12, max_overflow=4)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        await _reset(factory)
        checks = await _order_and_attempt_race(factory)
        checks.append(await _retention_proof(factory))
        await _reset(factory)
        remote = {"id": "race-payment", "status": "succeeded", "paid": True, "amount": {"value": "890.00", "currency": "RUB"}, "test": False}
        provider = FakeProvider(remote)
        service, body = await _seed(factory, provider)
        results = await _wave(service, body)
        order, attempt, event, reports, jobs = await _counts(factory)
        checks += [
            ("concurrent lookup exactly once", provider.lookups == 1),
            ("one event / attempt one", event.attempt_count == 1),
            ("one paid transition", order.status == "paid" and attempt.status == "succeeded"),
            ("one report and job", reports == 1 and jobs == 1),
            ("processed event", event.processing_status == "processed" and event.processed_at is not None),
            ("non-winners are safe", all(item["result"] in {"activated", "in_progress", "already_processed"} for item in results)),
        ]

        await _reset(factory)
        provider = FakeProvider(remote.copy())
        service, body = await _seed(factory, provider)
        await service._intake_event(provider.remote["id"], body["event"], body)
        fresh_results = await _wave(service, body)
        checks.append(("fresh processing no lookup", provider.lookups == 0 and {x["result"] for x in fresh_results} == {"in_progress"}))

        await _reset(factory)
        provider = FakeProvider(remote.copy(), timeout=True)
        service, body = await _seed(factory, provider)
        await _wave(service, body)
        _, _, failed, reports, jobs = await _counts(factory)
        checks.append(("retryable failure retained", provider.lookups == 1 and failed.processing_status == "failed" and failed.retryable and reports == jobs == 0))
        provider.timeout = False
        second = await _wave(service, body)
        order, _, retry_event, reports, jobs = await _counts(factory)
        checks.append(("retry claim activates once", provider.lookups == 2 and retry_event.attempt_count == 2 and order.status == "paid" and reports == jobs == 1 and any(x["result"] == "activated" for x in second)))

        await _reset(factory)
        wrong = remote.copy()
        wrong["amount"] = {"value": "1.00", "currency": "RUB"}
        provider = FakeProvider(wrong)
        service, body = await _seed(factory, provider)
        await _wave(service, body)
        await _wave(service, body)
        order, _, failed, reports, jobs = await _counts(factory)
        checks.append(("terminal verification failure blocks replay", provider.lookups == 1 and not failed.retryable and order.status == "pending" and reports == jobs == 0))

        await _reset(factory)
        provider = FakeProvider(remote.copy())
        service, body = await _seed(factory, provider)
        claim = await service._intake_event(provider.remote["id"], body["event"], body)
        async with factory() as session:
            event = await session.get(PaymentEvent, claim.event_id)
            assert event is not None
            event.claimed_at = _now() - timedelta(seconds=301)
            await session.commit()
        recovered = await service._intake_event(provider.remote["id"], body["event"], body)
        stale = await service._complete_claimed_event(claim, provider.remote)
        completed = await service._complete_claimed_event(recovered, provider.remote)
        order, _, event, reports, jobs = await _counts(factory)
        checks.append(("stale fencing", stale["result"] == "fenced" and completed["result"] == "activated" and event.attempt_count == 2 and order.status == "paid" and reports == jobs == 1))

        mismatch = dict(body)
        mismatch["object"] = {"id": provider.remote["id"], "status": "canceled"}
        result = await service.process_webhook(mismatch)
        checks.append(("payload mismatch has no lookup", result["result"] == "payload_mismatch" and provider.lookups == 0))
        for label, passed in checks:
            print(f"[{'PASS' if passed else 'FAIL'}] {label}")
        return all(passed for _, passed in checks)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
