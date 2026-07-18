# NURA Payment Flow: contract and security audit

Дата аудита: 2026-07-16. Область: текущий незакоммиченный Closed Beta Hardening diff в `C:\tmp\nura-closed-beta-hardening`.

## Verdict

**C — перед закрытой бетой нужны исправления P1.**

## Remediation status (2026-07-16)

`PAY-P1-001` закрыт в текущем worktree: production `Settings` отклоняет
`YOOKASSA_VERIFY_ON_WEBHOOK=false` до запуска приложения; service дополнительно
требует server-to-server `YooPayment.find_one` при каждом production webhook,
даже при runtime bypass конфигурации. Provider response, а не webhook body,
является источником metadata; provider errors, malformed response, wrong
status/amount/currency/metadata оставляют payment pending и не меняют
subscription. Readiness сообщает неготовую production payment configuration без
credentials/secrets. IP allowlist остался дополнительным слоем и не заменяет lookup.

При временной ошибке provider lookup webhook route отвечает безопасным `503
payment_verification_unavailable`, поэтому YooKassa может повторить доставку; наружу не
возвращаются детали provider exception. Существующее расхождение promo-цены остаётся
`PAY-P2-003`: checkout может запросить полную сумму, тогда как локальная запись содержит
скидку. Новая обязательная сверка суммы намеренно не выдаст entitlement в таком случае;
исправление канонического pricing вынесено за scope этой P1-remediation.

Подтверждено `tests/test_payment_webhook_verification.py` без реального YooKassa API.
`PAY-P1-002` закрыт: Telegram callbacks `buy_subscription` и
`buy_tarot_subscription` используют общий `PaymentService.create_telegram_payment`.
Он создаёт provider payment с server-side суммой и `RUB`, затем сохраняет локальную
`Payment` (provider id, внутренний user id, type, amount, pending) и только после
commit возвращает confirmation URL. Повторная доставка того же callback сохраняет
одну локальную запись; orphan webhook по-прежнему fail-closed. Verified webhook
разрешает обе Telegram-категории и активирует entitlement идемпотентно.

При provider create или DB failure URL пользователю не возвращается; repository
выполняет rollback. Никакие реальные YooKassa/Telegram API или production credentials
не использовались. Подтверждено
`tests/test_payment_creation_persistence.py` без skip/xfail.

Исторический verdict `C` выше сохранён как результат исходного аудита. Текущий
remediation verdict: **B** — оба P1 закрыты; `PAY-P2-003` promo amount mismatch
остаётся открытым и намеренно не исправлялся.

`YooKassa` — фактический провайдер: SDK вызывается из `core/services/payment.py`.
Web checkout технически подключён, а серверная повторная проверка платежа включена по умолчанию. Но production-contract допускает `YOOKASSA_VERIFY_ON_WEBHOOK=false`, при пустом (допустимом) `YOOKASSA_IP_WHITELIST`; тогда поддельный `payment.succeeded` для собственной pending web-записи будет принят и выдаст доступ без оплаты. Это P1, так как production не принудительно fail-closed. Фактические значения production `.env` намеренно не читались, поэтому нельзя подтвердить, что этот путь уже закрыт деплоем.

Отдельный P1/contract-blocker: Telegram callbacks `buy_subscription` и `buy_tarot_subscription` создают YooKassa payment, но не создают локальный `Payment`. Их последующий webhook отвечает `404 Payment not found`; оплаченная Telegram-подписка не активируется. Matrix callback локальную запись создаёт и отличается от двух подписочных flows.

`PAY-P2-003` закрыт: `PaymentService.resolve_web_checkout_amount` вычисляет
неизменяемую сумму web Matrix и Tarot в целых копейках. То же
`final_amount_kopecks` сериализуется для YooKassa ровно с двумя десятичными
знаками, сохраняется в local `Payment` и строго сверяется verified webhook.
Ограниченное использование promo атомарно резервируется до создания provider
intent, высвобождается при provider/DB failure, а в один `used_count` переводится
только после verified successful webhook; duplicate webhook не расходует promo
повторно. Admin API читает
`amount_kopecks` с fallback для legacy rows, поэтому агрегации и выдача сохраняют
две десятичные позиции. Полная, меньшая и неверная по валюте provider-суммы
остаются fail-closed. Регрессия с fake provider пройдена: `13 passed` promo
contract tests, `72 passed` combined payment tests и `4 passed` targeted bot
payment/cancel tests. Текущий remediation verdict остаётся **B**, так как
`PAY-P2-005` и `PAY-P2-006` остаются открытыми.

### Promo reservation foundation (2026-07-17)

