# NURA — Report Spec

> **STATUS: MIXED — CURRENT RENDERING + LEGACY WEB DELIVERY + TARGET**
>
> До Stage 2B не трактуйте web-link delivery как target. Product format задаёт [canonical spec](product/NURA_1_0_1_5_PRODUCT_SPEC.md), текущий gap — [current status](implementation/current-status.md).

> Актуально на 26.05.2026. Версия шаблона: V2 (`full_report_v2.html`).
> Источники истины: `nura_app/templates/reports/full_report_v2.html`, `nura_app/core/services/report.py`, `nura_app/core/schemas/__init__.py`.

---

## 1. Общая архитектура

### Форматы

| Формат | Реализован | Как генерируется |
|--------|-----------|-----------------|
| HTML (онлайн) | ✅ | `ReportService.render_report_v2_html()` |
| PDF (скачать) | ✅ | `ReportService.generate_pdf(html)` через WeasyPrint |
| Мини-разбор (бот) | ✅ | `generate_html_report()` → `mini_report.html` |
| HTML устаревший | 🗑 | `full_report.html` — не используется в продакшене |

### URL и доступ

```
/report/{token}          — HTML-рендер (GET)
/report/{token}/pdf      — PDF-генерация (GET)
/report/{token}/kitchen  — Kitchen API (JSON, GET)
```

`token` — уникальный UUID из таблицы `reports`. Время жизни токена не ограничено.

### Рендеринг (диспетчеризация)

`ReportService.render_report_html()` определяет тип по `report.report_type`:

```
MINI          → mini_report.html
FULL          → render_report_v2_html() → full_report_v2.html
COMPATIBILITY → full_report_v2.html (те же данные, другой заголовок)
FALLBACK_FULL → 202 «отчёт готовится» (детект через _is_fallback_analysis())
```

`_is_fallback_analysis(analysis)` — ищет маркеры заглушки в тексте (`analysis.main_archetype`).

---

## 2. Данные для подстановки

### 2.1 Структурные данные (вычисляются в коде, не через AI)

#### MatrixData (из БД + `MatrixService`)

| Переменная в шаблоне | Источник | Описание |
|---------------------|---------|----------|
| `matrix.center` | `MatrixData.center` | Центр матрицы |
| `matrix.top/bottom/left/right` | `MatrixData` | Четыре угла |
| `matrix.talent_zone` | `MatrixData.talent_zone` | Зона таланта |
| `matrix.comfort_zone` | `MatrixData.comfort_zone` | Зона комфорта |
| `matrix.portrait_zone` | `MatrixData.portrait_zone` | Личностный портрет |
| `matrix.karmic_tail` | `MatrixData.karmic_tail` | Список [0], [1], [2] — кармический хвост |
| `arcana_names` | `MatrixData.arcana_names` | Dict `{str(n): name}` для арканов 1–22 |

#### Данные пользователя

| Переменная в шаблоне | Источник |
|---------------------|---------|
| `user_name` | `User.full_name` |
| `birth_date_raw` | `User.birth_date` (строка YYYY-MM-DD) |
| `birth_date_formatted` | форматированная `DD.MM.YYYY` |
| `age` | вычисляется из `birth_date` |
| `report_number` | `Report.id` |
| `generated_at` | `Report.created_at` (day, month_name, year) |

#### Архетип

| Переменная в шаблоне | Источник |
|---------------------|---------|
| `archetype_number` | `matrix.center` |
| `archetype_roman` | roman numeral от `center` |
| `archetype_name` | `arcana_names[str(center)]` |
| `archetype_full` | полное название аркана |
| `archetype_key` | ключевое слово аркана |

#### Линии матрицы

| Переменная в шаблоне | Источник |
|---------------------|---------|
| `sky_line_nums` | `matrix.sky_line` (список арканов) |
| `earth_line_nums` | `matrix.earth_line` |
| `karmic_line_nums` | `matrix.karmic_tail` |
| `money_line_nums` | `matrix.money_line` |
| `father_line_nums` | `matrix.relationship_line` (отцовская) |
| `mother_line_nums` | `matrix.relationship_line` (материнская) |

#### Год и прогноз

| Переменная в шаблоне | Источник |
|---------------------|---------|
| `current_year` | текущий год |
| `year_arcana_number` | `MatrixService.calculate_year_arcana()` |
| `year_arcana_roman` | roman numeral |
| `year_arcana_name` | `arcana_names[year_arcana_number]` |
| `life_periods` | `MatrixService.calculate_life_periods()` → список nodes с `year`, `arcana`, `label` |
| `chakra_data` | `MatrixService.calculate_chakras()` → 7 чакр с `name`, `arcana`, `color`, `organs` |
| `daily_tarot_arcana` | аркан дня для S15 |

