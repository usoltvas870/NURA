import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.handlers.validators import validate_date
from bot.keyboards.main_menu import main_menu_keyboard
from bot.states.onboarding_state import OnboardingStates
from bot.texts.onboarding import (
    ask_birth_date_onboarding_text,
    invalid_format_onboarding_text,
    my_matrix_text,
    onboarding_done_text,
    onboarding_greeting_text,
    onboarding_loading_text,
)
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository
from core.services.matrix import MatrixService

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, user=None) -> None:
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    db_user = user or await user_repo.get_by_telegram_id(message.from_user.id)

    if db_user and db_user.birth_date:
        await _show_authenticated_menu(message, db_user)
        return

    first_name = (
        message.from_user.first_name
        or message.from_user.username
        or "друг"
    )
    await state.set_state(OnboardingStates.waiting_for_birth_date)
    await message.answer(onboarding_greeting_text(first_name))
    await asyncio.sleep(0.3)
    await message.answer(ask_birth_date_onboarding_text())


@router.message(OnboardingStates.waiting_for_birth_date)
async def process_onboarding_birth_date(
    message: Message, state: FSMContext, user=None
) -> None:
    date_str = message.text.strip()

    if not validate_date(date_str):
        await message.answer(invalid_format_onboarding_text())
        return

    await state.clear()

    loading_msg = await message.answer(onboarding_loading_text())

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    db_user = user or await user_repo.get_by_telegram_id(message.from_user.id)

    if db_user is None:
        db_user = await user_repo.create(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )

    matrix = MatrixService.calculate(date_str)
    archetype_name = MatrixService.get_archetype_name(matrix.center)
    archetype_number = matrix.center

    await user_repo.update_birth_date(db_user.id, date_str)
    await user_repo.update_archetype(db_user.id, archetype_name, archetype_number)

    await asyncio.sleep(0.5)
    await loading_msg.edit_text(
        onboarding_done_text(archetype_name, archetype_number),
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(F.data == "my_matrix")
async def show_my_matrix(callback: CallbackQuery) -> None:
    await callback.answer()
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(callback.from_user.id)

    if not user or not user.birth_date:
        await callback.message.edit_text(
            "У тебя ещё нет рассчитанной матрицы.\n"
            "Напиши /start чтобы начать ✶"
        )
        return

    matrix = MatrixService.calculate(user.birth_date)
    arcana = matrix.arcana_names

    text = my_matrix_text(
        archetype_name=user.main_archetype or arcana["center"],
        archetype_number=user.main_archetype_number or matrix.center,
        birth_date=user.birth_date,
        center_name=arcana["center"],
        top_name=arcana["top"],
        bottom_name=arcana["bottom"],
        left_name=arcana["left"],
        right_name=arcana["right"],
        talent_zone=arcana["talent_zone"],
        comfort_zone=arcana["comfort_zone"],
        portrait_zone=arcana["portrait_zone"],
    )

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📖 Полный разбор", callback_data="full_report_pay")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
            ]
        ),
    )


async def _show_authenticated_menu(message: Message, user) -> None:
    from bot.texts.start import welcome_back_text

    name = user.first_name or user.username or "пользователь"
    archetype = user.main_archetype or "не определён"
    await message.answer(
        welcome_back_text(name=name, archetype=archetype),
        reply_markup=main_menu_keyboard(),
    )
