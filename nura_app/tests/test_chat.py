import pytest
from unittest.mock import AsyncMock, patch

from core.fallbacks import FALLBACK_CHAT
from core.services.ai import (
    AICompletionResult,
    AIService,
)
from core.services.prompt_governance import resolve_active_bundle


class TestChatRestrictions:

    def test_template_contains_refusal_instruction(self):
        template = resolve_active_bundle("chat.free").content("system.txt")
        assert "не анализируй другого человека" in template.lower()
        assert "не пересчитывай Матрицу" in template

    def test_build_chat_prompt_contains_refusal(self, sample_matrix):
        bundle = resolve_active_bundle("chat.free")
        prompt = AIService._governed_chat_system(bundle, sample_matrix, "Тест")
        assert "не анализируй другого человека" in prompt.lower()
        assert "не пересчитывай Матрицу" in prompt

    @pytest.mark.asyncio
    async def test_chat_response_calls_with_correct_system_prompt(self, sample_matrix):
        with patch.object(AIService, "chat_with_metadata", new_callable=AsyncMock) as mock:
            mock.return_value = AICompletionResult(
                "Я знаю только тебя и твою матрицу.", "deepseek", "deepseek-chat", {}, 1, False
            )
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
        assert "не анализируй другого человека" in system_content.lower()

    @pytest.mark.asyncio
    async def test_chat_refuses_to_analyze_other_person(self, sample_matrix):
        with patch.object(AIService, "chat_with_metadata", new_callable=AsyncMock) as mock:
            mock.return_value = AICompletionResult(
                "Я знаю только тебя и твою матрицу. "
                "Хочешь разобраться, как твой архетип влияет на отношения с другими?",
                "deepseek", "deepseek-chat", {}, 1, False,
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
        with patch.object(AIService, "chat_with_metadata", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("API error")
            result = await AIService.chat_response(
                user_message="привет",
                chat_history=[],
                matrix_data=sample_matrix,
                user_name="Тест",
            )
        assert result == FALLBACK_CHAT
