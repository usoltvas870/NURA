# NURA Payment Flow Audit

**Статус документа:** EVIDENCE-ORIENTED AUDIT RECORD
**Проверено:** 2026-07-28
**Code baseline:** `main` / `7cc1122773656cb73847de70adee628a7f843e4e`

## 1. Authority, scope and baseline

Этот документ фиксирует проверяемые payment, entitlement, refund и delivery invariants. Он не является product specification и не заменяет:

- [канонический target NURA 1.0/1.5](../product/NURA_1_0_1_5_PRODUCT_SPEC.md);
- [компактное зеркало current implementation](../implementation/current-status.md);
- [решения владельца по документационной миграции](../decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md).

Current-утверждения ниже проверены по reachable code, моделям, миграциям и тестам указанного baseline. Dated reconciliation и прежний аудит используются как историческое evidence, но не как live contract. Локальные fake-provider/SQLite/PostgreSQL проверки не доказывают YooKassa sandbox, внешний Telegram или production.

Scope current-аудита — dedicated one-time Full Matrix order за 890 ₽ и связанные generation/delivery/refund boundaries. Достижимая подписочная механика 390 ₽ описана отдельно как legacy compatibility. Gift access и 399 ₽ относятся только к target NURA 1.5.

## 2. Status legend

- `CURRENT — IMPLEMENTED` — поведение подтверждено current code/test evidence; это не production proof.
- `TARGET — NURA 1.0` — обязательный target из canonical spec; не утверждение о реализации.
- `TARGET — NURA 1.5` — target следующей версии; не входит в NURA 1.0.
- `IMPLEMENTATION GAP` — target contract отсутствует или реализован не полностью.
- `LEGACY COMPATIBILITY` — достижимый путь прежней monetization model, не current roadmap.
- `HISTORICAL / REMEDIATED` — дефект существовал на зафиксированном baseline и закрыт последующим evidence.
- `OWNER DECISION PENDING` — authority sources не содержат решения; этот документ его не принимает.
- `OUT OF SCOPE` — тема не входит в границы этой audit-сессии.

## 3. Current verified payment flow

`CURRENT — IMPLEMENTED` локально для one-time Full Matrix:

```text
Telegram CTA
→ server-side Order (89000 kopecks, RUB, full_matrix)
→ opaque checkout capability
→ receipt email validation
→ YooKassa redirect payment (save_payment_method=false)
→ informational browser return
→ claimed PaymentEvent
→ server-to-server YooKassa payment/refund lookup
→ amount/currency/product/order verification
→ trusted Order/PaymentAttempt transition
→ report entitlement and durable generation job
→ generation, persistence and Telegram PDF delivery
```

| Stage | Trust boundary | Durable effect | Entitlement effect | Primary evidence |
|---|---|---|---|---|
| `create_or_get_order` | Server-owned user/product/price | Создаёт или возвращает один active `Order`; `amount_kopecks=89000`, `currency=RUB`, `product_code=full_matrix` | Нет | `core/services/full_matrix_checkout.py`, `core/models.py` |
| Checkout start | Opaque token + validated fiscal email; client не задаёт product/price | Создаёт/reuses pending `PaymentAttempt`; YooKassa payload содержит receipt и provider idempotency key | Нет | `FullMatrixCheckoutService.start_checkout`, `tests/test_full_matrix_checkout.py` |
| YooKassa redirect | External provider UI | Локальный attempt уже сохранён до redirect | Нет | checkout service/tests |
| Browser return | **Untrusted / informational** | Не меняет `Order`, attempt, event, report или job | Нет: return не доказывает оплату, не активирует order и не запускает generation/delivery | `api/routes/payment.py::full_matrix_return`, PostgreSQL golden path |
| Webhook intake | Untrusted notification identity | Deduplicated `PaymentEvent` получает processing claim | Нет до provider verification | `FullMatrixCheckoutService._intake_event`, `PaymentEventRepository` |
| Provider lookup | Trusted server-to-server result | Проверяются provider id, `890.00 RUB`, product/order metadata; refund дополнительно сверяется по refund id/payment id/status/amount | Нет при mismatch или временной ошибке | checkout service, webhook/refund tests |
| Successful activation | Trusted transaction | В одной transaction: attempt → `succeeded`, order → `paid`, event → processed, report payment confirmed, unique generation job, `has_matrix=True` | Появляется order-backed entitlement | `_complete_claimed_event`, full-matrix tests |
| Generation | Active paid order + report/job lifecycle | Worker claims job, генерирует вне DB transaction и перед persist повторно проверяет `Order.status=paid` | Незавершённый refunded order не может сохранить result | `matrix_report_worker.py`, lifecycle tests |
| Delivery | Completed canonical PDF + active user + `has_matrix` + paid order | Durable delivery claim/completion, reusable Telegram `file_id`, retry/reconciliation | Refund до claim блокирует send; paid-order lock линеаризует send с refund | full-report delivery service/repository/tests |