#### Кармический хвост (вычисленные тексты)

| Переменная в шаблоне | Источник |
|---------------------|---------|
| `karmic_cause` | первый аркан хвоста → название |
| `karmic_effect` | второй аркан хвоста → название |
| `karmic_lesson` | третий аркан хвоста → название |

#### SVG матрицы

| Переменная в шаблоне | Источник |
|---------------------|---------|
| `matrix_svg_cells` | список ячеек для SVG-сетки в S1 |

### 2.2 AI-поля (FullReportResult)

Все поля — строки, генерируются DeepSeek в Celery-задаче.

| Поле | Тип | Секция V2 | Статус |
|------|-----|----------|--------|
| `analysis.main_archetype` | str | S3 | ✅ |
| `analysis.karmic_tail_analysis` | str | S4 | ✅ |
| `analysis.ancestral_programs` | str | S5 | ✅ |
| `analysis.life_purpose` | str | S6 | ✅ |
| `analysis.strengths` | str | S7 | ✅ |
| `analysis.shadow_side` | str | S8 | ✅ |
| `analysis.relationship_dynamics` | str | S9 | ✅ |
| `analysis.financial_scenario` | str | S10 | ✅ |
| `analysis.recurring_mistakes` | str | S11 | ✅ |
| `analysis.internal_conflicts` | str | S12 | ✅ |
| `analysis.life_forecast` | str | S13 | ✅ |
| `analysis.ai_recommendations` | str | S14 (parsed) | ✅ |
| `analysis.life_cycles` | str | — | 🗑 в схеме, не отображается в V2 |
| `analysis.psychological_blocks` | str | — | 📋 шаблон есть, не интегрирован |
| `analysis.health_analysis` | str | — | 📋 шаблон есть, не интегрирован |

#### Парсинг AI-полей

**`parse_recommendations(text)`** — получает `analysis.ai_recommendations`:
- Разбивает по `\n(?=\d+\.)` (7 дней)
- Возвращает список `[{number, text, category}]`
- `category` определяется по ключевым словам: Тело / Ум / Дух / Практика

**`parse_psych_blocks(raw_text, arcana_names)`** — получает `analysis.psychological_blocks`:
- Regex-разбивка по `"Аркан N"`
- Извлекает: `belief`, `manifestation`, `strategy`
- Результат → `psych_blocks` (список блоков)
- [PLANNED] — вызывается в коде, но секция не добавлена в `full_report_v2.html`

### 2.3 Kitchen-данные (KitchenReportResult)

Генерируются отдельным AI-вызовом (/kitchen endpoint).

| Поле | Секции |
|------|--------|
| `kitchen_analysis.main_archetype.positions/energies/logic` | S3 (аккордеон "Почему я так думаю?") |
| Остальные 13 ключей | [PLANNED] — не отображаются в V2 |

Аккордеон в S3 — единственное место Kitchen-данных в V2.

---

## 3. CSS Design System

Все стили инлайново в `full_report_v2.html` (не внешний CSS-файл).

### CSS-переменные

```css
--bg:             #0A0E0C           /* основной фон */
--bg-page:        #0C1310           /* фон полотна */
--bg-soft:        #111613           /* мягкий фон */
--bg-card:        #0E1A14           /* фон карточек */

--ink:            #F2EFE7           /* основной текст */
--ink-soft:       rgba(242,239,231,0.78)  /* secondary */
--ink-mute:       rgba(242,239,231,0.52)  /* muted */
--ink-faint:      rgba(242,239,231,0.32)  /* very muted */

--line:           rgba(242,239,231,0.08)  /* тонкие линии */
--line-strong:    rgba(242,239,231,0.16)  /* линии с акцентом */

--m-bg:           #0E2419           /* фон секций матрицы */
--m-bg-soft:      #143527           /* мягкий фон матрицы */
--m-line:         rgba(151,197,161,0.18)  /* линии матрицы */
--m-accent:       #C9A55C           /* золото матрицы */
--m-accent-soft:  rgba(201,165,92,0.16)   /* золото мягкое */
--m-leaf:         #6BA37A           /* зелёный матрицы */

--t-bg:           #0F1830           /* фон секций таро */
--t-accent:       #D8B36A           /* золото таро */
--t-violet:       #7E7AC8           /* фиолетовый таро */

--reading-w:      720px             /* ширина чтения */
--radius-lg:      20px
--radius-md:      14px
--radius-sm:      10px
```

### Шрифты

