import pytest
from unittest.mock import AsyncMock, patch

from core.services.ai import AIService, FALLBACK_FULL, FALLBACK_MINI


def _mini_json():
    return (
        '{"main_archetype":"a","core_strength":"b",'
        '"emotional_conflict":"c","relationship_pattern":"d","financial_block":"e"}'
    )


def _full_json():
    return (
        '{"main_archetype":"a","strengths":"b","shadow_side":"c",'
        '"relationship_dynamics":"d","financial_scenario":"e",'
        '"recurring_mistakes":"f","internal_conflicts":"g",'
        '"life_cycles":"h","ai_recommendations":"i"}'
    )


@pytest.mark.asyncio
class TestMiniAnalysis:
    async def test_returns_correct_fields(self, sample_matrix):
        with patch.object(AIService, "chat", new_callable=AsyncMock) as mock:
            mock.return_value = _mini_json()
            result = await AIService.generate_mini_analysis(
                "01.01.2000", sample_matrix
            )
        assert set(result.keys()) == {
            "main_archetype", "core_strength", "emotional_conflict",
            "relationship_pattern", "financial_block",
        }

    async def test_fallback_on_error(self, sample_matrix):
        with patch.object(AIService, "chat", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("API error")
            result = await AIService.generate_mini_analysis(
                "01.01.2000", sample_matrix
            )
        assert result == FALLBACK_MINI


@pytest.mark.asyncio
class TestFullReport:
    async def test_returns_correct_fields(self, sample_matrix):
        with patch.object(AIService, "chat", new_callable=AsyncMock) as mock:
            mock.return_value = _full_json()
            result = await AIService.generate_full_report(
                "01.01.2000", sample_matrix
            )
        assert set(result.keys()) == {
            "main_archetype", "strengths", "shadow_side",
            "relationship_dynamics", "financial_scenario",
            "recurring_mistakes", "internal_conflicts",
            "life_cycles", "ai_recommendations",
        }

    async def test_fallback_on_invalid_json(self, sample_matrix):
        with patch.object(AIService, "chat", new_callable=AsyncMock) as mock:
            mock.return_value = "NOT JSON"
            result = await AIService.generate_full_report(
                "01.01.2000", sample_matrix
            )
        assert result == FALLBACK_FULL
