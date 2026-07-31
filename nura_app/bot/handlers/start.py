import logging
import re
import uuid

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards.main_menu import main_menu_keyboard
from bot.middlewares.registration import _RETIRED_LEGACY_TG_AUTH_MESSAGE
from bot.states.onboarding_state import OnboardingStates
from bot.texts.onboarding import (
    ask_birth_date_onboarding_text,
    delete_account_cancelled_text,
    delete_account_done_text,
    delete_account_warning_text,
    onboarding_greeting_text,
    pd_consent_declined_text,
    pd_consent_text,
)
from bot.texts.start import help_text, welcome_back_text
from core.database import get_async_sessionmaker, get_redis
from core.config import settings
from core.services.account_deletion import AccountDeletionService
from core.repositories.user import UserRepository
from core.services.attribution import AttributionService
from core.services.auth import TelegramLinkConfirmationService
from core.services.broadcast import BroadcastCampaignService

logger = logging.getLogger(__name__)

router = Router()

_LINK_TOKEN_PATTERN = re.compile(r"[0-9a-f]{32}")
_SIGNED_BIGINT_MAX = 2**63 - 1


def _pd_consent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Согласен", callback_data="pd_consent_yes"),
        InlineKeyboardButton(text="❌ Не согласен", callback_data="pd_consent_no"),
    ]])


def _delete_account_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да, удалить всё", callback_data="delete_account_confirm"),
        InlineKeyboardButton(text="Отмена", callback_data="delete_account_cancel"),
    ]])


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, command: CommandObject) -> None:
    args = command.args

    if args and args.startswith("tgauth_"):
        await message.answer(_RETIRED_LEGACY_TG_AUTH_MESSAGE)
        return

    await state.clear()

    if args and args.startswith("link_"):
        token = args[5:]
        await _handle_link_token(message, token)
        return

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    start_result = await AttributionService(
        session_factory, user_repository=user_repo
    ).process_telegram_start(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        start_parameter=args,
    )

    if args and args.startswith("ref_") and settings.enable_referral_promotion:
        ref_part = args[4:]
        if ref_part.isdigit():
            referrer_telegram_id = int(ref_part)
            if referrer_telegram_id != message.from_user.id:
                await _handle_referral(message, referrer_telegram_id)

    user = start_result.user
    try:
        await BroadcastCampaignService(session_factory).release_start_suppression(user.id)
    except Exception:
        logger.warning(
            "Could not release automatic Telegram suppression on /start",
            exc_info=True,
        )

    if user and user.birth_date:
        await _show_authenticated_menu(message, user)
        return

    if not user.pd_consent_at:
        await message.answer(pd_consent_text(), reply_markup=_pd_consent_keyboard())
        await state.set_state(OnboardingStates.waiting_for_pd_consent)
        return

    await message.answer(onboarding_greeting_text(message.from_user.first_name or ""))
    await state.set_state(OnboardingStates.waiting_for_birth_date)
    await message.answer(ask_birth_date_onboarding_text())


@router.callback_query(F.data == "pd_consent_yes")
async def callback_pd_consent_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(callback.from_user.id)
    if user:
        await user_repo.set_pd_consent(user.id)
    await state.set_state(OnboardingStates.waiting_for_birth_date)
    await callback.message.answer(onboarding_greeting_text(callback.from_user.first_name or ""))
    await callback.message.answer(ask_birth_date_onboarding_text())


