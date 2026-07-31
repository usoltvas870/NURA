import logging
from typing import TYPE_CHECKING

from core.fallbacks import FALLBACK_FULL
from core.services.ai import AIService, GeneratedContentResult
from core.services.prompt_governance import ResolvedPromptBundle
from core.services.verifier import ContentVerifier

if TYPE_CHECKING:
    from core.schemas import MatrixData

logger = logging.getLogger(__name__)

MAX_SEMANTIC_RETRIES = 2


def _build_retry_prompt(issues: list[str]) -> str:
    issues_text = "\n".join(f"- {iss}" for iss in issues)
    return (
        f"Твой предыдущий ответ не прошёл проверку качества. Вот что нужно исправить:\n\n"
        f"{issues_text}\n\n"
        f"Перегенерируй ответ, исправив каждую из указанных проблем. "
        f"Сохрани строгую структуру JSON. Без markdown-блоков."
    )


async def generate_full_report_with_loop(
    birth_date: str,
    matrix_data: "MatrixData | dict",
    name: str = "пользователь",
) -> dict:
    from core.services.prompt_governance import resolve_active_bundle

    result = await generate_governed_full_report_with_loop(
        birth_date,
        matrix_data,
        name,
        bundle=resolve_active_bundle("report.full"),
    )
    return dict(result.content)


async def generate_governed_full_report_with_loop(
    birth_date: str,
    matrix_data: "MatrixData | dict",
    name: str,
    *,
    bundle: ResolvedPromptBundle,
) -> GeneratedContentResult:
    issues: list[str] | None = None
    last_duration_ms = 0
    md = AIService._to_matrix_data(matrix_data)

    for attempt in range(MAX_SEMANTIC_RETRIES + 1):
        result = await AIService.generate_full_report_with_metadata(
            birth_date,
            md,
            name,
            issues=issues,
            bundle=bundle,
        )
        last_duration_ms += result.duration_ms
        if result.generation_source == "provider" and isinstance(result.content, dict):
            verification = ContentVerifier.verify_report(
                result.content, matrix_data=md, min_words=50
            )
            if verification.passed:
                return GeneratedContentResult(
                    content=result.content,
                    provider=result.provider,
                    model=result.model,
                    usage=result.usage,
                    duration_ms=last_duration_ms,
                    cached=result.cached,
                    generation_source="provider",
                )
            issues = verification.issues
        else:
            issues = ["provider output unavailable"]
        logger.warning(
            "governed report loop attempt %d/%d failed: %d issue(s)",
            attempt + 1,
            MAX_SEMANTIC_RETRIES + 1,
            len(issues),
        )

    logger.error("governed report loop exhausted")
    return GeneratedContentResult(
        content=dict(FALLBACK_FULL),
        provider=None,
        model=None,
        usage={},
        duration_ms=last_duration_ms,
        cached=False,
        generation_source="fallback",
    )
