# Апгрейд платного отчёта NURA — 10 шагов

> База: `docs/report-upgrade-plan.md` — прочитай перед стартом.
> Каждый шаг — один Task (субагент). Запускать строго по порядку.
>
> **ВАЖНО: Все файлы — относительно `nura_app/`.**
> Рабочая директория: `C:\git\NURA\nura_app\`.
> Пример: файл `core/prompts/full_report.txt` → полный путь `nura_app/core/prompts/full_report.txt`.

## Легенда моделей

| Метка | Модель | Когда |
|-------|--------|-------|
| ⚡ Flash | DeepSeek V4 Flash | CRUD, одиночные файлы, шаблоны, стили |
| 🔥 Pro | DeepSeek V4 Pro | 2+ модуля, архитектура, сложная логика |
| 📝 Kimi | Kimi K2.6 | Промпт-инжиниринг, длинные тексты |

---

## ШАГ 1 — Схема + fallback + max_tokens + аркан года

**Модель:** 🔥 Pro (затрагивает 2+ модуля: schemas, ai.py, matrix.py)

**По плану:** §1.4, §4.1, §4.3

**Файлы:** `nura_app/core/schemas.py`, `nura_app/core/services/ai.py`, `nura_app/core/services/matrix.py`

**Промпт:**
```
Задача: расширить FullReportResult в nura_app/core/schemas.py, обновить FALLBACK_FULL
в nura_app/core/services/ai.py, увеличить max_tokens, добавить методы аркана года
в MatrixService в nura_app/core/services/matrix.py.

--- ЧАСТЬ 1: nura_app/core/schemas.py ---

Текущий класс FullReportResult:
class FullReportResult(BaseModel):
    main_archetype: str
    strengths: str
    shadow_side: str
    relationship_dynamics: str
    financial_scenario: str
    recurring_mistakes: str
    internal_conflicts: str
    life_cycles: str
    ai_recommendations: str

Новая версия (каждое поле с Field, min_length, max_length, description):

main_archetype: str = Field(..., min_length=400, max_length=1200,
    description="глубокий разбор главного архетипа, жизненная стратегия, стиль решений")
strengths: str = Field(..., min_length=300, max_length=1000,
    description="сильные стороны, таланты, ресурсы, врождённые способности")
shadow_side: str = Field(..., min_length=300, max_length=1000,
    description="теневая сторона, слепые пятна, зоны роста")
relationship_dynamics: str = Field(..., min_length=350, max_length=1000,
    description="динамика отношений, паттерны привязанности, тип партнёра")
financial_scenario: str = Field(..., min_length=400, max_length=1200,
    description="финансовый сценарий, каналы дохода, блоки, стратегии")
recurring_mistakes: str = Field(..., min_length=250, max_length=800,
    description="повторяющиеся ошибки, циклы и паттерны")
internal_conflicts: str = Field(..., min_length=300, max_length=1000,
    description="внутренние конфликты, противоречия между энергиями")
life_cycles: str = Field(..., min_length=250, max_length=800,
    description="жизненные циклы, периоды подъёма и спада")
ai_recommendations: str = Field(..., min_length=300, max_length=1500,
    description="рекомендации на 7 дней, привязанные к позициям матрицы")

# Новые поля
karmic_tail_analysis: str = Field(..., min_length=400, max_length=1200,
    description="кармический хвост: причина→следствие→урок, как выйти из цикла")
ancestral_programs: str = Field(..., min_length=400, max_length=1200,
    description="родовые программы: линия отца, линия матери, влияние на жизнь")
life_purpose: str = Field(..., min_length=400, max_length=1200,
    description="предназначение: линия неба, кармический дар, денежный канал, профессии")
life_forecast: str = Field(..., min_length=300, max_length=1000,
    description="прогноз периодов: ключевые возраста, энергия года, 3-летний прогноз")

--- ЧАСТЬ 2: core/services/ai.py ---

2.1. Расширить FALLBACK_FULL (строка 116): добавить 4 новых ключа:

