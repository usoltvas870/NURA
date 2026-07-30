from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.compatibility import _reject_compatibility
from bot.handlers.tarot import _reject_expanded_tarot
from bot.keyboards.main_menu import main_menu_keyboard
from bot.keyboards.tarot_keyboard import tarot_menu_keyboard


def _callback() -> MagicMock:
    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()
    return callback


@pytest.mark.asyncio
async def test_disabled_expanded_tarot_blocks_direct_callback_and_clears_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.handlers.tarot.settings.enable_expanded_tarot", False)
    callback = _callback()
    state = MagicMock()
    state.clear = AsyncMock()

    assert await _reject_expanded_tarot(callback, state)
    state.clear.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_disabled_compatibility_blocks_direct_callback_and_clears_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bot.handlers.compatibility.settings.enable_compatibility", False)
    callback = _callback()
    state = MagicMock()
    state.clear = AsyncMock()

    assert await _reject_compatibility(callback, state)
    state.clear.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()


def test_default_nura_1_0_menu_hides_early_surfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bot.keyboards.main_menu.settings.enable_compatibility", False)

    main_callbacks = {
        button.callback_data
        for row in main_menu_keyboard().inline_keyboard
        for button in row
        if button.callback_data
    }
    tarot_callbacks = {
        button.callback_data
        for row in tarot_menu_keyboard(has_tarot=True).inline_keyboard
        for button in row
        if button.callback_data
    }
    assert "compatibility" not in main_callbacks
    assert tarot_callbacks == {"tarot_daily_card", "main_menu"}


def test_explicit_flags_restore_existing_navigation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bot.keyboards.main_menu.settings.enable_compatibility", True)
    main_callbacks = {
        button.callback_data
        for row in main_menu_keyboard().inline_keyboard
        for button in row
        if button.callback_data
    }
    tarot_callbacks = {
        button.callback_data
        for row in tarot_menu_keyboard(has_tarot=True, expanded_enabled=True).inline_keyboard
        for button in row
        if button.callback_data
    }
    assert "compatibility" in main_callbacks
    assert "tarot_more" in tarot_callbacks
