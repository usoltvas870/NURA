import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import ErrorEvent

from bot.handlers.start import router as start_router
from bot.handlers.matrix import router as matrix_router
from bot.handlers.profile import router as profile_router
from bot.middlewares import UserRegistrationMiddleware, ThrottlingMiddleware, AntiFloodMiddleware
from bot.texts.system import global_error_text
from core.config import settings

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

    dp.include_router(start_router)
    dp.include_router(matrix_router)
    dp.include_router(profile_router)

    logger.info("Bot polling started")
    await dp.start_polling(bot)


async def global_error_handler(event: ErrorEvent) -> bool:
    logger.exception("Global bot error", exc_info=event.exception)
    try:
        if event.update.message:
            await event.update.message.answer(global_error_text())
        elif event.update.callback_query:
            await event.update.callback_query.message.answer(global_error_text())
    except Exception:
        pass
    return True


if __name__ == "__main__":
    asyncio.run(main())
