# Документация NURA

**STATUS: AUTHORITY ROUTER**

Этот файл отвечает только за навигацию и статус источников. Он не дублирует product spec и не доказывает реализацию.

## Минимальный маршрут

1. [Canonical target: NURA 1.0 / 1.5](product/NURA_1_0_1_5_PRODUCT_SPEC.md) — утверждённый product scope, цены, границы версий и acceptance target.
2. [Current implementation status](implementation/current-status.md) — что фактически подтверждается code/migrations/tests/config и какие остаются gaps.
3. [Owner migration decisions](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md) — решения владельца по этой миграции; не замена product spec.
4. [Acceptance index](acceptance/README.md) — local evidence, pending external sandbox и production gates.

Target state не равен implemented state. При конфликте product spec определяет цель, а code/tests/config — фактическую реализацию.

## Разделы

| Раздел | Роль | Авторитетность |
|---|---|---|
| [product/](product/NURA_1_0_1_5_PRODUCT_SPEC.md) | Целевой контракт NURA 1.0/1.5 | Канонический target; редактируется только отдельной задачей |
| [implementation/](implementation/current-status.md) | Evidence-backed зеркало реализации | Удобный индекс; code/tests/config имеют приоритет |
| [decisions/](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md) | Утверждённые решения владельца | Авторитетны в своей области, но не заменяют spec |
| [architecture/](architecture/README.md) | Технические contracts | Stage 2B pending; не заполнять предположениями |
| [acceptance/](acceptance/README.md) | Local, sandbox и production evidence | Local PASS не означает production ready |
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
- [Local Telegram-first sandbox runbook](acceptance/telegram-first-sandbox.md)
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

## Mixed documents — Stage 2B pending

Следующие документы сохранены без масштабного переписывания и имеют временный banner MIXED:

- bot-spec.md, bot-ux-map.md;
- pricing.md, pricing-vs-report-analysis.md;
- prompt-spec.md, report-spec.md, two-layer-architecture.md;
- tarot-integration-plan.md, tarot-integration-sessions.md;
- audits/PAYMENT_FLOW_AUDIT.md;
- brand/nura-universe/README.md.

Оставшиеся root mixed-документы, включая `ADMIN_BOT_SPEC.md` и `DEPLOY.md`, перечислены в полном [migration file map](reconciliation/2026-07-28/MIGRATION_FILE_MAP.md); они не являются product authority.

Их нельзя использовать как самостоятельный current product contract. Stage 2B должен разделить current technical facts, legacy history и accepted future target.

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
- mixed documents — требуют Stage 2B split.
- generated/tool documentation вне docs/ — не product authority.

## Правило изменений

Не создавай второй canonical product spec. Не переноси runtime prompts в docs/: исполняемые prompt templates остаются только в nura_app/core/prompts/. Не расширяй NURA 1.0 функциями 1.5 без отдельного owner decision.
