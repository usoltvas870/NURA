import asyncio
import json
import logging
import random
import re
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from core.config import settings
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

SYSTEM_PROMPT = """Ты — NURA, девушка, AI-проводница в самопознании через Матрицу Судьбы.

Твоя роль:
Ты помогаешь людям понять себя через систему 22 Старших Арканов, зашифрованных в дате рождения.
Ты не предсказываешь судьбу — ты показываешь паттерны, которые уже есть в жизни человека.
Ты — тёплая подруга, которая прошла этот путь раньше и помогает увидеть яснее.

Правила тона и стиля:
- Всегда на "ты". Никакого "вы".
- Ты девушка — отвечай от женского лица.
- Без эзотерического жаргона. Никаких: гадание, карма, магия, чакры, порча, сглаз, вибрации, космос, предсказание.
- Без страха и запугивания. Никаких "тебе нельзя", "ты навредишь себе", "это опасно".
- Без оценочных суждений. Не оцениваешь человека как "плохой" или "хороший".
- Конкретно и точно. Избегаешь общих фраз и клише. Каждое слово — в точку.
- Тёплый, но не слащавый тон. Как умная подруга, которая разбирается в психологии и архетипах.
- Не притворяешься человеком. Ты — AI, и это нормально.

Слова-разрешители (используй свободно):
ясность, видеть, сценарий, энергия, опора, карта, архетип, паттерн, цикл, реализация,
выбор, рост, сила, конкретный, понять себя, программа, установка, ресурс, канал.

Слова-запретители (никогда):
гадание, гадалка, судьба (как рок), предсказание, предсказать, карма, кармический,
магия, магический, чакры, порча, сглаз, проклятие, вибрации, космос, волшебство,
приворот, родовое проклятие, энергетика (в смысле мистики).

Поведение:
- Не даёшь медицинских, юридических или финансовых советов.
- Если пользователь в кризисе или говорит о самоповреждении — мягко предлагаешь обратиться к специалисту.
- Не даёшь готовых ответов — помогаешь увидеть то, что уже есть внутри человека.
- Каждый ответ ведёт к следующему шагу. Не оставляешь в состоянии "я понял проблему и всё".
- Используешь знание архетипа и матрицы пользователя в каждом ответе.
- При анализе ссылаешься на конкретные позиции матрицы и их значения.

Ты не заменяешь психолога. Ты — инструмент самопознания."""

CHAT_SYSTEM_PROMPT_TEMPLATE = """Ты — NURA, девушка, AI-проводница в Матрицу Судьбы. Ты в живом диалоге с пользователем.

Ты знаешь пользователя лично:
- Имя: {user_name}
- Архетип: {archetype_name} ({archetype_number} аркан)
- Ключевая фраза архетипа: {archetype_key}

Матрица пользователя (все позиции):
{matrix_text}

Правила диалога:
- Ты уже знаешь пользователя и его матрицу. Не нужно представляться заново.
- Отвечай на "ты" — как тёплая, мудрая подруга.
- Ты девушка — все глаголы в женском роде (сказала, ответила, подумала, знаю).
- Используй знание архетипа и конкретных позиций матрицы пользователя в каждом ответе.
- Ответы — 2-4 предложения. Не читай лекций.
- Не даёшь медицинских, юридических или финансовых советов.
- Если пользователь в кризисе или говорит о самоповреждении — мягко предложи обратиться к специалисту.
- Если пользователь спрашивает о будущем — не предсказывай, а покажи паттерн: «Исходя из твоего архетипа, для тебя характерно...»
- Если вопрос не по теме матрицы — отвечай, но мягко возвращай к самопознанию.
- Завершай ответ вопросом или приглашением к следующему шагу, если это уместно.
- Без эзотерического жаргона (запрещены: гадание, карма, магия, чакры, порча, вибрации, судьба как рок).
- Если пользователь просит проанализировать другого человека (имя + дата рождения) — мягко отказывай: «Я знаю только тебя и твою матрицу. Хочешь разобраться, как твой архетип влияет на отношения с другими?»
- Не пытаться рассчитать матрицу по переданной пользователем дате рождения.

Общие правила NURA:
- На "ты", тёплая проводница
- Без эзотерики, без страха, без оценочных суждений
- Конкретно и точно
- Каждый ответ — шаг к ясности"""

FALLBACK_MINI = {
    "main_archetype": (
        "Твой главный архетип определён, но для точной интерпретации мне нужно "
        "чуть больше времени. Попробуй запросить разбор ещё раз через минуту — "
        "я выдам полный анализ."
    ),
    "core_strength": (
        "Твоя сильная сторона связана с твоим архетипом. Чтобы раскрыть её точно, "
        "дай мне ещё одну попытку."
    ),
    "emotional_conflict": (
        "Эмоциональный паттерн виден в матрице, но я хочу дать тебе точный разбор. "
        "Повтори запрос через минуту."
    ),
    "relationship_pattern": (
        "Паттерн отношений зашифрован в твоих углах матрицы. Мне нужно чуть больше "
        "времени, чтобы расшифровать его точно."
    ),
    "financial_block": (
        "Денежный сценарий связан с твоей линией денег. Запроси разбор повторно — "
        "я выдам конкретный анализ."
    ),
}

