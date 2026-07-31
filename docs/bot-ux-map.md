# NURA Telegram Bot — UX Journey Map

> Prompt governance update (2026-07-31): UX entries и quota/delivery journeys не менялись. Новые substantive chat answers и report artifacts теперь имеют доказуемые bundle/version/hash/provider-source metadata; Matrix не обязана упоминаться в каждом chat answer. См. [runtime prompt governance](prompt-governance.md).

**Статус документа:** CURRENT UX MAP WITH TARGET CROSSWALK
**Проверено:** 2026-07-28
**Граница evidence:** локальный committed code baseline; external Telegram/YooKassa sandbox и production не подтверждены.

## 1. Scope and authority

Документ показывает пользовательские пути Telegram-бота: что доступно сейчас, чем путь должен стать в NURA 1.0, что относится к NURA 1.5 и какие legacy-переходы ещё достижимы. Тексты экранов здесь — смысловые состояния, а не утверждённый copy deck.

- Target определяет только [canonical product spec](product/NURA_1_0_1_5_PRODUCT_SPEC.md).
- Current подтверждается handlers, services, repositories, config и tests; [current status](implementation/current-status.md) служит компактным evidence mirror.
- Технические детали и subsystem crosswalk находятся в [bot technical specification](bot-spec.md).
- Наличие кнопки или route доказывает runtime reachability, но не release approval, внешний sandbox или production availability.

## 2. Status legend

- `CURRENT — IMPLEMENTED` — путь подтверждён code/test evidence; это не production proof.
- `TARGET — NURA 1.0` — обязательный target из canonical spec; не утверждение о реализации.
- `TARGET — NURA 1.5` — расширение 1.5; не входит в NURA 1.0.
- `IMPLEMENTATION GAP` — target contract отсутствует или реализован не полностью.
- `OUT OF SCOPE — NURA 1.0/1.5` — поверхность прямо исключена из canonical target этих версий; это не implementation gap и не future roadmap.
- `LEGACY COMPATIBILITY` — действующий путь прежней PWA/subscription-модели, не current roadmap.
- `OWNER DECISION PENDING` — authority sources не содержат решения; документ его не принимает.
- `SUPERSEDED / HISTORICAL` — прежний план или описание, не current contract.

Обозначения путей: `→` действие пользователя; `⇒` автоматический переход; `↺` повтор/возврат; `×` отказ или ошибка.

## 3. Current journeys

### 3.1. First start, consent and birth date

`CURRENT — IMPLEMENTED`, с target gaps.

| Aspect | Current behavior |
|---|---|
| Entry | `/start`, включая deep link/attribution/referral payload |
| User action | Принимает consent callback, затем вводит дату рождения |
| Bot response | Приветствие/consent prompt, запрос даты, validation feedback, запуск расчёта |
| Persisted state | Telegram identity, attribution touch, `pd_consent_at`, birth date, Matrix archetype, FSM state |
| Quota/payment | Не применяются |
| Success | Mini generation поставлена в очередь; пользователь может вернуться в menu/profile |
| Failure/retry | Неверная дата запрашивается повторно; незавершённый FSM можно продолжить |
| Current limits | Preferred name отдельно не спрашивается; используется Telegram name. Consent text version не хранится |
| Evidence | `bot/handlers/start.py`, `bot/handlers/onboarding.py`, user repository/model, onboarding tests |

```text
/start
  → consent prompt
  → «Согласна»
  ⇒ persist consent timestamp
  → birth date
  ⇒ validate and persist
  ⇒ calculate archetype
  ⇒ enqueue mini generation
```

`IMPLEMENTATION GAP`: target NURA 1.0 требует явные preferred name + birth date, понятное объяснение обработки данных, links к privacy/offer и versioned consent.

### 3.2. Returning user and main navigation

`CURRENT — IMPLEMENTED`.

