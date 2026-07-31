from dataclasses import dataclass
from typing import Protocol

from core.services.ai import AIService
from core.services.matrix import MatrixService
from core.services.prompt_governance import ResolvedPromptBundle


@dataclass(frozen=True)
class MatrixReportGeneratorResult:
    matrix_data: dict
    ai_analysis: dict
    kitchen_analysis: dict | None
    generation_details: dict | None = None


class MatrixReportGenerator(Protocol):
    async def generate(
        self,
        *,
        birth_date: str,
        user_name: str,
        report_token: str,
        prompt_bundle: ResolvedPromptBundle,
    ) -> MatrixReportGeneratorResult: ...


class MatrixReportGenerationError(Exception):
    def __init__(self, error_category: str):
        self.error_category = error_category
        super().__init__(error_category)


class DefaultMatrixReportGenerator:
    """Production adapter — pure computation, no DB persistence."""

    async def generate(
        self,
        *,
        birth_date: str,
        user_name: str,
        report_token: str,
        prompt_bundle: ResolvedPromptBundle,
    ) -> MatrixReportGeneratorResult:
        from asyncio import gather

        from core.loop_specs.report_loop import generate_governed_full_report_with_loop

        matrix = MatrixService.calculate(birth_date)
        matrix_dict = matrix.model_dump()

        analysis_task = generate_governed_full_report_with_loop(
            birth_date,
            matrix,
            name=user_name,
            bundle=prompt_bundle,
        )
        kitchen_task = AIService.generate_kitchen_report_with_metadata(
            birth_date,
            matrix,
            bundle=prompt_bundle,
        )
        analysis_result, kitchen_result = await gather(analysis_task, kitchen_task)

        return MatrixReportGeneratorResult(
            matrix_data=matrix_dict,
            ai_analysis=dict(analysis_result.content),
            kitchen_analysis=dict(kitchen_result.content),
            generation_details={
                "provider": analysis_result.provider,
                "model": analysis_result.model,
                "generation_source": analysis_result.generation_source,
                "components": {
                    "full_report": {
                        "provider": analysis_result.provider,
                        "model": analysis_result.model,
                        "generation_source": analysis_result.generation_source,
                    },
                    "kitchen_report": {
                        "provider": kitchen_result.provider,
                        "model": kitchen_result.model,
                        "generation_source": kitchen_result.generation_source,
                    },
                },
            },
        )
