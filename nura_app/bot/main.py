import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand, BotCommandScopeDefault, MenuButtonCommands

from bot.handlers.chat import router as chat_router
from bot.handlers.compatibility import router as compatibility_router
from bot.handlers.errors import global_error_handler
from bot.handlers.onboarding import router as onboarding_router
from bot.handlers.payment import router as payment_router
from bot.handlers.profile import router as profile_router
from bot.handlers.start import router as start_router, fallback_router
from bot.handlers.tarot import router as tarot_router
from bot.middlewares import UserRegistrationMiddleware, ThrottlingMiddleware, AntiFloodMiddleware
from core.config import settings
from core.database import create_engine
from core.models import Base

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main():
    token = settings.telegram_bot_token
    if not token or token.startswith("change-me"):
        logger.error(
            "TELEGRAM_BOT_TOKEN is not configured. "
            "Bot will not start. Set a real token in .env"
        )
        while True:
            await asyncio.sleep(3600)

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)

    dp.errors.register(global_error_handler)

    dp.message.middleware(UserRegistrationMiddleware())
    dp.callback_query.middleware(UserRegistrationMiddleware())
    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())
    dp.message.middleware(AntiFloodMiddleware())
    dp.callback_query.middleware(AntiFloodMiddleware())

    dp.include_router(onboarding_router)
    dp.include_router(start_router)
    dp.include_router(compatibility_router)
    dp.include_router(chat_router)
    dp.include_router(payment_router)
    dp.include_router(profile_router)
    dp.include_router(tarot_router)
    dp.include_router(fallback_router)

    max_db_retries = 10
    for attempt in range(max_db_retries):
        try:
            engine = create_engine()
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await engine.dispose()
            logger.info("Database tables ensured")
            break
        except Exception as e:
            logger.warning(
                "DB init attempt %d/%d failed: %s",
                attempt + 1, max_db_retries, e,
            )
            try:
                await engine.dispose()
            except Exception:
                pass
            if attempt < max_db_retries - 1:
                await asyncio.sleep(3)
            else:
                raise

    commands = [
        BotCommand(command="start", description="🚀 Главное меню"),
        BotCommand(command="profile", description="👤 Мой профиль"),
        BotCommand(command="help", description="❓ Помощь"),
    ]
    await bot.set_my_commands(commands, BotCommandScopeDefault())
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Bot commands registered")
    logger.info("Bot polling started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
