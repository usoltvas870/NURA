import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Message, Update, User
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import limiter
from api.routes.web import router as web_router
from bot.handlers.start import cmd_start
from bot.main import configure_dispatcher
from bot.middlewares.registration import is_retired_legacy_tg_auth_start


LEGACY_TOKEN = "legacy-token-must-not-be-used"
RETIRED_DETAIL = "legacy_telegram_auth_retired"
RETIRED_HEADERS = {
    "cache-control": "no-store, no-cache, must-revalidate",
    "pragma": "no-cache",
    "expires": "0",
}


class TrackingRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def get(self, *args: object) -> None:
        self.calls.append(("get", args))

    async def setex(self, *args: object) -> None:
        self.calls.append(("setex", args))

    async def delete(self, *args: object) -> None:
        self.calls.append(("delete", args))

    async def execute_command(self, *args: object) -> None:
        self.calls.append(("execute_command", args))


class RetiredMessage:
    def __init__(self) -> None:
        self.from_user = MagicMock(id=123456789, username="private-user", first_name="Private")
        self.answer = AsyncMock()


class RecordingBotSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.methods: list[TelegramMethod] = []

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        self.methods.append(method)
        if method.__api_method__ == "getMe":
            return User(id=42, is_bot=True, first_name="NURA", username="NuraBot")
        return True

    async def stream_content(self, *args, **kwargs):
        yield b""


def make_update(bot: Bot, text: str, update_id: int) -> Update:
    return Update.model_validate(
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "date": 0,
                "chat": {"id": 123456789, "type": "private"},
                "from": {
                    "id": 123456789,
                    "is_bot": False,
                    "first_name": "Private",
                    "username": "private-user",
                },
                "text": text,
            },
        },
        context={"bot": bot},
    )


@pytest.fixture
def legacy_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, TrackingRedis]:
    redis = TrackingRedis()
    limiter._storage.reset()
    monkeypatch.setattr("api.routes.web.get_redis", lambda: redis)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(web_router)
    with TestClient(app) as client:
        yield client, redis


def assert_retired_response(response) -> None:
    assert response.status_code == 410
    assert response.json() == {"detail": RETIRED_DETAIL}
    for header, value in RETIRED_HEADERS.items():
        assert response.headers[header] == value
    assert "set-cookie" not in response.headers
    assert LEGACY_TOKEN not in response.text


def test_legacy_start_is_stateless_tombstone(legacy_client, caplog) -> None:
    client, redis = legacy_client

    with caplog.at_level(logging.INFO):
        response = client.post("/api/v1/web/auth/start")

    assert_retired_response(response)
    assert redis.calls == []
    assert all(
        LEGACY_TOKEN not in record.getMessage()
        for record in caplog.records
        if record.name.startswith("api.")
    )


def test_legacy_check_is_stateless_tombstone_and_preserves_cookie(legacy_client, caplog) -> None:
    client, redis = legacy_client
    client.cookies.set("nura_session_id", "existing-session-must-not-change")

    with caplog.at_level(logging.INFO):
        response = client.get(f"/api/v1/web/auth/check?token={LEGACY_TOKEN}")

    assert_retired_response(response)
    assert client.cookies.get("nura_session_id") == "existing-session-must-not-change"
    assert redis.calls == []
    assert all(
        LEGACY_TOKEN not in record.getMessage()
        for record in caplog.records
        if record.name.startswith("api.")
    )


def test_parallel_legacy_checks_are_stateless(legacy_client) -> None:
    client, redis = legacy_client

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda _: client.get(f"/api/v1/web/auth/check?token={LEGACY_TOKEN}"),
                range(2),
            )
        )

    for response in responses:
        assert_retired_response(response)
    assert redis.calls == []


def test_legacy_telegram_auth_implementation_is_unreachable_or_removed(legacy_client) -> None:
    client, redis = legacy_client

    start_response = client.post("/api/v1/web/auth/start")
    check_response = client.get(f"/api/v1/web/auth/check?token={LEGACY_TOKEN}")

    assert_retired_response(start_response)
    assert_retired_response(check_response)
    assert redis.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("args", ["tgauth_legacy-token", "tgauth_"])
async def test_legacy_bot_dispatch_is_retired_without_state_access(
    monkeypatch: pytest.MonkeyPatch,
    args: str,
    caplog,
) -> None:
    message = RetiredMessage()
    state = AsyncMock()
    command = MagicMock(args=args)

    monkeypatch.setattr(
        "bot.handlers.start.get_redis",
        lambda: (_ for _ in ()).throw(AssertionError("legacy flow must not use Redis")),
    )
    monkeypatch.setattr(
        "bot.handlers.start.UserRepository",
        lambda *_: (_ for _ in ()).throw(AssertionError("legacy flow must not use repository")),
    )

    with caplog.at_level(logging.INFO):
        await cmd_start(message, state, command)

    text = message.answer.await_args.args[0]
    assert "ссылка для входа устарела" in text
    assert "legacy-token" not in text
    assert "123456789" not in text
    assert all(
        "legacy-token" not in record.getMessage()
        and "123456789" not in record.getMessage()
        for record in caplog.records
        if record.name.startswith("bot.")
    )


@pytest.mark.asyncio
async def test_dispatcher_rejects_tgauth_before_user_registration(
    monkeypatch: pytest.MonkeyPatch,
    caplog,
) -> None:
    class ForbiddenRepository:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("retired legacy update must not construct a repository")

    monkeypatch.setattr("bot.middlewares.registration.UserRepository", ForbiddenRepository)
    monkeypatch.setattr("bot.handlers.start.UserRepository", ForbiddenRepository)
    monkeypatch.setattr(
        "bot.handlers.start.get_redis",
        lambda: (_ for _ in ()).throw(AssertionError("retired legacy update must not use Redis")),
    )

    session = RecordingBotSession()
    bot = Bot(token="42:TEST", session=session)
    dispatcher = Dispatcher()
    configure_dispatcher(dispatcher)
    secret = "do-not-log-this-token"
    updates = [
        make_update(bot, f"/start tgauth_{secret}", 1),
        make_update(bot, f"/start@NuraBot tgauth_{secret}", 2),
        make_update(bot, "/start tgauth_", 3),
    ]

    try:
        with caplog.at_level(logging.INFO):
            await asyncio.gather(*(dispatcher.feed_update(bot, update) for update in updates))
    finally:
        await dispatcher.storage.close()
        await bot.session.close()

    answers = [method for method in session.methods if method.__api_method__ == "sendMessage"]
    assert len(answers) == 3
    for method in answers:
        assert "ссылка для входа устарела" in method.text
        assert secret not in method.text
        assert "123456789" not in method.text
    assert all(
        secret not in record.getMessage() and "123456789" not in record.getMessage()
        for record in caplog.records
        if record.name.startswith("bot.")
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/start tgauth_token", True),
        (" /start@NuraBot   tgauth_ ", True),
        ("/start link_0123456789abcdef0123456789abcdef", False),
        ("/start tgauthx_token", False),
        ("tgauth_token", False),
        ("/help tgauth_token", False),
    ],
)
def test_retirement_guard_matches_only_legacy_start_payload(text: str, expected: bool) -> None:
    event = Message.model_validate(
        {
            "message_id": 1,
            "date": 0,
            "chat": {"id": 123456789, "type": "private"},
            "from": {"id": 123456789, "is_bot": False, "first_name": "Private"},
            "text": text,
        }
    )
    assert is_retired_legacy_tg_auth_start(event) is expected
