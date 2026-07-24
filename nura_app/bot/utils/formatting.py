"""
Утилиты форматирования текстов бота NURA.
Применяются ко всем AI-ответам перед отправкой пользователю.
"""

from html import escape
import re

TELEGRAM_INPUT_MAX_LENGTH = 2000
TELEGRAM_MESSAGE_MAX_LENGTH = 4096


def escape_telegram_html(value: object | None) -> str:
    """Escape an untrusted dynamic value for Telegram HTML parse mode."""
    if value is None:
        return ""
    return escape(str(value), quote=False)


def split_telegram_html_text(
    value: object | None,
    max_length: int = TELEGRAM_MESSAGE_MAX_LENGTH,
) -> list[str]:
    """Escape and split dynamic text without breaking generated HTML entities."""
    return split_telegram_html_message(
        escape_telegram_html(value),
        max_length=max_length,
    )


def split_telegram_html_message(
    html_text: str,
    max_length: int = TELEGRAM_MESSAGE_MAX_LENGTH,
) -> list[str]:
    """Split trusted static HTML plus escaped values without breaking markup atoms."""
    if max_length <= 0:
        raise ValueError("max_length must be positive")

    if not html_text:
        return [""]

    atoms = re.findall(
        r"&(?:amp|lt|gt);|</?(?:b|i|u|s|code|pre)>|.",
        html_text,
        flags=re.DOTALL,
    )
    chunks: list[str] = []
    current: list[str] = []
    open_tags: list[str] = []

    def closing_tags(tags: list[str]) -> str:
        return "".join(f"</{tag}>" for tag in reversed(tags))

    def tag_name(atom: str) -> str | None:
        if not atom.startswith("<"):
            return None
        return atom.removeprefix("</").removeprefix("<").removesuffix(">")

    for atom in atoms:
        next_open_tags = open_tags.copy()
        name = tag_name(atom)
        if name:
            if atom.startswith("</"):
                next_open_tags.pop()
            else:
                next_open_tags.append(name)

        if current and len("".join(current) + atom + closing_tags(next_open_tags)) > max_length:
            chunks.append("".join(current) + closing_tags(open_tags))
            current = [f"<{tag}>" for tag in open_tags]

        if len("".join(current) + atom + closing_tags(next_open_tags)) > max_length:
            raise ValueError("max_length is too small for trusted HTML markup")

        current.append(atom)
        open_tags = next_open_tags
    if current:
        chunks.append("".join(current) + closing_tags(open_tags))
    return chunks


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

    normalized = re.sub(r"\n{3,}", "\n\n", text.strip())
    return escape_telegram_html(normalized)


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
    parts.append(f"<b>{escape_telegram_html(title)}</b>")
    parts.append("─" * 20)
    parts.append("")

    # Тело — разбить на абзацы по 3 предложения
    paragraphs = _split_into_paragraphs(body)
    parts.extend(paragraphs)

    # Практическое действие
    if action:
        parts.append("")
        parts.append("─" * 20)
        parts.append(f"<i>{escape_telegram_html(action)}</i>")

    # Карты
    if cards:
        parts.append("")
        parts.append(f"<i>{escape_telegram_html(cards)}</i>")

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
    parts.append(f"🎭 <b>{escape_telegram_html(user_name)}</b>")
    parts.append(format_bot_text(portrait_user))
    parts.append("")

    # Портрет партнёра
    parts.append(f"🎭 <b>{escape_telegram_html(partner_name)}</b>")
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
    sentences = re.split(r"(?<=[.!?])\s+", escape_telegram_html(text.strip()))
    sentences = [s.strip() for s in sentences if s.strip()]

    paragraphs = []
    for i in range(0, len(sentences), sentences_per_para):
        chunk = sentences[i:i + sentences_per_para]
        if not chunk:
            continue
        chunk[0] = f"<b>{chunk[0]}</b>"
        paragraphs.append(" ".join(chunk))

    return paragraphs
