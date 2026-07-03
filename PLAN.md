# NURA — Plan

> Бэклог и приоритеты. Смотрит вперёд.
> История сделанного: [STATE.md](STATE.md). Контекст для агента: [AGENTS.md](nura_app/AGENTS.md).

---

## Now

- **Tarot chat history + FSM → Redis migration** — заменить FSM storage на Redis в bot/handlers/tarot.py для консистентности с chat
- **Multi-model fallback** — переключение на другую модель при отказе DeepSeek
- **Авто-регенерация отчётов** — если fallback задетекчен, перегенерировать через час

---

## Next

- **Tarot chat history + FSM → Redis migration** — заменить FSM storage на Redis в bot/handlers/tarot.py для консистентности с chat
- **Сквозная трассировка ошибок (Sentry + structured logs)** — привязать structured extra к Sentry breadcrumbs
- **A/B testing промптов** — сравнение качества при разных температурах/структурах
- **Multi-model fallback** — переключение на другую модель при отказе DeepSeek
- **Авто-регенерация отчётов** — если fallback задетекчен, перегенерировать через час

---

## Ideas

- **A/B testing промптов** — сравнение качества при разных температурах/структурах
- **Semantic loop для совместимости** — `generate_compatibility()` тоже plain text, без проверок

---

## Done

- Phase 0: SemanticVerifier + loop_specs/ + gather fix + retry factory
- Phase 1: Кэширование portal/weekly/daily tarot
- Phase 2: Semantic loop для full_report
- Phase 3: Semantic loop для 7 tarot plain-text хендлеров
- Phase 4 partial: Degradation ladder (Level 1→Level 2), check_name_in_text(), generate_tarot_text(user_name)
- Удалён VideoPipeline и все медиа-сервисы
- **Chat history persistence** — история чата сохраняется в Redis (ключ `chat:history:{user_id}`, TTL 7 дней). bot (`enter_chat`, `chat_message`, `clear_chat`) и web (`web_chat`) синхронизированы.
- **AI metrics — structured logging** — `AIService.chat()` логирует method, model, tokens (prompt/completion/total), duration_ms, cached, status (success/fallback/failure/cached) через logger.info с structured extra во всех 9 вызовах.
- **Circuit Breaker для full_report** — Part A → Part B последовательно: если Part A упала, Part B не вызывается (экономия токенов). Было: параллельный asyncio.gather.
