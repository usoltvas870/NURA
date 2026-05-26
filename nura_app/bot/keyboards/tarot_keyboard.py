from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def tarot_menu_keyboard(has_tarot: bool = False) -> InlineKeyboardMarkup:
    if has_tarot:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🌒 Карта дня", callback_data="tarot_daily_card")],
                [
                    InlineKeyboardButton(text="✦ Расклад недели", callback_data="tarot_weekly"),
                    InlineKeyboardButton(text="◈ По вопросу", callback_data="tarot_question"),
                ],
                [
                    InlineKeyboardButton(text="✶ Сферы жизни", callback_data="tarot_spheres"),
                    InlineKeyboardButton(text="☯ Двойники", callback_data="tarot_twins"),
                ],
                [
                    InlineKeyboardButton(text="🌅 Портал месяца", callback_data="tarot_portal"),
                    InlineKeyboardButton(text="👁 Да/Нет", callback_data="tarot_yes_no"),
                ],
                [InlineKeyboardButton(text="← Назад", callback_data="main_menu")],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌒 Карта дня", callback_data="tarot_daily_card")],
            [
                InlineKeyboardButton(text="🔒 Расклад недели", callback_data="tarot_weekly"),
                InlineKeyboardButton(text="🔒 По вопросу", callback_data="tarot_question"),
            ],
            [
                InlineKeyboardButton(text="🔒 Сферы жизни", callback_data="tarot_spheres"),
                InlineKeyboardButton(text="🔒 Двойники", callback_data="tarot_twins"),
            ],
            [
                InlineKeyboardButton(text="🔒 Портал месяца", callback_data="tarot_portal"),
                InlineKeyboardButton(text="🔒 Да/Нет", callback_data="tarot_yes_no"),
            ],
            [InlineKeyboardButton(text="✨ Открыть практику — 390₽/мес", callback_data="buy_tarot_subscription")],
            [InlineKeyboardButton(text="← Назад", callback_data="main_menu")],
        ]
    )


def tarot_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="← К раскладам", callback_data="tarot_menu")],
        ]
    )


def tarot_paywall_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✨ Подключить — 390₽/мес", callback_data="buy_tarot_subscription")],
            [InlineKeyboardButton(text="← К раскладам", callback_data="tarot_menu")],
        ]
    )


def tarot_spheres_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💰 Деньги", callback_data="tarot_sphere_money"),
                InlineKeyboardButton(text="❤️ Отношения", callback_data="tarot_sphere_relations"),
                InlineKeyboardButton(text="✦ Предназначение", callback_data="tarot_sphere_purpose"),
            ],
            [InlineKeyboardButton(text="← К раскладам", callback_data="tarot_menu")],
        ]
    )
