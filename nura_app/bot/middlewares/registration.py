from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TelegramUser

from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository


class UserRegistrationMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler,
        event: TelegramObject,
        data: dict,
    ):
        telegram_user: TelegramUser | None = data.get("event_from_user")
        if telegram_user and not telegram_user.is_bot:
            session_factory = get_async_sessionmaker()
            repo = UserRepository(session_factory)
            user = await repo.get_or_create_by_telegram_id(
                telegram_user.id,
                username=telegram_user.username,
                first_name=telegram_user.first_name,
            )
            data["user"] = user

        return await handler(event, data)
