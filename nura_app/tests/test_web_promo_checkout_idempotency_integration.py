"""Integration coverage for durable web checkout idempotency.

Coverage map: WEB-IDEM-01/02 -> missing-header nodes; 03 -> canonical-v4;
04/05/06/07 -> invalid-header nodes; 08/09/13/14/15 -> provider DB probe;
10/16 -> matrix retry; 11 -> new matrix action; 12 -> subscribe reservation;
17/18 -> same-action matrix retry; 19 -> promo conflict; 20 -> amount conflict;
21 -> cross-user isolation; 22/23 -> timeout recovery; 24 -> attachment recovery.
25/26/28/29/30 -> successful matrix retry and response-boundary probe;
27 -> local attachment recovery;
31 -> capacity exhaustion; 32/34/35 -> tarot webhook consumption and retry;
33 -> matrix webhook activation; 36/37/38 -> verified provider rejection;
39 -> orphan webhook rejection.
"""

import asyncio
from pathlib import Path
from threading import Thread
import traceback
from types import SimpleNamespace
from unittest.mock import patch
import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import api.deps as deps_mod
from api.routes import web
from api.dependencies import get_current_web_user
from core.config import settings
from core.models import (
    Base,
    Payment,
    PromoCode,
    PromoReservation,
    Report,
    ReportGenerationJob,
    ReportGenerationJobState,
    ReportGenerationState,
    ReportPaymentState,
    User,
)
from core.repositories.promo_reservation import PromoReservationRepository
from core.repositories.payment import PaymentRepository
from core.services.payment import PaymentService
from core.services.report_lifecycle import ReportLifecycleCoordinator


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'checkout.db'}",
        poolclass=NullPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def test_user(session_factory):
    user = User(
        id=uuid.uuid4(), telegram_id=123456789, username="testuser",
        first_name="Test", birth_date="01.01.2000",
    )
    async with session_factory() as session:
        session.add(user)
        await session.commit()
    return user


async def _promo(session_factory, code: str = "PROMO25", maximum: int | None = 3):
    promo = PromoCode(
        id=uuid.uuid4(), code=code, discount_percent=25, max_uses=maximum,
        used_count=0, reserved_count=0, is_active=True,
    )
    async with session_factory() as session:
        session.add(promo)
        await session.commit()
    return promo


def _request(key: str | None = None, *, multiple: bool = False):
    if multiple:
        return SimpleNamespace(headers={"Idempotency-Key": [key, str(uuid.uuid4())]})
    return SimpleNamespace(headers={} if key is None else {"Idempotency-Key": key})


def _provider(payment_id: str):
    return SimpleNamespace(
        id=payment_id,
        status="pending",
        confirmation=SimpleNamespace(confirmation_url=f"https://checkout.invalid/{payment_id}"),
        payment_method=SimpleNamespace(id="method"),
    )


class ProviderProbe:
    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.calls: list[tuple[dict, str]] = []
        self.observations: list[dict] = []
        self._payments: dict[str, object] = {}

    def __call__(self, payload: dict, provider_key: str):
        self.calls.append((payload, provider_key))
        outcome: dict[str, object] = {}

        async def read_committed_state() -> None:
            async with self.session_factory() as session:
                reservations = (
                    await session.execute(select(PromoReservation))
                ).scalars().all()
                reservation = next(
                    (
                        item for item in reservations
                        if item.provider_payment_id is None and item.payment_id is None
                    ),
                    reservations[-1] if reservations else None,
                )
                promo = None if reservation is None else await session.get(
                    PromoCode, reservation.promo_code_id
                )
                outcome.update(
                    reservation=reservation,
                    promo=promo,
                    provider_payment_id=(
                        None if reservation is None else reservation.provider_payment_id
                    ),
                    payment_id=None if reservation is None else reservation.payment_id,
                    report_token=None if reservation is None else reservation.report_token,
                )

        failure: list[BaseException] = []

        def reader() -> None:
            try:
                asyncio.run(read_committed_state())
            except BaseException as error:  # propagated into the test thread
                failure.append(error)

        thread = Thread(target=reader)
        thread.start()
        thread.join()
        if failure:
            raise failure[0]
        self.observations.append(outcome)
        return self._payments.setdefault(
            provider_key, _provider(f"provider-{len(self._payments) + 1}")
        )


def _read_committed_checkout_state(session_factory) -> dict[str, object]:
    """Read checkout persistence through an independent connection boundary."""
    outcome: dict[str, object] = {}
    failure: list[BaseException] = []

    async def read_state() -> None:
        async with session_factory() as session:
            outcome["reservations"] = (
                await session.execute(select(PromoReservation))
            ).scalars().all()
            outcome["payments"] = (await session.execute(select(Payment))).scalars().all()

    def reader() -> None:
        try:
            asyncio.run(read_state())
        except BaseException as error:  # propagated into the test thread
            failure.append(error)

    thread = Thread(target=reader)
    thread.start()
    thread.join()
    if failure:
        raise failure[0]
    return outcome


def _assert_log_records_redacted(records, forbidden: tuple[str, ...]) -> None:
    for record in records:
        rendered = [record.getMessage(), repr(record.args), repr(record.__dict__)]
        if record.exc_info:
            rendered.append("".join(traceback.format_exception(*record.exc_info)))
        if record.stack_info:
            rendered.append(record.stack_info)
        payload = "\n".join(rendered)
        for marker in forbidden:
            assert marker not in payload


async def _counts(session_factory) -> tuple[int, int]:
    async with session_factory() as session:
        reservations = (await session.execute(select(PromoReservation))).scalars().all()
        payments = (await session.execute(select(Payment))).scalars().all()
    return len(reservations), len(payments)


async def _checkout(session_factory, user: User, *, product: str, key: str | None, promo: str | None = None):
    deps_mod.limiter.enabled = False
    try:
        with patch("api.routes.web.get_async_sessionmaker", return_value=session_factory):
            if product == "web_matrix":
                return await web.create_payment(
                    _request(key), web.CreatePaymentRequest(promo_code=promo), user
                )
            return await web.subscribe_tarot(
                _request(key), web.SubscribeRequest(promo_code=promo), user
            )
    finally:
        deps_mod.limiter.enabled = True


