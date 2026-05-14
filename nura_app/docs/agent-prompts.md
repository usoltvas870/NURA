# Промпты для запуска агентов документации

Копируй промпт нужного шага и вставляй в Task tool (поле `prompt`). Агент сам разберётся что делать, какие файлы читать и куда сохранять результат.

---

## Шаг 1 — `docs/matrix-algo.md`

**Модель:** DeepSeek V4 Pro
**Агент:** backend-architect
**Параллельно с:** шаг 4

```
Напиши документ docs/matrix-algo.md — Алгоритм расчёта Матрицы Судьбы.

Инструкции:
1. Прочитай docs/docs-plan.md, секцию "1. docs/matrix-algo.md"
2. Прочитай nura_app/core/services/matrix.py — текущую реализацию
3. Прочитай nura_app/core/schemas.py — структуру MatrixData
4. Прочитай nura_app/core/models.py — модель Report (поля matrix_data)

Напиши документ в docs/matrix-algo.md.

Документ должен содержать:
- Описание всех 22 арканов: номер, русское название, эмодзи, ключевая фраза
- Формулы расчёта каждой позиции матрицы (день, месяц, год → число → аркан)
- Все позиции: центр, портретная зона, зона талантов, зона комфорта, кармический хвост, линия неба, линия земли, линия отношений, линия денег
- Полный пример расчёта на конкретной дате
- Псевдокод или Python-функции для каждой позиции

После записи сделай commit: git add docs/matrix-algo.md и commit "Add matrix-algo.md"
```

---

## Шаг 2 — `docs/prompt-spec.md`

**Модель:** DeepSeek V4 Pro
**Агент:** ai-engineer
**Зависит от:** шаг 1 (matrix-algo.md готов)

```
Напиши документ docs/prompt-spec.md — Спецификация AI-промптов.

Инструкции:
1. Прочитай docs/docs-plan.md, секцию "2. docs/prompt-spec.md"
2. Прочитай docs/matrix-algo.md — оттуда берёшь названия арканов и позиции
3. Прочитай docs/исследование рынка.md — особенно разделы про позиционирование NURA как "союзника в самопознании" и требования к AI-чату
4. Прочитай nura_app/core/prompts/mini_analysis.txt — существующий промпт
5. Прочитай nura_app/core/prompts/full_report.txt — существующий промпт
6. Прочитай nura_app/core/services/ai.py — как вызывается AI
7. Прочитай nura_app/core/schemas.py — MiniAnalysisResult, FullReportResult
8. Прочитай docs/bot-spec.md — чтобы понимать контекст использования

Напиши документ в docs/prompt-spec.md.

Документ должен содержать:
- Полный system prompt для NURA (тон, правила, запреты)
- User prompt для мини-разбора + JSON Schema ответа (все поля с типами)
- User prompt для полного отчёта + JSON Schema ответа (с вложенностью)
- User prompt для совместимости + JSON Schema ответа
- User prompt для чата с NURA + инструкция по работе с контекстом
- Fallback-стратегия: что возвращать при таймауте, ошибке API, невалидном JSON
- Chain-of-thought инструкция: как AI должен рассуждать о матрице перед ответом
- Примеры хороших и плохих ответов AI для каждой фичи

После записи сделай commit: git add docs/prompt-spec.md и commit "Add prompt-spec.md"
```

---

## Шаг 3 — `docs/report-spec.md`

**Модель:** DeepSeek V4 Flash
**Агент:** ux-architect + ui-designer
**Зависит от:** шаг 2 (prompt-spec.md), шаг 4 (tone-of-voice.md)

```
Напиши документ docs/report-spec.md — Структура HTML и PDF отчёта.

Инструкции:
1. Прочитай docs/docs-plan.md, секцию "3. docs/report-spec.md"
2. Прочитай docs/prompt-spec.md — оттуда берёшь поля AI-ответа
3. Прочитай docs/tone-of-voice.md — тон текстов в отчёте
4. Прочитай nura_app/core/services/report.py — текущая генерация
5. Прочитай nura_app/core/config.py — настройки отчёта (report_base_url и т.д.)
6. Прочитай index.html — бренд-стили NURA (цвета, шрифты)
7. Прочитай docs/bot-spec.md — секции про отчёты и профиль

Напиши документ в docs/report-spec.md.

Документ должен содержать:
- Полный макет каждой секции отчёта (схематичное описание расположения)
- Переменные подстановки для каждой секции — какие поля из AI куда вставляются
- CSS Design System для html-версии отчёта (цвета, типографика, отступы из бренда NURA)
- Правила печатной версии: page-break, font-size, margins, @page
- Cover-страница: что на ней (лого, имя, архетип, дата)
- Секции: архетип, сильные стороны, теневые стороны, отношения, деньги, жизненные циклы, рекомендации на 7 дней, совместимость
- Каждая секция: заголовок, тело, стиль оформления, длина текста
- Адаптивность: mobile, desktop, print
- Брендинговые элементы: лого, цвета NURA (из index.html)

После записи сделай commit: git add docs/report-spec.md и commit "Add report-spec.md"
```

