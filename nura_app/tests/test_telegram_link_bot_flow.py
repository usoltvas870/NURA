import json
import logging
import re
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers.start import _handle_link_token, cmd_start
from core.services.auth import (
    TELEGRAM_LINK_CONFIRMATION_MAX_ATTEMPTS,
    TELEGRAM_LINK_PENDING_TTL_SECONDS,
    TelegramConfirmationInvalidError,
    TelegramLinkConfirmationService,
)


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.fail_getdel = False

    async def execute_command(self, command: str, key: str) -> str | None:
        assert command == "GETDEL"
        if self.fail_getdel:
            raise RuntimeError("redis unavailable")
        self.ttls.pop(key, None)
        return self.store.pop(key, None)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value
        self.ttls[key] = ttl

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)
        self.ttls.pop(key, None)

    async def pttl(self, key: str) -> int:
        return self.ttls.get(key, -2) * 1000 if key in self.store else -2

    def pipeline(self) -> "FakeRedisPipeline":
        return FakeRedisPipeline(self)


class FakeRedisPipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self.commands: list[tuple[str, str, str | None]] = []

    async def __aenter__(self) -> "FakeRedisPipeline":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def watch(self, key: str) -> None:
        return None

    async def get(self, key: str) -> str | None:
        return await self.redis.get(key)

    async def pttl(self, key: str) -> int:
        return await self.redis.pttl(key)

    def multi(self) -> None:
        return None

    def set(self, key: str, value: str, *, keepttl: bool = False) -> None:
        self.commands.append(("set", key, value))

    def delete(self, key: str) -> None:
        self.commands.append(("delete", key, None))

    async def execute(self) -> list[bool]:
        for command, key, value in self.commands:
            if command == "set":
                assert value is not None
                self.redis.store[key] = value
            else:
                await self.redis.delete(key)
        return [True] * len(self.commands)


class FakeFromUser:
    def __init__(self, telegram_id: int) -> None:
        self.id = telegram_id


class FakeMessage:
    def __init__(self, telegram_id: int | None = 123456789) -> None:
        self.from_user = None if telegram_id is None else FakeFromUser(telegram_id)
        self.answer = AsyncMock()


@pytest.fixture
def flow(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr("bot.handlers.start.get_redis", lambda: redis)
    monkeypatch.setattr("core.services.auth.get_redis", lambda: redis)
    return redis, TelegramLinkConfirmationService()


async def _run_valid_flow(redis: FakeRedis, web_user_id: uuid.UUID, telegram_id: int = 123456789):
    token = uuid.uuid4().hex
    redis.store[f"link_token:{token}"] = str(web_user_id)
    message = FakeMessage(telegram_id)
    await _handle_link_token(message, token)
    return token, message


@pytest.mark.asyncio
async def test_valid_link_creates_hashed_pending_and_sends_its_six_digit_code(
    flow, monkeypatch
) -> None:
    redis, service = flow
    web_user_id = uuid.uuid4()
    monkeypatch.setattr(
        "bot.handlers.start.UserRepository",
        lambda *_: (_ for _ in ()).throw(AssertionError("link flow must not use repository")),
    )

    token, message = await _run_valid_flow(redis, web_user_id)

    pending_key = f"telegram_link_pending:{web_user_id}"
    record = json.loads(redis.store[pending_key])
    text = message.answer.await_args.args[0]
    code = re.search(r"<code>([0-9]{6})</code>", text).group(1)
    assert f"link_token:{token}" not in redis.store
    assert code not in redis.store[pending_key]
    assert record["attempts"] == 0
    assert redis.ttls[pending_key] == TELEGRAM_LINK_PENDING_TTL_SECONDS
    assert TELEGRAM_LINK_CONFIRMATION_MAX_ATTEMPTS == 5
    assert await service.verify_confirmation(web_user_id, code) == 123456789
    assert message.answer.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["", "wrong", "A" * 32, "g" * 32])
async def test_invalid_or_missing_token_creates_no_pending(flow, token: str) -> None:
    redis, _ = flow
    message = FakeMessage()

    await _handle_link_token(message, token)

    assert not redis.store
    assert "Ссылка недействительна" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_replayed_token_is_rejected_without_replacing_pending(flow) -> None:
    redis, _ = flow
    web_user_id = uuid.uuid4()
    token, _ = await _run_valid_flow(redis, web_user_id)
    first_pending = redis.store[f"telegram_link_pending:{web_user_id}"]
    message = FakeMessage()

    await _handle_link_token(message, token)

    assert redis.store[f"telegram_link_pending:{web_user_id}"] == first_pending
    assert "Ссылка недействительна" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_expired_token_is_rejected_without_creating_pending(flow) -> None:
    redis, _ = flow
    token = uuid.uuid4().hex
    redis.store[f"link_token:{token}"] = str(uuid.uuid4())
    redis.store.pop(f"link_token:{token}")
    message = FakeMessage()

    await _handle_link_token(message, token)

    assert not any(key.startswith("telegram_link_pending:") for key in redis.store)
    assert "Ссылка недействительна" in message.answer.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("telegram_id", [0, -1, 2**63, True, None])
