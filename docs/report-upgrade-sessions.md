# Апгрейд страницы отчёта NURA — 16 шагов

> **Основание:** `docs/benchmark-competitors.md` — стратегический бенчмарк (8 конкурентов, 956 отзывов).
> **Цель:** довести страницу матрицы до уровня 890 ₽ (разовый продукт).
> **Предыдущая версия:** `docs/report-upgrade-sessions.md` (устарела, заменена этим документом).
>
> **ВАЖНО: Все файлы — относительно `nura_app/`.**
> Рабочая директория: `C:\git\NURA\nura_app\`.

---

## Что изменилось относительно старого плана

| Было | Стало |
|------|-------|
| max_tokens: 16000 | **32000** (обосновано benchmark — нужно 60000-80000 зн.) |
| 13 полей AI | 13 полей AI + глубокая проработка каждого (×3-5 объёма) |
| 4 новые секции | + health_map AI-разбор, + психоблоки, + таро-блок, + страницы рефлексии |
| Без навигации | Sticky sidebar, оглавление, якоря, кнопка «наверх» |
| Kitchen-слой: только бэкенд | + UI в HTML (стрелка «Почему я так думаю?») и в Telegram |
| Рекомендации: текст | Чек-боксы с категориями тело/ум/дух (уже было) |
| Прогноз: аркан года | Прогноз на год по сферам + таймлайн с иконками |

---

## Легенда моделей

| Метка | Модель | Когда |
|-------|--------|-------|
| ⚡ Flash | DeepSeek V4 Flash | CRUD, одиночные файлы, шаблоны, стили |
| 🔥 Pro | DeepSeek V4 Pro | 2+ модуля, архитектура, сложная логика |
| 📝 Kimi | Kimi K2.6 | Промпт-инжиниринг, длинные тексты |

---

## ШАГ 1 — Схема + fallback + max_tokens + аркан года

**Модель:** 🔥 Pro (затрагивает schemas, ai.py, matrix.py)

**Файлы:** `core/schemas.py`, `core/services/ai.py`, `core/services/matrix.py`

**Промпт:**
```
Задача: расширить FullReportResult, обновить FALLBACK_FULL, увеличить max_tokens
до 32000, добавить методы аркана года и жизненных периодов в MatrixService.

--- ЧАСТЬ 1: core/schemas.py ---

Текущий FullReportResult (9 полей) → расширить до 13 полей с увеличенными объёмами:

main_archetype: str = Field(..., min_length=600, max_length=2500,
    description="глубокий разбор: ключевая фраза, жизненная стратегия, стиль решений, проявление в работе/отношениях/деньгах")
strengths: str = Field(..., min_length=500, max_length=2000,
    description="сильные стороны, таланты, ресурсы, примеры реализации")
shadow_side: str = Field(..., min_length=500, max_length=2000,
    description="теневая сторона, слепые пятна, психологические защиты")
relationship_dynamics: str = Field(..., min_length=600, max_length=3000,
    description="динамика отношений: тип партнёра (точка отношений), паттерн входа/выхода, совместимость с архетипами")
financial_scenario: str = Field(..., min_length=600, max_length=3000,
    description="финансовый сценарий: 2-3 профессии/ниши, стратегия дохода, конкретные денежные блоки")
recurring_mistakes: str = Field(..., min_length=400, max_length=1500,
    description="повторяющиеся сценарии, циклы и причины")
internal_conflicts: str = Field(..., min_length=500, max_length=2000,
    description="внутренние конфликты между энергиями матрицы, путь разрешения")
life_cycles: str = Field(..., min_length=400, max_length=1500,
    description="жизненные циклы, периоды подъёма и спада")
ai_recommendations: str = Field(..., min_length=500, max_length=3000,
    description="7 дней рекомендаций в категориях тело/ум/дух, каждый с конкретным арканом и действием")

# Новые поля
karmic_tail_analysis: str = Field(..., min_length=800, max_length=4000,
    description="детальный разбор: причина→следствие→урок, история трёх арканов, практический выход из цикла")
ancestral_programs: str = Field(..., min_length=800, max_length=4000,
    description="родовые программы: линия отца (G) и матери (I), их влияние, ресурс vs блоки, путь проработки")
life_purpose: str = Field(..., min_length=1000, max_length=5000,
    description="предназначение: 4 уровня (личное/социальное/духовное/кармическое), кармический дар (F), денежный канал (H), конкретные сферы реализации")
life_forecast: str = Field(..., min_length=1000, max_length=5000,
    description="прогноз: текущий год по сферам (карьера/отношения/здоровье/деньги), прогноз 3 года, ключевые возраста и их энергии")
psychological_blocks: str = Field(..., min_length=800, max_length=3500,
    description="психологические блоки: какие убеждения формирует каждый ключевой аркан, к каким ситуациям приводит, как изменить")
health_analysis: str = Field(..., min_length=1000, max_length=5000,
    description="карта здоровья: 7 чакр с детальным разбором — состояние, причина дисбаланса, органы под управлением, практика восстановления (на основе арканов матрицы)")

--- ЧАСТЬ 2: core/services/ai.py ---

2.1. Расширить FALLBACK_FULL: добавить 6 новых ключей:
- karmic_tail_analysis, ancestral_programs, life_purpose, life_forecast
- psychological_blocks, health_analysis
Формат: "Твой {раздел} зашифрован в матрице. Мне нужно ещё немного времени для точного разбора. Попробуй запросить повторно."

2.2. FULL_REPORT_PARAMS: max_tokens = 8000 → 32000

2.3. Добавить FALLBACK_KITCHEN: словарь с 13 ключами (positions, energies, logic для каждой секции), логика "Данные обрабатываются. Запроси повторно."

--- ЧАСТЬ 3: core/services/matrix.py ---

3.1. calculate_year_arcana(birth_date: date, target_year: int) -> int:
- age = target_year - birth_date.year
- if age < 0: return 22
- return sum_digits(age)  # 31 → 3+1=4