"karmic_tail_analysis": (
    "Твой кармический хвост зашифрован в нижней части матрицы. "
    "Мне нужно ещё немного времени, чтобы расшифровать его полностью. "
    "Попробуй запросить разбор повторно."
),
"ancestral_programs": (
    "Родовые программы видны по линии земли. Я подготовлю точный "
    "разбор через минуту."
),
"life_purpose": (
    "Твоё предназначение заложено в линии неба. Я вернусь с "
    "конкретным анализом талантов и денежного канала."
),
"life_forecast": (
    "Прогноз жизненных периодов строится на аркане текущего возраста. "
    "Дай мне минуту для точного расчёта."
)

2.2. FULL_REPORT_PARAMS (строка 186): max_tokens = 8000 → 16000

--- ЧАСТЬ 3: core/services/matrix.py ---

3.1. Добавить метод calculate_year_arcana(birth_date, target_year) -> int:
- Распарсить birth_date (формат "DD.MM.YYYY")
- Вычислить возраст = target_year - birth_date.year
- Если возраст < 0 → вернуть 22
- Применить sum_digits к числу возраста
- Пример: "15.08.1995", 2026 → возраст 31 → 3+1=4

3.2. Добавить метод calculate_life_periods(birth_date) -> dict:
- Вычислить аркан для возрастов: 0, 17, 25, 33, 40, 50, 60, 70
- Вернуть {"age_0": <аркан>, "age_17": <аркан>, ...}

3.3. Обновить format_for_prompt: добавить в конец блок:
"== Жизненные периоды =="
Для каждого периода: "17 лет: Энергия (5) Иерофант"
"Текущий год (2026): Энергия (4) Император"

Импорт: from datetime import date добавить в начало файла.

После выполнения проверь (из `nura_app/`):
- ruff check core/schemas.py core/services/ai.py core/services/matrix.py --fix
```

---

## ШАГ 2 — Промпт full_report.txt

**Модель:** 📝 Kimi (промпт-инжиниринг)

**По плану:** §1.1–1.4, §4.2

**Файлы:** `nura_app/core/prompts/full_report.txt`

**Промпт:**
```
Файл: nura_app/core/prompts/full_report.txt.

Задача: полностью переработать промпт генерации полного отчёта.

Текущий промпт — 28 строк, генерирует 9 полей. Нужно расширить до 13 полей.

Требования к новому промпту:

1. Сохранить структуру: {chain_of_thought} + вступление + {matrix_text}
   + инструкция + JSON-схема. matrix_text уже обновлён и содержит
   жизненные периоды (арканы по возрастам и текущий год).

2. Каждый раздел — минимум 4-5 предложений конкретного разбора.
   Запретить общие фразы и клише.

3. Новые разделы (добавить в схему):

   "karmic_tail_analysis":
   - Низ (причина из прошлого) — какой сценарий тянется
   - Центр (следствие сейчас) — как проявляется в жизни
   - Верх (урок) — что осознать для выхода из цикла
   - Практический вывод с конкретным действием

   "ancestral_programs":
   - Линия отца (G) — программы по мужской линии
   - Линия матери (I) — программы по женской линии
   - Как они взаимодействуют с центром (E)
   - Что взять как ресурс, что трансформировать

   "life_purpose":
   - Кармический дар (F) — духовный ресурс
   - Как центр (E) направляет дар в деятельность
   - Денежный канал (H) — монетизация предназначения
   - Конкретные профессиональные ниши

   "life_forecast":
   - Текущий возраст и его архетипическая энергия
   - Ключевые возрастные периоды и их задачи
   - Ближайший год — детальный разбор
   - 3-летняя перспектива

4. Усилить требования к существующим полям:
   - main_archetype: +жизненная стратегия, стиль решений, ключевая фраза
   - financial_scenario: +конкретные профессии, финансовые стратегии
   - relationship_dynamics: +тип партнёра (точка отношений), паттерн входа/выхода
   - ai_recommendations: разбить на 3 категории (тело/ум/дух)

5. Напоминание о тоне: на "ты", без эзотерики, без страха, конкретно,
   ссылаться на конкретные арканы и позиции матрицы.

6. Схема JSON в промпте — с расширенными описаниями каждого поля
   (не просто "<текст>", а что именно писать в этом разделе).

