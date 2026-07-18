import asyncio
import json
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import WatchError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.deps import limiter
from api.routes.web import ConfirmTelegramLinkRequest, _consume_link_token, router
from core.repositories.user import UserRepository
from core.services.auth import (
    TELEGRAM_LINK_PENDING_TTL_SECONDS,
    TELEGRAM_LINK_CONFIRMATION_TRANSACTION_RETRIES,
    TelegramConfirmationInvalidError,
    TelegramConfirmationNotFoundError,
    TelegramConfirmationUnavailableError,
    TelegramLinkConfirmationService,
)


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self._lock = threading.Lock()
        self._versions: dict[str, int] = {}

    def _write(self, key: str, value: str, *, keepttl: bool = False) -> None:
        self.store[key] = value
        if not keepttl:
            self.ttls.pop(key, None)
        self._versions[key] = self._versions.get(key, 0) + 1

    async def setex(self, key: str, ttl: int, value: str) -> None:
        with self._lock:
            self._write(key, value)
            self.ttls[key] = ttl

    async def get(self, key: str) -> str | None:
        with self._lock:
            return self.store.get(key)

    async def pttl(self, key: str) -> int:
        with self._lock:
            if key not in self.store:
                return -2
            return self.ttls.get(key, -1) * 1000

    async def delete(self, key: str) -> None:
        with self._lock:
            self.store.pop(key, None)
            self.ttls.pop(key, None)
            self._versions[key] = self._versions.get(key, 0) + 1

    def pipeline(self) -> "FakeRedisPipeline":
        return FakeRedisPipeline(self)


class FakeRedisPipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._watched: dict[str, int] = {}
        self._commands: list[tuple[str, str, str | None, bool]] = []

    async def __aenter__(self) -> "FakeRedisPipeline":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self._watched.clear()
        self._commands.clear()

    async def watch(self, key: str) -> None:
        with self._redis._lock:
            self._watched[key] = self._redis._versions.get(key, 0)

    async def get(self, key: str) -> str | None:
        return await self._redis.get(key)

    async def pttl(self, key: str) -> int:
        return await self._redis.pttl(key)

    def multi(self) -> None:
        return None

    def set(self, key: str, value: str, *, keepttl: bool = False) -> None:
        self._commands.append(("set", key, value, keepttl))

    def delete(self, key: str) -> None:
        self._commands.append(("delete", key, None, False))

    async def execute(self) -> list[bool]:
        with self._redis._lock:
            if any(self._redis._versions.get(key, 0) != version for key, version in self._watched.items()):
                raise WatchError()
            for command, key, value, keepttl in self._commands:
                if command == "set":
                    assert value is not None
                    self._redis._write(key, value, keepttl=keepttl)
                else:
                    self._redis.store.pop(key, None)
                    self._redis.ttls.pop(key, None)
                    self._redis._versions[key] = self._redis._versions.get(key, 0) + 1
        return [True] * len(self._commands)


def factory(db_engine) -> async_sessionmaker:
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


async def pending_snapshot(service, redis: FakeRedis, user_id: uuid.UUID) -> tuple[str, int]:
    key = f"telegram_link_pending:{user_id}"
    record = json.loads(redis.store[key])
    assert (await service.get_status(user_id))["attempts_remaining"] == 5
    return record["expires_at"], await redis.pttl(key)


async def assert_pending_unchanged(service, redis: FakeRedis, user_id: uuid.UUID, snapshot: tuple[str, int]) -> None:
    key = f"telegram_link_pending:{user_id}"
    record = json.loads(redis.store[key])
    status = await service.get_status(user_id)
    assert record["attempts"] == 0 and record["expires_at"] == snapshot[0]
    assert status["status"] == "pending_confirmation" and status["attempts_remaining"] == 5
    assert 0 < await redis.pttl(key) <= snapshot[1]


async def create_pending_pair(session_factory, service, redis: FakeRedis) -> tuple[UserRepository, Any, Any, tuple[str, int], tuple[str, int]]:
    repo = UserRepository(session_factory)
    owner = await repo.create_web_user("Owner", "", f"owner-{uuid.uuid4().hex}")
    other = await repo.create_web_user("Other", "", f"other-{uuid.uuid4().hex}")
    await service.create_pending(owner.id, 123456789)
    await service.create_pending(other.id, 123456790)
    return repo, owner, other, await pending_snapshot(service, redis, owner.id), await pending_snapshot(service, redis, other.id)


@pytest.fixture
def web_client(monkeypatch, pending_service) -> tuple[TestClient, FakeRedis]:
    _, redis = pending_service
    monkeypatch.setattr("api.routes.web.get_redis", lambda: redis)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router)
    with TestClient(app) as client:
        yield client, redis


