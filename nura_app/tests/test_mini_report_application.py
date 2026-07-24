import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models import MiniReportGenerationState
from core.services.mini_report_application import (
    GuestMiniReportSubject,
    MiniReportApplicationService,
    MiniReportRequest,
    MiniReportResultKind,
    UserMiniReportSubject,
)


def _generation(status: str, report_id: uuid.UUID | None = None) -> MagicMock:
    generation = MagicMock()
    generation.id = uuid.uuid4()
    generation.status = status
    generation.report_id = report_id
    generation.error_code = None
    return generation


@pytest.mark.asyncio
async def test_invalid_input_does_not_touch_generation_or_provider() -> None:
    generations = MagicMock()
    service = MiniReportApplicationService(generations, MagicMock(), MagicMock())

    result = await service.generate(
        MiniReportRequest(
            owner=UserMiniReportSubject(uuid.uuid4()), name="   ", birth_date="01.01.2000"
        )
    )

    assert result.kind == MiniReportResultKind.INVALID_INPUT
    generations.get_or_create_generation.assert_not_called()


@pytest.mark.asyncio
async def test_missing_owner_is_rejected_before_generation() -> None:
    generations = MagicMock()
    service = MiniReportApplicationService(generations, MagicMock(), MagicMock())

    result = await service.generate(
        MiniReportRequest(owner=None, name="Иван", birth_date="01.01.2000")  # type: ignore[arg-type]
    )

    assert result.kind == MiniReportResultKind.INVALID_INPUT
    assert result.error_code == "invalid_owner"
    generations.get_or_create_generation.assert_not_called()


@pytest.mark.asyncio
async def test_user_generation_persists_once_and_marks_completed() -> None:
    user_id = uuid.uuid4()
    generation = _generation(MiniReportGenerationState.PENDING)
    generations = MagicMock()
    generations.get_or_create_generation = AsyncMock(return_value=generation)
    generations.claim_generation = AsyncMock(return_value=1)
    generations.finalize_result = AsyncMock(return_value=uuid.uuid4())
    report = MagicMock(id=uuid.uuid4())
    reports = MagicMock()
    reports.create = AsyncMock(return_value=report)
    guests = MagicMock()
    matrix = MagicMock(center=8)
    matrix.model_dump.return_value = {"center": 8}
    analysis = {"main_archetype": "Сила"}
    service = MiniReportApplicationService(generations, reports, guests)

    with (
        patch("core.services.mini_report_application.MatrixService.calculate", return_value=matrix),
        patch(
            "core.services.mini_report_application.AIService.generate_mini_analysis",
            new_callable=AsyncMock,
            return_value=analysis,
        ),
        patch("core.services.mini_report_application.ReportService.generate_token", return_value="token"),
    ):
        result = await service.generate(
            MiniReportRequest(
                owner=UserMiniReportSubject(user_id), name=" ИВАН ", birth_date="1/1/2000"
            )
        )

    assert result.kind == MiniReportResultKind.COMPLETED_NEW
    assert result.report_id is not None
    reports.create.assert_not_called()
    generations.finalize_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_completed_guest_result_is_reused_without_provider_call() -> None:
    guest_id = uuid.uuid4()
    generation = _generation(MiniReportGenerationState.COMPLETED)
    generations = MagicMock()
    generations.get_or_create_generation = AsyncMock(return_value=generation)
    guest = MagicMock(report_data={
        "main_archetype": "Сила",
        "core_strength": "Опора",
        "emotional_conflict": "Напряжение",
        "relationship_pattern": "Диалог",
        "financial_block": "Страх",
        "matrix_data": {"center": 8},
    })
    guests = MagicMock()
    guests.get = AsyncMock(return_value=guest)
    service = MiniReportApplicationService(generations, MagicMock(), guests)

    result = await service.generate(
        MiniReportRequest(
            owner=GuestMiniReportSubject(guest_id), name="Иван", birth_date="01.01.2000"
        )
    )

    assert result.kind == MiniReportResultKind.COMPLETED_REUSED
    assert result.content is not None
    assert result.content["main_archetype"] == "Сила"
    generations.claim_generation.assert_not_called()
