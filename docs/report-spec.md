# Структура HTML и PDF отчёта NURA

> Зависимости: `prompt-spec.md` (поля AI-ответа), tone-of-voice.md (тон текстов).
> Реализация: `nura_app/core/services/report.py` (Jinja2 + WeasyPrint).

---

## 1. Общая архитектура отчёта

Отчёт существует в трёх форматах (один HTML, рендерится адаптивно):

| Формат | Назначение | URL |
|--------|-----------|-----|
| HTML (mobile) | Просмотр в Telegram WebApp / браузере телефона | `{report_base_url}/report/{token}` |
| HTML (desktop) | Просмотр в десктоп-браузере | `{report_base_url}/report/{token}` |
| PDF | Скачивание, печать, отправка файлом | `{report_base_url}/report/{token}?format=pdf` |

Рендеринг: единый HTML-шаблон на Jinja2 → для PDF прогоняется через WeasyPrint.

---

## 2. Данные для подстановки

### 2.1 Общие переменные (доступны во всём шаблоне)

```python
{
    "user_name": str,          # Имя пользователя (из БД)
    "bot_username": str,       # username бота в Telegram
    "generated_at": str,       # Дата генерации (ISO-формат, DD.MM.YYYY)
    "report_token": str,       # 32-символьный hex-токен
    "report_base_url": str,    # "https://nura-ai.ru"
}
```

### 2.2 Переменные матрицы

```python
{
    "matrix": {
        "birth_date": str,     # "15.08.1995"
        "center": int,         # аркан центра (главный архетип)
        "top": int,            # небо
        "bottom": int,         # земля
        "left": int,           # мужское
        "right": int,          # женское
        "talent_zone": int,    # зона талантов
        "comfort_zone": int,   # зона комфорта
        "portrait_zone": int,  # портретная зона
        "karmic_tail": list[int],  # кармический хвост [низ, центр, верх]
        "heaven_line": list[int],  # линия неба
        "earth_line": list[int],   # линия земли
        "relation_line": list[int],# линия отношений
        "money_line": list[int],   # линия денег
        "relation_point": int,     # точка отношений
    },
    "matrix_labels": {
        # Строковые названия арканов для каждого числа
        "center": str,         # "Император (4)"
        "top": str,
        # ... и т.д. для всех позиций
    }
}
```

### 2.3 AI-анализ (полный отчёт)

Соответствует `FullReportResult` из `prompt-spec.md` §3.3:

```python
{
    "analysis": {
        "main_archetype": str,           # 3-4 предложения, 120-800 зн.
        "strengths": str,                # 4-5 предложений, 160-1000 зн.
        "shadow_side": str,              # 4-5 предложений, 160-1000 зн.
        "relationship_dynamics": str,    # 4-5 предложений, 160-1000 зн.
        "financial_scenario": str,       # 4-5 предложений, 160-1000 зн.
        "recurring_mistakes": str,       # 3-4 предложения, 120-800 зн.
        "internal_conflicts": str,       # 4-5 предложений, 160-1000 зн.
        "life_cycles": str,              # 3-4 предложения, 120-800 зн.
        "ai_recommendations": str,       # 7 пунктов, 200-1200 зн.
        "archetype_name": str,           # Название архетипа (напр. "Император")
        "archetype_number": int,         # Номер архетипа (1-22)
    }
}
```

### 2.4 AI-анализ (совместимость)

Соответствует `CompatibilityFullResult` из `prompt-spec.md` §4.5:

```python
{
    "compatibility": {
        "archetype_first": str,
        "archetype_second": str,
        "emotional_compatibility": str,
        "conflict_zones": str,
        "pair_strengths": str,
        "ai_recommendation": str,
    }
}
```

---

## 3. CSS Design System (NURA Brand)

### 3.1 CSS-переменные (полностью из бренда, `index.html`)

