import json
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from core.config import settings

if TYPE_CHECKING:
    from core.schemas import MatrixData


PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class AIService:
    @staticmethod
    def _load_prompt(name: str) -> str:
        path = PROMPTS_DIR / name
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    @staticmethod
    async def chat(messages: list[dict]) -> str:
        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.deepseek_model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4000,
        }
        async with httpx.AsyncClient(timeout=90.0) as client:
            r = await client.post(
                f"{settings.deepseek_base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]

    @staticmethod
    async def generate_mini_analysis(matrix_data: "MatrixData | dict") -> dict:
        from core.services.matrix import MatrixService

        matrix_text = MatrixService.format_for_prompt(matrix_data)
        prompt_template = AIService._load_prompt("mini_analysis.txt")
        system_prompt = (
            "Ты — Нура, AI-проводник в самопознании через Матрицу Судьбы. "
            "Ты помогаешь людям понять себя через архетипы Таро. "
            "Твой тон — тёплый, проницательный, без эзотерического жаргона. "
            "Ты не предсказываешь судьбу — ты помогаешь увидеть то, что уже есть. "
            "Избегай клише и общих фраз. Будь конкретным и точным."
        )

        if prompt_template:
            user_content = prompt_template.format(matrix_text=matrix_text)
        else:
            user_content = (
                f"Проанализируй Матрицу Судьбы:\n{matrix_text}\n\n"
                "Верни ТОЛЬКО JSON-объект с полями: "
                "main_archetype, core_strength, emotional_conflict, "
                "relationship_pattern, financial_block. "
                "Каждое поле — 2-4 предложения на русском языке."
            )

        response = await AIService.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ])

        try:
            result = json.loads(response)
        except json.JSONDecodeError:
            response = await AIService.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
                {
                    "role": "assistant",
                    "content": response,
                },
                {
                    "role": "user",
                    "content": "Выдай ТОЛЬКО валидный JSON без дополнительного текста.",
                },
            ])
            result = json.loads(response)

        return result

    @staticmethod
    async def generate_full_report(matrix_data: "MatrixData | dict") -> dict:
        from core.services.matrix import MatrixService

        matrix_text = MatrixService.format_for_prompt(matrix_data)
        prompt_template = AIService._load_prompt("full_report.txt")
        system_prompt = (
            "Ты — Нура, AI-проводник в глубоком самопознании через Матрицу Судьбы. "
            "Твой анализ глубокий, точный и трансформирующий. "
            "Ты помогаешь человеку увидеть свои теневые стороны, "
            "повторяющиеся сценарии и путь к целостности. "
            "Тон — мудрый, спокойный, уверенный. Без эзотерики."
        )

        if prompt_template:
            user_content = prompt_template.format(matrix_text=matrix_text)
        else:
            user_content = (
                f"Дай полный разбор Матрицы Судьбы:\n{matrix_text}\n\n"
                "Верни ТОЛЬКО JSON-объект с полями: "
                "main_archetype, strengths, shadow_side, relationship_dynamics, "
                "financial_scenario, recurring_mistakes, internal_conflicts, "
                "life_cycles, ai_recommendations. "
                "Каждое поле — 3-6 предложений на русском языке."
            )

        response = await AIService.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ])

        try:
            result = json.loads(response)
        except json.JSONDecodeError:
            response = await AIService.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": response},
                {"role": "user", "content": "Выдай ТОЛЬКО валидный JSON без дополнительного текста."},
            ])
            result = json.loads(response)

        return result
