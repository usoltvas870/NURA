from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiogram import Bot
from aiogram.methods import SendMessage
from aiogram.types import User as TelegramUser

from bot.handlers.profile import _show_profile
from core.config import settings
from bot.keyboards.main_menu import (
    main_menu_keyboard,
    open_pwa_keyboard,
    pwa_cta_keyboard,
)
from bot.keyboards.tarot_keyboard import tarot_result_keyboard
from bot.texts.start import welcome_back_text
from core.services.chat_telegram_delivery import TelegramChatDeliveryService
from core.services.telegram_sandbox import (
    SandboxGuardedBot,
    SandboxTelegramInboundMiddleware,
    SandboxTelegramRecipientBlocked,
    require_telegram_recipient_allowed,
    verify_telegram_identity_with,
)


@pytest.fixture(autouse=True)
def sandbox_policy(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "sandbox")
    monkeypatch.setattr(settings, "sandbox_environment_id", "nura-sbx-policy")
    monkeypatch.setattr(settings, "sandbox_telegram_allowed_user_ids", "101")
    monkeypatch.setattr(settings, "sandbox_telegram_bot_id", 777)
    monkeypatch.setattr(settings, "sandbox_telegram_bot_username", "nura_sandbox_bot")


@pytest.mark.asyncio
async def test_disallowed_inbound_stops_before_handler_or_persistence() -> None:
    middleware = SandboxTelegramInboundMiddleware()
    handler = AsyncMock()
    telegram_user = TelegramUser(id=999, is_bot=False, first_name="Blocked")

    result = await middleware(
        handler,
        SimpleNamespace(),
        {"event_from_user": telegram_user},
    )

    assert result is None
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_allowed_inbound_reaches_handler() -> None:
    middleware = SandboxTelegramInboundMiddleware()
    handler = AsyncMock(return_value="handled")
    telegram_user = TelegramUser(id=101, is_bot=False, first_name="Allowed")

    result = await middleware(
        handler,
        SimpleNamespace(),
        {"event_from_user": telegram_user},
    )

    assert result == "handled"
    handler.assert_awaited_once()


def test_outbound_recipient_is_checked_before_transport() -> None:
    require_telegram_recipient_allowed(101)
    with pytest.raises(
        SandboxTelegramRecipientBlocked,
        match="sandbox_telegram_recipient_not_allowed",
    ):
        require_telegram_recipient_allowed(999)


def test_sandbox_generated_telegram_ui_contains_no_production_url() -> None:
    markups = (
        main_menu_keyboard(),
        main_menu_keyboard(has_matrix=True),
        pwa_cta_keyboard(),
        open_pwa_keyboard(),
        tarot_result_keyboard(),
    )
    urls = [
        button.url
        for markup in markups
        for row in markup.inline_keyboard
        for button in row
        if button.url
    ]

    assert not urls
    assert "nura-ai.ru" not in welcome_back_text("Test", "Mage")


@pytest.mark.asyncio
async def test_sandbox_bot_requires_identity_evidence_before_transport() -> None:
    bot = SandboxGuardedBot(token="42:TEST")
    transport = AsyncMock()
    with patch(
        "core.services.telegram_sandbox.require_telegram_identity_evidence",
        side_effect=RuntimeError("sandbox_telegram_identity_evidence_required"),
    ), patch.object(Bot, "__call__", transport):
        with pytest.raises(
            RuntimeError,
            match="sandbox_telegram_identity_evidence_required",
        ):
            await bot(SendMessage(chat_id=101, text="bounded fixture"))

    transport.assert_not_awaited()
    await bot.session.close()


@pytest.mark.asyncio
async def test_disabled_referral_promotion_emits_no_telegram_link(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "enable_referral_promotion", False)
    monkeypatch.setattr(settings, "bot_username", "production_bot")
    message = SimpleNamespace(answer=AsyncMock())
    user = SimpleNamespace(
        first_name="Test",
        username=None,
        main_archetype="Mage",
        subscription_status="free",
        tarot_subscription=False,
        birth_date=None,
        telegram_id=101,
    )

    await _show_profile(message, user, [])

    text = message.answer.await_args.args[0]
    assert "t.me/" not in text
    assert "production_bot" not in text


@pytest.mark.asyncio
async def test_disallowed_chat_delivery_does_not_send_or_consume_quota() -> None:
    claim = SimpleNamespace(
        usage_id="usage-1",
        attempt=1,
        chat_id=999,
        response_text="persisted response",
        total_chunks=1,
        next_chunk_index=0,
    )
    quota = SimpleNamespace(
        claim_telegram_delivery=AsyncMock(return_value=claim),
        fail_telegram_delivery=AsyncMock(return_value="released"),
        mark_telegram_chunk_delivered=AsyncMock(),
        complete_telegram_delivery=AsyncMock(),
    )
    send = AsyncMock()

    result = await TelegramChatDeliveryService(quota).deliver(
        claim.usage_id,
        send_chunk=send,
    )

    assert result.status == "failed"
    assert result.retryable is False
    send.assert_not_awaited()
    quota.mark_telegram_chunk_delivered.assert_not_awaited()
    quota.complete_telegram_delivery.assert_not_awaited()
    quota.fail_telegram_delivery.assert_awaited_once_with(
        claim.usage_id,
        claim.attempt,
        error_code="sandbox_telegram_recipient_not_allowed",
        retryable=False,
    )


class _FakeIdentityVerifier:
    def __init__(self, bot_id: int, username: str) -> None:
        self.bot_id = bot_id
        self.username = username
        self.calls = 0

    async def get_identity(self) -> tuple[int, str]:
        self.calls += 1
        return self.bot_id, self.username


@pytest.mark.asyncio
async def test_injected_bot_identity_verifier_matches_and_mismatch_blocks() -> None:
    matching = _FakeIdentityVerifier(777, "@nura_sandbox_bot")

    evidence = await verify_telegram_identity_with(matching)

    assert evidence["status"] == "verified"
    assert matching.calls == 1
    with pytest.raises(Exception, match="sandbox_telegram_identity_mismatch"):
        await verify_telegram_identity_with(_FakeIdentityVerifier(778, "other_bot"))
