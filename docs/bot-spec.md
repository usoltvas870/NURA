# NURA Telegram Bot — Technical Specification

> Prompt governance update (2026-07-31): free chat использует independent checked-in `chat/v1` bundle, pin при durable reservation и metadata вместе с `result_ready`. Duplicate/delivery retry replays persisted text без второго AI call. Quota, safety disposition и Telegram delivery contract не изменены. См. [runtime prompt governance](prompt-governance.md).

**Статус документа:** CURRENT TECHNICAL SPECIFICATION WITH TARGET CROSSWALK
**Проверено:** 2026-07-28
**Граница evidence:** локальный committed code baseline; external Telegram/YooKassa sandbox и production не подтверждены.

## 1. Authority and scope

Этот документ отвечает на вопросы о текущей технической архитектуре Telegram-бота, реализованных путях, implementation gaps до NURA 1.0, границе NURA 1.5 и legacy compatibility. Он не является product specification.

- Target NURA 1.0/1.5 определяет только [canonical product spec](product/NURA_1_0_1_5_PRODUCT_SPEC.md).
- Current implementation подтверждается code, migrations, config и tests; [current status](implementation/current-status.md) — компактное зеркало evidence.
- Telegram — основной интерфейс target NURA 1.0/1.5. Landing объясняет продукт и ведёт в бот; отдельный публичный Telegram-канал находится вне scope NURA 1.0/1.5.
- PWA, email/VK/guest auth и web-report links описываются только как legacy compatibility.
- Наличие handler, route или кнопки означает runtime reachability в локальном baseline, но не доказывает approved release scope, внешний sandbox или production availability.

## 2. Status legend

- `CURRENT — IMPLEMENTED` — путь подтверждён code/test evidence; это не production proof.
- `TARGET — NURA 1.0` — обязательный target из canonical spec; не утверждение о реализации.
- `TARGET — NURA 1.5` — расширение 1.5; не входит в NURA 1.0.
- `IMPLEMENTATION GAP` — target contract отсутствует или реализован не полностью.
- `OUT OF SCOPE — NURA 1.0/1.5` — поверхность прямо исключена из canonical target этих версий; это не implementation gap и не future roadmap.
- `LEGACY COMPATIBILITY` — действующий путь прежней PWA/subscription-модели, не current roadmap.
- `OWNER DECISION PENDING` — authority sources не содержат решения; документ его не принимает.
- `SUPERSEDED / HISTORICAL` — прежний план или описание, не current contract.

## 3. Product interface boundary

| Surface | Contract | Status |
|---|---|---|
| Telegram bot | Onboarding, профиль, материалы, checkout entry, delivery, chat, daily card и минимальная messaging surface | `TARGET — NURA 1.0`; значительная часть `CURRENT — IMPLEMENTED` |
| Landing | Короткий объясняющий вход с CTA/deep link в Telegram | `TARGET — NURA 1.0` |
| Public Telegram channel | Не входит в обязательные поверхности 1.0/1.5 | `OUT OF SCOPE — NURA 1.0/1.5` |
| PWA/web | Существующий web client, auth, chat, Tarot, report links и push | `LEGACY COMPATIBILITY` |
| Expanded Tarot, compatibility, referral | Реализация сохранена за explicit release flags; default NURA 1.0 скрывает UI и direct callbacks/deep-link entry | `CURRENT — DM-04 APPLIED` |

## 4. Current implemented architecture

### 4.1. Runtime and persistence

`CURRENT — IMPLEMENTED`