3.2. calculate_life_periods(birth_date: date) -> dict:
- арканы для возрастов: 0, 7, 14, 21, 28, 35, 42, 49, 56, 63, 70
- {17: 5, 25: 4, 33: 8, ...}

3.3. calculate_year_forecast(birth_date: date, target_year: int) -> dict:
- аркан года, аркан года+1, аркан года+2
- {current: 4, next: 5, next_next: 6}

3.4. Обновить format_for_prompt: добавить блоки:
"== Жизненные периоды ==" (арканы по возрастам)
"== Прогноз по годам ==" (текущий/след/через год)
"== Карта здоровья (чакры) ==" (7 чакр с арканами и органами)

Импорт: from datetime import date в начало.

После выполнения: ruff check core/schemas.py core/services/ai.py core/services/matrix.py --fix
```

---

## ШАГ 2 — Промпт full_report.txt (полная переработка)

**Модель:** 📝 Kimi (промпт-инжиниринг)

**Файлы:** `core/prompts/full_report.txt`

**Промпт:**
```
Файл: core/prompts/full_report.txt.

Задача: полностью переработать промпт генерации полного отчёта.
Текущий: 33 строки, 13 полей. Нужно: 33 строки → 80+ строк, 15 полей (добавить psychological_blocks, health_analysis).

Требования:

1. Сохранить структуру: {chain_of_thought} + вступление + {matrix_text} + инструкция + JSON-схема.
   matrix_text уже содержит: жизненные периоды, прогноз по годам, карту здоровья.

2. КАЖДОЕ поле — минимум 300-500 слов (на русском). Запретить общие фразы и клише.
   Каждый ответ должен включать: психологическую интерпретацию, привязку к позициям матрицы,
   конкретные примеры из жизни, практический вывод.

3. Новые поля (добавить в схему):

   "psychological_blocks":
   - Для каждого из топ-3 арканов матрицы: какое убеждение формирует
   - Как это убеждение проявляется в поведении и решениях
   - Конкретная стратегия перепрограммирования (не «работай над собой», а «попробуй в течение недели записывать...»)
   - Привязка к позициям матрицы

   "health_analysis":
   - 7 чакр (сахасрара → муладхара): для каждой — название, аркан в позиции, состояние
   - Органы и системы под управлением чакры
   - Причина дисбаланса (связь с арканом матрицы)
   - Практика восстановления (1-2 предложения на чакру)

4. Усилить существующие:
   main_archetype: +ключевая фраза (1 предложение — суть архетипа), +жизненная стратегия, +реакция на кризисы
   financial_scenario: +2-3 конкретные профессии (не «творческие профессии», а «UX-дизайнер, арт-директор»), +конкретные блоки («страх выставить счёт», «убеждение что деньги = зло»)
   relationship_dynamics: +тип партнёра (связь с точкой отношений), +паттерн входа/выхода, +совместимость с 2-3 архетипами
   ai_recommendations: 7 дней, КАЖДЫЙ с категорией тело/ум/дух, конкретным действием и привязкой к аркану
   life_forecast: прогноз на текущий год по 4 сферам (карьера/отношения/здоровье/деньги) + прогноз 3 года

5. Тон: на "ты", без эзотерического жаргона (кроме секции health_analysis — там «чакра» разрешено),
   без страха, конкретно, ссылаться на арканы и позиции матрицы.

6. Схема JSON — с развёрнутыми описаниями: не «<текст>», а «минимум 300 слов: включи X, Y, Z».

Верни ПОЛНЫЙ текст нового full_report.txt.
```

---

## ШАГ 3 — CoT-инструкция (полная переработка)

**Модель:** ⚡ Flash

**Файлы:** `core/prompts/cot_instruction.txt`

**Промпт:**
```
Файл: core/prompts/cot_instruction.txt.

Задача: дополнить CoT-инструкцию новыми шагами анализа (9 шагов вместо 7).

Текущие шаги сохранить, расширить:

Шаг 2 (кармический хвост) — расширить:
«Какая ключевая фраза каждого из трёх арканов? Какую историю они рассказывают ВМЕСТЕ?
Как причина (низ) создаёт следствие (центр)? Какой урок (верх) нужно усвоить?
Какое КОНКРЕТНОЕ действие поможет выйти из цикла?»

Шаг 4 (линии) — разбить на подшаги:
4.1 Линия отношений (левый→центр→правый): тип партнёра, паттерн входа, паттерн выхода
4.2 Линия денег (верх→центр→низ): источник дохода, денежное мышление, материальный результат
4.3 Линия неба / предназначение (F→E→H): кармический дар, как направить в деятельность, монетизация
4.4 Линия земли / родовые программы (G→E→I): род отца, род матери, как освободиться и взять ресурс

Добавить Шаг 8 — Психологические блоки:
«Какие глубинные убеждения формирует каждый из ключевых арканов? Как они проявляются
в повседневных решениях и выборах? Какая стратегия перепрограммирования?»

Добавить Шаг 9 — Карта здоровья:
«Пройди по 7 чакрам. Для каждой: какой аркан в позиции, как он влияет на здоровье,
какие органы уязвимы, какая практика восстановления подходит?»

Шаг 6 (рекомендации) — дополнить: «Разбей 7 советов на категории: тело, ум, дух.
Каждый совет с конкретным арканом и действием, не абстракцией.»

Шаг 7 (проверка тона) — дополнить: «Проверь, что каждый ответ содержит психологическую
интерпретацию и привязку к позициям матрицы. Нет ли общих фраз?»

Верни ПОЛНЫЙ текст нового cot_instruction.txt.
```

---

## ШАГ 4 — Data pipeline в tasks.py

**Модель:** ⚡ Flash

**Файлы:** `core/tasks.py`

**Промпт:**
```
Файл: core/tasks.py, функция _process_full_report.

