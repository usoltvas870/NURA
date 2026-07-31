import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from core.config import settings
from core.services.ai import AIService
from core.services.sandbox_ai_budget import (
    SandboxAIBudgetError,
    reserve_sandbox_ai_call,
)


class _AtomicFakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.lock = asyncio.Lock()

    async def eval(self, _script, _keys, calls_key, tokens_key, *args):
        max_calls, max_tokens, requested_tokens = map(int, args)
        async with self.lock:
            calls = self.values.get(calls_key, 0)
            tokens = self.values.get(tokens_key, 0)
            if calls >= max_calls or tokens + requested_tokens > max_tokens:
                return [0, calls, tokens]
            calls += 1
            tokens += requested_tokens
            self.values[calls_key] = calls
            self.values[tokens_key] = tokens
            return [1, calls, tokens]


@pytest.fixture
def sandbox_ai_settings(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "sandbox")
    monkeypatch.setattr(settings, "deepseek_base_url", "https://ai.sandbox.test/v1")
    monkeypatch.setattr(
        settings, "sandbox_ai_allowed_base_url", "https://ai.sandbox.test/v1"
    )
    monkeypatch.setattr(settings, "deepseek_model", "sandbox-model")
    monkeypatch.setattr(settings, "sandbox_ai_allowed_model", "sandbox-model")
    monkeypatch.setattr(settings, "sandbox_ai_max_external_calls", 2)
    monkeypatch.setattr(settings, "sandbox_ai_max_total_tokens", 200)
    monkeypatch.setattr(settings, "sandbox_redis_key_prefix", "sandbox:nura-sbx-ai:")


@pytest.mark.asyncio
async def test_atomic_shared_budget_fails_closed_at_limit(
    sandbox_ai_settings,
) -> None:
    redis = _AtomicFakeRedis()
    with patch(
        "core.services.sandbox_ai_budget.get_redis",
        return_value=redis,
    ):
        results = await asyncio.gather(
            *(
                reserve_sandbox_ai_call(model="sandbox-model", max_tokens=100)
                for _ in range(3)
            ),
            return_exceptions=True,
        )

    assert sum(result is None for result in results) == 2
    errors = [result for result in results if isinstance(result, Exception)]
    assert len(errors) == 1
    assert isinstance(errors[0], SandboxAIBudgetError)
    assert errors[0].code == "sandbox_ai_budget_exhausted"


@pytest.mark.asyncio
async def test_wrong_base_or_model_is_rejected_before_redis(
    sandbox_ai_settings,
    monkeypatch,
) -> None:
    redis = AsyncMock()
    with patch("core.services.sandbox_ai_budget.get_redis", return_value=redis):
        monkeypatch.setattr(settings, "deepseek_base_url", "https://api.deepseek.com/v1")
        with pytest.raises(SandboxAIBudgetError, match="base_url_not_allowed"):
            await reserve_sandbox_ai_call(model="sandbox-model", max_tokens=100)

        monkeypatch.setattr(settings, "deepseek_base_url", "https://api.deepseek.com/v2")
        monkeypatch.setattr(
            settings,
            "sandbox_ai_allowed_base_url",
            "https://api.deepseek.com/v2",
        )
        with pytest.raises(SandboxAIBudgetError, match="base_url_not_allowed"):
            await reserve_sandbox_ai_call(model="sandbox-model", max_tokens=100)

        monkeypatch.setattr(
            settings,
            "deepseek_base_url",
            "https://api.deepseek.com./v1",
        )
        monkeypatch.setattr(
            settings,
            "sandbox_ai_allowed_base_url",
            "https://api.deepseek.com./v1",
        )
        with pytest.raises(SandboxAIBudgetError, match="base_url_not_allowed"):
            await reserve_sandbox_ai_call(model="sandbox-model", max_tokens=100)

        monkeypatch.setattr(settings, "deepseek_base_url", "https://ai.sandbox.test/v1")
        monkeypatch.setattr(
            settings,
            "sandbox_ai_allowed_base_url",
            "https://ai.sandbox.test/v1",
        )
        with pytest.raises(SandboxAIBudgetError, match="model_not_allowed"):
            await reserve_sandbox_ai_call(model="production-model", max_tokens=100)

    redis.eval.assert_not_awaited()


@pytest.mark.asyncio
async def test_unavailable_budget_store_fails_closed(
    sandbox_ai_settings,
) -> None:
    redis = AsyncMock()
    redis.eval.side_effect = ConnectionError("synthetic Redis outage")

    with patch("core.services.sandbox_ai_budget.get_redis", return_value=redis):
        with pytest.raises(SandboxAIBudgetError, match="budget_unavailable"):
            await reserve_sandbox_ai_call(model="sandbox-model", max_tokens=100)


@pytest.mark.asyncio
async def test_cache_hit_does_not_reserve_external_call() -> None:
    payload = json.dumps(
        {
            "contract": "nura-ai-cache-v1",
            "content": "cached",
            "provider": "deepseek",
            "model": settings.deepseek_model,
            "usage": {"total_tokens": 7},
        }
    )
    cache = AsyncMock()
    cache.get.return_value = payload

    with patch("core.database.get_redis", return_value=cache), patch(
        "core.services.ai.reserve_sandbox_ai_call",
        new_callable=AsyncMock,
    ) as reserve:
        result = await AIService.chat_with_metadata(
            [{"role": "user", "content": "cache fixture"}],
            use_cache=True,
        )

    assert result.cached is True
    assert result.content == "cached"
    reserve.assert_not_awaited()


class _FailingClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **_kwargs):
        request = httpx.Request("POST", url)
        raise httpx.ConnectError("synthetic provider failure", request=request)


@pytest.mark.asyncio
async def test_retries_and_fallback_attempts_each_reserve_budget(caplog) -> None:
    secret_prompt = "prompt-content-must-not-be-logged"
    with patch("core.services.ai.httpx.AsyncClient", return_value=_FailingClient()), patch(
        "core.services.ai.reserve_sandbox_ai_call",
        new_callable=AsyncMock,
    ) as reserve, patch(
        "core.services.ai.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        with pytest.raises(httpx.ConnectError):
            await AIService.chat_with_metadata(
                [{"role": "user", "content": secret_prompt}],
                api_params={"max_tokens": 100},
                max_retries=1,
                use_cache=False,
            )

    assert reserve.await_count == 3
    assert secret_prompt not in caplog.text
