# Промпт для агента: Двухслойная архитектура отчётов NURA

## Задача

Реализовать двухслойную архитектуру в проекте NURA:
- **User Layer** (существующий) — тёплый человеческий разбор от NURA, хранится в `ai_analysis`
- **Kitchen Layer** (новый) — техническое объяснение "почему AI так сказал" со ссылками на конкретные позиции матрицы и энергии

---

## Файлы для изменения (6 файлов)

### 1. `nura_app/core/prompts/kitchen_report.txt` — NEW

Создать файл с содержимым:

```
{chain_of_thought}

Ты — технический анализатор Матрицы Судьбы.

Твоя задача — объяснить пользователю логику расчёта и значение
конкретных энергий в его матрице. Никаких общих фраз, никаких
советов. Только факты арканов и их интерпретация в данной позиции.

Матрица:
{matrix_text}

Для каждой зоны ответа из полного отчёта укажи:
1. Какие позиции матрицы участвуют
2. Какие числа (энергии) стоят в этих позициях
3. Как эти энергии формируют вывод

Верни ТОЛЬКО валидный JSON (без markdown-блоков ```json), строго по схеме ниже.
Каждое поле — объект с ключами:
- "positions": ["левый угол (4)"]
- "energies": ["4 — Император"]
- "logic": "строка объяснения на 2-4 предложения"

Схема:
{
  "main_archetype": { "positions": [], "energies": [], "logic": "" },
  "strengths": { "positions": [], "energies": [], "logic": "" },
  "shadow_side": { "positions": [], "energies": [], "logic": "" },
  "relationship_dynamics": { "positions": [], "energies": [], "logic": "" },
  "financial_scenario": { "positions": [], "energies": [], "logic": "" },
  "recurring_mistakes": { "positions": [], "energies": [], "logic": "" },
  "internal_conflicts": { "positions": [], "energies": [], "logic": "" },
  "life_cycles": { "positions": [], "energies": [], "logic": "" },
  "karmic_tail_analysis": { "positions": [], "energies": [], "logic": "" },
  "ancestral_programs": { "positions": [], "energies": [], "logic": "" },
  "life_purpose": { "positions": [], "energies": [], "logic": "" },
  "life_forecast": { "positions": [], "energies": [], "logic": "" }
}
```

---

### 2. `nura_app/core/schemas/__init__.py` — добавить схемы Kitchen

После `class FullReportResult(BaseModel):` (строка 138) добавить:

```python
class KitchenEntry(BaseModel):
    positions: list[str]
    energies: list[str]
    logic: str

class KitchenReportResult(BaseModel):
    main_archetype: KitchenEntry
    strengths: KitchenEntry
    shadow_side: KitchenEntry
    relationship_dynamics: KitchenEntry
    financial_scenario: KitchenEntry
    recurring_mistakes: KitchenEntry
    internal_conflicts: KitchenEntry
    life_cycles: KitchenEntry
    karmic_tail_analysis: KitchenEntry
    ancestral_programs: KitchenEntry
    life_purpose: KitchenEntry
    life_forecast: KitchenEntry
```

Также добавить `KitchenEntry`, `KitchenReportResult` в `__all__` (строка 191+).

---

### 3. `nura_app/core/models.py` — добавить поле kitchen_analysis в модель Report

В классе `Report` (строка 57-78) после строки 73 (`ai_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)`) добавить:

```python
kitchen_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

---

### 4. `nura_app/core/services/ai.py` — добавить метод generate_kitchen_report

В класс `AIService` (строка 222+) после метода `generate_full_report` (строка 417) добавить:

```python
FALLBACK_KITCHEN: dict[str, dict] = {
    key: {"positions": [], "energies": [], "logic": "Не удалось подготовить объяснение. Попробуй ещё раз."}
    for key in [
        "main_archetype", "strengths", "shadow_side", "relationship_dynamics",
        "financial_scenario", "recurring_mistakes", "internal_conflicts",
        "life_cycles", "karmic_tail_analysis", "ancestral_programs",
        "life_purpose", "life_forecast",
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
            ]
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
        )
        result = await AIService._parse_json_response(response, _retry_callback)
        validated = KitchenReportResult(**result)
        return validated.model_dump()
    except Exception as e:
        logger.error("generate_kitchen_report failed: %s", e, exc_info=True)
        return FALLBACK_KITCHEN
```

Также добавить `KitchenReportResult` в импорт (строка 12-17):
```python
from core.schemas import (
    CompatibilityFullResult,
    DailyInsightResult,
    FullReportResult,
    KitchenReportResult,
    MiniAnalysisResult,
)
```

---

### 5. `nura_app/core/tasks.py` — параллельная генерация кухни в _process_full_report

В функции `_process_full_report` (строка 197) изменить строку 206:

Было:
```python
analysis = await AIService.generate_full_report(birth_date, matrix)
```

Стало:
```python
from asyncio import gather
analysis_task = AIService.generate_full_report(birth_date, matrix)
kitchen_task = AIService.generate_kitchen_report(birth_date, matrix)
analysis, kitchen_analysis = await gather(analysis_task, kitchen_task)
```

Затем в вызове `report_repo.create` (строка 257-263) добавить `kitchen_analysis=kitchen_analysis`:

```python
report = await report_repo.create(
    user_id=uid,
    report_type=ReportType.FULL,
    token=token,
    matrix_data=matrix_dict,
    ai_analysis=analysis,
    kitchen_analysis=kitchen_analysis,
)
```

---

### 6. `nura_app/core/repositories/report.py` — добавить kitchen_analysis в create

В методе `create` (строка 29-45) добавить параметр:

```python
async def create(
    self,
    user_id: uuid.UUID,
    report_type: ReportType,
    token: str,
    matrix_data: dict[str, Any] | None = None,
    ai_analysis: dict[str, Any] | None = None,
    kitchen_analysis: dict[str, Any] | None = None,
) -> Report:
    report = Report(
        id=uuid.uuid4(),
        user_id=user_id,
        report_type=report_type.value,
        token=token,
        matrix_data=matrix_data,
        ai_analysis=ai_analysis,
        kitchen_analysis=kitchen_analysis,
    )
    return await self.add(report)
```

---

### 7. `nura_app/api/routes/reports.py` — эндпоинт /{token}/kitchen

Добавить новый эндпоинт после `serve_report_pdf` (строка 89):

```python
@router.get("/{token}/kitchen")
async def serve_kitchen_analysis(token: str):
    session_factory = get_async_sessionmaker()
    report_repo = ReportRepository(session_factory)
    report = await report_repo.get_by_token(token)

    if report is None or report.kitchen_analysis is None:
        return PlainTextResponse("Kitchen analysis not found", status_code=404)

    return report.kitchen_analysis
```

---

## Проверка

После реализации:
```bash
ruff check nura_app/core/schemas/__init__.py nura_app/core/models.py nura_app/core/services/ai.py nura_app/core/tasks.py nura_app/core/repositories/report.py nura_app/api/routes/reports.py
ruff check --fix .
pytest tests/ -x -q
```
