import hashlib
import json
import logging

from aiogram import F, Router
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
from core.services.ai import AIService  # noqa: F401
from core.services.chat_application import ChatApplicationService, ChatResultKind
from core.services.chat_history import finalize_chat_history_once
from core.services.chat_quota import ChatChannel, ChatQuotaService

logger = logging.getLogger(__name__)

router = Router()

def _history_key(uid: object) -> str:
    return f"chat:history:{uid}"


def _telegram_request_key(chat_id: int, message_id: int) -> str:
    return hashlib.sha256(f"telegram:{chat_id}:{message_id}".encode()).hexdigest()


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
    history_key = _history_key(user.id)
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

    subscriber = ChatQuotaService.is_subscriber(
        tarot_subscription=bool(user.tarot_subscription),
        tarot_subscription_until=user.tarot_subscription_until,
        subscription_status=user.subscription_status,
        subscription_until=user.subscription_until,
    )
    quota_state = await ChatQuotaService(get_async_sessionmaker()).state(
        user.id, subscriber=subscriber
    )
    if subscriber:
        await state.update_data(chat_messages_left=-1)
        text = greeting_text_unlimited(name, archetype_name)
    else:
        messages_left = quota_state.messages_left or 0
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

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(message.from_user.id)
    if user is None:
        await message.answer("Пользователь не найден. Начни с /start")
        return
    subscriber = ChatQuotaService.is_subscriber(
        tarot_subscription=bool(user.tarot_subscription),
        tarot_subscription_until=user.tarot_subscription_until,
        subscription_status=user.subscription_status,
        subscription_until=user.subscription_until,
    )
    request_key = _telegram_request_key(message.chat.id, message.message_id)
    result = await ChatApplicationService(ChatQuotaService(session_factory)).respond(
        user_id=user.id,
        request_key=request_key,
        channel=ChatChannel.TELEGRAM,
        subscriber=subscriber,
        message=user_message,
        history=chat_history,
        matrix_data=matrix_data or {},
        user_name=user_name,
        history_finalizer=lambda reply: finalize_chat_history_once(
            get_redis(),
            user_id=user.id,
            request_key=request_key,
            user_message=user_message,
            assistant_response=reply,
        ),
    )
    if result.kind == ChatResultKind.QUOTA_EXHAUSTED:
        await message.answer(paywall_text(), reply_markup=pwa_cta_keyboard())
        await state.clear()
        return
    if result.kind == ChatResultKind.IN_PROGRESS:
        await message.answer("Это сообщение уже обрабатывается. Попробуй немного позже.")
        return
    if result.kind not in {ChatResultKind.COMPLETED_NEW, ChatResultKind.COMPLETED_REPLAYED}:
        await message.answer("Сервис временно недоступен. Сообщение не списано.")
        return
    chat_history = result.history
    await state.update_data(chat_history=chat_history, chat_user_id=str(user.id))
    suffix = "" if subscriber else messages_remaining_text(result.quota.messages_left or 0)
    response_chunks = split_telegram_html_text(
        result.reply or "", max_length=TELEGRAM_MESSAGE_MAX_LENGTH - len(suffix),
    )
    response_chunks[-1] += suffix
    for response_chunk in response_chunks:
        await message.answer(response_chunk)
    if not subscriber and result.quota.messages_left == 0:
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
        session_factory = get_async_sessionmaker()
        user = await UserRepository(session_factory).get_by_telegram_id(callback.from_user.id)
        if user is not None:
            await redis.delete(_history_key(user.id))
    except Exception:
        pass
    await callback.message.answer(history_cleared_text())
