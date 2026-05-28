"""
Утилиты форматирования текстов бота NURA.
Применяются ко всем AI-ответам перед отправкой пользователю.
"""

import re


def format_bot_text(text: str) -> str:
    """
    Применяет правила форматирования к тексту от AI.

    Правила:
    1. Абзацы разделены пустой строкой (каждые 2-3 предложения)
    2. Ключевая мысль каждого абзаца выделена жирным
    3. Практическое действие в конце — курсив
    4. Максимум 3 предложения в абзаце
    5. Никаких HTML-тегов от AI — только наши
    """
    if not text:
        return text

    # Убрать лишние пробелы и переносы
    text = re.sub(r'\n{3,}', '\n\n', text.strip())

    # Убрать случайные HTML-теги которые мог добавить AI
    text = re.sub(r'<(?!b>|/b>|i>|/i>|code>|/code>)[^>]+>', '', text)

    return text


def format_tarot_result(
    title: str,
    body: str,
    cards: str = "",
    action: str = "",
) -> str:
    """
    Форматирует результат таро-расклада.

    Структура:
      {эмодзи} Название расклада
      ────────────────────
      {body — абзацами}

      ────────────────────
      {action — курсив если есть}

      {cards — курсив, через ·}
    """
    parts = []

    # Заголовок
    parts.append(f"<b>{title}</b>")
    parts.append("─" * 20)
    parts.append("")

    # Тело — разбить на абзацы по 3 предложения
    paragraphs = _split_into_paragraphs(body)
    parts.extend(paragraphs)

    # Практическое действие
    if action:
        parts.append("")
        parts.append("─" * 20)
        parts.append(f"<i>{action}</i>")

    # Карты
    if cards:
        parts.append("")
        parts.append(f"<i>{cards}</i>")

    return "\n".join(parts)


def format_compatibility_result(
    user_name: str,
    partner_name: str,
    portrait_user: str,
    portrait_partner: str,
    emotional: str,
    relation_type: str = "общение",
) -> str:
    """
    Форматирует результат совместимости.
    Имена вместо названий арканов.
    Тип отношений влияет на формулировки.
    """
    rel_labels = {
        "романтика":  ("В паре",    "ваши отношения", "партнёр"),
        "дружба":     ("В дружбе",  "ваша дружба",    "друг"),
        "работа":     ("В работе",  "ваше взаимодействие", "коллега"),
        "семья":      ("В семье",   "ваши отношения", "родственник"),
        "общение":    ("В общении", "ваше взаимодействие", "человек"),
    }
    context, rel_name, role = rel_labels.get(
        relation_type, rel_labels["общение"]
    )

    parts = []

    # Портрет пользователя
    parts.append(f"🎭 <b>{user_name}</b>")
    parts.append(format_bot_text(portrait_user))
    parts.append("")

    # Портрет партнёра
    parts.append(f"🎭 <b>{partner_name}</b>")
    parts.append(format_bot_text(portrait_partner))
    parts.append("")

    # Эмоциональная совместимость
    parts.append(f"💞 <b>{context}: как вы взаимодействуете</b>")
    parts.append(format_bot_text(emotional))

    return "\n".join(parts)


def _split_into_paragraphs(text: str, sentences_per_para: int = 3) -> list[str]:
    """
    Разбивает текст на абзацы по N предложений.
    Выделяет первое предложение каждого абзаца жирным.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    paragraphs = []
    for i in range(0, len(sentences), sentences_per_para):
        chunk = sentences[i:i + sentences_per_para]
        if not chunk:
            continue
        chunk[0] = f"<b>{chunk[0]}</b>"
        paragraphs.append(" ".join(chunk))

    return paragraphs
