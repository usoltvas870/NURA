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
from bot.handlers.insights import router as insights_router
from bot.middlewares import (
    AntiFloodMiddleware,
    ThrottlingMiddleware,
    UserRegistrationMiddleware,
)
from bot.middlewares.registration import LegacyTelegramAuthRetirementMiddleware
from core.config import settings
from core.database import (
    create_engine,
    dispose_async_database_state,
    get_redis,
)
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def _verify_database_ready() -> None:
    """Verify the runtime database dependency before polling begins."""
    engine = create_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


async def _on_startup(**_: object) -> None:
    await _verify_database_ready()
    await get_redis().ping()
    logger.info("Bot runtime dependencies ready")


async def _on_shutdown(**_: object) -> None:
    await get_redis().aclose()
    await dispose_async_database_state()
    logger.info("Bot runtime shutdown complete")


def configure_dispatcher(dp: Dispatcher) -> None:
    dp.errors.register(global_error_handler)
    dp.startup.register(_on_startup)
    dp.shutdown.register(_on_shutdown)

    dp.message.middleware(LegacyTelegramAuthRetirementMiddleware())
    dp.message.middleware(UserRegistrationMiddleware())
    dp.callback_query.middleware(UserRegistrationMiddleware())
    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())
    dp.message.middleware(AntiFloodMiddleware())
    dp.callback_query.middleware(AntiFloodMiddleware())

    dp.include_router(start_router)
    dp.include_router(onboarding_router)
    dp.include_router(compatibility_router)
    dp.include_router(chat_router)
    dp.include_router(payment_router)
    dp.include_router(profile_router)
    dp.include_router(tarot_router)
    dp.include_router(insights_router)
    dp.include_router(fallback_router)


def create_runtime() -> tuple[Bot, Dispatcher]:
    """Construct the production Bot and Dispatcher without performing Telegram I/O."""
    token = settings.telegram_bot_token
    if not token or not token.strip() or token.startswith("change-me"):
        raise RuntimeError("telegram_bot_token_not_configured")

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)
    configure_dispatcher(dp)
    return bot, dp


async def main() -> None:
    try:
        bot, dp = create_runtime()
    except RuntimeError as error:
        logger.error("Telegram runtime cannot start: %s", error)
        raise SystemExit(1) from None

    max_db_retries = 10
    for attempt in range(max_db_retries):
        try:
            await _verify_database_ready()
            logger.info("Database ready")
            break
        except Exception as e:
            logger.warning(
                "DB init attempt %d/%d failed: %s",
                attempt + 1, max_db_retries, e,
            )
            if attempt < max_db_retries - 1:
                await asyncio.sleep(3)
            else:
                raise

    commands = [
        BotCommand(command="start", description="🚀 Главное меню"),
        BotCommand(command="profile", description="👤 Мой профиль"),
        BotCommand(command="delete_account", description="🗑 Удалить аккаунт"),
        BotCommand(command="help", description="❓ Помощь"),
    ]
    await bot.set_my_commands(commands, BotCommandScopeDefault())
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Bot commands registered")
    logger.info("Bot polling started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