Задача: расширить matrix_raw и report_data для новых секций.

Текущий matrix_raw — 9 ключей: center, top, bottom, left, right, talent_zone,
comfort_zone, portrait_zone, karmic_tail

Добавить в matrix_raw:
- sky_line: list[int] = matrix.sky_line
- earth_line: list[int] = matrix.earth_line
- relationship_line: list[int] = matrix.relationship_line
- money_line: list[int] = matrix.money_line
- relationship_point: int = matrix.relationship_point
- inner_f, inner_g, inner_h, inner_i: int (все 4 внутренние точки)
- chakra_map: dict = matrix.chakra_map (если есть в MatrixData, иначе собрать:
  {1: matrix.sahasrara, 2: matrix.ajna, 3: matrix.vishuddha, 4: matrix.anahata,
   5: matrix.manipura, 6: matrix.svadhisthana, 7: matrix.muladhara})
- arcana_names: dict = matrix.arcana_names

Добавить в report_data:
- "life_periods": MatrixService.calculate_life_periods(birth_date)
- "year_forecast": MatrixService.calculate_year_forecast(birth_date, date.today().year)
- "current_year_arcana": MatrixService.calculate_year_arcana(birth_date, date.today().year)

MatrixService уже импортирован. from datetime import date добавить если нет.

После выполнения: ruff check core/tasks.py --fix
```

---

## ШАГ 5 — Шаблоны новых секций (6 штук)

**Модель:** ⚡ Flash

**Файлы:** создать/обновить в `frontend/reports/templates/`

**Промпт:**
```
Задача: создать/обновить 6 шаблонов секций. Дизайн-система: классы из _styles.html.

--- Файл 1: _section_karmic_tail.html (обновить существующий) ---
Секция с цепочкой причина→следствие→урок (3 кружка) + AI-текст + pull-quote.
Добавить под текстом: <blockquote class="section-insight">Ключевой инсайт</blockquote>

--- Файл 2: _section_ancestral.html (обновить существующий) ---
Добавить визуализацию: две колонки — «Линия отца» и «Линия матери»,
каждая с номером аркана, названием и мини-описанием из arcana_names.

--- Файл 3: _section_purposes.html (обновить существующий) ---
4 уровня в виде карточек: Личное, Социальное, Духовное, Кармическое.
Каждая карточка: номер аркана, название, AI-текст.

--- Файл 4: _section_forecast.html (обновить существующий) ---
- Блок «Текущий год»: аркан года + прогноз по 4 сферам (карьера/отношения/здоровье/деньги)
- Таймлайн: горизонтальная лента возрастов с кружками (иконки арканов)
- Блок «Прогноз 3 года»: 3 карточки (текущий/следующий/через год)

--- Файл 5: _health_map.html (обновить существующий) ---
7 чакр в виде вертикального списка. Для каждой:
- Название (Сахасрара, Аджна...), номер аркана в позиции
- Цветовая индикация (зелёный/жёлтый/красный — на основе аркана)
- Список органов
- AI-текст разбора (из health_analysis)
- Мини-практика восстановления

--- Файл 6: _psychological_blocks.html (НОВЫЙ) ---
Секция «Почему это происходит». 3 карточки психологических блоков:
- Аркан → убеждение → проявление в жизни → стратегия изменения
- Каждая карточка с цветовым акцентом

Все шаблоны используют CSS-классы, стили будут в ШАГЕ 14.
Верни содержимое всех 6 файлов.
```

---

## ШАГ 6 — Развёрнутая матрица + Dashboard

**Модель:** ⚡ Flash

**Файлы:** заменить `frontend/reports/templates/_matrix_full.html`, обновить `_dashboard.html`

**Промпт:**
```
Задача 1: переработать _matrix_full.html — развёрнутая визуализация.

Вместо простой сетки — полноценная визуализация:
- Сетка 3×3 (каждая ячейка: номер + полное название аркана из arcana_names)
- Центр с оранжевым свечением (glow effect)
- Под сеткой — 4 линии (небо, земля, отношения, деньги) в виде полос из 3 кружков с номерами
- Кармический хвост: цепочка причина→следствие→урок
- Точка отношений отдельно

Данные: все поля matrix (включая arcana_names).

Классы: matrix-grid, matrix-cell, matrix-cell.center, matrix-lines-section,
matrix-line (sky/earth/relationship/money), matrix-line-dot, matrix-line-connector,
matrix-line-label, karmic-chain, karmic-link (cause/effect/lesson).

Задача 2: обновить _dashboard.html — текстовые подписи к карточкам.

5 карточек с подписями:
- Архетип: номер + название + «Твой главный аркан — как он проявляется» (1 предложение из analysis)
- Талант: номер + «В чём твоя суперсила» (1 предложение)
- Вызов: номер + «Что тянется из прошлого» (1 предложение)
- Урок: номер + «Что нужно осознать» (1 предложение)
- Ресурс: номер + «Где ты восстанавливаешься» (1 предложение)

Тексты подписей брать из analysis (если есть), иначе формулировать на основе аркана.

Верни полное содержимое обоих файлов.
```

---

## ШАГ 7 — Сборка full_report.html с навигацией

**Модель:** ⚡ Flash

**Файлы:** `frontend/reports/templates/full_report.html`, создать `_nav_sidebar.html`, `_toc.html`

**Промпт:**
```
Три задачи: навигация, оглавление, сборка full_report.html.

--- Задача 1: _nav_sidebar.html (НОВЫЙ) ---
Sticky sidebar для десктопа. Слева, фиксированный при скролле.
Содержит список секций с якорными ссылками:
- Обложка
- Матрица
- Dashboard
- Архетип
- Кармический хвост
- Здоровье (чакры)
- Предназначение
- Родовые программы
- Сильные стороны
- Теневая сторона
- Отношения
- Деньги и карьера
- Жизненные периоды
- Психологические блоки
- Повторяющиеся сценарии
- Внутренние конфликты
- Твои 7 дней
- Карта дня (таро)