| Aspect | Current behavior |
|---|---|
| Entry | `/start`, `/menu`, completion callbacks, profile/menu return |
| User action | Выбирает Matrix, Tarot с бесплатной картой дня, chat, reports или profile; compatibility видна только при явном release flag |
| Bot response | Inline main menu и feature-specific message |
| Persisted state | User/report/order state читается из PostgreSQL; transient interaction state — Redis FSM |
| Quota/payment | Зависит от выбранной функции |
| Success | Переход к выбранному current/runtime-reachable flow |
| Failure/retry | Callback alerts/messages; возврат в menu |
| Current limits | Menu смешивает current, legacy и early 1.5 surfaces; PWA/email/VK entry заметен |
| Evidence | `bot/keyboards/main_menu.py`, feature handlers and router registration |

Expanded Tarot и compatibility видимы в menu, а referral link — в profile, хотя DM-04 требует скрыть функции вне NURA 1.0 из primary user path до соответствующего release — `IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04`. PWA entry — `LEGACY COMPATIBILITY`.

### 3.3. Mini-report generation and delivery

`CURRENT — IMPLEMENTED` locally.

| Aspect | Current behavior |
|---|---|
| Entry | Завершение onboarding/Matrix calculation или повторный доступ из «Мои разборы» |
| User action | Ждёт generation либо выбирает сохранённый mini |
| Bot response | Структурированный текст по пяти блокам и PDF document |
| Persisted state | Report/artifact, generation state, delivery progress, hashes/Telegram file metadata |
| Quota/payment | Бесплатно; chat quota не расходуется |
| Success | Текст и PDF доставлены; artifact доступен для repeated delivery |
| Failure/retry | Durable retry/replay продолжает с сохранённого шага, не дублируя завершённое |
| Current limits | External Telegram/content/safety acceptance не выполнена |
| Evidence | `core/services/telegram_report_delivery.py`, report generation/tasks, delivery tests, acceptance runbook |

```text
birth date saved
  ⇒ generate mini
  ⇒ persist artifact
  ⇒ send Telegram text
  ⇒ send Telegram PDF
  ⇒ persist delivery completion
```

### 3.4. Full report purchase and delivery

`CURRENT — IMPLEMENTED` partially; local evidence only.

| Aspect | Current behavior |
|---|---|
| Entry | 890 ₽ CTA / `buy_matrix` |
| User action | Открывает YooKassa redirect и оплачивает |
| Bot response | Checkout link/status; browser return показывает только информационное «проверяем оплату»; после verified webhook/provider verification — generation и text-then-PDF delivery |
| Persisted state | Order, payment attempt/event, full report artifact, generation/delivery ledgers |
| Quota/payment | One-time 890 ₽; verified amount/currency/metadata; idempotent activation |
| Success | Canonical full text доставлен в Telegram до PDF и оба артефакта доступны для resend |
| Failure/retry | Browser return не подтверждает оплату и при повторном открытии остаётся информационным; webhook verification/reconciliation, generation retry, manual/automatic delivery retry; refund blocks delivery |
| Current limits | External YooKassa/Telegram sandbox и receipt path не подтверждены |
| Evidence | `core/services/full_matrix_checkout.py`, `api/routes/payment.py`, `core/services/full_report_telegram_delivery.py`, tests/acceptance |

```text
890 ₽ CTA
  → YooKassa checkout
  → informational browser return (no activation/entitlement/delivery)
  ⇒ verified successful payment
  ⇒ activate order once
  ⇒ generate and persist full PDF
  ⇒ send persisted Telegram text chunks
  ⇒ send Telegram PDF
  ↺ resend from saved materials if requested
```

`CURRENT — IMPLEMENTED locally`: NURA 1.0 full delivery отправляет persisted text и затем PDF; external sandbox не выполнялся.

### 3.5. Saved reports/materials

`CURRENT — IMPLEMENTED`, с taxonomy gap.

| Aspect | Current behavior |
|---|---|
| Entry | Main menu → «Мои разборы» |
| User action | Выбирает mini/full item и запрашивает повторную доставку |
| Bot response | Показывает список/detail; mini и full отправляют текст+PDF |
| Persisted state | Report ownership/status/artifact and delivery records |
| Quota/payment | Повторный просмотр не расходует chat quota и не требует повторной оплаты |
| Success | Сохранённый artifact повторно доставлен без regeneration |
| Failure/retry | Missing/not-ready/ownership cases получают controlled response; delivery можно повторить |
| Current limits | Раздел называется «Мои разборы»; full может иметь label «Мини-разбор»; target types/metadata неполны |
| Evidence | `core/services/my_reports.py`, profile/report callbacks, delivery services/tests |

