import logging

from core.services.ai import AIService
from core.services.verifier import ContentVerifier

logger = logging.getLogger(__name__)

MAX_RETRIES = 1


async def generate_tarot_text(
    messages: list[dict],
    api_params: dict | None = None,
    timeout: float = 30.0,
    max_words: int | None = None,
    min_words: int = 30,
    max_retries: int = MAX_RETRIES,
    use_cache: bool = False,
    cache_ttl: int = 86400,
    user_name: str = "",
) -> str:
    for attempt in range(max_retries + 1):
        try:
            text = await AIService.chat(
                messages,
                api_params=api_params,
                timeout=timeout,
                use_cache=use_cache,
                cache_ttl=cache_ttl,
            )
        except Exception:
            if attempt >= max_retries:
                raise
            continue

        text = text.strip().strip('"')

        result = ContentVerifier.verify_text(
            text,
            min_words=min_words,
            max_words=max_words,
            check_banned=True,
            check_tone=True,
            user_name=user_name,
        )

        if result.passed:
            if attempt > 0:
                logger.info("tarot_loop passed on attempt %d", attempt + 1)
            return text

        logger.warning(
            "tarot_loop attempt %d/%d failed: %d issue(s)",
            attempt + 1, max_retries + 1, len(result.issues),
        )

    logger.error(
        "tarot_loop exhausted after %d attempts — returning last result",
        max_retries + 1,
    )
    return text
