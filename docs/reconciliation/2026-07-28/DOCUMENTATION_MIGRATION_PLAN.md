# NURA: план миграции документации (без выполнения)

**STATUS: STAGE 1 MIGRATION PLAN — EXECUTION RECORDED BY STAGE 2A REPORTS**

Этот файл описывает Этап 2, но **не выполняет** перемещения, переименования, удаления или редактирования. Per-file source classification находится в `DOCUMENTATION_INVENTORY.md`; правила ниже однозначно покрывают все 180 артефактов.

## Волны миграции

1. **Authority first:** canonical Markdown, docs router, decision log, current status, acceptance index.
2. **Critical split:** bot, pricing/payments, reports, prompts/chat, broadcasts/lifecycle.
3. **Legacy isolation:** PWA-first product/architecture/acceptance с legacy index и compatibility boundary.
4. **Research/vision:** отделить dated research от normative contracts.
5. **Tool/generated hygiene:** OpenCode duplicates, Graphify retention, broken links/mojibake.
6. **Acceptance:** link check, inventory reconciliation, code/test evidence, owner sign-off.

## Product/project/docs files: точный per-file plan

| Текущий путь | Действие | Предлагаемое назначение/target |
|---|---|---|
| `C:/Users/Bayzel/OneDrive/Desktop/NURA_1_0_1_5_PRODUCT_SPEC.md` | `REPLACE_WITH_NEW_DOCUMENT` | Скопировать утверждённое содержимое в `docs/product/NURA_1_0_1_5_PRODUCT_SPEC.md`; внешнюю копию больше не использовать как repository authority. |
| `C:/Users/Bayzel/OneDrive/Desktop/NURA_1_0_1_5_CANONICAL_SPEC.docx` | `MERGE_WITH_ANOTHER_DOCUMENT` | Считать generated human-readable derivative canonical Markdown; решить, хранить ли release artifact вне repo. |
| `ADMIN_BOT_SPEC.md` | `UPDATE_IN_PLACE` | После сверки переместить/объединить с `docs/architecture/admin-operations.md`. |
| `AGENTS.md` | `UPDATE_IN_PLACE` | Добавить только compact authority links и task-reading routes. |
| `AGENTS_TODO.md` | `MOVE_TO_LEGACY_PWA` | `docs/archive/legacy-pwa/plans/auth-recovery-todo.md`. |
| `AUTH_REMAINING_TASKS.md` | `SPLIT` | Проверенные web-auth compatibility facts → architecture; checklist/history → legacy PWA. |
| `DEPLOY.md` | `KEEP_AS_CURRENT` | Сохранить release contract; добавить в operations index. |
| `industry-standard-analysis.md` | `MERGE_WITH_ANOTHER_DOCUMENT` | Объединить provenance/current copy с `docs/industry-standard-analysis.md`, root copy retire. |
| `NURA_SITE_QA_AUDIT_2026-07-06.md` | `MOVE_TO_LEGACY_PWA` | `archive/legacy-pwa/acceptance/`. |
| `PLAN.md` | `SPLIT` | Accepted decisions → decision log; verified current → status; ideas → vision/backlog; затем retire. |
| `pricing-vs-report-analysis.md` | `MERGE_WITH_ANOTHER_DOCUMENT` | Объединить с docs copy/research; root copy retire. |
| `STATE.md` | `SPLIT` | Оставить append-only journal; извлечь без переписывания history: decisions/current/acceptance links. |
| `Все_расклады_и_разборы,_которыми_я_занимаюсь.pdf` | `MERGE_WITH_ANOTHER_DOCUMENT` | После checksum verification оставить только `docs/` copy. |
| `docs/agent-prompts.md` | `MOVE_TO_SUPERSEDED_ARCHIVE` | Исторический agent workflow; удалить broken links из active index. |
| `docs/AGENTS.md` | `UPDATE_IN_PLACE` | Исправить UTF-8/mojibake; добавить compact authority map. |
| `docs/audit-astro-insight-contamination.md` | `KEEP_AS_CURRENT` | Переместить в `acceptance/audits/` как dated evidence. |
| `docs/audits/LEGACY_TELEGRAM_AUTH_AUDIT.md` | `KEEP_AS_CURRENT` | Оставить security evidence; ясно маркировать retired flow. |
| `docs/audits/PAYMENT_FLOW_AUDIT.md` | `SPLIT` | Current one-time checkout evidence отдельно от legacy 390 findings/history. |
| `docs/auth_system_implementation_plan.md` | `MOVE_TO_LEGACY_PWA` | Извлечь current compatibility contract, план сохранить в archive. |
| `docs/benchmark-competitors.md` | `UPDATE_IN_PLACE` | `docs/research/report-benchmarks/`; добавить as-of date и убрать current product authority. |
| `docs/bot-spec.md` | `SPLIT` | `architecture/telegram.md`, UX/acceptance matrix, legacy subscription appendix. |
| `docs/bot-spec-pwa-patch.md` | `MOVE_TO_LEGACY_PWA` | Historical PWA ADR/patch. |
| `docs/bot-ux-map.md` | `SPLIT` | NURA 1.0 Telegram UX vs NURA 1.5 target vs legacy 390/PWA. |
| `docs/bot-ux-map-pwa-patch.md` | `MOVE_TO_LEGACY_PWA` | Historical UX patch. |
| `docs/brand/nura-universe/README.md` | `SPLIT` | Current brand tokens/voice → standards; extended world → vision. |
| `docs/design-system.md` | `UPDATE_IN_PLACE` | Current design source map; согласовать с NURA design skill и legacy PWA boundary. |
| `docs/dev-prompts.md` | `MOVE_TO_SUPERSEDED_ARCHIVE` | Retain as history only; исключить из active index. |
| `docs/engineering/review-video-assembler-v2.md` | `KEEP_AS_CURRENT` | Сохранить рядом с assembler; owner решает operations vs vision/content tooling. |
| `docs/engineering/video-assembler.md` | `KEEP_AS_CURRENT` | Сохранить current technical doc; добавить code/test evidence. |
| `docs/industry-standard-analysis.md` | `UPDATE_IN_PLACE` | Dated research, consolidated with root duplicate topic. |
| `docs/launch-checklist.md` | `MOVE_TO_LEGACY_PWA` | Historical acceptance archive; active launch index заменить. |
| `docs/matrix-algo.md` | `UPDATE_IN_PLACE` | `standards/matrix-algorithm.md`, связать с implementation tests. |
| `docs/NURA FORMS SYSTEM.txt` | `MOVE_TO_FUTURE_VISION` | `vision/content-forms.md`, если owner сохраняет subsystem. |
| `docs/operations/backup-restore.md` | `KEEP_AS_CURRENT` | Сохранить в operations; link from acceptance. |
| `docs/operations/p7a-security-configuration.md` | `KEEP_AS_CURRENT` | Сохранить как versioned security config contract. |
| `docs/operations/p7b-state-b-handoff.md` | `KEEP_AS_CURRENT` | Сохранить как release handoff. |
| `docs/platform-strategy.md` | `MOVE_TO_LEGACY_PWA` | `archive/legacy-pwa/product/platform-strategy.md`. |
| `docs/pricing.md` | `SPLIT` | Retired 390 model → archive; new `architecture/payments-entitlements.md` derives from canonical + code. |
| `docs/pricing-vs-report-analysis.md` | `MERGE_WITH_ANOTHER_DOCUMENT` | Dated value research; broken link cleanup. |
| `docs/prompt-spec.md` | `SPLIT` | Current AI prompt architecture/registry отдельно от editorial examples/target runtime layer. |
| `docs/pwa/PWA_IMPLEMENTATION_RULES.md` | `MOVE_TO_LEGACY_PWA` | Active compatibility maintenance rules under legacy index. |
| `docs/pwa/PWA_NORTH_STAR_DESIGN.md` | `MOVE_TO_LEGACY_PWA` | Historical design direction; убрать «North Star» authority. |
| `docs/pwa/PWA_PAGE_CONTRACTS.md` | `MOVE_TO_LEGACY_PWA` | Active compatibility page contracts. |
| `docs/pwa-spec.md` | `SPLIT` | Implemented compatibility architecture vs historical plan; оба под legacy boundary. |
| `docs/README.md` | `UPDATE_IN_PLACE` | Первая Stage 2 правка: authority/status router с current/target/legacy/vision. |
| `docs/report-spec.md` | `SPLIT` | Current render/generation/storage, Telegram delivery target, legacy web access appendix. |
| `docs/tarot-integration-plan.md` | `SPLIT` | Historical implementation plan + accepted NURA 1.5 target links. |
| `docs/tarot-integration-plan-pwa-patch.md` | `MOVE_TO_LEGACY_PWA` | PWA Tarot history. |
| `docs/tarot-integration-sessions.md` | `SPLIT` | Session history archive; verified current status moves to implementation matrix. |
| `docs/telegram-first-sandbox-runbook.md` | `KEEP_AS_CURRENT` | `acceptance/telegram-first-sandbox.md` or operations runbook; preserve explicit opt-in. |
| `docs/telegram-first-v1-readiness-review.md` | `KEEP_AS_CURRENT` | Dated local readiness evidence under `acceptance/evidence/`; не превращать cumulative worktree verdict в standing product contract. |
| `docs/tone-of-voice.md` | `UPDATE_IN_PLACE` | `standards/tone-of-voice.md`; fix links and bind to runtime prompt versions. |
| `docs/two-layer-architecture.md` | `UPDATE_IN_PLACE` | Merge into current reports architecture; remove future-path fiction. |
| `docs/анализ структуры, глубины и ценностного предложения платных отчётов по «Матрице судьбы» на рынке России и СНГ.pdf` | `KEEP_AS_CURRENT` | `research/report-benchmarks/`; add provenance/quality caveat in index. |
| `docs/Все_расклады_и_разборы,_которыми_я_занимаюсь.pdf` | `KEEP_AS_CURRENT` | Единственная retained research/content source copy. |
| `docs/исследование рынка.md` | `KEEP_AS_CURRENT` | `research/market/`, as-of label, no normative claims. |
| `docs/Карта вечнозелёного спроса для Nura_ Конфигурация Viral Screening Radar в нише самопознания на TikTok.pdf` | `KEEP_AS_CURRENT` | `research/content-acquisition/`, as-of/decay warning. |
| `frontend/pwa/app/AGENTS.md` | `UPDATE_IN_PLACE` | Encoding fix + legacy compatibility scope; не перемещать без tool-path audit. |
| `nura_app/templates/reports/AGENTS.md` | `UPDATE_IN_PLACE` | Encoding fix + links to reports architecture/QA; path remains nested. |

