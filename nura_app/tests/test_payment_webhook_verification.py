"""Fail-closed production contract tests for YooKassa webhook verification."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import api.deps as deps_mod
from api import main as api_main
from api.routes import payment as payment_route
from core.config import Settings, settings
from core.repositories.payment import PaymentRepository
from core.repositories.user import UserRepository
from core.services.payment import PaymentService


@pytest_asyncio.fixture
async def session_factory(db_engine):
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def pending_subscription(session_factory, test_user):
    payment = await PaymentRepository(session_factory).create(
        user_id=test_user.id,
        amount=390,
        yookassa_id="yo-verified-001",
        payment_type="subscription",
    )
    return test_user, payment


def provider_payment(
    payment_id: str,
    metadata: dict[str, str] | object,
    *,
    status: str = "succeeded",
    paid: bool = True,
    amount: str = "390.00",
    currency: str = "RUB",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=payment_id,
        status=status,
        paid=paid,
        metadata=metadata,
        amount=SimpleNamespace(value=amount, currency=currency),
    )


async def assert_pending_without_entitlement(session_factory, user_id) -> None:
    user = await UserRepository(session_factory).get(user_id)
    payment = await PaymentRepository(session_factory).get_by_yookassa_id("yo-verified-001")
    assert user is not None and user.subscription_status == "free"
    assert user.subscription_until is None
    assert payment is not None and payment.status == "pending"


def webhook_payload(telegram_id: int) -> dict:
    return {
        "event": "payment.succeeded",
        "object": {
            "id": "yo-verified-001",
            "metadata": {"telegram_id": str(telegram_id)},
        },
    }


def test_production_rejects_disabled_provider_verification_at_settings_load() -> None:
    with pytest.raises(ValidationError, match="production_payment_webhook_verification_required"):
        Settings(
            app_env="production",
            yookassa_verify_on_webhook=False,
        )

    assert Settings(
        app_env="production",
        secret_key="test-only-non-default-secret-at-least-32-chars",
        redis_url="redis://:test-password@redis:6379/0",
        celery_broker_url="redis://:test-password@redis:6379/1",
        celery_result_backend="redis://:test-password@redis:6379/2",
        yookassa_verify_on_webhook=True,
        yookassa_shop_id="test-shop",
        yookassa_secret_key="test-secret",
    ).payment_webhook_configuration_error is None


def test_production_missing_credentials_fails_startup_but_development_is_compatible() -> None:
    with pytest.raises(
        ValidationError, match="production_payment_webhook_credentials_required"
    ):
        Settings(
            app_env="production",
            secret_key="test-only-non-default-secret-at-least-32-chars",
            redis_url="redis://:test-password@redis:6379/0",
            celery_broker_url="redis://:test-password@redis:6379/1",
            celery_result_backend="redis://:test-password@redis:6379/2",
            yookassa_verify_on_webhook=True,
        )
    development = Settings(app_env="development", yookassa_verify_on_webhook=False)

    assert development.payment_webhook_configuration_error is None
    with patch.object(api_main, "settings", development):
        assert api_main.payment_webhook_readiness_status() == "ok"


@pytest.mark.asyncio
async def test_production_guard_still_looks_up_provider_when_runtime_flag_is_false(
    session_factory, pending_subscription,
) -> None:
    user, _ = pending_subscription
    remote = provider_payment(
        "yo-verified-001", {"telegram_id": str(user.telegram_id)},
    )

    with patch.object(settings, "app_env", "production"), patch.object(
        settings, "yookassa_verify_on_webhook", False,
    ), patch("core.services.payment.YooPayment.find_one", return_value=remote) as lookup:
        result = await PaymentService.process_webhook(session_factory, webhook_payload(user.telegram_id))

    assert result == {"ok": True}
    lookup.assert_called_once_with("yo-verified-001")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("remote", "expected_reason"),
    [
        (None, "not_succeeded"),
        (provider_payment("yo-verified-001", {}, status="pending", paid=False), "not_succeeded"),
        (provider_payment("yo-verified-001", object()), "invalid_provider_response"),
        (provider_payment("yo-verified-001", {}, amount="1.00"), "amount_or_currency_mismatch"),
        (provider_payment("yo-verified-001", {}, currency="USD"), "amount_or_currency_mismatch"),
    ],
)
async def test_unverified_or_invalid_provider_response_never_activates_subscription(
    session_factory, pending_subscription, remote, expected_reason,
) -> None:
    user, _ = pending_subscription
    if remote is not None and isinstance(remote.metadata, dict):
        remote.metadata = {"telegram_id": str(user.telegram_id)}

    with patch.object(settings, "app_env", "production"), patch(
        "core.services.payment.YooPayment.find_one", return_value=remote,
    ):
        result = await PaymentService.process_webhook(session_factory, webhook_payload(user.telegram_id))

    assert result == {"status": "ignored", "reason": expected_reason}
    await assert_pending_without_entitlement(session_factory, user.id)


@pytest.mark.asyncio
async def test_provider_timeout_is_redacted_and_retry_safe(
    session_factory, pending_subscription, caplog,
) -> None:
    user, _ = pending_subscription
    secret_marker = "provider-secret-must-not-leak"

    with patch.object(settings, "app_env", "production"), patch(
        "core.services.payment.YooPayment.find_one",
        side_effect=RuntimeError(secret_marker),
    ):
        first = await PaymentService.process_webhook(session_factory, webhook_payload(user.telegram_id))
        second = await PaymentService.process_webhook(session_factory, webhook_payload(user.telegram_id))

    assert first == second == {"status": "ignored", "reason": "verification_unavailable"}
    assert secret_marker not in caplog.text
    await assert_pending_without_entitlement(session_factory, user.id)


@pytest.mark.asyncio
async def test_provider_5xx_never_activates_subscription(
    session_factory, pending_subscription,
) -> None:
    user, _ = pending_subscription

    with patch.object(settings, "app_env", "production"), patch(
        "core.services.payment.YooPayment.find_one",
        side_effect=RuntimeError("provider 5xx"),
    ):
        result = await PaymentService.process_webhook(session_factory, webhook_payload(user.telegram_id))

    assert result == {"status": "ignored", "reason": "verification_unavailable"}
    await assert_pending_without_entitlement(session_factory, user.id)


@pytest.mark.asyncio
async def test_provider_timeout_returns_retryable_error_without_exposing_details(
    session_factory, pending_subscription,
) -> None:
    user, _ = pending_subscription
    app = FastAPI()
    app.include_router(payment_route.router)
    app.state.limiter = None

    deps_mod.limiter.enabled = False
    try:
        with patch.object(settings, "app_env", "production"), patch(
            "api.routes.payment.get_async_sessionmaker", return_value=session_factory,
        ), patch(
            "core.services.payment.YooPayment.find_one",
            side_effect=TimeoutError("provider timeout with secret"),
        ):
            response = TestClient(app).post(
                "/api/v1/payment/webhook",
                json=webhook_payload(user.telegram_id),
            )
    finally:
        deps_mod.limiter.enabled = True

    assert response.status_code == 503
    assert response.json() == {"detail": "payment_verification_unavailable"}
    await assert_pending_without_entitlement(session_factory, user.id)


@pytest.mark.parametrize(
    ("body", "content_type"),
    [(b"not-json", "application/json"), (b"[]", "application/json")],
)
def test_malformed_webhook_payload_is_rejected_without_processing(
    body: bytes, content_type: str
) -> None:
    app = FastAPI()
    app.include_router(payment_route.router)
    app.state.limiter = None

    deps_mod.limiter.enabled = False
    try:
        with patch.object(
            PaymentService, "process_webhook"
        ) as process_webhook:
            response = TestClient(app).post(
                "/api/v1/payment/webhook",
                content=body,
                headers={"Content-Type": content_type},
            )
    finally:
        deps_mod.limiter.enabled = True

    assert response.status_code == 400
    assert response.json() == {"detail": "invalid_webhook_payload"}
    process_webhook.assert_not_called()


@pytest.mark.asyncio
async def test_provider_metadata_is_the_only_account_mapping_source(
    session_factory, pending_subscription,
) -> None:
    user, _ = pending_subscription
    remote = provider_payment("yo-verified-001", {"telegram_id": "999999999"})

    with patch.object(settings, "app_env", "production"), patch(
        "core.services.payment.YooPayment.find_one", return_value=remote,
    ):
        result = await PaymentService.process_webhook(session_factory, webhook_payload(user.telegram_id))

    assert result == {"status": "needs_review", "detail": "User not found"}
    await assert_pending_without_entitlement(session_factory, user.id)


@pytest.mark.asyncio
async def test_allowlisted_webhook_still_uses_provider_lookup(
    session_factory, pending_subscription,
) -> None:
    user, _ = pending_subscription
    app = FastAPI()
    app.include_router(payment_route.router)
    app.state.limiter = None
    remote = provider_payment("yo-verified-001", {"telegram_id": str(user.telegram_id)})

    deps_mod.limiter.enabled = False
    try:
        with patch.object(settings, "app_env", "production"), patch.object(
            settings, "yookassa_verify_on_webhook", False,
        ), patch.object(settings, "yookassa_ip_whitelist", "203.0.113.0/24"), patch(
            "api.routes.payment.get_async_sessionmaker", return_value=session_factory,
        ), patch(
            "core.services.payment.YooPayment.find_one", return_value=remote,
        ) as lookup:
            response = TestClient(app).post(
                "/api/v1/payment/webhook",
                json=webhook_payload(user.telegram_id),
                headers={"X-Forwarded-For": "203.0.113.10"},
            )
    finally:
        deps_mod.limiter.enabled = True

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    lookup.assert_called_once_with("yo-verified-001")
