# NURA — Сравнение прайс-листа и наполнения отчёта

> **STATUS: DATED RESEARCH**
>
> **Research date/baseline:** 30.06.2026, repository assumptions recorded by the original analysis. Claims were not re-researched or externally refreshed in Write Session 5.
>
> **Purpose:** compare the then-described report content with the then-described offer and preserve the resulting recommendations.
>
> This document is research, not a product spec, owner decision, implementation proof, pricing contract or roadmap. Current product target: [canonical spec](product/NURA_1_0_1_5_PRODUCT_SPEC.md). Current implementation: [current status](implementation/current-status.md), [accepted report spec](report-spec.md) and [accepted pricing map](pricing.md).

## Research authority boundary

- All «заявлено», «реализовано», «запланировано», page-count, section-count and competitor claims below describe the 30 June research baseline unless explicitly reclassified.
- The current 890 ₽ target is governed by the canonical product spec and accepted pricing documentation, not by this comparison.
- Historical recommendations P1–P5, proposed phases and projections are `DATED RESEARCH`; they do not create implementation tasks or future report scope.
- `image-prompts.md`, referenced by the original analysis, is not present in the current repository. Its alleged readiness is therefore a stale/unsupported source claim, not an existing asset contract.
- Research conclusions are preserved even where later product direction or implementation changed.

---

## 1. Research baseline: заявлено в прайс-листе

### Матрица Судьбы — 890 ₽ (разово)

**Обещания:**
- Полный HTML/PDF отчёт
- **30-50 страниц**
- **21+ секций**
- Доступ навсегда
- Kitchen-слой (AI-обоснования)
- 1 расклад совместимости навсегда

---

## 2. Research baseline: наполнение отчёта на 30.06.2026

### Классифицировано исходным исследованием как реализованное (17 секций)

| # | Секция | AI-поле | Статус |
|---|--------|---------|--------|
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

### Классифицировано исходным исследованием как запланированное (5 секций)

| # | Секция | AI-поле | Приоритет |
|---|--------|---------|-----------|
| P1 | Психологические блоки | `psychological_blocks` | Средний |
| P2 | Карта здоровья | `health_analysis` | Средний |
| P3 | Kitchen для всех секций | `kitchen_analysis.*` | Низкий |
| P4 | Таро-блок | — | Низкий |
| P5 | Практики | — | Низкий |

---

## 3. Dated comparison, not current conformity evidence

### Исходный вывод исследования: «соответствует»

| Критерий | Заявлено | Факт | Статус |
|----------|----------|------|--------|
| Количество секций | 21+ | 17 реализовано + 5 запланировано = 22 | ✅ Соответствует |
| Kitchen-слой | Да | Реализован для S3, запланирован для остальных | ️ Частично |
| HTML/PDF форматы | Да | Оба реализованы | ✅ |
| Доступ навсегда | Да | Токен не истекает | ✅ |
| Расклад совместимости | 1 навсегда | Реализовано в боте | ✅ |

### Исходный вывод исследования: «требует внимания»

| Проблема | Описание | Рекомендация |
|----------|----------|--------------|
| **Объём страниц** | Заявлено 30-50 стр., фактически ~25-35 стр. | Добавить P1, P2 для увеличения объёма |
| **Kitchen-слой** | Только S3 имеет аккордеон | Расширить на S4-S13 (P3) |
| **Визуальный контент** | Исходное утверждение: только SVG матрицы, нет изображений | Историческая рекомендация ссылалась на отсутствующий `image-prompts.md`; current asset/visual contract этим не доказан |

---

## 4. Competitor snapshot used by the research

### Рынок Матрицы Судьбы

| Конкурент | Цена | Объём | Особенности |
|-----------|------|-------|-------------|
| matrica-sudby.ru | 580 ₽ | ~20 стр. | Базовый отчёт |
| matrica-sudbyy.ru | 590 ₽ | ~25 стр. | Стандартный отчёт |
| 22energy.ru | 100-499 ₽ | ~15-20 стр. | Дешёвый сегмент |
| matritca-sudbi.com | 490 ₽ | ~20 стр. | Средний сегмент |
| matrix-profi.ru | 1400 ₽ | ~40 стр. | Премиум сегмент |
| **NURA** | **890 ₽** | **~30-35 стр.** | **AI-интерпретация, Kitchen-слой** |

### Вывод

NURA находится в **верхнем сегменте рынка** по цене, но предлагает:
- ✅ Больше секций (22 vs 15-20 у конкурентов)
- ✅ AI-интерпретация (уникальная фича)
- ✅ Kitchen-слой (прозрачность AI-решений)
- ✅ Рефлексивные страницы (R1, R2)
- ⚠️ Меньше визуального контента (изображения)