- `bot/main.py` создаёт aiogram `Dispatcher` с `RedisStorage`, регистрирует handlers/middlewares и запускает polling.
- PostgreSQL/SQLAlchemy хранит пользователей, consent timestamp, отчёты, заказы/платёжные события, chat usage, daily Tarot, delivery ledgers, attribution и referral foundation.
- Redis используется для FSM и chat history; legacy direct-broadcast task status остаётся только fail-closed compatibility evidence.
- Celery выполняет mini/full generation, Telegram delivery, service maintenance и reconciliation persisted broadcast campaigns. Legacy editorial Tarot/inactive/subscription-expiry/recurring-charge jobs не входят в default Beat schedule.
- FastAPI обслуживает YooKassa webhook/checkout, tokenized report routes, legacy web/PWA/auth и admin API.
- DeepSeek consumers загружают prompts только из `nura_app/core/prompts/`.
- Центральный middleware order для message/callback surfaces: registration → throttling → anti-flood; на message surface перед registration также работает legacy Telegram-auth retirement guard.
- `ThrottlingMiddleware` ограничивает до одного события в секунду, а `AntiFloodMiddleware` после более чем 10 событий за 60 секунд блокирует обработку на 30 секунд. Оба механизма применяются к messages и callbacks и хранят состояние в памяти процесса, поэтому не являются distributed/global rate limit между несколькими процессами.

Локальные acceptance tests используют реальные application/repository paths и fake Telegram/YooKassa/AI boundaries. External sandbox и production gates не выполнялись.

### 4.2. Identity, onboarding and consent

`CURRENT — IMPLEMENTED`

- `/start` создаёт/обновляет Telegram user, сохраняет normalized attribution touch и обрабатывает legacy/referral deep links.
- До даты рождения бот запрашивает согласие; принятие сохраняет `pd_consent_at`.
- После согласия FSM принимает и валидирует дату рождения, сохраняет Matrix archetype и ставит mini generation в Celery.
- Имя берётся из Telegram `first_name`/`username`; отдельного шага preferred-name нет.
- Consent timestamp хранится, но versioned consent text не найден.

Public wiring подтверждён bot router и локальным golden path; реальный Telegram sandbox не выполнен. Отдельное имя и consent versioning — `IMPLEMENTATION GAP` относительно NURA 1.0.

### 4.3. Navigation and profile

`CURRENT — IMPLEMENTED`

- `/start`, `/menu`, `/profile`, `/help` и callbacks ведут в inline-menu/profile flows.
- Main menu содержит Matrix, Tarot с бесплатной картой дня, chat, «Мои разборы», профиль и 890 ₽ CTA.
- Compatibility скрыта по умолчанию; `enable_compatibility=true` восстанавливает существующий путь. Expanded Tarot закрыт `enable_expanded_tarot=false` по умолчанию.
- Profile показывает Telegram name, birth date, Matrix/report state, legacy subscription controls и support contact.
- Target settings surface, preferred-name edit, consent/legal navigation и полноценная quota state не собраны в единый профиль.

Legacy PWA buttons — `LEGACY COMPATIBILITY`. Expanded Tarot, compatibility и referral promotion используют explicit false-by-default flags; закрытые callbacks дают нейтральный ответ и очищают FSM. Parsing legacy `ref_` deep links сохраняется без reward processing.

### 4.4. Mini-report

`CURRENT — IMPLEMENTED`

- Matrix calculation запускает durable mini generation; repeated requests не должны создавать дубли.
- `MiniReportTelegramDeliveryService` отправляет структурированный текст по пяти блокам и PDF document, сохраняет прогресс и поддерживает retry/replay.
- PDF artifact проверяется по MIME, hash, размеру и `%PDF-` signature.
- Mini доступен через «Мои разборы» и repeated delivery.

Внешняя content/safety review и Telegram sandbox остаются release gates, а не доказанной current production availability.

### 4.5. Full report, payments and delivery

`CURRENT — IMPLEMENTED`

