import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.keyboards.main_menu import profile_keyboard, reports_keyboard, subscription_keyboard
from bot.texts.profile import (
    profile_full_text,
    profile_mini_text,
    profile_no_matrix_text,
    profile_subscriber_text,
    reports_list_text,
)
from bot.texts.subscription import subscription_offer_text
from core.database import get_async_sessionmaker
from core.repositories.report import ReportRepository
from core.repositories.user import UserRepository

logger = logging.getLogger(__name__)

router = Router()


async def _get_user_and_reports(telegram_id: int):
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    report_repo = ReportRepository(session_factory)
    user = await user_repo.get_by_telegram_id(telegram_id)
    if user is None:
        return None, []
    reports = await report_repo.get_by_user_id(user.id)
    seen: set[str] = set()
    deduped: list = []
    for r in sorted(reports, key=lambda x: x.created_at, reverse=True):
        if r.report_type not in seen:
            seen.add(r.report_type)
            deduped.append(r)
    return user, deduped


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    user, reports = await _get_user_and_reports(message.from_user.id)
    if user is None:
        await message.answer("Пользователь не найден. Начни с /start")
        return

    await _show_profile(message, user, reports)


@router.callback_query(F.data == "profile")
async def callback_profile(callback: CallbackQuery) -> None:
    await callback.answer()
    user, reports = await _get_user_and_reports(callback.from_user.id)
    if user is None:
        await callback.message.edit_text("Пользователь не найден. Начни с /start")
        return

    await _show_profile(callback.message, user, reports)


async def _show_profile(message: Message, user, reports) -> None:
    name = user.first_name or user.username or "пользователь"
    reports_count = len(reports)

    has_full = any(r.report_type == "full" for r in reports)

    if not user.main_archetype:
        text = profile_no_matrix_text(name)
        kb = profile_keyboard(has_matrix=False, is_subscriber=False)
    elif user.subscription_status == "premium":
        until_str = user.subscription_until.strftime("%d.%m.%Y") if user.subscription_until else "—"
        text = profile_subscriber_text(name, user.main_archetype, until_str, reports_count)
        kb = profile_keyboard(has_matrix=True, is_subscriber=True)
    elif has_full:
        text = profile_full_text(name, user.main_archetype, reports_count)
        kb = profile_keyboard(has_matrix=True, is_subscriber=False, has_full_report=True)
    else:
        text = profile_mini_text(name, user.main_archetype, reports_count)
        kb = profile_keyboard(has_matrix=True, is_subscriber=False)

    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "view_reports")
async def view_reports(callback: CallbackQuery) -> None:
    await callback.answer()

    user, reports = await _get_user_and_reports(callback.from_user.id)
    if user is None:
        await callback.message.edit_text("Пользователь не найден. Начни с /start")
        return

    if not reports:
        text = reports_list_text([])
        await callback.message.edit_text(text, reply_markup=reports_keyboard([]))
        return

    report_list = []
    for r in reports:
        has_pdf = r.report_type == "full"
        report_type_name = {
            "mini": "Матрица",
            "full": "Матрица",
            "compatibility": "Совместимость",
        }.get(r.report_type, "Матрица")
        report_list.append({
            "token": r.token,
            "has_pdf": has_pdf,
            "type": report_type_name,
            "date": r.created_at.strftime("%d.%m.%Y"),
            "is_full": r.report_type == "full",
        })

    text = reports_list_text(report_list)
    await callback.message.edit_text(text, reply_markup=reports_keyboard(report_list))


@router.callback_query(F.data == "subscription")
async def show_subscription(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        subscription_offer_text(),
        reply_markup=subscription_keyboard(),
    )


@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: CallbackQuery) -> None:
    await callback.answer()
    user, reports = await _get_user_and_reports(callback.from_user.id)
    if user is None:
        await callback.message.edit_text("Пользователь не найден. Начни с /start")
        return

    await _show_profile(callback.message, user, reports)
