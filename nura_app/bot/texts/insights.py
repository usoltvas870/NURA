from bot.utils.formatting import escape_telegram_html


def no_matrix_text() -> str:
    return (
        "Чтобы получать инсайты, сначала нужно рассчитать свою матрицу.\n\n"
        "Нажми ✨ <b>Рассчитать матрицу</b> — и возвращайся за инсайтами."
    )


def insight_of_day_text(archetype: str, insight_text: str) -> str:
    return (
        f"<b>🌒 Инсайт дня</b>\n"
        f"<i>для архетипа {escape_telegram_html(archetype)}</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{escape_telegram_html(insight_text)}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Этот инсайт пришёл к тебе сегодня неслучайно.\n"
        "<i>Попробуй заметить, как он отзовётся в течение дня.</i>"
    )


def share_insight_text(insight_text: str) -> str:
    return (
        f"<b>🌒 Инсайт дня от NURA</b>\n\n"
        f"{escape_telegram_html(insight_text)}\n\n"
        "— NURA, твой AI-проводник"
    )


def insight_copied_text() -> str:
    return (
        "Готово! Инсайт скопирован.\n"
        "<i>Можешь отправить его кому-то близкому.</i>"
    )


def insights_exhausted_text() -> str:
    return (
        "Ты сегодня уже достаточно услышал.\n"
        "Сохрани этот инсайт — он будет ждать тебя завтра.\n\n"
        "А хочешь получать инсайты <b>каждое утро</b>?\n"
        "Оформи подписку — и они будут приходить сами 🌅"
    )


def no_insights_text() -> str:
    return "У тебя пока нет инсайтов. Рассчитай матрицу, чтобы получать их."