```css
:root {
  /* Brand colors */
  --black: #0B0B0B;
  --deep-green: #0F1A17;
  --green: #355C4D;
  --card-bg: #171717;
  --card-soft: rgba(245, 243, 238, 0.06);
  --white: #F5F3EE;
  --muted: #B7B2A8;
  --orange: #D97A32;
  --gold: #8C6A3B;
  --line: rgba(245, 243, 238, 0.12);
  --shadow: 0 30px 90px rgba(0, 0, 0, 0.45);

  /* Typography */
  --font-heading: 'Cormorant Garamond', Georgia, serif;
  --font-body: 'DM Sans', Arial, sans-serif;
  --h1-size: clamp(36px, 5vw, 52px);
  --h2-size: clamp(26px, 3.5vw, 38px);
  --h3-size: 20px;
  --body-size: 15px;
  --small-size: 13px;
  --line-height: 1.68;

  /* Spacing */
  --space-xs: 8px;
  --space-sm: 16px;
  --space-md: 24px;
  --space-lg: 36px;
  --space-xl: 48px;
  --space-2xl: 64px;

  /* Border radius */
  --radius-sm: 12px;
  --radius-md: 20px;
  --radius-lg: 28px;
  --radius-xl: 36px;

  /* Section accent bar */
  --accent-bar-width: 3px;
}
```

### 3.2 Типографика

| Элемент | Шрифт | Размер | Вес | Цвет |
|---------|-------|--------|-----|------|
| Заголовок отчёта (h1) | Cormorant Garamond | clamp(36px, 5vw, 52px) | 500 | `--white` |
| Заголовок секции (h2) | Cormorant Garamond | clamp(26px, 3.5vw, 38px) | 500 | `--white` |
| Имя архетипа (hero) | Cormorant Garamond | clamp(32px, 6vw, 56px) | 500 | `--orange` |
| Номер архетипа | Cormorant Garamond | 18px | 400 | `--muted` |
| Основной текст | DM Sans | 15px | 400 | `--white` (opacity 0.85) |
| Мелкий текст | DM Sans | 13px | 300 | `--muted` |
| Дата / мета | DM Sans | 12px | 300 | `--muted` |
| Нумерация рекомендаций | DM Sans | 14px | 500 | `--orange` |

### 3.3 Цвета секций

