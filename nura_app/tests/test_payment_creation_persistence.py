"""Telegram checkout persistence contract with real handlers, services, and DB."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.handlers.payment import initiate_subscription, initiate_tarot_subscription
from core.config import settings
from core.models import User
from core.repositories.payment import PaymentRepository
from core.repositories.user import UserRepository
from core.services.payment import PaymentService


@pytest_asyncio.fixture
async def session_factory(db_engine):
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


def created_provider_payment(payment_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=payment_id,
        status="pending",
        confirmation=SimpleNamespace(
            confirmation_url=f"https://checkout.invalid/{payment_id}",
        ),
        payment_method=SimpleNamespace(id="payment-method-id"),
    )


def verified_provider_payment(payment_id: str, metadata: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=payment_id,
        status="succeeded",
        paid=True,
        metadata=metadata,
        amount=SimpleNamespace(
            value=f"{settings.tarot_subscription_price_rub}.00",
            currency="RUB",
        ),
    )


def callback(telegram_id: int, callback_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=callback_id,
        from_user=SimpleNamespace(id=telegram_id),
        answer=AsyncMock(),
        message=SimpleNamespace(
            edit_text=AsyncMock(),
            answer=AsyncMock(),
        ),
    )


def payment_handler(payment_type: str):
    if payment_type == "subscription":
        return initiate_subscription
    if payment_type == "tarot":
        return initiate_tarot_subscription
    raise ValueError("Unsupported payment type")


@pytest.mark.asyncio
@pytest.mark.parametrize("payment_type", ["subscription", "tarot"])
async def test_telegram_checkout_persists_payment_before_response(
    session_factory, test_user, payment_type,
) -> None:
    provider = created_provider_payment(f"provider-{payment_type}")
    checkout_callback = callback(test_user.telegram_id, f"callback-{payment_type}")
    payment_repo = PaymentRepository(session_factory)

    async def assert_payment_exists_before_response(*args, **kwargs) -> None:
        persisted = await payment_repo.get_by_yookassa_id(provider.id)
        assert persisted is not None
        assert persisted.user_id == test_user.id
        assert persisted.payment_type == payment_type
        assert persisted.amount == settings.tarot_subscription_price_rub
        assert persisted.status == "pending"

    checkout_callback.message.edit_text.side_effect = assert_payment_exists_before_response

    with patch.object(settings, "test_mode", False), patch(
        "bot.handlers.payment.get_async_sessionmaker", return_value=session_factory,
    ), patch(
        "core.services.payment.YooPayment.create", return_value=provider,
    ) as create:
        await payment_handler(payment_type)(checkout_callback)

    body, idempotence_key = create.call_args.args
    assert len(idempotence_key) == 32
    assert body["amount"] == {
        "value": f"{settings.tarot_subscription_price_rub}.00",
        "currency": "RUB",
    }
    assert body["metadata"] == {
        "telegram_id": test_user.telegram_id,
        "payment_type": payment_type,
        **({"subscription": "true"} if payment_type == "subscription" else {}),
    }
    checkout_callback.message.edit_text.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("payment_type", ["subscription", "tarot"])
async def test_verified_webhook_activates_persisted_telegram_payment_once(
    session_factory, test_user, payment_type,
) -> None:
    provider = created_provider_payment(f"verified-{payment_type}")
    checkout_callback = callback(test_user.telegram_id, f"verified-callback-{payment_type}")

    with patch.object(settings, "test_mode", False), patch(
        "bot.handlers.payment.get_async_sessionmaker", return_value=session_factory,
    ), patch("core.services.payment.YooPayment.create", return_value=provider):
        await payment_handler(payment_type)(checkout_callback)

    metadata = {
        "telegram_id": test_user.telegram_id,
        "payment_type": payment_type,
    }
    if payment_type == "subscription":
        metadata["subscription"] = "true"
    remote = verified_provider_payment(provider.id, metadata)
    webhook = {"event": "payment.succeeded", "object": {"id": provider.id}}

    with patch.object(settings, "app_env", "production"), patch(
        "core.services.payment.YooPayment.find_one", return_value=remote,
    ):
        first = await PaymentService.process_webhook(session_factory, webhook)
        user_after_first = await UserRepository(session_factory).get(test_user.id)
        second = await PaymentService.process_webhook(session_factory, webhook)
        user_after_second = await UserRepository(session_factory).get(test_user.id)

    assert first == {"ok": True}
    assert second == {"ok": True, "idempotent": True}
    assert user_after_first is not None and user_after_second is not None
    if payment_type == "subscription":
        assert user_after_first.subscription_status == "premium"
        assert user_after_first.subscription_until == user_after_second.subscription_until
    else:
        assert user_after_first.tarot_subscription is True
        assert user_after_first.tarot_subscription_until == user_after_second.tarot_subscription_until
    persisted = await PaymentRepository(session_factory).get_by_yookassa_id(provider.id)
    assert persisted is not None and persisted.status == "succeeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("payment_type", ["subscription", "tarot"])
async def test_repeated_callback_with_same_provider_payment_keeps_one_local_record(
    session_factory, test_user, payment_type,
) -> None:
    provider = created_provider_payment(f"duplicate-{payment_type}")
    checkout_callback = callback(test_user.telegram_id, f"duplicate-callback-{payment_type}")

    with patch.object(settings, "test_mode", False), patch(
        "bot.handlers.payment.get_async_sessionmaker", return_value=session_factory,
    ), patch(
        "core.services.payment.YooPayment.create", return_value=provider,
    ) as create:
        await payment_handler(payment_type)(checkout_callback)
        await payment_handler(payment_type)(checkout_callback)

    payments = await PaymentRepository(session_factory).get_all()
    assert len(payments) == 1
    assert payments[0].yookassa_id == provider.id
    assert create.call_count == 2
    assert create.call_args_list[0].args[1] == create.call_args_list[1].args[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("provider-secret"), TimeoutError("provider-timeout")])
async def test_provider_creation_failure_never_persists_or_exposes_details(
    session_factory, test_user, failure, caplog,
) -> None:
    checkout_callback = callback(test_user.telegram_id, "provider-failure")

    with patch.object(settings, "test_mode", False), patch(
        "bot.handlers.payment.get_async_sessionmaker", return_value=session_factory,
    ), patch("core.services.payment.YooPayment.create", side_effect=failure):
        await initiate_subscription(checkout_callback)

    assert await PaymentRepository(session_factory).get_all() == []
    assert "provider-secret" not in caplog.text
    assert "provider-timeout" not in caplog.text
    assert "checkout.invalid" not in str(checkout_callback.message.edit_text.await_args)


class CommitFailingSession(AsyncSession):
    rollback_calls = 0

    async def commit(self) -> None:
        raise RuntimeError("db-write-secret")

    async def rollback(self) -> None:
        type(self).rollback_calls += 1
        await super().rollback()


@pytest.mark.asyncio
async def test_database_failure_rolls_back_and_hides_checkout_url(
    db_engine, test_user, caplog,
) -> None:
    CommitFailingSession.rollback_calls = 0
    failing_factory = async_sessionmaker(
        db_engine,
        class_=CommitFailingSession,
        expire_on_commit=False,
    )
    provider = created_provider_payment("db-failure")
    checkout_callback = callback(test_user.telegram_id, "db-failure-callback")

    with patch.object(settings, "test_mode", False), patch(
        "bot.handlers.payment.get_async_sessionmaker", return_value=failing_factory,
    ), patch("core.services.payment.YooPayment.create", return_value=provider):
        await initiate_subscription(checkout_callback)

    assert CommitFailingSession.rollback_calls >= 1
    assert await PaymentRepository(failing_factory).get_all() == []
    assert "db-write-secret" not in caplog.text
    assert provider.confirmation.confirmation_url not in str(
        checkout_callback.message.edit_text.await_args,
    )


@pytest.mark.asyncio
async def test_cross_account_webhook_does_not_activate_other_user(
    session_factory, test_user,
) -> None:
    other_user = User(
        id=uuid.uuid4(),
        telegram_id=987654321,
        username="other-user",
        first_name="Other",
        birth_date="02.02.2000",
    )
    async with session_factory() as session:
        session.add(other_user)
        await session.commit()

    provider = created_provider_payment("cross-account")
    checkout_callback = callback(test_user.telegram_id, "cross-account-callback")
    with patch.object(settings, "test_mode", False), patch(
        "bot.handlers.payment.get_async_sessionmaker", return_value=session_factory,
    ), patch("core.services.payment.YooPayment.create", return_value=provider):
        await initiate_subscription(checkout_callback)

    remote = verified_provider_payment(
        provider.id,
        {"telegram_id": other_user.telegram_id, "payment_type": "subscription"},
    )
    with patch.object(settings, "app_env", "production"), patch(
        "core.services.payment.YooPayment.find_one", return_value=remote,
    ):
        result = await PaymentService.process_webhook(
            session_factory,
            {"event": "payment.succeeded", "object": {"id": provider.id}},
        )

    assert result == {"status": "needs_review", "detail": "Payment user_id mismatch"}
    payment = await PaymentRepository(session_factory).get_by_yookassa_id(provider.id)
    first_user = await UserRepository(session_factory).get(test_user.id)
    second_user = await UserRepository(session_factory).get(other_user.id)
    assert payment is not None and payment.status == "pending"
    assert first_user is not None and first_user.subscription_status == "free"
    assert second_user is not None and second_user.subscription_status == "free"


@pytest.mark.asyncio
async def test_orphan_provider_webhook_and_unknown_plan_fail_closed(session_factory, test_user) -> None:
    remote = verified_provider_payment(
        "orphan-provider-payment",
        {"telegram_id": test_user.telegram_id, "payment_type": "subscription"},
    )
    with patch.object(settings, "app_env", "production"), patch(
        "core.services.payment.YooPayment.find_one", return_value=remote,
    ):
        with pytest.raises(ValueError, match="Payment not found"):
            await PaymentService.process_webhook(
                session_factory,
                {"event": "payment.succeeded", "object": {"id": remote.id}},
            )

    with patch("core.services.payment.YooPayment.create") as create:
        with pytest.raises(ValueError, match="Unsupported Telegram payment type"):
            await PaymentService.create_telegram_payment(
                session_factory,
                user_id=test_user.id,
                telegram_id=test_user.telegram_id,
                payment_type="unknown",  # type: ignore[arg-type]
                idempotence_key="unknown-plan",
            )
    create.assert_not_called()
