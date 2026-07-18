import re

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, User as TelegramUser

from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository


_START_COMMAND_PATTERN = re.compile(r"^/start(?:@[A-Za-z0-9_]+)?$", re.IGNORECASE)
_RETIRED_LEGACY_TG_AUTH_MESSAGE = (
    "Эта ссылка для входа устарела. Откройте NURA и войдите через доступный "
    "способ авторизации. Telegram можно подключить позже в профиле."
)


def is_retired_legacy_tg_auth_start(event: TelegramObject) -> bool:
    if not isinstance(event, Message) or not event.text:
        return False
    parts = event.text.split(maxsplit=1)
    if len(parts) != 2:
        return False
    command, payload = parts
    return bool(_START_COMMAND_PATTERN.fullmatch(command) and payload.startswith("tgauth_"))


class LegacyTelegramAuthRetirementMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler,
        event: TelegramObject,
        data: dict,
    ):
        if is_retired_legacy_tg_auth_start(event):
            await event.answer(_RETIRED_LEGACY_TG_AUTH_MESSAGE)
            return None
        return await handler(event, data)


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