Для `PromoReservation.provider_payment_id` подтверждён реальный DB-конфликт
уникальности: repository делает rollback и возвращает безопасный
`reservation_attachment_conflict`, после чего тот же `AsyncSession` выполняет
чтение и успешно прикрепляет другой свободный provider id. Состояния
резерваций и счётчики promo при конфликте не изменяются; локальные `Payment` и
entitlement не затрагиваются. Проверка не использует реальный YooKassa.

Для `PromoReservation.payment_id` подтверждён аналогичный реальный DB-конфликт
уникальности: ownership и тип payment валидируются до записи, а конфликт двух
совместимых reservations делает rollback, возвращает
`reservation_attachment_conflict` и оставляет тот же `AsyncSession` пригодным
для чтения и последующего прикрепления другой свободной local `Payment`.
Локальная `Payment`, её owner, status и provider id, состояния reservations,
promo-счётчики и entitlement при конфликте не изменяются.

Конкурентная ёмкость `PromoReservation` также подтверждена на file-backed
SQLite с WAL, `NullPool` и независимыми physical connections. Условный
атомарный `UPDATE` резервирует slot только при доступной ёмкости; затем
reservation создаётся в той же транзакции. В десяти синхронизированных гонках
с capacity=1 получены ровно один success и один `promo_capacity_exhausted`,
одна active reservation и `reserved_count=1`; проигравшая session остаётся
пригодной для чтения. SQLite lock не преобразуется в business result без
повторного DB-claim.

Durable promo reservation foundation доказана. Интеграция с checkout,
reconciliation и production-поток YooKassa по-прежнему не выполнены; риск P2
остаётся открытым до этих блоков. Исторические findings выше не
переопределяются.

### Durable web promo checkout (2026-07-17)

Web Matrix и Tarot checkout теперь требуют один канонический UUID v4 в
`Idempotency-Key`. Сервер выводит из него scoped digest и независимый provider
idempotency key, не сохраняя и не логируя raw header. Promo checkout использует
`PromoReservation` в production ordering: reservation и Matrix `report_token`
фиксируются до provider call; provider id и ровно один local `Payment`
прикрепляются durable до возврата confirmation URL. Retry повторно использует
ту же reservation, report token и provider key; конкурентная foundation
ёмкости применяется этим production flow.

Verified web webhook после строгой provider-проверки идемпотентно переводит
связанную reservation в `consumed`; повторная доставка не создаёт второй
entitlement или второй расход promo. Reconciliation намеренно не реализована:
открытым остаётся только promo P2 до отдельного reconciliation block.

Coverage status: executable integration tests подтверждают WEB-IDEM-01–32,
включая отсутствие side effects при invalid header, независимое DB-чтение
reservation/report token до provider call, согласованность RUB amount,
same-action conflict/isolation, durable provider/local attachments, отсутствие URL
до их фиксации и recovery после provider/local attachment failure. Требования
WEB-IDEM-33 и далее ещё не закрыты; browser visual QA в этом блоке не выполнялся.
Reconciliation отсутствует, P2 остаётся открытым.

### Report lifecycle and transactional outbox schema foundation (2026-07-17)

Выбрана transactional outbox architecture. Добавлены schema foundation для
durable lifecycle `Report` и отдельной таблицы `ReportGenerationJob`; legacy
`Report` безопасно backfill-ятся как `legacy_unlinked` / `completed` без
попытки угадать связь с `Payment`. Backfill не создаёт job и сохраняет
существующие content, token и user ownership.

Репозитории и state transitions ещё не реализованы. Webhook integration с
новой lifecycle/outbox foundation, dispatcher и Celery worker также не
реализованы; текущий production flow generation намеренно не менялся. Matrix
lifecycle P1, WEB-IDEM-33 и reconciliation остаются открытыми.

### Report lifecycle repository foundation (2026-07-17)

Repository и lifecycle-service foundation для `Report` и
`ReportGenerationJob` готовы. Методы работают с caller-owned `AsyncSession`,
не делают собственных commit/rollback и потому composable в будущей единой
webhook transaction. Payment confirmation, перевод `Report` в
`pending_dispatch` и unique full-report job insert выполняются атомарно после
одного flush; повтор того же trusted Payment возвращает существующий job без
изменения timestamp или attempts.

Conditional и идемпотентные transitions покрывают payment confirmation,
generation и job lifecycle. Защиты unpaid, legacy, completed и terminal
состояний, safe error categories, rollback и reuse того же `AsyncSession`
подтверждены executable SQLite tests. Dispatcher concurrency, webhook
integration и Celery worker integration не реализованы; Matrix lifecycle P1,
WEB-IDEM-33 и reconciliation остаются открытыми.