Загружаются с Google Fonts:
- `Cormorant Garamond` — заголовки, архетип
- `DM Sans` — основной текст
- `JetBrains Mono` — номера арканов, технические данные

### Ключевые компоненты

| Компонент | Класс | Описание |
|-----------|-------|----------|
| Сайдбар | `.sidebar` | sticky, 260px, IntersectionObserver scroll tracking |
| Мобильное меню | `.mobile-nav` | hamburger, открывается по кнопке |
| Секция | `.section` | padding, border-bottom |
| Дашборд | `.dashboard-grid` | 5 карточек, 3-колонки desktop / 2-мобайл |
| Аккордеон kitchen | `.why` / `.why-btn` | только в S3 |
| Чекбоксы 7 дней | `.day-item` / `.day-check` | S14, JS click handler |
| Таймлайн | `.timeline` | S13, горизонтальный, узлы с годами |
| Чакры | `.chakra-row` | [PLANNED] в `_health_map.html` |

### @media print (WeasyPrint)

- Белый фон, чёрный текст
- Системные шрифты (Google Fonts не загружаются в WeasyPrint)
- A4, `page-break-before: always` на каждой секции
- Скрыты: `.sidebar`, `.mobile-nav`, `.why-btn`, `.section-actions`
- Показывается: `.print-toc` (оглавление 15+2 секции)

---

## 4. Структура полного отчёта (V2)

### S1 — Обложка ✅

**Шаблон:** inline в `full_report_v2.html`

Данные:
- `user_name`, `birth_date_formatted`, `age`
- `archetype_number`, `archetype_roman`, `archetype_name`, `archetype_full`, `archetype_key`
- `matrix_svg_cells` — SVG сетка матрицы
- `report_number`, `generated_at`

AI-поля: нет.

---

### S2 — Дашборд «За 30 секунд» ✅

**Шаблон:** inline в `full_report_v2.html`

5 карточек в сетке:

| Карточка | Данные |
|---------|--------|
| Архетип | `archetype_number`, `archetype_roman`, `archetype_name`, `archetype_key` |
| Зона таланта | `matrix.talent_zone`, `arcana_names[talent_zone]` |
| Зона сложностей | `matrix.comfort_zone`, `arcana_names[comfort_zone]` |
| Предназначение | `matrix.portrait_zone`, `arcana_names[portrait_zone]` |
| Аркан года | `year_arcana_number`, `year_arcana_name`, `current_year` |

AI-поля: нет (полностью структурные).

---

### S3 — Архетип личности ✅

**Шаблон:** inline в `full_report_v2.html`

Данные:
- `analysis.main_archetype` — основной AI-текст
- `archetype_name`, `archetype_number`, `archetype_roman`
- Kitchen-аккордеон: `kitchen_analysis.main_archetype.positions`, `.energies`, `.logic`

Особенность: единственная секция с UI аккордеона "Почему я так думаю?" (`.why` блок).
Kitchen-аккордеон скрыт если `kitchen_analysis` отсутствует.

AI-поля: `main_archetype`

---

### S4 — Кармический хвост ✅

**Шаблон:** inline в `full_report_v2.html`

Данные:
- `analysis.karmic_tail_analysis` — AI-текст
- `karmic_cause`, `karmic_effect`, `karmic_lesson` — названия арканов 3 хвоста
- `matrix.karmic_tail[0/1/2]` — номера арканов

AI-поля: `karmic_tail_analysis`

---

### S5 — Родовые программы ✅

**Шаблон:** inline в `full_report_v2.html`

Данные:
- `analysis.ancestral_programs` — AI-текст
- `father_line_nums`, `mother_line_nums` — линии матрицы

AI-поля: `ancestral_programs`

---

### S6 — Предназначение ✅

**Шаблон:** inline в `full_report_v2.html`

Данные:
- `analysis.life_purpose` — AI-текст
- `matrix.portrait_zone`, `arcana_names[portrait_zone]`

AI-поля: `life_purpose`

---

### S7 — Таланты и сила ✅

**Шаблон:** inline в `full_report_v2.html`

Данные:
- `analysis.strengths` — AI-текст
- `matrix.talent_zone`, `sky_line_nums`

AI-поля: `strengths`

---

### S8 — Теневая сторона ✅

**Шаблон:** inline в `full_report_v2.html`

Данные:
- `analysis.shadow_side` — AI-текст
- `matrix.comfort_zone`

AI-поля: `shadow_side`

---

### S9 — Отношения ✅

**Шаблон:** inline в `full_report_v2.html`

Данные:
- `analysis.relationship_dynamics` — AI-текст
- `matrix.relationship_point`, `father_line_nums`, `mother_line_nums`