---

## 5. Dated research recommendations — not roadmap

### Приоритет 1: Добавить запланированные секции

1. **P1 — Психологические блоки**
   - Шаблон уже готов: `_psychological_blocks.html`
   - AI-поле уже парсится: `parse_psych_blocks()`
   - **Действие:** добавить `{% include '_psychological_blocks.html' %}` в `full_report_v2.html` после S12
   - **Эффект:** +3-5 страниц, уникальная фича

2. **P2 — Карта здоровья**
   - Шаблон уже готов: `_health_map.html`
   - Данные уже вычисляются: `chakra_data`
   - **Действие:** добавить `{% include '_health_map.html' %}` в `full_report_v2.html` после P1
   - **Эффект:** +3-5 страниц, уникальная фича

### Приоритет 2: Расширить Kitchen-слой

3. **P3 — Kitchen для всех секций**
   - Данные уже генерируются: `KitchenReportResult` (14 ключей)
   - **Действие:** добавить аккордеоны "Почему я так думаю?" для S4-S13
   - **Эффект:** повышение доверия, прозрачность AI

### Приоритет 3: Визуальный контент

4. **Фоновые изображения**
   - Исходное утверждение: промпты готовы в `image-prompts.md`; такого repository file нет
   - **Действие:** сгенерировать 11 изображений для секций
   - **Эффект:** премиальный вид, увеличение объёма на 5-10%

### Приоритет 4: Дополнительные секции

5. **P4 — Таро-блок**
   - Интеграция с подпиской
   - **Действие:** после реализации таро-подписки
   - **Эффект:** кросс-продажи

6. **P5 — Практики**
   - Шаблон не создан
   - **Действие:** создать `_practices.html`
   - **Эффект:** +2-3 страницы

---

## 6. Historical proposed action plan — not committed roadmap

### Фаза 1 (1-2 дня)
- [ ] Добавить P1 (Психологические блоки)
- [ ] Добавить P2 (Карта здоровья)
- [ ] Обновить pricing.md: "22 секции" вместо "21+"

### Фаза 2 (3-5 дней)
- [ ] Сгенерировать фоновые изображения по image-prompts.md
- [ ] Интегрировать изображения в секции
- [ ] Расширить Kitchen-слой на S4-S10

### Фаза 3 (1-2 недели)
- [ ] Реализовать P4 (Таро-блок) после запуска подписки
- [ ] Создать P5 (Практики)
- [ ] Обновить marketing-материалы

---

## 7. Hypothetical projection from the dated study

### После Фазы 1

| Критерий | Заявлено | Будет | Статус |
|----------|----------|-------|--------|
| Количество секций | 21+ | 19 реализовано + 3 запланировано = 22 | ✅ Полное соответствие |
| Объём страниц | 30-50 | 35-45 стр. | ✅ Полное соответствие |
| Kitchen-слой | Да | S3-S10 (8 секций) | ✅ Полное соответствие |

### После Фазы 2

| Критерий | Заявлено | Будет | Статус |
|----------|----------|-------|--------|
| Визуальный контент | — | 11 фоновых изображений | ✅ Превышает ожидания |
| Premium-ощущение | — | Высокое | ✅ Конкурентное преимущество |

---

## 8. Dated research conclusion

**Вывод исследования на 30.06.2026:** NURA соответствовала описанному в использованном прайс-листе baseline, но исследование видело потенциал для улучшения. Это не current implementation verdict.

**Ключевые действия:**
1. Добавить P1 и P2 (быстрая победа, шаблоны готовы)
2. Сгенерировать визуальный контент (премиальный вид)
3. Расширить Kitchen-слой (доверие к AI)

**Результат:** NURA станет **безусловным лидером** в сегменте 890-1400 ₽ по соотношению цена/качество/объём.

---

## 9. Provenance and stale-claim notes

- Исходное исследование утверждало, что все AI-поля уже реализованы в `core/services/report.py`; current implementation следует проверять по accepted report documentation and code.
- Исходное исследование утверждало, что шаблоны P1 и P2 уже существуют и требуют только подключения; это historical implementation claim, не задача из этого документа.
- Исходное исследование утверждало, что Kitchen-данные уже генерируются и требуют только отображения; current two-layer contract находится в accepted report/two-layer docs.
- Исходное исследование называло визуальный контент единственным внешним generation gap. Эта формулировка могла устареть и не является launch-readiness evidence.
- Отсутствующая ссылка `image-prompts.md` не восстановлена по догадке; visual/content assets governed by current brand/design workflows.