### Report generation job concurrent claim foundation (2026-07-17)

Добавлена database-level concurrent claim foundation для `ReportGenerationJob`.
Условный atomic UPDATE даёт право dispatch только одной transaction; на десяти
file-backed SQLite/WAL race cycles две независимые physical connections дали
ровно один claim и один safe conflict без double claim. Stale pre-publish
`dispatching` claim можно явно вернуть в `failed_retryable` без увеличения
attempts; published и terminal jobs не восстанавливаются.

Actual dispatcher publish loop, Celery publish, webhook и worker integration
по-прежнему не реализованы. Matrix lifecycle P1, WEB-IDEM-33 и reconciliation
остаются открытыми.

### Report generation dispatcher orchestration foundation (2026-07-17)

Добавлен короткотранзакционный dispatcher с injected `ReportGenerationPublisher`
protocol: он выбирает dispatchable jobs, атомарно claim-ит каждый job и завершает
claim transaction до вызова publisher. Publisher получает только `job_id`,
`report_id` и детерминированный opaque `nura-report-v1-<sha256>` task id; runtime
Celery adapter, Celery Beat и production wiring не добавлялись.

После accepted publish Report и job переводятся в queued в одной короткой
transaction. Retryable publisher/timeout failure сохраняет bounded exponential
backoff без sleep, terminal failure переводит согласованную пару Report/job в
terminal state. Crash после claim или ошибка DB после accepted publish оставляют
job recoverable существующим stale-claim mechanism; batch продолжает обработку
остальных jobs. Тесты также проверяют отсутствие DB transaction во время вызова
publisher и отсутствие raw UUID в task id/логах.

Webhook integration, реальный publish в Celery, worker execution, scheduling,
reconciliation и Matrix lifecycle P1 по-прежнему не реализованы. WEB-IDEM-33
остаётся открытым.

### Durable Matrix web checkout and activation remediation (2026-07-17)

Matrix web checkout теперь создаёт durable placeholder `Report` и durable
checkout reservation в одной caller-owned DB transaction до вызова YooKassa.
Повтор того же idempotency action возвращает тот же placeholder, а новый action
создаёт новый token/report. Reservation используется как локальная доверенная
цепочка mapping provider payment → local Payment → report token → full Report;
она допускает checkout без promo, поскольку иначе schema не могла бы дать
требуемую durable mapping chain.

После strict provider lookup Matrix webhook запускает единственную короткую DB
transaction: pending Payment → succeeded, Report payment confirmation и unique
`pending_dispatch` job, `User.has_matrix`, reservation consumption и promo
accounting. Любой mapping conflict fail-closed, duplicate не меняет snapshot.
Прямой Matrix webhook publish в Celery удалён: `generation_enqueued_at`,
`celery_task_id` и `published_at` остаются пустыми до отдельного dispatcher
wiring. Controlled checkpoint tests подтверждают полный rollback после payment
claim, report/job, entitlement и promo-consume boundary.

Matrix Report payment activation P1 и WEB-IDEM-33 закрыты на уровне durable
payment activation. Production dispatcher/Celery wiring, worker lifecycle,
reconciliation и Matrix generation completion остаются открытыми.

## Фактический production contract

| Продукт / вход | Backend | Сумма, валюта, срок | Redirect / результат |
| --- | --- | --- | --- |
| Web Matrix | `POST /api/v1/web/create-payment`, cookie-auth | 890 RUB, one-time; `has_matrix=True` | `/report/{report_token}`; webhook запускает отчёт |
| Web Tarot | `POST /api/v1/web/subscribe`, cookie-auth | 390 RUB, 30 дней | `/app/success` → `tarot.html`; entitlement только после webhook |
| Telegram Matrix | callback `buy_matrix` | 890 RUB, one-time | `/success`; запись `Payment` сохранена |
| Telegram Premium | callback `buy_subscription` | 390 RUB, 30 дней | `/success`; **запись Payment не сохранена** |
| Telegram Tarot | callback `buy_tarot_subscription` | 390 RUB, 30 дней | `/success`; **запись Payment не сохранена** |

Цены в коде совпадают с лендингом: `matrix_one_time_price_rub=890`, `tarot_subscription_price_rub=390` (`core/config.py:69-70`, `index.html:540,579`). Но документация расходится с кодом: `docs/platform-strategy.md:284` называет `/web/subscribe` Premium, тогда как route вызывает `create_web_tarot_payment`; текущий UI Profile и Tarot использует этот endpoint для Таро.

