# NURA Report System — Technical Specification

> Prompt governance update (2026-07-31): active mini/full/kitchen consumers используют checked-in `report/v1`, а не shared legacy system prompt. Output keys и renderer compatibility сохранены; unsafe legacy key names имеют safe semantic mapping. Новые report outputs сохраняют nullable bounded provenance согласно [runtime prompt governance](prompt-governance.md). Historical rows остаются без v1 attribution.

## 1. Authority and scope

Документ описывает реализованную систему отчётов и отделяет её от утверждённого target и compatibility-поверхностей.

Иерархия источников:

1. Reachable code, модели, миграции, конфигурация, шаблоны и тесты подтверждают текущую реализацию.
2. [NURA 1.0/1.5 Product Specification](product/NURA_1_0_1_5_PRODUCT_SPEC.md) — единственный canonical target source; он не доказывает реализацию.
3. [Current implementation status](implementation/current-status.md) — компактное evidence-backed зеркало, а не самостоятельный контракт.
4. [Documentation migration decisions](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md) определяют документарную authority и классификацию compatibility.

Scope включает mini/full generation, persistence, rendering, Telegram delivery, saved materials, payment/refund fences, удаление и legacy web/PWA compatibility. Цены и bot navigation остаются в [pricing.md](pricing.md), [bot-spec.md](bot-spec.md) и [bot-ux-map.md](bot-ux-map.md).

## 2. Status legend

- `CURRENT — IMPLEMENTED` — reachable-поведение подтверждено primary repository evidence.
- `TARGET — NURA 1.0` — утверждённый target canonical product spec; label не доказывает реализацию.
- `TARGET — NURA 1.5` — более поздняя продуктовая граница, не входящая в acceptance NURA 1.0.
- `IMPLEMENTATION GAP` — target- или contract-свойство не подтверждено текущими evidence.
- `LEGACY COMPATIBILITY` — сохранённая рабочая поверхность, не определяющая Telegram-first target.
- `HISTORICAL / SUPERSEDED` — происхождение или старый план, больше не описывающий нормативную архитектуру.
- `OWNER DECISION PENDING` — нерешённая policy, требующая authority владельца.
- `EVIDENCE BOUNDARY` — граница того, что доказывают repository/local-test evidence.
- `OUT OF SCOPE` — намеренно исключённая тема.

## 3. Terminology and artifact lifecycle

Термины не взаимозаменяемы:

- **Calculated** — deterministic matrix data рассчитаны из валидированного ввода.
- **Generated** — AI narrative получен и провалидирован runtime result schema.
- **Persisted** — structured data, narrative, lifecycle state и применимые artifact bytes/metadata закоммичены в БД.
- **Rendered** — HTML и/или PDF bytes созданы из persisted либо in-flight report data.
- **Delivered** — Telegram принял соответствующую отправку сообщения или документа.
- **Durably completed** — прогресс delivery закоммичен в delivery record после transport success.
- **Available in My Reports** — eligible completed report доступен для listing/resend; это не доказывает initial delivery.

Generated HTML не равен Telegram text. Persisted PDF не равен successful Telegram delivery. Если transport success произошёл до сбоя database commit, retry может создать транспортный duplicate: delivery durable, но не exactly-once на внешней границе.

## 4. Current mini-report contract

### Registered Telegram mini — `CURRENT — IMPLEMENTED`

1. `MiniReportApplicationService` нормализует и валидирует name/date и строит PII-safe HMAC fingerprint с generation version `mini-v1`.
2. `MiniReportGenerationRepository` получает или создаёт одну generation на owner + fingerprint + version и атомарно claim-ит eligible attempt.
3. `MatrixService.calculate()` формирует deterministic `MatrixData`; `AIService.generate_mini_analysis()` — `MiniAnalysisResult`.
4. Application layer считает generic mini fallback ошибкой generation, а не завершённым результатом.
5. Для registered user finalization создаёт/связывает `Report`, сохраняет matrix JSON и mini narrative JSON, затем завершает generation.
6. Initial Telegram delivery сначала отправляет пять именованных text sections и сохраняет каждый message id, затем переиспользует либо рендерит и сохраняет canonical mini PDF и отправляет document.
7. Delivery завершается только после text и PDF. Retry продолжает с сохранённого прогресса; сбой PDF после text не переотправляет успешные text chunks.
8. Manual resend имеет отдельный idempotent purpose и использует сохранённые report/PDF без повторного calculation или AI call.

