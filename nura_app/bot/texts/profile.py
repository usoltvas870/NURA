def profile_no_matrix_text(name: str) -> str:
    return (
        f"<b>👤 {name}</b>\n\n"
        "Статус: 🌱 <i>исследователь</i>\n"
        "Матрица: <i>ещё не рассчитана</i>\n\n"
        "Твои 22 аркана пока молчат.\n"
        "Нажми кнопку — и узнай, какой архетип\n"
        "зашифрован в твоей дате рождения."
    )


def profile_mini_text(name: str, archetype: str, reports_count: int) -> str:
    return (
        f"<b>👤 {name}</b>\n\n"
        f"<b>🎭 Архетип:</b> {archetype}\n"
        "Статус: 📖 <i>есть мини-разбор</i>\n"
        f"Отчётов: {reports_count}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Твой мини-разбор — это только <b>первый слой</b>.\n"
        "Полный отчёт раскроет теневые стороны,\n"
        "жизненные циклы и даст персональные\n"
        "рекомендации на 7 дней."
    )


def profile_full_report_text(name: str, archetype: str, reports_count: int) -> str:
    return (
        f"<b>👤 {name}</b>\n\n"
        f"<b>🎭 Архетип:</b> {archetype}\n"
        "Статус: 📖 <i>есть полный отчёт</i>\n"
        f"Отчётов: {reports_count}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "У тебя уже есть доступ к полному разбору.\n"
        "Но матрица меняется каждый день —\n"
        "инсайты, чат с NURA и ежедневные подсказки\n"
        "доступны с подпиской."
    )


def profile_subscriber_text(name: str, archetype: str, until: str, reports_count: int) -> str:
    return (
        f"<b>👤 {name}</b>\n\n"
        f"<b>🎭 Архетип:</b> {archetype}\n"
        "👑 Статус: <b>подписка активна</b>\n"
        f"Подписка до: {until}\n"
        f"Отчётов: {reports_count}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>У тебя полный доступ:</b>\n"
        "• Чат с NURA без ограничений\n"
        "• Ежедневные инсайты в ЛС\n"
        "• Все отчёты без доплат"
    )


def reports_list_text(reports: list) -> str:
    if not reports:
        return (
            "У тебя пока нет ни одного отчёта.\n\n"
            "Начни с ✨ <b>Расчёта матрицы</b> — это бесплатно."
        )

    lines = ["<b>📋 Твои отчёты</b>\n", "━━━━━━━━━━━━━━━━━━━━\n"]
    for i, r in enumerate(reports, 1):
        report_type = r.get("type", "матрица")
        date = r.get("date", "")
        subtype = "полный" if r.get("is_full") else "мини-разбор"
        emoji = "❤️" if "совместимость" in report_type.lower() else "🎭"
        lines.append(f"{i}. {emoji} {report_type} — {date}")
        lines.append(f"   <i>Тип: {subtype}</i>\n")
    return "\n".join(lines)
