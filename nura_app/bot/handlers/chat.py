import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.main_menu import chat_keyboard, main_menu_keyboard
from bot.states.chat_state import ChatStates
from bot.texts.chat import exit_text, greeting_text, history_cleared_text, paywall_text
from bot.texts.start import unknown_message_text
from core.database import get_async_sessionmaker
from core.repositories.report import ReportRepository
from core.repositories.user import UserRepository
from core.services.ai import AIService

logger = logging.getLogger(__name__)

router = Router()


async def _get_user_matrix_data(telegram_id: int):
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    report_repo = ReportRepository(session_factory)
    user = await user_repo.get_by_telegram_id(telegram_id)
    if user is None:
        return None, None, None

    reports = await report_repo.get_by_user_id(user.id)
    matrix_report = None
    for r in reports:
        if r.matrix_data and r.report_type in ("mini", "full"):
            matrix_report = r
            break

    return user, matrix_report, reports


def _has_chat_access(user, reports) -> bool:
    if user.subscription_status == "premium":
        return True
    for r in reports:
        if r.report_type == "full":
            return True
    return False


@router.callback_query(F.data == "chat_with_nura")
async def enter_chat(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()

    user, matrix_report, reports = await _get_user_matrix_data(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return

    if not _has_chat_access(user, reports):
        last_mini_report = None
        for r in reports:
            if r.report_type == "mini":
                last_mini_report = r
        token = last_mini_report.token if last_mini_report else ""
        text = paywall_text()

        from bot.keyboards.main_menu import InlineKeyboardMarkup, InlineKeyboardButton

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✨ Полный отчёт 590 ₽", callback_data=f"pay_full_report:{token}")],
                [InlineKeyboardButton(text="💎 Подписка 390 ₽/мес", callback_data="buy_subscription")],
                [InlineKeyboardButton(text="👤 Назад в профиль", callback_data="back_to_profile")],
            ]
        )
        await callback.message.edit_text(text, reply_markup=kb)
        return

    name = user.first_name or user.username or "пользователь"
    archetype_name = user.main_archetype or "Неизвестный"

    await state.set_state(ChatStates.chatting)
    await state.update_data(chat_history=[])

    if matrix_report and matrix_report.matrix_data:
        await state.update_data(matrix_data=matrix_report.matrix_data)
    await state.update_data(user_name=name)

    text = greeting_text(name, archetype_name)
    await callback.message.edit_text(text, reply_markup=chat_keyboard())


@router.message(ChatStates.chatting)
async def chat_message(message: Message, state: FSMContext) -> None:
    state_data = await state.get_data()
    chat_history = state_data.get("chat_history", [])
    matrix_data = state_data.get("matrix_data")
    user_name = state_data.get("user_name", message.from_user.first_name or "пользователь")

    if not matrix_data:
        session_factory = get_async_sessionmaker()
        report_repo = ReportRepository(session_factory)
        user_repo = UserRepository(session_factory)
        user = await user_repo.get_by_telegram_id(message.from_user.id)
        if user:
            reports = await report_repo.get_by_user_id(user.id)
            for r in reports:
                if r.matrix_data and r.report_type in ("mini", "full"):
                    matrix_data = r.matrix_data
                    await state.update_data(matrix_data=matrix_data)
                    break

    chat_history.append({"role": "user", "content": message.text})

    response = await AIService.chat_response(
        user_message=message.text,
        chat_history=chat_history,
        matrix_data=matrix_data or {},
        user_name=user_name,
    )

    chat_history.append({"role": "assistant", "content": response})
    await state.update_data(chat_history=chat_history)

    await message.answer(response, reply_markup=chat_keyboard())


@router.callback_query(F.data == "chat_exit")
@router.message(Command("exit"))
async def exit_chat(event: Message | CallbackQuery, state: FSMContext) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer()
        message = event.message
        user_id = event.from_user.id
    else:
        message = event
        user_id = event.from_user.id

    await state.set_state(ChatStates.idle)
    await state.update_data(chat_history=[])

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(user_id)
    name = user.first_name or user.username or "пользователь" if user else "пользователь"

    await message.answer(exit_text(name), reply_markup=main_menu_keyboard())


@router.callback_query(F.data == "chat_clear")
async def clear_chat(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(chat_history=[])
    await callback.message.answer(history_cleared_text(), reply_markup=chat_keyboard())


@router.message(ChatStates.idle)
async def unknown_message_handler(message: Message) -> None:
    await message.answer(unknown_message_text())