---

## Шаг 4 — `docs/tone-of-voice.md`

**Модель:** MiniMax M2.7
**Агент:** content-creator
**Параллельно с:** шаг 1

```
Напиши документ docs/tone-of-voice.md — Голос NURA.

Инструкции:
1. Прочитай docs/docs-plan.md, секцию "4. docs/tone-of-voice.md"
2. Прочитай docs/bot-spec.md — все тексты бота, особенно приветствие /start, инсайты, чат
3. Прочитай index.html — копирайтинг лендинга
4. Прочитай nura_app/core/services/ai.py — строку 49-53 (текущий system prompt)

Напиши документ в docs/tone-of-voice.md.

Документ должен содержать:
- Портрет NURA: кто она, как говорит, как НЕ говорит (3-5 предложений)
- Принципы: на "ты", тёплый друг, без эзотерики, без страха, ясность
- Слова-разрешители: ясность, видеть, сценарий, энергия, опора, карта и т.д.
- Слова-запретители: гадание, судьба (как рок), предсказание, карма, магия, чакры
- Таблица "как сказать": плохой пример → хороший пример (минимум 10 пар)
- Сегментация тона: как NURA говорит в боте vs в отчёте vs в чате (нюансы)
- Эмодзи-гайд: какие используем (✶ ◈ ☯ ✦ 🌒), какие НЕ используем (🔮✨🧙‍♀️)
- Примеры диалогов: 2-3 примера разговора с пользователем в правильном тоне

После записи сделай commit: git add docs/tone-of-voice.md и commit "Add tone-of-voice.md"
```

---

## Шаг 5 — `docs/bot-spec-audit.md`

**Модель:** DeepSeek V4 Pro
**Агент:** product-manager
**Зависит от:** ВСЕ шаги 1-4 завершены

```
Напиши документ docs/bot-spec-audit.md — Финальный аудит bot-spec.

Инструкции:
1. Прочитай docs/docs-plan.md, секцию "5. docs/bot-spec-audit.md"
2. Прочитай docs/bot-spec.md — проверяемый документ
3. Прочитай docs/matrix-algo.md — сверка названий арканов и позиций
4. Прочитай docs/prompt-spec.md — сверка полей AI
5. Прочитай docs/report-spec.md — сверка ссылок на отчёты
6. Прочитай docs/tone-of-voice.md — сверка тона

Проверь bot-spec.md на консистентность со всеми новыми spec'ами.

Напиши документ в docs/bot-spec-audit.md.

Что проверить:
- Все ли поля AI из prompt-spec отражены в текстах bot-spec
- Все ли названия арканов из matrix-algo совпадают с bot-spec
- Все ли callback_data и FSM-состояния покрывают флоу из новых spec'ов
- Нет ли расхождений в тоне с tone-of-voice.md
- Все ли ссылки на отчёты соответствуют report-spec.md
- Нет ли висячих колбэков или missing handlers
- Все ли тексты сообщений соответствуют тону NURA

Формат документа:
- Сводка: найденные расхождения (таблица: раздел bot-spec → проблема → как исправить)
- Итоговая рекомендация: что менять в bot-spec, в каком порядке

После записи сделай commit: git add docs/bot-spec-audit.md и commit "Add bot-spec-audit.md"
```

---

## Быстрая шпаргалка

| Шаг | Документ | Модель | Запускать когда |
|-----|----------|--------|-----------------|
| 1 | `matrix-algo.md` | DeepSeek V4 Pro | Сразу (параллельно с шагом 4) |
| 4 | `tone-of-voice.md` | MiniMax M2.7 
| 2 | `prompt-spec.md` | DeepSeek V4 Pro | После шагов 1 и 4 |
| 3 | `report-spec.md` | DeepSeek V4 Flash | После шага 2 |
| 5 | `bot-spec-audit.md` | DeepSeek V4 Pro | После всех шагов 1-4 |
