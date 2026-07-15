"""Regression tests for the Tarot subscription checkout contract."""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.deps as deps_mod
from api.dependencies import get_current_web_user
from api.routes import web
from core.models import User
from core.services.payment import PaymentService


@pytest.fixture
def subscribed_user() -> MagicMock:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    return user


@pytest.fixture
def client(subscribed_user: MagicMock):
    deps_mod.limiter.enabled = False
    app = FastAPI()
    app.include_router(web.router)
    app.state.limiter = None
    app.dependency_overrides[get_current_web_user] = lambda: subscribed_user
    yield TestClient(app)
    deps_mod.limiter.enabled = True


def test_tarot_checkout_uses_empty_json_body() -> None:
    source = (Path(__file__).parents[2] / "frontend/pwa/app/tarot.html").read_text(encoding="utf-8")

    assert "fetch(BASE + '/web/subscribe'" in source
    assert "headers: { 'Content-Type': 'application/json' }" in source
    assert "body: JSON.stringify({})" in source


def test_subscribe_accepts_tarot_empty_json_body(
    client: TestClient, subscribed_user: MagicMock,
) -> None:
    payment = {"id": "mock-tarot-payment", "payment_url": "https://checkout.invalid/mock"}

    with patch.object(
        PaymentService, "create_web_tarot_payment", new_callable=AsyncMock,
        return_value=payment,
    ) as create_payment, patch("api.routes.web.PaymentRepository") as repo_class:
        repo_class.return_value.create = AsyncMock()

        response = client.post("/api/v1/web/subscribe", json={})

    assert response.status_code == 200
    assert response.json() == {"payment_url": payment["payment_url"]}
    create_payment.assert_awaited_once_with(user_id=subscribed_user.id)


def test_subscribe_without_body_remains_invalid(client: TestClient) -> None:
    assert client.post("/api/v1/web/subscribe").status_code == 422


def test_daily_card_cache_is_user_scoped_and_race_guarded() -> None:
    source = (Path(__file__).parents[2] / "frontend/pwa/app/tarot.html").read_text(encoding="utf-8")

    assert "nura_daily_card:" in source
    assert "user.user_id" in source
    assert "legacyCacheKey" in source
    assert "localStorage.removeItem(legacyCacheKey)" in source
    assert "requestId !== dailyCardRequest || currentUserId !== userId" in source
    assert "event.persisted" in source
    assert "currentUserId = null" in source
    assert "$('hero-name').textContent = '';" in source


def test_profile_logout_clears_daily_card_cache() -> None:
    source = (Path(__file__).parents[2] / "frontend/pwa/app/profile.html").read_text(encoding="utf-8")

    assert "nura_daily_card:" in source
    assert "tarot_daily_card_" in source