- `buy_matrix` инициирует dedicated one-time Full Matrix checkout 890 ₽.
- `FullMatrixCheckoutService` создаёт durable order/payment attempt, формирует YooKassa redirect, проверяет provider state/webhook, сумму, валюту и metadata, идемпотентно активирует заказ и поддерживает refund fence.
- Checkout redirect возвращает браузер на `/api/v1/payment/full-matrix/return/{checkout_token}`. Эта return page всегда информационная («проверяем оплату»): её открытие или повторное открытие не подтверждает платёж, не переводит заказ в `PAID`, не выдаёт entitlement и не запускает trusted delivery.
- Активация выполняется только после verified YooKassa webhook/provider verification; browser return не является доверенной платёжной границей.
- После оплаты Celery формирует и сохраняет canonical full PDF, затем создаёт durable automatic delivery.
- `FullReportTelegramDeliveryService` отправляет immutable snapshot полного текста и затем PDF document/cached Telegram `file_id`, поддерживает manual resend, retry/reconciliation и блокирует дальнейшую delivery после refund.
- Snapshot и каждый sent text message ID сохраняются durable; retry не вызывает AI, Matrix, checkout или chat quota.
- Tokenized HTML/PDF routes и web CTA продолжают существовать.

Итого: 890 ₽ + YooKassa + durable full Telegram text + PDF delivery — `CURRENT — IMPLEMENTED` локально; web-report route — `LEGACY COMPATIBILITY`. YooKassa sandbox, receipt и real webhook reachability не подтверждены.

### 4.6. Saved materials

- «Мои разборы» перечисляет завершённые mini и full reports с ownership check, detail callback и repeated Telegram delivery.
- Mini и full повторно доставляются сохранённым текстом и PDF через отдельные delivery ledgers.
- Текущая taxonomy и labels неполны: full item может отображаться как «Мини-разбор», а target «Мои материалы» включает более точные типы и metadata.
- Просмотр/resend не использует chat quota.

Taxonomy/naming — `IMPLEMENTATION GAP`; сохранение и repeated delivery — `CURRENT — IMPLEMENTED`.

### 4.7. Chat and quota

`CURRENT — IMPLEMENTED`

- Telegram и web используют общий `ChatMessageUsage` ledger и channel-neutral `ChatApplicationService`.
- Telegram handler вызывает `_has_chat_access`, но current helper безусловно возвращает `True`: обычный пользователь входит в Telegram chat без `has_matrix` и доходит до quota service.
- Verified full-matrix payment устанавливает `has_matrix=True`, но этот marker не управляет текущим chat access и не даёт quota bypass. Пользователь с купленной Матрицей остаётся на том же lifetime limit 5, если у него нет активного legacy entitlement.
- Активная legacy Tarot subscription или premium state с неистёкшим сроком даёт unlimited quota bypass. Отдельный `_has_unlimited_chat` helper с ветками для test mode и `has_matrix` не подключён к фактическому chat flow и не является current production access contract.
- Free limit берётся из `settings.chat_free_message_limit` (5), но считается за всё время пользователя, без date/window reset.
- Reservation предотвращает параллельный overspend; consume происходит после generation, сохранения результата и history finalization.
- Provider/fallback failure освобождает reservation; duplicate request возвращает сохранённый результат без повторного списания.
- В current greeting нет канонического набора 4–6 guided entry buttons.

Обычный зарегистрированный Telegram user входит в чат без `has_matrix`. Telegram и web используют общий `ChatMessageUsage` ledger: для Free это пять календарных committed-ответов с reset `00:00 Europe/Moscow` (`chat_quota_timezone`). Ответ сохраняется и финализирует history до transport; Telegram consume выполняется только после успешного send. `has_matrix` не даёт bypass; только активный legacy entitlement или development `test_mode` дают unlimited access. До полного delivery-aware contract остаются durable retry/progress для failed multipart Telegram transport и client ACK для web.

### 4.8. Daily card and expanded Tarot

- Daily card: durable one-result-per-user/local-date application/repository flow, Telegram callback и reuse/retry — `CURRENT — IMPLEMENTED`.
- Expanded spreads: multiple handlers/prompts, PWA route, scheduled weekly/monthly jobs and 390 ₽ paywall exist; видимый runtime entry должен быть скрыт из primary user path по DM-04 — `IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04`.
- No dedicated feature flag for expanded Tarot was found.
- Canonical expanded Tarot, accepted set, saved `TarotReading` history, gift/399 entitlement and fair-use model belong to `TARGET — NURA 1.5`.