`IMPLEMENTATION GAP`: единая target-библиотека «Мои материалы» с точной taxonomy, типом, датой, статусом и доступными форматами.

### 3.6. Free chat

Универсальный Telegram entry и daily quota/reset — `CURRENT — IMPLEMENTED` локально; durable delivery-aware retry/progress остаётся `IMPLEMENTATION GAP`.

| Aspect | Current behavior |
|---|---|
| Entry | Main menu → «Чат с NURA»; `_has_chat_access` безусловно возвращает `True`, поэтому ordinary user входит без `has_matrix`; legacy PWA chat uses the same application layer |
| User action | Отправляет свободный текст |
| Bot response | Ordinary user, включая пользователя без `has_matrix`, получает AI answer либо controlled daily-limit/failure response |
| Persisted state | Durable request reservation/result/consumption; conversation history in Redis |
| Quota/payment | Non-subscriber получает 5 успешно доставленных ответов за календарный день в shared Telegram/web ledger (`Europe/Moscow`). `has_matrix` не меняет access/quota; active legacy premium/subscriber bypasses quota |
| Success | Generation и history finalization завершены; Telegram consume выполняется после успешной отправки всех chunks |
| Failure/retry | Provider/fallback releases reservation; persistence/send failure не создаёт consumed usage; duplicate request replays durable result без второго AI-вызова или charge |
| Current limits | Canonical guided-button surface не реализован; external Telegram acceptance не выполнена |
| Evidence | `bot/handlers/chat.py`, `core/services/full_matrix_checkout.py`, `core/services/chat_quota.py`, chat application/history services and tests |

Локально реализованы universal entry, календарный reset `00:00 Europe/Moscow` и shared ledger. Активный legacy subscriber bypasses quota; `has_matrix` не участвует в access или bypass. `test_mode` остаётся development-only bypass. Для полного NURA 1.0 delivery-aware contract ещё нужны durable retry/progress при Telegram transport failure и client ACK после web rendering.

При lifetime-limit current chat возвращает limit response; menu, сохранённые материалы, PDF и daily card остаются отдельными путями и не расходуют chat quota.

#### Local free-chat delivery evidence (2026-07-30)

The daily shared ledger persists Telegram chunk index/attempt/error state and only consumes quota once all response chunks are recorded as delivered. Retryable failures retain the saved response and reservation; terminal or controlled-expiry failures release it. The legacy PWA receives a delivery ID and calls an owned idempotent ACK after it renders the reply. External Telegram/PWA runtime acceptance was not executed.

### 3.7. Daily card

`CURRENT — IMPLEMENTED` locally.

| Aspect | Current behavior |
|---|---|
| Entry | Tarot/menu callback for daily card |
| User action | Запрашивает карту дня |
| Bot response | Stable daily result; repeated request returns the same result |
| Persisted state | One reading per user/local date |
| Quota/payment | Бесплатно; chat quota не расходуется |
| Success | Result stored and delivered/reused |
| Failure/retry | Repository/application retry preserves one-result invariant |
| Current limits | External Telegram acceptance not executed |
| Evidence | `core/services/daily_tarot_application.py`, handler/repository/tests |

### 3.8. Expanded Tarot

`IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04`.

| Aspect | Current behavior |
|---|---|
| Entry | Tarot menu/handlers and legacy PWA routes |
| User action | Chooses spread or reaches 390 ₽ paywall |
| Bot response | Generated reading/paywall; scheduled weekly/monthly messages also exist |
| Persisted state | Mix of handler/application state and legacy subscription state |
| Quota/payment | Current code uses 390 ₽ subscription assumptions |
| Success | Runtime handlers and prompts can produce expanded results |
| Failure/retry | Handler/task-specific responses; no single accepted release contract |
| Current limits | No dedicated feature flag found; visible primary entry conflicts with DM-04; current set/paywall do not equal canonical 1.5 |
| Evidence | Tarot handlers/keyboards/prompts, PWA routes, scheduled tasks, config |