Верни ПОЛНЫЙ текст нового full_report.txt.
```

---

## ШАГ 3 — CoT-инструкция

**Модель:** ⚡ Flash

**По плану:** §4.2

**Файлы:** `nura_app/core/prompts/cot_instruction.txt`

**Промпт:**
```
Файл: nura_app/core/prompts/cot_instruction.txt.

Задача: дополнить CoT-инструкцию новыми шагами для кармического хвоста,
родовых программ, предназначения и прогноза периодов.

Текущие шаги:
1. Определи главный архетип
2. Посмотри на кармический хвост
3. Исследуй зоны
4. Пройди по линиям
5. Найди конфликты
6. Сформулируй практические рекомендации
7. Проверь тон

Что изменить:

Шаг 2 — расширить: «Какая ключевая фраза каждого из трёх арканов хвоста?
Какую историю они рассказывают вместе? Как причина из прошлого (низ)
создаёт следствие в настоящем (центр)? Какой урок (верх) нужно усвоить?»

Шаг 4 — разбить на подшаги:
4.1 Линия отношений (левый → центр → правый)
4.2 Линия денег (верх → центр → низ)
4.3 Линия неба / предназначение (F → E → H)
4.4 Линия земли / родовые программы (G → E → I)
Каждый подшаг с конкретными вопросами для анализа.

Добавить Шаг 8 — Жизненные периоды:
«Посмотри на вычисленные арканы жизненных периодов. Какая энергия
у текущего возраста человека? Какие задачи решаются в этом возрасте?
Какой аркан у ближайшего года — что он несёт?»

Шаг 6 (рекомендации) — дополнить: «Разбей 7 советов на категории:
тело, ум, дух. Каждый совет с конкретным арканом и действием,
а не абстракцией.»

Верни ПОЛНЫЙ текст нового cot_instruction.txt.
```

---

## ШАГ 4 — Data pipeline в tasks.py

**Модель:** ⚡ Flash

**По плану:** §1.1–1.3 (раздел «Данные»)

**Файлы:** `nura_app/core/tasks.py`

**Промпт:**
```
Файл: nura_app/core/tasks.py, функция _process_full_report (строка 198).

Задача: расширить словарь matrix_raw, который передаётся в шаблон.

Текущий matrix_raw (строка 217) — 9 ключей:
center, top, bottom, left, right, talent_zone, comfort_zone,
portrait_zone, karmic_tail

Добавить в конец словаря:
- sky_line: list[int] = matrix.sky_line
- earth_line: list[int] = matrix.earth_line
- relationship_line: list[int] = matrix.relationship_line
- money_line: list[int] = matrix.money_line
- relationship_point: int = matrix.relationship_point
- inner_f: int = matrix.inner_f
- inner_g: int = matrix.inner_g
- inner_h: int = matrix.inner_h
- inner_i: int = matrix.inner_i
- arcana_names: dict = matrix.arcana_names

MatrixService.calculate() уже возвращает все эти поля в MatrixData.
Нужно только добавить их в словарь.

Также — добавить в report_data:
- "life_periods": MatrixService.calculate_life_periods(birth_date)
  (импортировать MatrixService из core.services.matrix — уже импортирован)
- "current_year_arcana": MatrixService.calculate_year_arcana(birth_date, date.today().year)
  (добавить from datetime import date если нет)

После выполнения: ruff check core/tasks.py --fix
```

---

## ШАГ 5 — Новые шаблоны секций (karmic_tail + ancestral + purpose + forecast)

**Модель:** ⚡ Flash

**По плану:** §1.1–1.4

**Файлы:** создать 4 файла в `nura_app/frontend/reports/templates/`

**Промпт:**
```
Задача: создать 4 новых шаблона секций. Дизайн-система: цвета из _styles.html
(--orange, --green, --gold, --card-bg, --line, --radius-*, --space-*).

--- Файл 1: _section_karmic_tail.html ---