### 4.9. Compatibility and referral

- Compatibility is linked from main menu, collects partner name/relation/date, generates a result, marks lifetime use and exposes sharing/390 ₽ upsell — `IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04`.
- Referral deep links, `referred_by` and `ReferralReward` registration event exist; profile exposes referral link — `IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04`.
- Dedicated release flags were not found. Canonical compatibility/referral are `TARGET — NURA 1.5B`, not NURA 1.0.

### 4.10. Broadcasts

`CURRENT — IMPLEMENTED` locally as the minimal manual NURA 1.0 campaign contour.

- Admin API supports create/list/get/update, estimate, exact-version test send, idempotent launch, safe pre-claim cancel and stats. Mutations require authenticated admin access plus bounded `X-Admin-Actor`; audit entries persist actor, action, reason and bounded evidence.
- Campaign content is snapshotted and immutable after queueing. Supported content is Telegram HTML text with optional Telegram `photo`/`animation`/`video` `file_id` and one or two allowlisted inline CTAs.
- Canonical segments are `all_editorial_enabled`, `mini_completed_without_full_purchase`, `full_report_purchasers`, `onboarding_incomplete` and bounded `inactive` days. Selection always excludes editorial opt-out, active Telegram suppression and users at the shared editorial/commercial frequency cap.
- Test send goes only to configured admin allowlist recipients and records the tested content version. Launch requires matching estimate and test versions, persists one delivery row per selected user and rejects duplicate logical launch while safely replaying the same idempotency key.
- Delivery rechecks user preference, suppression and cap under lock, persists attempts/media/text progress, fences stale attempts and classifies retryable, terminal and blocked outcomes. Block/chat-not-found creates durable suppression; `/start` releases only automatic suppression after a real inbound user action.
- `/settings` and the profile settings entry expose the explicit editorial preference. PWA `news` preference remains a compatibility alias synchronized to the same field. Service messages such as paid-report delivery are outside this opt-out.
- CTA callbacks use opaque delivery tokens, validate ownership and the snapshotted allowlist destination, persist bounded click counts and route through existing bot functions. Stats expose selected/delivery outcomes, click aggregates and deterministic last-click paid-order attribution inside each campaign window; one paid order is counted for at most one campaign.
- The previous direct `/broadcast` path returns `410`, and its registered legacy Celery task fails closed without sending. The default Beat schedule retains service maintenance plus campaign reconciliation but no longer schedules weekly/monthly editorial Tarot, inactive-user broadcast, subscription-expiry or recurring-charge jobs.

External Telegram sandbox, production operator permissions and content approval remain `NOT_EXECUTED`. Advanced scheduling, lifecycle chains, quiet hours and A/B tests remain `TARGET — NURA 1.5`; the minimal NURA 1.0 contour includes the shared frequency cap and bounded attribution window required by its accepted contract.

### 4.11. Runtime prompts

`CURRENT — IMPLEMENTED LOCALLY` for checked-in governance.

- Report generation resolves approved `report/v1` with one bundle pin for mini or full/kitchen retry paths.
- Free chat resolves independent approved `chat/v1` and persists version/hash/provider-source metadata with its durable result.
- Legacy Daily Card/Tarot/compatibility prompts remain outside the active report/chat defaults.
- External AI/provider content acceptance remains `NOT EXECUTED`; local contract tests do not substitute for it.

Executable prompt bodies remain only in `nura_app/core/prompts/`; documentation records contracts and evidence boundaries, not prompt snapshots.

### 4.12. Admin, support and observability

- Bot support opens configured Telegram contact; account deletion exists.
- Admin API/admin bot provide user/payment/report operations, stats and health; persisted broadcast campaign controls принадлежат Admin API, а не Admin Bot.
- Durable generation/delivery retries, correlation/audit data, Sentry scrubbing and local backup/restore evidence exist.
- Some admin/profile/payment operations remain subscription-centric legacy paths.
- Telegram/YooKassa external sandbox, legal/support process and production infrastructure acceptance remain unexecuted.

