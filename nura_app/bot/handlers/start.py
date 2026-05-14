from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards.main_menu import main_menu_keyboard

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    text = (
        "NURA — AI-проводник в Матрицу Судьбы.\n\n"
        "Я помогу тебе понять:\n"
        "• Твой главный архетип\n"
        "• Сильные стороны и таланты\n"
        "• Эмоциональные конфликты\n"
        "• Паттерны в отношениях\n"
        "• Финансовый сценарий\n\n"
        "Нажми кнопку ниже, чтобы начать."
    )
    await message.answer(text, reply_markup=main_menu_keyboard())
