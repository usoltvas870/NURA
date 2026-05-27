import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.main_menu import main_menu_keyboard
from bot.texts.payment import (
    payment_error_text,
    payment_pending_text,
    report_ready_text,
)
from core.config import settings
from core.database import get_async_sessionmaker
from core.models import ReportType
from core.repositories.report import ReportRepository
from core.repositories.user import UserRepository
from core.services.payment import PaymentService

logger = logging.getLogger(__name__)

router = Router()


async def _get_user(telegram_id: int):
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    return await user_repo.get_by_telegram_id(telegram_id)


async def _get_report_by_token(token: str):
    session_factory = get_async_sessionmaker()
    report_repo = ReportRepository(session_factory)
    return await report_repo.get_by_token(token)





@router.callback_query(F.data == "buy_subscription")
async def initiate_subscription(callback: CallbackQuery) -> None:
    await callback.answer()

    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return

    if user.subscription_status == "premium":
        until_str = user.subscription_until.strftime("%d.%m.%Y") if user.subscription_until else "—"
        text = (
            "🎉 Подписка уже активна!\n\n"
            f"Твой статус: 👑 Premium\n"
            f"Действительна до: {until_str}"
        )
        await callback.message.edit_text(text, reply_markup=main_menu_keyboard())
        return

    if settings.test_mode:
        from datetime import datetime, timedelta, timezone
        session_factory = get_async_sessionmaker()
        user_repo = UserRepository(session_factory)
        until_date = datetime.now(timezone.utc) + timedelta(days=30)
        await user_repo.update_subscription(user.id, "premium", until_date)
        until_str = until_date.strftime("%d.%m.%Y")

        if user.birth_date:
            from core.tasks import generate_full_report
            from core.repositories.report import ReportRepository
            report_repo = ReportRepository(session_factory)
            existing = await report_repo.get_by_user_id_and_type(user.id, ReportType.FULL)
            if not existing:
                from core.services.report import ReportService
                report_token = ReportService.generate_token()
                generate_full_report.delay(str(user.id), user.birth_date, report_token)

        await callback.message.edit_text(
            f"🎉 Подписка активирована!\n"
            f"(тестовый режим — оплата не требуется)\n\n"
            f"Твой статус: 👑 Premium\n"
            f"Действительна до: {until_str}",
            reply_markup=main_menu_keyboard(),
        )
        return

    try:
        subscription = await PaymentService.create_subscription(
            telegram_id=user.telegram_id,
        )

        await callback.message.edit_text(
            "Почти готово!\n\n"
            "Для оформления подписки нужно завершить оплату.\n\n"
            "⚠️ Не закрывай это окно, пока платёж не завершится.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💎 Оплатить 390 ₽/мес", url=subscription["payment_url"])],
                    [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
                ]
            ),
        )

        await callback.message.answer(payment_pending_text())

    except Exception:
        logger.exception("Failed to create subscription for user %s", user.id)
        await callback.message.edit_text(
            payment_error_text(),
            reply_markup=main_menu_keyboard(),
        )


@router.callback_query(F.data == "buy_tarot_subscription")
async def initiate_tarot_subscription(callback: CallbackQuery) -> None:
    await callback.answer()

    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return

    if user.tarot_subscription:
        await callback.message.edit_text(
            "🃏 Таро-подписка уже активна!\n\n"
            "У тебя есть доступ к карте дня, раскладу недели и раскладу по вопросу.",
            reply_markup=main_menu_keyboard(has_tarot=True),
        )
        return

    if settings.test_mode:
        from datetime import datetime, timedelta, timezone
        session_factory = get_async_sessionmaker()
        user_repo = UserRepository(session_factory)
        until_date = datetime.now(timezone.utc) + timedelta(days=30)
        await user_repo.update_tarot_subscription(user.id, True, until_date)

        await callback.message.edit_text(
            "🃏 Таро-подписка активирована!\n"
            "(тестовый режим — оплата не требуется)\n\n"
            "Теперь тебе доступны:\n"
            "• Карта дня\n"
            "• Расклад недели\n"
            "• Расклад по вопросу",
            reply_markup=main_menu_keyboard(has_tarot=True),
        )
        return

    try:
        subscription = await PaymentService.create_subscription(
            telegram_id=user.telegram_id,
        )

        await callback.message.edit_text(
            "🃏 Таро-подписка — 390 ₽/мес\n\n"
            "Что входит:\n"
            "• Карта дня — аркан привязанный к твоей матрице\n"
            "• Расклад недели — энергия 7 дней\n"
            "• Расклад по вопросу — ситуация, отношения, карьера\n"
            "• Безлимитный AI-чат\n\n"
            "Не закрывай окно пока платёж не завершится.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="💎 Оплатить 390 ₽/мес",
                        url=subscription["payment_url"]
                    )],
                    [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
                ]
            ),
        )

    except Exception:
        logger.exception("Failed to create tarot subscription for user %s", user.id)
        await callback.message.edit_text(
            payment_error_text(),
            reply_markup=main_menu_keyboard(),
        )