Обязательные настройки: `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`; для безопасной production-конфигурации также необходимы `YOOKASSA_VERIFY_ON_WEBHOOK=true` и актуальный `YOOKASSA_IP_WHITELIST`. Без credentials SDK-вызов создания платежа падает, route/handler возвращает generic «платёжный сервис недоступен». В `test_mode` web route `/test-subscribe` и bot callbacks дают entitlement без оплаты, но `test_mode` принудительно выключается при `APP_ENV=production` (`core/config.py:100-106`).

## Подтверждённый flow

1. Web Matrix начинается на landing → `mini.html`/PWA Profile; фактический checkout вызывается только аутентифицированным `POST /api/v1/web/create-payment`. UI Таро вызывает аутентифицированный `POST /api/v1/web/subscribe` из `frontend/pwa/app/profile.html:135` и `tarot.html:437-442`.
2. Клиент передаёт лишь необязательные `email` и `promo_code` (Matrix), либо `promo_code` (Tarot). `user_id`, product type, base amount, currency, report token и provider id генерируются сервером.
3. `PaymentService` создаёт redirect payment с UUID-based YooKassa idempotence key. Amount/currency жёстко заданы в service: 890/`RUB` Matrix, 390/`RUB` Tarot. Metadata: web matrix — `user_id`, `payment_type=web_matrix`, `report_token`; web Tarot — `user_id`, `payment_type=web_tarot`.
4. Route сохраняет локальную pending `Payment(user_id, amount, yookassa_id, payment_type)` и возвращает только `payment_url`. Browser redirect не активирует доступ: `app/success.html` лишь сообщает об ожидании и Tarot заново читает `/web/me`; query `subscribed=1` не используется как entitlement.
5. YooKassa вызывает `POST /api/v1/payment/webhook`. Route принимает JSON, применяет rate limit 10/min и optional CIDR allowlist; service принимает только `event == payment.succeeded`.
6. При включённом `yookassa_verify_on_webhook` service делает `YooPayment.find_one(id)` в отдельном thread, требует remote `status=succeeded`, `paid=True` и совпадающий id, затем подменяет metadata на remote metadata.
7. Для web flows service находит локальный payment по provider id, сопоставляет `Payment.user_id` и metadata user id, атомарно переводит pending → succeeded через `SELECT ... FOR UPDATE`, затем выдаёт Matrix/Tarot. Duplicate webhook возвращает idempotent success; конкурентный webhook проигрывает claim.
8. Срок подписки вычисляется как `now(UTC) + 30 days`; это не продление от текущего `expires_at`. Matrix генерирует отчёт best-effort после entitlement.

## Entry points, UI, HTTP and privacy

Production routes: `/api/v1/web/create-payment`, `/api/v1/web/subscribe`, `/api/v1/payment/webhook`; test-only `/api/v1/web/test-subscribe`. Payment router включён в `api/main.py:48`.

Frontend callers: `frontend/pwa/app/profile.html`, `frontend/pwa/app/tarot.html`. Landing `index.html` ведёт в PWA/mini и не создаёт payment напрямую. Bot callers: `bot/handlers/payment.py::{initiate_subscription,initiate_tarot_subscription,buy_matrix}`; CTA также находятся в `bot/handlers/{onboarding,compatibility,start,tarot}.py` и keyboard modules.

`POST` используется для всех state-changing checkout/webhook routes. CORS ограничен `https://nura-ai.ru` и `https://www.nura-ai.ru`; cookie имеет `HttpOnly`, `Secure` и `SameSite=Lax`. Явной CSRF-проверки нет, но cross-site POST не должен нести Lax-cookie; этот риск не является текущим blocker. Nginx проксирует `/api/` с X-Forwarded-For, но не выдаёт `Cache-Control: no-store` для PII API responses. Service worker исключает `/api/`, `/report/`, webhook и subscription-like private paths из cache; static `app/success.html` можно кэшировать, но он не содержит entitlement.

Логи не пишут provider secret, authorization headers или raw webhook body. Однако payment service логирует provider payment id, UUID/Telegram id и при failed lookup пишет exception traceback; это P3 privacy/observability debt, не подтверждённая утечка secret. Readiness endpoint сообщает только категорию payment configuration, не credential.

## Security assessment

