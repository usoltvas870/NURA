import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from celery.result import AsyncResult

from bot.handlers.validators import validate_date
from bot.keyboards.main_menu import compatibility_paywall_keyboard
from bot.states.compatibility_state import CompatibilityStates
from bot.texts.compatibility import (
    ask_second_date_text,
    dates_match_error_text,
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


@router.callback_query(F.data == "compatibility")
async def ask_compatibility(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(CompatibilityStates.waiting_first_date)
    await callback.message.edit_text(explanation_text())


@router.message(CompatibilityStates.waiting_first_date)
async def process_first_date(message: Message, state: FSMContext) -> None:
    date_str = message.text.strip()

    if not validate_date(date_str):
        await message.answer(invalid_format_text())
        return

    await state.update_data(first_date=date_str)
    await state.set_state(CompatibilityStates.waiting_second_date)
    await message.answer(ask_second_date_text())


@router.message(CompatibilityStates.waiting_second_date)
async def process_second_date(message: Message, state: FSMContext) -> None:
    date_str = message.text.strip()

    if not validate_date(date_str):
        await message.answer(invalid_format_text())
        return

    data = await state.get_data()
    first_date = data["first_date"]

    if date_str == first_date:
        await message.answer(dates_match_error_text())
        return

    await state.clear()

    steps = loading_steps()
    msg = await message.answer(steps[0])
    for step in steps[1:]:
        await asyncio.sleep(1)
        await msg.edit_text(step)

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(message.from_user.id)
    if user is None:
        await msg.edit_text(
            "Пользователь не найден. Начни с /start",
        )
        return

    task = generate_compatibility_report.delay(
        str(user.id), first_date, date_str
    )

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
        await msg.edit_text(
            "Что-то пошло не так. Попробуй ещё раз через минуту.",
        )
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

    if settings.test_mode:
        report_url = f"{settings.report_base_url}/report/{token}"
        await msg.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="👁 Открыть полный разбор (тестовый режим — оплата не требуется)", url=report_url)],
                    [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
                ]
            ),
        )
    else:
        await msg.edit_text(text, reply_markup=compatibility_paywall_keyboard(token))
