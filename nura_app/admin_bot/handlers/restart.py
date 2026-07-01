import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from admin_bot.services.docker_client import DockerClient

logger = logging.getLogger(__name__)
router = Router(name="admin_restart")

ALLOWED_RESTART = {"api", "bot", "celery-worker", "celery-beat"}


@router.message(Command("restart"))
async def cmd_restart(message: Message) -> None:
    args = message.text.strip().split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "❓ Укажите сервис: <code>/restart api</code>, <code>/restart bot</code>, "
            "<code>/restart celery-worker</code>, <code>/restart celery-beat</code>"
        )
        return

    service = args[1].strip().lower()
    if service not in ALLOWED_RESTART:
        await message.answer(f"❌ Неизвестный сервис: {service}")
        return

    await message.answer(f"🔄 Перезапускаю <b>{service}</b>...")

    try:
        dc = DockerClient()
        result = await dc.restart_container(service)
        if result:
            await message.answer(f"✅ Контейнер <b>{service}</b> успешно перезапущен.")
        else:
            await message.answer(f"❌ Не удалось перезапустить <b>{service}</b>.")
    except Exception as e:
        logger.exception("Restart command failed for %s", service)
        await message.answer(f"❌ Ошибка: {e}")