Активная секция подсвечивается оранжевым. Реализовать через IntersectionObserver
(встроенный JS в <script>).

--- Задача 2: _toc.html (НОВЫЙ) ---
Страница-оглавление после cover (для PDF). Простой список секций с номерами страниц.
Для HTML — скрыто (display: none), для печати — показано (display: block в @media print).

--- Задача 3: full_report.html — финальная сборка ---

Порядок секций:
1. {% include '_cover.html' %}
2. {% include '_toc.html' %}  ← новое
3. {% include '_matrix_full.html' %}
4. {% include '_dashboard.html' %}
5. Архетип личности (_section_card)
6. Кармический хвост (_section_karmic_tail)
7. Карта здоровья (_health_map)
8. Предназначение (_section_purposes)
9. Родовые программы (_section_ancestral)
10. Сильные стороны (_section_card)
11. Теневая сторона (_section_card)
12. Динамика отношений (_section_card)
13. Линия отношений (_line_visual)
14. Деньги и карьера (_section_card)
15. Линия денег (_line_visual)
16. Жизненные периоды (_section_forecast)
17. Психологические блоки (_psychological_blocks)  ← новое
18. Повторяющиеся сценарии (_section_card)
19. Внутренние конфликты (_section_card)
20. Твои 7 дней (рекомендации)
21. Твоя карта дня (таро-блок)  ← новое (см. ШАГ 10)
22. Практики (см. ШАГ 13)
23. Страницы рефлексии (см. ШАГ 13)
24. {% include '_footer.html' %}

Все секции должны иметь id="{section_name}" для якорных ссылок.
Добавить кнопку «↑ Наверх» (фиксированная, правый нижний угол, только для HTML).

Верни содержимое всех 3 файлов.
```

---

## ШАГ 8 — Kitchen-слой: UI в HTML

**Модель:** ⚡ Flash

**Файлы:** создать `_kitchen_toggle.html`, обновить `full_report.html` (вставка в каждую секцию)

**Промпт:**
```
Задача: реализовать UI для kitchen-слоя (второй слой — техническое объяснение).

Данные: `kitchen_analysis` — JSON с 13 ключами. Для каждой секции:
{ "main_archetype": {"positions": "центр (E)", "energies": "Император (4)", "logic": "..."} }

--- Файл: _kitchen_toggle.html (НОВЫЙ include) ---
Принимает через with: section_key (str), kitchen_data (dict).

<div class="kitchen-toggle">
  <button class="kitchen-btn" onclick="this.parentElement.querySelector('.kitchen-content').classList.toggle('open')">
    <span>🔍 Почему я так думаю?</span>
    <span class="kitchen-arrow">▾</span>
  </button>
  <div class="kitchen-content">
    <div class="kitchen-positions">
      <span class="kitchen-label">Позиции:</span> {{ kitchen_data.positions }}
    </div>
    <div class="kitchen-energies">
      <span class="kitchen-label">Арканы:</span> {{ kitchen_data.energies }}
    </div>
    <div class="kitchen-logic">
      <span class="kitchen-label">Логика AI:</span> {{ kitchen_data.logic }}
    </div>
  </div>
</div>

Вставить _kitchen_toggle в КАЖДУЮ текстовую секцию full_report.html.
Если kitchen_analysis есть и содержит нужный ключ — показать блок.

Пример вставки:
{% with section_class='archetype', section_title='Архетип личности', section_text=analysis.main_archetype %}
  {% include '_section_card.html' %}
{% endwith %}
{% if kitchen_analysis and kitchen_analysis.main_archetype %}
  {% with section_key='main_archetype', kitchen_data=kitchen_analysis.main_archetype %}
    {% include '_kitchen_toggle.html' %}
  {% endwith %}
{% endif %}

CSS для kitchen — будет добавлен в ШАГЕ 14. Использовать классы:
kitchen-toggle, kitchen-btn, kitchen-arrow, kitchen-content, kitchen-content.open,
kitchen-positions, kitchen-energies, kitchen-logic, kitchen-label.

Кнопка «🔍 Показать расчёт» в Telegram-боте — отдельно, вне скоупа этого документа.

Верни _kitchen_toggle.html и diff для full_report.html (куда вставить include).
```

---

## ШАГ 9 — Таро-блок «Твоя карта дня»

**Модель:** ⚡ Flash

**Файлы:** создать `_tarot_card.html`, обновить `core/services/report.py`, `full_report.html`

**Промпт:**
```
Задача: добавить блок «Твоя карта дня» как тизер подписки на таро-ритуалы.

--- Файл: _tarot_card.html (НОВЫЙ) ---
Данные: current_year_arcana (int), arcana_names (dict).

<section class="report-section section-tarot">
  <div class="section-header">
    <div class="section-accent-bar" style="background: var(--tarot-blue);"></div>
    <h2>Твоя карта дня</h2>
  </div>
  <p class="section-subtitle">Энергия, которая ведёт тебя сегодня — на основе твоей матрицы</p>

  <div class="tarot-card-daily">
    <div class="tarot-card-visual">
      <span class="tarot-card-num">{{ current_year_arcana }}</span>
      <span class="tarot-card-name">{{ arcana_names.get('center', '') if arcana_names else '' }}</span>
    </div>
    <p class="tarot-card-insight">
      Сегодня твой день проходит под энергией аркана {{ current_year_arcana }}.
      Это энергия {{ arcana_names.get(current_year_arcana|string, 'твоего дня') if arcana_names else '' }}.
      Прислушайся: о чём она говорит именно тебе?
    </p>
  </div>

  <div class="tarot-cta">
    <p>Хочешь получать карту дня каждый день?</p>
    <p>Подпишись на таро-ритуалы — ежедневные расклады на основе твоей матрицы.</p>
    <a href="https://t.me/{{ bot_username }}" class="tarot-cta-btn">Подписаться в Telegram</a>
  </div>
