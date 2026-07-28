# NURA: current implementation vs canonical target

**STATUS: DATED RECONCILIATION EVIDENCE — SUPERSEDED AS LIVE STATUS BY `docs/implementation/current-status.md`**

## Метод и границы

`CURRENT_IMPLEMENTED_STATE` определялся только по worktree-коду, миграциям, конфигурации и тестам. `CANONICAL_TARGET_PRODUCT` определялся по `NURA_1_0_1_5_PRODUCT_SPEC.md` от 2026-07-28. DOCX использовался только как человекочитаемая копия: после нормализации он покрывает 99,7% токенов Markdown; добавочный текст связан главным образом с оглавлением/Word-разметкой.

Локальная targeted-проверка завершилась `exit code 0`: 148 тестов прошли за 33,30 с. Она выполнена 2026-07-28 из `C:/git/NURA/nura_app` на ветке `main`, HEAD `61977175ef3b88fad618674fca2554db60aae379`, поверх исходного dirty worktree. Точная команда:

```powershell
$env:APP_ENV='test'; pytest tests/test_attribution.py tests/test_lifetime_chat_contract.py tests/test_daily_tarot_application.py tests/test_mini_report_application.py tests/test_mini_report_telegram_delivery.py tests/test_full_matrix_checkout.py tests/test_matrix_report_worker_lifecycle.py tests/test_full_report_telegram_delivery.py tests/test_payment_webhook_verification.py tests/test_my_reports.py -q
```

Это не full suite. Concurrent `docs/telegram-first-v1-readiness-review.md` появился после запуска и не входил в этот test baseline. Production/VPS не проверялись и не подразумеваются.

## Фактический baseline

| Область | Состояние | Доказательство | Оценка |
|---|---|---|---|
| Telegram identity и `/start` | User создаётся/обновляется по Telegram; deep-link attribution сохраняется. | `bot/handlers/start.py:57-97`, `core/services/attribution.py`, `core/models.py:302-357` | Реализовано |
| Consent и onboarding | Согласие ПД, дата рождения, расчёт Matrix, постановка mini generation. Имя как отдельный обязательный ввод не запрашивается: используется Telegram name/username. | `bot/handlers/start.py:90-118`, `bot/handlers/onboarding.py:32-65` | Частично относительно target |
| Мини-разбор | Durable generation; текст по 5 блокам; PDF; retry/replay; repeated delivery. | `core/services/telegram_report_delivery.py:150-279`, `core/models.py:527-653`, mini tests | Реализовано |
| Полный отчёт 890 ₽ | Dedicated one-time order, YooKassa redirect/webhook verification, idempotent activation, persisted generation job/artifact, automatic/repeated PDF delivery. | `core/services/full_matrix_checkout.py`, `core/services/matrix_report_worker.py`, `core/services/full_report_telegram_delivery.py`, tests | Реализовано по PDF; текст отсутствует |
| «Мои материалы» | В bot есть «Мои разборы», list/pagination и повторная доставка mini/full. | `bot/keyboards/main_menu.py:23-30`, `bot/handlers/profile.py:100-225`, `core/services/my_reports.py` | Частично: имя/UX отличаются, нет всех target material types |
| Web report | HTML/PDF routes по token и web CTA продолжают работать. | `api/routes/reports.py:126-149`, `bot/handlers/payment.py:299-398` | Legacy active; не target delivery |
| Чат | Единая durable quota для Telegram/web, 5 lifetime messages, idempotent reservation/result/consume, shared subscriber bypass. | `core/services/chat_quota.py`, `core/services/chat_application.py`, chat tests | Реализовано; reset policy не утверждена |
| Карта дня | Durable per-user/per-local-date result, Telegram/PWA handlers и Celery messaging. | `core/models.py:185-248`, `core/services/daily_tarot_application.py`, `bot/handlers/tarot.py` | Реализовано |
| Расклады Таро | Несколько prompts/handlers, PWA spread API, subscription paywalls, weekly/monthly tasks. | `bot/handlers/tarot.py`, `api/routes/tarot_pwa.py`, `core/tasks.py:855-1135` | Частично реализовано раньше 1.5; monetization legacy |
| Pricing/subscriptions | 890 one-time matrix + 390 legacy subscription/Tarot, saved payment method, recurring tasks. | `core/config.py:251`, `core/services/payment.py`, `bot/handlers/payment.py`, `core/tasks.py:1185-1362` | Реализовано, но конфликтует с target |
| YooKassa | Единственный найденный payment provider; provider verification, amount/currency/metadata checks и idempotency присутствуют. Telegram Stars invoice flow не найден. | `core/services/full_matrix_checkout.py`, `core/services/payment.py`, payment tests | Реализовано локально; sandbox/production не подтверждены |
| Broadcasts | Generic admin start/status + Telegram/push sending + простые free/premium filters; status хранится в Redis. | `api/routes/admin_api.py:896-919`, `core/tasks.py:1365-1493` | Частично |
| Campaign analytics/opt-out | Нет persisted BroadcastCampaign/Delivery; нет Telegram editorial opt-out, suppression, CTA attribution/frequency cap. | модели/миграции отсутствуют | Gap NURA 1.0 |
| Acquisition attribution | Registry links и first/repeat touch metadata по Telegram start parameter. | `AttributionLink`, `AttributionTouch`, service/tests | Реализовано foundation |
| Product event analytics | Нет канонического event model/registry для funnel/payment/report/chat/broadcast. | models/migrations/routes | Gap NURA 1.0 |
| Profile/settings/support | Профиль, reports, support и delete account есть; edit date перезапускает onboarding; Telegram notification preferences/«О NURA» не образуют target settings surface. | `bot/handlers/profile.py`, `bot/handlers/start.py` | Частично |
| Admin/support | Admin API: stats/users/payments/grants/regenerate/health/promos/broadcast/logs; admin bot status/restart/cache/help. | `api/routes/admin_api.py`, `admin_bot/` | Реализовано, но некоторые операции legacy subscription-centric |
| Reliability/security | Durable jobs/delivery, payment events, retries, account deletion, rate limits, Sentry scrubber, backup/restore proof, controlled release tooling. | services/tests, `docs/operations/*` | Сильный local baseline; production proof отдельно |
| Runtime prompt target | Текущие `system_prompt.txt` и `chat_system_prompt.txt` загружаются; canonical `NURA_RUNTIME_SYSTEM_PROMPT.md` отсутствует. | `core/services/ai.py:792-803` | Gap NURA 1.0 |
| Entitlements/gift 399 | Отдельного Entitlement aggregate/table, gift activation и 399/30-day purchase нет. | `core/models.py`, migrations | Gap NURA 1.5 |
| Referral/compatibility | Referral fields/reward model и compatibility bot/report flows уже есть. | `core/models.py:148-151,894-908`, `bot/handlers/compatibility.py` | Частично, раньше target 1.5B |