Canonical expanded Tarot/history/fair-use belongs to `TARGET — NURA 1.5`.

### 3.9. Compatibility and referral

Both are runtime-reachable and belong canonically to `TARGET — NURA 1.5B`; their current primary-path visibility is an `IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04`.

| Journey | Current entry/action/response | Persistence/payment | Limits/evidence |
|---|---|---|---|
| Compatibility | Main menu → collect partner name/relation/date → generate/share result | One-use marker; 390 ₽ upsell path | Visible handler/FSM exists; no release flag; primary-path visibility conflicts with DM-04 |
| Referral | `/start ref_*` → attribute inviter → registration reward event; profile exposes referral link | `referred_by`, `ReferralReward` | Foundation exists; profile visibility conflicts with DM-04; full target rules/economics absent |

### 3.10. Profile, support and deletion

`CURRENT — IMPLEMENTED` with legacy elements.

| Aspect | Current behavior |
|---|---|
| Entry | `/profile`, `/help`, `/delete_account`, menu callbacks |
| User action | Views stored identity/report state, opens support, requests deletion or legacy subscription action |
| Bot response | Profile/support contact/confirmation flows |
| Persisted state | User identity, birth date, consent timestamp, report/subscription state; deletion removes user/report/delivery/job/legacy-payment/referral rows and Redis chat data, but retains detached financial audit rows |
| Quota/payment | Profile does not consume chat quota; legacy subscription actions may affect payment state |
| Success | Deletion detaches `Order`, keeps `PaymentAttempt`/`PaymentEvent`, reduces selected payment metadata and removes direct user linkage; repeated request is safe |
| Failure/retry | Database failure rolls back; post-commit Redis cleanup failure can be retried; other controls use callback response/support escalation |
| Current limits | `PaymentAttempt.fiscal_email` remains; bot copy promises deletion of «всех данных», which is an `IMPLEMENTATION / LEGAL COPY GAP`. Retention term/legal basis/further anonymization are undecided; preferred-name, consent/legal settings and target entitlement view are also incomplete |
| Evidence | `bot/handlers/account.py`, `core/services/account_deletion.py`, `tests/test_full_matrix_account_deletion.py`, profile/help handlers |

### 3.11. Broadcast receipt, CTA and opt-out

`CURRENT — IMPLEMENTED` locally as the minimal manual Telegram campaign contour.

| Aspect | Current behavior |
|---|---|
| Entry | Operator creates, estimates, test-sends and idempotently launches an immutable campaign through Admin API; recipient receives Telegram text and optional Telegram-hosted media |
| User action | Reads message, follows one of one/two registered inline CTAs, or disables editorial messages in `/settings` / profile settings |
| Bot response | Opaque owned CTA opens only an allowlisted existing function: main menu, chat, daily Tarot, My Reports, full Matrix checkout or profile |
| Persisted state | Campaign/version/audit, one delivery per selected user, attempt/media/text progress, blocked suppression, preference and bounded click aggregate |
| Quota/payment | Receipt and CTA click do not consume chat quota; stats attribute an already-paid full Matrix order by bounded deterministic last click without changing payment state |
| Success | Delivery is terminal only after all configured message parts persist Telegram message IDs; repeated dispatch/launch does not create a second logical delivery |
| Failure/retry | Retryable failures retain progress and use fenced bounded attempts; terminal block/chat-not-found creates suppression; claim-time opt-out/cap/suppression recheck prevents a stale selection from sending |
| Current limits | External Telegram/content acceptance and production operator permissions are not executed; advanced scheduler/quiet hours/lifecycle/A-B orchestration remain 1.5 target |
| Evidence | Broadcast migration/models/repository/service/routes/handler plus `test_broadcast_campaign.py`, `test_broadcast_admin_api.py` and PostgreSQL claim proof |

The minimal NURA 1.0 path is locally implemented. It is not external Telegram sandbox evidence and does not authorize sending to real users.

### 3.12. Throttling and anti-flood

