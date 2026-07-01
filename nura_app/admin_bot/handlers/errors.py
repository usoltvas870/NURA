import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from admin_bot.services.ai_advisor import AIAdvisor
from admin_bot.services.docker_client import DockerClient
from admin_bot.services.log_parser import LogParser

logger = logging.getLogger(__name__)
router = Router(name="admin_errors")


@router.message(Command("errors"))
async def cmd_errors(message: Message) -> None:
    args = message.text.strip().split(maxsplit=1)
    n = 20
    if len(args) > 1:
        try:
            n = max(1, min(100, int(args[1])))
        except ValueError:
            n = 20

    await message.answer(f"🔍 Ищу последние {n} ошибок...")

    try:
        dc = DockerClient()
        containers = await dc.list_containers()
        all_errors: list[dict] = []

        for c in containers:
            if c["state"] != "running":
                continue
            raw_lines = await dc.get_container_logs(c["name"], lines=n * 2)
            errors = LogParser.extract_errors(raw_lines, max_per_container=n // 2)
            for err in errors:
                all_errors.append({"container": c["name"], **err})

        all_errors = all_errors[:n]

        if not all_errors:
            await message.answer("✅ Ошибки не найдены.")
            return

        text_parts = [f"<b>⚠️ Найдено ошибок: {len(all_errors)}</b>\n"]
        for err in all_errors:
            line = err["line"][:200]
            text_parts.append(f"🔴 <b>{err['container']}</b>: <code>{line}</code>")

        # AI analysis of first 5 errors
        ai = AIAdvisor()
        analysis = await ai.analyze_errors(all_errors[:5])
        if analysis:
            text_parts.append(f"\n<b>🤖 AI-анализ:</b>\n{analysis}")

        await message.answer("\n".join(text_parts))
    except Exception as e:
        logger.exception("Errors command failed")
        await message.answer(f"❌ Ошибка: {e}")
