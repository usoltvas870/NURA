import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from admin_bot.services.docker_client import DockerClient

logger = logging.getLogger(__name__)
router = Router(name="admin_deploy")


@router.message(Command("deploy"))
async def cmd_deploy(message: Message) -> None:
    await message.answer("🚀 Запускаю деплой: git pull + docker compose up -d --build...\nЭто может занять несколько минут.")

    try:
        dc = DockerClient()
        result = await dc.run_deploy()
        await message.answer(f"✅ Деплой завершён.\n<pre>{result[:2000]}</pre>")
    except Exception as e:
        logger.exception("Deploy command failed")
        await message.answer(f"❌ Ошибка деплоя: {e}")


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


@router.message(Command("db"))
async def cmd_db(message: Message) -> None:
    args = message.text.strip().split(maxsplit=2)
    if len(args) < 3 or args[1].strip().lower() != "query":
        await message.answer("❓ Использование: <code>/db query SELECT count(*) FROM users</code>")
        return

    sql = args[2].strip()
    upper_sql = sql.upper().strip()

    forbidden = {"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE"}
    first_word = upper_sql.split()[0] if upper_sql.split() else ""
    if first_word in forbidden or "INTO" in upper_sql or "EXEC" in upper_sql:
        await message.answer("⛔ Только SELECT-запросы разрешены.")
        return

    if not upper_sql.startswith("SELECT"):
        await message.answer("⛔ Только SELECT-запросы разрешены.")
        return

    await message.answer(f"🔍 Выполняю: <code>{sql[:200]}</code>")

    try:
        dc = DockerClient()
        result = await dc.run_db_query(sql)
        text = str(result)[:2000] if result else "(empty result)"
        await message.answer(f"<b>Результат:</b>\n<pre>{text}</pre>")
    except Exception as e:
        logger.exception("DB query failed")
        await message.answer(f"❌ Ошибка: {e}")
