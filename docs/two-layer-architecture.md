# NURA Report Generation — Structured and Narrative Architecture

## 1. Authority and scope

Документ объясняет внутреннее разделение deterministic/structured processing и AI-generated narrative в reachable mini/full pipelines. Delivery и commercial lifecycle описаны в [report-spec.md](report-spec.md); product target — только в [NURA 1.0/1.5 Product Specification](product/NURA_1_0_1_5_PRODUCT_SPEC.md).

Используются labels `CURRENT — IMPLEMENTED`, `TARGET — NURA 1.0`, `TARGET — NURA 1.5`, `IMPLEMENTATION GAP`, `LEGACY COMPATIBILITY`, `HISTORICAL / SUPERSEDED`, `OWNER DECISION PENDING`, `EVIDENCE BOUNDARY`, `OUT OF SCOPE`.

## 2. Current architecture summary

### `CURRENT — IMPLEMENTED`

Текущая архитектура содержит два логических content layers и отдельные downstream artifact/delivery stages:

```text
Validated identity/date input
        │
        ▼
MatrixService.calculate()
        │
        ├── structured MatrixData ─────────────┐
        │                                      │
        ▼                                      ▼
AI narrative generation              template context assembly
        │                                      │
        ▼                                      ▼
Pydantic result validation       Jinja HTML → WeasyPrint PDF
        │                                      │
        └──────── persistence on Report ───────┘
                                   │
                                   ▼
                         durable Telegram delivery
```

«Two-layer» означает ownership of truth, а не два deployment services. Deterministic calculation — источник matrix numbers/positions. AI превращает переданные facts в narrative и не должен пересчитывать или перезаписывать их. Rendering/delivery потребляют оба слоя, но не являются narrative generation.

## 3. Structured/deterministic inputs

### `CURRENT — IMPLEMENTED`

`MatrixService.calculate(birth_date)` создаёт `MatrixData` с date-derived values и matrix positions для narrative/templates. Name не участвует в этом calculation, не меняет matrix numbers/arcana/date-derived facts и не является source of deterministic calculation truth. Name используется для narrative/template personalization и отдельно влияет на idempotency/reuse identity mini generation через HMAC fingerprint. Для registered flow calculated matrix результат сериализуется в `Report.matrix_data`.

Mini input нормализуется и fingerprint-ится до generation. HMAC fingerprint включает normalized name, canonical date, report type и `mini-v1`, поддерживая idempotency без readable PII key. Поэтому другой canonical name может создать другой generation reuse key, хотя deterministic Matrix values не меняются.

Canonical full generation начинается для claimed order-linked report с confirmed payment и active `PAID` entitlement. `LEGACY COMPATIBILITY` допускает payment-linked report без `order_id`; для него worker не проверяет active order. Worker передаёт calculated matrix data в AI/rendering layers; payment fields не являются AI input или AI decision.

Deterministic boundary владеет:

- validated name/date format;
- matrix values, positions, energies и calculator output;
- report ownership/type, order/payment linkage и lifecycle state;
- artifact bytes/hash/size/MIME/completion metadata;
- delivery eligibility/state.

## 4. AI narrative generation

### Mini — `CURRENT — IMPLEMENTED`

`AIService.generate_mini_analysis()` форматирует `mini_analysis.txt` с reasoning instruction и serialized matrix input, вызывает configured DeepSeek-compatible API, парсит JSON и валидирует `MiniAnalysisResult`. Пять narrative fields используются persistence, Telegram text и mini PDF.

### Full — `CURRENT — IMPLEMENTED`

`DefaultMatrixReportGenerator` запускает поверх уже рассчитанного structured layer:

- `ReportGenerationLoop`: full result из `full_report_part_a.txt` и `full_report_part_b.txt`, validation `FullReportResult`, bounded semantic verification/retry;
- `AIService.generate_kitchen_report()`: `kitchen_report.txt` и validation `KitchenReportResult`.

Full и kitchen outputs сохраняются отдельно как `Report.ai_analysis` и `Report.kitchen_analysis`; deterministic source остаётся в `Report.matrix_data`.

### `EVIDENCE BOUNDARY`

Schema validation доказывает shape/types, но не factual correctness каждого предложения. Semantic verifier проверяет selected minimum length, genericness, dashboard и arcana-consistency rules, а не полное отсутствие unsupported claims.

## 5. Schema and validation boundary

### Runtime schemas — `CURRENT — IMPLEMENTED`

Текущий schema package — `core/schemas/`, экспорт через `core/schemas/__init__.py`:

| Schema | Роль | Principal consumers |
|---|---|---|
| `MatrixData` | deterministic calculation result | AI formatting, persistence, templates |
| `MiniAnalysisResult` | five-field mini narrative | mini finalization, Telegram text, mini PDF |
| `FullReportResult` | full narrative sections | semantic verifier, persistence, V2 template |
| `KitchenEntry` / `KitchenReportResult` | structured kitchen explanations | persistence, V2 template, legacy kitchen JSON route |
| `ReportResponse` | Объявленная API-oriented schema | Current reachable consumer не найден; dormant, не persistence contract |

Validation sequence:

1. input normalization/validation;
2. deterministic calculation в typed `MatrixData`;
3. JSON extraction из AI response;
4. Pydantic validation ожидаемой narrative schema;
5. full-report semantic checks и bounded regeneration;
6. template-context assembly и PDF integrity checks.

Malformed model output допускает один corrective JSON call. Mini/full/kitchen определяют fallback data, но semantics различаются: mini application отклоняет generic mini fallback, а full AI loop после исчерпания semantic attempts может вернуть schema-shaped full fallback.

## 6. Persistence boundary

### `CURRENT — IMPLEMENTED`

SQLAlchemy `Report` — общий persistence boundary:

- `matrix_data` — deterministic JSON;
- `ai_analysis` — mini/full narrative JSON;
- `kitchen_analysis` — kitchen narrative JSON для full;
- payment/generation lifecycle fields;
- `artifact_bytes`, `artifact_sha256`, `artifact_size_bytes`, `artifact_mime_type`, `artifact_completed_at`.

Mini и full сохраняются в разные моменты:

- Registered mini finalization commit-ит structured/narrative data в `Report` и завершает durable mini generation. Initial delivery позже создаёт и atomically attaches canonical PDF. Guest web/PWA mini вместо `Report` пишет matrix/narrative в `GuestProfile.report_data` и не имеет Telegram/PDF delivery.
- Canonical order-backed full строит/валидирует HTML/PDF до final entitlement recheck; structured data, оба narrative results, canonical PDF, metadata и completed lifecycle state затем commit-ятся вместе. Legacy payment-linked full без `order_id` может пройти persistence без order recheck.

Generation records/jobs и delivery records — отдельные state machines, поэтому generated/persisted result не считается delivered.

## 7. Rendering and delivery downstream

### `CURRENT — IMPLEMENTED`

`ReportService` и full worker собирают template context из deterministic matrix fields и validated narrative fields; template не получает authority пересчитывать facts.

- Registered mini: `mini_report.html` + shared partials/styles → WeasyPrint PDF; Telegram text, затем PDF.
- Guest mini: web/PWA JSON persistence без Telegram/PDF contract (`LEGACY COMPATIBILITY`).
- Canonical full: `full_report_v2.html` + health/psychological partials → WeasyPrint PDF; Telegram PDF + caption.

### `IMPLEMENTATION GAP`

Full narrative есть в rendered HTML/PDF, но не доставляется как full Telegram text. PDF content не закрывает NURA 1.0 text+PDF target.

### `LEGACY COMPATIBILITY`

Старый task записывает HTML/PDF files и отправляет tokenized web links; token routes возвращают stored/rendered output. Этот path не меняет ownership слоёв и не определяет target delivery.

## 8. Integrity and safety invariants

1. Deterministic matrix facts рассчитывает `MatrixService`, а не AI prose.
2. AI получает serialized structured input и возвращает expected JSON shape; prose не пишет database lifecycle fields.
3. Pydantic validation необходима, но недостаточна для narrative truth.
4. `TARGET — NURA 1.0`: runtime language не должен позиционировать NURA как therapist, oracle, medical diagnosis или objective future predictor. Current composite report prompts содержат конфликтующие health/prediction-like instructions, поэтому invariant ещё не доказан end-to-end.
5. Voice/naturalness может меняться без изменения calculations, arcana facts, schemas, safety и deterministic report structure.
6. User content считается untrusted; Jinja HTML environment использует autoescape, diagnostic fallback экранирует serialized content.
7. Canonical PDF integrity проверяется до delivery; resend не повторяет matrix/AI generation.
8. Canonical order-backed full проверяет active `PAID` entitlement в services/repositories, не AI/templates. Legacy orderless exception не имеет эквивалентного order fence.

Runtime-reachable image-prompt layer в mini/full не найден. Future visual sections — `OWNER DECISION PENDING`, не неявный третий слой.

## 9. Current module registry