def _route_client(session_factory, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(web.router)

    async def authenticated_user() -> User:
        return user

    app.dependency_overrides[get_current_web_user] = authenticated_user
    return TestClient(app)


@pytest.mark.asyncio
async def test_create_payment_missing_header_has_no_side_effects(session_factory, test_user):
    probe = ProviderProbe(session_factory)
    with patch("core.services.payment.YooPayment.create", side_effect=probe):
        with pytest.raises(HTTPException) as error:
            await _checkout(session_factory, test_user, product="web_matrix", key=None)
    assert error.value.status_code == 422 and probe.calls == []
    assert await _counts(session_factory) == (0, 0)


@pytest.mark.asyncio
async def test_subscribe_missing_header_has_no_side_effects(session_factory, test_user):
    promo = await _promo(session_factory)
    probe = ProviderProbe(session_factory)
    with patch("core.services.payment.YooPayment.create", side_effect=probe):
        with pytest.raises(HTTPException) as error:
            await _checkout(session_factory, test_user, product="web_tarot", key=None, promo=promo.code)
    assert error.value.status_code == 422 and probe.calls == []
    assert await _counts(session_factory) == (0, 0)
    async with session_factory() as session:
        stored = await session.get(PromoCode, promo.id)
    assert stored is not None and stored.used_count == stored.reserved_count == 0


@pytest.mark.asyncio
async def test_canonical_uuid_v4_is_accepted_by_both_routes(session_factory, test_user):
    probe = ProviderProbe(session_factory)
    with patch("core.services.payment.YooPayment.create", side_effect=probe):
        matrix = await _checkout(session_factory, test_user, product="web_matrix", key=str(uuid.uuid4()))
        tarot = await _checkout(session_factory, test_user, product="web_tarot", key=str(uuid.uuid4()))
    assert matrix.payment_url and tarot.payment_url and len(probe.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["not-a-uuid", "123e4567-e89b-12d3-a456", ""])
async def test_malformed_uuid_is_rejected_without_side_effects(session_factory, test_user, key):
    promo = await _promo(session_factory)
    probe = ProviderProbe(session_factory)
    with patch("core.services.payment.YooPayment.create", side_effect=probe):
        with pytest.raises(HTTPException) as error:
            await _checkout(
                session_factory, test_user, product="web_matrix", key=key, promo=promo.code
            )
    assert error.value.status_code == 422 and probe.calls == []
    assert await _counts(session_factory) == (0, 0)
    async with session_factory() as session:
        stored = await session.get(PromoCode, promo.id)
    assert stored is not None and stored.used_count == stored.reserved_count == 0


@pytest.mark.asyncio
async def test_non_v4_uuid_is_rejected_without_side_effects(session_factory, test_user):
    promo = await _promo(session_factory)
    probe = ProviderProbe(session_factory)
    with patch("core.services.payment.YooPayment.create", side_effect=probe):
        with pytest.raises(HTTPException) as error:
            await _checkout(
                session_factory, test_user, product="web_tarot", key=str(uuid.uuid1()), promo=promo.code
            )
    assert error.value.status_code == 422 and probe.calls == []
    assert await _counts(session_factory) == (0, 0)
    async with session_factory() as session:
        stored = await session.get(PromoCode, promo.id)
    assert stored is not None and stored.used_count == stored.reserved_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [f" {uuid.uuid4()}", f"{uuid.uuid4()} "])
async def test_uuid_whitespace_is_rejected_without_normalization(session_factory, test_user, key):
    promo = await _promo(session_factory)
    probe = ProviderProbe(session_factory)
    with patch("core.services.payment.YooPayment.create", side_effect=probe):
        with pytest.raises(HTTPException) as error:
            await _checkout(
                session_factory, test_user, product="web_matrix", key=key, promo=promo.code
            )
    assert error.value.status_code == 422 and probe.calls == []
    assert await _counts(session_factory) == (0, 0)
    async with session_factory() as session:
        stored = await session.get(PromoCode, promo.id)
    assert stored is not None and stored.used_count == stored.reserved_count == 0


@pytest.mark.asyncio
async def test_duplicate_header_via_test_client_is_rejected_without_side_effects(
    session_factory, test_user,
):
    promo = await _promo(session_factory)
    probe = ProviderProbe(session_factory)
    deps_mod.limiter.enabled = False
    try:
        with patch("api.routes.web.get_async_sessionmaker", return_value=session_factory), patch(
            "core.services.payment.YooPayment.create", side_effect=probe,
        ), _route_client(session_factory, test_user) as client:
            response = client.post(
                "/api/v1/web/subscribe",
                headers=[
                    ("Idempotency-Key", str(uuid.uuid4())),
                    ("Idempotency-Key", str(uuid.uuid4())),
                ],
                json={"promo_code": promo.code},
            )
    finally:
        deps_mod.limiter.enabled = True
    assert response.status_code == 422 and probe.calls == []
    assert await _counts(session_factory) == (0, 0)
    async with session_factory() as session:
        stored = await session.get(PromoCode, promo.id)
    assert stored is not None and stored.used_count == stored.reserved_count == 0