### 4.13. Account deletion and retained payment records

`CURRENT — IMPLEMENTED` at the service/retry boundary, with an `IMPLEMENTATION / LEGAL COPY GAP`.

- `/delete_account` removes the user, reports, full-delivery rows, report-generation jobs, legacy `Payment` rows, referral rewards and Redis chat history/marker.
- Financial audit rows are retained: `Order` is detached from direct user/Telegram/report/checkout identifiers and receives a hashed customer reference; `PaymentAttempt` and `PaymentEvent` remain. Confirmation URL/provider metadata are reduced, but `PaymentAttempt.fiscal_email` remains stored.
- Repeated deletion is safe when the user row is already absent. Database failure rolls back transactionally; a post-commit Redis failure can be retried to finish cache/history cleanup.
- Current bot copy promises deletion of «всех данных», which is broader than the retained payment/fiscal evidence. Retention term, legal basis and any further anonymization require owner/legal decision and are not chosen here.

## 5. Target NURA 1.0 crosswalk

| Capability | Canonical NURA 1.0 target | Current implementation | Status / gap | Governing source |
|---|---|---|---|---|
| Telegram onboarding | Telegram-first welcome and resumable onboarding | Telegram identity, `/start`, FSM and return menu exist | `CURRENT — IMPLEMENTED`; external sandbox pending | Product spec §§7, 9; `start.py` |
| Name/date collection | Preferred name + birth date | Telegram name reused; birth date validated/stored | `IMPLEMENTATION GAP` — no explicit preferred-name step | Product spec §9.1 |
| Consent | Explain use/safety/legal links; persist version and time | Consent callback and timestamp exist | `IMPLEMENTATION GAP` — versioned consent/legal surface incomplete | Product spec §9.2 |
| Mini-report | Telegram text + PDF, saved/retryable | Durable text + PDF delivery and resend | `CURRENT — IMPLEMENTED` locally; external/content acceptance pending | Product spec §10; mini delivery service/tests |
| Saved materials | Mini/full text/PDF persist independently of chat quota | «Мои разборы» lists mini/full and resends | `IMPLEMENTATION GAP` — naming/taxonomy/metadata incomplete | Product spec §12; `my_reports.py` |
| Full report | One-time 890 ₽ finished product | Durable order/generation/full Telegram text + PDF | `CURRENT — IMPLEMENTED` locally | Product spec §11 |
| 890 ₽ / YooKassa | YooKassa only; no Stars/manual transfer | Dedicated checkout and verified webhook | `CURRENT — IMPLEMENTED` locally; sandbox/receipt pending | Product spec §§3.4, 11.3 |
| Telegram text delivery | Mini and full readable in chat | Durable mini/full text with progress and replay | `CURRENT — IMPLEMENTED` locally | Product spec §§3.5, 11.6 |
| Telegram PDF delivery | Mini/full document, repeatable | Durable mini/full PDF and replay/resend | `CURRENT — IMPLEMENTED` locally | Product spec §§10.2, 11.6 |
| Materials reopening | Open/resend without regeneration/payment | Ownership-checked list and repeated delivery | `CURRENT — IMPLEMENTED`; taxonomy gap | Product spec §12 |
| Free chat | Universal Telegram access; 5 successful delivered answers each product day | Ordinary users share five daily committed answers across Telegram/web; `has_matrix` does not bypass quota; active legacy entitlement remains unlimited | Daily/reset/access `CURRENT — IMPLEMENTED`; durable delivery retry/progress and web client ACK `IMPLEMENTATION GAP` | Product spec §13.1; Telegram chat handler/quota tests |
| Guided questions | 4–6 concrete entry topics | Generic examples in greeting; no canonical guided-button surface | `IMPLEMENTATION GAP` | Product spec §13.3 |
| Daily card | Free, one stable result per period | Durable per-user/local-date reuse | `CURRENT — IMPLEMENTED` locally | Product spec §14 |
| Minimal broadcasts | Manual campaign, test send, segment, CTA, idempotency, status | Persisted immutable campaign, five segments, exact-version estimate/test/launch, bounded delivery and stats | `CURRENT — IMPLEMENTED` locally; external sandbox pending | Product spec §16 |
| Opt-out | Editorial opt-out and suppression | Explicit Telegram/PWA-compatible preference plus durable blocked-user suppression and automatic `/start` release | `CURRENT — IMPLEMENTED` locally | Product spec §§16.6, 17.1 |
| Campaign tracking | campaign/delivery/click/conversion data | Persisted delivery outcomes, append-only CTA clicks and deterministic bounded last-click paid-order attribution | `CURRENT — IMPLEMENTED` for minimal campaign scope | Product spec §§16.8, 19 |
| Product analytics | Funnel/payment/report/chat/broadcast events and KPI queries | Acquisition link/touch plus campaign delivery/click/purchase queries; no unified cross-product event registry | `IMPLEMENTATION GAP` for unified registry/full funnel, not broadcast contour | Product spec §19 |
| Report/chat prompt contracts | Separate approved/versioned runtime contracts | Separate loaders/files exist | `IMPLEMENTATION GAP` — acceptance/version contract incomplete | Product spec §§3.7, 20 |
| Retry/support/observability | Recover payments/generation/delivery; support and monitoring | Strong durable/local foundation | `CURRENT — IMPLEMENTED` partially; external/legal/production gates pending | Product spec §§17–22; acceptance index |