### Guest web/PWA mini — `LEGACY COMPATIBILITY`

Reachable `/mini-analysis` принимает `GuestMiniReportSubject`. Для guest finalization не создаёт `Report`: matrix и narrative сохраняются в `GuestProfile.report_data`, а durable Telegram text/PDF delivery отсутствует. Поэтому гарантии registered Telegram mini нельзя переносить на guest surface.

Primary modules: `core/services/mini_report_application.py`, `core/services/mini_report_generation.py`, `core/repositories/mini_report_generation.py`, `core/services/telegram_report_delivery.py`, `core/repositories/telegram_report_delivery.py`.

## 5. Current full-report contract

### `CURRENT — IMPLEMENTED`

Canonical full-report path — order-backed Telegram flow:

1. Verified YooKassa activation связывает active `PAID` order с одним full `Report` и durable generation job.
2. Dispatcher и worker атомарно claim-ят lifecycle state. Worker требует full report, confirmed payment, корректную payment/order link и active `PAID` order.
3. Вне claim transaction `MatrixService` рассчитывает deterministic data, а AI layer формирует full narrative и kitchen analysis.
4. `FullReportResult` и `KitchenReportResult` валидируют narrative structures.
5. `full_report_v2.html` рендерит HTML; WeasyPrint конвертирует его в PDF. При ошибке V2 template используется минимальный escaped diagnostic HTML fallback, после чего worker ещё может создать безопасный artifact.
6. Непосредственно перед persistence worker блокирует и повторно проверяет order. Refund/revocation запрещает commit artifact.
7. Matrix JSON, narrative JSON, kitchen JSON, PDF bytes, SHA-256, size, MIME, completion timestamp и completed lifecycle state сохраняются в одной `Report` row.
8. Automatic Telegram delivery требует valid canonical PDF, active user/Telegram identity, `has_matrix` и active `PAID` order. Order блокируется для каждой Telegram boundary call и final completion, поэтому refund и delivery проверяют entitlement перед каждым следующим шагом.
9. Delivery отправляет immutable text snapshot, затем PDF с caption. Completed Telegram `file_id` переиспользуется; invalid reuse переключается на upload canonical artifact bytes.

### Legacy payment-linked full — `LEGACY COMPATIBILITY`

Lifecycle repository также допускает claim full `Report` с `payment_id`, но без `order_id`. Для такого report worker не может проверить/заблокировать `Order`, поэтому active `PAID` order fence и pre-persist refund recheck отсутствуют. Completed orderless full может попасть в My Reports, но current full Telegram delivery требует `order_id` и отклоняет resend/send. Это compatibility exception, а не гарантия canonical order-backed contract.

### Full Telegram delivery — `CURRENT — IMPLEMENTED locally`

Текущий full path отправляет full narrative из persisted `ai_analysis` как immutable Telegram text snapshot, затем PDF. Внешний Telegram sandbox и content acceptance остаются отдельными release gates.

## 6. Generation and persistence lifecycle

| Boundary | Mini | Full |
|---|---|---|
| Idempotency key | Registered/guest owner + normalized-input fingerprint + `mini-v1` | Canonical: одна order-linked report/job; deterministic dispatch task id |
| Claim | Generation state с attempt fencing | Report/job state с atomic claim |
| Work вне transaction | Deterministic calculation + AI generation | Deterministic calculation + full/kitchen AI + rendering |
| Result validation | `MiniAnalysisResult` | `FullReportResult`, `KitchenReportResult`, PDF integrity |
| Persistence | Registered: matrix/narrative в `Report`, PDF при delivery; guest: `GuestProfile.report_data`, без PDF delivery | Canonical: matrix/narrative/kitchen/PDF и metadata в `Report`; legacy orderless допускается без order fence |
| Completion | Generation и delivery — разные durable states | Generation/job и delivery — разные durable states |
| Recovery | Typed retry, stale-claim recovery, attempt fencing | Dispatcher/reconciliation, retryable failure, stale-claim recovery |

Generation completion никогда не означает delivery completion. Reconciliation может пересоздать или requeue eligible work, но не доказывает получение пользователем, если transport success не был durably recorded.

