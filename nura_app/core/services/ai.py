import asyncio
import hashlib
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from core.config import settings
from core.fallbacks import (
    CHAT_PARAMS,
    DEFAULT_PARAMS,
    FALLBACK_CHAT,
    FALLBACK_COMPATIBILITY,
    FALLBACK_FULL,
    FALLBACK_KITCHEN,
    FALLBACK_MINI,
    FALLBACK_TAROT_QUESTION,
    FALLBACK_TAROT_SPREAD,
    FULL_REPORT_PARAMS,
    TAROT_QUESTION_MODEL,
    TAROT_SPREAD_MODEL,
)
from core.schemas import (
    CompatibilityFullResult,
    DailyInsightResult,
    FullReportResult,
    KitchenReportResult,
    MiniAnalysisResult,
)
from core.services.prompt_governance import ResolvedPromptBundle, resolve_active_bundle

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from core.models import User
    from core.schemas import MatrixData

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_SYSTEM_PROMPT_CACHE: str | None = None
_CHAT_SYSTEM_PROMPT_TEMPLATE_CACHE: str | None = None


@dataclass(frozen=True)
class AICompletionResult:
    content: str
    provider: str
    model: str
    usage: dict[str, int]
    duration_ms: int
    cached: bool
    generation_source: str = "provider"


@dataclass(frozen=True)
class GeneratedContentResult:
    content: dict | str
    provider: str | None
    model: str | None
    usage: dict[str, int]
    duration_ms: int
    cached: bool
    generation_source: str


