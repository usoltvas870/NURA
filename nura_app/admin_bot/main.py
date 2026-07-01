import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

from admin_bot.config import AdminBotConfig
from admin_bot.handlers import (
    cache_router,
    chat_router,
    help_router,
    restart_router,
    status_router,
)
from admin_bot.middleware import AdminOnlyMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    bot_config = AdminBotConfig()

    if not bot_config.token or bot_config.token.startswith("change-me"):
        logger.error("ADMIN_BOT_TOKEN is not configured. Admin bot will not start.")
        while True:
            await asyncio.sleep(3600)

    if not bot_config.admin_telegram_id:
        logger.error("ADMIN_TELEGRAM_ID is not configured. Admin bot will not start.")
        while True:
            await asyncio.sleep(3600)

    bot = Bot(
        token=bot_config.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    admin_mw = AdminOnlyMiddleware(bot_config)
    dp.message.middleware(admin_mw)
    dp.callback_query.middleware(admin_mw)

    dp.include_router(help_router)
    dp.include_router(status_router)
    dp.include_router(restart_router)
    dp.include_router(cache_router)
    dp.include_router(chat_router)

    commands = [
        BotCommand(command="status", description="Состояние сервера"),
        BotCommand(command="restart", description="Перезапустить сервис"),
        BotCommand(command="cache", description="Очистить кэш"),
        BotCommand(command="help", description="Справка"),
    ]
    await bot.set_my_commands(commands, BotCommandScopeDefault())
    logger.info("Admin bot started, admin_id=%s", bot_config.admin_telegram_id)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