## 7. Rendering and PDF pipeline

### Registered mini — `CURRENT — IMPLEMENTED`

- Jinja2 рендерит `templates/reports/mini_report.html` с shared partials/styles.
- WeasyPrint создаёт PDF bytes.
- Artifact валидируется как PDF и сохраняется с MIME, size и SHA-256 до повторного использования.

Guest web/PWA mini не имеет этого PDF/delivery contract и классифицирован как `LEGACY COMPATIBILITY`.

### Full — `CURRENT — IMPLEMENTED`

- Order-backed worker рендерит `templates/reports/full_report_v2.html` с matrix, narrative и kitchen context.
- WeasyPrint создаёт canonical PDF; worker проверяет PDF signature и non-empty content.
- V2 template уже включает health/psychological partials. Старое описание kitchen/psychological sections как только planned — `HISTORICAL / SUPERSEDED`.

### `EVIDENCE BOUNDARY`

Templates содержат web fonts/web-oriented assets. Наличие файлов и local rendering tests не доказывает доступность каждого external asset в sandbox/production. Runtime-reachable image-prompt generation step в mini/full pipeline не найден.

## 8. Telegram delivery and durable completion

### Mini — `CURRENT — IMPLEMENTED`

- Surface: text chunks, затем PDF document.
- States: pending, delivering, partially delivered, delivered, failed.
- Completion: commit только после успеха обеих surfaces.
- Retry: продолжает по сохранённым message ids; retryable failures и stale claims восстанавливаются, terminal eligibility/input errors не ретраятся бесконечно.

### Full — `CURRENT — IMPLEMENTED`

- Surface: persisted text chunks, затем PDF document с caption.
- States: queued, sending, completed, failed, canceled.
- Eligibility повторно проверяется под order lock; refunded/ineligible deliveries отменяются или отклоняются.
- Automatic и manual deliveries имеют разные idempotency keys. Reconciliation создаёт отсутствующие automatic deliveries и requeue-ит eligible retryable/stale work.

### `EVIDENCE BOUNDARY`

Database protocol предотвращает concurrent claims и сохраняет durable progress, но не превращает Telegram transport и PostgreSQL commit в одну atomic transaction. Crash после send до completion commit может привести к duplicate send при recovery.

## 9. Saved materials and resend

### `CURRENT — IMPLEMENTED`

My Reports перечисляет completed registered mini и paid completed full reports текущего пользователя. Mini resend использует completed generation/report data и stored/canonicalized PDF. Canonical full resend требует paid order и canonical PDF, не повторяет purchase, matrix calculation или AI generation.

### `IMPLEMENTATION GAP`

Mixed mini/full pagination применяется не к единому объединённому набору: offset/limit сначала ограничивает mini, затем full добавляются и результат снова обрезается. Full entries могут повторяться между страницами или вытеснять mini; обе report types получают label «Мини-разбор». Orderless legacy full может быть listed, но не проходит current Telegram resend eligibility.

`has_matrix` участвует в full-delivery eligibility/UI gating, но сам по себе не является report entitlement. Authority остаётся у active `PAID` order и report linkage.

### `TARGET — NURA 1.0`

Saved materials должны оставаться Telegram-first access surface для eligible mini/full artifacts. Retention/legal rules этим technical document не устанавливаются.

## 10. Payment/refund entitlement boundary

### `CURRENT — IMPLEMENTED`

- Full report — one-time YooKassa order за 890 ₽; Telegram Stars не являются утверждённым путём.
- Generation claim требует confirmed payment и active `PAID` order.
- Worker повторно проверяет entitlement под lock непосредственно перед artifact persistence.
- Delivery удерживает order lock через send и durable completion, сериализуя refund относительно delivery.
- Refund reconciliation инвалидирует или отменяет незавершённую generation/delivery. Policy доступа к уже потреблённому контенту не выводится из technical cleanup behavior.

Эти refund-fence гарантии относятся к canonical order-backed flow. `LEGACY COMPATIBILITY` допускает payment-linked full без `order_id`: worker может generate/persist его без order lock/recheck, а current Telegram delivery такой report отклоняет.

Payment truth определяют [PAYMENT_FLOW_AUDIT.md](audits/PAYMENT_FLOW_AUDIT.md) и [pricing.md](pricing.md); здесь описана только report-system boundary.