| Контроль | Итог | Основание |
| --- | --- | --- |
| Client amount/currency/user id | PASS for normal creation | Web schemas не принимают эти поля; service вычисляет product values |
| Unknown plan / zero or negative amount | PASS | Нет plan/amount input; цены статические positive settings |
| Auth/rate limit checkout | PASS | `get_current_web_user`, 5/min на обоих web routes |
| Checkout duplicate/idempotency | GAP | Каждый retry создаёт новый YooKassa key/payment; pending-order lock отсутствует |
| Webhook provider verification | CONDITIONAL PASS | Provider lookup fail-closed, но выключаемый env flag без production guard |
| Webhook source IP | CONDITIONAL | CIDR optional; XFF берётся как первый, не как доверенно нормализованный proxy header |
| Payment id / account mapping | PARTIAL PASS | Local payment id and `user_id` сверяются web-flow; Telegram subscription record отсутствует |
| Amount/currency/type verification | FAIL | Remote amount/currency не сверяются с local expected values; `payment_type` читается из raw body до remote metadata |
| Replay/duplicate/concurrency | PARTIAL PASS | `claim_succeeded` защищает duplicate/concurrent success; нет atomic transaction с entitlement |
| Success redirect | PASS for entitlement | App success cannot grant premium; `/web/me` is source of truth |
| Refund/cancel/chargeback | FAIL | `payment.canceled` игнорируется; refund/chargeback handlers нет; bot cancel only changes local status |
| Recurring | FAIL / dormant | Beat task exists every 6h, но `payment_method_id` нигде не сохраняется; task также продлевает до confirmed provider success |
| Logout/deletion | PARTIAL | Logout не меняет payment; account deletion deletes payment/user but не отменяет saved provider method/recurring agreement |

### Findings

#### PAY-P1-001 — production can accept forged webhook

- **Location:** `core/config.py:75`, `api/routes/payment.py:37-51`, `core/services/payment.py:247-278`.
- **Current behaviour:** verification and source allowlist are optional settings. With verification false and empty allowlist, raw body controls event/id/metadata; a user who has initiated own web checkout knows a pending `yookassa_id`.
- **Impact:** free Tarot/Matrix/Premium-equivalent entitlement via accepted forged success webhook; P1 by audit policy.
- **Minimal fix:** force provider lookup in production (fail startup or reject webhook if absent); require validated provider CIDRs behind a trusted proxy; do not trust client-supplied XFF.
- **Regression:** production settings cannot disable verification/allowlist; forged payload with a local pending id never grants access.

#### PAY-P1-002 — Telegram subscription payments cannot activate

- **Location:** `bot/handlers/payment.py:89-91,155-157`; `core/services/payment.py:504-506`.
- **Current behaviour:** only `buy_matrix` calls `save_matrix_payment`; Subscription and Tarot callbacks omit `PaymentRepository.create`. Webhook requires local id and returns `404`.
- **Impact:** paid Telegram subscription flow fails after provider payment; closed-beta production contract is broken.
- **Minimal fix:** create one local pending record, with canonical product and account mapping, before displaying the payment URL; account for provider-create/DB-create compensation.
- **Regression:** each Telegram subscription callback persists exactly one record; simulated succeeded webhook activates intended entitlement; provider failure and DB failure leave recoverable state.

#### PAY-P2-003 — promo price is not sent to YooKassa

- **Location:** `api/routes/web.py:164-183,343-358`; `core/services/payment.py:112-165`.
- **Current behaviour:** promo alters DB `Payment.amount` and increments usage, but service still creates 890/390 provider charge from settings.
- **Impact:** user is charged full price; local audit amount disagrees; promo may be consumed even if provider creation fails.
- **Minimal fix:** pass validated server amount to a single canonical create method and commit promo consumption atomically with durable checkout intent.
- **Regression:** discounted Matrix/Tarot payload amount, local amount and provider amount match; provider failure does not consume promo.

#### PAY-P2-004 — webhook type and amount contract is incomplete

- **Location:** `core/services/payment.py:242-278,392-483,504-640`.
- **Current behaviour:** `payment_type` is read from raw webhook before remote metadata replacement; provider `amount`/`currency` and local `Payment.payment_type` are never checked.
- **Impact:** a payload can select a different processing branch for a verified payment id; product substitution and accounting mismatch are possible, and a provider-side wrong amount would still activate access.
- **Minimal fix:** derive id, metadata, status, paid, amount, currency exclusively from verified remote object; compare canonical expected product, local type and amount/currency before claim.
- **Regression:** forged type, wrong amount, wrong currency, wrong remote metadata and mismatched local type all leave payment pending.

#### PAY-P2-005 — claim and entitlement are not transactional

- **Location:** `core/repositories/payment.py:38-59`; `core/services/payment.py:327-359,439-476,516-640`.
- **Current behaviour:** payment claim commits in one session; user update/revert commits in other sessions. A crash or rollback failure between them may leave `succeeded` without access; later delivery idempotently skips it.
- **Impact:** lost paid entitlement and manual reconciliation.
- **Minimal fix:** one transaction for payment state and entitlement, or durable processing state plus retry/reconciliation worker.
- **Regression:** injected user-update failure/crash is recoverable; retry grants exactly once; concurrent webhook remains single-extension.