AI-поля: `relationship_dynamics`

---

### S10 — Деньги и карьера ✅

**Шаблон:** inline в `full_report_v2.html`

Данные:
- `analysis.financial_scenario` — AI-текст
- `money_line_nums`, `matrix.comfort_zone`

AI-поля: `financial_scenario`

---

### S11 — Повторяющиеся сценарии ✅

**Шаблон:** inline в `full_report_v2.html`

Данные:
- `analysis.recurring_mistakes` — AI-текст

AI-поля: `recurring_mistakes`

---

### S12 — Внутренние конфликты ✅

**Шаблон:** inline в `full_report_v2.html`

Данные:
- `analysis.internal_conflicts` — AI-текст

AI-поля: `internal_conflicts`

---

### S13 — Жизненные циклы и прогноз ✅

**Шаблон:** inline в `full_report_v2.html`

Данные:
- `analysis.life_forecast` — AI-текст прогноза
- `life_periods` — список nodes: `{year, arcana, label}` (из `calculate_life_periods()`)
- `year_arcana_number`, `year_arcana_name`, `current_year`

Отображение: горизонтальный таймлайн (`.timeline`) + AI-текст.

AI-поля: `life_forecast`

Примечание: поле `life_cycles` есть в `FullReportResult` (схеме), но в V2 не используется — заменено вычисленными `life_periods`.

---

### S14 — Семь дней ✅

**Шаблон:** inline в `full_report_v2.html`

Данные:
- `recommendations_parsed` — результат `parse_recommendations(analysis.ai_recommendations)`
- Каждый элемент: `{number, text, category}` (category: Тело / Ум / Дух / Практика)

Отображение: 7 карточек-дней с чекбоксами (`.day-check`). JS обрабатывает клик.

AI-поля: `ai_recommendations` (через `parse_recommendations`)

---

### S15 — Карта дня ✅

**Шаблон:** inline в `full_report_v2.html`

Данные:
- `daily_tarot_arcana` — аркан текущего дня
- Ссылка на бот Telegram (`bot_username`)

Отображение: карточка аркана + CTA «Открыть в боте».

AI-поля: нет (структурные данные).

---

### R1 — Мои инсайты ✅

**Тип:** рефлексивная страница.

Пустые строки для заполнения вручную (онлайн + print).
Данных не передаётся.

---

### R2 — Что я попробую ✅

**Тип:** рефлексивная страница.

Аналогично R1 — пустые строки для действий.

---

## 5. Секции [PLANNED] — не реализованы в V2

### P1 — Психологические блоки 📋

**Шаблон:** `_psychological_blocks.html` — существует, не подключён к V2.

Данные которые уже парсятся:
- `psych_blocks` — список `{arcana_number, arcana_name, belief, manifestation, strategy}`
- Fallback: `analysis.psychological_blocks` (сырой текст)

Что нужно сделать: добавить `{% include '_psychological_blocks.html' %}` в `full_report_v2.html` после S12.

AI-поля: `psychological_blocks`

---

### P2 — Карта здоровья 📋

**Шаблон:** `_health_map.html` — существует, не подключён к V2.

Данные:
- `chakra_data` — 7 чакр с `{name, arcana, color, organs}` (уже вычисляется в `_build_v2_report_data`)
- `analysis.health_analysis` — AI-текст

Отображение: 7 строк чакр (Сахасрара → Муладхара) с цветными индикаторами + AI-текст.

Примечание по тону: "чакра" — единственный допустимый эзотерический термин в этой секции (см. tone-of-voice.md).

AI-поля: `health_analysis`

---

### P3 — Kitchen-аккордеон для всех секций 📋

Сейчас: только S3 имеет `.why` аккордеон.
План: добавить "Почему я так думаю?" для S4–S13.

`KitchenReportResult` уже содержит 14 ключей (по одному на секцию).

---

### P4 — Таро-блок 📋

Интеграция Таро-ритуалов в отчёт. После S15 — превью недельного расклада.
Требует реализации таро-подписки и TarotWeeklySpreadResult.

---

### P5 — Практики 📋

Шаблон `_practices.html` — не создан. Упоминается в `report-upgrade-sessions.md`.

---

## 6. Мини-разбор

### Структура

Шаблон: `mini_report.html`
Тип отчёта: `MINI`

| Секция | AI-поле |
|--------|--------|
| Главный архетип | `analysis.main_archetype` |
| Сильная сторона | `analysis.core_strength` |
| Эмоциональный конфликт | `analysis.emotional_conflict` |
| Паттерн отношений | `analysis.relationship_pattern` |
| Финансовый блок | `analysis.financial_block` |

