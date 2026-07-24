import json
import logging

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.main_menu import main_menu_keyboard, pwa_cta_keyboard
from bot.states.chat_state import ChatStates
from bot.texts.chat import (
    exit_text,
    greeting_text_free,
    greeting_text_unlimited,
    history_cleared_text,
    messages_remaining_text,
    paywall_text,
)
from bot.texts.start import help_text
from bot.utils.formatting import (
    TELEGRAM_INPUT_MAX_LENGTH,
    TELEGRAM_MESSAGE_MAX_LENGTH,
    split_telegram_html_text,
)
from core.config import settings
from core.database import get_async_sessionmaker, get_redis
from core.repositories.report import ReportRepository
from core.repositories.user import UserRepository
from core.services.ai import AIService

logger = logging.getLogger(__name__)

router = Router()

FREE_MESSAGES_LIMIT = 5
CHAT_HISTORY_TTL = 7 * 86400
CHAT_HISTORY_MAX_MESSAGES = 20


def _history_key(uid: int) -> str:
    return f"chat:history:{uid}"


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


def _has_chat_access(user) -> bool:
    return True


def _has_unlimited_chat(user, reports: list | None = None) -> bool:  # noqa: ARG001
    if settings.test_mode:
        return True
    if user.subscription_status == "premium":
        return True
    if user.has_matrix:
        return True
    return False


@router.callback_query(F.data == "chat_with_nura")
async def enter_chat(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()

    user, matrix_report, reports = await _get_user_matrix_data(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(has_matrix=False),
        )
        return

    if not _has_chat_access(user):
        text = paywall_text()
        await callback.message.edit_text(text, reply_markup=pwa_cta_keyboard())
        return

    name = user.first_name or user.username or "пользователь"
    archetype_name = user.main_archetype or "Неизвестный"

    redis = get_redis()
    history_key = _history_key(callback.from_user.id)
    raw_history = await redis.get(history_key)
    chat_history: list[dict] = []
    if raw_history:
        try:
            chat_history = json.loads(raw_history)
        except (json.JSONDecodeError, TypeError):
            chat_history = []

    await state.set_state(ChatStates.chatting)
    await state.update_data(chat_history=chat_history)

    if matrix_report and matrix_report.matrix_data:
        await state.update_data(matrix_data=matrix_report.matrix_data)
    await state.update_data(user_name=name)

    if _has_unlimited_chat(user, reports):
        await state.update_data(chat_messages_left=-1)
        text = greeting_text_unlimited(name, archetype_name)
    else:
        redis = get_redis()
        counter_key = f"bot_chat_count:{callback.from_user.id}"
        raw = await redis.get(counter_key)
        used = int(raw) if raw else 0
        messages_left = max(0, FREE_MESSAGES_LIMIT - used)
        await state.update_data(chat_messages_left=messages_left)
        text = greeting_text_free(name, archetype_name)

    await callback.message.edit_text(text)


@router.message(Command(commands=["start", "menu", "help"]), ChatStates.chatting)
async def chat_command_exit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🚪 Вышел из чата.")

    if message.text.startswith("/start"):
        from bot.handlers.onboarding import cmd_start
        await cmd_start(message, state)
    elif message.text.startswith("/menu"):
        from bot.handlers.start import cmd_menu
        await cmd_menu(message)
    elif message.text.startswith("/help"):
        await message.answer(help_text())


@router.message(ChatStates.chatting)
async def chat_message(message: Message, state: FSMContext) -> None:
    user_message = message.text
    if not user_message or not user_message.strip():
        await message.answer("Напиши сообщение текстом.")
        return
    if len(user_message) > TELEGRAM_INPUT_MAX_LENGTH:
        await message.answer(
            f"Сообщение слишком длинное. Максимум — {TELEGRAM_INPUT_MAX_LENGTH} символов."
        )
        return

    state_data = await state.get_data()
    chat_history = state_data.get("chat_history", [])
    matrix_data = state_data.get("matrix_data")
    user_name = state_data.get("user_name", message.from_user.first_name or "пользователь")
    messages_left = state_data.get("chat_messages_left", 0)

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

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    chat_history.append({"role": "user", "content": user_message})

    response = await AIService.chat_response(
        user_message=user_message,
        chat_history=chat_history,
        matrix_data=matrix_data or {},
        user_name=user_name,
    )

    chat_history.append({"role": "assistant", "content": response})
    if len(chat_history) > CHAT_HISTORY_MAX_MESSAGES:
        chat_history = chat_history[-CHAT_HISTORY_MAX_MESSAGES:]
    await state.update_data(chat_history=chat_history)

    try:
        redis = get_redis()
        await redis.setex(
            _history_key(message.from_user.id),
            CHAT_HISTORY_TTL,
            json.dumps(chat_history, ensure_ascii=False),
        )
    except Exception:
        pass

    if messages_left > 0:
        redis = get_redis()
        counter_key = f"bot_chat_count:{message.from_user.id}"
        new_count = await redis.incr(counter_key)
        if new_count == 1:
            await redis.expire(counter_key, 86400)
        messages_left = max(0, FREE_MESSAGES_LIMIT - new_count)
        await state.update_data(chat_messages_left=messages_left)

    suffix = ""
    if messages_left == 0:
        suffix = messages_remaining_text(0)
    elif messages_left > 0:
        suffix = messages_remaining_text(messages_left)

    response_chunks = split_telegram_html_text(
        response,
        max_length=TELEGRAM_MESSAGE_MAX_LENGTH - len(suffix),
    )
    response_chunks[-1] += suffix
    for response_chunk in response_chunks:
        await message.answer(response_chunk)

    if messages_left == 0:
        await message.answer(paywall_text(), reply_markup=pwa_cta_keyboard())
        await state.clear()
        return


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

    await state.clear()

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(user_id)
    name = user.first_name or user.username or "пользователь" if user else "пользователь"

    has_matrix = user and user.birth_date is not None
    await message.answer(exit_text(name), reply_markup=main_menu_keyboard(has_matrix=has_matrix))


@router.callback_query(F.data == "chat_clear")
async def clear_chat(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(chat_history=[])
    try:
        redis = get_redis()
        await redis.delete(_history_key(callback.from_user.id))
    except Exception:
        pass
    await callback.message.answer(history_cleared_text())
