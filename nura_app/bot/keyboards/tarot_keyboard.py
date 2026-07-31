from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from core.config import settings


def tarot_menu_keyboard(has_tarot: bool = False, *, expanded_enabled: bool = False) -> InlineKeyboardMarkup:
    """
    Новая структура (задача 2.2):
    [🌒 Карта дня]
    [💰 Деньги]  [❤️ Отношения]
    [🌟 Предназначение]  [🔮 Да / Нет]
    [❓ По вопросу]  [✨ Ещё расклады →]
    [← Назад]
    """
    if expanded_enabled and has_tarot:
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
    if not expanded_enabled:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🌙 Карта дня", callback_data="tarot_daily_card")],
                [InlineKeyboardButton(text="← Назад", callback_data="main_menu")],
            ]
        )
    # Для не-подписчиков: карта дня свободна, остальное — замки
    rows = [
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
    ]
    if settings.payment_operations_enabled:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✨ Открыть практику — 390 ₽/мес",
                    callback_data="buy_tarot_subscription",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="← Назад", callback_data="main_menu")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tarot_more_keyboard() -> InlineKeyboardMarkup:
    """
    Подменю «Ещё расклады» (callback: tarot_more):
    - Расклад недели
    - Теневые стороны (бывш. Двойники)
    - Энергия месяца (бывш. Портал месяца)
    - Что мешает
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✦ Расклад недели", callback_data="tarot_weekly")],
            [InlineKeyboardButton(text="☯ Теневые стороны", callback_data="tarot_twins")],
            [InlineKeyboardButton(text="🌅 Энергия месяца", callback_data="tarot_portal")],
            [InlineKeyboardButton(text="🚧 Что мешает", callback_data="tarot_blocks")],
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
    if not settings.payment_operations_enabled:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="← К раскладам", callback_data="tarot_menu")],
            ]
        )
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



def tarot_result_keyboard() -> InlineKeyboardMarkup:
    if settings.telegram_access_restricted:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="← К раскладам", callback_data="tarot_menu")],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Открыть в PWA", url="https://nura-ai.ru/app/tarot")],
            [InlineKeyboardButton(text="← К раскладам", callback_data="tarot_menu")],
        ]
    )

