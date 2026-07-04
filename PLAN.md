# NURA — Plan

> Бэклог и приоритеты. Смотрит вперёд.
> История сделанного: [STATE.md](STATE.md). Контекст для агента: [AGENTS.md](nura_app/AGENTS.md).

---

## Now

- **Tarot chat history + FSM → Redis migration** — заменить FSM storage на Redis в bot/handlers/tarot.py для консистентности с chat
- **Сквозная трассировка ошибок (Sentry + structured logs)** — привязать structured extra из AIService.chat() к Sentry breadcrumbs
- **Multi-model fallback** — переключение на другую модель при отказе DeepSeek

---

## Next

- **Авто-регенерация отчётов** — если fallback задетекчен, перегенерировать через час
- **A/B testing промптов** — сравнение качества при разных температурах/структурах
- **Semantic loop для совместимости** — `generate_compatibility()` тоже без проверок

---

## Ideas

- **A/B testing промптов** — сравнение качества при разных температурах/структурах

---

## Done

- Phase 0: SemanticVerifier + loop_specs/ + gather fix + retry factory
- Phase 1: Кэширование portal/weekly/daily tarot
- Phase 2: Semantic loop для full_report
- Phase 3: Semantic loop для 7 tarot plain-text хендлеров
- Phase 4 partial: Degradation ladder (Level 1→Level 2), check_name_in_text(), generate_tarot_text(user_name)
- Удалён VideoPipeline и все медиа-сервисы
- **Chat history persistence** — история чата сохраняется в Redis (ключ `chat:history:{user_id}`, TTL 7 дней). bot и web синхронизированы.
- **AI metrics — structured logging** — `AIService.chat()` логирует method, model, tokens, duration_ms, cached, status через structured extra.
- **Circuit Breaker для full_report** — Part A → Part B последовательно: Part A упала → Part B не вызывается.
- **Loop Engineering fixup**: `_build_retry_prompt` активирован (retry с обратной связью), tarot_loop exhausted → fallback, 5 bypass-ов закрыты.