class AIService:
    @staticmethod
    def _load_prompt(name: str) -> str:
        path = PROMPTS_DIR / name
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    @staticmethod
    def _cache_key(
        messages: list[dict],
        model: str,
        params: dict,
        cache_namespace: str = "",
    ) -> str:
        raw = json.dumps(
            {
                "cache_namespace": cache_namespace,
                "m": messages,
                "model": model,
                "p": params,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return f"ai:{hashlib.md5(raw.encode()).hexdigest()}"

    @staticmethod
    def _make_retry_callback(
        system_prompt: str,
        user_content: str,
        api_params: dict | None = None,
    ) -> "Callable[[str], Coroutine[None, None, str]]":
        async def retry(bad: str) -> str:
            return await AIService.chat(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                    {"role": "assistant", "content": bad},
                    {
                        "role": "user",
                        "content": (
                            "Твой ответ содержит невалидный JSON. "
                            "Исправь и выдай ТОЛЬКО валидный JSON, "
                            "строго по схеме, без markdown-блоков."
                        ),
                    },
                ],
                api_params=api_params,
            )

        return retry

    @staticmethod
    async def chat(
        messages: list[dict],
        api_params: dict | None = None,
        max_retries: int = 3,
        timeout: float = 30.0,
        use_cache: bool = False,
        cache_ttl: int = 86400,
        cache_namespace: str = "",
        method_name: str = "chat",
    ) -> str:
        result = await AIService.chat_with_metadata(
            messages,
            api_params=api_params,
            max_retries=max_retries,
            timeout=timeout,
            use_cache=use_cache,
            cache_ttl=cache_ttl,
            cache_namespace=cache_namespace,
            method_name=method_name,
        )
        return result.content

    @staticmethod
    async def chat_with_metadata(
        messages: list[dict],
        api_params: dict | None = None,
        max_retries: int = 3,
        timeout: float = 30.0,
        use_cache: bool = False,
        cache_ttl: int = 86400,
        cache_namespace: str = "",
        method_name: str = "chat",
    ) -> AICompletionResult:
        params = {**DEFAULT_PARAMS, **(api_params or {})}
        model = params.pop("model", settings.deepseek_model)
        start_time = time.perf_counter()
        cache_hit = False

        if use_cache:
            try:
                cache_key = AIService._cache_key(
                    messages, model, params, cache_namespace
                )
                from core.database import get_redis

                redis = get_redis()
                cached = await redis.get(cache_key)
                if cached is not None:
                    cache_hit = True
                    duration_ms = int((time.perf_counter() - start_time) * 1000)
                    logger.info(
                        "AI chat cache hit: method=%s model=%s duration_ms=%d cached=True status=cached",
                        method_name, model, duration_ms,
                        extra={
                            "method": method_name,
                            "model": model,
                            "tokens": 0,
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                            "duration_ms": duration_ms,
                            "cached": True,
                            "status": "cached",
                        },
                    )
                    raw_cached = (
                        cached.decode("utf-8") if isinstance(cached, bytes) else cached
                    )
                    try:
                        cached_payload = json.loads(raw_cached)
                    except (TypeError, json.JSONDecodeError):
                        cached_payload = None
                    if (
                        isinstance(cached_payload, dict)
                        and cached_payload.get("contract") == "nura-ai-cache-v1"
                        and isinstance(cached_payload.get("content"), str)
                    ):
                        cached_usage = cached_payload.get("usage")
                        usage = cached_usage if isinstance(cached_usage, dict) else {}
                        provider = str(cached_payload.get("provider") or "deepseek")
                        cached_model = str(cached_payload.get("model") or model)
                        return AICompletionResult(
                            content=cached_payload["content"],
                            provider=provider,
                            model=cached_model,
                            usage={key: int(value) for key, value in usage.items()},
                            duration_ms=duration_ms,
                            cached=True,
                        )
                    return AICompletionResult(
                        content=str(raw_cached),
                        provider="deepseek",
                        model=model,
                        usage={},
                        duration_ms=duration_ms,
                        cached=True,
                    )
            except Exception:
                pass

        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": model, "messages": messages, **params}

        last_error = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    r = await client.post(
                        f"{settings.deepseek_base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    r.raise_for_status()
                    data = r.json()
                    content = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})

                    duration_ms = int((time.perf_counter() - start_time) * 1000)
                    logger.info(
                        "AI chat success: method=%s model=%s tokens=%d duration_ms=%d cached=%s status=success",
                        method_name, model, usage.get("total_tokens", 0), duration_ms, cache_hit,
                        extra={
                            "method": method_name,
                            "model": model,
                            "prompt_tokens": usage.get("prompt_tokens", 0),
                            "completion_tokens": usage.get("completion_tokens", 0),
                            "total_tokens": usage.get("total_tokens", 0),
                            "duration_ms": duration_ms,
                            "cached": cache_hit,
                            "status": "success",
                            "attempt": attempt + 1,
                        },
                    )

                    if use_cache:
                        try:
                            redis = get_redis()
                            cache_payload = json.dumps(
                                {
                                    "contract": "nura-ai-cache-v1",
                                    "content": content,
                                    "provider": "deepseek",
                                    "model": model,
                                    "usage": {
                                        "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                                        "completion_tokens": int(usage.get("completion_tokens", 0)),
                                        "total_tokens": int(usage.get("total_tokens", 0)),
                                    },
                                },
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            )
                            await redis.setex(cache_key, cache_ttl, cache_payload)
                        except Exception:
                            pass

                    return AICompletionResult(
                        content=content,
                        provider="deepseek",
                        model=model,
                        usage={
                            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                            "completion_tokens": int(usage.get("completion_tokens", 0)),
                            "total_tokens": int(usage.get("total_tokens", 0)),
                        },
                        duration_ms=duration_ms,
                        cached=False,
                    )
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 * (2 ** attempt))
                continue

        safe_max = params.get("max_tokens", 4000)
        fallback_params = {
            **params,
            "temperature": 0.3,
            "max_tokens": min(safe_max, 500),
        }
        fallback_payload = {"model": model, "messages": messages, **fallback_params}
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    r = await client.post(
                        f"{settings.deepseek_base_url}/chat/completions",
                        headers=headers,
                        json=fallback_payload,
                    )
                    r.raise_for_status()
                    data = r.json()
                    content = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})

                    duration_ms = int((time.perf_counter() - start_time) * 1000)
                    logger.info(
                        "AI chat fallback success: method=%s model=%s tokens=%d duration_ms=%d cached=%s status=fallback",
                        method_name, model, usage.get("total_tokens", 0), duration_ms, cache_hit,
                        extra={
                            "method": method_name,
                            "model": model,
                            "prompt_tokens": usage.get("prompt_tokens", 0),
                            "completion_tokens": usage.get("completion_tokens", 0),
                            "total_tokens": usage.get("total_tokens", 0),
                            "duration_ms": duration_ms,
                            "cached": cache_hit,
                            "status": "fallback",
                            "attempt": attempt + 1,
                        },
                    )
                    return AICompletionResult(
                        content=content,
                        provider="deepseek",
                        model=model,
                        usage={
                            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                            "completion_tokens": int(usage.get("completion_tokens", 0)),
                            "total_tokens": int(usage.get("total_tokens", 0)),
                        },
                        duration_ms=duration_ms,
                        cached=False,
                    )
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError):
                if attempt < 1:
                    await asyncio.sleep(1)
                continue

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error(
            "AI chat failure: method=%s model=%s duration_ms=%d cached=%s status=failure",
            method_name, model, duration_ms, cache_hit,
            extra={
                "method": method_name,
                "model": model,
                "tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "duration_ms": duration_ms,
                "cached": cache_hit,
                "status": "failure",
            },
        )
        raise last_error  # type: ignore[misc]

    @staticmethod
    async def _parse_json_response(
        response: str,
        retry_callback: "Callable[[str], Coroutine[None, None, str]] | None" = None,
    ) -> dict:
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        if retry_callback is not None:
            try:
                corrected = await retry_callback(response)
            except Exception:
                pass
            else:
                try:
                    return json.loads(corrected)
                except json.JSONDecodeError:
                    pass
                match = re.search(r"```(?:json)?\s*([\s\S]*?)```", corrected)
                if match:
                    try:
                        return json.loads(match.group(1))
                    except json.JSONDecodeError:
                        pass

        raise ValueError("Failed to parse JSON from AI response")

    @staticmethod
    def _to_matrix_data(matrix_data: "MatrixData | dict") -> "MatrixData":
        if isinstance(matrix_data, dict):
            from core.schemas import MatrixData as MD

            return MD(**matrix_data)
        return matrix_data

    @staticmethod
    def _bundle_cache_namespace(bundle: ResolvedPromptBundle) -> str:
        return ":".join(
            (bundle.bundle_id, bundle.bundle_version, bundle.aggregate_hash)
        )

    @staticmethod
    def _governed_report_system(bundle: ResolvedPromptBundle) -> str:
        return "\n\n".join(
            (
                bundle.content("system.txt").strip(),
                bundle.content("style_contract.txt").strip(),
                bundle.content("reasoning_contract.txt").strip(),
            )
        )

    @staticmethod
    def _governed_chat_system(
        bundle: ResolvedPromptBundle,
        matrix_data: "MatrixData | dict",
        user_name: str,
    ) -> str:
        from core.services.matrix import MatrixService

        try:
            matrix_context = MatrixService.format_for_prompt(
                AIService._to_matrix_data(matrix_data)
            )
        except Exception:
            matrix_context = "(структурированные данные Матрицы не переданы)"
        return bundle.content("system.txt").format(
            user_name=user_name,
            matrix_context=matrix_context,
        )

    @staticmethod
    async def generate_mini_analysis_with_metadata(
        birth_date: str,
        matrix_data: "MatrixData | dict",
        *,
        bundle: ResolvedPromptBundle | None = None,
    ) -> GeneratedContentResult:
        from core.services.matrix import MatrixService

        resolved = bundle or resolve_active_bundle("report.mini")
        md = AIService._to_matrix_data(matrix_data)
        user_content = resolved.content("mini_analysis.txt").format(
            matrix_text=MatrixService.format_for_prompt(md)
        )
        system_prompt = AIService._governed_report_system(resolved)
        retry_cb = AIService._make_retry_callback(
            system_prompt, user_content, FULL_REPORT_PARAMS
        )
        try:
            completion = await AIService.chat_with_metadata(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                api_params=FULL_REPORT_PARAMS,
                timeout=300.0,
                cache_namespace=AIService._bundle_cache_namespace(resolved),
                method_name="mini_analysis",
            )
            parsed = await AIService._parse_json_response(completion.content, retry_cb)
            content = MiniAnalysisResult(**parsed).model_dump()
            return GeneratedContentResult(
                content=content,
                provider=completion.provider,
                model=completion.model,
                usage=completion.usage,
                duration_ms=completion.duration_ms,
                cached=completion.cached,
                generation_source="provider",
            )
        except Exception as exc:
            logger.error("generate_mini_analysis failed: %s", type(exc).__name__)
            return GeneratedContentResult(
                content=dict(FALLBACK_MINI),
                provider=None,
                model=None,
                usage={},
                duration_ms=0,
                cached=False,
                generation_source="fallback",
            )

    @staticmethod
    async def generate_full_report_with_metadata(
        birth_date: str,
        matrix_data: "MatrixData | dict",
        name: str = "пользователь",
        issues: list[str] | None = None,
        *,
        bundle: ResolvedPromptBundle | None = None,
    ) -> GeneratedContentResult:
        from core.services.matrix import MatrixService

        resolved = bundle or resolve_active_bundle("report.full")
        md = AIService._to_matrix_data(matrix_data)
        matrix_text = MatrixService.format_for_prompt(md)
        system_prompt = AIService._governed_report_system(resolved)
        templates = (
            ("part_a", "full_report_part_a.txt"),
            ("part_b", "full_report_part_b.txt"),
        )
        merged: dict[str, object] = {}
        completions: list[AICompletionResult] = []
        try:
            for part_label, template_name in templates:
                user_content = resolved.content(template_name).format(
                    matrix_text=matrix_text,
                    name=name,
                )
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ]
                if issues:
                    from core.loop_specs.report_loop import _build_retry_prompt

                    messages.append(
                        {"role": "user", "content": _build_retry_prompt(issues)}
                    )
                retry_cb = AIService._make_retry_callback(
                    system_prompt, user_content, FULL_REPORT_PARAMS
                )
                completion = await AIService.chat_with_metadata(
                    messages,
                    api_params=FULL_REPORT_PARAMS,
                    timeout=300.0,
                    cache_namespace=AIService._bundle_cache_namespace(resolved),
                    method_name=f"full_report_{part_label}",
                )
                parsed = await AIService._parse_json_response(
                    completion.content, retry_cb
                )
                if not isinstance(parsed, dict):
                    raise ValueError("full_report_part_not_object")
                merged.update(parsed)
                completions.append(completion)
            content = FullReportResult(**merged).model_dump()
        except Exception as exc:
            logger.error("generate_full_report failed: %s", type(exc).__name__)
            return GeneratedContentResult(
                content=dict(FALLBACK_FULL),
                provider=None,
                model=None,
                usage={},
                duration_ms=sum(item.duration_ms for item in completions),
                cached=False,
                generation_source="fallback",
            )
        usage = {
            key: sum(item.usage.get(key, 0) for item in completions)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        return GeneratedContentResult(
            content=content,
            provider=completions[0].provider,
            model=completions[0].model,
            usage=usage,
            duration_ms=sum(item.duration_ms for item in completions),
            cached=all(item.cached for item in completions),
            generation_source="provider",
        )

    @staticmethod
    async def generate_kitchen_report_with_metadata(
        birth_date: str,
        matrix_data: "MatrixData | dict",
        *,
        bundle: ResolvedPromptBundle | None = None,
    ) -> GeneratedContentResult:
        from core.services.matrix import MatrixService

        resolved = bundle or resolve_active_bundle("report.kitchen")
        md = AIService._to_matrix_data(matrix_data)
        user_content = resolved.content("kitchen_report.txt").format(
            matrix_text=MatrixService.format_for_prompt(md)
        )
        system_prompt = AIService._governed_report_system(resolved)
        params = {
            "temperature": 0.3,
            "max_tokens": 8000,
            "top_p": 0.9,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
        }
        retry_cb = AIService._make_retry_callback(system_prompt, user_content, params)
        try:
            completion = await AIService.chat_with_metadata(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                api_params=params,
                timeout=180.0,
                cache_namespace=AIService._bundle_cache_namespace(resolved),
                method_name="kitchen_report",
            )
            parsed = await AIService._parse_json_response(completion.content, retry_cb)
            content = KitchenReportResult(**parsed).model_dump()
            return GeneratedContentResult(
                content=content,
                provider=completion.provider,
                model=completion.model,
                usage=completion.usage,
                duration_ms=completion.duration_ms,
                cached=completion.cached,
                generation_source="provider",
            )
        except Exception as exc:
            logger.error("generate_kitchen_report failed: %s", type(exc).__name__)
            return GeneratedContentResult(
                content=dict(FALLBACK_KITCHEN),
                provider=None,
                model=None,
                usage={},
                duration_ms=0,
                cached=False,
                generation_source="fallback",
            )

    @staticmethod
    async def chat_response_with_metadata(
        user_message: str,
        chat_history: list[dict],
        matrix_data: "MatrixData | dict",
        user_name: str = "пользователь",
        *,
        bundle: ResolvedPromptBundle | None = None,
    ) -> GeneratedContentResult:
        resolved = bundle or resolve_active_bundle("chat.free")
        system_prompt = AIService._governed_chat_system(
            resolved, matrix_data, user_name
        )
        recent = chat_history[-10:] if len(chat_history) > 10 else chat_history
        try:
            completion = await AIService.chat_with_metadata(
                [
                    {"role": "system", "content": system_prompt},
                    *recent,
                    {"role": "user", "content": user_message},
                ],
                api_params=CHAT_PARAMS,
                cache_namespace=AIService._bundle_cache_namespace(resolved),
                method_name="chat_response",
            )
            return GeneratedContentResult(
                content=completion.content,
                provider=completion.provider,
                model=completion.model,
                usage=completion.usage,
                duration_ms=completion.duration_ms,
                cached=completion.cached,
                generation_source="provider",
            )
        except Exception as exc:
            logger.error("chat_response failed: %s", type(exc).__name__)
            return GeneratedContentResult(
                content=FALLBACK_CHAT,
                provider=None,
                model=None,
                usage={},
                duration_ms=0,
                cached=False,
                generation_source="fallback",
            )

    @staticmethod
    def _build_chat_system_prompt(
        matrix_data: "MatrixData | dict", user_name: str = "пользователь"
    ) -> str:
        from core.services.matrix import ARCANA, MatrixService

        md = AIService._to_matrix_data(matrix_data)
        archetype_number = md.center
        archetype_info = ARCANA.get(archetype_number, {})
        archetype_name = archetype_info.get("name", "Неизвестный")
        archetype_key = archetype_info.get("key", "")
        matrix_text = MatrixService.format_for_prompt(md)

        return _chat_system_prompt_template().format(
            user_name=user_name,
            archetype_name=archetype_name,
            archetype_number=archetype_number,
            archetype_key=archetype_key,
            matrix_text=matrix_text,
        )

    @staticmethod
    async def generate_mini_analysis(
        birth_date: str, matrix_data: "MatrixData | dict"
    ) -> dict:
        from core.services.matrix import MatrixService

        md = AIService._to_matrix_data(matrix_data)
        matrix_text = MatrixService.format_for_prompt(md)
        cot = AIService._load_prompt("cot_instruction.txt")
        template = AIService._load_prompt("mini_analysis.txt")
        user_content = template.format(chain_of_thought=cot, matrix_text=matrix_text)

        retry_cb = AIService._make_retry_callback(_system_prompt(), user_content, FULL_REPORT_PARAMS)

        try:
            response = await AIService.chat(
                [
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": user_content},
                ],
                api_params=FULL_REPORT_PARAMS,
                timeout=300.0,
                method_name="mini_analysis",
            )
            result = await AIService._parse_json_response(response, retry_cb)
            validated = MiniAnalysisResult(**result)
            return validated.model_dump()
        except Exception as e:
            logger.error("generate_mini_analysis failed: %s", e, exc_info=True)
            return FALLBACK_MINI

    @staticmethod
    async def generate_full_report(
        birth_date: str,
        matrix_data: "MatrixData | dict",
        name: str = "пользователь",
        issues: list[str] | None = None,
    ) -> dict:
        from core.services.matrix import MatrixService

        md = AIService._to_matrix_data(matrix_data)
        matrix_text = MatrixService.format_for_prompt(md)
        cot = AIService._load_prompt("cot_instruction.txt")

        template_a = AIService._load_prompt("full_report_part_a.txt")
        template_b = AIService._load_prompt("full_report_part_b.txt")

        user_content_a = template_a.format(
            chain_of_thought=cot,
            matrix_text=matrix_text,
            name=name,
            birth_date=birth_date,
        )
        user_content_b = template_b.format(
            chain_of_thought=cot,
            matrix_text=matrix_text,
            name=name,
            birth_date=birth_date,
        )

        async def _generate_part(user_content: str, part_label: str) -> dict:
            retry_cb = AIService._make_retry_callback(_system_prompt(), user_content, FULL_REPORT_PARAMS)
            messages = [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": user_content},
            ]
            if issues:
                from core.loop_specs.report_loop import _build_retry_prompt
                messages.append({"role": "user", "content": _build_retry_prompt(issues)})
            response = await AIService.chat(
                messages,
                api_params=FULL_REPORT_PARAMS,
                timeout=300.0,
                method_name=f"full_report_{part_label}",
            )
            return await AIService._parse_json_response(response, retry_cb)

        merged: dict = {}

        try:
            part_a_result = await _generate_part(user_content_a, "part_a")
            if isinstance(part_a_result, dict):
                merged.update(part_a_result)
                logger.info("generate_full_report: part_a succeeded")
            else:
                logger.error("generate_full_report: part_a returned non-dict: %s", type(part_a_result))
        except Exception as e:
            logger.error("generate_full_report: part_a failed: %s — skipping part_b", e)
            return FALLBACK_FULL

        try:
            part_b_result = await _generate_part(user_content_b, "part_b")
            if isinstance(part_b_result, dict):
                merged.update(part_b_result)
                logger.info("generate_full_report: part_b succeeded")
            else:
                logger.error("generate_full_report: part_b returned non-dict: %s", type(part_b_result))
        except Exception as e:
            logger.error("generate_full_report: part_b failed: %s", e)

        if not merged:
            logger.exception("generate_full_report failed — both parts returned empty")
            return FALLBACK_FULL

        validated = FullReportResult(**merged)
        return validated.model_dump()

    @staticmethod
    async def generate_kitchen_report(
        birth_date: str, matrix_data: "MatrixData | dict"
    ) -> dict:
        from core.services.matrix import MatrixService

        md = AIService._to_matrix_data(matrix_data)
        matrix_text = MatrixService.format_for_prompt(md)
        cot = AIService._load_prompt("cot_instruction.txt")
        template = AIService._load_prompt("kitchen_report.txt")
        user_content = template.format(chain_of_thought=cot, matrix_text=matrix_text)

        kitchen_params = {
            "temperature": 0.3,
            "max_tokens": 8000,
            "top_p": 0.9,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
        }
        retry_cb = AIService._make_retry_callback(_system_prompt(), user_content, kitchen_params)

        try:
            response = await AIService.chat(
                [
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": user_content},
                ],
                api_params=kitchen_params,
                timeout=180.0,
                method_name="kitchen_report",
            )
            result = await AIService._parse_json_response(response, retry_cb)
            validated = KitchenReportResult(**result)
            return validated.model_dump()
        except Exception as e:
            logger.error("generate_kitchen_report failed: %s", e, exc_info=True)
            return FALLBACK_KITCHEN

    @staticmethod
    async def generate_compatibility(
        date1: str,
        matrix1: "MatrixData | dict",
        date2: str,
        matrix2: "MatrixData | dict",
        user_name: str = "Первый",
        partner_name: str = "Второй",
        relation_type: str = "общение",
    ) -> dict:
        from core.services.matrix import MatrixService

        md1 = AIService._to_matrix_data(matrix1)
        md2 = AIService._to_matrix_data(matrix2)
        matrix_text_first = MatrixService.format_for_prompt(md1)
        matrix_text_second = MatrixService.format_for_prompt(md2)

        template = AIService._load_prompt("compatibility_full.txt")
        user_content = template.format(
            matrix_text_first=matrix_text_first,
            matrix_text_second=matrix_text_second,
            user_name=user_name,
            partner_name=partner_name,
            relation_type=relation_type,
        )

        retry_cb = AIService._make_retry_callback(_system_prompt(), user_content, FULL_REPORT_PARAMS)

        try:
            response = await AIService.chat(
                [
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": user_content},
                ],
                api_params=FULL_REPORT_PARAMS,
                timeout=300.0,
                method_name="compatibility",
            )
            result = await AIService._parse_json_response(response, retry_cb)
            validated = CompatibilityFullResult(**result)
            return validated.model_dump()
        except Exception:
            return FALLBACK_COMPATIBILITY

    @staticmethod
    async def generate_daily_insight(
        user_name: str,
        archetype_name: str,
        archetype_number: int,
        archetype_key: str,
        matrix_data: "MatrixData | dict",
        current_date: str,
    ) -> DailyInsightResult:
        from datetime import datetime

        md = AIService._to_matrix_data(matrix_data)
        matrix_json = md.model_dump_json()
        dt = datetime.fromisoformat(current_date)
        day_of_year = dt.timetuple().tm_yday

        template = AIService._load_prompt("daily_insight.txt")
        prompt = template.format(
            user_name=user_name,
            archetype_name=archetype_name,
            archetype_number=archetype_number,
            archetype_key=archetype_key,
            matrix_json=matrix_json,
            current_date=current_date,
            day_of_year=day_of_year,
        )

        try:
            response = await AIService.chat(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Сгенерируй инсайт дня на основе моих данных."},
                ],
                api_params={**DEFAULT_PARAMS, "max_tokens": 800},
                method_name="daily_insight",
            )
            result = await AIService._parse_json_response(response)
            validated = DailyInsightResult(**result)
            return validated
        except Exception:
            from core.services.insights_data import INSIGHTS_BY_ARCHETYPE

            archetype_data = INSIGHTS_BY_ARCHETYPE.get(archetype_number)
            if archetype_data and archetype_data["insights"]:
                insight = random.choice(archetype_data["insights"])
                return DailyInsightResult(insight=insight, focus_area="саморазвитие")
            return DailyInsightResult(
                insight="Сегодня — день новых возможностей. Откройся им.",
                focus_area="саморазвитие",
            )

    @staticmethod
    async def _get_matrix_context(user: "User") -> str:
        from sqlalchemy import select

        from core.database import get_async_sessionmaker
        from core.models import Report, ReportType

        session_factory = get_async_sessionmaker()
        async with session_factory() as session:
            result = await session.execute(
                select(Report).where(
                    Report.user_id == user.id,
                    Report.report_type == ReportType.FULL.value,
                    Report.matrix_data.isnot(None),
                ).order_by(Report.created_at.desc()).limit(1)
            )
            report = result.scalar_one_or_none()

        if report is None or report.matrix_data is None:
            return ""

        md = AIService._to_matrix_data(report.matrix_data)
        lines = []

        pos_map: dict[str, str] = {
            "center": "центр (архетип личности)",
            "top": "верх (духовная задача)",
            "bottom": "низ (материальная задача)",
            "left": "лево (энергия рода, прошлое)",
            "right": "право (энергия настоящего и будущего)",
            "talent_zone": "зона талантов",
            "comfort_zone": "зона комфорта",
            "portrait_zone": "портретная зона",
            "relationship_point": "точка отношений",
            "inner_f": "внутренняя точка F (дар)",
            "inner_g": "внутренняя точка G (линия отца)",
            "inner_h": "внутренняя точка H (денежный канал)",
            "inner_i": "внутренняя точка I (линия матери)",
        }
        for attr, pos_name in pos_map.items():
            value = getattr(md, attr, None)
            if value is not None:
                if isinstance(value, list):
                    vals = ", ".join(str(v) for v in value)
                    lines.append(f"В твоей матрице аркан {vals} стоит в позиции {pos_name}.")
                else:
                    lines.append(f"В твоей матрице аркан {value} стоит в позиции {pos_name}.")

        list_fields: list[tuple[str, str]] = [
            ("sky_line", "линия неба"),
            ("earth_line", "линия земли"),
            ("relationship_line", "линия отношений"),
            ("money_line", "линия денег"),
            ("karmic_tail", "кармический хвост"),
        ]
        for attr, pos_name in list_fields:
            value = getattr(md, attr, None)
            if value:
                vals = ", ".join(str(v) for v in value)
                lines.append(f"В твоей матрице аркан {vals} стоит в позиции {pos_name}.")

        return "\n".join(lines)

    @staticmethod
    async def _calculate_question_spread(birth_date: str, question: str) -> list[int]:
        from core.services.daily_arcana import calculate_daily_arcana

        base = calculate_daily_arcana(birth_date)
        seed_hash = sum(ord(c) for c in question)
        return [(base + seed_hash + i * 7) % 22 + 1 for i in range(3)]

    async def generate_tarot_daily_card(
        self,
        arcana_number: int,
        arcana_name: str,
        date_str: str,
        user_name: str = "друг",
        user_archetype_number: int = 0,
        user_archetype_name: str = "",
    ) -> str:
        from core.loop_specs.tarot_loop import generate_tarot_text

        prompt = self._load_prompt("tarot_daily_card.txt")
        filled = prompt.format(
            arcana_number=arcana_number,
            arcana_name=arcana_name,
            date=date_str,
            user_name=user_name,
            user_archetype_number=user_archetype_number or arcana_number,
            user_archetype_name=user_archetype_name or arcana_name,
        )
        result = await generate_tarot_text(
            messages=[
                {"role": "system", "content": (
                    "Ты — NURA, персональный психологический проводник. "
                    "Обращайся к пользователю по имени. "
                    "Никогда не называй арканы, карты и их номера. "
                    "Пиши живым личным языком — не как гороскоп, "
                    "а как персональный инсайт."
                )},
                {"role": "user", "content": filled},
            ],
            api_params={"max_tokens": 400, "temperature": 0.7},
            min_words=30,
            user_name=user_name,
        )
        return result

    @staticmethod
    async def generate_tarot_weekly_spread(
        birth_date: str,
        user: "User",
    ) -> dict:
        from core.services.daily_arcana import calculate_spread_arcanas

        three_arcana = calculate_spread_arcanas(birth_date, 3)
        matrix_context = await AIService._get_matrix_context(user)
        user_name = user.first_name or user.username or "пользователь"

        template = AIService._load_prompt("tarot_weekly_spread.txt")
        user_content = template.format(
            user_name=user_name,
            birth_date=birth_date,
            three_arcana=three_arcana,
            matrix_context=matrix_context if matrix_context else "(нет данных матрицы)",
        )

        spread_params = {"model": TAROT_SPREAD_MODEL, **DEFAULT_PARAMS}
        retry_cb = AIService._make_retry_callback(_system_prompt(), user_content, spread_params)

        try:
            response = await AIService.chat(
                [
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": user_content},
                ],
                api_params=spread_params,
                method_name="tarot_weekly_spread",
            )
            result = await AIService._parse_json_response(response, retry_cb)
            from core.schemas import TarotWeeklySpreadResult

            validated = TarotWeeklySpreadResult(**result)
            return validated.model_dump()
        except Exception as e:
            logger.error("generate_tarot_weekly_spread failed: %s", e, exc_info=True)
            return dict(FALLBACK_TAROT_SPREAD)

    @staticmethod
    async def generate_tarot_question(
        birth_date: str,
        question: str,
        user: "User",
    ) -> dict:
        three_arcana = await AIService._calculate_question_spread(birth_date, question)
        matrix_context = await AIService._get_matrix_context(user)
        user_name = user.first_name or user.username or "пользователь"

        template = AIService._load_prompt("tarot_question.txt")
        user_content = template.format(
            user_name=user_name,
            birth_date=birth_date,
            question=question,
            three_arcana=three_arcana,
            matrix_context=matrix_context if matrix_context else "(нет данных матрицы)",
        )

        question_params = {"model": TAROT_QUESTION_MODEL, **DEFAULT_PARAMS}
        retry_cb = AIService._make_retry_callback(_system_prompt(), user_content, question_params)

        try:
            response = await AIService.chat(
                [
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": user_content},
                ],
                api_params=question_params,
                method_name="tarot_question",
            )
            result = await AIService._parse_json_response(response, retry_cb)
            from core.schemas import TarotQuestionResult

            validated = TarotQuestionResult(**result)
            return validated.model_dump()
        except Exception as e:
            logger.error("generate_tarot_question failed: %s", e, exc_info=True)
            return dict(FALLBACK_TAROT_QUESTION)

    @staticmethod
    async def generate_tarot_mini_spread(
        birth_date: str,
        topic: str,
        user: "User",
    ) -> dict:
        three_arcana = await AIService._calculate_question_spread(birth_date, topic)
        matrix_context = await AIService._get_matrix_context(user)
        user_name = user.first_name or user.username or "пользователь"
        template = AIService._load_prompt("tarot_mini_spread.txt")
        user_content = template.format(
            user_name=user_name,
            topic=topic,
            three_arcana=three_arcana,
            matrix_context=matrix_context if matrix_context else "(нет данных матрицы)",
        )
        response = await AIService.chat(
            [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": user_content},
            ],
            api_params={"model": TAROT_QUESTION_MODEL, **DEFAULT_PARAMS},
            method_name="tarot_mini_spread",
        )
        result = await AIService._parse_json_response(response)
        from core.schemas import TarotMiniSpreadResult

        return TarotMiniSpreadResult(**result).model_dump()

    @staticmethod
    async def chat_response(
        user_message: str,
        chat_history: list[dict],
        matrix_data: "MatrixData | dict",
        user_name: str = "пользователь",
    ) -> str:
        result = await AIService.chat_response_with_metadata(
            user_message=user_message,
            chat_history=chat_history,
            matrix_data=matrix_data,
            user_name=user_name,
        )
        return str(result.content)


def _system_prompt() -> str:
    global _SYSTEM_PROMPT_CACHE
    if _SYSTEM_PROMPT_CACHE is None:
        _SYSTEM_PROMPT_CACHE = AIService._load_prompt("system_prompt.txt")
    return _SYSTEM_PROMPT_CACHE


def _chat_system_prompt_template() -> str:
    global _CHAT_SYSTEM_PROMPT_TEMPLATE_CACHE
    if _CHAT_SYSTEM_PROMPT_TEMPLATE_CACHE is None:
        _CHAT_SYSTEM_PROMPT_TEMPLATE_CACHE = AIService._load_prompt(
            "chat_system_prompt.txt"
        )
    return _CHAT_SYSTEM_PROMPT_TEMPLATE_CACHE
