import time

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 1.0):
        self.rate_limit = rate_limit
        self.last_time: dict[int, float] = {}

    async def __call__(
        self,
        handler,
        event: Message | CallbackQuery,
        data: dict,
    ):
        telegram_user = data.get("event_from_user")
        if telegram_user:
            user_id = telegram_user.id
            now = time.time()
            last = self.last_time.get(user_id, 0)
            if now - last < self.rate_limit:
                if isinstance(event, Message):
                    await event.answer("Слишком быстро — давай по одной команде за раз ☕")
                elif isinstance(event, CallbackQuery):
                    await event.answer("Слишком быстро — давай по одной команде за раз ☕", show_alert=False)
                return
            self.last_time[user_id] = now

        return await handler(event, data)