#### PAY-P2-006 — renewal, cancellation and recurring contract is inconsistent

- **Location:** `core/services/payment.py:197-231,555-644`; `core/tasks.py:1046-1105`; `bot/handlers/profile.py:192-211`.
- **Current behaviour:** one-time success resets expiry to now+30 rather than extending active time. `payment_method_id` is never persisted, so scheduled recurrence has no candidates. If reachable, task extends entitlement immediately after `create_recurring_payment`, without confirmed status/webhook. Cancel is local `cancelling`, never calls provider cancellation.
- **Impact:** early renewal can shorten access; promised `/month`/one-click cancellation behaviour is not reliable; a pending/failed recurrence could grant time.
- **Minimal fix:** define one product lifecycle; persist method only after verified initial success; activate only on verified recurring success; extend from `max(now, expires_at)`; implement provider cancellation and refund/chargeback state handling.
- **Regression:** active/expired renewal, pending/failed recurring payment, cancellation, refund and chargeback tests.

#### PAY-P3-007 — observability/cache contract needs tightening

- **Location:** `core/services/payment.py:255-262`, `nura_app/nginx/nura-ai.ru.conf` API location.
- **Current behaviour:** traceback plus payment/user identifiers are logged; API PII responses have no explicit no-store header.
- **Impact:** unnecessary sensitive operational data in log/cache layers.
- **Minimal fix:** structured redaction with stable event ids, no traceback for expected provider errors; apply `Cache-Control: no-store` to authenticated/payment API responses.
- **Regression:** caplog proves no raw webhook/credentials/PII; response cache headers are asserted.

## Existing tests and coverage

Executed node IDs: all 35 in `tests/test_payment.py` and `tests/test_tarot_subscription_contract.py`, plus `TestBuySubscription::test_creates_payment_url`, `TestBuyTarotSubscription::test_creates_payment`, `TestBuyMatrix::test_creates_matrix_payment`, and `TestProfile::test_cancel_subscription_do` from `tests/test_tarot_handlers.py`.

`test_payment.py` uses SQLite plus mock `YooPayment.create`/`find_one`; route tests mock `PaymentService`. It covers create payload basics, event filtering, missing id/telegram id, local id lookup, success for Telegram/Matrix/Web Matrix/Web Tarot, duplicate success, web user-id mismatch, endpoint status, IP rejection, provider non-success and provider lookup failure. `test_tarot_subscription_contract.py` asserts UI request shape and mocked `/web/subscribe` response. Bot tests mock provider service and cover URL rendering/cancel UI; they do not assert persisted records for Telegram subscriptions.

Not covered: verification-disabled production mode, verified remote metadata/type replacement, wrong amount/currency, wrong local product, replay after partial DB failure, true parallel webhook, duplicate checkout, promo charge/rollback, Telegram subscription persistence, recurring save/decline/timeout, refund/cancel/chargeback, cache/log redaction, and browser webhook-vs-redirect timing. No relevant test is skipped or xfailed. Nearby `tarot_dialogs_e2e`/harness tests are UI/auth harnesses, not provider checkout tests.

## Minimal test harness architecture (not implemented)

Introduce a test-only `PaymentProvider` protocol injected into `PaymentService`: `create_payment`, `lookup_payment`, and optional `cancel_payment_method`. A deterministic fake should retain provider-side payment objects and expose explicit operations: succeed/fail/timeout, emit webhook, emit duplicate webhook, mutate amount/currency/metadata, and refund/cancel. Keep it outside runtime provider wiring; production adapter remains YooKassa. Tests then call real routes/services against SQLite and fake provider, with no network or production credentials.

## Next atomic tasks

1. Make production webhook verification/source trust fail-closed and add forged/type/amount/currency contract tests.
2. Make checkout intent + provider id + local payment record durable for web and all Telegram products; add duplicate/promo/DB-failure tests.
3. Make webhook claim and entitlement recovery-safe, with idempotency/concurrency/partial-failure tests.
4. Specify and implement recurring/cancel/refund/chargeback lifecycle plus browser redirect-vs-webhook E2E.

## Checks and scope confirmation

- `APP_ENV=test .venv\\Scripts\\pytest.exe -q tests/test_payment.py tests/test_tarot_subscription_contract.py`: **35 passed** (two pytest cache write warnings only).
- Four targeted bot payment/cancel tests: **4 passed** (one pytest cache write warning only).
- `ruff check --no-cache core/services/payment.py api/routes/payment.py core/repositories/payment.py api/routes/web.py core/tasks.py`: **All checks passed**.
- `git diff --check`: **passed** (no whitespace errors in tracked Closed Beta diff); the new audit file was additionally checked for trailing whitespace.

