import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from admin_bot.services.docker_client import DockerClient

logger = logging.getLogger(__name__)
router = Router(name="admin_status")


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    await message.answer("🔍 Проверяю состояние сервера...")

    try:
        dc = DockerClient()
        containers = await dc.list_containers()

        if not containers:
            await message.answer("❌ Не удалось получить список контейнеров (Docker socket недоступен).")
            return

        lines = ["<b>📊 Состояние контейнеров:</b>\n"]
        for c in sorted(containers, key=lambda x: x["name"]):
            name = c["name"]
            status = c["status"]
            state = c["state"]
            emoji = "✅" if state == "running" else "❌"
            health = c.get("health", "")
            health_str = f" [{health}]" if health else ""
            lines.append(f"{emoji} <b>{name}</b> — {status}{health_str}")

        lines.append("\n<b>🔗 API health:</b>")
        try:
            api_ok = await dc.check_api_health()
            lines.append("✅ API /health — ok" if api_ok else "❌ API /health — error")
        except Exception as e:
            lines.append(f"⚠️ API health check failed: {e}")

        await message.answer("\n".join(lines))
    except Exception as e:
        logger.exception("Status command failed")
        await message.answer(f"❌ Ошибка: {e}")
