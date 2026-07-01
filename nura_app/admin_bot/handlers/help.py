from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="admin_help")

HELP_TEXT = (
    "🛠 <b>Команды Admin Bot</b>\n\n"
    "/status — сводка: контейнеры, health, последние ошибки\n"
    "/errors [N] — последние N ошибок из логов с AI-анализом\n"
    "/logs [name] — логи контейнера за последний час\n"
    "/restart [svc] — перезапустить контейнер (api|bot|celery-worker|celery-beat)\n"
    "/cache clear — очистить Redis кэш\n"
    "/deploy — git pull + docker compose up -d --build\n"
    "/db query SQL — выполнить read-only SQL запрос\n"
    "/help — этот список"
)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)
