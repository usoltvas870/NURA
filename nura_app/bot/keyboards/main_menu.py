from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔮 Моя матрица", callback_data="my_matrix"),
                InlineKeyboardButton(text="🌒 Инсайты", callback_data="insights"),
            ],
            [
                InlineKeyboardButton(text="💬 Чат с NURA", callback_data="chat_with_nura"),
                InlineKeyboardButton(text="❤️ Совместимость", callback_data="compatibility"),
            ],
            [
                InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
            ],
        ]
    )


def compatibility_paywall_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Полный разбор по подписке 390 ₽/мес", callback_data="buy_subscription")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
        ]
    )


def profile_keyboard(has_matrix: bool, is_subscriber: bool) -> InlineKeyboardMarkup:
    if not has_matrix:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✨ Рассчитать матрицу", callback_data="calculate_matrix")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
            ]
        )

    if is_subscriber:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💬 Чат с NURA", callback_data="chat_with_nura")],
                [InlineKeyboardButton(text="📋 Мои отчёты", callback_data="view_reports")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Чат с NURA", callback_data="chat_with_nura")],
            [InlineKeyboardButton(text="📋 Мои отчёты", callback_data="view_reports")],
            [InlineKeyboardButton(text="💎 О подписке", callback_data="subscription")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
        ]
    )


def insight_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Поделиться", callback_data="share_insight"),
                InlineKeyboardButton(text="🔄 Ещё", callback_data="another_insight"),
            ],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
        ]
    )


def insight_keyboard_subscriber() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Поделиться", callback_data="share_insight"),
            ],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
        ]
    )


def subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Оформить 390 ₽/мес", callback_data="buy_subscription")],
            [InlineKeyboardButton(text="👤 Назад в профиль", callback_data="back_to_profile")],
        ]
    )


def reports_keyboard(reports: list, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for report in reports:
        token = report.get("token", "")
        has_pdf = report.get("has_pdf", False)
        buttons = []
        buttons.append(InlineKeyboardButton(text="👁 Открыть", callback_data=f"open_report:{token}"))
        if has_pdf:
            buttons.append(InlineKeyboardButton(text="📄 PDF", callback_data=f"download_pdf:{token}"))
        if buttons:
            builder.row(*buttons, width=len(buttons))
    builder.row(InlineKeyboardButton(text="👤 Назад в профиль", callback_data="back_to_profile"))
    return builder.as_markup()