## 11. Account deletion and privacy

### `CURRENT — IMPLEMENTED`

`AccountDeletionService` удаляет DB-backed `Report` rows вместе с report payloads и canonical in-DB artifact bytes/metadata, dependent generation/job и delivery rows и очищает Redis chat history. Financial records, необходимые для accounting/audit, сохраняются detached/anonymized в payment deletion flow; legacy payment rows обрабатываются отдельно текущей deletion implementation.

| Data/artifact | Current account-deletion behavior |
|---|---|
| DB `Report` row и stored matrix/narrative payloads | Удаляются |
| Generation/job и delivery DB rows | Удаляются |
| Canonical PDF bytes/metadata в `Report` | Удаляются вместе с `Report` row |
| Legacy filesystem `{token}.html` / `{token}.pdf` | `AccountDeletionService` не удаляет |
| Уже доставленная Telegram-копия или сохранённая пользователем local copy | Account deletion технически не отзывает |

### `IMPLEMENTATION / PRIVACY GAP`

Runtime-reachable legacy token flow записывает personalized HTML/PDF в `templates/reports/output`, но filesystem lifecycle не связан автоматически с удалением DB records. После account deletion эти files могут остаться в output directory; repository-backed cleanup contract для них не найден. Это current cleanup gap, а не retention/legal policy и не доказательство доступности конкретного файла или URL после deletion.

Generation fingerprints используют HMAC и не раскрывают normalized name/date как readable idempotency key. Report tokens на legacy web routes остаются bearer capabilities и не являются authenticated ownership.

### `OWNER DECISION PENDING`

Retention duration, legal basis и post-refund access к уже потреблённому контенту требуют owner/legal authority.

## 12. Target NURA 1.0 crosswalk

| Capability | Current evidence | NURA 1.0 status |
|---|---|---|
| Telegram-first mini | Text + PDF с durable delivery | `CURRENT — IMPLEMENTED` |
| Telegram-first full | Durable text + PDF with fenced progress | `CURRENT — IMPLEMENTED locally`; external sandbox pending |
| Защита deterministic facts от prose layer | Matrix рассчитывается вне AI и передаётся как structured input | `CURRENT — IMPLEMENTED`, с ограничениями verifier ниже |
| Stored artifacts/resend | Registered mini и canonical full artifacts; mixed listing defects | `IMPLEMENTATION GAP`: My Reports pagination/labels и orderless resend |
| Payment/refund fence | Canonical full: active `PAID` order claim и recheck перед persist/send | `CURRENT — IMPLEMENTED` для order-backed flow; legacy exception остаётся gap |
| Separate report/chat runtime contracts | Separate files/loaders/consumers | `IMPLEMENTATION GAP`: нет independent version/acceptance lifecycle |
| Operational acceptance | Есть local/static evidence | `EVIDENCE BOUNDARY`: sandbox/production proof отделён |

## 13. Target NURA 1.5 boundary

`TARGET — NURA 1.5` включает later gift, Tarot и compatibility surfaces по canonical product spec и будущим owner decisions. Они не расширяют current mini/full contract автоматически. Future visual/image sections, compatibility rules, expanded Tarot и будущие report prices здесь не объявляются implemented.

## 14. Legacy web/PWA compatibility

### `LEGACY COMPATIBILITY`

Token routes для HTML, PDF и kitchen JSON остаются reachable; старый full-report task может записывать filesystem HTML/PDF и отправлять web link. Эти surfaces поддерживают compatibility/history, но не задают Telegram-first NURA 1.0 delivery.

Созданные этим legacy path files не удаляются `AccountDeletionService` автоматически; удаление связанного DB account/report state само по себе не является filesystem cleanup.

Order-backed full worker использует `full_report_v2.html`. Generic full fallback token route ссылается на `full_report.html`, которого нет среди tracked templates. Поэтому web rendering order-backed full row не доказан без compatible saved output; route presence не равен delivery proof.

Duration/sunset web/PWA compatibility — `OWNER DECISION PENDING` по DM-03.

## 15. Implementation and evidence gaps

