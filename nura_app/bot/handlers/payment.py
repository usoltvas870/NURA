import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.main_menu import main_menu_keyboard
from bot.texts.payment import (
    already_paid_text,
    payment_error_text,
    payment_link_text,
    payment_pending_text,
    report_ready_text,
)
from core.config import settings
from core.database import get_async_sessionmaker
from core.repositories.payment import PaymentRepository
from core.repositories.report import ReportRepository
from core.repositories.user import UserRepository
from core.services.access import can_access_full_report
from core.services.payment import PaymentService
from core.tasks import generate_full_report

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


@router.callback_query(F.data.startswith("pay_full_report:"))
async def initiate_full_report_payment(callback: CallbackQuery) -> None:
    await callback.answer()

    token = callback.data.split(":", 1)[1]
    if not token:
        await callback.message.edit_text(
            payment_error_text(),
            reply_markup=main_menu_keyboard(),
        )
        return

    report = await _get_report_by_token(token)
    if report and report.report_type == "full":
        text = already_paid_text()
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="👁 Открыть", callback_data=f"open_report:{token}"),
                ],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
            ]
        )
        await callback.message.edit_text(text, reply_markup=kb)
        return

    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return

    report_birth_date = (report.matrix_data or {}).get("birth_date") if report else None
    if not report_birth_date:
        report_birth_date = user.birth_date

    access, reason = await can_access_full_report(user, report_birth_date)

    if access and reason == "subscription":
        generate_full_report.delay(str(user.id), report_birth_date, token)
        await callback.message.edit_text(
            "🎉 Доступно по подписке!\n\n"
            "🔄 Генерирую твой полный AI-отчёт...\n"
            "Это займёт около минуты.\n\n"
            "Я пришлю уведомление, как только он будет готов.",
            reply_markup=main_menu_keyboard(),
        )
        return

    if reason == "other_person":
        message_prefix = (
            "ℹ️ Этот отчёт для другого человека.\n"
            "Приобрети его отдельно за 590 ₽.\n\n"
        )
    else:
        message_prefix = ""

    try:
        payment = await PaymentService.create_payment(
            telegram_id=user.telegram_id,
            amount=settings.report_price_rub,
            description="NURA — Полный разбор матрицы",
            metadata={"report_token": token, "user_id": str(user.id)},
        )

        await callback.message.edit_text(
            message_prefix + payment_link_text(),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"💳 Оплатить {settings.report_price_rub} ₽", url=payment["payment_url"])],
                    [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
                ]
            ),
        )

        session_factory = get_async_sessionmaker()
        payment_repo = PaymentRepository(session_factory)
        await payment_repo.create(
            user_id=user.id,
            amount=settings.report_price_rub,
            yookassa_id=payment["id"],
        )

        await callback.message.answer(payment_pending_text())

    except Exception:
        logger.exception("Failed to create payment for user %s", user.id)
        await callback.message.edit_text(
            payment_error_text(),
            reply_markup=main_menu_keyboard(),
        )


@router.callback_query(F.data.startswith("pay_compatibility:"))
async def initiate_compatibility_payment(callback: CallbackQuery) -> None:
    await callback.answer()

    token = callback.data.split(":", 1)[1]
    if not token:
        await callback.message.edit_text(
            payment_error_text(),
            reply_markup=main_menu_keyboard(),
        )
        return

    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return

    try:
        payment = await PaymentService.create_payment(
            telegram_id=user.telegram_id,
            amount=settings.report_price_rub,
            description="NURA — Полный разбор совместимости",
            metadata={"report_token": token, "user_id": str(user.id)},
        )

        await callback.message.edit_text(
            payment_link_text(),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"💳 Оплатить {settings.report_price_rub} ₽", url=payment["payment_url"])],
                    [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
                ]
            ),
        )

        session_factory = get_async_sessionmaker()
        payment_repo = PaymentRepository(session_factory)
        await payment_repo.create(
            user_id=user.id,
            amount=settings.report_price_rub,
            yookassa_id=payment["id"],
        )

        await callback.message.answer(payment_pending_text())

    except Exception:
        logger.exception("Failed to create compatibility payment for user %s", user.id)
        await callback.message.edit_text(
            payment_error_text(),
            reply_markup=main_menu_keyboard(),
        )


@router.callback_query(F.data == "full_report_pay")
async def full_report_pay(callback: CallbackQuery) -> None:
    await callback.answer()

    user = await _get_user(callback.from_user.id)
    if not user or not user.birth_date:
        await callback.message.edit_text(
            "Сначала рассчитай базовую матрицу — напиши /start ✶",
            reply_markup=main_menu_keyboard(),
        )
        return

    session_factory = get_async_sessionmaker()
    report_repo = ReportRepository(session_factory)
    reports = await report_repo.get_by_user_id(user.id)
    mini_report = next((r for r in reports if r.report_type == "mini"), None)

    if mini_report:
        from bot.texts.matrix import mini_analysis_text
        analysis = mini_report.ai_analysis or {}
        matrix_data = mini_report.matrix_data or {}
        text = mini_analysis_text(
            archetype_name=matrix_data.get("archetype_name", user.main_archetype or "..."),
            archetype_number=matrix_data.get("archetype_number", user.main_archetype_number or 0),
            main_archetype=analysis.get("main_archetype", "..."),
            core_strength=analysis.get("core_strength", "..."),
            emotional_conflict=analysis.get("emotional_conflict", "..."),
            relationship_pattern=analysis.get("relationship_pattern", "..."),
            financial_block=analysis.get("financial_block", "..."),
        )
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔮 Полный разбор за 590 ₽", callback_data=f"pay_full_report:{mini_report.token}")],
                    [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
                ]
            ),
        )
        return

    await callback.message.edit_text(
        "Для доступа к полному разбору нужно сначала получить мини-анализ.\n\n"
        "Нажми «Рассчитать матрицу», чтобы начать:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✨ Рассчитать матрицу", callback_data="calculate_matrix")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
            ]
        ),
    )


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
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👁 Открыть отчёт", url=report_url)],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
        ]
    )
    await callback.message.answer(report_ready_text(), reply_markup=kb)


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
