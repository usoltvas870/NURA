import logging

from aiogram.types import ErrorEvent

from bot.texts.system import global_error_text

logger = logging.getLogger(__name__)


async def global_error_handler(event: ErrorEvent) -> bool:
    logger.error(
        "telegram_update_failed category=unhandled_exception exception_type=%s",
        type(event.exception).__name__,
    )
    try:
        if event.update.message:
            await event.update.message.answer(global_error_text())
        elif event.update.callback_query:
            await event.update.callback_query.message.answer(global_error_text())
    except Exception:
        pass
    return True