- `IMPLEMENTATION GAP` — external Telegram/content acceptance full text + PDF не выполнен.
- `IMPLEMENTATION GAP` — separate report/chat prompt files и consumers не имеют independently accepted/versioned rollout/rollback contract.
- `IMPLEMENTATION GAP` — semantic verifier проверяет selected genericness, length, dashboard и arcana consistency, но не является complete formal acceptance suite всех content invariants.
- `IMPLEMENTATION GAP` — legacy token fallback ссылается на отсутствующий `full_report.html`; web rendering current order-backed full rows не гарантирован.
- `IMPLEMENTATION GAP` — legacy payment-linked full без `order_id` может generate/persist без active-order refund fence, попасть в listing и затем не пройти Telegram delivery.
- `IMPLEMENTATION GAP` — My Reports mixed mini/full pagination и labels некорректны для full entries.
- `IMPLEMENTATION / PRIVACY GAP` — account deletion удаляет DB-backed report/job/delivery state, но не удаляет personalized HTML/PDF, записанные legacy token flow на filesystem.
- `EVIDENCE BOUNDARY` — static tests/repository inspection не доказывают sandbox provider, Telegram, YooKassa, external assets или production behavior.

## 16. Owner decisions

`OWNER DECISION PENDING` сохраняется для:

- duration/sunset legacy PWA/web links;
- policy уже потреблённого content после refund;
- retention period/legal basis;
- early-buyer gift, future report pricing, expanded Tarot/compatibility rules;
- future visual/image report sections;
- prompt acceptance thresholds, model/provider changes и rollout strategy.

Telegram-first, цена full report 890 ₽, YooKassa, no Stars, full text+PDF target, report/chat separation target и утверждённый gating не pending.

## 17. Acceptance boundary

Repository tests являются implementation evidence, если assertions соответствуют reachable wiring. Они не доказывают sandbox/production deployment, provider availability, real-user Telegram delivery, YooKassa callbacks, external font loading или operational observability.

Acceptance различает:

1. deterministic calculation correctness;
2. AI output schema/semantic checks;
3. persisted lifecycle/artifact integrity;
4. HTML/PDF rendering;
5. Telegram transport success;
6. durable delivery completion;
7. external environment proof.

Ни одна row, PDF, route, prompt file или local test не объединяет эти границы.

## 18. References

Документация:

- [NURA 1.0/1.5 Product Specification](product/NURA_1_0_1_5_PRODUCT_SPEC.md)
- [Current implementation status](implementation/current-status.md)
- [Documentation migration decisions](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md)
- [Bot specification](bot-spec.md)
- [Bot UX map](bot-ux-map.md)
- [Payment flow audit](audits/PAYMENT_FLOW_AUDIT.md)
- [Pricing](pricing.md)

Primary implementation:

- [Mini application service](../nura_app/core/services/mini_report_application.py)
- [Mini Telegram delivery](../nura_app/core/services/telegram_report_delivery.py)
- [Full order activation](../nura_app/core/services/full_matrix_checkout.py)
- [Full generation worker](../nura_app/core/services/matrix_report_worker.py)
- [Full Telegram delivery](../nura_app/core/services/full_report_telegram_delivery.py)
- [Report models](../nura_app/core/models.py)
- [Runtime result schemas](../nura_app/core/schemas/__init__.py)
- [Report renderer](../nura_app/core/services/report.py)
- [Report API routes](../nura_app/api/routes/reports.py)
- [Mini template](../nura_app/templates/reports/mini_report.html)
- [Full V2 template](../nura_app/templates/reports/full_report_v2.html)

## Full report Telegram delivery

The canonical full-report delivery is `full-text-pdf-v1`: it renders ordered,
user-safe Telegram HTML only from persisted `Report.ai_analysis`, snapshots the
immutable chunks and their SHA-256 before the first send, persists each sent
message ID, then sends the existing canonical PDF artifact. Completion means
both text and PDF were durably recorded. `kitchen_analysis` is never rendered.
Retries resume from the first unsaved text chunk; a PDF retry does not replay
text. The Telegram/DB boundary is at-least-once: the residual crash window is
after Telegram accepts one send and before its adjacent progress commit.

Historical completed PDF-only rows remain marked `pdf-only-v0`; no rollout
creates an unsolicited text resend. A user-initiated resend creates a new
`full-text-pdf-v1` delivery from saved report data and the canonical PDF, with
no new Matrix or AI generation.