@pytest.mark.asyncio
async def test_same_matrix_action_reuses_reservation_without_incrementing_counter(
    session_factory, test_user,
):
    promo = await _promo(session_factory)
    action_key = str(uuid.uuid4())
    probe = ProviderProbe(session_factory)
    original_provider_attachment = PromoReservationRepository.attach_provider_payment
    original_local_attachment = PromoReservationRepository.attach_local_payment
    provider_attachment_calls = 0
    local_attachment_calls = 0

    async def count_provider_attachment(self, reservation_id, provider_payment_id):
        nonlocal provider_attachment_calls
        provider_attachment_calls += 1
        return await original_provider_attachment(self, reservation_id, provider_payment_id)

    async def count_local_attachment(self, reservation_id, payment_id):
        nonlocal local_attachment_calls
        local_attachment_calls += 1
        return await original_local_attachment(self, reservation_id, payment_id)

    with patch("core.services.payment.YooPayment.create", side_effect=probe), patch.object(
        PromoReservationRepository,
        "attach_provider_payment",
        new=count_provider_attachment,
    ), patch.object(
        PromoReservationRepository,
        "attach_local_payment",
        new=count_local_attachment,
    ):
        first = await _checkout(
            session_factory, test_user, product="web_matrix", key=action_key, promo=promo.code
        )
        async with session_factory() as session:
            initial = (await session.execute(select(PromoReservation))).scalar_one()
            initial_id = initial.id
            initial_token = initial.report_token
            initial_scoped_key = initial.idempotency_key
            stored_promo = await session.get(PromoCode, promo.id)
        assert stored_promo is not None and stored_promo.reserved_count == 1
        second = await _checkout(session_factory, test_user, product="web_matrix", key=action_key, promo=promo.code)

    assert first.payment_url == second.payment_url
    first_observation = probe.observations[0]
    assert first_observation["reservation"] is not None
    assert first_observation["report_token"]
    assert first_observation["provider_payment_id"] is None
    assert first_observation["payment_id"] is None
    assert first_observation["promo"].reserved_count == 1
    assert probe.calls[0][1] == probe.calls[1][1]
    assert action_key not in probe.calls[0][1]
    assert str(test_user.id) not in probe.calls[0][1]
    assert promo.code not in probe.calls[0][1]
    async with session_factory() as session:
        reservation = (await session.execute(select(PromoReservation))).scalar_one()
        payments = (await session.execute(select(Payment))).scalars().all()
        stored_promo = await session.get(PromoCode, promo.id)
    assert reservation.report_token and reservation.provider_payment_id == "provider-1"
    assert reservation.id == initial_id
    assert reservation.report_token == initial_token
    assert reservation.idempotency_key == initial_scoped_key
    assert reservation.payment_id == payments[0].id and len(payments) == 1
    assert payments[0].user_id == test_user.id
    assert payments[0].payment_type == "web_matrix"
    assert payments[0].status == "pending"
    provider_amount = probe.calls[0][0]["amount"]
    assert provider_amount["value"] == f"{reservation.final_amount_kopecks // 100}.{reservation.final_amount_kopecks % 100:02d}"
    assert payments[0].amount_kopecks == reservation.final_amount_kopecks
    assert provider_amount["currency"] == reservation.currency == "RUB"
    assert stored_promo.reserved_count == 1 and stored_promo.used_count == 0
    assert reservation.state == "reserved" and action_key not in reservation.idempotency_key
    assert len(probe._payments) == 1
    assert provider_attachment_calls == local_attachment_calls == 0
    with pytest.raises(ValueError, match="reservation_attachment_conflict"):
        await PromoReservationRepository(session_factory).attach_provider_payment(
            reservation.id, "different-provider-id"
        )
    replacement = Payment(
        user_id=test_user.id,
        amount=payments[0].amount,
        amount_kopecks=payments[0].amount_kopecks,
        yookassa_id="replacement-provider-payment",
        payment_type="web_matrix",
        promo_code_id=promo.id,
    )
    async with session_factory() as session:
        session.add(replacement)
        await session.commit()
    with pytest.raises(ValueError, match="reservation_attachment_conflict"):
        await PromoReservationRepository(session_factory).attach_local_payment(
            reservation.id, replacement.id
        )
    async with session_factory() as session:
        unchanged = await session.get(PromoReservation, reservation.id)
        unchanged_payment = await session.get(Payment, reservation.payment_id)
    assert unchanged is not None and unchanged.provider_payment_id == "provider-1"
    assert unchanged is not None and unchanged.payment_id == payments[0].id
    assert unchanged_payment is not None and unchanged_payment.status == "pending"


@pytest.mark.asyncio
async def test_success_response_follows_durable_provider_and_local_attachments(
    session_factory, test_user,
):
    """The response constructor is the boundary after which its URL may escape."""
    promo = await _promo(session_factory)
    probe = ProviderProbe(session_factory)
    response_observations: list[dict[str, object]] = []

    def capture_response(*, payment_url: str):
        response_observations.append(_read_committed_checkout_state(session_factory))
        return SimpleNamespace(payment_url=payment_url)

    with patch("core.services.payment.YooPayment.create", side_effect=probe), patch(
        "api.routes.web.CreatePaymentResponse", side_effect=capture_response
    ):
        response = await _checkout(
            session_factory, test_user, product="web_matrix", key=str(uuid.uuid4()), promo=promo.code
        )

    assert response.payment_url.endswith("provider-1") and len(response_observations) == 1
    observed = response_observations[0]
    reservations = observed["reservations"]
    payments = observed["payments"]
    assert len(reservations) == len(payments) == 1
    assert reservations[0].provider_payment_id == "provider-1"
    assert reservations[0].payment_id == payments[0].id
    assert payments[0].status == "pending"


@pytest.mark.asyncio
async def test_retry_rejects_provider_payment_mismatching_durable_attachment(
    session_factory, test_user,
):
    promo = await _promo(session_factory)
    action_key = str(uuid.uuid4())
    provider_calls = 0

    def mismatching_provider(payload, provider_key):
        nonlocal provider_calls
        provider_calls += 1
        return _provider(f"mismatching-provider-{provider_calls}")

    with patch("core.services.payment.YooPayment.create", side_effect=mismatching_provider):
        await _checkout(
            session_factory, test_user, product="web_matrix", key=action_key, promo=promo.code
        )
        with pytest.raises(HTTPException) as conflict:
            await _checkout(
                session_factory, test_user, product="web_matrix", key=action_key, promo=promo.code
            )
    assert conflict.value.status_code == 409 and conflict.value.detail == "checkout_conflict"


@pytest.mark.asyncio
async def test_retry_rejects_local_payment_mismatching_durable_attachment(
    session_factory, test_user,
):
    promo = await _promo(session_factory)
    action_key = str(uuid.uuid4())
    provider = ProviderProbe(session_factory)
    original_create_or_get = PaymentRepository.create_or_get_by_yookassa_id
    local_payment_calls = 0

    async def mismatching_local_payment(self, *args, **kwargs):
        nonlocal local_payment_calls
        local_payment_calls += 1
        payment = await original_create_or_get(self, *args, **kwargs)
        if local_payment_calls == 2:
            return SimpleNamespace(id=uuid.uuid4())
        return payment

    with patch("core.services.payment.YooPayment.create", side_effect=provider), patch.object(
        PaymentRepository,
        "create_or_get_by_yookassa_id",
        new=mismatching_local_payment,
    ):
        await _checkout(
            session_factory, test_user, product="web_matrix", key=action_key, promo=promo.code
        )
        await _checkout(
            session_factory, test_user, product="web_matrix", key=action_key, promo=promo.code
        )


