from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from weasyprint import HTML
from bot.handlers.chat import chat_message
from bot.handlers.tarot import handle_question_input
from bot.texts.chat import greeting_text_free
from bot.texts.matrix import mini_analysis_text
from bot.utils.formatting import (
    TELEGRAM_INPUT_MAX_LENGTH,
    TELEGRAM_MESSAGE_MAX_LENGTH,
    escape_telegram_html,
    format_bot_text,
    split_telegram_html_message,
    split_telegram_html_text,
)
from core.services.report import ReportService


def _matrix_data() -> dict[str, object]:
    return {
        "birth_date": "01.01.2000",
        "center": 1,
        "top": 1,
        "bottom": 1,
        "left": 1,
        "right": 1,
        "inner_f": 1,
        "inner_g": 1,
        "inner_h": 1,
        "inner_i": 1,
        "arcana_names": {},
    }


def _analysis() -> dict[str, str]:
    return {
        "main_archetype": "Маг <img src=x onerror=alert(1)>",
        "core_strength": 'Сила < > & "кавычки" и кириллица',
        "emotional_conflict": "Первая строка\nВторая строка",
        "relationship_pattern": "• первый пункт\n• второй пункт",
        "financial_block": "",
        "karmic_tail_analysis": "<img src=x onerror=alert(1)>",
        "strengths": "Сила\n• первый пункт\n• второй пункт",
    }


def _render_report_pair() -> tuple[str, str]:
    analysis = _analysis()
    mini_html = ReportService.generate_html_report(
        {"analysis": analysis, "matrix": _matrix_data()},
        template_name="mini_report.html",
    )
    full_data = ReportService._build_v2_report_data(
        matrix_data=_matrix_data(),
        analysis=analysis,
        kitchen_analysis=None,
        user_name="<script>alert(1)</script>",
        archetype_number=1,
        archetype_name="Маг",
        token="security-rendering-test",
    )
    full_html = ReportService.generate_html_report(
        full_data,
        template_name="full_report_v2.html",
    )
    return mini_html, full_html


def test_report_html_autoescapes_user_and_ai_content() -> None:
    mini_html, full_html = _render_report_pair()

    assert ReportService._env().autoescape("report.html") is True
    assert ReportService._env().autoescape("report.txt") is False
    for html in (mini_html, full_html):
        assert "<img src=x onerror=alert(1)>" not in html
        assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "Сила &lt; &gt; &amp; &#34;кавычки&#34; и кириллица" in mini_html
    assert "<script>alert(1)</script>" not in full_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in full_html
    assert '<p class="report-text">' in full_html
    assert 'class="cover-archetype report-plain-text"' in mini_html
    assert '<p class="report-plain-text">Первая строка\nВторая строка</p>' in mini_html
    assert 'class="who user-value"' in full_html
    assert 'class="v user-value"' in full_html


@pytest.mark.asyncio
@pytest.mark.parametrize("report_index", [0, 1], ids=["mini", "full"])
async def test_report_pdf_is_generated(
    report_index: int,
) -> None:
    html = _render_report_pair()[report_index]
    document = HTML(string=html).render()
    page_texts = [
        "".join(
            getattr(box, "text", "")
            for box in page._page_box.descendants()
            if getattr(box, "text", None)
        )
        for page in document.pages
    ]
    pdf = await ReportService.generate_pdf(html)

    assert pdf.startswith(b"%PDF")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert len(pdf) > 10_000
    assert all(text.strip() for text in page_texts)


def test_telegram_helper_escapes_dynamic_text_but_keeps_static_markup() -> None:
    name = "Аня <admin> & друзья"
    greeting = greeting_text_free(name, "Маг <root>")
    matrix = mini_analysis_text(
        "Маг",
        1,
        "<b>AI tag</b>",
        "<script>alert(1)</script>",
        "эмоции & чувства",
        "паттерн",
        "блок",
    )

    assert escape_telegram_html(None) == ""
    assert escape_telegram_html(name) == "Аня &lt;admin&gt; &amp; друзья"
    assert "<b>💬 Чат с NURA</b>" in greeting
    assert "Аня &lt;admin&gt; &amp; друзья" in greeting
    assert "<root>" not in greeting
    assert "&lt;b&gt;AI tag&lt;/b&gt;" in matrix
    assert "<script>" not in matrix
    assert format_bot_text("<broken>& text") == "&lt;broken&gt;&amp; text"
    chunks = split_telegram_html_text(
        "<" * TELEGRAM_MESSAGE_MAX_LENGTH,
        max_length=TELEGRAM_MESSAGE_MAX_LENGTH,
    )
    assert len(chunks) > 1
    assert all(len(chunk) <= TELEGRAM_MESSAGE_MAX_LENGTH for chunk in chunks)
    assert all(not chunk.endswith(("&", "&l", "&lt")) for chunk in chunks)
    assert "".join(chunks) == "&lt;" * TELEGRAM_MESSAGE_MAX_LENGTH


