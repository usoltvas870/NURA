import pytest
from unittest.mock import AsyncMock, patch

from core.services.ai import (
    AIService,
    CHAT_SYSTEM_PROMPT_TEMPLATE,
    FALLBACK_CHAT,
)


class TestChatRestrictions:

    def test_template_contains_refusal_instruction(self):
        assert "проанализировать другого человека" in CHAT_SYSTEM_PROMPT_TEMPLATE
        assert "Не пытаться рассчитать матрицу" in CHAT_SYSTEM_PROMPT_TEMPLATE

    def test_build_chat_prompt_contains_refusal(self, sample_matrix):
        prompt = AIService._build_chat_system_prompt(sample_matrix, "Тест")
        assert "проанализировать другого человека" in prompt
        assert "Не пытаться рассчитать матрицу" in prompt

    @pytest.mark.asyncio
    async def test_chat_response_calls_with_correct_system_prompt(self, sample_matrix):
        with patch.object(AIService, "chat", new_callable=AsyncMock) as mock:
            mock.return_value = "Я знаю только тебя и твою матрицу."
            result = await AIService.chat_response(
                user_message="проанализируй мужа, дата 01.01.1990",
                chat_history=[],
                matrix_data=sample_matrix,
                user_name="Тест",
            )
        assert result == "Я знаю только тебя и твою матрицу."
        # verify system prompt with restriction was sent
        sent_messages = mock.call_args[0][0]
        system_content = sent_messages[0]["content"]
        assert "проанализировать другого человека" in system_content

    @pytest.mark.asyncio
    async def test_chat_refuses_to_analyze_other_person(self, sample_matrix):
        with patch.object(AIService, "chat", new_callable=AsyncMock) as mock:
            mock.return_value = (
                "Я знаю только тебя и твою матрицу. "
                "Хочешь разобраться, как твой архетип влияет на отношения с другими?"
            )
            result = await AIService.chat_response(
                user_message="проанализируй мужа, дата 01.01.1990",
                chat_history=[],
                matrix_data=sample_matrix,
                user_name="Тест",
            )
        assert "только тебя" in result
        assert "матрицу" in result

    @pytest.mark.asyncio
    async def test_chat_response_fallback_on_error(self, sample_matrix):
        with patch.object(AIService, "chat", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("API error")
            result = await AIService.chat_response(
                user_message="привет",
                chat_history=[],
                matrix_data=sample_matrix,
                user_name="Тест",
            )
        assert result == FALLBACK_CHAT