@router.callback_query(F.data == "buy_matrix")
async def buy_matrix(callback: CallbackQuery) -> None:
    await callback.answer()

    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return

    if user.has_matrix:
        await callback.message.edit_text(
            "◈ Матрица уже куплена.\n"
            "Твой отчёт доступен в профиле.",
            reply_markup=main_menu_keyboard(purchased_matrix=True),
        )
        return

    if settings.test_mode:
        session_factory = get_async_sessionmaker()
        user_repo = UserRepository(session_factory)
        await user_repo.update_has_matrix(user.id, True)

        if user.birth_date:
            try:
                from core.tasks import generate_full_report
                from core.repositories.report import ReportRepository
                report_repo = ReportRepository(session_factory)
                existing = await report_repo.get_by_user_id_and_type(user.id, ReportType.FULL)
                if not existing:
                    from core.services.report import ReportService
                    report_token = ReportService.generate_token()
                    generate_full_report.delay(str(user.id), user.birth_date, report_token)
            except Exception:
                logger.exception("Failed to queue full report generation for user %s", user.id)

        await callback.message.edit_text(
            "✦ Тест-режим: Матрица активирована!\n"
            "Генерирую отчёт...",
            reply_markup=main_menu_keyboard(purchased_matrix=True),
        )
        return

    try:
        payment = await PaymentService.create_matrix_payment(
            telegram_id=callback.from_user.id
        )
        await PaymentService.save_matrix_payment(
            session_factory=get_async_sessionmaker(),
            user_id=user.id,
            yookassa_payment_id=payment["id"],
        )

        await callback.message.edit_text(
            "💎 Матрица Судьбы — 890₽\n\n"
            "Полный AI-отчёт по твоей дате рождения:\n"
            "• 15 секций · 30–50 страниц\n"
            "• HTML + PDF навсегда\n"
            "• 1 расклад совместимости\n\n"
            "Нажми кнопку для оплаты 👇",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="💳 Оплатить 890₽",
                        url=payment["payment_url"]
                    )],
                    [InlineKeyboardButton(
                        text="← Назад",
                        callback_data="main_menu"
                    )],
                ]
            ),
        )
    except ValueError:
        logger.exception("Failed to create matrix payment for user %s", user.id)
        await callback.message.edit_text(
            "⚠️ Оплата временно недоступна.\n"
            "Попробуй позже.",
            reply_markup=main_menu_keyboard(),
        )
    except Exception:
        logger.exception("Failed to create matrix payment for user %s", user.id)
        await callback.message.edit_text(
            payment_error_text(),
            reply_markup=main_menu_keyboard(),
        )


@router.callback_query(F.data.startswith("open_report:"))
async def open_report(callback: CallbackQuery) -> None:
    await callback.answer()

    token = callback.data.split(":", 1)[1]
    report = await _get_report_by_token(token)

    if report is None:
        await callback.message.edit_text(
            "Отчёт не найден.",
            reply_markup=main_menu_keyboard(),
        )
        return

    report_url = f"{settings.report_base_url}/report/{token}"
    buttons = [[InlineKeyboardButton(text="👁 Открыть отчёт", url=report_url)]]
    if report.kitchen_analysis:
        buttons.insert(0, [InlineKeyboardButton(text="🧮 Показать расчёт", callback_data=f"kitchen:{token}")])
    buttons.append([InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer(report_ready_text(), reply_markup=kb)


@router.callback_query(F.data.startswith("kitchen:"))
async def show_kitchen_analysis(callback: CallbackQuery) -> None:
    await callback.answer()

    token = callback.data.split(":", 1)[1]
    report = await _get_report_by_token(token)

    if report is None or not report.kitchen_analysis:
        await callback.message.edit_text(
            "Кухонный слой не найден.",
            reply_markup=main_menu_keyboard(),
        )
        return

    ka = report.kitchen_analysis
    lines = ["<b>🧮 Кухонный слой — как NURA это посчитала</b>\n"]
    for key, entry in ka.items():
        if not isinstance(entry, dict):
            continue
        title = {
            "main_archetype": "Архетип",
            "strengths": "Сильные стороны",
            "shadow_side": "Теневая сторона",
            "relationship_dynamics": "Отношения",
            "financial_scenario": "Деньги и карьера",
            "recurring_mistakes": "Сценарии",
            "internal_conflicts": "Конфликты",
            "life_cycles": "Циклы",
            "karmic_tail_analysis": "Кармический хвост",
            "ancestral_programs": "Родовые программы",
            "life_purpose": "Предназначение",
            "life_forecast": "Прогноз",
        }.get(key, key)
        positions = entry.get("positions", [])
        energies = entry.get("energies", [])
        logic = entry.get("logic", "")
        if not logic:
            continue
        lines.append(f"\n<b>{title}</b>")
        if positions:
            lines.append(f"📍 Позиции: {', '.join(positions)}")
        if energies:
            lines.append(f"🔢 Арканы: {', '.join(energies)}")
        lines.append(f"💬 {logic}")

    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад к отчёту", callback_data=f"open_report:{token}")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("download_pdf:"))
async def download_pdf(callback: CallbackQuery) -> None:
    await callback.answer()

    token = callback.data.split(":", 1)[1]
    report = await _get_report_by_token(token)

    if report is None:
        await callback.message.edit_text(
            "Отчёт не найден.",
            reply_markup=main_menu_keyboard(),
        )
        return

    pdf_url = f"{settings.report_base_url}/report/{token}/pdf"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📄 Скачать PDF", url=pdf_url)],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
        ]
    )
    await callback.message.answer("PDF-отчёт готов к скачиванию:", reply_markup=kb)
