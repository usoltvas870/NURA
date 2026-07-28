# Документация NURA

> **STATUS: SUPERSEDED — ARCHIVED ROUTER SNAPSHOT**
>
> Preserved to retain the pre-Stage-2A navigation baseline. Do not use as current authority.

## Текущий Telegram-first v1

> Текущий источник истины для решения о запуске Telegram-first v1: [`STATE.md`](../STATE.md), [sandbox acceptance runbook](telegram-first-sandbox-runbook.md), [readiness review](telegram-first-v1-readiness-review.md) и [launch checklist](launch-checklist.md). Локальная реализация и автоматизированная приёмка завершены, но внешний sandbox не выполнялся и production launch остаётся заблокированным.

- [Telegram-first sandbox acceptance runbook](telegram-first-sandbox-runbook.md) — режимы локального disposable PostgreSQL/Redis runner, диагностика и operator evidence.
- [Telegram-first v1 readiness review](telegram-first-v1-readiness-review.md) — локальный verdict, внешние gates, go/no-go и порядок действий оператора.
- [Launch checklist](launch-checklist.md) — текущие local/external/production gates перед сохранённым историческим PWA-планом.

Telegram-бот является текущим основным пользовательским интерфейсом v1. Документы PWA ниже сохранены как legacy/history и не являются текущим launch contract.

## Legacy / PWA

- [PWA North Star Design](pwa/PWA_NORTH_STAR_DESIGN.md) — продуктовая позиция и устойчивая визуальная направленность активной PWA.
- [PWA Implementation Rules](pwa/PWA_IMPLEMENTATION_RULES.md) — проверенные правила безопасного изменения PWA, её CSS, навигации и release metadata.
- [PWA Page Contracts](pwa/PWA_PAGE_CONTRACTS.md) — наблюдаемые контракты Home, Tarot, Chat, Profile и общей навигации.

Единый источник правды для продукта и разработки NURA — AI-проводника самопознания через Матрицу Судьбы и Таро-ритуалы.

> \\\\\\\*\\\\\\\*Текущее состояние проекта\\\\\\\*\\\\\\\* — всегда в `STATE.md` (корень репозитория).

\---

## Документы

### Продукт и стратегия

|Файл|Что описывает|Статус|
|-|-|-|
|`pricing.md`|Ценовая модель: матрица 890₽ разово + таро-подписка 390₽/мес|✅ Актуален|
|`benchmark-competitors.md`|Анализ 8 конкурентов, 956 отзывов, gap-анализ, таро-стратегия|✅ Актуален|
|`launch-checklist.md`|Всё что нужно до запуска: лендинг, миграции, тесты, деплой (\~40.5ч)|📝 План|
|`исследование\\\\\\\_рынка.md`|Исходное исследование рынка (основа для benchmark)|📦 Архив|

### Бот (Telegram)

|Файл|Что описывает|Статус|
|-|-|-|
|`bot-spec.md`|Полная функциональная спецификация бота: FSM, callbacks, тексты, клавиатуры|✅ Актуален|
|`bot-ux-map.md`|Карта пользовательских экранов: ASCII-макеты всех путей|✅ Актуален|
|`bot-spec-audit.md`|Аудит bot-spec от 14.05.2026: 48 расхождений (часть исправлена)|⚠️ Частично актуален|
|`two-layer-architecture.md`|Архитектура User Layer + Kitchen Layer|✅ Актуален|

### Отчёт (HTML/PDF)

|Файл|Что описывает|Статус|
|-|-|-|
|`report-spec.md`|Структура V2 отчёта: 17 секций ✅, 5 📋, шаблоны, CSS, переменные|✅ Актуален (V2)|

### Таро

|Файл|Что описывает|Статус|
|-|-|-|
|`tarot-integration-plan.md`|Интеграция таро на 4 поверхности: лендинг, бот, отчёт, PWA (\~40ч)|📝 План|
|`tarot-integration-plan-pwa-patch.md`|Патч под PWA-архитектуру: новый §10, обновлённые статусы, трудозатраты|✅ Готово|
|`tarot-integration-sessions.md`|9 шагов реализации таро: промпты, структура, логи сессий 12–17|📦 Архив|
|`bot-spec-pwa-patch.md`|Патч bot-spec под PWA: deep-link, open_pwa, link-токен, виральные кнопки|📝 План|
|`bot-ux-map-pwa-patch.md`|Патч bot-ux-map под PWA: обновлённые экраны меню, чата, подписки, связки|📝 План|

### AI и алгоритмы

|Файл|Что описывает|Статус|
|-|-|-|
|`matrix-algo.md`|Алгоритм расчёта Матрицы Судьбы, справочник 22 арканов|✅ Актуален|
|`prompt-spec.md`|Спецификация AI-промптов: форматы, JSON-схемы, fallback|✅ Актуален|

### Тон и коммуникация

|Файл|Что описывает|Статус|
|-|-|-|
|`tone-of-voice.md`|Голос NURA: принципы, запрещённые слова, эмодзи-гайд, исключения|✅ Актуален|

### Бренд и визуальная система

|Файл|Что описывает|Статус|
|-|-|-|
|`brand/nura-universe/README.md`|Визуальная вселенная NURA: 10 локаций, стиль, символы и правила использования|✅ Approved v1|
|`brand/nura-universe/assets-manifest.json`|Машиночитаемый манифест 24 визуальных ассетов для LOOPRA|✅ Approved v1|

### Разработка

|Файл|Что описывает|Статус|
|-|-|-|
|`agent-prompts.md`|Готовые промпты для запуска AI-агентов по шагам|✅ Актуален|
|`dev-prompts.md`|Промпты для разработки конкретных модулей|✅ Актуален|

### Эксплуатация

|Файл|Что описывает|Статус|
|-|-|-|
|`operations/backup-restore.md`|Synthetic-only disposable PostgreSQL backup/restore proof и его safety gates|✅ Актуален|
|`operations/p7a-security-configuration.md`|Redis secret-file hardening, APP_ENV contract, YooKassa verification facts и controlled P7B rollout|✅ Актуален|
|`operations/p7b-state-b-handoff.md`|Persistent State B handoff, baseline bootstrap, managed activation, compensation, recovery и canonical finalization|✅ Актуален|

\---

## Источник истины

* **`STATE.md`** (корень) — текущее состояние: что готово, блокеры, история сессий
* **Код всегда приоритетнее документации** — если расходятся, проверяй код

## Правила работы с документацией

1. **После каждой сессии** — обновить `STATE.md`: статусы, блокеры, запись в историю
2. **Устаревший документ** — пометить `⚠️ Устарел` в этой таблице, не удалять без явного решения
3. **Новый документ** — добавить строку в таблицу выше
4. **Цены** — единственный источник правды: `pricing.md`. Везде остальное — следствие

## Future v1.5

Подписка, gift access, возвратные сообщения и другие возможности v1.5 остаются будущим scope. Они не входят в текущий Telegram-first v1 и не являются его launch blockers.
