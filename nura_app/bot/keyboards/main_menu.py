from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Рассчитать матрицу",
                    callback_data="calculate_matrix",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Совместимость",
                    callback_data="compatibility",
                ),
                InlineKeyboardButton(
                    text="Инсайты",
                    callback_data="insights",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Профиль",
                    callback_data="profile",
                ),
            ],
        ]
    )


def paywall_keyboard(report_token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Получить полный отчёт за 590 ₽",
                    callback_data=f"pay_{report_token}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Вернуться в меню",
                    callback_data="back_to_menu",
                )
            ],
        ]
    )
