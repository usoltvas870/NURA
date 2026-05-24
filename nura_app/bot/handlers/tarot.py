import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.main_menu import main_menu_keyboard
from bot.keyboards.tarot_keyboard import tarot_menu_keyboard, tarot_paywall_keyboard
from bot.states.tarot_state import TarotStates
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


TAROT_TEASER_TEXT = (
    "🃏 Ритуалы дня — твой ежедневный канал с архетипами.\n\n"
    "Каждый день новая карта — новый взгляд на то, что происходит "
    "в твоей жизни. Арканы подсказывают паттерны, которые уже "
    "разворачиваются вокруг тебя.\n\n"
    "✨ Что ты получишь:\n"
    "• 🂡 Карта дня — ежедневный архетип-проводник\n"
    "• 🂠 Расклад недели — сценарий ближайших 7 дней\n"
    "• ❓ Ответ на вопрос — расклад по твоей ситуации\n\n"
    "💎 Таро-доступ — 390 ₽/мес"
)


def _format_daily_card(data: dict) -> str:
    lines = [
        f"🃏 Твоя карта дня — {data['card_name']} ({data['card_number']} аркан)",
        "",
        data["key_phrase"],
        "",
        data["interpretation"],
    ]
    if data.get("matrix_link"):
        lines.extend(["", data["matrix_link"]])
    lines.extend([
        "",
        f"💡 Совет: {data['advice']}",
        f"🌀 Аффирмация: {data['affirmation']}",
    ])
    return "\n".join(lines)


def _format_weekly_spread(data: dict) -> str:
    body = data["body"]
    mind = data["mind"]
    spirit = data["spirit"]
    lines = [
        "📅 Расклад недели",
        "",
        f"🫀 Тело — {body['card_name']} ({body['card_number']} аркан)",
        body["energy"],
        body["interpretation"],
        f"→ {body['practice']}",
        "",
        f"🧠 Ум — {mind['card_name']} ({mind['card_number']} аркан)",
        mind["energy"],
        mind["interpretation"],
        f"→ {mind['practice']}",
        "",
        f"🌟 Дух — {spirit['card_name']} ({spirit['card_number']} аркан)",
        spirit["energy"],
        spirit["interpretation"],
        f"→ {spirit['practice']}",
        "",
        data["overall"],
    ]
    return "\n".join(lines)


def _format_question(data: dict) -> str:
    past = data["past"]
    present = data["present"]
    future = data["future"]
    lines = [
        "❓ Расклад по твоему вопросу",
        "",
        f"Прошлое — {past['card_name']} ({past['card_number']} аркан)",
        past["meaning"],
        past["how_it_relates"],
        "",
        f"Настоящее — {present['card_name']} ({present['card_number']} аркан)",
        present["meaning"],
        present["how_it_relates"],
        "",
        f"Будущее — {future['card_name']} ({future['card_number']} аркан)",
        future["meaning"],
        future["how_it_relates"],
        "",
        data["summary"],
        "",
        f"💡 Совет: {data['advice']}",
    ]
    return "\n".join(lines)


@router.message(Command("ritual"))
async def cmd_ritual(message: Message) -> None:
    user, has_sub = await _check_tarot_subscription(message.from_user.id)
    if user is None:
        await message.answer("Пользователь не найден. Начни с /start")
        return
    if not has_sub:
        await message.answer(TAROT_TEASER_TEXT, reply_markup=tarot_paywall_keyboard())
        return
    await message.answer(
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
    if not has_sub:
        await callback.message.edit_text(
            TAROT_TEASER_TEXT,
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
    if not has_sub:
        await callback.message.edit_text(
            TAROT_TEASER_TEXT,
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
        text = _format_daily_card(result)
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
    if not has_sub:
        await callback.message.edit_text(
            TAROT_TEASER_TEXT,
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
        text = _format_weekly_spread(result)
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
    if not has_sub:
        await callback.message.edit_text(
            TAROT_TEASER_TEXT,
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
    if not has_sub:
        await message.answer(
            TAROT_TEASER_TEXT,
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
        text = _format_question(result)
        await message.answer(text, reply_markup=tarot_menu_keyboard())
    except Exception as e:
        logger.error("tarot_question failed: %s", e, exc_info=True)
        await message.answer(
            "Что-то пошло не так. Попробуй ещё раз.",
            reply_markup=tarot_menu_keyboard(),
        )
    await state.clear()