Повтор одного и того же payment/refund event возвращает idempotent terminal result без второго provider lookup после уже обработанного event. Повтор checkout того же pending order/fiscal email возвращает тот же confirmation URL и provider idempotency key. Provider lookup failure оставляет event retryable и заставляет HTTP boundary запросить повторную доставку webhook через `503`.

## 4. Current verified entitlement invariants

| Invariant | Evidence | Status | Limitation |
|---|---|---|---|
| Order-backed full-report claim требует связанный `Order.status=paid` | `_report_has_active_paid_entitlement`, worker load/persist checks, delivery `_subject`, report queries | `CURRENT — IMPLEMENTED` | Completed legacy full report без `order_id` остаётся отдельной compatibility-веткой |
| `created`, `pending`, `failed`, `canceled` и `refunded` order не дают order-backed claim/delivery | lifecycle repository, worker, delivery and My Reports queries | `CURRENT — IMPLEMENTED` | Не определяет product/legal refund policy для уже просмотренного контента |
| Verified success создаёт report/job и устанавливает `has_matrix=True` | checkout activation transaction and tests | `CURRENT — IMPLEMENTED` | `has_matrix` — marker покупки, не самостоятельное доказательство active paid order |
| Один `has_matrix=True` без active paid order недостаточен для order-backed full report | delivery проверяет одновременно user marker и `Order.status=paid`; My Reports join-ит paid order | `CURRENT — IMPLEMENTED` | Legacy unlinked full reports проверяются по отдельной compatibility-ветке |
| `has_matrix` не даёт chat entitlement и не снимает current quota | `ChatQuotaService.is_subscriber`, actual Telegram chat wiring, lifetime chat tests | `CURRENT — IMPLEMENTED` | Current free ledger — 5 lifetime answers; target NURA 1.0 требует 5 delivered answers/day |
| Active legacy Tarot/premium state с неистёкшим сроком bypass-ит current chat quota | `ChatQuotaService.is_subscriber` и chat handlers | `LEGACY COMPATIBILITY` | Не является NURA 1.0 entitlement и не равен gift/399 target |
| Completed paid full report виден в «Мои разборы» и допускает manual resend | `ReportRepository`, `MyReportsService`, delivery tests | `CURRENT — IMPLEMENTED` | Current full delivery — PDF; обязательный полный текст Telegram отсутствует |
| Refund скрывает order-backed full report из My Reports и запрещает новый resend | order status filter, refund golden path | `CURRENT — IMPLEMENTED` | Completed artifact не удаляется самим refund handler; он становится недоступным через current order-backed path |
| Account deletion удаляет User, reports, jobs, deliveries и legacy `Payment`, но сохраняет anonymized `Order`/`PaymentAttempt`/`PaymentEvent` | account deletion service/tests | `CURRENT — IMPLEMENTED` | Эти financial rows получают `retain_until = now + 365 × 5 days`; `PaymentAttempt.fiscal_email` сохраняется. Это current technical metadata, а не доказательство cleanup или утверждённой legal policy: automated enforcement по дате не подтверждён, а formal term/basis, дальнейшая anonymization и fiscal-email handling требуют решения |

## 5. Refund and concurrency invariants