</section>

Использовать цвета таро-скина: --tarot-blue: #1a2a3a, --tarot-gold: #c9a96e.

--- Обновить core/services/report.py ---
В generate_html_report() добавить переменную bot_username из контекста/config.

--- Вставить в full_report.html ---
После секции «Твои 7 дней», перед compatiblity:
{% include '_tarot_card.html' %}

Верни _tarot_card.html и diff для report.py + full_report.html.
```

---

## ШАГ 10 — Карта здоровья: цветная визуализация чакр

**Модель:** ⚡ Flash

**Файлы:** обновить `_health_map.html` (создан в ШАГЕ 5), добавить CSS в _styles.html (ШАГ 14)

**Промпт:**
```
Задача: добавить в _health_map.html цветовую визуализацию чакр с индикаторами.

Для каждой из 7 чакр:
- Цветной индикатор (bar) — процент «заполненности» на основе аркана
  (арканы 1-7 → высокий, 8-14 → средний, 15-22 → требует внимания)
- Иконка/символ чакры
- Название чакры на русском и санскрите
- Номер аркана в позиции
- Список органов (из matrix.chakra_map или хардкод:
  Сахасрара: мозг, нервная система
  Аджна: глаза, гипофиз
  Вишудха: горло, щитовидка, голосовые связки
  Анахата: сердце, лёгкие
  Манипура: желудок, печень, поджелудочная
  Свадхистана: репродуктивная система, почки
  Муладхара: позвоночник, кости, ноги, иммунитет)
- AI-текст разбора (из analysis.health_analysis — парсить по чакрам)
- Мини-практика (1 предложение)

Пример структуры одной чакры:
<div class="chakra-row">
  <div class="chakra-indicator" style="--fill: 65%"></div>
  <div class="chakra-icon">👁</div>
  <div class="chakra-info">
    <h4>Аджна (Третий глаз)</h4>
    <span class="chakra-arcana">Аркан {{ chakra.arcana }} — {{ chakra.arcana_name }}</span>
    <div class="chakra-organs">Глаза, гипофиз, интуиция</div>
    <p class="chakra-analysis">{{ chakra.analysis }}</p>
    <p class="chakra-practice">{{ chakra.practice }}</p>
  </div>
</div>

Верни полный _health_map.html.
```

---

## ШАГ 11 — Психологические блоки: секция

**Модель:** ⚡ Flash

**Файлы:** создать `_psychological_blocks.html` (заготовка из ШАГА 5 — дополнить)

**Промпт:**
```
Задача: финализировать секцию «Почему это происходит» — психологические блоки.

Данные: analysis.psychological_blocks (строка, нужно парсить).

Структура секции:
<section class="report-section section-psychology">
  <div class="section-header">
    <div class="section-accent-bar" style="background: var(--deep-purple);"></div>
    <h2>Почему это происходит</h2>
  </div>
  <p class="section-subtitle">Психологические паттерны, которые управляют твоими решениями</p>

  <div class="psych-grid">
    {% for block in psych_blocks %}
    <div class="psych-card">
      <div class="psych-card-header">
        <span class="psych-arcana-num">{{ block.arcana }}</span>
        <span class="psych-arcana-name">{{ block.arcana_name }}</span>
      </div>
      <div class="psych-card-body">
        <div class="psych-belief">
          <span class="psych-label">Убеждение</span>
          <p>{{ block.belief }}</p>
        </div>
        <div class="psych-manifestation">
          <span class="psych-label">Как проявляется</span>
          <p>{{ block.manifestation }}</p>
        </div>
        <div class="psych-strategy">
          <span class="psych-label">Стратегия изменения</span>
          <p>{{ block.strategy }}</p>
        </div>
      </div>
    </div>
    {% endfor %}
  </div>
</section>

Парсинг psychological_blocks: функция parse_psych_blocks() в report.py.
AI возвращает текст с блоками — разбить на массив объектов {arcana, arcana_name, belief, manifestation, strategy}.
Если не удалось распарсить — показать сырой текст.

Цвет: --deep-purple: #4a2c6e.

Верни _psychological_blocks.html и функцию parse_psych_blocks() для report.py.
```

---

## ШАГ 12 — Страницы рефлексии

**Модель:** ⚡ Flash

**Файлы:** создать `_reflection.html`

**Промпт:**
```
Задача: создать страницы для самостоятельной работы пользователя в конце отчёта.

--- Файл: _reflection.html (НОВЫЙ) ---

Две страницы:

Страница 1 — «Мои инсайты»:
<section class="report-section section-reflection">
  <div class="section-header">
    <div class="section-accent-bar"></div>
    <h2>Мои инсайты</h2>
  </div>
  <p class="section-subtitle">Что важного ты узнал(а) о себе из этого отчёта? Запиши — чтобы не забыть.</p>
  <div class="reflection-lines">
    {% for i in range(8) %}
    <div class="reflection-line"></div>
    {% endfor %}
  </div>
</section>

Страница 2 — «Что я попробую на этой неделе»:
<section class="report-section section-reflection">
  <div class="section-header">
    <div class="section-accent-bar"></div>
    <h2>Что я попробую на этой неделе</h2>
  </div>
  <p class="section-subtitle">Выбери 3 практики из отчёта и запиши их сюда.</p>
  <div class="reflection-prompts">
    <div class="reflection-prompt">
      <span class="reflection-prompt-num">1</span>
      <div class="reflection-line"></div>
    </div>
    <div class="reflection-prompt">
      <span class="reflection-prompt-num">2</span>
      <div class="reflection-line"></div>
    </div>
    <div class="reflection-prompt">
      <span class="reflection-prompt-num">3</span>
      <div class="reflection-line"></div>
    </div>
  </div>
</section>

Для PDF: линии — это пустые строки с нижним подчёркиванием (border-bottom: 1px dashed).
Для HTML: нередактируемые (пользователь может распечатать и писать от руки).

