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
            user = await repo.get_by_telegram_id(telegram_user.id)
            if user is None:
                user = await repo.create(
                    telegram_id=telegram_user.id,
                    username=telegram_user.username,
                    first_name=telegram_user.first_name,
                )
                first_name = telegram_user.first_name or telegram_user.username or "друг"
                text = (
                    f"Приятно познакомиться, {first_name}! ✶\n\n"
                    "NURA — это пространство, где ты можешь "
                    "узнать себя через свою Матрицу Судьбы.\n\n"
                    "Начни с расчёта — это займёт всего минуту."
                )
                from bot.keyboards.main_menu import main_menu_keyboard
                from aiogram.types import Message, CallbackQuery

                if isinstance(event, Message):
                    await event.answer(text, reply_markup=main_menu_keyboard())
                elif isinstance(event, CallbackQuery):
                    await event.message.answer(text, reply_markup=main_menu_keyboard())
            data["user"] = user

        return await handler(event, data)