@pytest.fixture
def authenticated_client(monkeypatch, pending_service, db_engine) -> tuple[TestClient, FakeRedis, async_sessionmaker]:
    _, redis = pending_service
    session_factory = factory(db_engine)
    limiter._storage.reset()
    monkeypatch.setattr("api.routes.web.get_redis", lambda: redis)
    monkeypatch.setattr("api.routes.web.get_async_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("api.dependencies.get_async_sessionmaker", lambda: session_factory)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router)
    with TestClient(app) as client:
        yield client, redis, session_factory


@pytest.fixture
def pending_service(monkeypatch) -> tuple[TelegramLinkConfirmationService, FakeRedis]:
    redis = FakeRedis()
    monkeypatch.setattr("core.services.auth.get_redis", lambda: redis)
    return TelegramLinkConfirmationService(), redis


@pytest.mark.asyncio
async def test_pending_code_is_six_digits_hashed_and_replaced(pending_service) -> None:
    service, redis = pending_service
    user_id = uuid.uuid4()
    first = await service.create_pending(user_id, 123456789, "Telegram")
    second = await service.create_pending(user_id, 123456790, "Telegram")

    key = f"telegram_link_pending:{user_id}"
    record = json.loads(redis.store[key])
    assert re.fullmatch(r"[0-9]{6}", first)
    assert re.fullmatch(r"[0-9]{6}", second)
    assert first != second
    assert redis.ttls[key] == TELEGRAM_LINK_PENDING_TTL_SECONDS
    assert first not in redis.store[key] and second not in redis.store[key]
    assert "link_token" not in redis.store[key]
    assert record["attempts"] == 0 and "code_hash" in record and "telegram_id" in record


@pytest.mark.asyncio
async def test_status_is_scoped_and_does_not_expose_identity(pending_service) -> None:
    service, _ = pending_service
    owner, other = uuid.uuid4(), uuid.uuid4()
    await service.create_pending(owner, 123456789, "Telegram")

    status = await service.get_status(owner)
    assert status["status"] == "pending_confirmation"
    assert "telegram_id" not in status and "web_user_id" not in status
    assert (await service.get_status(other))["status"] == "idle"


@pytest.mark.asyncio
async def test_invalid_attempts_expire_pending(pending_service) -> None:
    service, _ = pending_service
    user_id = uuid.uuid4()
    await service.create_pending(user_id, 123456789)

    for remaining in range(4, -1, -1):
        with pytest.raises(TelegramConfirmationInvalidError) as error:
            await service.verify_confirmation(user_id, "000000")
        assert error.value.attempts_remaining == remaining
    with pytest.raises(TelegramConfirmationNotFoundError):
        await service.verify_confirmation(user_id, "000000")


@pytest.mark.asyncio
async def test_invalid_attempt_preserves_pending_ttl_and_logical_expiry(pending_service) -> None:
    service, redis = pending_service
    user_id = uuid.uuid4()
    await service.create_pending(user_id, 123456789)
    key = f"telegram_link_pending:{user_id}"
    ttl_before = await redis.pttl(key)
    expires_at = json.loads(redis.store[key])["expires_at"]

    with pytest.raises(TelegramConfirmationInvalidError):
        await service.verify_confirmation(user_id, "0" * 6)

    assert 0 < await redis.pttl(key) <= ttl_before
    assert json.loads(redis.store[key])["expires_at"] == expires_at


@pytest.mark.asyncio
async def test_invalid_attempt_retries_a_transaction_conflict(pending_service, monkeypatch) -> None:
    service, _ = pending_service
    user_id = uuid.uuid4()
    await service.create_pending(user_id, 123456789)
    original_execute = FakeRedisPipeline.execute
    execute_calls = 0

    async def conflict_once(pipeline: FakeRedisPipeline) -> list[bool]:
        nonlocal execute_calls
        execute_calls += 1
        if execute_calls == 1:
            raise WatchError()
        return await original_execute(pipeline)

    monkeypatch.setattr(FakeRedisPipeline, "execute", conflict_once)
    with pytest.raises(TelegramConfirmationInvalidError) as error:
        await service.verify_confirmation(user_id, "0" * 6)

    assert error.value.attempts_remaining == 4
    assert execute_calls == 2


@pytest.mark.asyncio
async def test_invalid_attempt_stops_after_finite_transaction_retries(pending_service, monkeypatch) -> None:
    service, _ = pending_service
    user_id = uuid.uuid4()
    await service.create_pending(user_id, 123456789)
    execute_calls = 0

    async def always_conflict(pipeline: FakeRedisPipeline) -> list[bool]:
        nonlocal execute_calls
        execute_calls += 1
        raise WatchError()

    monkeypatch.setattr(FakeRedisPipeline, "execute", always_conflict)
    with pytest.raises(TelegramConfirmationUnavailableError):
        await service.verify_confirmation(user_id, "0" * 6)

    assert execute_calls == TELEGRAM_LINK_CONFIRMATION_TRANSACTION_RETRIES


@pytest.mark.asyncio
async def test_expired_pending_is_not_revived_after_transaction_conflict(pending_service, monkeypatch) -> None:
    service, redis = pending_service
    user_id = uuid.uuid4()
    await service.create_pending(user_id, 123456789)
    key = f"telegram_link_pending:{user_id}"
    original_execute = FakeRedisPipeline.execute
    expire_once = True

    async def expire_before_execute(pipeline: FakeRedisPipeline) -> list[bool]:
        nonlocal expire_once
        if expire_once:
            expire_once = False
            record = json.loads(redis.store[key])
            record["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            await redis.setex(key, redis.ttls[key], json.dumps(record))
        return await original_execute(pipeline)

    monkeypatch.setattr(FakeRedisPipeline, "execute", expire_before_execute)
    with pytest.raises(TelegramConfirmationNotFoundError):
        await service.verify_confirmation(user_id, "0" * 6)

    assert key not in redis.store


@pytest.mark.asyncio
async def test_valid_confirmation_links_and_preserves_conflicts(db_engine, pending_service) -> None:
    service, _ = pending_service
    repo = UserRepository(factory(db_engine))
    target = await repo.create_web_user("Target", "", uuid.uuid4().hex)
    owner = await repo.create(222222222, "owner")
    candidate = 123456789

    code = await service.create_pending(target.id, candidate)
    assert await repo.link_telegram_id_safely(target.id, await service.verify_confirmation(target.id, code))
    assert await repo.link_telegram_id_safely(target.id, candidate)
    assert not await repo.link_telegram_id_safely(target.id, owner.telegram_id)
    assert not await repo.link_telegram_id_safely(target.id, 333333333)


@pytest.mark.asyncio
async def test_pending_service_rejects_invalid_telegram_ids(pending_service) -> None:
    service, _ = pending_service
    for telegram_id in (0, -1, 2**63, True):
        with pytest.raises(ValueError):
            await service.create_pending(uuid.uuid4(), telegram_id)


def test_public_consumer_route_is_absent_and_confirm_schema_is_strict() -> None:
    paths = {route.path for route in router.routes}
    assert "/api/v1/web/check-link-token" not in paths
    assert "/api/v1/web/telegram-link-status" in paths
    assert "/api/v1/web/confirm-telegram-link" in paths
    assert "/api/v1/web/cancel-telegram-link" in paths
    assert ConfirmTelegramLinkRequest(code="123456").code == "123456"
    for code in ("12345", "1234567", "12 456", "abcdef"):
        with pytest.raises(ValueError):
            ConfirmTelegramLinkRequest(code=code)


def test_removed_consumer_returns_404_and_preserves_token(web_client) -> None:
    client, redis = web_client
    token = "link-token-kept"
    redis.store[f"link_token:{token}"] = "user-value"

    response = client.get("/api/v1/web/check-link-token", headers={"X-Link-Token": token})
    assert response.status_code == 404
    assert redis.store[f"link_token:{token}"] == "user-value"


@pytest.mark.asyncio
async def test_internal_consumer_still_consumes_link_token(web_client) -> None:
    _, redis = web_client
    token = "link-token-internal"
    redis.store[f"link_token:{token}"] = "user-value"

    async def getdel(key: str) -> str | None:
        return redis.store.pop(key, None)

    redis.execute_command = lambda command, key: getdel(key)  # type: ignore[attr-defined]
    assert await _consume_link_token(token) == "user-value"
    assert f"link_token:{token}" not in redis.store


@pytest.mark.parametrize(
    ("method", "url", "payload"),
    [
        ("get", "/api/v1/web/telegram-link-status", None),
        ("post", "/api/v1/web/confirm-telegram-link", {"code": "123456"}),
        ("delete", "/api/v1/web/cancel-telegram-link", None),
    ],
)
def test_confirmation_routes_require_auth(web_client, method, url, payload) -> None:
    client, _ = web_client
    response = client.request(method.upper(), url, json=payload)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_and_expired_cookies_are_rejected_without_consuming_pending(authenticated_client) -> None:
    client, redis, session_factory = authenticated_client
    repo = UserRepository(session_factory)
    user = await repo.create_web_user("Expired", "", "expired-session")
    code = await TelegramLinkConfirmationService().create_pending(user.id, 123456789)
    async with session_factory() as session:
        stored = await session.get(type(user), user.id)
        stored.web_session_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()

    for value in ("missing-session", "expired-session"):
        response = client.post(
            "/api/v1/web/confirm-telegram-link",
            json={"code": code},
            cookies={"nura_session_id": value},
        )
        assert response.status_code == 401 and value not in response.text
    assert f"telegram_link_pending:{user.id}" in redis.store


@pytest.mark.asyncio
async def test_status_confirm_isolated_and_private_over_http(authenticated_client) -> None:
    client, redis, session_factory = authenticated_client
    repo = UserRepository(session_factory)
    owner = await repo.create_web_user("Owner", "", "owner-session")
    other = await repo.create_web_user("Other", "", "other-session")
    code = await TelegramLinkConfirmationService().create_pending(owner.id, 123456789, "Telegram")

    status = client.get("/api/v1/web/telegram-link-status", cookies={"nura_session_id": "owner-session"})
    assert status.status_code == 200 and status.json()["status"] == "pending_confirmation"
    serialized = status.text
    for secret in (str(owner.id), "123456789", code, "code_hash", "code_salt", "telegram_link_pending", "owner-session"):
        assert secret not in serialized

    other_status = client.get("/api/v1/web/telegram-link-status", cookies={"nura_session_id": "other-session"})
    assert other_status.json() == {"status": "idle", "display_label": None, "expires_in": None, "attempts_remaining": None}
    denied = client.post(
        "/api/v1/web/confirm-telegram-link",
        json={"code": code},
        cookies={"nura_session_id": "other-session"},
    )
    assert denied.status_code == 404 and f"telegram_link_pending:{owner.id}" in redis.store

    response = client.post(
        "/api/v1/web/confirm-telegram-link",
        json={"code": code, "user_id": str(other.id), "telegram_id": 999},
        cookies={"nura_session_id": "owner-session"},
    )
    assert response.status_code == 200 and response.json() == {"ok": True}
    assert f"telegram_link_pending:{owner.id}" not in redis.store
    assert (await repo.get_by_telegram_id(123456789)).id == owner.id
    assert await repo.get_by_telegram_id(999) is None
    repeat = client.post("/api/v1/web/confirm-telegram-link", json={"code": code}, cookies={"nura_session_id": "owner-session"})
    assert repeat.status_code == 404


@pytest.mark.asyncio
async def test_invalid_attempts_validation_replacement_and_expiry_over_http(authenticated_client) -> None:
    client, redis, session_factory = authenticated_client
    repo = UserRepository(session_factory)
    user = await repo.create_web_user("Attempts", "", "attempts-session")
    service = TelegramLinkConfirmationService()
    code = await service.create_pending(user.id, 555555555)
    cookies = {"nura_session_id": "attempts-session"}

    for invalid in ("12345", "1234567", "abc123", "１２３４５６", " 123456", "123456 ", "123 456", "", None, 123456):
        response = client.post("/api/v1/web/confirm-telegram-link", json={"code": invalid}, cookies=cookies)
        assert response.status_code == 422
    assert (await service.get_status(user.id))["attempts_remaining"] == 5

    bad = client.post("/api/v1/web/confirm-telegram-link", json={"code": "000000"}, cookies=cookies)
    assert bad.status_code == 400 and bad.json()["detail"] == "telegram_confirmation_invalid"
    assert (await service.get_status(user.id))["attempts_remaining"] == 4
    assert "000000" not in bad.text and "555555555" not in bad.text
    assert client.post("/api/v1/web/confirm-telegram-link", json={"code": code}, cookies=cookies).status_code == 200

    old = await service.create_pending(user.id, 666666666)
    new = await service.create_pending(user.id, 666666666)
    assert client.post("/api/v1/web/confirm-telegram-link", json={"code": old}, cookies=cookies).status_code == 400
    assert (await service.get_status(user.id))["attempts_remaining"] == 4
    assert client.post("/api/v1/web/confirm-telegram-link", json={"code": new}, cookies=cookies).status_code == 409

    expiring = await repo.create_web_user("Expiring", "", "expiring-session")
    expiring_cookies = {"nura_session_id": "expiring-session"}
    expiring_code = await service.create_pending(expiring.id, 666666667)
    key = f"telegram_link_pending:{expiring.id}"
    record = json.loads(redis.store[key])
    record["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    redis.store[key] = json.dumps(record)
    expired = client.post("/api/v1/web/confirm-telegram-link", json={"code": expiring_code}, cookies=expiring_cookies)
    assert expired.status_code == 404 and expired.json()["detail"] == "telegram_confirmation_not_found"
    assert client.get("/api/v1/web/telegram-link-status", cookies=expiring_cookies).json()["status"] == "idle"


@pytest.mark.asyncio
async def test_cancel_and_logout_cleanup_are_scoped_and_idempotent(authenticated_client) -> None:
    client, redis, session_factory = authenticated_client
    repo = UserRepository(session_factory)
    first = await repo.create_web_user("First", "", "first-session")
    second = await repo.create_web_user("Second", "", "second-session")
    service = TelegramLinkConfirmationService()
    first_code = await service.create_pending(first.id, 777777777)
    second_code = await service.create_pending(second.id, 888888888)
    first_cookies = {"nura_session_id": "first-session"}
    second_cookies = {"nura_session_id": "second-session"}

    assert client.delete("/api/v1/web/cancel-telegram-link", cookies=first_cookies).json() == {"ok": True}
    assert client.delete("/api/v1/web/cancel-telegram-link", cookies=first_cookies).json() == {"ok": True}
    assert (await service.get_status(first.id))["status"] == "idle"
    assert client.post("/api/v1/web/confirm-telegram-link", json={"code": first_code}, cookies=first_cookies).status_code == 404
    assert client.post("/api/v1/web/confirm-telegram-link", json={"code": second_code}, cookies=second_cookies).status_code == 200

    await service.create_pending(first.id, 777777778)
    await service.create_pending(second.id, 888888889)
    logout = client.post("/api/v1/web/logout", cookies=first_cookies)
    assert logout.status_code == 200 and "777777778" not in logout.text
    assert (await service.get_status(first.id))["status"] == "idle"
    assert (await service.get_status(second.id))["status"] == "pending_confirmation"
    assert client.get("/api/v1/web/telegram-link-status", cookies=first_cookies).status_code == 401
    assert client.get("/api/v1/web/telegram-link-status", cookies=second_cookies).status_code == 200
    assert client.post("/api/v1/web/logout", cookies=first_cookies).status_code == 200
    assert f"telegram_link_pending:{first.id}" not in redis.store


@pytest.mark.asyncio
async def test_five_invalid_attempts_lock_pending_and_allow_fresh_confirmation(authenticated_client, caplog) -> None:
    client, redis, session_factory = authenticated_client
    repo = UserRepository(session_factory)
    user = await repo.create_web_user("Locked", "", "locked-session")
    service = TelegramLinkConfirmationService()
    code = await service.create_pending(user.id, 919191919)
    cookies = {"nura_session_id": "locked-session"}
    key = f"telegram_link_pending:{user.id}"

    for remaining in (4, 3, 2, 1, 0):
        response = client.post("/api/v1/web/confirm-telegram-link", json={"code": "000000"}, cookies=cookies)
        assert response.status_code == 400 and response.json()["detail"] == "telegram_confirmation_invalid"
        status = await service.get_status(user.id)
        if remaining:
            assert status["attempts_remaining"] == remaining and key in redis.store
        else:
            assert status["status"] == "idle" and key not in redis.store
    assert client.post("/api/v1/web/confirm-telegram-link", json={"code": code}, cookies=cookies).status_code == 404
    assert client.post("/api/v1/web/confirm-telegram-link", json={"code": "000000"}, cookies=cookies).status_code == 404
    assert await repo.get_by_telegram_id(919191919) is None
    assert code not in caplog.text and "919191919" not in caplog.text and str(user.id) not in caplog.text

    fresh = await service.create_pending(user.id, 919191919)
    assert (await service.get_status(user.id))["attempts_remaining"] == 5
    assert client.post("/api/v1/web/confirm-telegram-link", json={"code": fresh}, cookies=cookies).status_code == 200


@pytest.mark.asyncio
async def test_invalid_attempts_are_isolated_between_users(authenticated_client) -> None:
    client, _, session_factory = authenticated_client
    repo = UserRepository(session_factory)
    first = await repo.create_web_user("Counter A", "", "counter-a")
    second = await repo.create_web_user("Counter B", "", "counter-b")
    service = TelegramLinkConfirmationService()
    first_code = await service.create_pending(first.id, 929292929)
    second_code = await service.create_pending(second.id, 939393939)

    first_bad = client.post("/api/v1/web/confirm-telegram-link", json={"code": "000000"}, cookies={"nura_session_id": "counter-a"})
    assert first_bad.status_code == 400
    assert (await service.get_status(first.id))["attempts_remaining"] == 4
    assert (await service.get_status(second.id))["attempts_remaining"] == 5

    second_uses_first = client.post("/api/v1/web/confirm-telegram-link", json={"code": first_code}, cookies={"nura_session_id": "counter-b"})
    assert second_uses_first.status_code == 400
    assert (await service.get_status(first.id))["attempts_remaining"] == 4
    assert (await service.get_status(second.id))["attempts_remaining"] == 4
    assert client.post("/api/v1/web/confirm-telegram-link", json={"code": first_code}, cookies={"nura_session_id": "counter-a"}).status_code == 200
    assert client.post("/api/v1/web/confirm-telegram-link", json={"code": second_code}, cookies={"nura_session_id": "counter-b"}).status_code == 200


@pytest.mark.asyncio
async def test_parallel_invalid_confirmations_consume_two_attempts(authenticated_client, monkeypatch) -> None:
    _, redis, session_factory = authenticated_client
    repo = UserRepository(session_factory)
    user = await repo.create_web_user("Parallel", "", "parallel-session")
    service = TelegramLinkConfirmationService()
    key = f"telegram_link_pending:{user.id}"
    original_get = redis.get
    read_lock = threading.Lock()
    barrier: threading.Barrier | None = None
    barrier_reads = 0

    async def synchronized_get(candidate_key: str) -> str | None:
        nonlocal barrier_reads
        should_wait = False
        with read_lock:
            if candidate_key == key and barrier is not None and barrier_reads < 2:
                barrier_reads += 1
                should_wait = True
        if should_wait:
            barrier.wait(timeout=5)
        return await original_get(candidate_key)

    def post_invalid_confirmation() -> int:
        app = FastAPI()
        app.state.limiter = limiter
        app.include_router(router)
        with TestClient(app) as client:
            client.cookies.set("nura_session_id", "parallel-session")
            response = client.post("/api/v1/web/confirm-telegram-link", json={"code": "0" * 6})
        return response.status_code

    monkeypatch.setattr(redis, "get", synchronized_get)
    remaining_attempts: list[int] = []
    for _ in range(10):
        await service.create_pending(user.id, 123456789)
        ttl_before = await redis.pttl(key)
        expires_at = json.loads(redis.store[key])["expires_at"]
        limiter._storage.reset()
        barrier = threading.Barrier(2)
        barrier_reads = 0
        try:
            statuses = await asyncio.gather(
                asyncio.to_thread(post_invalid_confirmation),
                asyncio.to_thread(post_invalid_confirmation),
            )
            assert statuses == [400, 400]
            assert barrier_reads == 2
            status = await service.get_status(user.id)
            remaining_attempts.append(status["attempts_remaining"])
            assert 0 < await redis.pttl(key) <= ttl_before
            assert json.loads(redis.store[key])["expires_at"] == expires_at
        finally:
            await redis.delete(key)

    assert remaining_attempts == [3] * 10


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"code": "12345"}, {"code": "1234567"}, {"code": "12a456"}, {"code": "１２３４５６"},
    {"code": "123４56"}, {"code": " 123456"}, {"code": "123456 "}, {"code": "123 456"},
    {"code": "123\t56"}, {"code": "123\n56"}, {"code": ""}, {"code": None}, {"code": 123456},
    {"code": 123.0}, {"code": True}, {"code": []}, {"code": {}}, {},
])
async def test_schema_invalid_confirmations_do_not_consume_pending(authenticated_client, payload) -> None:
    client, redis, session_factory = authenticated_client
    service = TelegramLinkConfirmationService()
    repo, owner, other, owner_before, other_before = await create_pending_pair(session_factory, service, redis)
    client.cookies.set("nura_session_id", owner.web_session_id)
    response = client.post("/api/v1/web/confirm-telegram-link", json=payload)
    assert response.status_code == 422
    assert "traceback" not in response.text.lower()
    await assert_pending_unchanged(service, redis, owner.id, owner_before)
    await assert_pending_unchanged(service, redis, other.id, other_before)
    assert await repo.get_by_telegram_id(123456789) is None