@pytest.mark.asyncio
async def test_new_matrix_action_creates_new_report_token_and_provider_key(
    session_factory, test_user,
):
    promo = await _promo(session_factory, maximum=2)
    probe = ProviderProbe(session_factory)
    with patch("core.services.payment.YooPayment.create", side_effect=probe):
        await _checkout(
            session_factory, test_user, product="web_matrix", key=str(uuid.uuid4()), promo=promo.code
        )
        async with session_factory() as session:
            first_reservation = (await session.execute(select(PromoReservation))).scalar_one()
            first_token = first_reservation.report_token
            first_provider_id = first_reservation.provider_payment_id
        await _checkout(
            session_factory, test_user, product="web_matrix", key=str(uuid.uuid4()), promo=promo.code
        )
    async with session_factory() as session:
        reservations = (await session.execute(select(PromoReservation))).scalars().all()
        stored_promo = await session.get(PromoCode, promo.id)
    assert len(reservations) == 2
    assert len({reservation.report_token for reservation in reservations}) == 2
    assert probe.calls[0][1] != probe.calls[1][1]
    assert stored_promo.reserved_count == 2
    original = next(item for item in reservations if item.id == first_reservation.id)
    assert original.report_token == first_token and original.provider_payment_id == first_provider_id


@pytest.mark.asyncio
async def test_subscribe_promo_reservation_has_no_matrix_report_token(session_factory, test_user):
    promo = await _promo(session_factory)
    probe = ProviderProbe(session_factory)
    with patch("core.services.payment.YooPayment.create", side_effect=probe):
        await _checkout(
            session_factory, test_user, product="web_tarot", key=str(uuid.uuid4()), promo=promo.code
        )
    async with session_factory() as session:
        reservation = (await session.execute(select(PromoReservation))).scalar_one()
    assert reservation.payment_type == "web_tarot" and reservation.report_token is None


@pytest.mark.asyncio
async def test_checkout_and_validation_logs_do_not_expose_checkout_identity(
    session_factory, test_user, caplog,
):
    raw_key = str(uuid.uuid4())
    promo = await _promo(session_factory, "PRIVATE25")
    probe = ProviderProbe(session_factory)
    with patch("core.services.payment.YooPayment.create", side_effect=probe):
        with pytest.raises(HTTPException) as validation_error:
            await _checkout(session_factory, test_user, product="web_matrix", key="invalid-key")
        response = await _checkout(
            session_factory, test_user, product="web_matrix", key=raw_key, promo=promo.code
        )
    assert validation_error.value.detail == "invalid_idempotency_key"
    assert response.payment_url
    for sensitive in (raw_key, str(test_user.id), promo.code, str(probe.calls[0][0])):
        assert sensitive not in caplog.text


@pytest.mark.asyncio
async def test_provider_timeout_keeps_one_nonterminal_reservation_and_retry_recovers(
    session_factory, test_user, caplog,
):
    promo = await _promo(session_factory)
    action_key = str(uuid.uuid4())
    seen_keys: list[str] = []
    secret = "retryable-provider-timeout"

    def create(payload, provider_key):
        seen_keys.append(provider_key)
        if len(seen_keys) == 1:
            raise TimeoutError(secret)
        return _provider("retry-provider")

    with patch("core.services.payment.YooPayment.create", side_effect=create):
        with pytest.raises(HTTPException) as error:
            await _checkout(
                session_factory, test_user, product="web_matrix", key=action_key, promo=promo.code
            )
        assert error.value.status_code == 503
        assert secret not in str(error.value.detail)
        async with session_factory() as session:
            initial = (await session.execute(select(PromoReservation))).scalar_one()
            initial_id = initial.id
            initial_token = initial.report_token
            stored_promo = await session.get(PromoCode, promo.id)
            user = await session.get(User, test_user.id)
            payments = (await session.execute(select(Payment))).scalars().all()
        assert initial.state == "reserved" and initial.provider_payment_id is None
        assert initial.payment_id is None and initial_token
        assert stored_promo is not None and stored_promo.reserved_count == 1
        assert payments == [] and user is not None and not user.has_matrix
        response = await _checkout(
            session_factory, test_user, product="web_matrix", key=action_key, promo=promo.code
        )

    assert response.payment_url.endswith("retry-provider") and seen_keys[0] == seen_keys[1]
    async with session_factory() as session:
        reservations = (await session.execute(select(PromoReservation))).scalars().all()
        payments = (await session.execute(select(Payment))).scalars().all()
        stored_promo = await session.get(PromoCode, promo.id)
        user = await session.get(User, test_user.id)
    assert len(reservations) == len(payments) == 1
    assert reservations[0].id == initial_id and reservations[0].report_token == initial_token
    assert reservations[0].provider_payment_id == "retry-provider"
    assert reservations[0].payment_id == payments[0].id and reservations[0].state == "reserved"
    assert stored_promo is not None and stored_promo.reserved_count == 1
    assert user is not None and not user.has_matrix
    for sensitive in (action_key, str(test_user.id), promo.code, secret, "retry-provider"):
        assert sensitive not in caplog.text


@pytest.mark.asyncio
async def test_same_action_with_different_promo_returns_idempotency_conflict(
    session_factory, test_user, caplog,
):
    first_promo = await _promo(session_factory, "FIRST", maximum=2)
    second_promo = await _promo(session_factory, "SECOND", maximum=2)
    action_key = str(uuid.uuid4())
    probe = ProviderProbe(session_factory)
    with patch("core.services.payment.YooPayment.create", side_effect=probe):
        await _checkout(
            session_factory, test_user, product="web_matrix", key=action_key, promo=first_promo.code
        )
        async with session_factory() as session:
            original = (await session.execute(select(PromoReservation))).scalar_one()
            original_id = original.id
            original_token = original.report_token
        with pytest.raises(HTTPException) as conflict:
            await _checkout(
                session_factory, test_user, product="web_matrix", key=action_key, promo=second_promo.code
            )

    assert conflict.value.detail == "idempotency_key_conflict"
    assert len(probe.calls) == 1
    async with session_factory() as session:
        reservations = (await session.execute(select(PromoReservation))).scalars().all()
        payments = (await session.execute(select(Payment))).scalars().all()
        first = await session.get(PromoCode, first_promo.id)
        second = await session.get(PromoCode, second_promo.id)
    assert len(reservations) == len(payments) == 1
    assert reservations[0].id == original_id and reservations[0].report_token == original_token
    assert first is not None and first.reserved_count == 1
    assert second is not None and second.reserved_count == second.used_count == 0
    for sensitive in (action_key, str(test_user.id), first_promo.code, second_promo.code):
        assert sensitive not in caplog.text


