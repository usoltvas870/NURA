from dataclasses import dataclass
from typing import Protocol

from core.services.ai import AIService
from core.services.matrix import MatrixService


@dataclass(frozen=True)
class MatrixReportGeneratorResult:
    matrix_data: dict
    ai_analysis: dict
    kitchen_analysis: dict | None


class MatrixReportGenerator(Protocol):
    async def generate(
        self, *, birth_date: str, user_name: str, report_token: str
    ) -> MatrixReportGeneratorResult: ...


class MatrixReportGenerationError(Exception):
    def __init__(self, error_category: str):
        self.error_category = error_category
        super().__init__(error_category)


class DefaultMatrixReportGenerator:
    """Production adapter — pure computation, no DB persistence."""

    async def generate(
        self, *, birth_date: str, user_name: str, report_token: str
    ) -> MatrixReportGeneratorResult:
        from asyncio import gather

        from core.loop_specs.report_loop import generate_full_report_with_loop

        matrix = MatrixService.calculate(birth_date)
        matrix_dict = matrix.model_dump()

        analysis_task = generate_full_report_with_loop(birth_date, matrix, name=user_name)
        kitchen_task = AIService.generate_kitchen_report(birth_date, matrix)
        analysis, kitchen_analysis = await gather(analysis_task, kitchen_task)

        return MatrixReportGeneratorResult(
            matrix_data=matrix_dict,
            ai_analysis=analysis,
            kitchen_analysis=kitchen_analysis,
        )
