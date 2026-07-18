from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.routes import web
from core.config import settings
from core.models import (
    Base,
    Payment,
    PromoReservation,
    Report,
    ReportGenerationJob,
    ReportGenerationJobState,
    ReportGenerationState,
    ReportPaymentState,
    User,
)
from core.services.payment import CheckoutAmount, PaymentService
from core.services.report_lifecycle import ReportLifecycleCoordinator


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'matrix-lifecycle.db'}",
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def user(session_factory):
    user = User(id=uuid.uuid4(), name="Matrix", birth_date="01.01.2000")
    async with session_factory() as session:
        session.add(user)
        await session.commit()
    return user


def _amount() -> CheckoutAmount:
    return CheckoutAmount(
        product="web_matrix",
        base_amount_kopecks=89000,
        discount_amount_kopecks=0,
        discount_percent=0,
        final_amount_kopecks=89000,
        currency="RUB",
    )


async def _checkout(session_factory, user, raw_key):
    scoped_key, report_token = web._checkout_keys(user.id, "web_matrix", raw_key)
    return await web._complete_web_checkout(
        session_factory=session_factory,
        user=user,
        checkout_amount=_amount(),
        scoped_key=scoped_key,
        provider_key=f"provider-{raw_key}",
        report_token=report_token,
    )


@pytest.mark.asyncio
async def test_matrix_checkout_commits_one_placeholder_before_provider_and_reuses_it(
    session_factory, user
):
    calls: list[str] = []

    async def create_payment(**kwargs):
        calls.append(kwargs["idempotence_key"])
        async with session_factory() as session:
            reservation = (await session.execute(select(PromoReservation))).scalar_one()
            report = (
                await session.execute(
                    select(Report).where(Report.token == reservation.report_token)
                )
            ).scalar_one()
            assert report is not None
            assert report.payment_id is None
            assert report.payment_state == ReportPaymentState.AWAITING_PAYMENT
            assert report.generation_state == ReportGenerationState.NOT_REQUESTED
        return {"id": "provider-matrix-1", "payment_url": "https://checkout.invalid/1"}

    raw_key = str(uuid.uuid4())
    with patch.object(PaymentService, "create_web_matrix_payment", new=create_payment):
        await _checkout(session_factory, user, raw_key)
        await _checkout(session_factory, user, raw_key)

    async with session_factory() as session:
        reports = (await session.execute(select(Report))).scalars().all()
        reservations = (await session.execute(select(PromoReservation))).scalars().all()
    assert len(reports) == len(reservations) == 1
    assert reports[0].token == reservations[0].report_token
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_verified_matrix_webhook_activates_outbox_once_without_celery(
    session_factory, user
):
    async def create_payment(**kwargs):
        return {"id": "provider-matrix-2", "payment_url": "https://checkout.invalid/2"}

    with patch.object(PaymentService, "create_web_matrix_payment", new=create_payment):
        await _checkout(session_factory, user, str(uuid.uuid4()))
    async with session_factory() as session:
        reservation = (await session.execute(select(PromoReservation))).scalar_one()
        payment = await session.get(Payment, reservation.payment_id)
    remote = SimpleNamespace(
        id="provider-matrix-2",
        status="succeeded",
        paid=True,
        amount=SimpleNamespace(value="890.00", currency="RUB"),
        metadata={
            "user_id": str(user.id),
            "payment_type": "web_matrix",
            "report_token": reservation.report_token,
        },
    )
    with patch.object(settings, "app_env", "production"), patch(
        "core.services.payment.YooPayment.find_one", return_value=remote
    ), patch("core.tasks.generate_full_report.delay") as enqueue:
        first = await PaymentService.process_webhook(
            session_factory, {"event": "payment.succeeded", "object": {"id": remote.id}}
        )
        second = await PaymentService.process_webhook(
            session_factory, {"event": "payment.succeeded", "object": {"id": remote.id}}
        )
    enqueue.assert_not_called()
    assert first == {"ok": True}
    assert second == {"ok": True, "idempotent": True}
    async with session_factory() as session:
        report = (await session.execute(select(Report))).scalar_one()
        job = (await session.execute(select(ReportGenerationJob))).scalar_one()
        stored_user = await session.get(User, user.id)
        stored_reservation = await session.get(PromoReservation, reservation.id)
        stored_payment = await session.get(Payment, payment.id)
    assert report.payment_id == payment.id
    assert report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED
    assert report.generation_state == ReportGenerationState.PENDING_DISPATCH
    assert job.state == ReportGenerationJobState.PENDING_DISPATCH
    assert job.celery_task_id is None and job.published_at is None
    assert stored_user is not None and stored_user.has_matrix
    assert stored_reservation is not None and stored_reservation.state == "consumed"
    assert stored_payment is not None and stored_payment.status == "succeeded"


