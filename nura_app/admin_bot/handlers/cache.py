import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from admin_bot.services.docker_client import DockerClient

logger = logging.getLogger(__name__)
router = Router(name="admin_cache")


@router.message(Command("cache"))
async def cmd_cache(message: Message) -> None:
    args = message.text.strip().split(maxsplit=1)
    if len(args) < 2 or args[1].strip().lower() != "clear":
        await message.answer("❓ Использование: <code>/cache clear</code> — очистить Redis кэш")
        return

    await message.answer("🧹 Очищаю Redis кэш...")

    try:
        dc = DockerClient()
        result = await dc.clear_redis_cache()
        if result:
            await message.answer("✅ Redis кэш успешно очищен.")
        else:
            await message.answer("❌ Не удалось очистить Redis кэш.")
    except Exception as e:
        logger.exception("Cache clear failed")
        await message.answer(f"❌ Ошибка: {e}")
