from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard(
    has_matrix: bool = False,
    has_tarot: bool = False,
    subscription_status: str = "free",
    # backward-compat: ignored, use has_matrix
    purchased_matrix: bool = False,
    has_pwa_shown: bool = False,
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
            InlineKeyboardButton(text="📄 Мои отчёты", callback_data="view_reports"),
            InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
        ],
    ]
    if has_matrix:
        keyboard.insert(0, [
            InlineKeyboardButton(text="🌐 Открыть в NURA", url="https://nura-ai.ru/app")
        ])
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
    has_matrix: bool = False,
    is_subscriber: bool = False,
    has_tarot: bool = False,
) -> InlineKeyboardMarkup:
    """
    Личный кабинет — управление подпиской, поддержка, меню.
    Кнопки «Мои отчёты» и «Чат с NURA» — в главном меню.
    """
    if is_subscriber or has_tarot:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 Управление подпиской", callback_data="manage_subscription")],
                [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
            ]
        )

    if has_matrix:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💎 Оформить подписку — 390 ₽/мес", callback_data="buy_subscription")],
                [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✨ Рассчитать матрицу", callback_data="calculate_matrix")],
            [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")],
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


def pwa_cta_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Открыть NURA в браузере", url="https://nura-ai.ru/app/chat")],
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


def open_pwa_keyboard(url: str = "https://nura-ai.ru/app") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Открыть в NURA", url=url)],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
    ])
