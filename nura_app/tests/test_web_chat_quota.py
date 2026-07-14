from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

import api.deps as deps_mod
import api.routes.web as web
from api.dependencies import get_current_web_user
from core.schemas.chat import ChatRequest

from core.services.chat_quota import (
    CHAT_DAILY_LIMIT,
    CHAT_TIMEZONE,
    _COMMIT_SCRIPT,
    _REFUND_SCRIPT,
    _RESERVE_SCRIPT,
    _STATE_SCRIPT,
    ChatQuotaService,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.reservations: dict[str, dict[str, int]] = {}
        self.history: dict[str, str] = {}

    def _active(self, key: str, now_ms: int) -> dict[str, int]:
        active = self.reservations.setdefault(key, {})
        for token, expires_ms in list(active.items()):
            if expires_ms <= now_ms:
                del active[token]
        return active

    async def eval(self, script: str, _keys: int, quota_key: str, reservation_key: str, *args: object) -> list[int]:
        now_ms = int(args[0])
        active = self._active(reservation_key, now_ms)
        used = self.values.get(quota_key, 0)
        if script == _STATE_SCRIPT:
            return [used, len(active)]
        if script == _RESERVE_SCRIPT:
            limit, lease_ms, token = int(args[1]), int(args[2]), str(args[3])
            if used + len(active) >= limit:
                return [0, used, len(active)]
            active[token] = lease_ms
            return [1, used, len(active)]
        if script == _COMMIT_SCRIPT:
            token = str(args[1])
            if token not in active:
                return [0, used, len(active)]
            del active[token]
            used += 1
            self.values[quota_key] = used
            return [1, used, len(active)]
        if script == _REFUND_SCRIPT:
            active.pop(str(args[1]), None)
            return [used, len(active)]
        raise AssertionError("Unexpected Lua script")

    async def get(self, key: str) -> str | None:
        return self.history.get(key)

    async def setex(self, key: str, _ttl: int, value: str) -> None:
        self.history[key] = value


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 7, 14, 12, 0, tzinfo=CHAT_TIMEZONE)


@pytest.mark.asyncio
async def test_free_quota_allows_exactly_five_committed_messages(now: datetime) -> None:
    service = ChatQuotaService(FakeRedis())

    for expected_used in range(1, CHAT_DAILY_LIMIT + 1):
        reservation = await service.reserve("user-1", subscriber=False, now=now)
        assert reservation.token is not None
        state = await service.commit("user-1", reservation.token, subscriber=False, now=now)
        assert state.used == expected_used

    denied = await service.reserve("user-1", subscriber=False, now=now)
    assert denied.token is None
    assert denied.state.code == "daily_limit_reached"
    assert denied.state.messages_left == 0


@pytest.mark.asyncio
async def test_refund_releases_reservation_without_spending_quota(now: datetime) -> None:
    service = ChatQuotaService(FakeRedis())

    reservation = await service.reserve("user-2", subscriber=False, now=now)
    state = await service.refund("user-2", reservation.token, subscriber=False, now=now)

    assert state.used == 0
    assert state.messages_left == CHAT_DAILY_LIMIT
    assert (await service.reserve("user-2", subscriber=False, now=now)).token is not None


@pytest.mark.asyncio
async def test_active_reservations_prevent_double_spend_across_tabs(now: datetime) -> None:
    service = ChatQuotaService(FakeRedis())

    reservations = [await service.reserve("user-3", subscriber=False, now=now) for _ in range(CHAT_DAILY_LIMIT)]
    denied = await service.reserve("user-3", subscriber=False, now=now)

    assert all(item.token is not None for item in reservations)
    assert denied.token is None
    assert denied.state.used == 0
    assert denied.state.messages_left == 0


@pytest.mark.asyncio
async def test_commit_and_refund_are_idempotent(now: datetime) -> None:
    service = ChatQuotaService(FakeRedis())
    reservation = await service.reserve("user-idempotent", subscriber=False, now=now)

    state = await service.commit("user-idempotent", reservation.token, subscriber=False, now=now)
    assert state.used == 1
    with pytest.raises(RuntimeError, match="expired"):
        await service.commit("user-idempotent", reservation.token, subscriber=False, now=now)

    refunded = await service.refund("user-idempotent", reservation.token, subscriber=False, now=now)
    assert refunded.used == 1
    assert refunded.messages_left == CHAT_DAILY_LIMIT - 1


@pytest.mark.asyncio
async def test_new_moscow_day_starts_with_a_fresh_quota(now: datetime) -> None:
    service = ChatQuotaService(FakeRedis())
    reservation = await service.reserve("user-new-day", subscriber=False, now=now)
    await service.commit("user-new-day", reservation.token, subscriber=False, now=now)

    next_day = datetime(2026, 7, 15, 0, 1, tzinfo=CHAT_TIMEZONE)
    state = await service.state("user-new-day", subscriber=False, now=next_day)
    assert state.used == 0
    assert state.messages_left == CHAT_DAILY_LIMIT