## Ancillary files: exhaustive deterministic rules

These rules apply to every path listed under the matching inventory section; there are no hidden exceptions.

### `.agents/skills/` — 5 files

All five files listed in Inventory §C: `KEEP_AS_CURRENT`. They remain outside docs because they are executable agent instructions. After authority migration, update only links that point to moved docs.

### `.design-sync/` — 9 files

All nine files listed in Inventory §D: `UPDATE_IN_PLACE` only through the design-sync workflow. Keep outside docs. Add an index link to the accepted design authority; do not manually fork component prompt contracts.

### `.github/agents/` and `.github/instructions/` — 9 files

All nine files in Inventory §E: `KEEP_AS_CURRENT`. Later verify they defer to root/nested AGENTS and do not claim product authority.

### Root `.opencode/` — 38 files

- `.opencode/plans/ADMIN_UPGRADE_PLAN.md`: `SPLIT`; verified current facts → admin architecture, remaining work → non-authoritative plan/archive.
- The other 37 files in Inventory §F: `KEEP_AS_CURRENT` as tool instructions. Update links only if documentation moves.

### `nura_app/.opencode/agents/` — 40 files

The following 11 exact duplicates: `MERGE_WITH_ANOTHER_DOCUMENT` after OD-10 decides canonical tool location:

- `ai-engineer.md`
- `api-tester.md`
- `backend-architect.md`
- `code-reviewer.md`
- `database-optimizer.md`
- `devops-automator.md`
- `frontend-developer.md`
- `security-engineer.md`
- `software-architect.md`
- `technical-writer.md`
- `workflow-architect.md`

The other 29 exact paths in Inventory §G: `KEEP_AS_CURRENT` pending an OpenCode authority/index audit. No product status should be derived from them.

### `graphify-out/` Markdown — 20 files

- `graphify-out/GRAPH_REPORT.md`: `KEEP_AS_CURRENT` as generated current view, never normative.
- All 19 dated `graphify-out/YYYY-MM-DD/GRAPH_REPORT.md` paths in Inventory §H: `MOVE_TO_SUPERSEDED_ARCHIVE` conceptually via a documented retention policy. Do not manually move generated trees until Graphify tooling expectations are verified. Exact duplicate dates 2026-07-14/2026-07-26 should not both be presented as distinct architecture states.

## Новые документы Stage 2 и их источники

| Новый документ | Источники, которые он заменяет/объединяет |
|---|---|
| `docs/product/NURA_1_0_1_5_PRODUCT_SPEC.md` | Приложенный canonical MD; DOCX remains derivative. |
| `docs/product/decisions.md` | Только принятые owner decisions + relevant canonical updates; не копия STATE. |
| `docs/implementation/current-status.md` | Этот audit + fresh code/tests/migrations evidence. |
| `docs/architecture/telegram.md` | Current code + split bot spec/UX + canonical target. |
| `docs/architecture/payments-entitlements.md` | Full-matrix checkout/payment audit + canonical 1.0/1.5; legacy 390 explicitly separated. |
| `docs/architecture/reports.md` | report spec + two-layer doc + delivery services/tests. |
| `docs/architecture/chat.md` | chat quota/application/history code/tests + OD-01. |
| `docs/architecture/broadcasts-lifecycle.md` | generic broadcast current + canonical 1.0/1.5 targets. |
| `docs/acceptance/README.md` | canonical checklists + test/sandbox/production evidence map. |
| `docs/archive/legacy-pwa/README.md` | Все `LEGACY_PWA` files and compatibility status. |
| `docs/vision/platform-independent/README.md` | Short boundary/triggers; links to research/legacy, no duplicated architecture. |

## Acceptance gates Этапа 2

1. 180 source rows each have a destination/disposition; counts reconcile.
2. No active index links to missing files.
3. Canonical price/funnel/payment/report assertions appear in one normative product spec.
4. All current technical docs label current vs target vs legacy.
5. Code/test references resolve; paths reflect actual packages.
6. UTF-8/mojibake fixed in active agent/docs navigation.
7. No secrets, generated Graphify diffs or unrelated worktree changes included.
8. Owner decisions are recorded before changing behavior or deleting legacy compatibility.