No production code or tests were changed; no real payment, production YooKassa API call or production credential was used. Telegram, Email and VK were not modified. `C:\git\NURA` was not modified. No staging, commit, push, merge, reset, restore or clean was performed. Graphify update is not required: this is an audit document, not an architecture implementation change. `STATE.md` is intentionally unchanged.

### Idempotent Matrix Report Worker (2026-07-17)

Новый idempotent worker `MatrixReportGenerationWorker` создан. Task
`core.tasks.process_report_generation_job` принимает только `job_id` и
`report_id`; задача не получает user_id, birth_date, token, payment id, provider
id или promo code. DB является единственным source of truth.

Worker atomic claim использует conditional `UPDATE` на `reports` table
(`generation_state=queued AND payment_state=payment_confirmed`) и detaches до
вызова generator. Generator (pure computation, `MatrixReportGenerator` Protocol)
вызывается вне DB transaction с минимальными inputs (birth_date, user_name,
report_token). DefaultMatrixReportGenerator переиспользует существующие
helpers (MatrixService, generate_full_report_with_loop, AIService) без
destructive delete/create persistence.

На success worker заполняет существующий placeholder Report in-place
(matrix_data, ai_analysis, kitchen_analysis) и атомарно переводит Report+Job в
completed в одной transaction. При commit failure Report остаётся running.
Duplicate delivery возвращает идемпотентный completed без вызова generator.

Retryable/terminal failures durable сохраняют согласованное состояние пары
Report/Job. Raw exception и sensitive identifiers не сохраняются в error
category, логи и task return value.

Stale-running recovery foundation (`mark_stale_running_generation_retryable`)
добавлена в репозиторий: переводит stale running Report+Job в failed_retryable
без увеличения attempts.

Production-файлы: `core/services/matrix_report_worker.py`,
`core/services/matrix_report_generator.py`,
`core/repositories/report_lifecycle.py` (расширен), `core/tasks.py` (новая
task). Тесты: `tests/test_matrix_report_worker_lifecycle.py` (28 tests, 0
failed, 0 skipped, 0 xfailed).

Production dispatcher wiring, Celery Beat schedule, reconciliation loop,
Telegram/bot/web_tarot legacy flow migration не выполнялись. Старая
`generate_full_report` task не изменена. End-to-end lifecycle остаётся
открытым до wiring/reconciliation.

### Production Celery Publisher and Dispatcher Task (2026-07-17)

Production Celery publisher adapter `CeleryReportGenerationPublisher` реализован
в `core/services/celery_publisher.py`. Имплементирует `ReportGenerationPublisher`
protocol: вызывает `celery_app.send_task("core.tasks.process_report_generation_job", ...)`
с kwargs `job_id`/`report_id` и переданным `task_id`. Publisher не открывает
DB транзакцию, не логирует broker URL/credentials/identifiers.

Retryable classification: `KombuOperationalError`, `ConnectionError`, `TimeoutError`,
`OSError` → `DISPATCH_FAILED`. Terminal: только `EncodeError`, `SerializationError`,
`TypeError`, `NotRegistered` (preflight). Неизвестные exceptions fail-safe
как retryable — оплаченный generation не становится failed_terminal из-за
неизвестной/временной ошибки. Publisher preflight проверяет registry до
send_task — missing task возвращает terminal без вызова broker.

Ручная dispatcher task `core.tasks.dispatch_report_generation_jobs(limit=20)`
добавлена в `core/tasks.py`. Лениво собирает `build_dispatcher()` и вызывает
`dispatch_batch(now=UTC, limit=limit)`. Валидирует `0 < limit <= 100`.
Результат — только агрегаты (selected/claimed/published/retryable_failed/
terminal_failed/claim_conflicts), без identifiers.

Dispatcher→worker production wiring завершена. Celery Beat schedule не
добавлен; автоматический startup loop не добавлен; reconciliation не
реализован. Тесты: `tests/test_report_generation_celery_wiring.py` (21 tests,
0 failed, 0 skipped, 0 xfailed). Комбинированный regression: 62 passed
(dispatcher + worker + wiring + webhook lifecycle), 113 passed (payment regression).

### Report Generation Reconciliation (2026-07-17)