| Scenario / invariant | Provider/order/report effect | Evidence | Status / limitation |
|---|---|---|---|
| Refund до payment-success event | Verified refund переводит attempt/order в `refunded`; поздний success становится idempotent и report/job не создаются | `test_refund_before_payment_webhook_permanently_blocks_activation` | `CURRENT — IMPLEMENTED` locally |
| Refund до generation claim | Unfinished report/job terminalized как `entitlement_revoked`; generator не вызывается | lifecycle repository and worker tests | `CURRENT — IMPLEMENTED` |
| Refund во время generation | Worker перед persist заново lock-ит order; при status ≠ `paid` очищает незавершённый result и не сохраняет artifact/analysis | worker code; SQLite and PostgreSQL refund-race tests | `CURRENT — IMPLEMENTED` |
| Pre-persist entitlement recheck | Проверка активного paid order выполняется после генерации и до записи result | `MatrixReportGenerationWorker._persist_success` | `CURRENT — IMPLEMENTED` |
| No persist / no delivery after revoked unfinished entitlement | Report/job становятся terminal; artifact отсутствует; reconciliation не возвращает retry | refund-race and reconciliation tests | `CURRENT — IMPLEMENTED` |
| Duplicate refund | Один verified refund event; replay → `already_processed`; `provider_status=refunded` сохранён | checkout unit and PostgreSQL golden path | `CURRENT — IMPLEMENTED` |
| Refund before delivery claim | Новый enqueue/resend отсутствует; active queued/retryable delivery отменяется reconciliation | delivery service/repository/tests | `CURRENT — IMPLEMENTED` |
| Delivery/refund race | Delivery держит `Order FOR UPDATE` от entitlement check до Telegram send и durable completion; refund линеаризуется строго до или после delivery | `test_postgres_delivery_and_refund_share_order_linearization_point` | PostgreSQL local proof; external Telegram/YooKassa не участвовали |
| Refund/account deletion race | Оба пути соблюдают lock hierarchy `User → Order`; финансовые rows остаются согласованными и anonymized | `test_postgres_refund_and_account_deletion_complete_without_deadlock` | PostgreSQL local proof; не production proof |

Для уже завершённого и ранее доставленного report current refund handler сохраняет completed artifact row, но `Order.status=refunded`, `has_matrix=False`, My Reports и delivery service блокируют order-backed доступ. Это описывает фактический implementation result, а не утверждённую refund policy для потреблённого цифрового товара.

## 6. Historical findings and remediation status

Исходный аудит 2026-07-16 проводился в другом worktree и зафиксировал реальные defects прежнего payment contour. История сохранена, но closed findings не являются current defects dedicated 890 ₽ flow.

| Historical finding | Original impact | Remediation evidence | Current status |
|---|---|---|---|
| `PAY-P1-001`: production мог принять unverified webhook | Forged success мог активировать legacy entitlement | Production settings требуют verification/credentials; provider lookup является source of truth; dedicated full-matrix flow всегда читает provider state | `HISTORICAL / REMEDIATED` |
| `PAY-P1-002`: Telegram 390 callbacks не сохраняли local `Payment` | Оплаченный legacy subscription webhook не находил payment | `create_telegram_payment` сохраняет pending `Payment` до возврата URL; duplicate callback и orphan webhook покрыты tests | `HISTORICAL / REMEDIATED` для legacy checkout creation |
| `PAY-P2-003`: promo amount расходился с provider/local amount | Пользователь мог быть charged не по локальной audit sum | Legacy promo resolver/reservation сверяет amount; dedicated 890 checkout вообще не принимает client/promo amount и фиксирует `890.00 RUB` | `HISTORICAL / REMEDIATED` для current 890 path |
| `PAY-P2-004`: type/amount/currency/metadata contract был неполным | Product substitution или underpayment activation | Verified provider object и local intent сверяются; dedicated full-matrix metadata/amount/currency проверяются до transition | `HISTORICAL / REMEDIATED` для current 890 path |
| `PAY-P2-005`: payment claim и entitlement были разными transactions | Crash мог оставить paid без access | Dedicated full-matrix activation фиксирует attempt/order/event/report/job/user в одной transaction; reconciliation покрывает generation/delivery | `HISTORICAL / REMEDIATED` для current 890 path; legacy 390 остаётся отдельной моделью |
| `PAY-P2-006`: recurring/cancel lifecycle противоречив | Ненадёжное продление, cancellation и provider-success boundary | Отдельной remediation legacy lifecycle не найдено; target 1.0/1.5 исключает этот recurring contract | `LEGACY COMPATIBILITY` / evidence gap, не current 890 defect |
| `PAY-P3-007`: широкие cache/logging риски | Лишние identifiers/cache exposure | Dedicated checkout/return используют `Cache-Control: no-store`, generic external errors и redacted event data | `HISTORICAL / REMEDIATED` только для проверенного dedicated boundary; broader legacy surface вне этого вывода |

Durable order/event schema, transactional report lifecycle, dispatcher, worker, reconciliation, Beat schedule, PDF delivery and account-deletion retention появились как последовательные remediation blocks 17–18 июля 2026 года. Их current status подтверждается current code/tests, а не прежними промежуточными пометками «foundation only».

