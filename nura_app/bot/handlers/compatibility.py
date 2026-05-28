import asyncio
import logging
from urllib.parse import quote

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from celery.result import AsyncResult

from bot.handlers.validators import validate_date
from bot.states.compatibility_state import CompatibilityStates
from bot.texts.compatibility import (
    explanation_text,
    loading_steps,
    mini_compatibility_text,
)
from bot.texts.matrix import invalid_format_text
from core.config import settings
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository
from core.tasks import generate_compatibility_report

logger = logging.getLogger(__name__)

router = Router()

POLL_INTERVAL = 2
MAX_POLL_SECONDS = 90


def _has_unlimited_compat(user) -> bool:
    """Безлимитная совместимость: подписка таро ИЛИ subscription_status=premium."""
    return bool(user.tarot_subscription) or user.subscription_status == "premium"


@router.callback_query(F.data == "compatibility")
async def ask_compatibility(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(callback.from_user.id)

    if user is None:
        await callback.message.edit_text("Пользователь не найден. Начни с /start")
        return

    # Ветка A: нет матрицы → пейволл матрицы
    if not user.has_matrix:
        await callback.message.edit_text(
            "❤️ Совместимость\n\n"
            "Введи дату рождения любого человека —\n"
            "я разберу вашу совместимость по матрицам.\n\n"
            "Доступно с покупкой Матрицы судьбы.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="💎 Купить Матрицу — 890 ₽",
                        callback_data="buy_matrix"
                    )],
                    [InlineKeyboardButton(text="← Назад", callback_data="main_menu")],
                ]
            )
        )
        return

    # Ветка B: матрица есть, лимит исчерпан, нет безлимита → пейволл таро
    if user.compatibility_used and not _has_unlimited_compat(user):
        await callback.message.edit_text(
            "❤️ Ты уже использовал бесплатный расклад совместимости.\n\n"
            "Безлимитная совместимость доступна с Таро-подпиской.\n"
            "Проверяй совместимость с друзьями, коллегами,\n"
            "новыми знакомыми — без ограничений.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="✨ Подключить Таро — 390 ₽/мес",
                        callback_data="buy_tarot_subscription"
                    )],
                    [InlineKeyboardButton(text="← В меню", callback_data="main_menu")],
                ]
            )
        )
        return

    # Ветка C/D: доступно (первый расклад ИЛИ безлимит)
    await callback.message.edit_text(explanation_text())
    await state.set_state(CompatibilityStates.waiting_partner_date)


@router.message(CompatibilityStates.waiting_partner_date)
async def process_partner_date(message: Message, state: FSMContext) -> None:
    date_str = message.text.strip()

    if not validate_date(date_str):
        await message.answer(invalid_format_text())
        return

    await state.clear()

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(message.from_user.id)

    if user is None or not user.birth_date:
        await message.answer("Пользователь не найден. Начни с /start")
        return

    # Анимация загрузки
    msg = await message.answer(loading_steps[0])
    for step in loading_steps[1:]:
        await asyncio.sleep(1.5)
        await msg.edit_text(step)

    task = generate_compatibility_report.delay(str(user.id), date_str)

    result = None
    waited = 0
    while waited < MAX_POLL_SECONDS:
        ready = AsyncResult(task.id).ready()
        if ready:
            result = AsyncResult(task.id).result
            break
        await asyncio.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL

    if result is None:
        await msg.edit_text("Что-то пошло не так. Попробуй ещё раз через минуту.")
        return

    analysis = result.get("analysis", {})
    token = result.get("token", "")

    text = mini_compatibility_text(
        archetype_1=analysis.get("archetype_first", "..."),
        archetype_2=analysis.get("archetype_second", "..."),
        block_1=analysis.get("archetype_first", "..."),
        block_2=analysis.get("archetype_second", "..."),
        block_3=analysis.get("emotional_compatibility", "..."),
    )

    partner_arcana_name = result.get(
        "archetype_second_name",
        analysis.get("archetype_second", "...")
    )
    partner_arcana_number = result.get("archetype_second_number", 0)

    sender_name = user.first_name or user.username or "Пользователь"
    share_text = (
        f"{sender_name} проверил нашу совместимость "
        f"в NURA ✦\n\n"
        f"Твой аркан в этой паре — "
        f"{partner_arcana_name} ({partner_arcana_number})\n\n"
        f"Хочешь увидеть полный разбор?\n"
        f"👉 t.me/ai_nura_bot"
    )
    share_url = (
        f"https://t.me/share/url"
        f"?url=t.me/ai_nura_bot"
        f"&text={quote(share_text)}"
    )

    keyboard_rows = [
        [InlineKeyboardButton(text="📤 Отправить другу", url=share_url)],
    ]

    # У пользователей с активной подпиской не показываем цену
    if _has_unlimited_compat(user):
        keyboard_rows.append(
            [InlineKeyboardButton(text="🔄 Новый расклад", callback_data="compatibility")]
        )
    else:
        keyboard_rows.append(
            [InlineKeyboardButton(text="✨ Подключить Таро", callback_data="buy_tarot_subscription")]
        )

    keyboard_rows.append(
        [InlineKeyboardButton(text="← В меню", callback_data="main_menu")]
    )

    # Отметить лимит если нет безлимита
    if not _has_unlimited_compat(user):
        await user_repo.mark_compatibility_used(user.id)

    if settings.test_mode:
        report_url = f"{settings.report_base_url}/report/{token}"
        keyboard_rows.insert(
            0,
            [InlineKeyboardButton(
                text="👁 Открыть полный разбор (тест)",
                url=report_url
            )],
        )

    await msg.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
    )
