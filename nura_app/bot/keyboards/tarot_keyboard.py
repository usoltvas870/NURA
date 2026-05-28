from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def tarot_menu_keyboard(has_tarot: bool = False) -> InlineKeyboardMarkup:
    """
    Новая структура (задача 2.2):
    [🌒 Карта дня]
    [💰 Деньги]  [❤️ Отношения]
    [🌟 Предназначение]  [🔮 Да / Нет]
    [❓ По вопросу]  [✨ Ещё расклады →]
    [← Назад]
    """
    if has_tarot:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🌒 Карта дня", callback_data="tarot_daily_card")],
                [
                    InlineKeyboardButton(text="💰 Деньги", callback_data="tarot_money"),
                    InlineKeyboardButton(text="❤️ Отношения", callback_data="tarot_relations"),
                ],
                [
                    InlineKeyboardButton(text="🌟 Предназначение", callback_data="tarot_purpose"),
                    InlineKeyboardButton(text="🔮 Да / Нет", callback_data="tarot_yes_no"),
                ],
                [
                    InlineKeyboardButton(text="❓ По вопросу", callback_data="tarot_question"),
                    InlineKeyboardButton(text="✨ Ещё расклады →", callback_data="tarot_more"),
                ],
                [InlineKeyboardButton(text="← Назад", callback_data="main_menu")],
            ]
        )
    # Для не-подписчиков: карта дня свободна, остальное — замки
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌒 Карта дня", callback_data="tarot_daily_card")],
            [
                InlineKeyboardButton(text="🔒 Деньги", callback_data="tarot_money"),
                InlineKeyboardButton(text="🔒 Отношения", callback_data="tarot_relations"),
            ],
            [
                InlineKeyboardButton(text="🔒 Предназначение", callback_data="tarot_purpose"),
                InlineKeyboardButton(text="🔒 Да / Нет", callback_data="tarot_yes_no"),
            ],
            [
                InlineKeyboardButton(text="🔒 По вопросу", callback_data="tarot_question"),
                InlineKeyboardButton(text="🔒 Ещё расклады", callback_data="tarot_more"),
            ],
            [InlineKeyboardButton(text="✨ Открыть практику — 390 ₽/мес", callback_data="buy_tarot_subscription")],
            [InlineKeyboardButton(text="← Назад", callback_data="main_menu")],
        ]
    )


def tarot_more_keyboard() -> InlineKeyboardMarkup:
    """
    Подменю «Ещё расклады» (callback: tarot_more):
    - Расклад недели
    - Сферы жизни (общий)
    - Теневые стороны (бывш. Двойники)
    - Энергия месяца (бывш. Портал месяца)
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✦ Расклад недели", callback_data="tarot_weekly")],
            [InlineKeyboardButton(text="✶ Сферы жизни", callback_data="tarot_spheres")],
            [InlineKeyboardButton(text="☯ Теневые стороны", callback_data="tarot_twins")],
            [InlineKeyboardButton(text="🌅 Энергия месяца", callback_data="tarot_portal")],
            [InlineKeyboardButton(text="← К раскладам", callback_data="tarot_menu")],
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
            [InlineKeyboardButton(text="✨ Подключить — 390 ₽/мес", callback_data="buy_tarot_subscription")],
            [InlineKeyboardButton(text="← К раскладам", callback_data="tarot_menu")],
        ]
    )


def tarot_spheres_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура сфер жизни (теперь общее подменю, отдельные сферы вынесены на верх)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💰 Деньги", callback_data="tarot_money"),
                InlineKeyboardButton(text="❤️ Отношения", callback_data="tarot_relations"),
                InlineKeyboardButton(text="🌟 Предназначение", callback_data="tarot_purpose"),
            ],
            [InlineKeyboardButton(text="← К раскладам", callback_data="tarot_menu")],
        ]
    )