@pytest.mark.asyncio
async def test_malformed_json_does_not_consume_pending(authenticated_client) -> None:
    client, redis, session_factory = authenticated_client
    service = TelegramLinkConfirmationService()
    repo, owner, other, owner_before, other_before = await create_pending_pair(session_factory, service, redis)
    client.cookies.set("nura_session_id", owner.web_session_id)
    response = client.post("/api/v1/web/confirm-telegram-link", content=b'{"code":', headers={"content-type": "application/json"})
    assert response.status_code == 422 and "traceback" not in response.text.lower()
    await assert_pending_unchanged(service, redis, owner.id, owner_before)
    await assert_pending_unchanged(service, redis, other.id, other_before)
    assert await repo.get_by_telegram_id(123456789) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "unknown", "expired", "cleared", "empty", "wrong_name", "other"])
async def test_auth_failures_do_not_consume_owner_pending(authenticated_client, case) -> None:
    client, redis, session_factory = authenticated_client
    service = TelegramLinkConfirmationService()
    _, owner, other, owner_before, other_before = await create_pending_pair(session_factory, service, redis)
    cookies: dict[str, str] | None = None
    if case == "unknown":
        cookies = {"nura_session_id": "missing"}
    elif case == "expired":
        async with session_factory() as session:
            stored = await session.get(type(owner), owner.id)
            stored.web_session_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()
        cookies = {"nura_session_id": owner.web_session_id}
    elif case == "cleared":
        async with session_factory() as session:
            stored = await session.get(type(owner), owner.id)
            stored.web_session_id = None
            await session.commit()
        cookies = {"nura_session_id": owner.web_session_id}
    elif case == "empty":
        cookies = {"nura_session_id": ""}
    elif case == "wrong_name":
        cookies = {"wrong_session": owner.web_session_id}
    elif case == "other":
        await service.delete_pending(other.id)
        cookies = {"nura_session_id": other.web_session_id}
    response = client.post("/api/v1/web/confirm-telegram-link", json={"code": "0" * 6}, cookies=cookies)
    assert response.status_code == (404 if case == "other" else 401)
    await assert_pending_unchanged(service, redis, owner.id, owner_before)
    if case == "other":
        assert (await service.get_status(other.id))["status"] == "idle"
    else:
        await assert_pending_unchanged(service, redis, other.id, other_before)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,url", [
    ("get", "/api/v1/web/telegram-link-status"), ("get", "/api/v1/web/telegram-link-status"),
    ("get", "/api/v1/web/check-link-token"), ("get", "/api/v1/web/check-link-token"),
    ("post", "/api/v1/web/not-a-confirmation"), ("get", "/api/v1/web/confirm-telegram-link"),
    ("put", "/api/v1/web/confirm-telegram-link"),
])
async def test_read_only_and_unrelated_routes_do_not_consume_pending(authenticated_client, method, url) -> None:
    client, redis, session_factory = authenticated_client
    service = TelegramLinkConfirmationService()
    _, owner, other, owner_before, other_before = await create_pending_pair(session_factory, service, redis)
    client.cookies.set("nura_session_id", owner.web_session_id)
    headers = {"X-Link-Token": "unused"} if url.endswith("check-link-token") else None
    response = client.request(method.upper(), url, headers=headers)
    assert response.status_code in {200, 401, 404, 405}
    await assert_pending_unchanged(service, redis, owner.id, owner_before)
    await assert_pending_unchanged(service, redis, other.id, other_before)


