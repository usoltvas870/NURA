import logging
from typing import TYPE_CHECKING

from core.fallbacks import FALLBACK_FULL
from core.services.ai import AIService
from core.services.verifier import ContentVerifier

if TYPE_CHECKING:
    from core.schemas import MatrixData

logger = logging.getLogger(__name__)

MAX_SEMANTIC_RETRIES = 2


def _build_retry_prompt(
    original_system: str,
    original_user_a: str,
    original_user_b: str,
    issues: list[str],
) -> str:
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
    report = FALLBACK_FULL

    for attempt in range(MAX_SEMANTIC_RETRIES + 1):
        try:
            report = await AIService.generate_full_report(birth_date, matrix_data, name)
        except Exception as e:
            logger.error("report_loop generate_full_report crashed: %s", e, exc_info=True)
            return FALLBACK_FULL

        md = AIService._to_matrix_data(matrix_data) if isinstance(matrix_data, dict) else matrix_data

        result = ContentVerifier.verify_report(report, matrix_data=md, min_words=50)

        if result.passed:
            if attempt > 0:
                logger.info("report_loop passed on attempt %d", attempt + 1)
            return report

        logger.warning(
            "report_loop attempt %d/%d failed: %d issue(s)",
            attempt + 1, MAX_SEMANTIC_RETRIES + 1, len(result.issues),
        )

        if attempt >= MAX_SEMANTIC_RETRIES:
            break

    logger.error(
        "report_loop exhausted after %d attempts — returning fallback",
        MAX_SEMANTIC_RETRIES + 1,
    )
    return FALLBACK_FULL
