"""No payment or entitlement path is reachable while prelaunch payments are off."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api import main as api_main
from api.routes import admin_api
from bot.handlers.payment import buy_matrix
from bot.keyboards.tarot_keyboard import tarot_menu_keyboard
from core.config import settings
from core.models import Order, PaymentAttempt
from core.services.full_matrix_checkout import FullMatrixCheckoutService
from core.services.payment import PaymentService
from core.tasks import charge_recurring_subscriptions


@pytest.fixture(autouse=True)
def payments_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "prelaunch_owner_only", True)
    monkeypatch.setattr(settings, "prelaunch_telegram_allowed_user_ids", "101")
    monkeypatch.setattr(settings, "payments_enabled", False)
    monkeypatch.setattr(settings, "test_mode", False)
    monkeypatch.setattr(settings, "enable_internal_payment_shortcut", False)


@pytest.mark.asyncio
async def test_buy_matrix_stops_before_user_lookup_or_checkout() -> None:
    callback = SimpleNamespace(
        answer=AsyncMock(),
        from_user=SimpleNamespace(id=101),
        message=SimpleNamespace(edit_text=AsyncMock()),
    )

    with (
        patch("bot.handlers.payment._get_user", new_callable=AsyncMock) as get_user,
        patch(
            "bot.handlers.payment.FullMatrixCheckoutService"
        ) as checkout_service,
    ):
        await buy_matrix(callback)

    get_user.assert_not_awaited()
    checkout_service.assert_not_called()
    text = callback.message.edit_text.await_args.args[0]
    assert text == "Оплата пока недоступна — полный запуск готовится."


@pytest.mark.asyncio
async def test_full_matrix_service_creates_no_order_or_attempt_when_disabled(
    db_engine,
    test_user,
) -> None:
    factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    provider = AsyncMock()
    service = FullMatrixCheckoutService(factory, provider=provider)

    with pytest.raises(ValueError, match="payments_disabled"):
        await service.create_or_get_order(user_id=test_user.id)

    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Order)) == 0
        assert (
            await session.scalar(select(func.count()).select_from(PaymentAttempt))
            == 0
        )
    provider.create_payment.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_webhook_is_blocked_before_provider_lookup(
    db_engine,
) -> None:
    factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    with patch("core.services.payment.YooPayment.find_one") as provider_lookup:
        with pytest.raises(RuntimeError, match="payments_disabled"):
            await PaymentService.process_webhook(
                factory,
                {"event": "payment.succeeded", "object": {"id": "ignored"}},
            )

    provider_lookup.assert_not_called()


def test_payment_routes_fail_closed_before_processing() -> None:
    with TestClient(api_main.app) as client, patch(
        "api.routes.payment.FullMatrixCheckoutService"
    ) as checkout_service, patch(
        "api.routes.payment.PaymentService.process_webhook",
        new_callable=AsyncMock,
    ) as legacy_webhook:
        webhook = client.post(
            "/api/v1/payment/webhook",
            json={"event": "payment.succeeded", "object": {"id": "ignored"}},
        )
        returned = client.get(
            f"/api/v1/payment/full-matrix/return/{'a' * 40}"
        )

    assert webhook.status_code == 503
    assert webhook.json() == {"detail": "payments_disabled"}
    assert returned.status_code == 404
    checkout_service.assert_not_called()
    legacy_webhook.assert_not_awaited()


def test_recurring_charge_task_is_disabled_without_database_or_provider_call() -> None:
    with patch(
        "core.tasks._charge_recurring_subscriptions_async",
        new_callable=AsyncMock,
    ) as recurring:
        result = charge_recurring_subscriptions.run()

    assert result == {
        "charged": 0,
        "failed": 0,
        "total": 0,
        "disabled": True,
    }
    recurring.assert_not_awaited()


def test_pwa_hides_payment_ctas_when_runtime_switch_is_off() -> None:
    app_root = Path(__file__).parents[2] / "frontend" / "pwa" / "app"
    home = (app_root / "index.html").read_text(encoding="utf-8")
    profile = (app_root / "profile.html").read_text(encoding="utf-8")
    tarot = (app_root / "tarot.html").read_text(encoding="utf-8")

    assert "var paymentsEnabled = d.payments_enabled !== false;" in home
    assert "Оплата пока недоступна — полный запуск готовится." in profile
    assert "if (state.user && state.user.payments_enabled === false) return;" in profile
    assert "var paymentsEnabled = true;" in tarot
    assert "if (!paymentsEnabled) return;" in tarot
    assert "paymentsEnabled: user.payments_enabled !== false" in tarot


def test_owner_tarot_keyboard_has_no_payment_callback() -> None:
    callbacks = {
        button.callback_data
        for row in tarot_menu_keyboard(
            has_tarot=False,
            expanded_enabled=True,
        ).inline_keyboard
        for button in row
        if button.callback_data
    }

    assert "buy_tarot_subscription" not in callbacks


@pytest.mark.asyncio
async def test_admin_health_does_not_contact_yookassa_when_payments_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url: str, **_kwargs):
            calls.append(url)
            return SimpleNamespace(status_code=200, json=lambda: {"ok": True})

    monkeypatch.setattr(settings, "yookassa_shop_id", "inherited-shop")
    monkeypatch.setattr(settings, "yookassa_secret_key", "inherited-key")
    monkeypatch.setattr(admin_api.httpx, "AsyncClient", FakeClient)

    response = await admin_api.get_health()

    yookassa = next(
        item for item in response.components if item.name == "Yookassa"
    )
    assert yookassa.status == "disabled"
    assert not any("yookassa" in url for url in calls)