def test_telegram_splitter_balances_trusted_tags_across_chunks() -> None:
    chunks = split_telegram_html_message("<b>" + "x" * 20 + "</b>", max_length=16)

    assert chunks == ["<b>xxxxxxxxx</b>", "<b>xxxxxxxxx</b>", "<b>xx</b>"]
    assert all(len(chunk) <= 16 for chunk in chunks)


def _telegram_message(text: str) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.from_user = SimpleNamespace(id=42, first_name="Аня")
    message.chat = SimpleNamespace(id=42)
    message.bot.send_chat_action = AsyncMock()
    message.answer = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_chat_rejects_over_limit_before_ai_history_and_quota() -> None:
    message = _telegram_message("x" * (TELEGRAM_INPUT_MAX_LENGTH + 1))
    state = AsyncMock()

    with patch(
        "bot.handlers.chat.AIService.chat_response", new_callable=AsyncMock
    ) as ai:
        await chat_message(message, state)

    ai.assert_not_awaited()
    state.get_data.assert_not_awaited()
    state.update_data.assert_not_awaited()
    message.bot.send_chat_action.assert_not_awaited()
    assert "Максимум" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_chat_accepts_limit_and_escapes_ai_response() -> None:
    message = _telegram_message("x" * TELEGRAM_INPUT_MAX_LENGTH)
    state = AsyncMock()
    state.get_data.return_value = {
        "chat_history": [],
        "matrix_data": {"center": 1},
        "user_name": "Аня",
        "chat_messages_left": -1,
    }

    with patch(
        "bot.handlers.chat.AIService.chat_response",
        new=AsyncMock(return_value="<broken>& ответ"),
    ) as ai:
        await chat_message(message, state)

    ai.assert_awaited_once()
    assert ai.await_args.kwargs["user_message"] == message.text
    assert message.answer.await_args.args[0] == "&lt;broken&gt;&amp; ответ"


@pytest.mark.asyncio
async def test_chat_whitespace_keeps_existing_text_only_ux() -> None:
    message = _telegram_message("   ")
    state = AsyncMock()

    with patch(
        "bot.handlers.chat.AIService.chat_response", new_callable=AsyncMock
    ) as ai:
        await chat_message(message, state)

    ai.assert_not_awaited()
    state.get_data.assert_not_awaited()
    message.answer.assert_awaited_once_with("Напиши сообщение текстом.")


@pytest.mark.asyncio
async def test_tarot_rejects_over_limit_before_state_and_ai() -> None:
    message = _telegram_message("x" * (TELEGRAM_INPUT_MAX_LENGTH + 1))
    state = AsyncMock()

    with patch(
        "bot.handlers.tarot.generate_tarot_text", new_callable=AsyncMock
    ) as ai:
        await handle_question_input(message, state)

    ai.assert_not_awaited()
    state.get_data.assert_not_awaited()
    state.clear.assert_not_awaited()
    assert "Максимум" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_tarot_accepts_limit_and_splits_escaped_question() -> None:
    message = _telegram_message("<" * TELEGRAM_INPUT_MAX_LENGTH)
    state = AsyncMock()
    state.get_data.return_value = {"spread_type": "yes_no"}
    loading = AsyncMock()
    loading.__aenter__ = AsyncMock()
    loading.__aexit__ = AsyncMock()

    with (
        patch("bot.handlers.tarot._daily_arcana_number", return_value=5),
        patch(
            "bot.handlers.tarot.AIService._load_prompt",
            return_value="{question} {arcana_number} {arcana_name} {yes_or_no}",
        ),
        patch(
            "bot.handlers.tarot.generate_tarot_text",
            new=AsyncMock(return_value="<broken>& ответ"),
        ) as ai,
        patch("bot.handlers.tarot.animated_loading", return_value=loading),
        patch("bot.handlers.tarot.tarot_result_keyboard", return_value=MagicMock()),
    ):
        await handle_question_input(message, state)

    ai.assert_awaited_once()
    chunks = [call.args[0] for call in message.answer.await_args_list]
    assert len(chunks) > 1
    assert all(len(chunk) <= TELEGRAM_MESSAGE_MAX_LENGTH for chunk in chunks)
    rendered = "".join(chunks)
    assert "<" * TELEGRAM_INPUT_MAX_LENGTH not in rendered
    assert "&lt;" * TELEGRAM_INPUT_MAX_LENGTH in rendered
    assert "&lt;broken&gt;&amp; ответ" in rendered
    state.clear.assert_awaited_once()