## NURA 1.0 target и gaps

| Target 1.0 | Current | Gap / действие |
|---|---|---|
| Telegram-first funnel | Основной bot funnel существует, но меню и recovery продолжают вести в PWA. | Убрать legacy PWA как обязательный шаг; сохранить compatibility boundary. |
| Обязательные имя + дата + consent | Consent/date есть; отдельный user-chosen name не собирается. | Решить, достаточно ли Telegram first name; иначе добавить валидируемый шаг. |
| Бесплатный mini text + PDF | Есть. | Production acceptance и content review. |
| Full report 890 ₽, YooKassa only | One-time 890 flow есть. | Sandbox/production acceptance; устранить параллельную 390 subscription surface из 1.0. |
| Full report text + PDF in bot | Только PDF delivery durable. | P0 implementation gap. |
| «Мои материалы» | «Мои разборы» и resend есть. | Унифицировать naming и включить target material taxonomy. |
| 5 free chat messages | Lifetime shared 5 реализованы. | Владелец определяет reset window. |
| Daily card | Есть. | Проверить UX/cache/timezone against acceptance. |
| Minimal editorial broadcasts | Есть transport и admin trigger. | Нужны persisted campaign/delivery, test send, Telegram opt-out, CTA analytics, suppression/frequency policy. |
| Funnel/product analytics | Только acquisition attribution + operational stats. | Нужен minimal event contract и accepted KPI queries. |
| Runtime style prompt (report/chat) | Требуемого файла/версии нет. | P0 implementation gap. |
| Support, retry, observability, backup | Большая часть локально реализована. | Реальная sandbox/controlled-rollout проверка. |
| No subscription/gift/expanded spreads gating launch | Legacy 390/recurring и advanced Tarot живы. | Не должны определять 1.0 UX; нужна disposition/migration decision. |

## NURA 1.5 target

| Target 1.5 | Current | Статус |
|---|---|---|
| 30-day gift after full report purchase | Нет | Gap |
| Separate 399 ₽ / 30 days, no auto-renew | Есть 390 recurring subscription | Противоположная legacy model |
| Canonical Entitlement resolver/status/dates/refund | Legacy booleans/status fields | Gap |
| Expanded chat with fair use | Subscriber bypass есть, fair-use/cost control contract не подтверждён | Частично |
| Accepted set of spreads + saved readings | Handlers/prompts есть; отдельного durable TarotReading model не найдено, кроме daily draw | Частично |
| Weekly focus/monthly compass | Celery weekly/monthly Tarot messages есть, но target product semantics/persistence не приняты | Частично/не подтверждено |
| Lifecycle chains/suppression | Отдельные inactive/expiry tasks есть; canonical lifecycle state/campaign delivery отсутствует | Частично |
| Referrals/gift report/compatibility/additional profile | Referral foundation + compatibility есть; gift order и additional profiles отсутствуют | Частично |

## Только в документации

- `NURA_RUNTIME_SYSTEM_PROMPT.md` и его два accepted consumers.
- Полный report text delivery в Telegram.
- Canonical 1.0 broadcast campaign/delivery/opt-out/analytics contract.
- Canonical product event registry и KPI contract.
- NURA 1.5 entitlement, 30-day gift, 399 ₽ voluntary renewal, gift report, additional profile.
- Отдельные target rules для «Мои материалы», settings и lifecycle suppression.

## Только в коде либо существенно опережает актуальные документы

- Durable mini/full delivery ledgers, artifact hashes, retry/reconciliation и race handling.
- Dedicated `Order`/`PaymentAttempt`/`PaymentEvent` full-matrix financial aggregate.
- Lifetime cross-channel chat usage ledger.
- Durable daily Tarot draw.
- Attribution link/touch registry.
- Account-deletion reconciliation preserving financial records.
- Telegram-first PostgreSQL acceptance harnesses и Sentry scrubber.

## Неизвестные/неподтверждённые области

- Реальный production deployment, applied migration head и конфигурация без чтения secrets.
- YooKassa sandbox/production receipts, webhook reachability и refund path end-to-end.
- Реальная Telegram send limits, PDF size distribution и delivery replay на production data.
- Финальный human-reviewed content quality для mini/full/chat/runtime style layer.
- Точное quota reset window, migration ранних покупателей и disposition legacy subscriptions.
