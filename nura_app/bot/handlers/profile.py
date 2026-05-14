from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("profile"))
async def cmd_profile(message: Message):
    text = (
        "Твой профиль\n\n"
        f"Telegram ID: {message.from_user.id}\n"
        "Статус: бесплатный\n\n"
        "Купи полный отчёт, чтобы открыть все возможности."
    )
    await message.answer(text)
