from bot.utils.formatting import escape_telegram_html


def paywall_text() -> str:
    return (
        "<b>✨ На сегодня доступны все 5 бесплатных ответов.</b>\n\n"
        "Новый лимит появится в следующий календарный день.\n\n"
        "<i>Твои сохранённые разборы, карта дня, профиль и меню остаются доступны.</i>"
    )


def greeting_text_free(name: str, archetype: str) -> str:
    safe_name = escape_telegram_html(name)
    safe_archetype = escape_telegram_html(archetype)
    return (
        f"<b>💬 Чат с NURA</b>\n\n"
        f"{safe_name}, твой архетип — <b>{safe_archetype}</b>.\n"
        "Я знаю твою матрицу и здесь, чтобы говорить с тобой на её языке.\n\n"
        "У тебя <b>5 бесплатных ответов на сегодня</b>.\n\n"
        "Ты можешь спросить меня о себе, отношениях, работе или повторяющихся "
        "жизненных сценариях.\n\n"
        "<b>Готов?</b> Просто напиши мне что-нибудь."
    )


def greeting_text_unlimited(name: str, archetype: str) -> str:
    safe_name = escape_telegram_html(name)
    safe_archetype = escape_telegram_html(archetype)
    return (
        f"<b>💬 Чат с NURA</b>\n\n"
        f"{safe_name}, твой архетип — <b>{safe_archetype}</b>.\n"
        "Я знаю твою матрицу и здесь, чтобы говорить с тобой на её языке.\n\n"
        "<b>✨ Полный доступ — без ограничений.</b>\n\n"
        "Ты можешь спросить меня о себе, отношениях, работе или повторяющихся "
        "жизненных сценариях.\n\n"
        "<b>Готов?</b> Просто напиши мне что-нибудь."
    )


def history_cleared_text() -> str:
    return (
        "<b>🗑 История диалога очищена.</b>\n\n"
        "Мы начинаем заново. Что ты хочешь спросить?"
    )


def exit_text(name: str) -> str:
    safe_name = escape_telegram_html(name)
    return (
        f"<b>🚪 Ты вышел из чата.</b>\n\n"
        "Если захочешь поговорить — нажми 💬 Чат с NURA в главном меню.\n\n"
        f"<i>Береги себя, {safe_name} ✦</i>"
    )


def messages_remaining_text(remaining: int) -> str:
    if remaining <= 0:
        return "\n\n<i>Это был последний бесплатный ответ на сегодня.</i>"
    plural = "ответ" if remaining == 1 else "ответа" if remaining in (2, 3, 4) else "ответов"
    return f"\n\n<i>Осталось {remaining} бесплатных {plural} на сегодня.</i>"
