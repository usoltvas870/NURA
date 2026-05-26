from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_keyboard(has_matrix: bool = True, has_tarot: bool = False) -> InlineKeyboardMarkup:
    matrix_btn = (
        InlineKeyboardButton(text="🔮 Моя матрица", callback_data="my_matrix")
        if has_matrix
        else InlineKeyboardButton(text="✨ Рассчитать матрицу", callback_data="calculate_matrix")
    )
    tarot_btn = (
        InlineKeyboardButton(text="🃏 Ритуалы дня", callback_data="tarot_menu")
        if has_tarot
        else InlineKeyboardButton(text="🃏 Карта дня", callback_data="ritual")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                matrix_btn,
                InlineKeyboardButton(text="🌒 Инсайты", callback_data="insights"),
            ],
            [
                tarot_btn,
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


def profile_keyboard(has_matrix: bool, is_subscriber: bool, has_full_report: bool = False, has_tarot: bool = False) -> InlineKeyboardMarkup:
    if not has_matrix:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✨ Рассчитать матрицу", callback_data="calculate_matrix")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
            ]
        )

    if has_tarot and not is_subscriber:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🃏 Ритуалы дня", callback_data="tarot_menu")],
                [InlineKeyboardButton(text="💬 Чат с NURA", callback_data="chat_with_nura")],
                [InlineKeyboardButton(text="📋 Мои отчёты", callback_data="view_reports")],
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

    if has_full_report:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💬 Чат с NURA", callback_data="chat_with_nura")],
                [InlineKeyboardButton(text="📋 Мои отчёты", callback_data="view_reports")],
                [InlineKeyboardButton(text="💎 О подписке", callback_data="subscription")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Полный отчёт по подписке", callback_data="buy_subscription")],
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
    for i, report in enumerate(reports, 1):
        token = report.get("token", "")
        has_pdf = report.get("has_pdf", False)
        rtype = report.get("type", "Матрица")
        date = report.get("date", "")
        emoji = "❤️" if "совместимость" in rtype.lower() else "🎭"
        label = f"{emoji} {rtype} {date}"
        buttons = []
        buttons.append(InlineKeyboardButton(text=label, callback_data=f"open_report:{token}"))
        if has_pdf:
            buttons.append(InlineKeyboardButton(text="📄 PDF", callback_data=f"download_pdf:{token}"))
        if buttons:
            builder.row(*buttons, width=len(buttons))
    builder.row(InlineKeyboardButton(text="👤 Назад в профиль", callback_data="back_to_profile"))
    return builder.as_markup()
