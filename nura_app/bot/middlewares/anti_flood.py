import time

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery


class AntiFloodMiddleware(BaseMiddleware):
    def __init__(self, max_messages: int = 10, window: float = 60.0, ban_duration: float = 30.0):
        self.max_messages = max_messages
        self.window = window
        self.ban_duration = ban_duration
        self.history: dict[int, list[float]] = {}
        self.bans: dict[int, float] = {}

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

            ban_until = self.bans.get(user_id, 0)
            if now < ban_until:
                remaining = int(ban_until - now)
                if isinstance(event, Message):
                    await event.answer(f"Ты слишком быстр. Давай сделаем паузу на {remaining} сек ☕")
                elif isinstance(event, CallbackQuery):
                    await event.answer(f"Ты слишком быстр. Давай сделаем паузу на {remaining} сек ☕", show_alert=True)
                return

            timestamps = self.history.get(user_id, [])
            timestamps = [t for t in timestamps if now - t < self.window]
            timestamps.append(now)
            self.history[user_id] = timestamps

            if len(timestamps) > self.max_messages:
                self.bans[user_id] = now + self.ban_duration
                msg = "Ты слишком быстр. Давай сделаем паузу на полминуты ☕"
                if isinstance(event, Message):
                    await event.answer(msg)
                elif isinstance(event, CallbackQuery):
                    await event.answer(msg, show_alert=True)
                return

        return await handler(event, data)