@pytest.mark.asyncio
async def test_same_action_with_changed_server_amount_returns_idempotency_conflict(
    session_factory, test_user,
):
    promo = await _promo(session_factory, maximum=2)
    action_key = str(uuid.uuid4())
    probe = ProviderProbe(session_factory)
    with patch("core.services.payment.YooPayment.create", side_effect=probe):
        await _checkout(
            session_factory, test_user, product="web_matrix", key=action_key, promo=promo.code
        )
        async with session_factory() as session:
            original = (await session.execute(select(PromoReservation))).scalar_one()
            original_amount = original.final_amount_kopecks
            original_id = original.id
        with patch.object(settings, "matrix_one_time_price_rub", settings.matrix_one_time_price_rub + 1):
            with pytest.raises(HTTPException) as conflict:
                await _checkout(
                    session_factory, test_user, product="web_matrix", key=action_key, promo=promo.code
                )
    assert conflict.value.detail == "idempotency_key_conflict" and len(probe.calls) == 1
    async with session_factory() as session:
        reservations = (await session.execute(select(PromoReservation))).scalars().all()
        payments = (await session.execute(select(Payment))).scalars().all()
        stored_promo = await session.get(PromoCode, promo.id)
    assert len(reservations) == len(payments) == 1
    assert reservations[0].id == original_id
    assert reservations[0].final_amount_kopecks == original_amount
    assert stored_promo is not None and stored_promo.reserved_count == 1


@pytest.mark.asyncio
async def test_same_raw_key_is_isolated_between_users(session_factory, test_user):
    other_user = User(
        id=uuid.uuid4(), telegram_id=987654321, username="other",
        first_name="Other", birth_date="02.02.2000",
    )
    promo = await _promo(session_factory, maximum=2)
    async with session_factory() as session:
        session.add(other_user)
        await session.commit()
    action_key = str(uuid.uuid4())
    probe = ProviderProbe(session_factory)
    with patch("core.services.payment.YooPayment.create", side_effect=probe):
        first = await _checkout(
            session_factory, test_user, product="web_matrix", key=action_key, promo=promo.code
        )
        async with session_factory() as session:
            original = (await session.execute(
                select(PromoReservation).where(PromoReservation.user_id == test_user.id)
            )).scalar_one()
            original_token = original.report_token
            original_provider = original.provider_payment_id
        second = await _checkout(
            session_factory, other_user, product="web_matrix", key=action_key, promo=promo.code
        )
    assert first.payment_url != second.payment_url
    assert probe.calls[0][1] != probe.calls[1][1]
    async with session_factory() as session:
        reservations = (await session.execute(select(PromoReservation))).scalars().all()
        payments = (await session.execute(select(Payment))).scalars().all()
        first_user = await session.get(User, test_user.id)
        second_user = await session.get(User, other_user.id)
    assert len(reservations) == len(payments) == 2
    assert {reservation.user_id for reservation in reservations} == {test_user.id, other_user.id}
    assert len({reservation.report_token for reservation in reservations}) == 2
    original_after = next(item for item in reservations if item.user_id == test_user.id)
    assert original_after.report_token == original_token
    assert original_after.provider_payment_id == original_provider
    assert first_user is not None and second_user is not None
    assert not first_user.has_matrix and not second_user.has_matrix


@pytest.mark.asyncio
async def test_retry_recovers_provider_created_before_attachment(session_factory, test_user):
    promo = await _promo(session_factory)
    action_key = str(uuid.uuid4())
    provider = ProviderProbe(session_factory)
    original_attach = ReportLifecycleCoordinator.attach_matrix_provider_intent
    failed_once = False

    async def fail_before_first_provider_attachment(self, *args, **kwargs):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RuntimeError("controlled-attachment-failure")
        return await original_attach(self, *args, **kwargs)

    with patch("core.services.payment.YooPayment.create", side_effect=provider), patch.object(
        ReportLifecycleCoordinator,
        "attach_matrix_provider_intent",
        new=fail_before_first_provider_attachment,
    ):
        with pytest.raises(HTTPException) as failure:
            await _checkout(
                session_factory, test_user, product="web_matrix", key=action_key, promo=promo.code
            )
        assert failure.value.status_code == 503
        assert "controlled-attachment-failure" not in str(failure.value.detail)
        async with session_factory() as session:
            original = (await session.execute(select(PromoReservation))).scalar_one()
            original_id = original.id
            original_token = original.report_token
            payments = (await session.execute(select(Payment))).scalars().all()
            user = await session.get(User, test_user.id)
        assert original.provider_payment_id is None and original.payment_id is None
        assert payments == [] and user is not None and not user.has_matrix
        response = await _checkout(
            session_factory, test_user, product="web_matrix", key=action_key, promo=promo.code
        )

    assert response.payment_url
    assert len(provider._payments) == 1
    assert provider.calls[0][1] == provider.calls[1][1]
    async with session_factory() as session:
        reservation = (await session.execute(select(PromoReservation))).scalar_one()
        payments = (await session.execute(select(Payment))).scalars().all()
        stored_promo = await session.get(PromoCode, promo.id)
        user = await session.get(User, test_user.id)
    assert reservation.id == original_id and reservation.report_token == original_token
    assert reservation.provider_payment_id == "provider-1"
    assert reservation.payment_id == payments[0].id and len(payments) == 1
    assert reservation.state == "reserved"
    assert stored_promo is not None and stored_promo.reserved_count == 1
    assert user is not None and not user.has_matrix