### MiniAnalysisResult (схема)

```python
class MiniAnalysisResult(BaseModel):
    main_archetype: str
    core_strength: str
    emotional_conflict: str
    relationship_pattern: str
    financial_block: str
```

Генерируется за 1 вызов DeepSeek, max_tokens ≈ 2000.
Доступен сразу после /start или в бесплатном демо.

---

## 7. Шаблоны — файловая структура

```
nura_app/templates/reports/
├── full_report_v2.html          ← АКТИВНЫЙ шаблон V2 (2531 строк, самодостаточный)
├── mini_report.html             ← мини-разбор
├── full_report.html             ← УСТАРЕВШИЙ, не используется в продакшене
├── _dashboard.html              ← старый дашборд (для full_report.html)
├── _section_*.html              ← старые секции (для full_report.html)
├── _psychological_blocks.html   ← [PLANNED] психоблоки — готов, не подключён
└── _health_map.html             ← [PLANNED] карта здоровья — готов, не подключён
```

`full_report_v2.html` не использует `{% include %}`. Все секции S1–S15 + R1–R2 — inline.

---

## 8. ReportService

Файл: `nura_app/core/services/report.py`

### Методы

| Метод | Назначение |
|-------|-----------|
| `render_report_html(report, session_factory)` | Диспетчер по `report_type` |
| `render_report_v2_html(report, session_factory)` | Основной рендер V2 |
| `_build_v2_report_data(report, session)` | Async. Строит dict всех переменных для Jinja2 |
| `generate_html_report(report_data, template_name)` | Универсальный Jinja2-рендер |
| `generate_pdf(html)` | WeasyPrint: HTML → bytes |
| `_is_fallback_analysis(analysis)` | Детектирует заглушку AI |
| `parse_recommendations(text)` | `ai_recommendations` → `[{number, text, category}]` |
| `parse_psych_blocks(raw_text, arcana_names)` | `psychological_blocks` → список блоков по арканам |

### Timeout

Для full/kitchen/compat вызовов: `httpx timeout = 300с`.

---

## 9. Доставка отчёта

### Флоу доставки

```
Пользователь оплачивает (YooKassa webhook)
    ↓
Celery-задача: генерация AI (FullReportResult)
    ↓
Запись в reports (JSONB поле analysis)
    ↓
Бот отправляет сообщение с кнопкой «Открыть отчёт»
    ↓
/report/{token} → render_report_v2_html()
    ↓
Пользователь читает онлайн или скачивает PDF
```

### Права доступа

| Тип | Отчёт | Доступ |
|-----|-------|--------|
| Free | Мини-разбор (2-3 блока в боте) | Бесплатно |
| Матрица 890₽ | Полный HTML/PDF отчёт | После разовой оплаты |
| Таро-подписка 390₽/мес | Карта дня, таро-ритуалы в боте | По активной подписке |
| Kitchen-слой | /kitchen API (JSON) | Встроен в токен отчёта |

### URL продакшена

```
https://nura-ai.ru/report/{token}
```

Токен не истекает.

---

## 10. Сводная таблица секций

| # | Название | AI-поле | Статус |
|---|----------|---------|--------|
| S1 | Обложка | — | ✅ |
| S2 | Дашборд «За 30 секунд» | — | ✅ |
| S3 | Архетип личности | `main_archetype` | ✅ |
| S4 | Кармический хвост | `karmic_tail_analysis` | ✅ |
| S5 | Родовые программы | `ancestral_programs` | ✅ |
| S6 | Предназначение | `life_purpose` | ✅ |
| S7 | Таланты и сила | `strengths` | ✅ |
| S8 | Теневая сторона | `shadow_side` | ✅ |
| S9 | Отношения | `relationship_dynamics` | ✅ |
| S10 | Деньги и карьера | `financial_scenario` | ✅ |
| S11 | Повторяющиеся сценарии | `recurring_mistakes` | ✅ |
| S12 | Внутренние конфликты | `internal_conflicts` | ✅ |
| S13 | Жизненные циклы и прогноз | `life_forecast` | ✅ |
| S14 | Семь дней | `ai_recommendations` | ✅ |
| S15 | Карта дня | — | ✅ |
| R1 | Мои инсайты | — | ✅ |
| R2 | Что я попробую | — | ✅ |
| P1 | Психологические блоки | `psychological_blocks` | 📋 |
| P2 | Карта здоровья | `health_analysis` | 📋 |
| P3 | Kitchen для всех секций | `kitchen_analysis.*` | 📋 |
| P4 | Таро-блок | — | 📋 |
| P5 | Практики | — | 📋 |