<section class="report-section section-karmic-tail">
  <div class="section-header">
    <div class="section-accent-bar"></div>
    <h2>Кармический хвост</h2>
  </div>
  <div class="section-body">
    <p>{{ analysis.karmic_tail_analysis }}</p>
  </div>
  <div class="karmic-chain">
    <div class="karmic-link cause">
      <span class="karmic-link-label">Причина</span>
      <span class="karmic-link-num">{{ matrix.karmic_tail[0] if matrix.karmic_tail else '' }}</span>
    </div>
    <div class="karmic-arrow">→</div>
    <div class="karmic-link effect">
      <span class="karmic-link-label">Следствие</span>
      <span class="karmic-link-num">{{ matrix.karmic_tail[1] if matrix.karmic_tail else '' }}</span>
    </div>
    <div class="karmic-arrow">→</div>
    <div class="karmic-link lesson">
      <span class="karmic-link-label">Урок</span>
      <span class="karmic-link-num">{{ matrix.karmic_tail[2] if matrix.karmic_tail else '' }}</span>
    </div>
  </div>
</section>

--- Файл 2: _section_ancestral.html ---

<section class="report-section section-ancestral">
  <div class="section-header">
    <div class="section-accent-bar"></div>
    <h2>Родовые программы</h2>
  </div>
  <div class="section-body">
    <p>{{ analysis.ancestral_programs }}</p>
  </div>
</section>

--- Файл 3: _section_purpose.html ---

<section class="report-section section-purpose">
  <div class="section-header">
    <div class="section-accent-bar"></div>
    <h2>Предназначение</h2>
  </div>
  <div class="section-body">
    <p>{{ analysis.life_purpose }}</p>
  </div>
</section>

--- Файл 4: _section_forecast.html ---

<section class="report-section section-forecast">
  <div class="section-header">
    <div class="section-accent-bar"></div>
    <h2>Жизненные периоды</h2>
  </div>
  <div class="section-body">
    <p>{{ analysis.life_forecast }}</p>
  </div>
  {% if current_year_arcana is defined %}
  <div class="year-arcana-block">
    <span class="year-label">Твой год</span>
    <span class="year-value">{{ current_year_arcana }} аркан</span>
  </div>
  {% endif %}
</section>

Верни содержимое всех 4 файлов.
```

---

## ШАГ 6 — Матрица (развёрнутая) + Dashboard

**Модель:** ⚡ Flash

**По плану:** §3.1, §3.3

**Файлы:** заменить `nura_app/frontend/reports/templates/_matrix_3x3.html`, создать `_dashboard.html`

**Промпт:**
```
Задача 1: переработать _matrix_3x3.html — развёрнутая визуализация матрицы.

Вместо простой сетки 3×3 с номерами — полноценная визуализация:
- Основная сетка 3×3 (каждая ячейка: номер + название аркана)
- Центр — с оранжевым свечением
- Под сеткой — 4 линии (небо, земля, отношения, деньги) в виде горизонтальных полос
  из 3 кружков с номерами, соединённых линиями
- Кармический хвост в виде цепочки под линиями
- Точка отношений (если есть)

Данные: все поля из matrix (center, top, bottom, left, right, talent_zone,
comfort_zone, portrait_zone, karmic_tail, sky_line, earth_line,
relationship_line, money_line, relationship_point, arcana_names).

CSS не писать — будет добавлен в ШАГЕ 8. Использовать классы:
matrix-grid, matrix-cell (с подклассом center), matrix-lines,
matrix-line (sky/earth/relationship/money), matrix-line-dot,
matrix-line-connector, matrix-line-label.

Задача 2: создать _dashboard.html — резюме «Твоя матрица за 30 секунд».

5 карточек в grid:
- Архетип (номер + название, цвет оранжевый)
- Талант (matrix.talent_zone, название из arcana_names, зелёный)
- Вызов (matrix.karmic_tail[1], золотой)
- Урок (matrix.karmic_tail[2], оранжевый)
- Ресурс (matrix.comfort_zone, название из arcana_names, зелёный)

