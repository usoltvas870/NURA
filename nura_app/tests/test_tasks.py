import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

import core.celery_async as celery_async
from core.services.mini_report_application import MiniReportResultKind
from core.services.telegram_report_delivery import TelegramDeliveryError
from core.celery_async import _reset_runtime_for_tests
from core.tasks import (
    _process_mini_report,
    _send_daily_card_async,
    deliver_mini_report,
    generate_mini_report,
)


@pytest.fixture(autouse=True)
def reset_celery_runtime_between_task_tests() -> None:
    """Keep task ``.run()`` unit calls from leaking a process-local worker loop."""
    try:
        yield
    finally:
        _reset_runtime_for_tests()


class TestMiniReport:
    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.parametrize(
        "kind",
        [
            MiniReportResultKind.COMPLETED_NEW,
            MiniReportResultKind.COMPLETED_REUSED,
        ],
    )
    def test_generation_task_enqueues_same_idempotent_delivery(self, kind) -> None:
        user_id = str(uuid.uuid4())
        report_id = str(uuid.uuid4())
        generation_id = str(uuid.uuid4())
        with (
            patch(
                "core.tasks._process_mini_report",
                new_callable=AsyncMock,
                return_value={
                    "kind": kind,
                    "report_id": report_id,
                    "generation_id": generation_id,
                },
            ),
            patch("core.tasks.deliver_mini_report.delay") as enqueue,
        ):
            result = generate_mini_report.run(user_id, "01.01.2000", "Иван")

        assert result["kind"] == kind
        enqueue.assert_called_once_with(user_id, report_id, generation_id)

    def test_task_runtime_is_reset_between_task_runs(self) -> None:
        """A direct task unit test must not reserve a worker loop for later modules."""
        assert celery_async._runtime is None

    def test_delivery_task_retries_transient_database_failure(self) -> None:
        operational_error = OperationalError("SELECT", {}, RuntimeError("down"))
        with (
            patch(
                "core.tasks.MiniReportTelegramDeliveryService.deliver",
                new_callable=AsyncMock,
                side_effect=operational_error,
            ),
            patch.object(
                deliver_mini_report,
                "retry",
                side_effect=RuntimeError("retry-called"),
            ) as retry,
        ):
            with pytest.raises(RuntimeError, match="retry-called"):
                deliver_mini_report.run(
                    str(uuid.uuid4()),
                    str(uuid.uuid4()),
                    str(uuid.uuid4()),
                )

        retry.assert_called_once()

    def test_delivery_task_does_not_retry_non_retryable_error(self) -> None:
        with (
            patch(
                "core.tasks.MiniReportTelegramDeliveryService.deliver",
                new_callable=AsyncMock,
                side_effect=TelegramDeliveryError(
                    "telegram_forbidden",
                    retryable=False,
                ),
            ),
            patch.object(deliver_mini_report, "retry") as retry,
        ):
            deliver_mini_report.run(
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                str(uuid.uuid4()),
            )

        retry.assert_not_called()


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
