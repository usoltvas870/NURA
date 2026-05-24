from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def tarot_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🂡 Карта дня", callback_data="tarot_daily_card")],
            [InlineKeyboardButton(text="🂠 Расклад недели", callback_data="tarot_weekly_spread")],
            [InlineKeyboardButton(text="❓ Задать вопрос", callback_data="tarot_ask_question")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
        ]
    )


def tarot_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔙 Назад к ритуалам", callback_data="tarot_menu"),
                InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu"),
            ],
        ]
    )


def tarot_paywall_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Таро-подписка 390 ₽/мес", callback_data="buy_tarot_subscription")],
            [InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")],
        ]
    )