### Local chat delivery evidence (2026-07-30)

The shared Telegram/PWA ledger now persists one request, stored response and logical delivery ID. Telegram records multipart progress after each completed chunk and commits quota only after the final chunk; retryable transport failures preserve the reservation and resume from the next persisted chunk. The PWA receives a stable delivery ID and commits through an owned, idempotent ACK endpoint after rendering. This is local implementation evidence only; no external Telegram, PWA runtime, AI, YooKassa or production sandbox was executed.

## 6. Target NURA 1.5 boundary

The following categories are `TARGET — NURA 1.5` only. Their full rules remain in the canonical spec:

- 30-day gift access after full-report purchase, without automatic charge;
- voluntary 399 ₽ / 30-day access and canonical entitlement resolver;
- expanded chat with fair-use/cost controls;
- accepted expanded Tarot set and saved reading history;
- weekly focus and monthly compass;
- lifecycle chains, suppression, scheduler, quiet hours and frequency caps;
- A/B testing and expanded attribution;
- referral, gift report, compatibility and additional profile as 1.5B growth.

`LEGACY RECURRING 390 ₽ SUBSCRIPTION PATH — NOT TARGET GIFT`: saved payment method and automatic-charge code are not the 30-day gift after full-report purchase and not the voluntary 399 ₽ / 30-day non-auto-renew target. Existing subscriber/saved-method migration remains undecided.

## 7. Legacy compatibility

| Legacy path | Current evidence | Constraint |
|---|---|---|
| PWA/web client | `frontend/pwa/app/`, web routes and PWA buttons | Compatibility client, not roadmap owner |
| Email/VK/guest auth | `/api/v1/auth/*` and auth services/tests | Web compatibility, not Telegram-first funnel |
| Web report links | `/report/{token}` and `/report/{token}/pdf`; bot/web CTA | Must not be required target delivery |
| Shared PWA chat | Same durable usage ledger as Telegram | Current ledger is lifetime; target daily rule still missing |
| 390 ₽ subscription | config, Telegram/PWA checkout, saved method and recurring tasks | `LEGACY RECURRING 390 ₽ SUBSCRIPTION PATH — NOT TARGET GIFT`; conflicts with target and is neither NURA 1.0 nor target 1.5 access |
| Legacy push/lifecycle | PWA push plus inactive/expiry/recurring jobs | Not canonical 1.0 broadcast or 1.5 lifecycle contract |