FALLBACK_FULL = {
    "main_archetype": (
        "Твой главный архетип определён. Для глубокого анализа мне требуется "
        "дополнительное время."
    ),
    "strengths": (
        "Твои сильные стороны заложены в зоне талантов. Я вернусь с точным "
        "анализом через минуту."
    ),
    "shadow_side": (
        "Теневая сторона связана с кармическим хвостом. Мне нужно время для "
        "точной интерпретации."
    ),
    "relationship_dynamics": (
        "Динамика отношений видна по линии отношений. Я подготовлю точный разбор "
        "и вернусь."
    ),
    "financial_scenario": (
        "Финансовый сценарий зашифрован в линии денег. Дай мне минуту для анализа."
    ),
    "recurring_mistakes": (
        "Повторяющиеся сценарии определены. Я уточню анализ и вернусь с результатом."
    ),
    "internal_conflicts": (
        "Внутренние конфликты видны на пересечении линий матрицы. Мне нужно время "
        "для точного разбора."
    ),
    "life_cycles": (
        "Жизненные циклы заложены в архетипе. Я подготовлю точный анализ."
    ),
    "ai_recommendations": (
        "Рекомендации будут готовы через минуту. Они будут привязаны к твоим "
        "конкретным позициям матрицы."
    ),
    "karmic_tail_analysis": (
        "Кармический хвост — это ключ к твоим повторяющимся сценариям. "
        "Мне нужно время для точной интерпретации трёх узлов."
    ),
    "ancestral_programs": (
        "Родовые программы по линиям отца и матери зашифрованы в твоей матрице. "
        "Я подготовлю разбор и вернусь."
    ),
    "life_purpose": (
        "Твоё предназначение раскрывается через линию неба и зону талантов. "
        "Мне нужно время для глубокого анализа."
    ),
    "life_forecast": (
        "Прогноз жизненных периодов строится на основе твоего архетипа и циклов. "
        "Я уточню расчёты и вернусь с результатом."
    ),
    "psychological_blocks": (
        "Психологические блоки зашифрованы в ключевых арканах твоей матрицы. "
        "Мне нужно время для точного анализа убеждений и их проработки."
    ),
    "health_analysis": (
        "Карта здоровья строится на основе всех позиций твоей матрицы. "
        "Я подготовлю детальный разбор по чакрам и вернусь."
    ),
}

FALLBACK_COMPATIBILITY = {
    "archetype_first": (
        "Архетип первого человека определён. Для точного анализа в отношениях "
        "нужно чуть больше времени."
    ),
    "archetype_second": (
        "Архетип второго человека определён. Я уточню его проявление в паре."
    ),
    "emotional_compatibility": (
        "Эмоциональная совместимость видна по сочетанию архетипов. Мне нужно "
        "время для точного разбора."
    ),
    "conflict_zones": (
        "Зоны конфликтов зашифрованы в пересечении матриц. Я подготовлю точный анализ."
    ),
    "pair_strengths": (
        "Сильные стороны пары определены. Я вернусь с конкретным разбором."
    ),
    "ai_recommendation": (
        "Рекомендация для пары будет готова через минуту. Она будет привязана "
        "к вашим архетипам."
    ),
}

FALLBACK_CHAT = "Мне нужно чуть больше времени. Спроси ещё раз?"

TAROT_DAILY_MODEL = settings.deepseek_model
TAROT_SPREAD_MODEL = settings.deepseek_model
TAROT_QUESTION_MODEL = settings.deepseek_model

FALLBACK_TAROT_DAILY = {
    "card_number": 0,
    "card_name": "Аркан не определён",
    "key_phrase": "Сегодня — день тишины и внутреннего внимания.",
    "interpretation": (
        "Энергия дня не поддаётся точному определению. "
        "Прислушайся к себе — твой внутренний компас подскажет верное направление."
    ),
    "matrix_link": "",
    "advice": "Сделай паузу и задай себе вопрос: «Что для меня сейчас важнее всего?»",
    "affirmation": "Я доверяю своему внутреннему знанию.",
}

FALLBACK_TAROT_SPREAD = {
    "body": {
        "card_number": 0,
        "card_name": "Аркан не определён",
        "energy": "Энергия тела требует внимания.",
        "interpretation": "Прислушайся к своему телу — оно знает ответы.",
        "practice": "Сделай несколько глубоких вдохов и почувствуй своё тело.",
    },
    "mind": {
        "card_number": 0,
        "card_name": "Аркан не определён",
        "energy": "Энергия ума ищет ясность.",
        "interpretation": "Твои мысли ищут порядок — дай им время сложиться в картину.",
        "practice": "Запиши три главные мысли дня.",
    },
    "spirit": {
        "card_number": 0,
        "card_name": "Аркан не определён",
        "energy": "Энергия духа зовёт к тишине.",
        "interpretation": "Твой дух просит паузы — остановись на минуту и просто будь.",
        "practice": "Побудь в тишине 5 минут.",
    },
    "overall": (
        "Неделя приглашает тебя замедлиться и прислушаться к себе. "
        "Твоё тело, ум и дух ищут гармонию — дай им время найти её."
    ),
}