Шаблон dashboard:
<div class="dashboard">
  <div class="dashboard-grid">
    <div class="dashboard-card card-archetype">
      <span class="card-label">Архетип</span>
      <span class="card-number">{{ archetype_number }}</span>
      <span class="card-name">{{ archetype_name }}</span>
    </div>
    <div class="dashboard-card card-talent">
      <span class="card-label">Талант</span>
      <span class="card-number">{{ matrix.talent_zone }}</span>
      <span class="card-name">{{ matrix.arcana_names.get('talent_zone', '') if matrix.arcana_names else '' }}</span>
    </div>
    <div class="dashboard-card card-challenge">
      <span class="card-label">Вызов</span>
      <span class="card-number">{{ matrix.karmic_tail[1] if matrix.karmic_tail else '' }}</span>
      <span class="card-name">—</span>
    </div>
    <div class="dashboard-card card-lesson">
      <span class="card-label">Урок</span>
      <span class="card-number">{{ matrix.karmic_tail[2] if matrix.karmic_tail else '' }}</span>
      <span class="card-name">—</span>
    </div>
    <div class="dashboard-card card-resource">
      <span class="card-label">Ресурс</span>
      <span class="card-number">{{ matrix.comfort_zone }}</span>
      <span class="card-name">{{ matrix.arcana_names.get('comfort_zone', '') if matrix.arcana_names else '' }}</span>
    </div>
  </div>
</div>

Верни полное содержимое обоих файлов.
```

---

## ШАГ 7 — Сборка full_report.html + визуализация линий

**Модель:** ⚡ Flash

**По плану:** §3.2, итоговая таблица структуры

**Файлы:** `nura_app/frontend/reports/templates/full_report.html`, создать `_line_visual.html`

**Промпт:**
```
Две задачи: создать компонент line_visual и собрать full_report.html.

--- Задача 1: _line_visual.html ---

Include-компонент для отображения линии матрицы между секциями.
Принимает через with: line_class, line_title, line_data, line_emoji.

<div class="line-visual {{ line_class }}">
  <div class="line-visual-header">
    <span class="line-visual-emoji">{{ line_emoji }}</span>
    <span class="line-visual-title">{{ line_title }}</span>
  </div>
  <div class="line-visual-pips">
    {% for arcana in line_data %}
    <div class="line-pip">
      <span class="line-pip-num">{{ arcana }}</span>
    </div>
    {% if not loop.last %}<span class="line-pip-connector"></span>{% endif %}
    {% endfor %}
  </div>
</div>

--- Задача 2: full_report.html ---

Обновить full_report.html до итогового порядка секций:

1. Cover ({% include '_cover.html' %})
2. Dashboard ({% include '_dashboard.html' %})
3. Архетип личности (_section_card section_class='archetype')
4. Кармический хвост ({% include '_section_karmic_tail.html' %})
5. Родовые программы ({% include '_section_ancestral.html' %})
6. Предназначение ({% include '_section_purpose.html' %})
7. Сильные стороны (_section_card section_class='strengths')
8. Теневая сторона (_section_card section_class='shadow')
9. Динамика отношений (_section_card section_class='relationships')
10. {% if matrix.relationship_line %} — вставить _line_visual с линией отношений
11. Деньги и карьера (_section_card section_class='money')
12. {% if matrix.money_line %} — вставить _line_visual с линией денег
13. Жизненные периоды ({% include '_section_forecast.html' %})
    ВАЖНО: старый _section_card с section_class='cycles' — УДАЛИТЬ
14. Повторяющиеся сценарии (_section_card section_class='mistakes')
15. Внутренние конфликты (_section_card section_class='conflicts')
16. Рекомендации 7 дней (существующий блок)
17. Совместимость ({% if compatibility %} — НЕ МЕНЯТЬ)
18. Footer ({% include '_footer.html' %})

Верни ПОЛНЫЙ файл full_report.html. Не менять существующие блоки
cover, compatibility, recommendations — только добавить новые include
и переставить порядок.
```

---

## ШАГ 8 — CSS для всех новых элементов

**Модель:** ⚡ Flash

**По плану:** §3.1–3.3

**Файлы:** `nura_app/frontend/reports/templates/_styles.html`

**Промпт:**
```
Файл: nura_app/frontend/reports/templates/_styles.html.

Задача: добавить CSS для всех новых элементов. Добавить В КОНЕЦ файла
(перед @media print).

