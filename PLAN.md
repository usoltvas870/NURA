# NURA — Plan

> Бэклог и приоритеты. Смотрит вперёд.
> История сделанного: [STATE.md](STATE.md). Контекст для агента: [AGENTS.md](nura_app/AGENTS.md).

---

## Now

- **Chat history persistence** — сохранять историю чата в Redis (сейчас теряется при перезапуске бота)
- **AI metrics** — structured logging для подсчёта токенов, latency, cache hit rate
- **Circuit Breaker** — если Part A full_report упала, не вызывать Part B (экономия токенов)

---

## Next

- **Chat history persistence** — сохранять историю чата в Redis (сейчас теряется при перезапуске бота)
- **AI metrics** — structured logging для подсчёта токенов, latency, cache hit rate
- **Circuit Breaker** — если Part A full_report упала, не вызывать Part B (экономия токенов)

---

## Ideas

- **A/B testing промптов** — сравнение качества при разных температурах/структурах
- **Multi-model fallback** — переключение на другую модель при отказе DeepSeek
- **Авто-регенерация отчётов** — если fallback задетекчен, перегенерировать через час
- **Semantic loop для совместимости** — `generate_compatibility()` тоже plain text, без проверок

---

## Done

- Phase 0: SemanticVerifier + loop_specs/ + gather fix + retry factory
- Phase 1: Кэширование portal/weekly/daily tarot
- Phase 2: Semantic loop для full_report
- Phase 3: Semantic loop для 7 tarot plain-text хендлеров
- Phase 4 partial: Degradation ladder (Level 1→Level 2), check_name_in_text(), generate_tarot_text(user_name)
- Удалён VideoPipeline и все медиа-сервисы
