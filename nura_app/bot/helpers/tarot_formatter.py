import logging

logger = logging.getLogger(__name__)

HTML_TAROT_CARD = '''<blockquote style="background:#1a2a3a;border:1px solid #c9a96e;border-radius:12px;padding:16px;margin:8px 0;">
  🃏 <b>Твоя карта дня — {number}. {name}</b>
</blockquote>'''

HTML_TAROT_SPREAD = '''<blockquote style="background:#1a2a3a;border:1px solid #c9a96e;border-radius:12px;padding:16px;margin:8px 0;">
  <b>{title}</b>
  <i>{arcana_name}</i>
  {interpretation}
</blockquote>'''


def format_tarot_message(card_data: dict, message_type: str = "daily") -> str:
    if message_type == "daily":
        return _format_daily_html(card_data)
    if message_type == "spread":
        return _format_spread_html(card_data)
    if message_type == "question":
        return _format_question_html(card_data)
    logger.warning("Unknown tarot message_type: %s", message_type)
    return str(card_data)


def _format_daily_html(data: dict) -> str:
    lines = [
        "<b>✦ Ежедневный ритуал ✦</b>\n",
        HTML_TAROT_CARD.format(number=data["card_number"], name=data["card_name"]),
        data["key_phrase"],
        "",
        data["interpretation"],
    ]
    if data.get("matrix_link"):
        lines.extend(["", data["matrix_link"]])
    lines.extend([
        "",
        f"<b>💡 Совет:</b> {data['advice']}",
        f"<b>🌀 Аффирмация:</b> {data['affirmation']}",
        "",
        "<b>✦ Готов к следующему шагу ✦</b>",
    ])
    return "\n".join(lines)


def _format_spread_html(data: dict) -> str:
    body = data["body"]
    mind = data["mind"]
    spirit = data["spirit"]
    lines = [
        "<b>✦ Расклад недели ✦</b>\n",
        HTML_TAROT_SPREAD.format(
            title="🫀 Тело",
            arcana_name=f"{body['card_name']} ({body['card_number']} аркан)",
            interpretation=f"{body['energy']}\n{body['interpretation']}\n→ {body['practice']}",
        ),
        HTML_TAROT_SPREAD.format(
            title="🧠 Ум",
            arcana_name=f"{mind['card_name']} ({mind['card_number']} аркан)",
            interpretation=f"{mind['energy']}\n{mind['interpretation']}\n→ {mind['practice']}",
        ),
        HTML_TAROT_SPREAD.format(
            title="🌟 Дух",
            arcana_name=f"{spirit['card_name']} ({spirit['card_number']} аркан)",
            interpretation=f"{spirit['energy']}\n{spirit['interpretation']}\n→ {spirit['practice']}",
        ),
        data["overall"],
        "",
        "<b>✦ Готов к следующему шагу ✦</b>",
    ]
    return "\n".join(lines)


def _format_question_html(data: dict) -> str:
    past = data["past"]
    present = data["present"]
    future = data["future"]
    lines = [
        "<b>✦ Расклад по вопросу ✦</b>\n",
        HTML_TAROT_SPREAD.format(
            title="📜 Прошлое",
            arcana_name=f"{past['card_name']} ({past['card_number']} аркан)",
            interpretation=f"{past['meaning']}\n{past['how_it_relates']}",
        ),
        HTML_TAROT_SPREAD.format(
            title="📌 Настоящее",
            arcana_name=f"{present['card_name']} ({present['card_number']} аркан)",
            interpretation=f"{present['meaning']}\n{present['how_it_relates']}",
        ),
        HTML_TAROT_SPREAD.format(
            title="🔮 Будущее",
            arcana_name=f"{future['card_name']} ({future['card_number']} аркан)",
            interpretation=f"{future['meaning']}\n{future['how_it_relates']}",
        ),
        data["summary"],
        "",
        f"<b>💡 Совет:</b> {data['advice']}",
        "",
        "<b>✦ Готов к следующему шагу ✦</b>",
    ]
    return "\n".join(lines)


def format_tarot_paywall() -> str:
    return (
        "🃏 Таро-ритуалы — это ежедневные расклады на основе твоей матрицы.\n\n"
        "Каждый день новая карта — новый взгляд на то, что происходит "
        "в твоей жизни. Арканы подсказывают паттерны, которые уже "
        "разворачиваются вокруг тебя.\n\n"
        "✨ Что ты получишь:\n"
        "• 🂡 Карта дня — ежедневный архетип-проводник\n"
        "• 🂠 Расклад недели — сценарий ближайших 7 дней\n"
        "• ❓ Ответ на вопрос — расклад по твоей ситуации\n\n"
        "💎 Таро-доступ — 390 ₽/мес"
    )