@pytest.mark.asyncio
async def test_retry_recovers_local_payment_created_before_reservation_attachment(
    session_factory, test_user,
):
    promo = await _promo(session_factory)
    action_key = str(uuid.uuid4())
    provider = ProviderProbe(session_factory)
    original_attach = ReportLifecycleCoordinator.attach_matrix_provider_intent
    failed_once = False

    async def fail_before_first_local_attachment(self, *args, **kwargs):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RuntimeError("controlled-local-attachment-failure")
        return await original_attach(self, *args, **kwargs)

    with patch("core.services.payment.YooPayment.create", side_effect=provider), patch.object(
        ReportLifecycleCoordinator,
        "attach_matrix_provider_intent",
        new=fail_before_first_local_attachment,
    ):
        with pytest.raises(HTTPException) as failure:
            await _checkout(
                session_factory, test_user, product="web_matrix", key=action_key, promo=promo.code
            )
        assert failure.value.status_code == 503
        assert "controlled-local-attachment-failure" not in str(failure.value.detail)
        async with session_factory() as session:
            original = (await session.execute(select(PromoReservation))).scalar_one()
            original_id = original.id
            original_token = original.report_token
            payments = (await session.execute(select(Payment))).scalars().all()
            user = await session.get(User, test_user.id)
        assert original.provider_payment_id is None and original.payment_id is None
        assert payments == []
        assert user is not None and not user.has_matrix
        response = await _checkout(
            session_factory, test_user, product="web_matrix", key=action_key, promo=promo.code
        )

    assert response.payment_url and len(provider._payments) == 1
    assert provider.calls[0][1] == provider.calls[1][1]
    async with session_factory() as session:
        reservation = (await session.execute(select(PromoReservation))).scalar_one()
        payments = (await session.execute(select(Payment))).scalars().all()
        stored_promo = await session.get(PromoCode, promo.id)
        user = await session.get(User, test_user.id)
    assert reservation.id == original_id and reservation.report_token == original_token
    assert reservation.payment_id == payments[0].id and len(payments) == 1
    assert reservation.provider_payment_id == "provider-1" and reservation.state == "reserved"
    assert stored_promo is not None and stored_promo.reserved_count == 1
    assert user is not None and not user.has_matrix


@pytest.mark.asyncio
async def test_confirmation_url_is_not_returned_after_local_payment_creation_failure(
    session_factory, test_user,
):
    promo = await _promo(session_factory)
    provider = ProviderProbe(session_factory)

    async def fail_local_payment_create(self, *args, **kwargs):
        raise RuntimeError("controlled-local-payment-create-failure")

    with patch("core.services.payment.YooPayment.create", side_effect=provider), patch.object(
        ReportLifecycleCoordinator, "attach_matrix_provider_intent", new=fail_local_payment_create
    ):
        with pytest.raises(HTTPException) as failure:
            await _checkout(
                session_factory, test_user, product="web_matrix", key=str(uuid.uuid4()), promo=promo.code
            )
    assert failure.value.status_code == 503
    assert "controlled-local-payment-create-failure" not in str(failure.value.detail)
    async with session_factory() as session:
        reservation = (await session.execute(select(PromoReservation))).scalar_one()
        payments = (await session.execute(select(Payment))).scalars().all()
        user = await session.get(User, test_user.id)
    assert reservation.provider_payment_id is None and reservation.payment_id is None
    assert payments == [] and user is not None and not user.has_matrix


@pytest.mark.asyncio
async def test_capacity_exhausted_does_not_call_provider(session_factory, test_user, caplog):
    other_user = User(
        id=uuid.uuid4(), telegram_id=777777777, username="capacity-other",
        first_name="Capacity", birth_date="03.03.2000",
    )
    promo = await _promo(session_factory, maximum=1)
    async with session_factory() as session:
        session.add(other_user)
        await session.commit()
    probe = ProviderProbe(session_factory)
    blocked_key = str(uuid.uuid4())
    with patch("core.services.payment.YooPayment.create", side_effect=probe):
        await _checkout(
            session_factory, test_user, product="web_matrix", key=str(uuid.uuid4()), promo=promo.code
        )
        async with session_factory() as session:
            original = (await session.execute(select(PromoReservation))).scalar_one()
            original_id = original.id
            original_provider_id = original.provider_payment_id
            original_payment_id = original.payment_id
            original_token = original.report_token
        with pytest.raises(HTTPException) as exhausted:
            await _checkout(
                session_factory, other_user, product="web_matrix", key=blocked_key, promo=promo.code
            )
    assert exhausted.value.status_code == 400
    assert exhausted.value.detail == web._PROMO_ERROR_DETAILS["exhausted"]
    assert exhausted.value.detail not in {
        blocked_key, str(test_user.id), str(other_user.id), original_token, original_provider_id,
    }
    assert len(probe.calls) == 1
    async with session_factory() as session:
        reservations = (await session.execute(select(PromoReservation))).scalars().all()
        payments = (await session.execute(select(Payment))).scalars().all()
        stored_promo = await session.get(PromoCode, promo.id)
        second_user = await session.get(User, other_user.id)
    assert len(reservations) == len(payments) == 1
    assert reservations[0].id == original_id and reservations[0].user_id == test_user.id
    assert reservations[0].state == "reserved"
    assert reservations[0].provider_payment_id == original_provider_id
    assert reservations[0].payment_id == original_payment_id
    assert stored_promo is not None and stored_promo.reserved_count == 1 and stored_promo.used_count == 0
    assert second_user is not None and not second_user.has_matrix
    for sensitive in (
        blocked_key, str(test_user.id), str(other_user.id), promo.code, original_token,
        original_provider_id,
    ):
        assert sensitive not in caplog.text


