"""Atomic, Redis-backed external AI budget for APP_ENV=sandbox."""

from __future__ import annotations

from urllib.parse import urlsplit

from core.config import Settings, settings
from core.database import get_redis


_RESERVE_SCRIPT = """
local calls = tonumber(redis.call('GET', KEYS[1]) or '0')
local tokens = tonumber(redis.call('GET', KEYS[2]) or '0')
local max_calls = tonumber(ARGV[1])
local max_tokens = tonumber(ARGV[2])
local requested_tokens = tonumber(ARGV[3])
if calls >= max_calls or tokens + requested_tokens > max_tokens then
  return {0, calls, tokens}
end
calls = redis.call('INCR', KEYS[1])
tokens = redis.call('INCRBY', KEYS[2], requested_tokens)
return {1, calls, tokens}
"""
_PRODUCTION_AI_HOSTNAMES = frozenset({"api.deepseek.com"})


class SandboxAIBudgetError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


async def reserve_sandbox_ai_call(
    *,
    model: str,
    max_tokens: int,
    current_settings: Settings = settings,
) -> None:
    """Reserve one provider attempt and its worst-case completion tokens."""

    if not current_settings.is_sandbox:
        return
    try:
        configured_hostname = (
            urlsplit(current_settings.deepseek_base_url).hostname or ""
        ).casefold()
    except ValueError as exc:
        raise SandboxAIBudgetError("sandbox_ai_base_url_not_allowed") from exc
    if (
        current_settings.deepseek_base_url.rstrip("/")
        != str(current_settings.sandbox_ai_allowed_base_url).rstrip("/")
        or configured_hostname.endswith(".")
        or configured_hostname.rstrip(".")
        in _PRODUCTION_AI_HOSTNAMES
    ):
        raise SandboxAIBudgetError("sandbox_ai_base_url_not_allowed")
    if (
        model != current_settings.deepseek_model
        or model != current_settings.sandbox_ai_allowed_model
    ):
        raise SandboxAIBudgetError("sandbox_ai_model_not_allowed")
    if not isinstance(max_tokens, int) or max_tokens <= 0:
        raise SandboxAIBudgetError("sandbox_ai_token_reservation_invalid")
    prefix = current_settings.sandbox_redis_key_prefix
    if not prefix:
        raise SandboxAIBudgetError("sandbox_ai_redis_prefix_required")
    try:
        result = await get_redis().eval(
            _RESERVE_SCRIPT,
            2,
            f"{prefix}ai:external_calls",
            f"{prefix}ai:reserved_tokens",
            current_settings.sandbox_ai_max_external_calls,
            current_settings.sandbox_ai_max_total_tokens,
            max_tokens,
        )
    except Exception as exc:
        raise SandboxAIBudgetError("sandbox_ai_budget_unavailable") from exc
    if (
        not isinstance(result, (list, tuple))
        or not result
        or int(result[0]) != 1
    ):
        raise SandboxAIBudgetError("sandbox_ai_budget_exhausted")