@pytest.mark.asyncio
async def test_extra_identity_fields_only_consume_current_users_attempt(authenticated_client) -> None:
    client, redis, session_factory = authenticated_client
    service = TelegramLinkConfirmationService()
    _, owner, other, _, other_before = await create_pending_pair(session_factory, service, redis)
    client.cookies.set("nura_session_id", owner.web_session_id)
    response = client.post("/api/v1/web/confirm-telegram-link", json={"code": "0" * 6, "user_id": str(other.id), "telegram_id": 999})
    assert response.status_code == 400
    assert (await service.get_status(owner.id))["attempts_remaining"] == 4
    await assert_pending_unchanged(service, redis, other.id, other_before)


@pytest.mark.asyncio
async def test_cancel_telegram_link_lifecycle(authenticated_client) -> None:
    client, redis, session_factory = authenticated_client
    service = TelegramLinkConfirmationService()
    repo = UserRepository(session_factory)
    user = await repo.create_web_user("Cancel", "", "cancel-session")
    code = await service.create_pending(user.id, 123456789)
    client.cookies.set("nura_session_id", "cancel-session")
    assert client.delete("/api/v1/web/cancel-telegram-link").json() == {"ok": True}
    assert (await service.get_status(user.id))["status"] == "idle"
    assert client.post("/api/v1/web/confirm-telegram-link", json={"code": code}).status_code == 404
    assert client.get("/api/v1/web/telegram-link-status").status_code == 200
    assert await repo.get_by_telegram_id(123456789) is None
    assert client.delete("/api/v1/web/cancel-telegram-link").json() == {"ok": True}