`OWNER DECISION PENDING — compatibility support duration` for PWA, email/VK/guest auth and web-report links.
`OWNER DECISION PENDING — migration/disposition of legacy 390 ₽ subscribers and saved payment methods`.

No sunset date or migration behavior is introduced here.

## 8. Runtime-reachable early features and DM-04 gating gap

| Feature | Evidence | Classification |
|---|---|---|
| Expanded Tarot | Telegram handlers/keyboards, prompts, PWA API, scheduled jobs, 390 paywall; visible Tarot entry | `IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04` |
| Compatibility | Main-menu callback, FSM, generation/share flow, usage flag; visible menu entry | `IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04` |
| Referral | `ref_` deep link, profile link and reward record | `IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04` |
| 390 subscription/recurring | Telegram/PWA checkout, saved payment method, renewal/cancel tasks | `LEGACY COMPATIBILITY`; public migration state unresolved |

DM-04 already requires functions outside NURA 1.0 to be hidden from the primary user path through existing or new feature flags/gating and not promoted before their release; working implementation may remain. The exact flag design, beta/rollout parameters, migration and possible removal remain undecided and are not prescribed here.

## 9. Implementation gaps

| Gap | Current evidence | Target source | Documentation implication |
|---|---|---|---|
| Preferred-name onboarding | Telegram profile name only | Product spec §9.1 | Do not describe name collection as complete |
| Versioned consent/profile settings | `pd_consent_at`, limited profile | Product spec §§9.2, 9.5, 17 | Consent path exists, target surface incomplete |
| Full report Telegram text | Full delivery sends persisted text before PDF | Product spec §§3.5, 11.6 | External sandbox/content acceptance remains outstanding |
| Daily quota | Lifetime ledger without window | Product spec §13.1 | Always label lifetime current vs daily target |
| Guided chat entries | No canonical button set | Product spec §13.3 | Do not claim guided journey implemented |
| Materials taxonomy | «Мои разборы», incomplete labels/metadata | Product spec §12 | Saved access exists; target library incomplete |
| Broadcast external acceptance | Local persisted campaign/opt-out/delivery/click/paid-order analytics pass contract and PostgreSQL tests | Product spec §§16, 19; sandbox runbook | Do not claim real Telegram/provider or production readiness until approved external evidence exists |
| Product event registry/KPIs | Attribution foundation only | Product spec §19 | Do not infer funnel analytics from acquisition tracking |
| Approved report/chat runtime contracts | Separate files/loaders, no accepted version contract | Product spec §§3.7, 20 | Existing prompts are partial implementation |
| Early-feature visibility | No dedicated flags; primary menu/profile wiring exists | Product spec §§23–32; migration decision DM-04 | Treat current visibility as an implementation gap; do not invent exact gating/rollout mechanics |
| Account deletion legal copy | Payment/audit rows and fiscal email are retained after user deletion | Current service/tests; owner/legal decision required | Do not promise deletion of all data or invent retention terms/legal basis |
| External and production acceptance | Local fakes/pass evidence only | Product spec §22 | Local PASS is not sandbox/production proof |

## 10. References

- [Canonical target NURA 1.0/1.5](product/NURA_1_0_1_5_PRODUCT_SPEC.md)
- [Current implementation mirror](implementation/current-status.md)
- [Owner migration decisions](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md)
- [Telegram UX map](bot-ux-map.md)
- [Acceptance index](acceptance/README.md)
- [Local Telegram-first sandbox runbook](acceptance/telegram-first-sandbox.md)
- [Dated reconciliation evidence](reconciliation/2026-07-28/CURRENT_IMPLEMENTATION_VS_TARGET.md)
- Payment/pricing details remain in the pending consolidation group: [pricing](pricing.md) and [payment flow audit](audits/PAYMENT_FLOW_AUDIT.md).
- Report internals remain in the pending consolidation group: [report spec](report-spec.md) and [two-layer architecture](two-layer-architecture.md).