@router.callback_query(F.data == "pd_consent_no")
async def callback_pd_consent_no(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.answer(pd_consent_declined_text())


@router.message(Command("delete_account"))
async def cmd_delete_account(message: Message) -> None:
    await message.answer(delete_account_warning_text(), reply_markup=_delete_account_keyboard())


@router.callback_query(F.data == "delete_account_confirm")
async def callback_delete_account_confirm(callback: CallbackQuery) -> None:
    await callback.answer()
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(callback.from_user.id)
    if user:
        await AccountDeletionService(session_factory, get_redis()).delete(user.id)
    await callback.message.answer(delete_account_done_text())


@router.callback_query(F.data == "delete_account_cancel")
async def callback_delete_account_cancel(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(delete_account_cancelled_text())


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
    from_user = message.from_user
    telegram_id = getattr(from_user, "id", None)
    if (
        not _LINK_TOKEN_PATTERN.fullmatch(token)
        or type(telegram_id) is not int
        or not 0 < telegram_id <= _SIGNED_BIGINT_MAX
    ):
        logger.info("telegram_link_token_invalid")
        await message.answer(
            "Ссылка недействительна или истекла.\n\n"
            "Вернитесь в профиль NURA и создайте новую ссылку."
        )
        return

    try:
        user_id = await get_redis().execute_command("GETDEL", f"link_token:{token}")
    except Exception:
        logger.warning("telegram_link_token_consume_failure")
        await message.answer(
            "Не удалось начать привязку. Попробуйте ещё раз немного позже."
        )
        return

    if not user_id:
        logger.info("telegram_link_token_invalid")
        await message.answer(
            "Ссылка недействительна или истекла.\n\n"
            "Вернитесь в профиль NURA и создайте новую ссылку."
        )
        return

    try:
        if isinstance(user_id, bytes):
            user_id = user_id.decode("utf-8")
        web_user_id = uuid.UUID(user_id)
    except (TypeError, ValueError, UnicodeDecodeError):
        logger.info("telegram_link_token_invalid")
        await message.answer(
            "Ссылка недействительна или истекла.\n\n"
            "Вернитесь в профиль NURA и создайте новую ссылку."
        )
        return

    try:
        code = await TelegramLinkConfirmationService().create_pending(
            web_user_id,
            telegram_id,
        )
    except Exception:
        logger.warning("telegram_link_pending_failure")
        await message.answer(
            "Привязка не завершена. Вернитесь в профиль NURA и создайте новую ссылку."
        )
        return

    logger.info("telegram_link_token_consumed")
    await message.answer(
        "Код подтверждения: <code>%s</code>\n\n"
        "Вернитесь в профиль NURA и введите его там. Код действует 10 минут. "
        "Никому не сообщайте этот код: открытие ссылки само по себе не завершает привязку."
        % code
    )


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
            has_matrix=bool(user.has_matrix),
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
            has_matrix=bool(user.has_matrix),
            has_tarot=has_tarot,
            subscription_status=user.subscription_status,
        ),
    )


@router.callback_query(F.data == "sample_report")
async def callback_sample_report(callback: CallbackQuery) -> None:
    await callback.answer()
    payment_copy = (
        "<b>💎 Полный разбор — 890 ₽ разово, навсегда.</b>"
        if settings.payment_operations_enabled
        else "Оплата пока недоступна — полный запуск готовится."
    )
    rows = []
    if settings.payment_operations_enabled:
        rows.append([
            InlineKeyboardButton(
                text="💎 Купить — 890 ₽",
                callback_data="buy_matrix",
            )
        ])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="my_matrix")])
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
        f"{payment_copy}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def _handle_referral(message: Message, referrer_telegram_id: int) -> None:
    try:
        from core.repositories.referral import ReferralRepository

        session_factory = get_async_sessionmaker()
        user_repo = UserRepository(session_factory)
        ref_repo = ReferralRepository(session_factory)

        current_user = await user_repo.get_by_telegram_id(message.from_user.id)
        referrer = await user_repo.get_by_telegram_id(referrer_telegram_id)

        if current_user and referrer:
            set_ok = await user_repo.set_referred_by(current_user.id, referrer_telegram_id)
            if set_ok:
                await ref_repo.create_reward(
                    referrer_id=referrer.id,
                    referred_id=current_user.id,
                    event="registration",
                )
                try:
                    await message.bot.send_message(
                        referrer_telegram_id,
                        "👥 По твоей ссылке зарегистрировался новый пользователь!\n\n"
                        "Когда он купит матрицу — ты получишь бонус.",
                    )
                except Exception:
                    pass

    except Exception:
        logger.exception("Referral handling error")


fallback_router = Router()


@fallback_router.message()
async def unknown_message(message: Message) -> None:
    from bot.texts.start import unknown_message_text
    await message.answer(unknown_message_text())
