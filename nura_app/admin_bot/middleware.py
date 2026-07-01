import logging

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

from admin_bot.config import AdminBotConfig

logger = logging.getLogger(__name__)


class AdminOnlyMiddleware(BaseMiddleware):
    def __init__(self, config: AdminBotConfig) -> None:
        self.admin_id = config.admin_telegram_id
        super().__init__()

    async def __call__(self, handler, event: Message | CallbackQuery, data: dict) -> None:
        user_id = event.from_user.id if event.from_user else None
        if user_id and user_id == self.admin_id:
            return await handler(event, data)
        logger.warning("Access denied for telegram_id=%s", user_id)
        if isinstance(event, Message):
            await event.answer("⛔ Доступ запрещён.")
