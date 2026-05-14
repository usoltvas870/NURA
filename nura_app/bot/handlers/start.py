from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.keyboards.main_menu import main_menu_keyboard
from bot.texts.start import help_text, welcome_back_text, welcome_text
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository

router = Router()


async def _show_main_menu(message: Message, user_id: int) -> None:
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(user_id)

    if user and user.main_archetype:
        text = welcome_back_text(
            name=user.first_name or user.username or "пользователь",
            archetype=user.main_archetype,
        )
    else:
        text = welcome_text()

    await message.answer(text, reply_markup=main_menu_keyboard())


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await _show_main_menu(message, message.from_user.id)


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await _show_main_menu(message, message.from_user.id)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(help_text())


@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await _show_main_menu(callback.message, callback.from_user.id)
