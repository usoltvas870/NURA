import asyncio
import json
import logging
import random
import re
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

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from core.models import User
    from core.schemas import MatrixData

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_SYSTEM_PROMPT_CACHE: str | None = None
_CHAT_SYSTEM_PROMPT_TEMPLATE_CACHE: str | None = None


class AIService:
    @staticmethod
    def _load_prompt(name: str) -> str:
        path = PROMPTS_DIR / name
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    @staticmethod
    async def chat(
        messages: list[dict],
        api_params: dict | None = None,
        max_retries: int = 3,
        timeout: float = 30.0,
    ) -> str:
        params = {**DEFAULT_PARAMS, **(api_params or {})}
        model = params.pop("model", settings.deepseek_model)

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
                    return data["choices"][0]["message"]["content"]
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 * (2 ** attempt))
                continue

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

        async def _retry_callback(bad: str) -> str:
            return await AIService.chat(
                [
                    {"role": "system", "content": _system_prompt()},
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
                ]
            )

        try:
            response = await AIService.chat(
                [
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": user_content},
                ],
                api_params=FULL_REPORT_PARAMS,
                timeout=300.0,
            )
            result = await AIService._parse_json_response(response, _retry_callback)
            validated = MiniAnalysisResult(**result)
            return validated.model_dump()
        except Exception as e:
            logger.error("generate_mini_analysis failed: %s", e, exc_info=True)
            return FALLBACK_MINI

    @staticmethod
    async def generate_full_report(
        birth_date: str, matrix_data: "MatrixData | dict", name: str = "пользователь"
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

        async def _generate_part(user_content: str) -> dict:
            async def _retry_callback(bad: str) -> str:
                return await AIService.chat(
                    [
                        {"role": "system", "content": _system_prompt()},
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
                    api_params=FULL_REPORT_PARAMS,
                )

            response = await AIService.chat(
                [
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": user_content},
                ],
                api_params=FULL_REPORT_PARAMS,
                timeout=300.0,
            )
            return await AIService._parse_json_response(response, _retry_callback)

        try:
            results_a, results_b = await asyncio.gather(
                _generate_part(user_content_a),
                _generate_part(user_content_b),
            )
            merged = {**results_a, **results_b}
            validated = FullReportResult(**merged)
            return validated.model_dump()
        except Exception:
            logger.exception("generate_full_report failed — returning FALLBACK_FULL")
            return FALLBACK_FULL

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

        async def _retry_callback(bad: str) -> str:
            return await AIService.chat(
                [
                    {"role": "system", "content": _system_prompt()},
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
                api_params=FULL_REPORT_PARAMS,
                timeout=300.0,
            )

        try:
            response = await AIService.chat(
                [
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": user_content},
                ],
                api_params={
                    "temperature": 0.3,
                    "max_tokens": 8000,
                    "top_p": 0.9,
                    "frequency_penalty": 0.0,
                    "presence_penalty": 0.0,
                },
                timeout=180.0,
            )
            result = await AIService._parse_json_response(response, _retry_callback)
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

        async def _retry_callback(bad: str) -> str:
            return await AIService.chat(
                [
                    {"role": "system", "content": _system_prompt()},
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
                api_params=FULL_REPORT_PARAMS,
            )

        try:
            response = await AIService.chat(
                [
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": user_content},
                ],
                api_params=FULL_REPORT_PARAMS,
                timeout=300.0,
            )
            result = await AIService._parse_json_response(response, _retry_callback)
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
        prompt = self._load_prompt("tarot_daily_card.txt")
        filled = prompt.format(
            arcana_number=arcana_number,
            arcana_name=arcana_name,
            date=date_str,
            user_name=user_name,
            user_archetype_number=user_archetype_number or arcana_number,
            user_archetype_name=user_archetype_name or arcana_name,
        )
        result = await self.chat(
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
        )
        return result.strip().strip('"')

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

        async def _retry_callback(bad: str) -> str:
            return await AIService.chat(
                [
                    {"role": "system", "content": _system_prompt()},
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
                api_params={"model": TAROT_SPREAD_MODEL, **DEFAULT_PARAMS},
            )

        try:
            response = await AIService.chat(
                [
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": user_content},
                ],
                api_params={"model": TAROT_SPREAD_MODEL, **DEFAULT_PARAMS},
            )
            result = await AIService._parse_json_response(response, _retry_callback)
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

        async def _retry_callback(bad: str) -> str:
            return await AIService.chat(
                [
                    {"role": "system", "content": _system_prompt()},
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
                api_params={"model": TAROT_QUESTION_MODEL, **DEFAULT_PARAMS},
            )

        try:
            response = await AIService.chat(
                [
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": user_content},
                ],
                api_params={"model": TAROT_QUESTION_MODEL, **DEFAULT_PARAMS},
            )
            result = await AIService._parse_json_response(response, _retry_callback)
            from core.schemas import TarotQuestionResult

            validated = TarotQuestionResult(**result)
            return validated.model_dump()
        except Exception as e:
            logger.error("generate_tarot_question failed: %s", e, exc_info=True)
            return dict(FALLBACK_TAROT_QUESTION)

    @staticmethod
    async def chat_response(
        user_message: str,
        chat_history: list[dict],
        matrix_data: "MatrixData | dict",
        user_name: str = "пользователь",
    ) -> str:
        system_prompt = AIService._build_chat_system_prompt(matrix_data, user_name)
        recent = chat_history[-10:] if len(chat_history) > 10 else chat_history

        messages = [
            {"role": "system", "content": system_prompt},
            *recent,
            {"role": "user", "content": user_message},
        ]

        try:
            return await AIService.chat(messages, api_params=CHAT_PARAMS)
        except Exception:
            return FALLBACK_CHAT


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