Вставить в full_report.html после секции практик, перед footer.

Верни _reflection.html.
```

---

## ШАГ 13 — Секция «Практики» (3 зоны матрицы)

**Модель:** ⚡ Flash

**Файлы:** создать `_practices.html`

**Промпт:**
```
Задача: создать секцию «Практики» — по 3 зонам матрицы.

Данные: три зоны матрицы — небо (духовное), земля (родовое), центр (личное).

--- Файл: _practices.html (НОВЫЙ) ---

<section class="report-section section-practices">
  <div class="section-header">
    <div class="section-accent-bar"></div>
    <h2>Практики для интеграции</h2>
  </div>
  <p class="section-subtitle">Три направления работы — по зонам твоей матрицы</p>

  <div class="practices-grid">
    <div class="practice-card">
      <div class="practice-card-header">
        <span class="practice-icon">☀</span>
        <h4>Небо — Духовный путь</h4>
        <span class="practice-arcana">Аркан {{ matrix.sky_line[0] if matrix.sky_line else '' }}</span>
      </div>
      <p>Практика для соединения с высшим смыслом. Медитация, наблюдение, тишина.</p>
    </div>

    <div class="practice-card">
      <div class="practice-card-header">
        <span class="practice-icon">🌍</span>
        <h4>Земля — Родовые корни</h4>
        <span class="practice-arcana">Аркан {{ matrix.earth_line[0] if matrix.earth_line else '' }}</span>
      </div>
      <p>Практика для проработки родовых сценариев. Письмо предкам, ритуал благодарности.</p>
    </div>

    <div class="practice-card">
      <div class="practice-card-header">
        <span class="practice-icon">⭐</span>
        <h4>Центр — Личная сила</h4>
        <span class="practice-arcana">Аркан {{ matrix.center }}</span>
      </div>
      <p>Практика для укрепления центра. Ежедневный ритуал возвращения к себе.</p>
    </div>
  </div>
</section>

Вставить в full_report.html после «Твоей карты дня», перед страницами рефлексии.

Верни _practices.html.
```

---

## ШАГ 14 — CSS для всех новых элементов

**Модель:** ⚡ Flash

**Файлы:** `frontend/reports/templates/_styles.html`

**Промпт:**
```
Файл: frontend/reports/templates/_styles.html.

Задача: добавить CSS для ВСЕХ новых элементов. Добавить В КОНЕЦ файла (перед @media print).

Новые переменные (в :root):
--tarot-blue: #1a2a3a;
--tarot-gold: #c9a96e;
--deep-purple: #4a2c6e;

Блоки CSS для:

1. **Навигация** (_nav_sidebar.html): sticky sidebar слева (desktop), скрыт на мобильных.
   .report-nav { position: fixed; left: 0; top: 0; width: 240px; height: 100vh; overflow-y: auto;
     background: rgba(11,11,11,0.95); border-right: 1px solid var(--line); padding: var(--space-lg);
     z-index: 100; }
   .report-nav a { display: block; padding: 6px 0; color: var(--muted); text-decoration: none;
     font-size: 13px; border-left: 2px solid transparent; padding-left: 12px; }
   .report-nav a.active { color: var(--orange); border-left-color: var(--orange); }
   .report-nav a:hover { color: var(--white); }
   main.report-with-nav { margin-left: 240px; }
   @media (max-width: 1024px) { .report-nav { display: none; } main.report-with-nav { margin-left: 0; } }

2. **Оглавление** (_toc.html): скрыто в HTML, показано в PDF.
   .toc { display: none; }
   @media print { .toc { display: block; page-break-after: always; } }

3. **Kitchen toggle** (_kitchen_toggle.html):
   .kitchen-toggle { margin-top: var(--space-md); }
   .kitchen-btn { background: transparent; border: 1px solid var(--line); color: var(--muted);
     padding: 6px 12px; border-radius: var(--radius-sm); cursor: pointer; font-size: 13px;
     display: flex; align-items: center; gap: 8px; }
   .kitchen-btn:hover { border-color: var(--orange); color: var(--orange); }
   .kitchen-content { display: none; margin-top: var(--space-sm); padding: var(--space-md);
     background: rgba(255,255,255,0.03); border-radius: var(--radius-sm);
     border-left: 2px solid var(--orange); font-size: 13px; }
   .kitchen-content.open { display: block; }
   .kitchen-label { font-weight: 600; color: var(--orange); margin-right: 6px; }
   .kitchen-positions, .kitchen-energies, .kitchen-logic { margin-bottom: 8px; line-height: 1.5; }

