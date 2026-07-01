from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="admin_help")

HELP_TEXT = (
    "🛠 <b>Команды Admin Bot</b>\n\n"
    "/status — показать состояние всех сервисов\n"
    "/restart [svc] — перезапустить сервис (api|bot|celery-worker|celery-beat)\n"
    "/cache clear — очистить Redis кэш\n"
    "/deploy — выкатить обновление из GitHub\n"
    "/help — этот список\n\n"
    "💬 Также можно просто писать вопросы — бот ответит по-русски "
    "и поможет разобраться с проблемой."
)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)