@pytest.mark.asyncio
async def test_cancel_telegram_link_auth_and_isolation(authenticated_client) -> None:
    client, redis, session_factory = authenticated_client
    service = TelegramLinkConfirmationService()
    _, owner, other, _, other_before = await create_pending_pair(session_factory, service, redis)
    for cookies in (None, {"nura_session_id": "missing"}):
        assert client.delete("/api/v1/web/cancel-telegram-link", cookies=cookies).status_code == 401
    async with session_factory() as session:
        stored = await session.get(type(owner), owner.id)
        stored.web_session_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()
    assert client.delete("/api/v1/web/cancel-telegram-link", cookies={"nura_session_id": owner.web_session_id}).status_code == 401
    client.cookies.set("nura_session_id", other.web_session_id)
    assert client.delete("/api/v1/web/cancel-telegram-link").json() == {"ok": True}
    assert (await service.get_status(other.id))["status"] == "idle"


@pytest.mark.asyncio
async def test_logout_cleans_only_current_users_pending(authenticated_client) -> None:
    client, redis, session_factory = authenticated_client
    service = TelegramLinkConfirmationService()
    _, owner, other, _, other_before = await create_pending_pair(session_factory, service, redis)
    owner_code = json.loads(redis.store[f"telegram_link_pending:{owner.id}"])["code_hash"]
    client.cookies.set("nura_session_id", owner.web_session_id)
    assert client.post("/api/v1/web/logout").json() == {"ok": True}
    assert client.get("/api/v1/web/telegram-link-status", cookies={"nura_session_id": owner.web_session_id}).status_code == 401
    assert (await service.get_status(owner.id))["status"] == "idle"
    await assert_pending_unchanged(service, redis, other.id, other_before)
    assert owner_code not in client.post("/api/v1/web/logout").text


