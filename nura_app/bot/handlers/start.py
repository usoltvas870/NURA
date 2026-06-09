import logging
import uuid

import httpx
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards.main_menu import main_menu_keyboard, open_pwa_keyboard
from bot.states.onboarding_state import OnboardingStates
from bot.texts.onboarding import ask_birth_date_onboarding_text, onboarding_greeting_text
from bot.texts.start import help_text, welcome_back_text
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, command: CommandObject) -> None:
    await state.clear()

    args = command.args
    if args and args.startswith("link_"):
        token = args[5:]
        await _handle_link_token(message, token)
        return

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(message.from_user.id)

    if user and user.birth_date:
        await _show_authenticated_menu(message, user)
        return

    if user is None:
        user = await user_repo.create(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )

    await message.answer(onboarding_greeting_text(message.from_user.first_name or ""))
    await state.set_state(OnboardingStates.waiting_for_birth_date)
    await message.answer(ask_birth_date_onboarding_text())


async def _show_authenticated_menu(message: Message, user) -> None:
    name = user.first_name or user.username or "пользователь"
    archetype = user.main_archetype or "не определён"
    has_tarot = bool(user.tarot_subscription) if user else False
    await message.answer(
        welcome_back_text(name=name, archetype=archetype),
        reply_markup=main_menu_keyboard(
            has_matrix=bool(user.has_matrix),
            has_tarot=has_tarot,
            subscription_status=user.subscription_status,
        ),
    )


async def _handle_link_token(message: Message, token: str) -> None:
    telegram_id = message.from_user.id

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "http://127.0.0.1:8000/api/v1/web/check-link-token",
                params={"token": token},
                timeout=5.0,
            )

        if resp.status_code == 404:
            await message.answer(
                "❌ Ссылка недействительна или истекла.\n\n"
                "Вернись в приложение NURA и запроси новую ссылку.",
                reply_markup=open_pwa_keyboard(),
            )
            return

        if resp.status_code != 200:
            await message.answer("Что-то пошло не так. Попробуй ещё раз.")
            return

        user_id_str = resp.json()["user_id"]

        session_factory = get_async_sessionmaker()
        user_repo = UserRepository(session_factory)
        updated = await user_repo.update_telegram_id(
            uuid.UUID(user_id_str), telegram_id
        )

        if updated is None:
            await message.answer(
                "⚠️ Этот Telegram-аккаунт уже привязан к другому профилю NURA.\n\n"
                "Напиши в поддержку если считаешь это ошибкой."
            )
            return

        await message.answer(
            "✅ Аккаунты связаны!\n\n"
            "Теперь карта дня будет приходить сюда, "
            "если ты не разрешил уведомления в приложении.",
            reply_markup=open_pwa_keyboard(),
        )

    except httpx.TimeoutException:
        await message.answer("Сервер не отвечает. Попробуй через минуту.")
    except Exception:
        logger.exception("Link token error for telegram_id=%s", telegram_id)
        await message.answer("Что-то пошло не так. Попробуй ещё раз.")


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(message.from_user.id)

    if not user or not user.birth_date:
        await message.answer("Напиши /start, чтобы начать знакомство с NURA ✶")
        return

    name = user.first_name or user.username or "пользователь"
    archetype = user.main_archetype or "не определён"
    has_tarot = bool(user.tarot_subscription) if user else False
    await message.answer(
        welcome_back_text(name=name, archetype=archetype),
        reply_markup=main_menu_keyboard(
            has_matrix=bool(user.birth_date),
            has_tarot=has_tarot,
            subscription_status=user.subscription_status,
        ),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(help_text())


@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(callback.from_user.id)

    if not user or not user.birth_date:
        await callback.message.answer("Напиши /start, чтобы начать знакомство с NURA ✶")
        return

    name = user.first_name or user.username or "пользователь"
    archetype = user.main_archetype or "не определён"
    has_tarot = bool(user.tarot_subscription) if user else False
    await callback.message.edit_text(
        welcome_back_text(name=name, archetype=archetype),
        reply_markup=main_menu_keyboard(
            has_matrix=bool(user.birth_date),
            has_tarot=has_tarot,
            subscription_status=user.subscription_status,
        ),
    )


@router.callback_query(F.data == "sample_report")
async def callback_sample_report(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "📄 <b>Пример полного отчёта</b>\n\n"
        "Отчёт включает 15 разделов:\n"
        "• Главный архетип и жизненная стратегия\n"
        "• Теневые стороны и слепые пятна\n"
        "• Сценарии в отношениях\n"
        "• Денежные блоки и способы их снять\n"
        "• Жизненные циклы — периоды силы и спада\n"
        "• 7-дневные персональные рекомендации\n\n"
        "Всё это — на основе твоей даты рождения.\n\n"
        "<b>💎 Полный разбор — 890 ₽ разово, навсегда.</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="💎 Купить — 890 ₽",
                callback_data="buy_matrix"
            )],
            [InlineKeyboardButton(text="← Назад", callback_data="my_matrix")],
        ])
    )


fallback_router = Router()


@fallback_router.message()
async def unknown_message(message: Message) -> None:
    from bot.texts.start import unknown_message_text
    await message.answer(unknown_message_text())