## 7. Legacy recurring subscription

`LEGACY RECURRING 390 ₽ SUBSCRIPTION — NOT NURA 1.0 AND NOT TARGET GIFT`

`LEGACY COMPATIBILITY` evidence:

- `settings.tarot_subscription_price_rub=390`;
- Telegram/PWA subscription and Tarot checkout paths runtime-reachable;
- initial provider payload просит `save_payment_method=True` и возвращает `payment_method_id`;
- pending legacy `Payment` сохраняется до показа confirmation URL;
- verified `payment.succeeded` может установить `subscription_status=premium` или `tarot_subscription=True` на 30 дней;
- `User.payment_method_id`, recurring create method и scheduled `charge-recurring-subscriptions` task существуют;
- active legacy premium/Tarot state с неистёкшим сроком bypass-ит current chat quota и участвует в отдельных Tarot/compatibility gates;
- expiry task переводит `premium` в `free`; cancel callback ставит `subscription_status=cancelling`.

Границы evidence:

- assignment, сохраняющий returned provider `payment_method_id` в `User.payment_method_id`, в current wiring не найден; recurring task обрабатывает только уже заполненные значения;
- dedicated tests для фактического recurring charge task не найдены; schedule/async registration проверяются отдельно;
- recurring task после `YooPayment.create` создаёт local `Payment` и продлевает user access без отдельной проверки provider `status=succeeded`;
- cancel callback не вызывает `PaymentService.cancel_subscription` и не очищает saved method; status `cancelling` не считается active subscriber current chat resolver;
- production existence/count existing subscribers и сохранённых provider methods не проверялись;
- migration, forced cancellation, refund, grandfathering или перенос на 399 ₽ не утверждены.

Эта ветка не должна называться current NURA 1.0, target gift или implemented 399 ₽ access.

## 8. Target NURA 1.0 / NURA 1.5 boundary

| Surface | Current implementation | Canonical target | Classification |
|---|---|---|---|
| Full report 890 ₽ | Dedicated YooKassa one-time order, verified activation, durable PDF generation/delivery/refund fence | NURA 1.0: 890 ₽, YooKassa only, one-time, Telegram text + PDF, saved materials, refund/support/retry/observability | Payment/PDF `CURRENT — IMPLEMENTED`; full Telegram text and external sandbox are gaps |
| Browser return | Informational page only | Client return must not be sole payment proof | `CURRENT — IMPLEMENTED` |
| Telegram Stars | Invoice flow для target purchase не найден | Excluded | `OUT OF SCOPE` |
| Manual transfer/activation | Не является dedicated checkout path | Excluded | `OUT OF SCOPE` |
| 390 ₽ recurring | Reachable legacy handlers/service/task | Не является NURA 1.0 и не равен target 1.5 | `LEGACY COMPATIBILITY` |
| Gift access | Entitlement aggregate/gift activation не найден | NURA 1.5: 30 дней после successful full-report purchase, без карты и автосписания | `TARGET — NURA 1.5` / `IMPLEMENTATION GAP` |
| 399 ₽ / 30 days | Price/checkout/entitlement resolver не найден | NURA 1.5: отдельная добровольная YooKassa purchase; новый период можно купить заранее, и он продлевает доступ без потери оплаченных дней; без auto-renew в baseline | `TARGET — NURA 1.5` / `IMPLEMENTATION GAP` |

## 9. Open owner decisions and evidence gaps