@pytest.mark.asyncio
async def test_logout_invalidates_session_before_cleanup_failure(authenticated_client, monkeypatch, caplog) -> None:
    client, redis, session_factory = authenticated_client
    service = TelegramLinkConfirmationService()
    _, owner, other, _, other_before = await create_pending_pair(session_factory, service, redis)
    key = f"telegram_link_pending:{owner.id}"
    original_delete = redis.delete

    async def fail_owner_cleanup(candidate_key: str) -> None:
        if candidate_key == key:
            raise RuntimeError("redis cleanup failed")
        await original_delete(candidate_key)

    monkeypatch.setattr(redis, "delete", fail_owner_cleanup)
    response = client.post("/api/v1/web/logout", cookies={"nura_session_id": owner.web_session_id})
    assert response.status_code == 200 and "redis cleanup failed" not in response.text and "traceback" not in response.text.lower()
    assert client.get("/api/v1/web/telegram-link-status", cookies={"nura_session_id": owner.web_session_id}).status_code == 401
    assert key in redis.store
    await assert_pending_unchanged(service, redis, other.id, other_before)
    assert "redis cleanup failed" not in caplog.text


@pytest.mark.asyncio
async def test_http_confirmation_conflict_invalidates_pending_without_linking(authenticated_client) -> None:
    client, redis, session_factory = authenticated_client
    repo = UserRepository(session_factory)
    owner = await repo.create(123456789, "Owner")
    target = await repo.create_web_user("Target", "", "target-conflict-session")
    service = TelegramLinkConfirmationService()
    code = await service.create_pending(target.id, owner.telegram_id)
    client.cookies.set("nura_session_id", "target-conflict-session")
    response = client.post("/api/v1/web/confirm-telegram-link", json={"code": code})
    assert response.status_code == 409 and response.json() == {"detail": "telegram_account_conflict"}
    assert (await service.get_status(target.id))["status"] == "idle"
    assert (await repo.get_by_telegram_id(owner.telegram_id)).id == owner.id
    assert "123456789" not in response.text and "target-conflict-session" not in response.text


@pytest.mark.asyncio
async def test_repository_telegram_link_conflicts_are_safe_and_idempotent(db_engine) -> None:
    repo = UserRepository(factory(db_engine))
    first = await repo.create_web_user("First", "", "first-link-session")
    second = await repo.create_web_user("Second", "", "second-link-session")
    assert await repo.link_telegram_id_safely(first.id, 123456789)
    assert await repo.link_telegram_id_safely(first.id, 123456789)
    assert not await repo.link_telegram_id_safely(second.id, 123456789)
    assert not await repo.link_telegram_id_safely(first.id, 123456790)
    assert (await repo.get_by_telegram_id(123456789)).id == first.id
    assert await repo.get_by_telegram_id(123456790) is None
