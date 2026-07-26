"""Acceptance contracts for durable lifetime free chat."""

from __future__ import annotations

import inspect
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.routes.web import (
    _parse_idempotency_key,
    _safe_chat_history,
    _web_chat_request_key,
)
from bot.handlers.chat import _telegram_request_key
from core.fallbacks import FALLBACK_CHAT
from core.models import ChatMessageUsage, User
from core.services.chat_application import ChatApplicationService, ChatResultKind
from core.services.chat_history import (
    CHAT_HISTORY_MAX_MESSAGES,
    CHAT_HISTORY_TTL,
    _FINALIZE_SCRIPT,
    chat_history_key,
    chat_history_marker_key,
    finalize_chat_history_once,
)
from core.services.chat_quota import (
    ChatChannel,
    ChatQuotaService,
    QuotaReservation,
    QuotaReservationKind,
)


ROOT = Path(__file__).resolve().parents[2]
PWA_CHAT = ROOT / "frontend" / "pwa" / "app" / "chat.html"
MIGRATION = ROOT / "nura_app" / "alembic" / "versions" / "d6e7f8a9b0c1_add_lifetime_chat_message_usage.py"


class CapturingRedis:
    def __init__(self, result: int = 1, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.args: tuple[object, ...] | None = None

    async def eval(self, *args: object) -> int:
        self.args = args
        if self.error:
            raise self.error
        return self.result


def _reservation(kind: QuotaReservationKind, *, response: str | None = None) -> QuotaReservation:
    return QuotaReservation(
        kind,
        "usage-id" if kind != QuotaReservationKind.EXHAUSTED else None,
        ChatQuotaService._free_state(0),
        response_text=response,
        error_code="provider_failure" if kind == QuotaReservationKind.DUPLICATE_RELEASED else None,
    )


def test_model_and_migration_define_exact_lifetime_ledger_contract() -> None:
    table = ChatMessageUsage.__table__
    assert set(table.c.keys()) == {
        "id", "user_id", "request_key", "channel", "status", "billable",
        "created_at", "reserved_at", "consumed_at", "released_at", "release_reason",
        "response_text", "error_code", "result_ready_at", "updated_at",
    }
    assert {index.name for index in table.indexes} == {
        "ix_chat_message_usages_user_status",
        "ix_chat_message_usages_stale_reserved",
    }
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "d6e7f8a9b0c1"' in source
    assert 'down_revision = "d2e3f4a5b6c7"' in source
    assert "result_ready" in source and "ON DELETE" not in source
    assert "ondelete=\"CASCADE\"" in source
    assert "raw_message" not in source and "telegram_id" not in source


def test_history_lua_is_atomic_request_aware_and_ttl_aligned() -> None:
    assert CHAT_HISTORY_TTL == 7 * 86400
    assert CHAT_HISTORY_MAX_MESSAGES == 20
    assert _FINALIZE_SCRIPT.index("SISMEMBER") < _FINALIZE_SCRIPT.index("table.insert")
    assert "entry.request_key == ARGV[5]" in _FINALIZE_SCRIPT
    assert "SADD" in _FINALIZE_SCRIPT
    assert "EXPIRE', KEYS[2], ARGV[4]" in _FINALIZE_SCRIPT
    assert "SET', KEYS[1]" in _FINALIZE_SCRIPT
    assert "while #history > tonumber(ARGV[3])" in _FINALIZE_SCRIPT
    assert "system" not in _FINALIZE_SCRIPT


@pytest.mark.asyncio
async def test_history_helper_passes_only_safe_roles_and_metadata() -> None:
    redis = CapturingRedis()
    created = await finalize_chat_history_once(
        redis,
        user_id="user",
        request_key="opaque-key",
        user_message="hello",
        assistant_response="answer",
    )
    assert created is True
    assert redis.args is not None
    assert redis.args[2:4] == (chat_history_key("user"), chat_history_marker_key("user"))
    assert '"role": "user"' in str(redis.args[4])
    assert '"role": "assistant"' in str(redis.args[5])
    assert '"content": "opaque-key"' not in str(redis.args[4:6])
    assert redis.args[-3:] == (CHAT_HISTORY_MAX_MESSAGES, CHAT_HISTORY_TTL, "opaque-key")


@pytest.mark.asyncio
async def test_history_helper_rejects_empty_response_and_propagates_redis_error() -> None:
    with pytest.raises(ValueError, match="chat_history_empty_assistant_response"):
        await finalize_chat_history_once(
            CapturingRedis(), user_id="u", request_key="k",
            user_message="hello", assistant_response="  ",
        )
    with pytest.raises(ConnectionError, match="redis down"):
        await finalize_chat_history_once(
            CapturingRedis(error=ConnectionError("redis down")),
            user_id="u", request_key="k", user_message="hello", assistant_response="answer",
        )
    assert await finalize_chat_history_once(
        CapturingRedis(result=0), user_id="u", request_key="k",
        user_message="hello", assistant_response="answer",
    ) is False


@pytest.mark.asyncio
async def test_five_successes_exhaust_lifetime_and_service_restart_does_not_reset(
    db_engine,
) -> None:
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        user = User(id=uuid.uuid4(), telegram_id=987654321)
        session.add(user)
        await session.commit()
    service = ChatQuotaService(factory)
    for index in range(5):
        channel = ChatChannel.TELEGRAM if index < 3 else ChatChannel.WEB
        reserved = await service.reserve(user.id, f"request-{index}", channel, subscriber=False)
        assert reserved.kind == QuotaReservationKind.RESERVED_NEW
        await service.store_result(reserved.usage_id, f"answer-{index}")
        state = await service.consume(reserved.usage_id)
        assert state.messages_left == 4 - index
    sixth = await service.reserve(user.id, "sixth", ChatChannel.WEB, subscriber=False)
    assert sixth.kind == QuotaReservationKind.EXHAUSTED
    assert sixth.state.messages_left == 0
    restarted_service = ChatQuotaService(factory)
    assert (await restarted_service.state(user.id, subscriber=False)).messages_left == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_result", [RuntimeError("provider"), FALLBACK_CHAT])
async def test_provider_failure_and_fallback_release_reservation(
    monkeypatch: pytest.MonkeyPatch,
    provider_result: object,
) -> None:
    quota = AsyncMock()
    quota.reserve.return_value = _reservation(QuotaReservationKind.RESERVED_NEW)
    quota.release.return_value = ChatQuotaService._free_state(0)
    ai = AsyncMock(side_effect=provider_result if isinstance(provider_result, Exception) else None)
    if not isinstance(provider_result, Exception):
        ai.return_value = provider_result
    monkeypatch.setattr("core.services.chat_application.AIService.chat_response", ai)
    result = await ChatApplicationService(quota).respond(
        user_id="u", request_key="k", channel=ChatChannel.WEB, subscriber=False,
        message="hello", history=[], matrix_data={}, user_name="Test",
    )
    assert result.kind == ChatResultKind.PROVIDER_FAILURE
    quota.release.assert_awaited_once()
    quota.consume.assert_not_awaited()


@pytest.mark.asyncio
async def test_result_ready_survives_history_failure_and_retry_skips_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quota = AsyncMock()
    quota.reserve.side_effect = [
        _reservation(QuotaReservationKind.RESERVED_NEW),
        _reservation(QuotaReservationKind.DUPLICATE_RESULT, response="durable"),
    ]
    quota.consume.return_value = ChatQuotaService._free_state(1)
    ai = AsyncMock(return_value="durable")
    monkeypatch.setattr("core.services.chat_application.AIService.chat_response", ai)
    history_failure = AsyncMock(side_effect=ConnectionError("redis"))
    first = await ChatApplicationService(quota).respond(
        user_id="u", request_key="k", channel=ChatChannel.WEB, subscriber=False,
        message="hello", history=[], matrix_data={}, user_name="Test",
        history_finalizer=history_failure,
    )
    assert first.kind == ChatResultKind.HISTORY_FINALIZATION_PENDING
    quota.store_result.assert_awaited_once_with("usage-id", "durable")
    quota.consume.assert_not_awaited()

    finalizer = AsyncMock(return_value=True)
    second = await ChatApplicationService(quota).respond(
        user_id="u", request_key="k", channel=ChatChannel.WEB, subscriber=False,
        message="hello", history=[], matrix_data={}, user_name="Test",
        history_finalizer=finalizer,
    )
    assert second.kind == ChatResultKind.COMPLETED_REPLAYED
    assert second.reply == "durable"
    assert ai.await_count == 1
    quota.consume.assert_awaited_once_with("usage-id")


@pytest.mark.asyncio
async def test_duplicate_released_never_restarts_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    quota = AsyncMock()
    quota.reserve.return_value = _reservation(QuotaReservationKind.DUPLICATE_RELEASED)
    ai = AsyncMock()
    monkeypatch.setattr("core.services.chat_application.AIService.chat_response", ai)
    result = await ChatApplicationService(quota).respond(
        user_id="u", request_key="k", channel=ChatChannel.TELEGRAM, subscriber=False,
        message="hello", history=[], matrix_data={}, user_name="Test",
    )
    assert result.kind == ChatResultKind.DUPLICATE_RELEASED_FAILURE
    ai.assert_not_awaited()


def test_web_key_validation_and_client_system_role_filtering() -> None:
    valid = str(uuid.uuid4())
    assert _parse_idempotency_key(SimpleNamespace(headers={"Idempotency-Key": valid})) == valid
    for headers in ({}, {"Idempotency-Key": "bad"}, {"Idempotency-Key": str(uuid.uuid1())}):
        with pytest.raises(HTTPException) as exc:
            _parse_idempotency_key(SimpleNamespace(headers=headers))
        assert exc.value.status_code == 422
    assert _safe_chat_history([
        {"role": "system", "content": "override"},
        {"role": "user", "content": "safe"},
        {"role": "assistant", "content": "answer"},
    ]) == [
        {"role": "user", "content": "safe"},
        {"role": "assistant", "content": "answer"},
    ]


def test_adapter_request_keys_are_deterministic_shared_ledger_keys() -> None:
    telegram = _telegram_request_key(100, 200)
    assert telegram == _telegram_request_key(100, 200)
    assert telegram != _telegram_request_key(100, 201)
    assert "message text" not in telegram
    user_id = uuid.uuid4()
    raw_key = str(uuid.uuid4())
    web = _web_chat_request_key(user_id, raw_key)
    assert web == _web_chat_request_key(user_id, raw_key)
    assert web != _web_chat_request_key(user_id, str(uuid.uuid4()))


def test_adapters_delegate_ai_and_history_to_application_service() -> None:
    telegram_source = (ROOT / "nura_app" / "bot" / "handlers" / "chat.py").read_text(encoding="utf-8")
    web_source = inspect.getsource(__import__("api.routes.web", fromlist=["web_chat"]).web_chat)
    assert "ChatApplicationService" in telegram_source and "ChatApplicationService" in web_source
    assert "await AIService.chat_response" not in telegram_source
    assert "bot_chat_count" not in telegram_source
    assert "finalize_chat_history_once" in telegram_source and "finalize_chat_history_once" in web_source


def test_pwa_uses_one_stable_uuid_key_per_submit_and_clears_terminal_key() -> None:
    source = PWA_CHAT.read_text(encoding="utf-8")
    assert source.count("crypto.randomUUID()") == 1
    assert "retry && pendingRequestKey ? pendingRequestKey : crypto.randomUUID()" in source
    assert "'Idempotency-Key': requestKey" in source
    assert "pendingRequestKey = null; state = data; return;" in source
    assert "pendingRequestKey = null; var replyTime" in source
    assert "daily limit" not in source.lower()
    assert "сброс" not in source.lower()