Reconciliation service `ReportGenerationReconciler` реализован в
`core/services/report_generation_reconciliation.py`. Batch-алгоритм
восстанавливает: stale dispatching claims (`mark_stale_dispatch_claim_retryable`),
stale queued pairs (новый `mark_stale_queued_generation_retryable`),
stale running pairs (существующий `mark_stale_running_generation_retryable`).
Due failed_retryable pairs продвигаются в `pending_dispatch`; при превышении
retry budget (max_dispatch_attempts=5, max_generation_attempts=3) → terminal.
Missing full_report jobs создаются только для доказуемо оплаченных pending
reports. Completed Report + active Job синхронизируется (Job → completed).

Reconciliation не вызывает Celery publish, generator, AI или external APIs.
Каждая pair обрабатывается одной короткой transaction. Конкурентные
reconciliation процессы защищены conditional UPDATE/rowcount и unique
constraints.

Новые error categories: `worker_delivery_expired`, `worker_lease_expired`,
`retry_budget_exhausted`. Ручная task
`core.tasks.reconcile_report_generation_jobs(limit=50)` зарегистрирована.
Тесты: `tests/test_report_generation_reconciliation.py` (41 tests, 0 failed,
0 skipped, 0 xfailed). Комбинированный: 102 passed.

Beat schedule отсутствует; PostgreSQL locking smoke не выполнен;
Telegram/bot/web_tarot legacy flows не менялись.

### Alembic bootstrap remediation (2026-07-18) — Block A

Строгая историческая baseline migration добавлена: `0001a2b3c4d5e6`.
Создаёт `users` (12 колонок), `reports` (7 колонок), `payments` (6 колонок)
в точном pre-Alembic состоянии. `e47590a5c5c1` указывает на baseline как
parent (`down_revision = "0001a2b3c4d5e6"`).

Результаты:
- blank PostgreSQL DB → `alembic upgrade head` работает без `create_all`,
  без `stamp`, без `IF NOT EXISTS` — 19 revisions, single head
  `b9c0d1e2f3a4`; 10 сценариев smoke harness прошли;
- существующая `create_all + stamp head` DB не ломается: baseline не
  перезапускается, `alembic_version` остаётся с одной строкой
  `b9c0d1e2f3a4`, `upgrade head` no-op;
- промежуточные revision upgrade работают (e475, f7a8b9c0d1e2, a8b9c0d1e2f3);
- baseline downgrade/re-upgrade корректен;
- legacy backfill подтверждён (legacy_unlinked, completed, generated_at);
- partial schema fail-closed (DuplicateTable, без IF NOT EXISTS маскировки);
- static contract tests: 15/15 passed;
- lifecycle/payment regression: 162 + 100 = 262 passed.

Block B остаётся отдельным. Production inventory и deploy ещё не выполнялись.

### FK constraint name normalization (2026-07-18) — Block B1

Добавлена forward migration `c0d1e2f3a4b5` (head после `b9c0d1e2f3a4`).
Безопасно нормализует имена двух внешних ключей, используя только
`RENAME CONSTRAINT` после семантической идентификации через `pg_constraint`:

- `reports_payment_id_fkey` → `fk_reports_payment_id_payments`
- `payments_promo_code_id_fkey` → `fk_payments_promo_code_id_promo_codes`

Properly migrated DB: no-op (target имена уже существуют). Legacy
create_all DB: переименование без DROP/ADD. Unknown/missing/duplicate
constraints: fail-closed. Downgrade: forward-only no-op (имена
сохраняются). Вся миграция атомарна в одной транзакции.

Static contract tests: 24/24 + 39 total. PostgreSQL smoke: 10 сценариев
подтверждены вручную + blank→head 20 migration chain. Regression:
91 + 188 = 279 passed.

Block B2 (legacy unversioned DB adoption, production inventory,
operational runbook) остаётся отдельным.

### Celery Beat Schedule (2026-07-17)

Beat schedule добавлен для dispatcher и reconciliation:
- `dispatch-report-generation-jobs`: interval=60s, limit=20, expires=55s
- `reconcile-report-generation-jobs`: interval=300s, limit=50, expires=270s

Конфигурация через settings: `report_generation_dispatch_interval_seconds`,
`report_generation_dispatch_limit`, `report_generation_reconciliation_interval_seconds`,
`report_generation_reconciliation_limit`. Overlap безопасен благодаря DB conditional
transitions и bounded expiration. Worker task не является periodic.

Production automatic Matrix generation lifecycle полностью wired.
Тесты: `tests/test_report_generation_beat_schedule.py` (28 tests, 0 failed,
0 skipped, 0 xfailed). 14 beat entries total (12 pre-existing + 2 new).
PostgreSQL concurrency smoke, финальная regression/Graphify/commit preparation
остаются открытыми.
