import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.services.mini_report_application import MiniReportResultKind
from core.tasks import _process_mini_report, _send_daily_card_async


@pytest.mark.asyncio
class TestMiniReport:
    async def test_celery_adapter_uses_application_service(self) -> None:
        user_id = str(uuid.uuid4())
        report = MagicMock(id=uuid.uuid4(), token="token-abc")
        result = MagicMock(
            kind=MiniReportResultKind.COMPLETED_NEW,
            report_id=report.id,
            content={"main_archetype": "Сила"},
        )
        with (
            patch("core.tasks.ReportRepository") as report_repository,
            patch("core.tasks.MiniReportApplicationService") as application_service,
        ):
            report_repository.return_value.get = AsyncMock(return_value=report)
            application_service.return_value.generate = AsyncMock(return_value=result)
            payload = await _process_mini_report(user_id, "01.01.2000", "Иван")

        assert payload["kind"] == MiniReportResultKind.COMPLETED_NEW
        assert payload["token"] == "token-abc"
        application_service.return_value.generate.assert_awaited_once()

    async def test_celery_adapter_does_not_notify_without_new_report(self) -> None:
        user_id = str(uuid.uuid4())
        result = MagicMock(
            kind=MiniReportResultKind.COMPLETED_REUSED,
            report_id=uuid.uuid4(),
            content={"main_archetype": "Сила"},
        )
        with (
            patch("core.tasks.ReportRepository") as report_repository,
            patch("core.tasks.MiniReportApplicationService") as application_service,
        ):
            report_repository.return_value.get = AsyncMock(return_value=MagicMock(token="token"))
            application_service.return_value.generate = AsyncMock(return_value=result)
            payload = await _process_mini_report(user_id, "01.01.2000", "Иван")

        assert payload["kind"] == MiniReportResultKind.COMPLETED_REUSED


@pytest.mark.asyncio
class TestDailyInsights:
    async def test_subscriber_gets_ai_insight(self) -> None:
        mock_user = MagicMock(
            id=uuid.uuid4(), telegram_id=123456789, first_name="Test", username="testuser",
            birth_date="01.01.2000", main_archetype="Маг", main_archetype_number=1,
            subscription_status="premium",
        )
        with (
            patch("core.tasks.get_async_sessionmaker") as mock_get_session,
            patch("core.tasks._send_message", new_callable=AsyncMock, return_value=True) as mock_send,
            patch("core.tasks.AIService.generate_tarot_daily_card", new_callable=AsyncMock, return_value="AI insight") as mock_ai,
        ):
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [mock_user]
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_get_session.return_value = MagicMock(return_value=mock_session)
            result = await _send_daily_card_async()

        assert result == {"sent": 1, "failed": 0, "total": 1}
        mock_ai.assert_awaited_once()
        mock_send.assert_awaited_once()

    async def test_failed_delivery_is_counted(self) -> None:
        mock_user = MagicMock(
            id=uuid.uuid4(), telegram_id=123456789, first_name="Test", username="testuser",
            birth_date="01.01.2000", main_archetype="Маг", main_archetype_number=1,
            subscription_status="premium",
        )
        with (
            patch("core.tasks.get_async_sessionmaker") as mock_get_session,
            patch("core.tasks._send_message", new_callable=AsyncMock, return_value=False),
            patch("core.tasks.AIService.generate_tarot_daily_card", new_callable=AsyncMock, return_value="AI insight"),
        ):
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [mock_user]
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_get_session.return_value = MagicMock(return_value=mock_session)
            result = await _send_daily_card_async()

        assert result == {"sent": 0, "failed": 1, "total": 1}
