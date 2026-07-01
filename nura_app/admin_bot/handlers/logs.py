import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from admin_bot.services.docker_client import DockerClient

logger = logging.getLogger(__name__)
router = Router(name="admin_logs")


@router.message(Command("logs"))
async def cmd_logs(message: Message) -> None:
    args = message.text.strip().split(maxsplit=1)
    container_name = args[1] if len(args) > 1 else "all"

    await message.answer(f"📄 Читаю логи <b>{container_name}</b> за последний час...")

    try:
        dc = DockerClient()

        if container_name == "all":
            containers = await dc.list_containers()
            all_lines: list[str] = []
            for c in containers:
                if c["state"] != "running":
                    continue
                raw = await dc.get_container_logs(c["name"], since_minutes=60, lines=50)
                for line in raw:
                    all_lines.append(f"[{c['name']}] {line}")
            lines = all_lines[:100]
            source = "все контейнеры"
        else:
            lines = await dc.get_container_logs(container_name, since_minutes=60, lines=100)
            source = container_name

        if not lines:
            await message.answer(f"📭 Логов для <b>{source}</b> не найдено.")
            return

        text = f"<b>📋 Логи: {source}</b>\n\n" + "\n".join(
            f"<code>{ln[:300]}</code>" for ln in lines[:30]
        )

        if len(lines) > 30:
            text += f"\n\n... и ещё {len(lines) - 30} строк"

        await message.answer(text)
    except Exception as e:
        logger.exception("Logs command failed")
        await message.answer(f"❌ Ошибка: {e}")
