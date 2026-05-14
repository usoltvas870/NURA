import uuid
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from core.models import ReportType
from core.tasks import _process_mini_report


@pytest.mark.asyncio
class TestMiniReport:
    async def test_creates_report(self):
        user_id = str(uuid.uuid4())
        mock_analysis = {
            "main_archetype": "a",
            "core_strength": "b",
            "emotional_conflict": "c",
            "relationship_pattern": "d",
            "financial_block": "e",
        }

        with (
            patch("core.tasks.ReportRepository") as MockRepo,
            patch("core.tasks.UserRepository") as MockUser,
            patch(
                "core.tasks.AIService.generate_mini_analysis",
                new_callable=AsyncMock,
            ) as mock_ai,
            patch(
                "core.tasks.ReportService.generate_token",
                return_value="token-abc",
            ),
        ):
            mock_ai.return_value = mock_analysis

            mock_report = MagicMock()
            mock_report.id = uuid.uuid4()
            mock_report.token = "token-abc"

            repo_instance = MagicMock()
            repo_instance.create = AsyncMock(return_value=mock_report)
            MockRepo.return_value = repo_instance

            user_instance = MagicMock()
            user_instance.update_archetype = AsyncMock()
            MockUser.return_value = user_instance

            result = await _process_mini_report(user_id, "01.01.2000")

        assert result["token"] == "token-abc"
        assert result["analysis"] == mock_analysis
        assert result["archetype"] == {"name": "Сила", "number": 8}

    async def test_saves_to_db(self):
        user_id = str(uuid.uuid4())

        with (
            patch("core.tasks.ReportRepository") as MockRepo,
            patch("core.tasks.UserRepository") as MockUser,
            patch(
                "core.tasks.AIService.generate_mini_analysis",
                new_callable=AsyncMock,
            ) as mock_ai,
            patch(
                "core.tasks.ReportService.generate_token",
                return_value="token-db",
            ),
        ):
            mock_ai.return_value = {"main_archetype": "data"}

            mock_report = MagicMock()
            mock_report.id = uuid.uuid4()
            mock_report.token = "token-db"

            repo_instance = MagicMock()
            repo_instance.create = AsyncMock(return_value=mock_report)
            MockRepo.return_value = repo_instance

            user_instance = MagicMock()
            user_instance.update_archetype = AsyncMock()
            MockUser.return_value = user_instance

            await _process_mini_report(user_id, "01.01.2000")

            repo_instance.create.assert_awaited_once_with(
                user_id=ANY,
                report_type=ReportType.MINI,
                token="token-db",
                matrix_data=ANY,
                ai_analysis={"main_archetype": "data"},
            )
