"""User broadcast preference and allowlisted campaign CTA routing."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from core.database import get_async_sessionmaker
from core.services.broadcast import BroadcastCampaignService, BroadcastServiceError

router = Router()


def _settings_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Выключить" if enabled else "Включить",
                    callback_data=f"broadcast_pref:{'off' if enabled else 'on'}",
                )
            ],
            [InlineKeyboardButton(text="← В профиль", callback_data="profile")],
        ]
    )


def _settings_text(enabled: bool) -> str:
    state = "включены" if enabled else "выключены"
    return (
        "<b>Настройки сообщений</b>\n\n"
        f"Полезные сообщения NURA: <b>{state}</b>.\n\n"
        "Настройка относится к редакционным и коммерческим сообщениям. "
        "Сервисные уведомления об оплате и готовности материалов сохраняются."
    )


@router.message(Command("settings"))
async def settings_command(message: Message) -> None:
    service = BroadcastCampaignService(get_async_sessionmaker())
    try:
        enabled = await service.get_preference(message.from_user.id)
    except BroadcastServiceError:
        await message.answer("Пользователь не найден. Начни с /start")
        return
    await message.answer(_settings_text(enabled), reply_markup=_settings_keyboard(enabled))


@router.callback_query(F.data == "settings")
async def settings_callback(callback: CallbackQuery) -> None:
    service = BroadcastCampaignService(get_async_sessionmaker())
    try:
        enabled = await service.get_preference(callback.from_user.id)
    except BroadcastServiceError:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        _settings_text(enabled), reply_markup=_settings_keyboard(enabled)
    )


@router.callback_query(F.data.startswith("broadcast_pref:"))
async def update_broadcast_preference(callback: CallbackQuery) -> None:
    enabled = (callback.data or "").rsplit(":", 1)[-1] == "on"
    service = BroadcastCampaignService(get_async_sessionmaker())
    try:
        saved = await service.set_preference(callback.from_user.id, enabled)
    except BroadcastServiceError:
        await callback.answer("Не удалось сохранить настройку", show_alert=True)
        return
    await callback.answer("Настройка сохранена")
    await callback.message.edit_text(
        _settings_text(saved), reply_markup=_settings_keyboard(saved)
    )


@router.callback_query(F.data.startswith("bc:"))
@router.callback_query(F.data.startswith("bct:"))
async def campaign_cta(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("Кнопка недействительна", show_alert=True)
        return
    prefix, token, cta_key = parts
    service = BroadcastCampaignService(get_async_sessionmaker())
    try:
        if prefix == "bc":
            destination = await service.record_click(
                token, cta_key, callback.from_user.id
            )
        else:
            destination = await service.resolve_test_click(
                token, cta_key, callback.from_user.id
            )
    except BroadcastServiceError:
        await callback.answer("Кнопка недействительна", show_alert=True)
        return
    await _route_destination(callback, state, destination)


async def _route_destination(
    callback: CallbackQuery, state: FSMContext, destination: str
) -> None:
    target_data = {
        "main_menu": "main_menu",
        "chat": "chat_with_nura",
        "tarot_daily": "tarot_daily_card",
        "my_reports": "reports:list:0",
        "buy_matrix": "buy_matrix",
        "profile": "profile",
        "settings": "settings",
    }[destination]
    routed = callback.model_copy(update={"data": target_data})
    if destination == "main_menu":
        from bot.handlers.start import callback_main_menu

        await callback_main_menu(routed, state)
    elif destination == "chat":
        from bot.handlers.chat import enter_chat

        await enter_chat(routed, state)
    elif destination == "tarot_daily":
        from bot.handlers.tarot import show_tarot_daily_card

        await show_tarot_daily_card(routed)
    elif destination == "my_reports":
        from bot.handlers.profile import my_reports_list

        await my_reports_list(routed)
    elif destination == "buy_matrix":
        from bot.handlers.payment import buy_matrix

        await buy_matrix(routed)
    elif destination == "profile":
        from bot.handlers.profile import callback_profile

        await callback_profile(routed)
    else:
        await settings_callback(routed)
