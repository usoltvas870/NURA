from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.main_menu import main_menu_keyboard
from bot.texts.start import help_text, welcome_back_text
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository

router = Router()


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(message.from_user.id)

    if not user or not user.birth_date:
        await message.answer("Напиши /start, чтобы начать знакомство с NURA ✶")
        return

    name = user.first_name or user.username or "пользователь"
    archetype = user.main_archetype or "не определён"
    has_tarot = bool(user.tarot_subscription) if user else False
    await message.answer(
        welcome_back_text(name=name, archetype=archetype),
        reply_markup=main_menu_keyboard(
            has_matrix=bool(user.birth_date),
            has_tarot=has_tarot,
            subscription_status=user.subscription_status,
        ),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(help_text())


@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(callback.from_user.id)

    if not user or not user.birth_date:
        await callback.message.answer("Напиши /start, чтобы начать знакомство с NURA ✶")
        return

    name = user.first_name or user.username or "пользователь"
    archetype = user.main_archetype or "не определён"
    has_tarot = bool(user.tarot_subscription) if user else False
    await callback.message.edit_text(
        welcome_back_text(name=name, archetype=archetype),
        reply_markup=main_menu_keyboard(
            has_matrix=bool(user.birth_date),
            has_tarot=has_tarot,
            subscription_status=user.subscription_status,
        ),
    )


@router.callback_query(F.data == "sample_report")
async def callback_sample_report(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "📄 Пример отчёта — скоро"
    )


@router.message()
async def unknown_message(message: Message) -> None:
    from bot.texts.start import unknown_message_text
    await message.answer(unknown_message_text())