Rapid messages and callbacks pass through registration → throttling → anti-flood; the message surface also has a preceding legacy Telegram-auth retirement guard. Throttling permits one event per second. Anti-flood blocks processing for 30 seconds after more than 10 events within 60 seconds. Both stores are process-local in-memory state, not a distributed/global limit across workers; the detailed contract belongs to [bot technical specification](bot-spec.md#41-runtime-and-persistence).

## 4. Target NURA 1.0 funnel

This is a target crosswalk, not a claim that every step exists.

| Step | Target user journey | Current status |
|---:|---|---|
| 1 | Landing/deep link explains NURA and opens Telegram bot | `TARGET — NURA 1.0`; deep-link handling `CURRENT — IMPLEMENTED`, landing acceptance outside this map |
| 2 | Welcome asks preferred name | `IMPLEMENTATION GAP` — Telegram name reused |
| 3 | Bot collects validated birth date | `CURRENT — IMPLEMENTED` |
| 4 | User sees data-use explanation, privacy/offer links and accepts versioned consent | `IMPLEMENTATION GAP` — timestamp only/limited surface |
| 5 | Bot calculates and persists Matrix/mini | `CURRENT — IMPLEMENTED` locally |
| 6 | Mini arrives as readable Telegram text + PDF | `CURRENT — IMPLEMENTED` locally; external/content acceptance pending |
| 7 | User opens «Мои материалы» and can reopen/resend mini | `CURRENT — IMPLEMENTED` foundation; `IMPLEMENTATION GAP` taxonomy/metadata |
| 8 | User buys one-time full report for 890 ₽ through YooKassa | `CURRENT — IMPLEMENTED` locally; sandbox/receipt pending |
| 9 | Full report arrives as Telegram text + PDF and remains saved | `CURRENT — IMPLEMENTED` locally; external sandbox pending |
| 10 | User asks guided/free questions | Universal free Telegram entry and quota foundation are `CURRENT — IMPLEMENTED`; guided buttons are `IMPLEMENTATION GAP` |
| 11 | First 5 successfully delivered answers per Moscow product day are free across channels | `IMPLEMENTATION GAP` — current ledger is lifetime |
| 12 | User receives one stable free daily card | `CURRENT — IMPLEMENTED` locally |
| 13 | User can manage profile, consent/legal links, support and deletion | Partial `CURRENT — IMPLEMENTED`; target settings/consent surface incomplete |
| 14 | Minimal manual messaging uses persisted campaign/delivery, test send, segment, CTA, opt-out and analytics | `CURRENT — IMPLEMENTED` locally; external sandbox pending |

## 5. Chat state matrix: current versus target

| State | Current response | Target NURA 1.0 response | Classification |
|---|---|---|---|
| Free user without matrix/legacy premium | Telegram chat is allowed; shared lifetime quota 5 applies | Enter Telegram chat and use the shared daily free allowance | Access `CURRENT — IMPLEMENTED`; quota window `IMPLEMENTATION GAP` |
| Verified full-matrix buyer (`has_matrix=True`) | Same Telegram access and lifetime quota 5 as an ordinary non-subscriber; marker gives no bypass | Same universal daily free rule; 1.5 gift is separate | Payment marker is not a chat entitlement; quota semantics gap |
| Test/internal state | `_has_unlimited_chat` mentions test mode and `has_matrix`, but is not called by the current chat flow | Not a product entitlement | Unused helper; no active production bypass |
| First eligible question | Reserve → generate → finalize history → consume | Same safety/idempotency principle, counted on successful delivery | Current foundation implemented; delivery semantics gap |
| Remaining free quota | Lifetime consumed count against 5 | Count 0–5 for current Moscow product day across Telegram/PWA | `IMPLEMENTATION GAP` |
| Day boundary | No reset | Reset at `00:00 Europe/Moscow` | `IMPLEMENTATION GAP` |
| Provider failure | Release reservation | Do not charge failed/undelivered answer | `CURRENT — IMPLEMENTED` partially |
| Duplicate request | Replay saved result without second charge | Same | `CURRENT — IMPLEMENTED` |
| Telegram delivery failure | Current consumption completes after generation/history finalization, not confirmed Telegram delivery | Release/retain quota until the answer is successfully delivered | `IMPLEMENTATION GAP` |
| Delivery retry | Not represented as a separate quota-safe delivery transaction | Retry must not consume a second answer | `IMPLEMENTATION GAP` |
| Telegram vs PWA | Shared durable ledger | Shared product-day ledger while PWA compatibility exists | Shared foundation implemented; window gap |
| Full-report buyer | Verified payment sets `has_matrix=True`; chat was already available and the same lifetime quota applies unless a separate legacy entitlement is active | Still NURA 1.0 universal free daily rule; 1.5 gift is separate | Payment marker does not control chat; daily semantics gap |
| Active 390 legacy subscriber | Bypasses quota | Not canonical NURA 1.0/1.5 entitlement | `LEGACY COMPATIBILITY` |
| Limit reached | Lifetime-limit response | Daily-limit response with next reset and allowed non-chat actions | `IMPLEMENTATION GAP` |
| Materials/menu/PDF/daily card/broadcast | Do not call chat quota consumption | Must remain available and not consume chat quota | `CURRENT — IMPLEMENTED` by boundary; consolidated target acceptance pending |
| Materials after exhaustion | Saved reports remain independently accessible | Materials remain available after daily quota is exhausted | `CURRENT — IMPLEMENTED` |
| Guided entry | Generic examples/free text | 4–6 specific guided topics plus free text | `IMPLEMENTATION GAP` |

## 6. Versioned feature matrix

| Surface / journey | Current implementation | NURA 1.0 target | NURA 1.5 target | Legacy compatibility | Release visibility |
|---|---|---|---|---|---|
| Onboarding | Telegram identity, consent timestamp, birth date | Preferred name, birth date, versioned consent | Refinement only | PWA auth is separate | confirmed current |
| Mini report | Text + PDF, durable replay | Required finished free artifact | Reused | Tokenized web view may remain | confirmed current |
| Full report | 890 ₽, durable Telegram text + PDF | 890 ₽, Telegram text + PDF | Purchase may start 30-day gift access | Tokenized web report remains reachable | confirmed current |
| Payments | One-time YooKassa 890 ₽ path | YooKassa one-time 890 ₽; Stars/manual transfers excluded | 30-day gift after full report; then voluntary 399 ₽ / 30 days, no auto-renew | `LEGACY RECURRING 390 ₽ SUBSCRIPTION PATH — NOT TARGET GIFT`; saved method and automatic charges | confirmed current |
| Materials | «Мои разборы», mini/full resend | Unified «Мои материалы» | Adds Tarot/history/gift artifacts | Web report access | confirmed current |
| Chat | Universal Telegram entry; ordinary users share five lifetime answers across Telegram/PWA; `has_matrix` has no effect; active legacy subscriber bypasses quota | Universal free Telegram entry; five delivered/day, Moscow reset | Gift/399 access, expanded fair-use | Shared PWA chat ledger and legacy subscriber bypass | daily/delivery-aware quota implementation gap |
| Daily card | Durable per user/local date | Required free habit | Continues | PWA Tarot route exists | confirmed current |
| Expanded Tarot | Telegram/PWA wiring with 390 assumptions | Excluded | Accepted set/history/access model | Existing PWA/paywall paths | `IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04` |
| Compatibility | Menu/FSM/generation/share flow | Excluded | Compatibility product in 1.5B | 390 upsell assumptions | `IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04` |
| Referral | Deep link, profile link and reward foundation | Excluded | Referral/growth in 1.5B | Early reward behavior | `IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04` |
| Broadcasts | Persisted manual campaign/test/segment/CTA/opt-out/delivery/analytics; legacy direct send fails closed | Persisted manual campaign/test/segment/CTA/opt-out/delivery/analytics | Advanced scheduler, lifecycle chains, quiet hours and A/B orchestration | Web push transport | NURA 1.0 local contract implemented; external sandbox pending |
| Lifecycle | Legacy scheduled inactive/expiry/recurring tasks exist | Excluded beyond minimal manual messaging | Chains, quiet hours, caps, attribution windows, A/B | Current legacy jobs | legacy only |
| Subscription/gift | Recurring 390 ₽ and saved method code | No subscription/gift access | Gift 30 days; voluntary 399 ₽ / 30 days without auto-renew | Existing 390 ₽ surface | legacy only |
| PWA/web | Active client, auth, reports, chat, Tarot and push | Compatibility surface only | Does not own roadmap | Entire row | legacy only |

## 7. Legacy PWA/web lane

This lane remains documented because it is reachable, not because it is the target funnel.

```text
Telegram menu or direct web entry
  → PWA / guest, email or VK auth
  → web chat / Tarot / tokenized report / push
  → shared user/report/chat/payment data where implemented
  ↺ return to Telegram
```

| Surface | Current role | Boundary |
|---|---|---|
| PWA | Existing web client for chat/Tarot/profile/report access | `LEGACY COMPATIBILITY`; Telegram remains product owner |
| Email/VK/guest auth | Existing web identity paths | `LEGACY COMPATIBILITY`; not required Telegram-first onboarding |
| Tokenized web reports | Existing HTML/PDF access | `LEGACY COMPATIBILITY`; cannot replace target Telegram text+PDF delivery |
| Web push | Existing notification transport | `LEGACY COMPATIBILITY`; not canonical campaign/opt-out system |
| 390 ₽ recurring | Saved method, automatic charges, renew/cancel and paywall paths | `LEGACY RECURRING 390 ₽ SUBSCRIPTION PATH — NOT TARGET GIFT`; migration/disposition remains undecided |

`OWNER DECISION PENDING — compatibility support duration` for PWA, email/VK/guest auth and web-report links.

## 8. Owner decisions preserved

- DM-04 already requires early Tarot, compatibility and referral to be hidden from the primary user path until their release; current visible menu/profile entries are an implementation gap. Exact flag/beta/rollout mechanics and possible removal remain undecided.
- `OWNER DECISION PENDING — compatibility support duration`.
- `OWNER DECISION PENDING — migration/disposition of legacy 390 ₽ subscribers and saved payment methods`.

This map does not prescribe the exact gating mechanism, beta/rollout parameters, removal, a sunset date, forced migration, refund, conversion or auto-renew behavior.

## 9. Failure and recovery summary

| Boundary | Current recovery | Remaining target/release risk |
|---|---|---|
| Invalid onboarding input | Validation and repeated prompt | Consent version/legal surface incomplete |
| Mini generation/delivery | Durable generation/delivery retry and replay | External Telegram/content acceptance pending |
| Payment browser return/webhook | Return is informational and repeat-safe; verified webhook activation is idempotent with amount/currency/metadata checks and reconciliation | Real YooKassa sandbox/receipt not executed |
| Full generation/delivery | Canonical text + PDF, retry/manual resend, refund fence | External Telegram/content acceptance pending |
| Chat concurrency/failure | Reservation, release, replay | Daily/delivery-aware semantics missing |
| Saved material reopen | Ownership/status check and resend | Taxonomy/metadata incomplete |
| Broadcast failure | Persisted typed delivery outcome, bounded retry/progress, suppression and campaign stats | External Telegram/provider behavior not executed |

## 10. References

- [Canonical target NURA 1.0/1.5](product/NURA_1_0_1_5_PRODUCT_SPEC.md)
- [Bot technical specification](bot-spec.md)
- [Current implementation mirror](implementation/current-status.md)
- [Owner migration decisions](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md)
- [Acceptance index](acceptance/README.md)
- [Local Telegram-first sandbox runbook](acceptance/telegram-first-sandbox.md)
- [Dated current-versus-target evidence](reconciliation/2026-07-28/CURRENT_IMPLEMENTATION_VS_TARGET.md)
- [Documentation conflict matrix](reconciliation/2026-07-28/DOCUMENTATION_CONFLICT_MATRIX.md)
- Pending pricing/payment write-group: [pricing](pricing.md) and [payment flow audit](audits/PAYMENT_FLOW_AUDIT.md)
- Pending reports write-group: [report spec](report-spec.md) and [two-layer architecture](two-layer-architecture.md)