| Pending decision / gap | Already known | Missing decision/evidence | Affected users | Blocking scope |
|---|---|---|---|---|
| Legacy 390 subscribers and saved methods | Legacy code is reachable; target excludes it | Honor-to-expiry, forced cancellation, migration credit, refunds, grandfathering, saved-method deletion and support period | Existing/possible legacy subscribers | `OWNER DECISION PENDING`; does not block accurate current docs, blocks migration/retirement |
| Early full-report buyers and 30-day gift | Canonical recommends a possible one-time gift but requires confirmation | Eligibility date, included purchases, activation start and duplicate prevention rule | Buyers before NURA 1.5 | `OWNER DECISION PENDING`; blocks only 1.5 migration implementation |
| Already delivered report after refund | Current code hides order-backed report/resend but retains completed artifact | Product/legal rule for consumed digital content, user copy and support procedure | Refunded buyers with completed delivery | `OWNER DECISION PENDING`; current implementation can be documented without inventing policy |
| Future 399 ₽ lifecycle | Price, 30-day term, YooKassa, voluntary purchase, no baseline auto-renew and no-loss advance extension are canonical | Implementation lacks entitlement ledger/schema, expiration scheduling, atomic/idempotent extension, UI/payment activation, concurrency behavior, tests and migration; only grace, proration, detailed cancellation/refund, reconciliation and support procedures remain product/operational decisions | Future NURA 1.5 users | `IMPLEMENTATION GAP`; `OWNER DECISION PENDING` only for details not fixed by canonical spec |
| Financial retention after account deletion | `Order`, `PaymentAttempt` and `PaymentEvent` receive `retain_until = now + 365 × 5 days` and survive deletion; retained `PaymentAttempt` keeps `fiscal_email` | Automated cleanup/enforcement at `retain_until` is not confirmed. Formal calendar/legal interpretation of five years, policy/legal basis, further anonymization, fiscal-email handling, exceptions and user disclosure remain unresolved | Deleted paying users | Current metadata is `CURRENT — IMPLEMENTED`; enforcement and legal copy remain `OWNER DECISION PENDING` |

Confirmed implementation/evidence gaps:

- full report is delivered as PDF, not the canonical full Telegram text + PDF pair;
- YooKassa test shop, public HTTPS webhook/return, receipt, success/refund and duplicate/out-of-order scenarios were not executed externally;
- production payment/refund/delivery state is unknown without separate authorized acceptance;
- target NURA 1.5 entitlement aggregate, gift activation and 399 ₽ purchase — including no-loss advance extension — do not exist;
- legacy recurring saved-method persistence and verified renewal activation are not demonstrated by current wiring/tests.

## 10. Acceptance boundary

| Evidence layer | What is proven | What is not proven |
|---|---|---|
| Local unit/integration | Checkout price/receipt/idempotency, provider verification, event replay, activation transaction, report claim, refund fence, account deletion and delivery behavior with fakes/SQLite | Real provider, real Telegram, deployed config |
| Local PostgreSQL race coverage | Refund vs worker persist, refund vs delivery linearization, refund vs account deletion lock order | Production load/latency/network behavior |
| Dated cumulative local acceptance | Golden path, fresh-process replay, refund/deletion replay and safe-suite evidence recorded in `docs/acceptance/` | External sandbox and production |
| YooKassa/Telegram external sandbox | **NOT EXECUTED** | Test-shop receipt/webhook/return and real sandbox delivery remain open |
| Production/legal | **NOT EXECUTED / BLOCKED** | No claim about deployed state, real charges, legal/support readiness or production data |

Тесты в этой documentation session не перезапускались: code не менялся, а test files использовались как primary evidence. Зафиксированный local PASS не повышается до sandbox/production PASS.

## 11. References

Authority and current mirrors:

- [Canonical product target](../product/NURA_1_0_1_5_PRODUCT_SPEC.md)
- [Current implementation status](../implementation/current-status.md)
- [Owner migration decisions](../decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md)
- [Acceptance index](../acceptance/README.md)
- [Dated readiness evidence](../acceptance/evidence/telegram-first-v1-readiness-review.md)
- [Current Telegram bot specification](../bot-spec.md)
- [Current Telegram UX map](../bot-ux-map.md)

Primary code and tests:

- `nura_app/core/services/full_matrix_checkout.py`
- `nura_app/api/routes/payment.py`
- `nura_app/core/services/matrix_report_worker.py`
- `nura_app/core/services/full_report_telegram_delivery.py`
- `nura_app/core/services/my_reports.py`
- `nura_app/core/services/account_deletion.py`
- `nura_app/core/services/payment.py` and `nura_app/core/tasks.py` (legacy 390 path)
- `nura_app/core/models.py`
- `nura_app/alembic/versions/e8f9a0b1c2d3_add_full_matrix_orders.py`
- `nura_app/alembic/versions/f9a0b1c2d3e4_add_full_report_telegram_delivery.py`
- `nura_app/tests/test_full_matrix_checkout.py`
- `nura_app/tests/test_payment_webhook_verification.py`
- `nura_app/tests/test_matrix_report_worker_lifecycle.py`
- `nura_app/tests/test_full_report_telegram_delivery.py`
- `nura_app/tests/test_full_matrix_account_deletion.py`
- `nura_app/tests/test_telegram_first_postgres_failure_retry.py`
- `nura_app/tests/test_telegram_first_postgres_golden_path.py`
