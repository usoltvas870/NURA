import uuid
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from core.models import ReportType
from core.tasks import _process_mini_report, _send_daily_card_async


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


@pytest.mark.asyncio
class TestDailyInsights:
    async def test_subscriber_gets_ai_insight(self):
        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()
        mock_user.telegram_id = 123456789
        mock_user.first_name = "Test"
        mock_user.username = "testuser"
        mock_user.birth_date = "01.01.2000"
        mock_user.main_archetype = "Маг"
        mock_user.main_archetype_number = 1
        mock_user.subscription_status = "premium"

        mock_insight = MagicMock()
        mock_insight.insight = "AI insight for you today"

        with (
            patch("core.tasks.get_async_sessionmaker") as mock_get_session,
            patch("core.tasks._send_message", new_callable=AsyncMock) as mock_send,
            patch(
                "core.tasks.AIService.generate_daily_insight",
                new_callable=AsyncMock,
            ) as mock_ai,
        ):
            mock_ai.return_value = mock_insight
            mock_send.return_value = True

            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [mock_user]
            mock_session.execute = AsyncMock(return_value=mock_result)

            mock_session_factory = MagicMock()
            mock_session_factory.return_value = mock_session
            mock_get_session.return_value = mock_session_factory

            result = await _send_daily_card_async()

        assert result["sent"] == 1
        assert result["total"] == 1
        mock_ai.assert_awaited_once()

    async def test_blocks_user_on_failure(self):
        mock_user = MagicMock()
        mock_user.id = uuid.uuid4()
        mock_user.telegram_id = 123456789
        mock_user.first_name = "Test"
        mock_user.birth_date = "01.01.2000"
        mock_user.main_archetype = "Маг"
        mock_user.main_archetype_number = 1
        mock_user.subscription_status = "premium"

        mock_insight = MagicMock()
        mock_insight.insight = "Fallback insight"

        with (
            patch("core.tasks.get_async_sessionmaker") as mock_get_session,
            patch("core.tasks._send_message", new_callable=AsyncMock) as mock_send,
            patch(
                "core.tasks.AIService.generate_daily_insight",
                new_callable=AsyncMock,
            ) as mock_ai,
        ):
            mock_ai.return_value = mock_insight
            mock_send.return_value = False

            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()

            db_session = MagicMock()
            db_session.__aenter__ = AsyncMock(return_value=db_session)
            db_session.__aexit__ = AsyncMock()
            db_user = MagicMock()
            db_session.get = AsyncMock(return_value=db_user)

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [mock_user]

            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session_factory = MagicMock()
            mock_session_factory.side_effect = [mock_session, db_session]
            mock_get_session.return_value = mock_session_factory

            result = await _send_daily_card_async()

        assert result["blocked"] == 1
        assert db_user.subscription_status == "blocked"