@pytest.mark.asyncio
async def test_subscriber_never_creates_quota_keys(now: datetime) -> None:
    redis = FakeRedis()
    service = ChatQuotaService(redis)

    reservation = await service.reserve("user-subscriber", subscriber=True, now=now)
    state = await service.commit("user-subscriber", reservation.token, subscriber=True, now=now)

    assert reservation.token is None
    assert state.access == "subscriber"
    assert redis.values == {}
    assert redis.reservations == {}


def test_subscriber_rule_requires_an_active_entitlement(now: datetime) -> None:
    active = now + timedelta(days=1)
    expired = now - timedelta(seconds=1)

    assert ChatQuotaService.is_subscriber(
        tarot_subscription=True,
        tarot_subscription_until=active,
        subscription_status=None,
        subscription_until=None,
        now=now,
    )
    assert ChatQuotaService.is_subscriber(
        tarot_subscription=False,
        tarot_subscription_until=None,
        subscription_status="premium",
        subscription_until=active,
        now=now,
    )
    assert not ChatQuotaService.is_subscriber(
        tarot_subscription=True,
        tarot_subscription_until=expired,
        subscription_status=None,
        subscription_until=None,
        now=now,
    )
    assert not ChatQuotaService.is_subscriber(
        tarot_subscription=False,
        tarot_subscription_until=None,
        subscription_status="premium",
        subscription_until=expired,
        now=now,
    )


def test_chat_request_rejects_whitespace_only_message() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message=" \n\t ")


@pytest.fixture
def chat_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FakeRedis, AsyncMock]:
    redis = FakeRedis()
    user = MagicMock()
    user.id = "route-user"
    user.tarot_subscription = False
    user.tarot_subscription_until = None
    user.subscription_status = "free"
    user.subscription_until = None
    user.first_name = "Test"
    user.name = "Test"
    reports = MagicMock()
    reports.get_by_user_id = AsyncMock(return_value=[])
    ai_response = AsyncMock(return_value="Ответ NURA")

    monkeypatch.setattr(web, "get_redis", lambda: redis)
    monkeypatch.setattr(web, "get_async_sessionmaker", lambda: object())
    monkeypatch.setattr(web, "ReportRepository", lambda _factory: reports)
    monkeypatch.setattr(web.AIService, "chat_response", ai_response)
    deps_mod.limiter.enabled = False
    app = FastAPI()
    app.include_router(web.router)
    app.state.limiter = None
    app.dependency_overrides[get_current_web_user] = lambda: user
    client = TestClient(app)
    yield client, redis, ai_response
    deps_mod.limiter.enabled = True


def test_route_returns_structured_402_without_calling_ai(chat_client: tuple[TestClient, FakeRedis, AsyncMock]) -> None:
    client, redis, ai_response = chat_client
    day, _, _ = ChatQuotaService._window()
    quota_key, _ = ChatQuotaService._keys("route-user", day)
    redis.values[quota_key] = CHAT_DAILY_LIMIT

    response = client.post("/api/v1/web/chat", json={"message": "Проверка", "history": []})

    assert response.status_code == 402
    assert response.json() == {
        "access": "free",
        "can_send": False,
        "daily_limit": CHAT_DAILY_LIMIT,
        "used": CHAT_DAILY_LIMIT,
        "messages_left": 0,
        "reset_at": response.json()["reset_at"],
        "timezone": "Europe/Moscow",
        "code": "daily_limit_reached",
    }
    ai_response.assert_not_awaited()


def test_route_refunds_reservation_when_provider_fails(
    chat_client: tuple[TestClient, FakeRedis, AsyncMock],
) -> None:
    client, redis, ai_response = chat_client
    ai_response.side_effect = RuntimeError("provider unavailable")

    response = client.post("/api/v1/web/chat", json={"message": "Проверка", "history": []})

    assert response.status_code == 503
    assert redis.values == {}
    assert all(not reservations for reservations in redis.reservations.values())


def test_route_validation_failure_does_not_reserve_quota(
    chat_client: tuple[TestClient, FakeRedis, AsyncMock],
) -> None:
    client, redis, ai_response = chat_client

    response = client.post("/api/v1/web/chat", json={"message": "   ", "history": []})

    assert response.status_code == 422
    assert redis.values == {}
    assert redis.reservations == {}
    ai_response.assert_not_awaited()


def test_route_auth_failure_does_not_reserve_quota(
    chat_client: tuple[TestClient, FakeRedis, AsyncMock],
) -> None:
    client, redis, ai_response = chat_client

    def unauthorized() -> None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    client.app.dependency_overrides[get_current_web_user] = unauthorized
    response = client.post("/api/v1/web/chat", json={"message": "Проверка", "history": []})

    assert response.status_code == 401
    assert redis.values == {}
    assert redis.reservations == {}
    ai_response.assert_not_awaited()


def test_quota_keys_are_bound_to_moscow_calendar_day(now: datetime) -> None:
    day, reset_at, _ = ChatQuotaService._window(now)

    assert day == "2026-07-14"
    assert reset_at.isoformat() == "2026-07-15T00:00:00+03:00"
    assert ChatQuotaService._keys("user-4", day) == (
        "chat_quota:user-4:2026-07-14",
        "chat_quota_reservations:user-4:2026-07-14",
    )
