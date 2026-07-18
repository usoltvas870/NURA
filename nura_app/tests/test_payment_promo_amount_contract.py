"""Server-side promo amount contract for web checkout and verified webhooks."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import api.deps as deps_mod
from api.routes import web
from core.config import settings
from core.models import Payment, PromoCode, User
from core.repositories.payment import PaymentRepository
from core.services.payment import PaymentService


@pytest_asyncio.fixture
async def session_factory(db_engine):
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


async def create_promo(
    session_factory,
    *,
    code: str = "PROMO25",
    discount_percent: int = 25,
    max_uses: int | None = 3,
    expires_at: datetime | None = None,
    is_active: bool = True,
) -> PromoCode:
    promo = PromoCode(
        id=uuid.uuid4(),
        code=code,
        discount_percent=discount_percent,
        max_uses=max_uses,
        used_count=0,
        reserved_count=0,
        expires_at=expires_at,
        is_active=is_active,
    )
    async with session_factory() as session:
        session.add(promo)
        await session.commit()
        await session.refresh(promo)
    return promo


async def read_promo(session_factory, promo_id: uuid.UUID) -> PromoCode | None:
    async with session_factory() as session:
        return await session.get(PromoCode, promo_id)


async def clear_birth_date(session_factory, user_id: uuid.UUID) -> None:
    async with session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        user.birth_date = None
        await session.commit()


def provider_payment(payment_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=payment_id,
        status="pending",
        confirmation=SimpleNamespace(
            confirmation_url=f"https://checkout.invalid/{payment_id}",
        ),
        payment_method=SimpleNamespace(id="payment-method-id"),
    )


def verified_provider_payment(
    payment_id: str,
    metadata: dict,
    *,
    amount: str,
    currency: str = "RUB",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=payment_id,
        status="succeeded",
        paid=True,
        metadata=metadata,
        amount=SimpleNamespace(value=amount, currency=currency),
    )


async def run_checkout(
    product: str,
    user,
    promo_code: str | None = None,
    **extra: int,
):
    deps_mod.limiter.enabled = False
    try:
        request = SimpleNamespace(headers={"Idempotency-Key": str(uuid.uuid4())})
        if product == "web_matrix":
            body = web.CreatePaymentRequest(promo_code=promo_code, **extra)
            return await web.create_payment(request, body, user)
        body = web.SubscribeRequest(promo_code=promo_code, **extra)
        return await web.subscribe_tarot(request, body, user)
    finally:
        deps_mod.limiter.enabled = True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("product", "payment_type", "base_amount"),
    [
        ("web_matrix", "web_matrix", 890),
        ("web_tarot", "web_tarot", 390),
    ],
)
async def test_valid_promo_uses_one_amount_for_provider_local_payment_and_webhook(
    session_factory, test_user, product, payment_type, base_amount,
) -> None:
    await clear_birth_date(session_factory, test_user.id)
    promo = await create_promo(session_factory)
    provider = provider_payment(f"promo-{product}")

    with patch("api.routes.web.get_async_sessionmaker", return_value=session_factory), patch(
        "core.services.payment.YooPayment.create", return_value=provider,
    ) as create:
        response = await run_checkout(product, test_user, promo.code)

    expected_amount_kopecks = (
        base_amount * 100 * (100 - promo.discount_percent) // 100
    )
    expected_amount = f"{expected_amount_kopecks // 100}.{expected_amount_kopecks % 100:02d}"
    assert response.payment_url == provider.confirmation.confirmation_url
    request_body = create.call_args.args[0]
    assert request_body["amount"] == {"value": expected_amount, "currency": "RUB"}
    assert "amount" not in request_body["metadata"]
    assert "discount" not in request_body["metadata"]

    payment = await PaymentRepository(session_factory).get_by_yookassa_id(provider.id)
    assert payment is not None
    assert payment.user_id == test_user.id
    assert payment.payment_type == payment_type
    assert payment.amount_kopecks == expected_amount_kopecks
    assert payment.promo_code_id == promo.id
    assert payment.status == "pending"
    reserved = await read_promo(session_factory, promo.id)
    assert reserved is not None and reserved.used_count == 0 and reserved.reserved_count == 1

    remote = verified_provider_payment(
        provider.id,
        request_body["metadata"],
        amount=expected_amount,
    )
    webhook = {"event": "payment.succeeded", "object": {"id": provider.id}}
    with patch.object(settings, "app_env", "production"), patch(
        "core.services.payment.YooPayment.find_one", return_value=remote,
    ):
        first = await PaymentService.process_webhook(session_factory, webhook)
        second = await PaymentService.process_webhook(session_factory, webhook)

    assert first == {"ok": True}
    assert second == {"ok": True, "idempotent": True}
    consumed = await read_promo(session_factory, promo.id)
    payment = await PaymentRepository(session_factory).get_by_yookassa_id(provider.id)
    assert consumed is not None and consumed.used_count == 1 and consumed.reserved_count == 0
    assert payment is not None and payment.promo_consumed_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("promo_kwargs", "detail"),
    [
        ({"is_active": False}, "Промокод недействителен"),
        ({"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}, "Промокод истёк"),
        ({"max_uses": 1}, "Промокод исчерпан"),
    ],
)
async def test_invalid_expired_or_exhausted_promo_does_not_create_discounted_payment(
    session_factory, test_user, promo_kwargs, detail,
) -> None:
    promo = await create_promo(session_factory, **promo_kwargs)
    if detail == "Промокод исчерпан":
        async with session_factory() as session:
            stored = await session.get(PromoCode, promo.id)
            stored.used_count = 1
            await session.commit()

    with patch("api.routes.web.get_async_sessionmaker", return_value=session_factory), patch(
        "core.services.payment.YooPayment.create",
    ) as create:
        with pytest.raises(HTTPException) as error:
            await run_checkout("web_matrix", test_user, promo.code)

    assert error.value.status_code == 400
    assert error.value.detail == detail
    create.assert_not_called()
    assert await PaymentRepository(session_factory).get_all() == []
    assert (await read_promo(session_factory, promo.id)).used_count == (1 if detail == "Промокод исчерпан" else 0)


@pytest.mark.asyncio
async def test_limited_promo_reservation_prevents_overbooked_checkout(
    session_factory, test_user,
) -> None:
    await clear_birth_date(session_factory, test_user.id)
    promo = await create_promo(session_factory, max_uses=1)
    provider = provider_payment("reserved-promo")

    with patch("api.routes.web.get_async_sessionmaker", return_value=session_factory), patch(
        "core.services.payment.YooPayment.create", return_value=provider,
    ) as create:
        await run_checkout("web_matrix", test_user, promo.code)
        with pytest.raises(HTTPException) as error:
            await run_checkout("web_matrix", test_user, promo.code)

    assert error.value.status_code == 400
    create.assert_called_once()
    reserved = await read_promo(session_factory, promo.id)
    assert reserved is not None and reserved.used_count == 0 and reserved.reserved_count == 1

    remote = verified_provider_payment(
        provider.id,
        create.call_args.args[0]["metadata"],
        amount="667.50",
    )
    with patch.object(settings, "app_env", "production"), patch(
        "core.services.payment.YooPayment.find_one", return_value=remote,
    ):
        assert await PaymentService.process_webhook(
            session_factory,
            {"event": "payment.succeeded", "object": {"id": provider.id}},
        ) == {"ok": True}

    consumed = await read_promo(session_factory, promo.id)
    assert consumed is not None and consumed.used_count == 1 and consumed.reserved_count == 0


@pytest.mark.asyncio
async def test_client_amount_and_discount_are_ignored_and_no_promo_keeps_base_price(
    session_factory, test_user,
) -> None:
    provider = provider_payment("base-price")
    with patch("api.routes.web.get_async_sessionmaker", return_value=session_factory), patch(
        "core.services.payment.YooPayment.create", return_value=provider,
    ) as create:
        response = await run_checkout(
            "web_tarot", test_user, amount=1, discount_percent=99,
        )

    assert response.payment_url == provider.confirmation.confirmation_url
    assert create.call_args.args[0]["amount"] == {"value": "390.00", "currency": "RUB"}
    payment = await PaymentRepository(session_factory).get_by_yookassa_id(provider.id)
    assert payment is not None and payment.amount_kopecks == 39000 and payment.promo_code_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_amount", "currency"),
    [("890.00", "RUB"), ("1.00", "RUB"), ("667.50", "USD")],
)
async def test_wrong_provider_amount_or_currency_remains_fail_closed(
    session_factory, test_user, provider_amount, currency,
) -> None:
    await clear_birth_date(session_factory, test_user.id)
    promo = await create_promo(session_factory, discount_percent=25)
    provider = provider_payment("mismatch")
    with patch("api.routes.web.get_async_sessionmaker", return_value=session_factory), patch(
        "core.services.payment.YooPayment.create", return_value=provider,
    ) as create:
        assert (await run_checkout("web_matrix", test_user, promo.code)).payment_url

    remote = verified_provider_payment(
        provider.id,
        create.call_args.args[0]["metadata"],
        amount=provider_amount,
        currency=currency,
    )
    with patch.object(settings, "app_env", "production"), patch(
        "core.services.payment.YooPayment.find_one", return_value=remote,
    ):
        result = await PaymentService.process_webhook(
            session_factory,
            {"event": "payment.succeeded", "object": {"id": provider.id}},
        )

    payment = await PaymentRepository(session_factory).get_by_yookassa_id(provider.id)
    assert result == {"status": "ignored", "reason": "amount_or_currency_mismatch"}
    assert payment is not None and payment.status == "pending" and payment.promo_consumed_at is None
    stored = await read_promo(session_factory, promo.id)
    assert stored is not None and stored.used_count == 0 and stored.reserved_count == 1


@pytest.mark.asyncio
async def test_provider_failure_does_not_consume_promo_or_leak_details(
    session_factory, test_user, caplog,
) -> None:
    promo = await create_promo(session_factory)
    secret = "provider-secret-must-not-leak"
    with patch("api.routes.web.get_async_sessionmaker", return_value=session_factory), patch(
        "core.services.payment.YooPayment.create", side_effect=RuntimeError(secret),
    ):
        with pytest.raises(HTTPException) as error:
            await run_checkout("web_tarot", test_user, promo.code)

    assert error.value.status_code == 503
    assert error.value.detail == "Платёжный сервис недоступен"
    assert secret not in caplog.text
    assert await PaymentRepository(session_factory).get_all() == []
    stored = await read_promo(session_factory, promo.id)
    assert stored is not None and stored.used_count == 0 and stored.reserved_count == 1


class CommitFailingSession(AsyncSession):
    async def commit(self) -> None:
        if any(isinstance(item, Payment) for item in self.new):
            raise RuntimeError("database-secret-must-not-leak")
        await super().commit()


@pytest.mark.asyncio
async def test_database_failure_does_not_return_url_or_consume_promo(
    db_engine, session_factory, test_user, caplog,
) -> None:
    promo = await create_promo(session_factory)
    failing_factory = async_sessionmaker(
        db_engine,
        class_=CommitFailingSession,
        expire_on_commit=False,
    )
    provider = provider_payment("database-failure")
    with patch("api.routes.web.get_async_sessionmaker", return_value=failing_factory), patch(
        "core.services.payment.YooPayment.create", return_value=provider,
    ):
        with pytest.raises(HTTPException) as error:
            await run_checkout("web_tarot", test_user, promo.code)

    assert error.value.status_code == 503
    assert error.value.detail == "Платёжный сервис недоступен"
    assert "database-secret-must-not-leak" not in caplog.text
    assert await PaymentRepository(session_factory).get_all() == []
    stored = await read_promo(session_factory, promo.id)
    assert stored is not None and stored.used_count == 0 and stored.reserved_count == 1
