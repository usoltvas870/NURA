import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from celery.result import AsyncResult

from bot.handlers.validators import validate_date
from bot.keyboards.main_menu import paywall_keyboard
from bot.states.matrix_state import MatrixState
from bot.texts.matrix import (
    ask_birth_date_text,
    impossible_date_text,
    invalid_format_text,
    loading_steps,
    mini_analysis_text,
)
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository
from core.tasks import generate_mini_report

logger = logging.getLogger(__name__)

router = Router()

POLL_INTERVAL = 2
MAX_POLL_SECONDS = 90


@router.callback_query(F.data == "calculate_matrix")
async def ask_birth_date(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(MatrixState.waiting_for_birth_date)
    await callback.message.edit_text(ask_birth_date_text())


@router.message(MatrixState.waiting_for_birth_date)
async def process_birth_date(message: Message, state: FSMContext) -> None:
    date_str = message.text.strip()

    if not validate_date(date_str):
        await message.answer(invalid_format_text())
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

    username = message.from_user.username or message.from_user.first_name or "user"
    task = generate_mini_report.delay(str(user.id), date_str, username)

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
    archetype = result.get("archetype", {})

    text = mini_analysis_text(
        archetype_name=archetype.get("name", "..."),
        archetype_number=archetype.get("number", 0),
        main_archetype=analysis.get("main_archetype", "..."),
        core_strength=analysis.get("core_strength", "..."),
        emotional_conflict=analysis.get("emotional_conflict", "..."),
        relationship_pattern=analysis.get("relationship_pattern", "..."),
        financial_block=analysis.get("financial_block", "..."),
    )

    await msg.edit_text(text, reply_markup=paywall_keyboard(token))
