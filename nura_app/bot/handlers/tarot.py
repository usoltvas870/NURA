import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.helpers.tarot_formatter import format_tarot_message, format_tarot_paywall
from bot.keyboards.main_menu import main_menu_keyboard
from bot.keyboards.tarot_keyboard import tarot_menu_keyboard, tarot_paywall_keyboard
from bot.states.tarot_state import TarotStates
from core.config import settings
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository
from core.services.ai import AIService

logger = logging.getLogger(__name__)

router = Router()


async def _get_user(telegram_id: int):
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    return await user_repo.get_by_telegram_id(telegram_id)


async def _check_tarot_subscription(
    telegram_id: int,
) -> tuple:
    user = await _get_user(telegram_id)
    if user is None:
        return None, False
    return user, bool(user.tarot_subscription)




@router.message(Command("ritual"))
async def cmd_ritual(message: Message) -> None:
    user, has_sub = await _check_tarot_subscription(message.from_user.id)
    if user is None:
        await message.answer("Пользователь не найден. Начни с /start")
        return
    if not has_sub and not settings.test_mode:
        await message.answer(format_tarot_paywall(), reply_markup=tarot_paywall_keyboard())
        return
    await message.answer(
        "🃏 Ритуалы дня\n\nВыбери, что хочешь узнать сегодня:",
        reply_markup=tarot_menu_keyboard(),
    )


@router.callback_query(F.data == "ritual")
async def callback_ritual(callback: CallbackQuery) -> None:
    await callback.answer()
    user, has_sub = await _check_tarot_subscription(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return
    if not has_sub and not settings.test_mode:
        await callback.message.edit_text(
            format_tarot_paywall(),
            reply_markup=tarot_paywall_keyboard(),
        )
        return
    await callback.message.edit_text(
        "🃏 Ритуалы дня\n\nВыбери, что хочешь узнать сегодня:",
        reply_markup=tarot_menu_keyboard(),
    )


@router.callback_query(F.data == "tarot_menu")
async def show_tarot_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    user, has_sub = await _check_tarot_subscription(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return
    if not has_sub and not settings.test_mode:
        await callback.message.edit_text(
            format_tarot_paywall(),
            reply_markup=tarot_paywall_keyboard(),
        )
        return
    await callback.message.edit_text(
        "🃏 Ритуалы дня\n\nВыбери, что хочешь узнать сегодня:",
        reply_markup=tarot_menu_keyboard(),
    )


@router.callback_query(F.data == "tarot_daily_card")
async def show_tarot_daily_card(callback: CallbackQuery) -> None:
    await callback.answer()
    user, has_sub = await _check_tarot_subscription(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return
    if not has_sub and not settings.test_mode:
        await callback.message.edit_text(
            format_tarot_paywall(),
            reply_markup=tarot_paywall_keyboard(),
        )
        return
    if not user.birth_date:
        await callback.message.edit_text(
            "Сначала укажи дату рождения в профиле.",
            reply_markup=main_menu_keyboard(),
        )
        return
    try:
        result = await AIService.generate_tarot_daily_card(user.birth_date, user)
        text = format_tarot_message(result, "daily")
        await callback.message.edit_text(text, reply_markup=tarot_menu_keyboard())
    except Exception as e:
        logger.error("tarot_daily_card failed: %s", e, exc_info=True)
        await callback.message.edit_text(
            "Что-то пошло не так. Попробуй ещё раз.",
            reply_markup=tarot_menu_keyboard(),
        )


@router.callback_query(F.data == "tarot_weekly_spread")
async def show_tarot_weekly_spread(callback: CallbackQuery) -> None:
    await callback.answer()
    user, has_sub = await _check_tarot_subscription(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return
    if not has_sub and not settings.test_mode:
        await callback.message.edit_text(
            format_tarot_paywall(),
            reply_markup=tarot_paywall_keyboard(),
        )
        return
    if not user.birth_date:
        await callback.message.edit_text(
            "Сначала укажи дату рождения в профиле.",
            reply_markup=main_menu_keyboard(),
        )
        return
    try:
        result = await AIService.generate_tarot_weekly_spread(user.birth_date, user)
        text = format_tarot_message(result, "spread")
        await callback.message.edit_text(text, reply_markup=tarot_menu_keyboard())
    except Exception as e:
        logger.error("tarot_weekly_spread failed: %s", e, exc_info=True)
        await callback.message.edit_text(
            "Что-то пошло не так. Попробуй ещё раз.",
            reply_markup=tarot_menu_keyboard(),
        )


@router.callback_query(F.data == "tarot_ask_question")
async def ask_tarot_question(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user, has_sub = await _check_tarot_subscription(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return
    if not has_sub and not settings.test_mode:
        await callback.message.edit_text(
            format_tarot_paywall(),
            reply_markup=tarot_paywall_keyboard(),
        )
        return
    await state.set_state(TarotStates.waiting_question)
    await callback.message.edit_text(
        "Напиши свой вопрос — и я сделаю расклад по ситуации.",
    )


@router.message(TarotStates.waiting_question)
async def handle_tarot_question(message: Message, state: FSMContext) -> None:
    user, has_sub = await _check_tarot_subscription(message.from_user.id)
    if user is None:
        await message.answer("Пользователь не найден. Начни с /start")
        await state.clear()
        return
    if not has_sub and not settings.test_mode:
        await message.answer(
            format_tarot_paywall(),
            reply_markup=tarot_paywall_keyboard(),
        )
        await state.clear()
        return
    if not user.birth_date:
        await message.answer(
            "Сначала укажи дату рождения в профиле.",
            reply_markup=main_menu_keyboard(),
        )
        await state.clear()
        return
    question = message.text
    if not question:
        await message.answer("Напиши свой вопрос текстом.")
        return
    try:
        result = await AIService.generate_tarot_question(user.birth_date, question, user)
        text = format_tarot_message(result, "question")
        await message.answer(text, reply_markup=tarot_menu_keyboard())
    except Exception as e:
        logger.error("tarot_question failed: %s", e, exc_info=True)
        await message.answer(
            "Что-то пошло не так. Попробуй ещё раз.",
            reply_markup=tarot_menu_keyboard(),
        )
    await state.clear()