4. **Таро-блок** (_tarot_card.html):
   .section-tarot .section-accent-bar { background: var(--tarot-gold); }
   .tarot-card-daily { display: flex; align-items: center; gap: var(--space-lg);
     padding: var(--space-lg); background: rgba(26,42,58,0.4);
     border: 1px solid rgba(201,169,110,0.3); border-radius: var(--radius-md); }
   .tarot-card-visual { width: 80px; height: 112px; background: linear-gradient(135deg, #1a2a3a, #2a3a4a);
     border: 2px solid var(--tarot-gold); border-radius: 8px; display: flex;
     flex-direction: column; align-items: center; justify-content: center; }
   .tarot-card-num { font-family: var(--font-heading); font-size: 32px; color: var(--tarot-gold); }
   .tarot-card-name { font-size: 11px; color: rgba(201,169,110,0.7); text-align: center; }
   .tarot-cta { margin-top: var(--space-lg); text-align: center; padding: var(--space-md);
     background: rgba(26,42,58,0.2); border-radius: var(--radius-sm); }
   .tarot-cta-btn { display: inline-block; margin-top: var(--space-sm); padding: 8px 20px;
     background: var(--tarot-gold); color: #1a2a3a; border-radius: var(--radius-sm);
     text-decoration: none; font-weight: 600; }

5. **Карта здоровья** (_health_map.html):
   .chakra-row { display: flex; gap: var(--space-md); padding: var(--space-md);
     border-bottom: 1px solid var(--line); align-items: flex-start; }
   .chakra-indicator { width: 6px; min-height: 60px; border-radius: 3px;
     background: linear-gradient(to bottom, var(--green), var(--orange), #8b0000);
     position: relative; flex-shrink: 0; }
   .chakra-indicator::after { content: ''; position: absolute; bottom: 0; left: 0; right: 0;
     height: calc(100% - var(--fill)); background: rgba(11,11,11,0.8); }
   .chakra-icon { font-size: 24px; flex-shrink: 0; }
   .chakra-info h4 { margin: 0 0 4px 0; font-family: var(--font-heading); font-size: 16px; }
   .chakra-arcana { font-size: 12px; color: var(--muted); }
   .chakra-organs { font-size: 12px; color: var(--green); margin: 4px 0; }
   .chakra-analysis { font-size: 14px; line-height: 1.6; }
   .chakra-practice { font-size: 13px; color: var(--orange); font-style: italic; }

6. **Психологические блоки** (_psychological_blocks.html):
   .psych-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
     gap: var(--space-md); }
   .psych-card { background: var(--card-bg); border: 1px solid var(--line);
     border-radius: var(--radius-md); overflow: hidden; }
   .psych-card-header { padding: var(--space-sm) var(--space-md);
     background: rgba(74,44,110,0.3); display: flex; align-items: center; gap: 12px; }
   .psych-arcana-num { font-family: var(--font-heading); font-size: 24px; color: var(--deep-purple); }
   .psych-card-body { padding: var(--space-md); display: flex; flex-direction: column; gap: 12px; }
   .psych-label { font-size: 11px; color: var(--deep-purple); text-transform: uppercase;
     letter-spacing: 1px; display: block; margin-bottom: 2px; }

7. **Страницы рефлексии** (_reflection.html):
   .reflection-lines, .reflection-prompt { display: flex; flex-direction: column; gap: 24px; }
   .reflection-line { border-bottom: 1px dashed var(--line); height: 36px; }
   .reflection-prompt { display: flex; align-items: center; gap: 12px; }
   .reflection-prompt-num { font-family: var(--font-heading); font-size: 20px;
     color: var(--orange); width: 28px; text-align: center; }
   .reflection-prompt .reflection-line { flex: 1; }

8. **Практики** (_practices.html):
   .practices-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
     gap: var(--space-md); }
   .practice-card { background: var(--card-bg); border: 1px solid var(--line);
     border-radius: var(--radius-md); padding: var(--space-md); }
   .practice-card-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
   .practice-icon { font-size: 20px; }
   .practice-arcana { font-size: 11px; color: var(--muted); margin-left: auto; }

9. **Кнопка «Наверх»:**
   .back-to-top { position: fixed; bottom: 24px; right: 24px; width: 40px; height: 40px;
     background: var(--orange); color: var(--black); border: none; border-radius: 50%;
     cursor: pointer; font-size: 18px; display: none; z-index: 200; align-items: center;
     justify-content: center; }
   .back-to-top.visible { display: flex; }

10. **Section insight (pull-quote):**
   .section-insight { margin: var(--space-md) 0; padding: var(--space-md) var(--space-lg);
     border-left: 3px solid var(--orange); font-family: var(--font-heading);
     font-size: 18px; line-height: 1.4; color: var(--orange);
     background: rgba(217,122,50,0.05); }