--- Блок 1: Dashboard ---
.dashboard { margin: var(--space-xl) 0; }
.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: var(--space-sm);
}
.dashboard-card {
  background: var(--card-bg);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  padding: var(--space-md);
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 4px;
  page-break-inside: avoid;
}
.card-label {
  font-size: 11px; color: var(--muted);
  text-transform: uppercase; letter-spacing: 1px;
}
.card-number {
  font-family: var(--font-heading);
  font-size: 36px; line-height: 1;
}
.card-name { font-size: 14px; color: rgba(245,243,238,0.7); }
.card-archetype .card-number { color: var(--orange); }
.card-talent .card-number { color: var(--green); }
.card-challenge .card-number { color: var(--gold); }
.card-lesson .card-number { color: var(--orange); }
.card-resource .card-number { color: var(--green); }

--- Блок 2: Karmic chain ---
.karmic-chain {
  display: flex; align-items: center; justify-content: center;
  gap: var(--space-sm); margin-top: var(--space-md);
}
.karmic-link {
  width: 64px; height: 64px; border-radius: 50%;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  border: 2px solid; page-break-inside: avoid;
}
.karmic-link.cause { border-color: var(--gold); }
.karmic-link.effect { border-color: var(--orange); }
.karmic-link.lesson { border-color: var(--green); }
.karmic-link-label { font-size: 10px; color: var(--muted); text-transform: uppercase; }
.karmic-link-num {
  font-family: var(--font-heading); font-size: 22px;
  color: var(--white);
}
.karmic-arrow { font-size: 20px; color: var(--muted); }

--- Блок 3: Year arcana block ---
.year-arcana-block {
  margin-top: var(--space-md);
  padding: var(--space-md);
  background: rgba(217,122,50,0.08);
  border: 1px solid rgba(217,122,50,0.2);
  border-radius: var(--radius-sm);
  text-align: center;
}
.year-label { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; display: block; margin-bottom: 4px; }
.year-value { font-family: var(--font-heading); font-size: 28px; color: var(--orange); }

