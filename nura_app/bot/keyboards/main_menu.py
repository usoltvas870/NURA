from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard(
    has_matrix: bool = False,
    has_tarot: bool = False,
    subscription_status: str = "free",
    # backward-compat: ignored, use has_matrix
    purchased_matrix: bool = False,
) -> InlineKeyboardMarkup:
    matrix_btn = (
        InlineKeyboardButton(text="◈ Моя матрица", callback_data="my_matrix")
        if has_matrix
        else InlineKeyboardButton(text="✨ Рассчитать матрицу", callback_data="calculate_matrix")
    )
    keyboard = [
        [
            matrix_btn,
            InlineKeyboardButton(text="🌒 Таро", callback_data="tarot_menu"),
        ],
        [
            InlineKeyboardButton(text="💬 Чат с NURA", callback_data="chat_with_nura"),
            InlineKeyboardButton(text="❤️ Совместимость", callback_data="compatibility"),
        ],
        [
            InlineKeyboardButton(text="📄 Пример отчёта", callback_data="sample_report"),
        ],
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
        ],
    ]
    # Кнопка «Купить разбор» скрывается если:
    # - has_matrix=True (матрица уже куплена)
    # - subscription_status="premium" (подписка даёт доступ ко всему)
    hide_buy_btn = has_matrix or subscription_status == "premium"
    if not hide_buy_btn:
        keyboard.insert(
            -1,
            [InlineKeyboardButton(text="💎 Купить разбор — 890 ₽", callback_data="buy_matrix")],
        )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def compatibility_paywall_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Полный разбор по подписке 390 ₽/мес", callback_data="buy_subscription")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
        ]
    )


def profile_keyboard(
    has_matrix: bool,
    is_subscriber: bool,
    has_full_report: bool = False,
    has_tarot: bool = False,
) -> InlineKeyboardMarkup:
    """
    Клавиатура профиля.
    Кнопка «Чат с NURA» убрана (задача 2.3) — чат доступен из главного меню.
    """
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
                [InlineKeyboardButton(text="📋 Мои отчёты", callback_data="view_reports")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
            ]
        )

    if has_tarot:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🃏 Ритуалы дня", callback_data="tarot_menu")],
                [InlineKeyboardButton(text="📋 Мои отчёты", callback_data="view_reports")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
            ]
        )

    if has_full_report:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📋 Мои отчёты", callback_data="view_reports")],
                [InlineKeyboardButton(text="💎 О подписке", callback_data="subscription")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
            ]
        )

    # Есть матрица, только мини-разбор
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Купить разбор — 890 ₽", callback_data="buy_matrix")],
            [InlineKeyboardButton(text="📋 Мои отчёты", callback_data="view_reports")],
            [InlineKeyboardButton(text="💎 О подписке", callback_data="subscription")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
        ]
    )


def subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Оформить подписку — 390 ₽/мес", callback_data="buy_subscription")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
        ]
    )


def reports_keyboard(reports: list) -> InlineKeyboardMarkup:
    buttons = []
    for r in reports:
        token = r.get("token", "")
        label = r.get("type", "Отчёт")
        row = [InlineKeyboardButton(text=f"👁 {label}", callback_data=f"open_report:{token}")]
        if r.get("has_pdf"):
            row.append(InlineKeyboardButton(text="📄 PDF", callback_data=f"download_pdf:{token}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="👤 Назад в профиль", callback_data="back_to_profile")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
