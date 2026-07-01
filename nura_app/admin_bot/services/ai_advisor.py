import logging
from typing import Any

from core.services.ai import AIService

logger = logging.getLogger(__name__)


class AIAdvisor:
    SYSTEM_PROMPT = (
        "Ты — NURA DevOps Assistant. Анализируй ошибки из Docker-логов "
        "и давай краткие рекомендации (2-3 предложения). "
        "Укажи возможную причину и действие для фикса. "
        "Будь конкретен и практичен."
    )

    async def analyze_errors(self, errors: list[dict[str, Any]]) -> str | None:
        if not errors:
            return None

        log_text = "\n".join(
            f"[{e['container']}] {e['line']}" for e in errors if "container" in e
        )

        if not log_text:
            return None

        prompt = (
            f"Проанализируй следующие ошибки из Docker-логов:\n\n{log_text}\n\n"
            "Для каждой ошибки укажи возможную причину и рекомендуемое действие. "
            "Если ошибки связаны, укажи это."
        )

        try:
            response = await AIService.chat(
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                api_params={"max_tokens": 500, "temperature": 0.3},
            )
            return response.strip()
        except Exception as e:
            logger.exception("AI analysis failed: %s", e)
            return None