--- Блок 4: Line visual ---
.line-visual {
  background: var(--card-soft);
  border-radius: var(--radius-md);
  padding: var(--space-md);
  margin-bottom: var(--space-md);
  display: flex; align-items: center; gap: var(--space-lg);
  page-break-inside: avoid;
}
.line-visual-header { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.line-visual-emoji { font-size: 20px; }
.line-visual-title { font-family: var(--font-heading); font-size: 16px; }
.line-visual.relationship .line-visual-title { color: var(--orange); }
.line-visual.money .line-visual-title { color: var(--green); }
.line-visual.sky .line-visual-title { color: var(--orange); }
.line-visual.earth .line-visual-title { color: var(--gold); }
.line-visual-pips { display: flex; align-items: center; gap: 8px; }
.line-pip {
  width: 40px; height: 40px; border-radius: 50%;
  border: 2px solid; display: grid; place-items: center;
}
.line-visual.relationship .line-pip { border-color: var(--orange); }
.line-visual.money .line-pip { border-color: var(--green); }
.line-visual.sky .line-pip { border-color: var(--orange); }
.line-visual.earth .line-pip { border-color: var(--gold); }
.line-pip-num {
  font-family: var(--font-heading); font-size: 18px;
  color: var(--white);
}
.line-pip-connector {
  width: 32px; height: 2px; background: var(--line); flex-shrink: 0;
}

--- Блок 5: Section accent colors for new sections ---
.section-karmic-tail .section-accent-bar { background: var(--gold); }
.section-ancestral .section-accent-bar { background: var(--green); }
.section-purpose .section-accent-bar { background: var(--orange); }
.section-forecast .section-accent-bar { background: var(--green); }

--- Блок 6: Print styles for new elements ---
@media print {
  .dashboard-card { border: 1px solid #ddd; }
  .karmic-link { border-color: #999 !important; print-color-adjust: exact; }
  .year-arcana-block { border: 1px solid #ddd; }
  .line-visual { border: 1px solid #eee; }
  .card-number, .karmic-link-num, .year-value, .line-pip-num { color: #1a1a1a !important; }
  .line-pip { border-color: #ccc !important; }
  .dashboard-card .card-number { color: #1a1a1a !important; }
  .card-archetype .card-number { color: #D97A32 !important; print-color-adjust: exact; }
  .card-talent .card-number { color: #355C4D !important; print-color-adjust: exact; }
  .card-challenge .card-number { color: #8C6A3B !important; print-color-adjust: exact; }
  .card-lesson .card-number { color: #D97A32 !important; print-color-adjust: exact; }
  .card-resource .card-number { color: #355C4D !important; print-color-adjust: exact; }
  .dashboard-card, .karmic-link, .year-arcana-block, .line-visual { page-break-inside: avoid; }
}

Верни ТОЛЬКО эти 6 блоков CSS (с комментариями-заголовками).
```

---

## ШАГ 9 — Углубление секций + чек-лист для рекомендаций

**Модель:** 🔥 Pro (затрагивает промпт + шаблон + сервис)

**По плану:** §2.1–2.3, §3.4

**Файлы:** `nura_app/core/prompts/full_report.txt` (проверить), `nura_app/frontend/reports/templates/_recommendation_day.html`, `nura_app/core/services/report.py`

**Промпт:**
```
Две параллельные задачи.

--- Задача 1: Проверить full_report.txt на глубину секций ---

Прочитать core/prompts/full_report.txt (уже обновлён в ШАГЕ 2).
Проверить, что требования к трём разделам включают:

main_archetype:
- Ключевая фраза архетипа
- Жизненная стратегия, стиль решений
- Реакция на кризисы
- Проявление в работе, отношениях, деньгах

financial_scenario:
- Конкретные профессии и ниши для этого архетипа
- Финансовые стратегии (актив/пассив, творчество/структура)
- Конкретные блоки в денежном мышлении (не общие «страх денег»)

relationship_dynamics:
- Тип партнёра (связь с точкой отношений)
- Паттерн входа (левый угол) и выхода (правый угол)
- Совместимость с 2-3 архетипами кратко

Если чего-то нет — дополнить промпт. Верни diff изменений.

--- Задача 2: Чек-лист для рекомендаций ---

2.1. Обновить frontend/reports/templates/_recommendation_day.html:

Текущая структура:
<div class="rec-day">
  <div class="rec-day-num">{{ day.number }}</div>
  <div class="rec-day-text">{{ day.text }}</div>
</div>

Новая структура:
<div class="rec-day">
  <div class="rec-day-check">
    <input type="checkbox" id="day-{{ day.number }}" class="rec-checkbox">
    <label for="day-{{ day.number }}" class="rec-check-label"></label>
  </div>
  <div class="rec-day-content">
    <div class="rec-day-header">
      <span class="rec-day-num">День {{ day.number }}</span>
      <span class="rec-day-category">{{ day.category if day.category else 'Практика' }}</span>
    </div>
    <div class="rec-day-text">{{ day.text }}</div>
  </div>
</div>

2.2. Обновить ReportService.parse_recommendations (core/services/report.py):
- После парсинга номера и текста, определять категорию по ключевым словам:
  "тело"/"физический"/"йога"/"дыхание"/"спорт"/"сон" → "Тело"
  "ум"/"мысли"/"анализ"/"изучение"/"чтение"/"план" → "Ум"
  "дух"/"медитация"/"осознанность"/"тишина"/"благодарность" → "Дух"
  иначе → "Практика"
- Возвращать список: [{"number": 1, "text": "...", "category": "Тело"}, ...]

2.3. Добавить CSS в _styles.html:
.rec-day-check { flex-shrink: 0; padding-top: 4px; }
.rec-checkbox { display: none; }
.rec-check-label {
  width: 22px; height: 22px; border: 2px solid var(--orange);
  border-radius: 4px; cursor: pointer; display: block;
  transition: background 0.2s;
}
.rec-checkbox:checked + .rec-check-label { background: var(--orange); }
.rec-day-content { flex: 1; }
.rec-day-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.rec-day-category { font-size: 11px; color: var(--green); text-transform: uppercase; letter-spacing: 1px; }
@media print { .rec-day-check { display: none; } }

Верни:
1. Diff для full_report.txt (или текст "всё ок")
2. Обновлённый _recommendation_day.html
3. Обновлённую функцию parse_recommendations
4. CSS-блок для _styles.html
```

---

## ШАГ 10 — Финальная интеграция и проверка

**Модель:** 🔥 Pro (затрагивает все модули)

**По плану:** весь документ

**Файлы:** Все изменённые

**Промпт:**
```
Финальная проверка целостности апгрейда.
Все пути — относительно nura_app/.

Проверить всё:

1. nura_app/core/schemas.py — FullReportResult содержит 13 полей
   (main_archetype, strengths, shadow_side, relationship_dynamics,
   financial_scenario, recurring_mistakes, internal_conflicts, life_cycles,
   ai_recommendations, karmic_tail_analysis, ancestral_programs,
   life_purpose, life_forecast)
   Каждое с Field(min_length=..., max_length=..., description=...).

2. nura_app/core/services/ai.py:
   - FALLBACK_FULL содержит 13 ключей (совпадает с FullReportResult)
   - FULL_REPORT_PARAMS: max_tokens = 16000

3. nura_app/core/services/matrix.py:
   - Есть calculate_year_arcana(birth_date, target_year) -> int
   - Есть calculate_life_periods(birth_date) -> dict
   - format_for_prompt выводит жизненные периоды

4. nura_app/core/prompts/cot_instruction.txt:
   - Шаг 2 расширен (кармический хвост детально)
   - Шаг 4 разбит на подшаги 4.1–4.4
   - Добавлен Шаг 8 (жизненные периоды)
   - Шаг 6 дополнен (категории тело/ум/дух)

5. nura_app/core/prompts/full_report.txt:
   - Схема JSON содержит 13 полей с развёрнутыми описаниями
   - main_archetype требует стратегию + стиль решений
   - financial_scenario требует профессии + стратегии
   - relationship_dynamics требует точку отношений + паттерны
   - ai_recommendations требует категории тело/ум/дух

6. nura_app/core/tasks.py _process_full_report:
   - matrix_raw содержит: center, top, bottom, left, right, talent_zone,
     comfort_zone, portrait_zone, karmic_tail, sky_line, earth_line,
     relationship_line, money_line, relationship_point, inner_f, inner_g,
     inner_h, inner_i, arcana_names
   - report_data содержит current_year_arcana, life_periods

7. nura_app/frontend/reports/templates/:
   - full_report.html: 16 секций + cover + footer
   - _matrix_3x3.html: развёрнутая версия с линиями
   - _dashboard.html: 5 карточек-резюме
   - _section_karmic_tail.html: текст + цепочка причина→следствие→урок
   - _section_ancestral.html: текст
   - _section_purpose.html: текст
   - _section_forecast.html: текст + блок года
   - _recommendation_day.html: чек-бокс + категория
   - _line_visual.html: полоса с 3 кружками

8. nura_app/frontend/reports/templates/_styles.html:
   - Стили для dashboard, karmic-chain, year-arcana-block, line-visual
   - Акцентные цвета для 4 новых секций
   - Стили для чек-боксов
   - Print-стили для всех новых элементов

Напиши скрипт проверки целостности (Python, без зависимостей):
- Проверить, что все 13 ключей FALLBACK_FULL совпадают с полями FullReportResult
- Проверить, что все include из full_report.html ведут на существующие файлы
- Проверить, что все CSS-классы из шаблонов определены в _styles.html
- Вывести отчёт: "✅ OK" или "❌ Проблема: ..."

После запусти ruff check . --fix и pytest, если есть тесты на report.
```

---

## Таблица зависимостей

| Шаг | Зависит от | Суть |
|-----|-----------|------|
| 1 | — | Схема + fallback + max_tokens + аркан года |
| 2 | 1 | Новый промпт full_report.txt |
| 3 | 1 | CoT-инструкция |
| 4 | 1 | Data pipeline в tasks.py |
| 5 | 4 | 4 новых шаблона секций |
| 6 | 4 | Развёрнутая матрица + dashboard |
| 7 | 5, 6 | Сборка full_report.html + line_visual |
| 8 | 5, 6, 7 | CSS для всех новых элементов |
| 9 | 2, 4 | Углубление секций + чек-лист |
| 10 | все | Финальная проверка |

**Порядок запуска:** 1 → 2 → 3 → 4 → (5 + 6 параллельно) → 7 → 8 → 9 → 10