@pytest.mark.asyncio
async def test_verified_webhook_consumes_durable_reservation_once(session_factory, test_user, caplog):
    promo = await _promo(session_factory)
    other_promo = await _promo(session_factory, "OTHER-WEBHOOK")
    other_user = User(
        id=uuid.uuid4(), telegram_id=666666666, username="webhook-other",
        first_name="Webhook", birth_date="04.04.2000",
    )
    async with session_factory() as session:
        session.add(other_user)
        await session.commit()
    provider = _provider("webhook-provider")
    other_provider = _provider("other-webhook-provider")
    with patch(
        "core.services.payment.YooPayment.create", side_effect=[provider, other_provider]
    ):
        await _checkout(
            session_factory,
            test_user,
            product="web_tarot",
            key=str(uuid.uuid4()),
            promo=promo.code,
        )
        await _checkout(
            session_factory,
            other_user,
            product="web_tarot",
            key=str(uuid.uuid4()),
            promo=other_promo.code,
        )
    async with session_factory() as session:
        before = (await session.execute(
            select(PromoReservation).where(PromoReservation.user_id == test_user.id)
        )).scalar_one()
        other_before = (await session.execute(
            select(PromoReservation).where(PromoReservation.user_id == other_user.id)
        )).scalar_one()
        before_provider_id = before.provider_payment_id
        before_payment_id = before.payment_id
        before_consumed_at = before.consumed_at
        other_before_snapshot = (
            other_before.id, other_before.state, other_before.provider_payment_id,
            other_before.payment_id, other_before.consumed_at,
        )
        pending_payment = await session.get(Payment, before_payment_id)
        other_pending_payment = await session.get(Payment, other_before.payment_id)
        stored_before = await session.get(PromoCode, promo.id)
        other_stored_before = await session.get(PromoCode, other_promo.id)
        user_before = await session.get(User, test_user.id)
        other_user_before = await session.get(User, other_user.id)
    assert before.state == "reserved" and before_consumed_at is None
    assert pending_payment is not None and pending_payment.status == "pending"
    assert other_pending_payment is not None and other_pending_payment.status == "pending"
    assert stored_before is not None and stored_before.used_count == 0 and stored_before.reserved_count == 1
    assert other_stored_before is not None and other_stored_before.used_count == 0 and other_stored_before.reserved_count == 1
    assert user_before is not None and not user_before.tarot_subscription
    assert other_user_before is not None and not other_user_before.tarot_subscription
    remote = SimpleNamespace(
        id=provider.id,
        status="succeeded",
        paid=True,
        amount=SimpleNamespace(value="292.50", currency="RUB"),
        metadata={"user_id": str(test_user.id), "payment_type": "web_tarot"},
    )
    with patch.object(settings, "app_env", "production"), patch(
        "core.services.payment.YooPayment.find_one", return_value=remote,
    ):
        first = await PaymentService.process_webhook(
            session_factory, {"event": "payment.succeeded", "object": {"id": provider.id}}
        )
        async with session_factory() as session:
            after_first_user = await session.get(User, test_user.id)
            after_first_reservation = await session.get(PromoReservation, before.id)
            after_first_payment = await session.get(Payment, before_payment_id)
            after_first_promo = await session.get(PromoCode, promo.id)
        assert after_first_user is not None
        after_first_snapshot = (
            after_first_user.tarot_subscription,
            after_first_user.tarot_subscription_until,
            after_first_reservation.state if after_first_reservation else None,
            after_first_reservation.consumed_at if after_first_reservation else None,
            after_first_payment.status if after_first_payment else None,
            after_first_promo.used_count if after_first_promo else None,
            after_first_promo.reserved_count if after_first_promo else None,
        )
        second = await PaymentService.process_webhook(
            session_factory, {"event": "payment.succeeded", "object": {"id": provider.id}}
        )
    async with session_factory() as session:
        reservation = (await session.execute(
            select(PromoReservation).where(PromoReservation.user_id == test_user.id)
        )).scalar_one()
        other_reservation = (await session.execute(
            select(PromoReservation).where(PromoReservation.user_id == other_user.id)
        )).scalar_one()
        stored_promo = await session.get(PromoCode, promo.id)
        other_stored_promo = await session.get(PromoCode, other_promo.id)
        payment = await session.get(Payment, before_payment_id)
        other_payment = await session.get(Payment, other_before.payment_id)
        user = await session.get(User, test_user.id)
        other_after_user = await session.get(User, other_user.id)
    assert first == {"ok": True} and second == {"ok": True, "idempotent": True}
    assert reservation.state == "consumed" and stored_promo.used_count == 1
    assert stored_promo.reserved_count == 0
    assert reservation.consumed_at is not None
    assert reservation.provider_payment_id == before_provider_id
    assert reservation.payment_id == before_payment_id
    assert payment is not None and payment.status == "succeeded"
    assert user is not None and user.tarot_subscription
    assert (
        user.tarot_subscription,
        user.tarot_subscription_until,
        reservation.state,
        reservation.consumed_at,
        payment.status if payment else None,
        stored_promo.used_count if stored_promo else None,
        stored_promo.reserved_count if stored_promo else None,
    ) == after_first_snapshot
    assert (
        other_reservation.id, other_reservation.state, other_reservation.provider_payment_id,
        other_reservation.payment_id, other_reservation.consumed_at,
    ) == other_before_snapshot
    assert other_stored_promo is not None and other_stored_promo.used_count == 0
    assert other_stored_promo.reserved_count == 1
    assert other_payment is not None and other_payment.status == "pending"
    assert other_after_user is not None and not other_after_user.tarot_subscription
    _assert_log_records_redacted(
        caplog.records,
        (provider.id, str(test_user.id), str(before.id), str(before_payment_id), promo.code),
    )