11. **Print styles для ВСЕХ новых элементов:**
   @media print {
     .report-nav { display: none; }
     .kitchen-btn { display: none; }
     .kitchen-content { display: block !important; border-left-color: #999; font-size: 11px; }
     .back-to-top { display: none; }
     .tarot-card-daily { border: 1px solid #ccc; }
     .tarot-cta { display: none; }  /* CTA не нужен в PDF */
     .tarot-cta-btn { display: none; }
     .chakra-row { border-color: #ddd; page-break-inside: avoid; }
     .psych-card { border: 1px solid #ddd; page-break-inside: avoid; }
     .reflection-line { border-color: #ccc; }
     .section-insight { border-left-color: #999; color: #333; }
     .practice-card { border: 1px solid #ddd; page-break-inside: avoid; }
   }

Верни ТОЛЬКО CSS (все 11 блоков с комментариями-заголовками).
```

---

## ШАГ 15 — Углубление секций + чек-лист для рекомендаций

**Модель:** 🔥 Pro

**Файлы:** `core/prompts/full_report.txt` (проверить), `frontend/reports/templates/_recommendation_day.html`, `core/services/report.py`

**Промпт:**
```
Две параллельные задачи.

--- Задача 1: Проверить full_report.txt на глубину ---
Прочитать core/prompts/full_report.txt (уже обновлён в ШАГЕ 2).
Проверить, что требования включают:

main_archetype:
- Ключевая фраза архетипа (1 предложение — суть)
- Жизненная стратегия + стиль решений + реакция на кризисы
- Проявление в работе, отношениях, деньгах

financial_scenario:
- 2-3 конкретные профессии/ниши (не «творческие», а «UX-дизайнер, фотограф-портретист»)
- Финансовая стратегия (активный/пассивный доход, структура/творчество)
- 2-3 конкретных денежных блока с примерами

relationship_dynamics:
- Тип притягиваемого партнёра (привязка к точке отношений)
- Паттерн входа и выхода из отношений
- Совместимость с 2-3 другими архетипами

Если нет — дополнить. Верни diff или "всё ок".

--- Задача 2: Чек-лист для рекомендаций (обновить) ---
2.1. Обновить _recommendation_day.html:
Текущая структура с чек-боксом + категорией (тело/ум/дух). Добавить:
- Иконку категории: тело = 💪, ум = 🧠, дух = 🌟
- Под текстом: мини-подсказка «Ожидаемый эффект: ...» (если есть в данных)

2.2. Обновить ReportService.parse_recommendations():
После парсинга номера и текста определять категорию:
- Ключевые слова тела: тело, физический, йога, дыхание, спорт, сон, движение, прогулка → "Тело"
- Ключевые слова ума: ум, мысли, анализ, изучение, чтение, план, запись, внимание → "Ум"
- Ключевые слова духа: дух, медитация, осознанность, тишина, благодарность, смысл → "Дух"
- Иначе → "Практика"
Возвращать: [{"number": 1, "text": "...", "category": "Тело", "effect": "..."}, ...]

2.3. Добавить CSS (будет в ШАГЕ 14, здесь только проверить классы):
.rec-day-category с иконкой, .rec-day-effect (12px, muted, italic)

Верни:
1. Diff для full_report.txt (или "всё ок")
2. Обновлённый _recommendation_day.html
3. Обновлённую функцию parse_recommendations
```

---

## ШАГ 16 — Финальная интеграция и тесты

**Модель:** 🔥 Pro (все модули)

**Файлы:** все изменённые

**Промпт:**
```
Финальная проверка целостности апгрейда. Все пути — относительно nura_app/.

Проверить:

1. core/schemas.py: FullReportResult содержит 15 полей (main_archetype, strengths, shadow_side,
   relationship_dynamics, financial_scenario, recurring_mistakes, internal_conflicts, life_cycles,
   ai_recommendations, karmic_tail_analysis, ancestral_programs, life_purpose, life_forecast,
   psychological_blocks, health_analysis). Каждое с Field(min_length, max_length, description).

2. core/services/ai.py:
   - FALLBACK_FULL: 15 ключей
   - FALLBACK_KITCHEN: 15 ключей
   - FULL_REPORT_PARAMS: max_tokens = 32000

3. core/services/matrix.py:
   - calculate_year_arcana(birth_date, target_year) -> int
   - calculate_life_periods(birth_date) -> dict
   - calculate_year_forecast(birth_date, target_year) -> dict
   - format_for_prompt включает: жизненные периоды, прогноз по годам, карту здоровья

4. core/prompts/cot_instruction.txt: 9 шагов (1-7 + 8 психология + 9 здоровье)

5. core/prompts/full_report.txt: 15 полей с требованиями 300-500 слов на поле

6. core/tasks.py _process_full_report:
   - matrix_raw: 17+ ключей (включая sky_line, earth_line, relationship_line, money_line,
     relationship_point, inner_f/g/h/i, chakra_map, arcana_names)
   - report_data: life_periods, year_forecast, current_year_arcana

7. frontend/reports/templates/ — ВСЕ файлы:
   - full_report.html: 24 секции (см. порядок в ШАГЕ 7), все с id для якорей
   - _nav_sidebar.html: sticky sidebar с IntersectionObserver
   - _toc.html: оглавление для PDF
   - _matrix_full.html: развёрнутая матрица с 4 линиями
   - _dashboard.html: 5 карточек с подписями
   - _section_karmic_tail.html: цепочка + pull-quote
   - _section_ancestral.html: две колонки отец/мать
   - _section_purposes.html: 4 карточки предназначений
   - _section_forecast.html: таймлайн + прогноз года + прогноз 3 года
   - _health_map.html: 7 чакр с индикаторами + органы + AI-разбор
   - _psychological_blocks.html: 3 карточки блоков
   - _reflection.html: 2 страницы рефлексии
   - _practices.html: 3 карточки практик
   - _tarot_card.html: карта дня + CTA подписки
   - _kitchen_toggle.html: сворачиваемый блок «Почему я так думаю?»
   - _recommendation_day.html: чек-бокс + категория + эффект
   - _line_visual.html: полоса с 3 кружками

8. frontend/reports/templates/_styles.html: все CSS-классы из шаблонов определены

9. core/services/report.py:
   - parse_recommendations возвращает категории и эффекты
   - parse_psych_blocks парсит psychological_blocks
   - generate_html_report передаёт kitchen_analysis, bot_username, psych_blocks

Напиши скрипт проверки целостности (Python, без зависимостей от проекта):
- Проверить 15 ключей FALLBACK_FULL == поля FullReportResult
- Проверить все include из full_report.html → существующие файлы
- Проверить, что все CSS-классы из шаблонов есть в _styles.html
- Вывести отчёт: "✅ OK" или "❌ Проблема: ..."

Запусти ruff check . --fix и pytest (если есть тесты на report).
```

---

## Таблица зависимостей

| Шаг | Зависит от | Суть |
|-----|-----------|------|
| 1 | — | Схема (15 полей) + fallback + max_tokens=32000 + аркан года |
| 2 | 1 | Промпт full_report.txt (15 полей, 300-500 слов/поле) |
| 3 | 1 | CoT-инструкция (9 шагов) |
| 4 | 1 | Data pipeline в tasks.py |
| 5 | 4 | 6 шаблонов новых секций |
| 6 | 4 | Развёрнутая матрица + Dashboard |
| 7 | 5, 6 | Сборка full_report + навигация (sidebar + TOC + якоря) |
| 8 | 7 | Kitchen-слой UI (в каждую секцию) |
| 9 | 4, 7 | Таро-блок «Карта дня» |
| 10 | 5 | Карта здоровья: цветная визуализация чакр |
| 11 | 2, 7 | Психологические блоки |
| 12 | 7 | Страницы рефлексии |
| 13 | 7 | Секция «Практики» (3 зоны) |
| 14 | 5-13 | CSS для ВСЕХ новых элементов |
| 15 | 2, 4 | Проверка глубины + чек-лист рекомендаций |
| 16 | все | Финальная интеграция + скрипт проверки |

**Порядок запуска:**
1 → 2 → 3 → 4 → (5 + 6 параллельно) → 7 → (8 + 9 + 10 + 11 + 12 + 13 параллельно) → 14 → 15 → 16
