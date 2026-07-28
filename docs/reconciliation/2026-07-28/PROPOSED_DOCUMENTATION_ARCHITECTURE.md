# NURA: предлагаемая информационная архитектура документации

**STATUS: STAGE 1 PROPOSAL — STAGE 2A STRUCTURAL BASIS**

## Принцип

Документация должна отвечать на четыре разных вопроса разными слоями: **что хотим** (product target), **что реально работает** (implementation status), **как это устроено** (technical contracts), **что было раньше/может быть потом** (archive/vision). Один файл не должен одновременно выполнять все роли.

## Предлагаемое дерево

```text
docs/
├── README.md                         # короткий authority/status router
├── product/
│   ├── NURA_1_0_1_5_PRODUCT_SPEC.md # canonical target, копия утверждённого MD
│   ├── decisions.md                  # только принятые product decisions/change log
│   └── glossary.md                   # общий язык без повторения scope
├── implementation/
│   ├── current-status.md             # generated-by-audit, evidence links, no target claims
│   └── feature-status-matrix.md       # implemented/partial/gap/legacy by version
├── architecture/
│   ├── telegram.md
│   ├── payments-entitlements.md
│   ├── reports.md
│   ├── chat.md
│   ├── broadcasts-lifecycle.md
│   ├── ai-prompts.md
│   ├── data-model.md
│   └── legacy-web-compatibility.md
├── acceptance/
│   ├── README.md                     # acceptance index by version/subsystem
│   ├── nura-1.0.md
│   ├── nura-1.5.md
│   └── evidence/                     # ссылки/метаданные, не secrets и не transient logs
├── operations/
│   ├── launch-runbook.md
│   ├── backup-restore.md
│   ├── security-configuration.md
│   └── release-handoff.md
├── standards/
│   ├── tone-of-voice.md
│   ├── design-system.md
│   └── matrix-algorithm.md
├── research/
│   ├── market/
│   ├── report-benchmarks/
│   └── content-acquisition/
├── vision/
│   └── platform-independent/
└── archive/
    ├── legacy-pwa/
    │   ├── README.md
    │   ├── product/
    │   ├── architecture/
    │   └── acceptance/
    └── superseded/
        ├── README.md
        └── generated-snapshots/
```

`graphify-out/`, `.agents/`, `.github/`, `.opencode/` и `.design-sync/` остаются вне `docs/`: это tool/generated contracts. `docs/README.md` может ссылаться на их канонические entrypoints, но не перечислять каждый snapshot.

## Авторитетность

| Вопрос | Source of truth | Что запрещено |
|---|---|---|
| Product scope/price/funnel/version | `docs/product/NURA_1_0_1_5_PRODUCT_SPEC.md` | Выводить implemented status только из spec |
| Новое owner decision | `docs/product/decisions.md` + синхронное изменение canonical spec, если меняется contract | Прятать решение в `STATE.md`, chat или plan |
| Current implemented state | Код + migrations + tests + config; краткое зеркало `docs/implementation/current-status.md` | Считать roadmap/checkbox доказательством реализации |
| Technical architecture | `docs/architecture/*.md`, проверяемые ссылками на code/tests | Смешивать target и legacy без labels |
| Acceptance | `docs/acceptance/` | Называть local tests production proof |
| Operations | `docs/operations/` | Печатать secrets; смешивать planned и executed steps |
| Historical PWA | `docs/archive/legacy-pwa/` | Давать документу статус current product contract |
| Future ideas | `docs/vision/` | Включать в committed roadmap без owner decision |
| Market/source research | `docs/research/` | Использовать как нормативный product contract |
| Session journal | `STATE.md` | Использовать как спецификацию |

## Какие новые документы нужны

| Документ | Решение | Причина |
|---|---|---|
| Product specification | **Нужен один** | Уже существует приложенный canonical Markdown; его следует внести как единственный product contract. DOCX — производная копия, не второй source of truth. |
| Current implementation status | **Нужен** | Короткое evidence-backed зеркало кода, явно не нормативное. Можно обновлять на milestones. |
| Product decision log | **Нужен** | Только принятые изменения canonical decisions; не общий дневник. |
| Telegram architecture | **Нужен** | Новый основной интерфейс не имеет чистого current/target technical contract. |
| Payments and entitlements | **Нужен** | Должен развести current one-time 890, retired 390 recurring и target 1.5 399/gift. |
| Report generation | **Нужен как обновление/слияние** | Существующий `report-spec.md` полезен, но смешивает web delivery и старую архитектуру. |
| Chat architecture | **Нужен** | Durable quota/history/idempotency реализованы лучше, чем описаны docs; reset policy открыт. |
| Broadcasts and lifecycle | **Нужен** | Минимальный broadcast foundation и target 1.0/1.5 сейчас смешаны. |
| Launch runbook | **Нужен новый** | Historical PWA checklist не годится; sandbox runbook — важный фрагмент, но не полный launch contract. |
| Acceptance index | **Нужен** | Связывает canonical criteria с unit/PostgreSQL/sandbox/production evidence. |
| Legacy PWA index | **Нужен** | Предотвращает потерю полезной compatibility knowledge и случайное принятие legacy за target. |
| Future platform vision | **Нужен только как index/короткий boundary** | Детальную PWA-архитектуру не дублировать; ссылаться на legacy и фиксировать triggers для возврата. |

## Что не создавать

- Вторую «полную продуктовую спецификацию» или отдельную продуктовую версию DOCX.
- Отдельные файлы для каждой цены, каждого report section или каждого bot callback.
- «Master roadmap», дублирующий canonical §37 и current status.
- Ещё один session journal рядом со `STATE.md`.
- Копии Graphify reports внутри docs.
- Новый giant bot spec: лучше Telegram architecture + UX contracts + acceptance matrix.

## Что должен читать Codex

| Тип задачи | Минимальный набор |
|---|---|
| Любая задача | root `AGENTS.md`, применимые nested `AGENTS.md`, `docs/README.md` как router |
| Product behavior/pricing/scope | canonical product spec + relevant decision log + current status |
| Backend/API/data | relevant architecture doc + code/tests + `nura-docs-state-graphify` |
| Telegram | canonical relevant sections + `architecture/telegram.md` + bot code/tests |
| Payments | canonical monetization sections + `architecture/payments-entitlements.md` + payment tests; protected approval matrix |
| Reports/PDF | canonical formats + `architecture/reports.md` + report nested AGENTS + render QA |
| PWA compatibility | `archive/legacy-pwa/README.md` + relevant legacy technical doc + current compatibility architecture; не product roadmap |
| Launch/ops | acceptance index + operations runbook + current code/config; external actions require current permission |

## Поздние изменения AGENTS.md

AGENTS.md должен остаться компактным. Позднее достаточно добавить:

1. Ссылку на `docs/README.md` как authority router.
2. Ссылку на canonical product spec и правило «target ≠ implemented».
3. Ссылку на `docs/implementation/current-status.md` как convenience index, но с приоритетом code/tests.
4. Маршрутизацию PWA legacy и future vision.
5. Требование обновлять acceptance index при material behavior changes.
6. Короткое правило: prices/payment models меняются только с owner decision.

Вставлять полную продуктовую спецификацию в AGENTS.md не следует.