@pytest.mark.asyncio
async def test_verified_webhook_activates_matrix_once_and_queues_reserved_report(
    session_factory, test_user, caplog,
):
    promo = await _promo(session_factory, "MATRIX-WEBHOOK")
    provider = _provider("matrix-webhook-provider")
    with patch("core.services.payment.YooPayment.create", return_value=provider):
        await _checkout(
            session_factory, test_user, product="web_matrix", key=str(uuid.uuid4()), promo=promo.code
        )
    async with session_factory() as session:
        reservation = (await session.execute(select(PromoReservation))).scalar_one()
        payment = await session.get(Payment, reservation.payment_id)
        user = await session.get(User, test_user.id)
        stored_promo = await session.get(PromoCode, promo.id)
    assert reservation.state == "reserved" and reservation.report_token
    assert payment is not None and payment.status == "pending"
    assert user is not None and not user.has_matrix
    assert stored_promo is not None and stored_promo.used_count == 0
    remote = SimpleNamespace(
        id=provider.id,
        status="succeeded",
        paid=True,
        amount=SimpleNamespace(value="667.50", currency="RUB"),
        metadata={
            "user_id": str(test_user.id),
            "payment_type": "web_matrix",
            "report_token": reservation.report_token,
        },
    )
    with patch.object(settings, "app_env", "production"), patch(
        "core.services.payment.YooPayment.find_one", return_value=remote,
    ), patch("core.tasks.generate_full_report.delay") as queue_report:
        first = await PaymentService.process_webhook(
            session_factory, {"event": "payment.succeeded", "object": {"id": provider.id}}
        )
        second = await PaymentService.process_webhook(
            session_factory, {"event": "payment.succeeded", "object": {"id": provider.id}}
        )
    queue_report.assert_not_called()
    assert first == {"ok": True} and second == {"ok": True, "idempotent": True}
    async with session_factory() as session:
        after_reservation = await session.get(PromoReservation, reservation.id)
        after_payment = await session.get(Payment, payment.id)
        after_user = await session.get(User, test_user.id)
        after_promo = await session.get(PromoCode, promo.id)
        report = (await session.execute(select(Report).where(Report.token == reservation.report_token))).scalar_one()
        job = (await session.execute(select(ReportGenerationJob).where(ReportGenerationJob.report_id == report.id))).scalar_one()
    assert after_reservation is not None and after_reservation.state == "consumed"
    assert after_reservation.consumed_at is not None
    assert after_reservation.report_token == reservation.report_token
    assert after_reservation.provider_payment_id == provider.id
    assert after_reservation.payment_id == payment.id
    assert after_payment is not None and after_payment.status == "succeeded"
    assert after_user is not None and after_user.has_matrix
    assert after_promo is not None and after_promo.used_count == 1 and after_promo.reserved_count == 0
    assert report.payment_id == payment.id
    assert report.payment_state == ReportPaymentState.PAYMENT_CONFIRMED
    assert report.generation_state == ReportGenerationState.PENDING_DISPATCH
    assert job.state == ReportGenerationJobState.PENDING_DISPATCH
    assert job.celery_task_id is None and job.published_at is None
    _assert_log_records_redacted(
        caplog.records,
        (provider.id, str(test_user.id), str(reservation.id), str(payment.id), reservation.report_token, promo.code),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "paid", "amount", "currency", "reason"),
    [
        ("succeeded", True, "667.49", "RUB", "amount_or_currency_mismatch"),
        ("succeeded", True, "667.51", "RUB", "amount_or_currency_mismatch"),
        ("succeeded", True, "667.50", "USD", "amount_or_currency_mismatch"),
        ("pending", False, "667.50", "RUB", "not_succeeded"),
        ("succeeded", False, "667.50", "RUB", "not_succeeded"),
    ],
)
async def test_verified_webhook_invalid_provider_state_fails_closed(
    session_factory, test_user, caplog, status, paid, amount, currency, reason,
):
    promo = await _promo(session_factory, f"REJECT{uuid.uuid4().hex[:8].upper()}")
    provider = _provider(f"reject-{uuid.uuid4().hex}")
    with patch("core.services.payment.YooPayment.create", return_value=provider):
        await _checkout(
            session_factory, test_user, product="web_matrix", key=str(uuid.uuid4()), promo=promo.code
        )
    async with session_factory() as session:
        reservation = (await session.execute(select(PromoReservation))).scalar_one()
        payment = await session.get(Payment, reservation.payment_id)
    remote = SimpleNamespace(
        id=provider.id, status=status, paid=paid,
        amount=SimpleNamespace(value=amount, currency=currency),
        metadata={
            "user_id": str(test_user.id), "payment_type": "web_matrix",
            "report_token": reservation.report_token,
        },
    )
    with patch.object(settings, "app_env", "production"), patch(
        "core.services.payment.YooPayment.find_one", return_value=remote,
    ):
        result = await PaymentService.process_webhook(
            session_factory, {"event": "payment.succeeded", "object": {"id": provider.id}}
        )
    assert result == {"status": "ignored", "reason": reason}
    async with session_factory() as session:
        after_reservation = await session.get(PromoReservation, reservation.id)
        after_payment = await session.get(Payment, payment.id if payment else None)
        after_user = await session.get(User, test_user.id)
        after_promo = await session.get(PromoCode, promo.id)
    assert after_reservation is not None and after_reservation.state == "reserved"
    assert after_payment is not None and after_payment.status == "pending"
    assert after_user is not None and not after_user.has_matrix
    assert after_promo is not None and after_promo.used_count == 0 and after_promo.reserved_count == 1
    for sensitive in (provider.id, str(test_user.id), reservation.report_token, amount):
        assert sensitive not in caplog.text


@pytest.mark.asyncio
async def test_verified_orphan_webhook_fails_closed_without_creating_local_state(
    session_factory, test_user, caplog,
):
    orphan_id = f"orphan-{uuid.uuid4().hex}"
    remote = SimpleNamespace(
        id=orphan_id,
        status="succeeded",
        paid=True,
        amount=SimpleNamespace(value="667.50", currency="RUB"),
        metadata={
            "user_id": str(test_user.id), "payment_type": "web_matrix", "report_token": "orphan-token",
        },
    )
    with patch.object(settings, "app_env", "production"), patch(
        "core.services.payment.YooPayment.find_one", return_value=remote,
    ):
        result = await PaymentService.process_webhook(
            session_factory, {"event": "payment.succeeded", "object": {"id": orphan_id}}
        )
    assert result == {"status": "ignored", "reason": "payment_not_found"}
    async with session_factory() as session:
        payments = (await session.execute(select(Payment))).scalars().all()
        reservations = (await session.execute(select(PromoReservation))).scalars().all()
    assert payments == [] and reservations == []
    _assert_log_records_redacted(caplog.records, (orphan_id, str(test_user.id), "orphan-token"))


def test_frontend_callers_keep_uuid_in_session_only():
    profile = (Path(__file__).parents[2] / "frontend/pwa/app/profile.html").read_text(encoding="utf-8")
    tarot = (Path(__file__).parents[2] / "frontend/pwa/app/tarot.html").read_text(encoding="utf-8")
    for page in (profile, tarot):
        assert "crypto.randomUUID()" in page
        assert "sessionStorage" in page
        assert "'Idempotency-Key'" in page
        assert "localStorage.setItem('nura_checkout_action" not in page
