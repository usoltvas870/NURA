# Двухслойная архитектура отчётов: пользовательский слой + кухонный слой

> Идея: пользователь видит тёплый, человеческий разбор от NURA.  
> Под капотом — всегда может открыть расчёты, арканы, логику цепочек.

---

## 1. Концепция

| Слой | Кому | Что показывает | Тон |
|------|------|----------------|-----|
| **User Layer** (по умолчанию) | Пользователю | Глубокий разбор жизни, отношений, денег, талантов человеческим языком | Тёплая подруга NURA, без эзотерики |
| **Kitchen Layer** (скрыт, открывается кнопкой) | Любопытному пользователю | Таблицу энергий по позициям, цитаты арканов, цепочку расчёта | Нейтральный, техничный, без AI-литературы |

---

## 2. Что меняется в коде

### 2.1 Новый промпт: `core/prompts/kitchen_report.txt`

Задача — объяснить **почему** AI сделал такие выводы, ссылаясь на конкретные числа и позиции матрицы.

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

Верни ТОЛЬКО валидный JSON по схеме ниже.
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

### 2.2 Новая схема: `core/schemas/kitchen.py`

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

### 2.3 Новый метод в `AIService` (`core/services/ai.py`)

```python
@staticmethod
async def generate_kitchen_report(
    birth_date: str, matrix_data: "MatrixData | dict"
) -> dict:
    # Загружает kitchen_report.txt, форматирует, шлёт в DeepSeek
    # Парсит JSON, валидирует KitchenReportResult
    # Возвращает dict или FALLBACK_KITCHEN
```

Параметры: `temperature=0.3` (меньше творчества, больше точности), `max_tokens=8000`.

### 2.4 Два поля в `ReportResponse` / БД

В модели отчёта (не затрагивая существующую миграцию без нужды):

```python
class ReportResponse(BaseModel):
    ...
    ai_analysis: dict | None          # существует (User Layer)
    kitchen_analysis: dict | None     # новое (Kitchen Layer)
```

В БД: новое поле `kitchen_analysis` (JSONB, nullable) в таблице reports.

Миграция:
```sql
ALTER TABLE reports ADD COLUMN kitchen_analysis JSONB;
```

### 2.5 Генерация Kitchen Layer

**Вариант A (рекомендуемый) — параллельная генерация.**
При запросе полного отчёта запускаются два AI-запроса одновременно:
- `generate_full_report` → сохраняется в `ai_analysis`
- `generate_kitchen_report` → сохраняется в `kitchen_analysis`

Пользователь ничего не ждёт дольше — оба запроса параллельны (asyncio.gather).

**Вариант B — ленивая генерация (по требованию).**
Kitchen слой генерируется только когда пользователь нажал "Показать расчёт".
Плюс: экономия токенов (не все откроют).
Минус: задержка при первом открытии.

Рекомендуется A — пользовательский опыт плавнее, да и кухонный слой для премиум-пользователей будет частью ценности.

### 2.6 Кнопка в боте / на странице отчёта

**В Telegram** — новая кнопка под отчётом или инлайн:
```
[🧮 Показать расчёт]
```

**На HTML-странице отчёта** — переключатель / аккордеон:
```
▸ Показать, как NURA это посчитала
```
При клике — AJAX-запрос `/api/report/{token}/kitchen` или данные уже вшиты в страницу (второй JSON).

### 2.7 Эндпоинт для Kitchen Layer

Добавить в `api/routes/`:

```python
@router.get("/report/{token}/kitchen")
async def get_kitchen_analysis(token: str, ...):
    # Достаёт отчёт, возвращает kitchen_analysis
    # Если нет — 404 или генерирует на лету (ленивый вариант)
```

---

## 3. Детали реализации

### 3.1 Параллельный вызов AI

```python
# В сервисе, который собирает отчёт:
from asyncio import gather

async def generate_full_with_kitchen(birth_date: str, matrix_data):
    user_task = AIService.generate_full_report(birth_date, matrix_data)
    kitchen_task = AIService.generate_kitchen_report(birth_date, matrix_data)
    user_result, kitchen_result = await gather(user_task, kitchen_task)
    return {
        "ai_analysis": user_result,
        "kitchen_analysis": kitchen_result,
    }
```

### 3.2 Отображение в HTML-шаблоне

В `templates/reports/`:
- Секция скрыта по умолчанию (`display: none`)
- Кнопка "Показать расчёт" переключает видимость
- Данные в переменной `kitchen_data`, вшитой в `<script>` или подгружаемой через fetch

---

## 4. Изменяемые файлы (полный список)

| Файл | Что делаем |
|------|-----------|
| `core/prompts/kitchen_report.txt` | **NEW** — промпт для кухонного слоя |
| `core/schemas/__init__.py` | Добавить `KitchenEntry`, `KitchenReportResult` |
| `core/services/ai.py` | Добавить `generate_kitchen_report()` |
| `core/services/report.py` | Добавить генерацию кухни параллельно или лениво |
| `api/routes/report.py` или новый файл | **NEW** — эндпоинт `/report/{token}/kitchen` |
| `bot/handlers/profile.py` | Добавить кнопку "Показать расчёт" + обработчик |
| `bot/keyboards/main_menu.py` | Добавить кнопку в разметку |
| `templates/reports/full_report.html` | Добавить блок кухонного слоя (скрытый + кнопка) |
| `core/schemas.py` → `core/models/report.py` (или аналоги) | Миграция: поле `kitchen_analysis` в таблице reports |

---

## 5. Риски и оценки

| Риск | Решение |
|------|---------|
| Рост токенов ×2 | Kitchen-промпт короче (не нужно генерировать связный текст, только факты), `temperature=0.3`, `max_tokens=8000` vs 16000 для full |
| Задержка при параллельном вызове | `asyncio.gather` — время = max(обеих), не сумма. Практически ~3-5 секунд |
| Пользователь не поймёт кухню | Кухонный слой опционален, скрыт за кнопкой, без перегрузки |
| Дублирование AI-логики | Kitchen не дублирует вывод — он объясняет уже сделанные выводы через конкретные позиции |

---

## 6. Приоритет (MVP → v2)

**MVP** — базовая двухслойность:
- Kitchen промпт + схема
- Kitchen метод в AI сервисе
- Параллельная генерация при full report
- Кнопка в боте "Показать расчёт" → выдаёт кухонный JSON текстом

**v2** — визуальная кухня:
- Аккордеон в HTML-отчёте
- Подсветка позиций матрицы
- Ссылки на описание арканов

---

## 7. Связь с пользовательским опытом

Идея:
> "Я не просто читаю красивые слова — я вижу, что за ними стоит конкретный расчёт.
> 4-я энергия в левом углу + 7-я в центре = меня учили быть структурированным,
> но моя суть — прорыв. Это про меня."

Пользователь получает:
- **Понимание** — не просто ответ, а "как это работает"
- **Доверие** — видит, что всё считается, не "AI наболтал"
- **Глубину** — может изучать Матрицу через кухонный слой, возвращаться к нему

Технически — 1 день, 4-5 файлов, пара часов работы DeepSeek.