| Секция | Акцентный цвет | Фоновый элемент |
|--------|---------------|----------------|
| Cover / Hero | `--orange` | Радиальный градиент от `--orange` (opacity 0.18) |
| Архетип | `--orange` | Тёмный фон + градиент |
| Сильные стороны | `--green` (#355C4D) | Карточный фон `--card-bg` |
| Теневая сторона | `--gold` (#8C6A3B) | Карточный фон |
| Отношения | `--orange` | Карточный фон |
| Деньги | `--green` | Карточный фон |
| Повторяющиеся ошибки | `--gold` | Карточный фон |
| Внутренние конфликты | `--orange` | Карточный фон |
| Жизненные циклы | `--green` | Карточный фон |
| Рекомендации (7 дней) | `--orange` | Выделенный блок с градиентом |
| Совместимость | `--gold` | Карточный фон |
| Футер | `--muted` | Минимальный |

### 3.4 Базовые стили body

```css
body {
  margin: 0;
  font-family: var(--font-body);
  color: var(--white);
  background:
    radial-gradient(circle at 80% 10%, rgba(217, 122, 50, 0.10), transparent 28%),
    radial-gradient(circle at 12% 24%, rgba(53, 92, 77, 0.30), transparent 34%),
    linear-gradient(135deg, var(--black), var(--deep-green) 58%, #090909);
  line-height: var(--line-height);
}
```

---

## 4. Макет отчёта — полная структура

```
┌─────────────────────────────────────────┐
│                COVER PAGE                │
│  Лого NURA                               │
│  Имя пользователя                        │
│  Имя архетипа + номер                    │
│  Дата генерации                          │
│  Мини-матрица (3×3 grid)                 │
│  Декоративная линия                      │
├─────────────────────────────────────────┤
│  СЕКЦИЯ 1: Архетип личности              │
│  Заголовок + иконка                      │
│  Текст: main_archetype                   │
├─────────────────────────────────────────┤
│  СЕКЦИЯ 2: Сильные стороны               │
│  Заголовок + иконка                      │
│  Текст: strengths                        │
├─────────────────────────────────────────┤
│  СЕКЦИЯ 3: Теневая сторона               │
│  Заголовок + иконка                      │
│  Текст: shadow_side                      │
├─────────────────────────────────────────┤
│  СЕКЦИЯ 4: Отношения                     │
│  Заголовок + иконка                      │
│  Текст: relationship_dynamics            │
├─────────────────────────────────────────┤
│  СЕКЦИЯ 5: Деньги и карьера              │
│  Заголовок + иконка                      │
│  Текст: financial_scenario               │
├─────────────────────────────────────────┤
│  СЕКЦИЯ 6: Повторяющиеся сценарии        │
│  Заголовок + иконка                      │
│  Текст: recurring_mistakes               │
├─────────────────────────────────────────┤
│  СЕКЦИЯ 7: Внутренние конфликты          │
│  Заголовок + иконка                      │
│  Текст: internal_conflicts               │
├─────────────────────────────────────────┤
│  СЕКЦИЯ 8: Жизненные циклы               │
│  Заголовок + иконка                      │
│  Текст: life_cycles                      │
├─────────────────────────────────────────┤
│  СЕКЦИЯ 9: Рекомендации на 7 дней        │
│  Заголовок + иконка                      │
│  7 нумерованных блоков-дней              │
│  Текст: ai_recommendations               │
├─────────────────────────────────────────┤
│  СЕКЦИЯ 10: Совместимость (опционально)  │
│  Заголовок + иконка                      │
│  Имя партнёра                            │
│  Подсекции: архетипы, эмоции,            │
│  конфликты, сила пары, рекомендация      │
├─────────────────────────────────────────┤
│                FOOTER                     │
│  Лого NURA (маленькое)                   │
│  © 2026 NURA                             │
│  nura-ai.ru                              │
│  «Не предсказание — инструмент           │
│   самопознания»                          │
└─────────────────────────────────────────┘
```

---

## 5. Постраничная детализация

### 5.1 Cover-страница

**Расположение:**
- Вся страница — flex/grid, вертикальное центрирование
- Стек элементов (сверху вниз): лого, имя, архетип, номер архетипа, мини-матрица, дата

**HTML-структура:**
```html
<section class="cover">
  <div class="cover-logo">✦ NURA</div>
  <h1 class="cover-name">{{ user_name }}</h1>
  <div class="cover-archetype">{{ analysis.archetype_name }}</div>
  <div class="cover-archetype-num">{{ analysis.archetype_number }} аркан</div>
  <div class="cover-matrix"><!-- 3×3 grid --></div>
  <div class="cover-date">{{ generated_at }}</div>
  <div class="cover-divider"></div>
</section>
```

**Переменные:**
- `{{ user_name }}` — имя пользователя
- `{{ analysis.archetype_name }}` — название архетипа (напр. «Император»)
- `{{ analysis.archetype_number }}` — номер (1-22)
- `{{ matrix }}` — данные для 3×3 сетки
- `{{ generated_at }}` — дата генерации

**Стиль:**
- Фон: тёмный градиент с радиальным оранжевым свечением в центре
- Лого: `--orange`, шрифт Cormorant Garamond, letter-spacing: 0.14em
- Имя: `--white`, h1
- Архетип: `--orange`, крупно (h1)
- Номер: `--muted`, поменьше
- Матрица: 3×3 grid, ячейки с полупрозрачными границами, центр выделен `--orange` border
- Дата: `--muted`, снизу
- Декоративный разделитель: тонкая линия или градиент

**При печати:**
- `page-break-after: always`
- Вся страница без полей (full-bleed)

---

### 5.2 Секция 1 — Архетип личности

**Расположение:** новая страница при печати. Заголовок + левый акцентный бар + текст.

**HTML-структура:**
```html
<section class="report-section section-archetype">
  <div class="section-header">
    <div class="section-accent-bar"></div>
    <h2>Архетип личности</h2>
  </div>
  <div class="section-body">
    <p>{{ analysis.main_archetype }}</p>
  </div>
</section>
```

**Переменные:**
- `{{ analysis.main_archetype }}` — 3-4 предложения, 120-800 знаков

**Стиль:**
- Акцентная полоса: 3px ширина, цвет `--orange`, слева от заголовка
- Заголовок: h2, `--white`
- Текст: DM Sans, 15px, line-height 1.7
- Карточка: фон `--card-bg`, border-radius `--radius-lg`, padding `--space-xl`
- Максимальная ширина текста: 680px

---

### 5.3 Секция 2 — Сильные стороны

**Переменная:** `{{ analysis.strengths }}` — 4-5 предложений, 160-1000 знаков

**Структура:** как секция архетипа. Акцентный цвет: `--green`.

---

### 5.4 Секция 3 — Теневая сторона

**Переменная:** `{{ analysis.shadow_side }}` — 4-5 предложений, 160-1000 знаков

**Структура:** как секция архетипа. Акцентный цвет: `--gold`.

---

### 5.5 Секция 4 — Динамика отношений

**Переменная:** `{{ analysis.relationship_dynamics }}` — 4-5 предложений, 160-1000 знаков

**Структура:** как секция архетипа. Акцентный цвет: `--orange`.

**Дополнительно:** если есть данные партнёра (совместимость), снизу добавляется ссылка/блок: «Совместимость с [имя партнёра] ниже».

---

### 5.6 Секция 5 — Деньги и карьера

**Переменная:** `{{ analysis.financial_scenario }}` — 4-5 предложений, 160-1000 знаков

**Структура:** как секция архетипа. Акцентный цвет: `--green`.

---

### 5.7 Секция 6 — Повторяющиеся сценарии

**Переменная:** `{{ analysis.recurring_mistakes }}` — 3-4 предложения, 120-800 знаков

**Структура:** как секция архетипа. Акцентный цвет: `--gold`.

---

### 5.8 Секция 7 — Внутренние конфликты

**Переменная:** `{{ analysis.internal_conflicts }}` — 4-5 предложений, 160-1000 знаков

**Структура:** как секция архетипа. Акцентный цвет: `--orange`.

---

### 5.9 Секция 8 — Жизненные циклы

**Переменная:** `{{ analysis.life_cycles }}` — 3-4 предложения, 120-800 знаков

**Структура:** как секция архетипа. Акцентный цвет: `--green`.

---

### 5.10 Секция 9 — Рекомендации на 7 дней

**Расположение:** новая страница при печати. Выделенный блок (отличается от остальных секций).

**HTML-структура:**
```html
<section class="report-section section-recommendations">
  <div class="section-header">
    <div class="section-accent-bar"></div>
    <h2>Твои 7 дней</h2>
  </div>
  <p class="section-subtitle">Практические шаги, привязанные к твоей матрице</p>
  <div class="recommendations-list">
    <!-- Парсинг ai_recommendations: разбивка по \n или цифровым пунктам -->
    {% for day in recommendations_parsed %}
      <div class="rec-day">
        <div class="rec-day-num">{{ day.number }}</div>
        <div class="rec-day-text">{{ day.text }}</div>
      </div>
    {% endfor %}
  </div>
</section>
```

**Переменная:** `{{ analysis.ai_recommendations }}` — 7 пунктов, 200-1200 знаков

**Парсинг:** сервер разбивает `ai_recommendations` по `\n` и/или паттерну `цифра. ` в список из 7 элементов. Если AI вернул не 7 пунктов — отображаем как есть.

**Стиль:**
- Фон: выделенный градиентный блок (`rgba(217,122,50,.08)` → `rgba(53,92,77,.05)`)
- Каждый день — карточка с номером слева (круглая, `--orange`) и текстом справа
- Номер дня: DM Sans, 14px, bold, `--white`, на круглом фоне `--orange`
- Текст дня: DM Sans, 15px, line-height 1.65
- Border: `--line`, border-radius `--radius-md`
- Расстояние между днями: `--space-sm`

---

### 5.11 Секция 10 — Совместимость (опциональная, только если есть partner_data)

**Условие отображения:** `{% if compatibility %}`

**HTML-структура:**
```html
<section class="report-section section-compatibility">
  <div class="section-header">
    <h2>Совместимость с {{ partner_name }}</h2>
  </div>

  <div class="compat-subsection">
    <h3>{{ partner_name }} — {{ compatibility.archetype_second }}</h3>
  </div>

  <div class="compat-subsection">
    <h3>Эмоциональное сочетание</h3>
    <p>{{ compatibility.emotional_compatibility }}</p>
  </div>

  <div class="compat-subsection">
    <h3>Точки напряжения</h3>
    <p>{{ compatibility.conflict_zones }}</p>
  </div>

  <div class="compat-subsection">
    <h3>Сила вашей пары</h3>
    <p>{{ compatibility.pair_strengths }}</p>
  </div>

  <div class="compat-subsection compat-recommendation">
    <h3>Что попробовать уже сегодня</h3>
    <p>{{ compatibility.ai_recommendation }}</p>
  </div>
</section>
```

**Переменные:**
- `{{ partner_name }}` — имя партнёра
- `{{ compatibility.archetype_first }}` — архетип первого человека
- `{{ compatibility.archetype_second }}` — архетип второго человека
- `{{ compatibility.emotional_compatibility }}` — 2-3 предложения
- `{{ compatibility.conflict_zones }}` — 3-4 предложения
- `{{ compatibility.pair_strengths }}` — 3-4 предложения
- `{{ compatibility.ai_recommendation }}` — 2-3 предложения

**Стиль:**
- Акцентный цвет: `--gold`
- Подсекции разделены тонкой линией `--line`
- Каждая подсекция: h3 + p, как карточка внутри секции

---

### 5.12 Footer

**HTML-структура:**
```html
<footer class="report-footer">
  <div class="footer-logo">✦ NURA</div>
  <div class="footer-text">© 2026 NURA</div>
  <div class="footer-text">{{ report_base_url }}</div>
  <div class="footer-disclaimer">Не предсказание — инструмент самопознания</div>
</footer>
```

**Стиль:**
- Минимальный, центрированный
- Цвет: `--muted`
- Размер: 12px
- Отступ сверху: `--space-2xl`

---

## 6. Правила печатной версии (PDF через WeasyPrint)

### 6.1 @page

```css
@page {
  size: A4;
  margin: 20mm 18mm 25mm 18mm;
  @bottom-center {
    content: "NURA — " counter(page);
    font-family: 'DM Sans', sans-serif;
    font-size: 10px;
    color: #B7B2A8;
  }
}

@page cover {
  margin: 0;
  @bottom-center {
    content: none;
  }
}

@page section-start {
  margin: 20mm 18mm 25mm 18mm;
}
```

### 6.2 Page breaks

```css
.cover {
  page: cover;
  page-break-after: always;
}

.section-archetype {
  page-break-before: avoid;
}

.section-recommendations {
  page-break-before: always;
}

.section-compatibility {
  page-break-before: always;
}

.report-section {
  page-break-inside: avoid;
}

.rec-day {
  page-break-inside: avoid;
}
```

### 6.3 Шрифты для печати

```css
@media print {
  body {
    font-size: 11pt;
    color: #1a1a1a;
    background: #ffffff !important;
    line-height: 1.6;
  }

  .cover {
    background: #0B0B0B !important;
    color: #F5F3EE !important;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }

  .report-section {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
  }

  .section-header h2 {
    color: #1a1a1a;
  }

  .section-body p, .rec-day-text {
    color: #333333;
  }

  /* Сохраняем акценты */
  .section-accent-bar {
    print-color-adjust: exact;
    -webkit-print-color-adjust: exact;
  }

  .rec-day-num {
    print-color-adjust: exact;
    -webkit-print-color-adjust: exact;
  }
}
```

### 6.4 Особые правила

| Правило | Значение |
|---------|----------|
| Размер страницы | A4 (210×297mm) |
| Отступы страницы | 20mm сверху, 18mm слева/справа, 25mm снизу |
| Cover | без полей (margin: 0), полноцветная печать |
| Разрыв перед рекомендациями | всегда новая страница |
| Разрыв перед совместимостью | всегда новая страница |
| Внутри секции | избегать разрыва (`page-break-inside: avoid`) |
| Нумерация страниц | снизу по центру, начиная со страницы 2 (cover — page 1 без номера) |
| Минимальный размер шрифта | 10pt |
| Заголовки h2 в печати | 16pt |
| Заголовки h3 в печати | 13pt |
| Основной текст в печати | 11pt |

---

## 7. Адаптивность

### 7.1 Desktop (ширина > 768px)

- Контейнер: `max-width: 720px`, `margin: 0 auto`
- Две колонки не используются — весь контент в одну колонку для читаемости
- Cover: полноэкранный hero, высота минимум 90vh
- Карточки секций: padding `--space-xl` (48px)
- Карточки дней: в строку с фиксированной шириной номера

### 7.2 Mobile (ширина ≤ 768px)

```css
@media (max-width: 768px) {
  .container { padding: 0 16px; }

  .cover { min-height: 80vh; }

  .section-header h2 {
    font-size: 24px;
  }

  .report-section {
    padding: 24px;
    border-radius: 20px;
  }

  .recommendations-list {
    gap: 12px;
  }

  .rec-day {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }

  .cover-archetype {
    font-size: 36px;
  }

  .cover-name {
    font-size: 24px;
  }
}
```

### 7.3 Small mobile (ширина ≤ 480px)

```css
@media (max-width: 480px) {
  .container { padding: 0 12px; }

  .cover { min-height: 70vh; }

  .report-section {
    padding: 20px;
    border-radius: 16px;
  }

  .section-body p {
    font-size: 14px;
  }

  .rec-day-num {
    width: 36px;
    height: 36px;
    font-size: 13px;
  }
}
```

---

## 8. Брендинговые элементы

### 8.1 Лого NURA

Используется в двух местах: cover (крупно) и footer (маленькое).

```html
<!-- Cover -->
<div class="cover-logo">
  <span class="logo-mark">✦</span>
  <span>NURA</span>
</div>

<!-- Footer -->
<div class="footer-logo">
  <span class="logo-mark">✦</span>
  <span>NURA</span>
</div>
```

```css
.logo-mark {
  width: 34px;
  height: 34px;
  border: 1px solid rgba(217, 122, 50, 0.55);
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: var(--orange);
  box-shadow: 0 0 26px rgba(217, 122, 50, 0.16);
}

.cover-logo {
  font-family: var(--font-heading);
  font-weight: 700;
  letter-spacing: 0.14em;
  font-size: 15px;
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: var(--space-xl);
}

.footer-logo {
  font-family: var(--font-heading);
  font-size: 13px;
  opacity: 0.6;
  display: flex;
  align-items: center;
  gap: 8px;
}
```

### 8.2 Акцентная полоса секции

```css
.section-accent-bar {
  width: var(--accent-bar-width);
  height: 32px;
  border-radius: 2px;
  margin-right: 12px;
  flex-shrink: 0;
}

.section-archetype .section-accent-bar { background: var(--orange); }
.section-strengths .section-accent-bar { background: var(--green); }
.section-shadow .section-accent-bar    { background: var(--gold); }
.section-relationships .section-accent-bar { background: var(--orange); }
.section-money .section-accent-bar     { background: var(--green); }
.section-mistakes .section-accent-bar  { background: var(--gold); }
.section-conflicts .section-accent-bar { background: var(--orange); }
.section-cycles .section-accent-bar    { background: var(--green); }
.section-recommendations .section-accent-bar { background: var(--orange); }
```

### 8.3 Цветовая ротация акцентов секций

Чередование для визуального ритма:
- `--orange` → `--green` → `--gold` → `--orange` → `--green` → `--gold` → `--orange` → `--green` → `--orange`

### 8.4 Декоративные элементы

- Фон body: многослойный радиальный градиент (из index.html, смягчённый)
- Тонкая текстура шума (SVG noise filter с opacity 0.08 вместо 0.26 в лендинге)
- Разделители: тонкая линия `--line` (12% opacity), не на всех секциях
- Свечение: радиальный градиент от `--orange` (opacity 0.08-0.10) на фоне секций

---

## 9. Мини-отчёт (веб-версия)

Облегчённая версия для Telegram WebApp и быстрого просмотра.

### 9.1 Структура

```
┌──────────────────────────────────┐
│  Лого NURA                       │
│  Имя архетипа (hero)             │
│  Матрица 3×3 (компактная)        │
├──────────────────────────────────┤
│  Карточка: Главный архетип       │
│  {{ main_archetype }}            │
├──────────────────────────────────┤
│  Карточка: Сильная сторона       │
│  {{ core_strength }}             │
├──────────────────────────────────┤
│  Карточка: Эмоциональный конфликт│
│  {{ emotional_conflict }}        │
├──────────────────────────────────┤
│  Карточка: Паттерн отношений     │
│  {{ relationship_pattern }}      │
├──────────────────────────────────┤
│  Карточка: Денежный блок         │
│  {{ financial_block }}           │
├──────────────────────────────────┤
│  CTA-кнопка:                     │
│  «Получить полный AI-разбор      │
│   за 590 ₽»                      │
│  → ссылка на бота                │
├──────────────────────────────────┤
│  Footer                          │
└──────────────────────────────────┘
```

### 9.2 Переменные мини-отчёта

Соответствует `MiniAnalysisResult` из `prompt-spec.md` §2.3:

```python
{
    "analysis": {
        "main_archetype": str,        # 2-3 предложения
        "core_strength": str,         # 2-3 предложения
        "emotional_conflict": str,    # 2-3 предложения
        "relationship_pattern": str,  # 2-3 предложения
        "financial_block": str,       # 2-3 предложения
    },
    "bot_username": str,              # для ссылки в CTA
}
```

### 9.3 CTA-блок

```html
<div class="mini-cta">
  <p class="mini-cta-text">
    Это только начало. В полном отчёте — глубокий разбор отношений,
    денег, талантов, теневых сторон, жизненных циклов и персональный
    план на 7 дней.
  </p>
  <a href="https://t.me/{{ bot_username }}" class="mini-cta-button">
    Получить полный AI-разбор за 590 ₽
  </a>
</div>
```

---

## 10. Jinja2-шаблоны и организация кода

### 10.1 Структура шаблонов

```
frontend/reports/
  templates/
    _base.html              # Базовый шаблон (head, body, footer, общие стили)
    _styles.html            # CSS Design System (подключается в _base)
    _cover.html             # Cover-страница (переиспользуется)
    _matrix_3x3.html        # Мини-матрица 3×3
    _section_card.html      # Карточка секции (макрос/include)
    _recommendation_day.html# Один день рекомендации

    full_report.html        # Полный отчёт (расширяет _base)
    mini_report.html        # Мини-отчёт (расширяет _base)
  output/                   # Сгенерированные HTML/PDF файлы
    {token}.html
    {token}.pdf
```

### 10.2 ReportService (обновлённый)

```python
class ReportService:
    TEMPLATE_DIR = Path("frontend/reports/templates")

    @staticmethod
    def render_mini(matrix, analysis, bot_username, user_name) -> str:
        """Мини-отчёт — 5 карточек + CTA."""
        env = Environment(loader=FileSystemLoader(ReportService.TEMPLATE_DIR))
        tmpl = env.get_template("mini_report.html")
        return tmpl.render(
            matrix=matrix,
            analysis=analysis,
            bot_username=bot_username,
            user_name=user_name,
            generated_at=date.today().strftime("%d.%m.%Y"),
        )

    @staticmethod
    def render_full(matrix, analysis, compatibility, user_name,
                    partner_name, generated_at) -> str:
        """Полный отчёт — cover + 8-10 секций + совместимость (опционально)."""
        env = Environment(loader=FileSystemLoader(ReportService.TEMPLATE_DIR))
        tmpl = env.get_template("full_report.html")
        return tmpl.render(
            matrix=matrix,
            analysis=analysis,
            compatibility=compatibility,
            user_name=user_name,
            partner_name=partner_name,
            generated_at=generated_at,
            report_base_url=settings.report_base_url,
            report_price_rub=settings.report_price_rub,
        )

    @staticmethod
    async def generate_pdf(html, output_path) -> str:
        """HTML → PDF через WeasyPrint с @page-правилами."""
        HTML(string=html).write_pdf(output_path)
        return output_path
```

---

## 11. Доставка отчёта пользователю

### 11.1 Flow

```
1. AI генерирует FullReportResult
2. ReportService.render_full() → HTML
3. HTML сохраняется на диск: frontend/reports/output/{token}.html
4. Отдаётся через API: GET /report/{token} → HTML
5. GET /report/{token}?format=pdf → PDF (WeasyPrint on-the-fly или из кеша)
6. Пользователь получает ссылку в Telegram: https://nura-ai.ru/report/{token}
7. В Telegram — кнопка «Открыть отчёт» (WebApp) или «Скачать PDF»
```

### 11.2 Права доступа

- Отчёт доступен по token-ссылке без авторизации
- Token — 32 символа hex (uuid4().hex), неперебираемый
- Для PDF — тот же токен, формат указывается query-параметром
- При запросе проверяется: существует ли файл на диске / запись в БД

---

## 12. Сводная таблица секций

| # | Секция | Поле AI | Длина | Акцент | Печать |
|---|--------|---------|-------|--------|--------|
| — | Cover | — | — | orange | page-break-after: always |
| 1 | Архетип личности | `main_archetype` | 120-800 зн. | orange | avoid |
| 2 | Сильные стороны | `strengths` | 160-1000 зн. | green | avoid |
| 3 | Теневая сторона | `shadow_side` | 160-1000 зн. | gold | avoid |
| 4 | Динамика отношений | `relationship_dynamics` | 160-1000 зн. | orange | avoid |
| 5 | Деньги и карьера | `financial_scenario` | 160-1000 зн. | green | avoid |
| 6 | Повторяющиеся сценарии | `recurring_mistakes` | 120-800 зн. | gold | avoid |
| 7 | Внутренние конфликты | `internal_conflicts` | 160-1000 зн. | orange | avoid |
| 8 | Жизненные циклы | `life_cycles` | 120-800 зн. | green | avoid |
| 9 | Рекомендации (7 дней) | `ai_recommendations` | 200-1200 зн. | orange | always new page |
| 10 | Совместимость | `compatibility.*` | варьируется | gold | always new page |
| — | Footer | — | — | muted | — |