FALLBACK_TAROT_QUESTION = {
    "past": {
        "card_number": 0,
        "card_name": "Аркан не определён",
        "meaning": "Прошлое содержит ключи к твоему вопросу.",
        "how_it_relates": "Оглянись назад — паттерн уже был в твоей жизни.",
    },
    "present": {
        "card_number": 0,
        "card_name": "Аркан не определён",
        "meaning": "Настоящее показывает, где ты сейчас.",
        "how_it_relates": "Ты в процессе — и это нормально.",
    },
    "future": {
        "card_number": 0,
        "card_name": "Аркан не определён",
        "meaning": "Будущее открывается через твой выбор.",
        "how_it_relates": "То, что ты делаешь сейчас, формирует следующий шаг.",
    },
    "summary": "У тебя есть всё, чтобы найти ответ внутри себя.",
    "advice": "Сделай один маленький шаг в направлении, которое чувствуется правильным.",
}

DEFAULT_PARAMS = {
    "temperature": 0.7,
    "max_tokens": 4000,
    "top_p": 0.9,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
}

FULL_REPORT_PARAMS = {
    "temperature": 0.7,
    "max_tokens": 32000,
    "top_p": 0.9,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
}

CHAT_PARAMS = {
    "temperature": 0.8,
    "max_tokens": 1000,
    "top_p": 0.95,
    "frequency_penalty": 0.1,
    "presence_penalty": 0.1,
}


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

        return CHAT_SYSTEM_PROMPT_TEMPLATE.format(
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
                    {"role": "system", "content": SYSTEM_PROMPT},
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
                    {"role": "system", "content": SYSTEM_PROMPT},
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
        birth_date: str, matrix_data: "MatrixData | dict"
    ) -> dict:
        from core.services.matrix import MatrixService

        md = AIService._to_matrix_data(matrix_data)
        matrix_text = MatrixService.format_for_prompt(md)
        cot = AIService._load_prompt("cot_instruction.txt")
        template = AIService._load_prompt("full_report.txt")
        user_content = template.format(chain_of_thought=cot, matrix_text=matrix_text)

        async def _retry_callback(bad: str) -> str:
            return await AIService.chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
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
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                api_params=FULL_REPORT_PARAMS,
                timeout=300.0,
            )
            result = await AIService._parse_json_response(response, _retry_callback)
            validated = FullReportResult(**result)
            return validated.model_dump()
        except Exception:
            logger.exception("generate_full_report failed — returning FALLBACK_FULL")
            return FALLBACK_FULL

    FALLBACK_KITCHEN: dict[str, dict] = {
        key: {"positions": [], "energies": [], "logic": "Не удалось подготовить объяснение. Попробуй ещё раз."}
        for key in [
            "main_archetype", "strengths", "shadow_side", "relationship_dynamics",
            "financial_scenario", "recurring_mistakes", "internal_conflicts",
            "life_cycles", "karmic_tail_analysis", "ancestral_programs",
            "life_purpose", "life_forecast", "psychological_blocks", "health_analysis",
        ]
    }

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
                    {"role": "system", "content": SYSTEM_PROMPT},
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
                    {"role": "system", "content": SYSTEM_PROMPT},
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
            return AIService.FALLBACK_KITCHEN

    @staticmethod
    async def generate_compatibility(
        date1: str,
        matrix1: "MatrixData | dict",
        date2: str,
        matrix2: "MatrixData | dict",
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
        )

        async def _retry_callback(bad: str) -> str:
            return await AIService.chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
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
                    {"role": "system", "content": SYSTEM_PROMPT},
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

    @staticmethod
    async def generate_tarot_daily_card(
        birth_date: str,
        user: "User",
    ) -> dict:
        from core.services.daily_arcana import calculate_daily_arcana

        daily_arcana = calculate_daily_arcana(birth_date)
        matrix_context = await AIService._get_matrix_context(user)
        user_name = user.first_name or user.username or "пользователь"

        template = AIService._load_prompt("tarot_daily_card.txt")
        user_content = template.format(
            user_name=user_name,
            birth_date=birth_date,
            daily_arcana=daily_arcana,
            matrix_context=matrix_context if matrix_context else "(нет данных матрицы)",
        )

        async def _retry_callback(bad: str) -> str:
            return await AIService.chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
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
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                api_params={"model": TAROT_DAILY_MODEL, **DEFAULT_PARAMS},
            )
            result = await AIService._parse_json_response(response, _retry_callback)
            from core.schemas import TarotDailyCardResult

            validated = TarotDailyCardResult(**result)
            return validated.model_dump()
        except Exception as e:
            logger.error("generate_tarot_daily_card failed: %s", e, exc_info=True)
            return dict(FALLBACK_TAROT_DAILY)

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
                    {"role": "system", "content": SYSTEM_PROMPT},
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
                    {"role": "system", "content": SYSTEM_PROMPT},
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
                    {"role": "system", "content": SYSTEM_PROMPT},
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
                    {"role": "system", "content": SYSTEM_PROMPT},
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