| Responsibility | Current path | Classification |
|---|---|---|
| Deterministic calculation | `nura_app/core/services/matrix.py` | `CURRENT — IMPLEMENTED` |
| Mini orchestration | `nura_app/core/services/mini_report_application.py` | `CURRENT — IMPLEMENTED` |
| Mini lifecycle | `nura_app/core/services/mini_report_generation.py`, `nura_app/core/repositories/mini_report_generation.py` | `CURRENT — IMPLEMENTED` |
| Guest mini endpoint | `nura_app/api/routes/web.py` | `LEGACY COMPATIBILITY` |
| AI prompt loading/calls | `nura_app/core/services/ai.py` | `CURRENT — IMPLEMENTED` |
| Full semantic loop | `nura_app/core/loop_specs/report_loop.py` | `CURRENT — IMPLEMENTED` |
| Semantic verifier | `nura_app/core/services/verifier.py` | `CURRENT — IMPLEMENTED`, limited rule scope |
| Runtime schemas | `nura_app/core/schemas/__init__.py` | `CURRENT — IMPLEMENTED` |
| Persistence models | `nura_app/core/models.py` | `CURRENT — IMPLEMENTED` |
| Full worker | `nura_app/core/services/matrix_report_worker.py` | `CURRENT — IMPLEMENTED` |
| Context/rendering | `nura_app/core/services/report.py` | `CURRENT — IMPLEMENTED` |
| Mini delivery | `nura_app/core/services/telegram_report_delivery.py` | `CURRENT — IMPLEMENTED` |
| Full delivery | `nura_app/core/services/full_report_telegram_delivery.py` | `CURRENT — IMPLEMENTED` |
| Web token routes | `nura_app/api/routes/reports.py` | `LEGACY COMPATIBILITY` |

## 10. Current limitations and target gaps

- `IMPLEMENTATION GAP` — schema/semantic checks не являются formal independently accepted report-content contract.
- `IMPLEMENTATION GAP` — independently versioned/accepted report/chat prompt release units отсутствуют при разделённых files/consumers.
- `IMPLEMENTATION GAP` — full Telegram text delivery отсутствует.
- `IMPLEMENTATION GAP` — guest mini не имеет `Report` artifact и durable Telegram text/PDF guarantees registered flow.
- `IMPLEMENTATION GAP` — legacy orderless full generation/persistence не защищён active-order refund fence и расходится с Telegram delivery eligibility.
- `IMPLEMENTATION GAP` — shared system и task prompts содержат конфликтующие health/prediction instructions; safety invariant не имеет complete acceptance evidence.
- `EVIDENCE BOUNDARY` — local tests проверяют orchestration/invariants с mocks/fixtures, не provider/production truth.
- `TARGET — NURA 1.0` — сохранить deterministic facts при approved улучшениях narrative voice/naturalness.
- `TARGET — NURA 1.5` — Tarot/compatibility/visual products требуют собственных schemas/boundaries и не наследуют контракт автоматически.

## 11. Historical/stale paths

`HISTORICAL / SUPERSEDED`:

- `core/schemas.py`: current package — `core/schemas/__init__.py` и связанные modules.
- `core/services/report.py` как report generator: это template/context/PDF и legacy file-output support; canonical full orchestration — `matrix_report_worker.py`.
- `api/routes/report.py`: current routes — `api/routes/reports.py`.
- «Kitchen layer planned»: `KitchenReportResult` уже generated, persisted и consumed V2 full template.
- «Two-layer architecture planned»: separation уже reachable; stronger acceptance/version governance остаётся gap.
- `full_report.html` как available template: legacy generic fallback ссылается на него, но tracked file отсутствует; canonical full worker использует `full_report_v2.html`.

Unconsumed `core/prompts/full_report.txt` не доказывает current generation layer; current full использует два part files.

## 12. References

Документация:

- [Report system specification](report-spec.md)
- [Runtime prompt contracts](prompt-spec.md)
- [NURA 1.0/1.5 Product Specification](product/NURA_1_0_1_5_PRODUCT_SPEC.md)
- [Current implementation status](implementation/current-status.md)
- [Documentation migration decisions](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md)

Primary implementation:

- [Matrix service](../nura_app/core/services/matrix.py)
- [AI service](../nura_app/core/services/ai.py)
- [Runtime result schemas](../nura_app/core/schemas/__init__.py)
- [Full report loop](../nura_app/core/loop_specs/report_loop.py)
- [Full generation worker](../nura_app/core/services/matrix_report_worker.py)
- [Report renderer](../nura_app/core/services/report.py)
- [Report models](../nura_app/core/models.py)
- [Mini report template](../nura_app/templates/reports/mini_report.html)
- [Full V2 template](../nura_app/templates/reports/full_report_v2.html)