@pytest.mark.asyncio
async def test_matrix_webhook_mapping_conflict_fails_closed(session_factory, user):
    async def create_payment(**kwargs):
        return {"id": "provider-matrix-3", "payment_url": "https://checkout.invalid/3"}

    with patch.object(PaymentService, "create_web_matrix_payment", new=create_payment):
        await _checkout(session_factory, user, str(uuid.uuid4()))
    remote = SimpleNamespace(
        id="provider-matrix-3",
        status="succeeded",
        paid=True,
        amount=SimpleNamespace(value="890.00", currency="RUB"),
        metadata={
            "user_id": str(uuid.uuid4()),
            "payment_type": "web_matrix",
            "report_token": "wrong-token",
        },
    )
    with patch.object(settings, "app_env", "production"), patch(
        "core.services.payment.YooPayment.find_one", return_value=remote
    ):
        result = await PaymentService.process_webhook(
            session_factory, {"event": "payment.succeeded", "object": {"id": remote.id}}
        )
    assert result["status"] == "needs_review"
    async with session_factory() as session:
        payment = (await session.execute(select(Payment))).scalar_one()
        report = (await session.execute(select(Report))).scalar_one()
        assert not (await session.execute(select(ReportGenerationJob))).scalars().all()
    assert payment.status == "pending"
    assert report.payment_state == ReportPaymentState.AWAITING_PAYMENT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_stage",
    [
        "after_payment_claim",
        "after_report_job",
        "after_entitlement",
        "after_promo_consume",
    ],
)
async def test_matrix_activation_checkpoint_failure_rolls_back_everything(
    session_factory, user, failure_stage
):
    async def create_payment(**kwargs):
        return {"id": f"provider-{failure_stage}", "payment_url": "https://checkout.invalid/failure"}

    with patch.object(PaymentService, "create_web_matrix_payment", new=create_payment):
        await _checkout(session_factory, user, str(uuid.uuid4()))
    async with session_factory() as session:
        reservation = (await session.execute(select(PromoReservation))).scalar_one()

    async def fail_at(stage: str) -> None:
        if stage == failure_stage:
            raise RuntimeError("controlled_lifecycle_failure")

    async with session_factory() as session:
        with pytest.raises(RuntimeError, match="controlled_lifecycle_failure"):
            await ReportLifecycleCoordinator(session, fail_at).activate_verified_matrix_payment(
                provider_payment_id=f"provider-{failure_stage}",
                verified_user_id=user.id,
                verified_report_token=reservation.report_token,
                confirmed_at=datetime.now(timezone.utc),
            )
        await session.rollback()
        payment = (await session.execute(select(Payment))).scalar_one()
        report = (await session.execute(select(Report))).scalar_one()
        stored_user = await session.get(User, user.id)
        stored_reservation = await session.get(PromoReservation, reservation.id)
        assert not (await session.execute(select(ReportGenerationJob))).scalars().all()
    assert payment.status == "pending"
    assert report.payment_state == ReportPaymentState.AWAITING_PAYMENT
    assert report.generation_state == ReportGenerationState.NOT_REQUESTED
    assert stored_user is not None and not stored_user.has_matrix
    assert stored_reservation is not None and stored_reservation.state == "reserved"

    async with session_factory() as session:
        outcome = await ReportLifecycleCoordinator(session).activate_verified_matrix_payment(
            provider_payment_id=f"provider-{failure_stage}",
            verified_user_id=user.id,
            verified_report_token=reservation.report_token,
            confirmed_at=datetime.now(timezone.utc),
        )
        await session.commit()
    assert outcome == "activated"