async def test_invalid_or_missing_telegram_identity_does_not_consume_token(flow, telegram_id: int | None) -> None:
    redis, _ = flow
    token = uuid.uuid4().hex
    redis.store[f"link_token:{token}"] = str(uuid.uuid4())
    message = FakeMessage(telegram_id)

    await _handle_link_token(message, token)

    assert f"link_token:{token}" in redis.store
    assert "Ссылка недействительна" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_replacement_invalidates_old_confirmation_code(flow) -> None:
    redis, service = flow
    web_user_id = uuid.uuid4()
    _, first_message = await _run_valid_flow(redis, web_user_id)
    first_code = re.search(r"<code>([0-9]{6})</code>", first_message.answer.await_args.args[0]).group(1)

    _, second_message = await _run_valid_flow(redis, web_user_id, 987654321)
    second_code = re.search(r"<code>([0-9]{6})</code>", second_message.answer.await_args.args[0]).group(1)

    assert first_code != second_code
    with pytest.raises(TelegramConfirmationInvalidError):
        await service.verify_confirmation(web_user_id, first_code)
    assert await service.verify_confirmation(web_user_id, second_code) == 987654321


@pytest.mark.asyncio
async def test_redis_and_pending_failures_do_not_expose_or_link_identity(flow, caplog, monkeypatch) -> None:
    redis, _ = flow
    web_user_id = uuid.uuid4()
    token = uuid.uuid4().hex
    redis.store[f"link_token:{token}"] = str(web_user_id)
    redis.fail_getdel = True
    message = FakeMessage()

    with caplog.at_level(logging.INFO):
        await _handle_link_token(message, token)

    assert f"link_token:{token}" in redis.store
    assert token not in caplog.text and str(web_user_id) not in caplog.text
    assert "Не удалось начать" in message.answer.await_args.args[0]

    redis.fail_getdel = False
    monkeypatch.setattr(
        TelegramLinkConfirmationService,
        "create_pending",
        AsyncMock(side_effect=RuntimeError("pending unavailable")),
    )
    message = FakeMessage()
    await _handle_link_token(message, token)

    assert not any(key.startswith("telegram_link_pending:") for key in redis.store)
    assert "Привязка не завершена" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_success_logs_do_not_expose_link_secrets_or_identities(flow, caplog) -> None:
    redis, _ = flow
    web_user_id = uuid.uuid4()
    token = uuid.uuid4().hex
    telegram_id = 123456789
    redis.store[f"link_token:{token}"] = str(web_user_id)
    message = FakeMessage(telegram_id)

    with caplog.at_level(logging.INFO):
        await _handle_link_token(message, token)

    code = re.search(r"<code>([0-9]{6})</code>", message.answer.await_args.args[0]).group(1)
    assert token not in caplog.text
    assert str(web_user_id) not in caplog.text
    assert str(telegram_id) not in caplog.text
    assert code not in caplog.text


@pytest.mark.asyncio
async def test_cmd_start_retires_tgauth_dispatch_without_touching_dependencies(monkeypatch) -> None:
    message = FakeMessage()
    state = AsyncMock()
    command = MagicMock(args="tgauth_legacy-token")

    monkeypatch.setattr(
        "bot.handlers.start.get_redis",
        lambda: (_ for _ in ()).throw(AssertionError("legacy flow must not use Redis")),
    )
    monkeypatch.setattr(
        "bot.handlers.start.UserRepository",
        lambda *_: (_ for _ in ()).throw(AssertionError("legacy flow must not use repository")),
    )

    await cmd_start(message, state, command)

    assert "ссылка для входа устарела" in message.answer.await_args.args[0]
    assert "legacy-token" not in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_cmd_start_preserves_ordinary_start_flow() -> None:
    message = FakeMessage()
    message.from_user.first_name = "NURA"
    message.from_user.username = "nura_user"
    state = AsyncMock()
    command = MagicMock(args=None)
    user = MagicMock(birth_date="01.01.2000")

    with (
        patch("bot.handlers.start.UserRepository") as repository,
        patch("bot.handlers.start._show_authenticated_menu", new_callable=AsyncMock) as menu,
    ):
        repository.return_value.get_or_create_by_telegram_id = AsyncMock(return_value=user)
        await cmd_start(message, state, command)

    menu.assert_awaited_once_with(message, user)
