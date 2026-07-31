from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from core.config import settings
from core.schemas.chat import ChatRequest
from core.services.chat_application import ChatApplicationService, ChatResultKind
from core.services.chat_quota import (
    ChatChannel,
    ChatQuotaService,
    QuotaReservation,
    QuotaReservationKind,
)
from bot.handlers.chat import _has_unlimited_chat


def test_free_chat_limit_is_centralized_in_settings() -> None:
    assert settings.chat_free_message_limit == 5


def test_subscriber_requires_active_entitlement() -> None:
    now = datetime.now(timezone.utc)
    assert ChatQuotaService.is_subscriber(
        tarot_subscription=True,
        tarot_subscription_until=now + timedelta(seconds=1),
        subscription_status="free",
        subscription_until=None,
        now=now,
    )


def test_has_matrix_never_grants_unlimited_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bot.handlers.chat.settings.test_mode", False)
    now = datetime.now(timezone.utc)
    has_matrix_only = type("User", (), {
        "has_matrix": True,
        "tarot_subscription": False,
        "tarot_subscription_until": None,
        "subscription_status": "free",
        "subscription_until": None,
    })()
    expired_premium = type("User", (), {
        "has_matrix": False,
        "tarot_subscription": False,
        "tarot_subscription_until": None,
        "subscription_status": "premium",
        "subscription_until": now - timedelta(seconds=1),
    })()
    active_premium = type("User", (), {
        "has_matrix": False,
        "tarot_subscription": False,
        "tarot_subscription_until": None,
        "subscription_status": "premium",
        "subscription_until": now + timedelta(seconds=1),
    })()
    assert not _has_unlimited_chat(has_matrix_only)
    assert not _has_unlimited_chat(expired_premium)
    assert _has_unlimited_chat(active_premium)
    assert not ChatQuotaService.is_subscriber(
        tarot_subscription=True,
        tarot_subscription_until=now - timedelta(seconds=1),
        subscription_status="premium",
        subscription_until=now - timedelta(seconds=1),
        now=now,
    )


def test_chat_request_rejects_whitespace_only_message() -> None:
    with pytest.raises(ValueError):
        ChatRequest(message=" \n\t ")


@pytest.mark.asyncio
async def test_application_service_does_not_send_ai_when_daily_quota_is_exhausted() -> None:
    quota = AsyncMock()
    quota.reserve.return_value = QuotaReservation(
        QuotaReservationKind.EXHAUSTED,
        None,
        ChatQuotaService._free_state(settings.chat_free_message_limit),
    )
    result = await ChatApplicationService(quota).respond(
        user_id="u", request_key="opaque", channel=ChatChannel.WEB,
        subscriber=False, message="hello", history=[], matrix_data={}, user_name="Test",
    )
    assert result.kind == ChatResultKind.QUOTA_EXHAUSTED
    quota.reserve.assert_awaited_once()
    quota.consume.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_completed_request_replays_durable_response_without_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quota = AsyncMock()
    quota.reserve.return_value = QuotaReservation(
        QuotaReservationKind.DUPLICATE_RESULT,
        "usage-1",
        ChatQuotaService._free_state(1),
        response_text="Durable answer",
    )
    ai = AsyncMock()
    monkeypatch.setattr(
        "core.services.chat_application.AIService.chat_response_with_metadata", ai
    )

    result = await ChatApplicationService(quota).respond(
        user_id="u", request_key="opaque", channel=ChatChannel.TELEGRAM,
        subscriber=False, message="hello", history=[], matrix_data={}, user_name="Test",
    )

    assert result.kind == ChatResultKind.COMPLETED_REPLAYED
    assert result.reply == "Durable answer"
    assert result.replayed is True
    ai.assert_not_awaited()
    quota.consume.assert_not_awaited()
    assert result.usage_id == "usage-1"
