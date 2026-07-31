import asyncio
import logging
import socket
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand, BotCommandScopeDefault, MenuButtonCommands
from redis.asyncio import Redis

from bot.handlers.chat import router as chat_router
from bot.handlers.broadcast import router as broadcast_router
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
    SandboxTelegramInboundMiddleware,
    ThrottlingMiddleware,
    UserRegistrationMiddleware,
)
from bot.middlewares.registration import LegacyTelegramAuthRetirementMiddleware
from core.config import settings
from core.services.prompt_governance import validate_active_prompt_bundles
from core.services.external_sandbox import (
    require_telegram_identity_evidence,
    validate_sandbox_database_head,
    validate_sandbox_startup,
)
from core.services.telegram_sandbox import SandboxGuardedBot
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
            await validate_sandbox_database_head(conn, settings)
    finally:
        await engine.dispose()


async def _on_startup(**_: object) -> None:
    validate_sandbox_startup(settings)
    validate_active_prompt_bundles()
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

    dp.message.middleware(SandboxTelegramInboundMiddleware())
    dp.callback_query.middleware(SandboxTelegramInboundMiddleware())
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
    dp.include_router(broadcast_router)
    dp.include_router(tarot_router)
    dp.include_router(insights_router)
    dp.include_router(fallback_router)


def create_runtime() -> tuple[Bot, Dispatcher]:
    """Construct the production Bot and Dispatcher without performing Telegram I/O."""
    validate_sandbox_startup(settings)
    if settings.is_sandbox and settings.telegram_polling_enabled:
        require_telegram_identity_evidence(settings)
    token = settings.telegram_bot_token
    if not token or not token.strip() or token.startswith("change-me"):
        raise RuntimeError("telegram_bot_token_not_configured")

    bot = SandboxGuardedBot(
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

    if not settings.telegram_polling_enabled:
        logger.info("Bot standby ready without Telegram I/O")
        await asyncio.Event().wait()

    commands = [
        BotCommand(command="start", description="🚀 Главное меню"),
        BotCommand(command="profile", description="👤 Мой профиль"),
        BotCommand(command="settings", description="⚙️ Настройки сообщений"),
        BotCommand(command="delete_account", description="🗑 Удалить аккаунт"),
        BotCommand(command="help", description="❓ Помощь"),
    ]
    await bot.set_my_commands(commands, BotCommandScopeDefault())
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Bot commands registered")

    lease = Redis.from_url(settings.redis_url)
    lease_prefix = settings.sandbox_redis_key_prefix or "nura_tg:"
    lease_key = f"{lease_prefix}polling_lease"
    polling_marker_key = f"{lease_prefix}polling_active"
    # Docker exposes the container instance identity as hostname; this lets the
    # controller prove that Redis lease ownership matches the running bot.
    lease_value = socket.gethostname()
    if not await lease.set(lease_key, lease_value, nx=True, ex=90):
        await lease.aclose()
        raise RuntimeError("telegram_polling_lease_unavailable")

    async def renew_lease() -> None:
        while True:
            await asyncio.sleep(30)
            renewed = await lease.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "redis.call('expire', KEYS[1], ARGV[2]); "
                "if redis.call('get', KEYS[2]) == ARGV[1] then "
                "redis.call('expire', KEYS[2], ARGV[2]) end; return 1 end return 0",
                2,
                lease_key,
                polling_marker_key,
                lease_value,
                90,
            )
            if not renewed:
                raise RuntimeError("telegram_polling_lease_lost")

    renewal = asyncio.create_task(renew_lease())
    polling: asyncio.Task[None] | None = None

    async def mark_polling_started(*_args: object) -> None:
        await lease.set(polling_marker_key, lease_value, ex=90)

    dp.startup.register(mark_polling_started)
    logger.info("Bot polling started")
    try:
        polling = asyncio.create_task(dp.start_polling(bot))
        await asyncio.sleep(5)
        if polling.done():
            polling.result()
        done, _ = await asyncio.wait(
            {polling, renewal}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            task.result()
    finally:
        renewal.cancel()
        if polling is not None:
            polling.cancel()
        await lease.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) end return 0",
            1,
            lease_key,
            lease_value,
        )
        await lease.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) end return 0",
            1,
            polling_marker_key,
            lease_value,
        )
        await lease.aclose()


if __name__ == "__main__":
    asyncio.run(main())
