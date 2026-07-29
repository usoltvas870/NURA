# Документация NURA

**STATUS: AUTHORITY ROUTER**

Этот файл отвечает только за навигацию и статус источников. Он не дублирует product spec и не доказывает реализацию.

## Минимальный маршрут

1. [Canonical target: NURA 1.0 / 1.5](product/NURA_1_0_1_5_PRODUCT_SPEC.md) — утверждённый product scope, цены, границы версий и acceptance target.
2. [Current implementation status](implementation/current-status.md) — что фактически подтверждается code/migrations/tests/config и какие остаются gaps.
3. [Owner migration decisions](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md) — решения владельца по этой миграции; не замена product spec.
4. [Acceptance evidence router](acceptance/README.md) — current/dated local evidence, runbooks, unexecuted external sandbox и unproven production/legal gates.

Target state не равен implemented state. При конфликте product spec определяет цель, а code/tests/config — фактическую реализацию.

## Разделы

| Раздел | Роль | Авторитетность |
|---|---|---|
| [product/](product/NURA_1_0_1_5_PRODUCT_SPEC.md) | Целевой контракт NURA 1.0/1.5 | Канонический target; редактируется только отдельной задачей |
| [implementation/](implementation/current-status.md) | Evidence-backed зеркало реализации | Удобный индекс; code/tests/config имеют приоритет |
| [decisions/](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md) | Утверждённые решения владельца | Авторитетны в своей области, но не заменяют spec |
| [architecture/](architecture/README.md) | Навигация к техническим contracts; принятые current contracts также сохраняют стабильные root/docs paths | Current technical routing; code/tests остаются implementation authority |
| [acceptance/](acceptance/README.md) | Local, dated, sandbox, production и legal evidence levels | Current evidence router; local PASS не означает sandbox или production ready |
| [operations/](operations/) | Runbooks и release/security/backup contracts | Не разрешают внешние действия без текущего approval |
| [standards/](standards/) | Matrix, design, tone | Технические/editorial standards, не product roadmap |
| [research/](research/) | Market/content/report evidence | Dated и non-normative |
| [vision/](vision/platform-independent/README.md) | Возможные будущие направления | FUTURE VISION — NOT COMMITTED TO ROADMAP |
| [archive/](archive/legacy-pwa/README.md) | Legacy и superseded history | Не использовать как текущий контракт |
| [reconciliation/](reconciliation/2026-07-28/AUDIT_SUMMARY.md) | Audit и migration evidence | Dated, non-normative |

## Current Telegram-first

Telegram-бот — основной интерфейс. NURA 1.0 включает mini-report, one-time Full Matrix 890 ₽ через YooKassa, сохранённые материалы, базовый чат, карту дня и минимальный broadcast contour согласно canonical target. Фактические пробелы, включая daily quota, full text delivery и broadcasts, перечислены в [current status](implementation/current-status.md).

## Acceptance и operations

- [Acceptance index](acceptance/README.md)
- [Telegram-first external sandbox runbook](acceptance/telegram-first-sandbox.md)
- [Dated readiness evidence](acceptance/evidence/telegram-first-v1-readiness-review.md)
- [Backup/restore](operations/backup-restore.md)
- [Security configuration](operations/p7a-security-configuration.md)
- [Release handoff](operations/p7b-state-b-handoff.md)
- Root [DEPLOY.md](../DEPLOY.md) сохраняет стабильный release-tooling path; это не production evidence.

## Standards и research

- [Matrix algorithm](standards/matrix-algorithm.md)
- [Design system source map](standards/design-system.md)
- [Tone of voice](standards/tone-of-voice.md)
- [Market research](research/market/market-research.md)
- [Competitor/report benchmarks](research/report-benchmarks/benchmark-competitors.md)
- [Industry report analysis](research/report-benchmarks/industry-standard-analysis.md)

PDF research sources пока остаются на прежних путях до отдельной безопасной binary migration; они не являются normative contracts.

## Stage 2B document classifications

Write Sessions 1–6 завершили содержательную классификацию domain, research,
operations и acceptance-документов. Эти labels задают маршрутизацию, но не
превращают ни один документ во вторую product specification или production proof.

