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

    try:
        payment = await PaymentService.create_payment(
            telegram_id=user.telegram_id,
            amount=settings.report_price_rub,
            description="NURA — Полный разбор матрицы",
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
