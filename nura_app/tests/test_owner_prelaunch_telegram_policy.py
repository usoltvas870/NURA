"""Canonical Telegram restricted-access behavior in owner prelaunch."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiogram import Bot
from aiogram.methods import SendMessage
from aiogram.types import User as TelegramUser

from core.config import settings
from core.services.telegram_sandbox import (
    RestrictedTelegramBot,
    RestrictedTelegramInboundMiddleware,
    TelegramRecipientBlocked,
    require_telegram_recipient_allowed,
    telegram_user_is_allowed,
)


@pytest.fixture(autouse=True)
def owner_prelaunch_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "prelaunch_owner_only", True)
    monkeypatch.setattr(settings, "prelaunch_telegram_allowed_user_ids", "101")
    monkeypatch.setattr(settings, "payments_enabled", False)


@pytest.mark.asyncio
async def test_owner_inbound_reaches_handler() -> None:
    handler = AsyncMock(return_value="handled")
    user = TelegramUser(id=101, is_bot=False, first_name="Owner")

    result = await RestrictedTelegramInboundMiddleware()(
        handler,
        SimpleNamespace(),
        {"event_from_user": user},
    )

    assert result == "handled"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_outsider_inbound_stops_before_persistence_or_handler() -> None:
    handler = AsyncMock()
    user = TelegramUser(id=999, is_bot=False, first_name="Outsider")

    result = await RestrictedTelegramInboundMiddleware()(
        handler,
        SimpleNamespace(),
        {"event_from_user": user},
    )

    assert result is None
    handler.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "telegram_user",
    [
        None,
        TelegramUser(id=101, is_bot=True, first_name="Owner bot"),
    ],
)
async def test_unknown_or_bot_sender_is_blocked_fail_closed(
    telegram_user: TelegramUser | None,
) -> None:
    handler = AsyncMock()

    result = await RestrictedTelegramInboundMiddleware()(
        handler,
        SimpleNamespace(),
        {"event_from_user": telegram_user},
    )

    assert result is None
    handler.assert_not_awaited()


def test_owner_outbound_allowed_and_outsider_gets_terminal_error() -> None:
    require_telegram_recipient_allowed(101)
    with pytest.raises(
        TelegramRecipientBlocked,
        match="prelaunch_telegram_recipient_not_allowed",
    ) as exc_info:
        require_telegram_recipient_allowed(999)

    assert exc_info.value.code == "prelaunch_telegram_recipient_not_allowed"


@pytest.mark.asyncio
async def test_current_production_bot_needs_no_sandbox_identity_evidence() -> None:
    bot = RestrictedTelegramBot(token="42:TEST")
    transport = AsyncMock(return_value=SimpleNamespace(message_id=1))
    with patch.object(Bot, "__call__", transport):
        await bot(SendMessage(chat_id=101, text="bounded fixture"))

    transport.assert_awaited_once()
    await bot.session.close()


def test_normal_production_remains_unrestricted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "prelaunch_owner_only", False)

    assert telegram_user_is_allowed(999) is True
    require_telegram_recipient_allowed(999)


def test_admin_bot_applies_restricted_guard_before_admin_middleware() -> None:
    source = (
        Path(__file__).parents[1] / "admin_bot" / "main.py"
    ).read_text(encoding="utf-8")

    restricted = source.index(
        "dp.message.middleware(RestrictedTelegramInboundMiddleware())"
    )
    admin_only = source.index("dp.message.middleware(admin_mw)")
    assert restricted < admin_only
