from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="admin_help")

HELP_TEXT = (
    "🛠 <b>Команды Admin Bot</b>\n\n"
    "/status — показать состояние всех сервисов\n"
    "/restart [svc] — перезапустить сервис (api|bot|celery-worker|celery-beat)\n"
    "/cache clear — очистить Redis кэш\n"
    "/help — этот список\n\n"
    "💬 Можно просто писать вопросы, например:\n"
    "• «что с сервером?» — бот покажет статус\n"
    "• «перезапусти api» — бот перезапустит\n"
    "• «очисти кэш» — бот очистит Redis\n"
    "• «почему ошибка?» — бот проанализирует логи"
)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)