| Документ / группа | Финальная классификация | Основная authority role |
|---|---|---|
| [bot-spec.md](bot-spec.md) | `current technical` | Telegram implementation architecture с target crosswalk |
| [bot-ux-map.md](bot-ux-map.md) | `current technical` | Telegram UX journeys с current/target/legacy boundaries |
| [PAYMENT_FLOW_AUDIT.md](audits/PAYMENT_FLOW_AUDIT.md) | `reconciliation evidence` | Dated evidence-oriented payment/refund/delivery audit |
| [pricing.md](pricing.md) | `current technical` | Pricing/access map; canonical prices остаются в product spec |
| [report-spec.md](report-spec.md) и [two-layer-architecture.md](two-layer-architecture.md) | `current technical` | Report delivery и structured/narrative architecture |
| [prompt-spec.md](prompt-spec.md) | `current technical` | Runtime-reachable prompt contracts без prompt bodies |
| [tarot-integration-plan.md](tarot-integration-plan.md) | `current technical` | Current Tarot/compatibility/referral map с target crosswalk |
| [tarot-integration-sessions.md](tarot-integration-sessions.md) | `historical/superseded` | Historical implementation record, не live plan |
| Root [AUTH_REMAINING_TASKS.md](../AUTH_REMAINING_TASKS.md) | `historical/superseded` | Auth checklist history; email wiring gap маршрутизируется в current status |
| Root [PLAN.md](../PLAN.md) | `historical/superseded` | Historical project board, не roadmap/backlog |
| Root [ADMIN_BOT_SPEC.md](../ADMIN_BOT_SPEC.md) | `current operations` | Static/local Admin Bot operations contract; Celery resolver gap сохранён |
| Root [DEPLOY.md](../DEPLOY.md) | `runbook` / `current operations` | Deployment instructions; не evidence выполненного deploy |
| [brand/nura-universe/README.md](brand/nura-universe/README.md) | `current technical` + `future vision` | Current brand standard и явно отделённое creative future |
| [pricing-vs-report-analysis.md](pricing-vs-report-analysis.md) и [industry-standard-analysis.md](research/report-benchmarks/industry-standard-analysis.md) | `dated research` | Non-normative research snapshots |
| Root [pricing-vs-report-analysis.md](../pricing-vs-report-analysis.md) и [industry-standard-analysis.md](../industry-standard-analysis.md) | `authority redirect` | Link-stable redirects к primary research documents |
| [acceptance/](acceptance/README.md) | `acceptance evidence` | Evidence levels, dated records, external/production boundaries |
| [telegram-first-sandbox.md](acceptance/telegram-first-sandbox.md) | `runbook` | External sandbox procedure; `RUNBOOK — NOT EXECUTION PROOF` |
| [reconciliation/](reconciliation/2026-07-28/AUDIT_SUMMARY.md) | `reconciliation evidence` | Dated migration/audit history, не current contract |

`current technical` и `current operations` не означают, что внешний sandbox,
deployment или production availability доказаны. Для implemented state всё равно
приоритетны code/migrations/tests/config и [current status](implementation/current-status.md).

## Remaining owner-decision boundaries

Stage 2B established the current documentation classifications and authority
boundaries reflected in this router. Repository history and accepted
documentation reviews provide change provenance; this router itself is not
product, implementation or acceptance evidence.

Следующий список — краткая навигационная, неисчерпывающая сводка нерешённых
decision families, а не полный owner-decision register:

- legacy/platform compatibility и retirement: PWA, email/VK/guest auth, web links,
  legacy 390 ₽ и saved payment methods;
- product/economics NURA 1.5: gift migration для ранних покупателей, Tarot
  retention/accepted set, expanded-chat fair use и 1.5B growth parameters;
- broadcast timing/suppression и остающиеся campaign parameters;
- prompt/content/style acceptance, prompt version approval и rollout/rollback
  governance;
- future tooling disposition: canonical location/status OpenCode-agent materials,
  Video Assembler и NURA Forms;
- external sandbox GO/timing, production/operations/legal gates, включая topology,
  secrets, backup/restore, monitoring, deployment и incident/support SLA.

Утверждённые product decisions определяют [canonical product spec](product/NURA_1_0_1_5_PRODUCT_SPEC.md)
и [migration decisions](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md).
Нерешённые границы могут быть распределены по принятым domain documents, включая
[bot specification](bot-spec.md), [bot UX map](bot-ux-map.md) и
[prompt contracts](prompt-spec.md). Датированный
[reconciliation owner-decision register](reconciliation/2026-07-28/OWNER_DECISIONS_REQUIRED.md)
сохраняет historical/full source своего этапа и должен читаться вместе с более
новыми решениями и domain documents. Отсутствие вопроса в этой краткой сводке не
означает, что решение принято. Router не принимает owner decisions молча.

## Legacy PWA и future vision

- [Legacy PWA archive](archive/legacy-pwa/README.md) сохраняет product, architecture и acceptance history для compatibility maintenance.
- [Platform-independent vision](vision/platform-independent/README.md) описывает только условия возможного будущего пересмотра.
- [Content forms vision](vision/content-forms.md) не входит автоматически в roadmap.

Исторические PWA документы, старые 390 ₽/recurring модели и superseded agent plans не управляют текущей разработкой.

## Что не является авторитетным

- STATE.md — session journal, не спецификация.
- archive/ — история.
- vision/ — неподтверждённые будущие направления.
- reconciliation reports — dated evidence.
- research — вход для решений, не решение.
- historical/superseded и dated research документы — не current authority независимо от сохранённой технической ценности.
- generated/tool documentation вне docs/ — не product authority.

## Правило изменений

Не создавай второй canonical product spec. Не переноси runtime prompts в docs/: исполняемые prompt templates остаются только в nura_app/core/prompts/. Не расширяй NURA 1.0 функциями 1.5 без отдельного owner decision.

`STATE.md` — журнал состояния и решений, но не нормативная спецификация, не
acceptance evidence и не замена current implementation mirror.
