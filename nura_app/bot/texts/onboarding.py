from bot.utils.formatting import escape_telegram_html


def onboarding_greeting_text(first_name: str) -> str:
    safe_first_name = escape_telegram_html(first_name)
    return (
        f"<b>Приятно познакомиться, {safe_first_name}! ✶</b>\n\n"
        "NURA — это пространство, где ты можешь узнать себя\n"
        "через свою <b>Матрицу Судьбы</b>.\n\n"
        "22 аркана, зашифрованных в твоей дате рождения, хранят\n"
        "твои <i>сильные стороны</i>, <i>скрытые таланты</i>,\n"
        "<i>эмоциональные сценарии</i> и многое другое.\n\n"
        "<b>Давай рассчитаем твою базовую матрицу — это бесплатно.</b>"
    )


def ask_birth_date_onboarding_text() -> str:
    return (
        "<b>Введи свою дату рождения</b>\n\n"
        "Формат: <b>ДД.ММ.ГГГГ</b>\n"
        "<i>Например: 15.06.1998</i>\n\n"
        "Это займёт меньше минуты ✶"
    )


def invalid_format_onboarding_text() -> str:
    return (
        "Формат должен быть таким: <b>ДД.ММ.ГГГГ</b>\n\n"
        "<i>Например: 15.06.1998</i>\n\n"
        "Попробуй ещё раз ↻"
    )


def onboarding_loading_text() -> str:
    return "<b>✶ Считаю твою матрицу...</b>\n\nРасшифровываю 22 аркана из чисел твоего рождения"


def onboarding_done_text(archetype_name: str, archetype_number: int) -> str:
    return (
        "<b>✶ Твоя базовая матрица готова!</b>\n\n"
        f"Твой архетип — <b>{archetype_name}</b> (энергия {archetype_number}).\n\n"
        "Теперь тебе доступно главное меню, где ты можешь:\n"
        "• 👤 Посмотреть свой профиль и матрицу\n"
        "• 🔮 Открыть полный разбор (AI-анализ)\n"
        "• ❤️ Проверить совместимость\n"
        "• 💬 Пообщаться с NURA в чате\n\n"
        "<i>Выбери, что хочешь сделать:</i>"
    )


def pd_consent_text() -> str:
    return "Для получения персонального анализа необходимо ваше согласие на обработку персональных данных (дата рождения). Вы согласны?"


def pd_consent_declined_text() -> str:
    return "Без согласия на обработку персональных данных мы не можем предоставить анализ. Вы можете вернуться позже."


def delete_account_warning_text() -> str:
    return "Вы уверены, что хотите удалить аккаунт? Все данные, отчёты и история будут удалены безвозвратно."


def delete_account_cancelled_text() -> str:
    return "Удаление аккаунта отменено."


def delete_account_done_text() -> str:
    return "Аккаунт удалён. Все ваши данные были удалены из системы."


def my_matrix_text(
    archetype_name: str,
    archetype_number: int,
    birth_date: str,
    center_name: str,
    top_name: str,
    bottom_name: str,
    left_name: str,
    right_name: str,
    talent_zone: str,
    comfort_zone: str,
    portrait_zone: str,
) -> str:
    return (
        f"<b>🔮 Твоя Матрица Судьбы</b>\n\n"
        f"<b>Дата рождения:</b> {birth_date}\n"
        f"<b>Главный архетип:</b> {archetype_name} ({archetype_number})\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>🎭 Основные позиции:</b>\n"
        f"• Центр (ты): {center_name}\n"
        f"• Верх (небо): {top_name}\n"
        f"• Низ (земля): {bottom_name}\n"
        f"• Лево (мужское): {left_name}\n"
        f"• Право (женское): {right_name}\n\n"
        f"<b>🌟 Зоны:</b>\n"
        f"• Таланты: {talent_zone}\n"
        f"• Комфорт: {comfort_zone}\n"
        f"• Портрет: {portrait_zone}\n\n"
        ""
    )
