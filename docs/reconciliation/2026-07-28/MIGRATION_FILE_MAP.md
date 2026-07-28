# Stage 2A migration file map

**STATUS: EXECUTED STRUCTURAL MIGRATION RECORD**
**Date:** 2026-07-28
**Baseline:** `main` / `61977175ef3b88fad618674fca2554db60aae379`, existing dirty worktree preserved.

`Content` values: `none` — pure move; `banner` — visible authority/status notice only; `structural` — router/index/report; `approved` — owner-approved product contract edit.

## Authority and navigation

| Old path | New path | Action | Classification | Basis | Links | Content |
|---|---|---|---|---|---|---|
| external `NURA_1_0_1_5_PRODUCT_SPEC.md` | `docs/product/NURA_1_0_1_5_PRODUCT_SPEC.md` | add canonical copy | CANONICAL_TARGET_PRODUCT | owner decision §2.1 / task | verified | approved daily quota + header/change log |
| external `NURA_DOCUMENTATION_MIGRATION_DECISIONS.md` | `docs/decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md` | add | OWNER_DECISION | task priority #1 | verified | none |
| — | `docs/implementation/current-status.md` | create | CURRENT_IMPLEMENTATION | task + reconciliation/code evidence | verified | structural |
| `docs/README.md` | `docs/archive/superseded/docs-README-pre-stage-2a.md` | preserve old router snapshot | SUPERSEDED | baseline preservation | archived exceptions listed in execution report | banner |
| — | `docs/README.md` | create authority router | AUTHORITY_ROUTER | task §6 | verified | structural |
| `AGENTS.md` | `AGENTS.md` | compact authority block | AGENT_NAVIGATION | task §7 | verified | structural |
| `docs/AGENTS.md` | `docs/archive/superseded/agent-rules/docs-AGENTS-mojibake.md` | archive damaged snapshot | SUPERSEDED | migration plan UTF-8 defect | not active | banner |
| — | `docs/AGENTS.md` | recreate compact rules | AGENT_NAVIGATION | task §7 | verified | structural |
| `frontend/pwa/app/AGENTS.md` | `docs/archive/superseded/agent-rules/pwa-AGENTS-mojibake.md` | archive damaged snapshot | SUPERSEDED | migration plan UTF-8 defect | not active | banner |
| — | `frontend/pwa/app/AGENTS.md` | recreate legacy compatibility rules | AGENT_NAVIGATION | task §7 / DM-03 | verified | structural |
| `nura_app/templates/reports/AGENTS.md` | `docs/archive/superseded/agent-rules/reports-AGENTS-mojibake.md` | archive damaged snapshot | SUPERSEDED | migration plan UTF-8 defect | not active | banner |
| — | `nura_app/templates/reports/AGENTS.md` | recreate report authority rules | AGENT_NAVIGATION | task §7 | verified | structural |

## Acceptance and current evidence

| Old path | New path | Action | Classification | Basis | Links | Content |
|---|---|---|---|---|---|---|
| `docs/launch-checklist.md` current section | `docs/acceptance/README.md` | safe split | CURRENT_ACCEPTANCE | clear `Historical PWA-era plan` boundary | verified | structural index |
| `docs/launch-checklist.md` historical section | `docs/archive/legacy-pwa/acceptance/launch-checklist.md` | safe split/move | LEGACY_PWA | migration plan | verified | banner |
| `docs/telegram-first-sandbox-runbook.md` | `docs/acceptance/telegram-first-sandbox.md` | move | CURRENT_ACCEPTANCE | migration plan | verified | banner/authority links |
| `docs/telegram-first-v1-readiness-review.md` | `docs/acceptance/evidence/telegram-first-v1-readiness-review.md` | move | CURRENT_ACCEPTANCE_EVIDENCE | migration plan | verified | dated-evidence banner |
| `docs/audit-astro-insight-contamination.md` | `docs/acceptance/audits/astro-insight-contamination.md` | move | CURRENT_ACCEPTANCE_EVIDENCE | migration plan | verified | banner |
| `docs/audits/LEGACY_TELEGRAM_AUTH_AUDIT.md` | `docs/acceptance/audits/legacy-telegram-auth.md` | move | CURRENT_ACCEPTANCE_EVIDENCE | migration plan | verified | retired-flow banner |
| — | `docs/architecture/README.md` | create placeholder/index | CURRENT_STRUCTURE | Stage 2A limit | verified | structural; no invented architecture |

## Legacy PWA archive

| Old path | New path | Action | Classification | Basis | Links | Content |
|---|---|---|---|---|---|---|
| `AGENTS_TODO.md` | `docs/archive/legacy-pwa/plans/auth-recovery-todo.md` | move | LEGACY_PWA | migration plan | verified | banner |
| `NURA_SITE_QA_AUDIT_2026-07-06.md` | `docs/archive/legacy-pwa/acceptance/site-qa-audit-2026-07-06.md` | move | LEGACY_PWA | migration plan | verified; historical STATE path retained | banner |
| `docs/auth_system_implementation_plan.md` | `docs/archive/legacy-pwa/architecture/auth-system-implementation-plan.md` | move | LEGACY_PWA | migration plan | verified | banner |
| `docs/bot-spec-pwa-patch.md` | `docs/archive/legacy-pwa/product/bot-spec-pwa-patch.md` | move | LEGACY_PWA | migration plan | verified | banner |
| `docs/bot-ux-map-pwa-patch.md` | `docs/archive/legacy-pwa/product/bot-ux-map-pwa-patch.md` | move | LEGACY_PWA | migration plan | verified | banner |
| `docs/platform-strategy.md` | `docs/archive/legacy-pwa/product/platform-strategy.md` | move | LEGACY_PWA | DM-02 / conflict CF-010 | verified | banner |
| `docs/pwa/PWA_IMPLEMENTATION_RULES.md` | `docs/archive/legacy-pwa/architecture/PWA_IMPLEMENTATION_RULES.md` | move | LEGACY_PWA_COMPATIBILITY | migration plan | code links fixed | banner |
| `docs/pwa/PWA_NORTH_STAR_DESIGN.md` | `docs/archive/legacy-pwa/architecture/PWA_NORTH_STAR_DESIGN.md` | move | LEGACY_PWA | migration plan | code links fixed | banner |
| `docs/pwa/PWA_PAGE_CONTRACTS.md` | `docs/archive/legacy-pwa/architecture/PWA_PAGE_CONTRACTS.md` | move | LEGACY_PWA_COMPATIBILITY | migration plan | verified | banner |
| `docs/pwa-spec.md` | `docs/archive/legacy-pwa/architecture/pwa-spec.md` | move | LEGACY_PWA | migration plan | verified | banner |
| `docs/tarot-integration-plan-pwa-patch.md` | `docs/archive/legacy-pwa/product/tarot-integration-plan-pwa-patch.md` | move | LEGACY_PWA | migration plan | verified | banner |
| — | `docs/archive/legacy-pwa/README.md` | create index | LEGACY_PWA | task §9 | verified | structural |

## Superseded and future vision

| Old path | New path | Action | Classification | Basis | Links | Content |
|---|---|---|---|---|---|---|
| `docs/agent-prompts.md` | `docs/archive/superseded/agent-prompts.md` | move | SUPERSEDED | migration plan | archived only | banner |
| `docs/dev-prompts.md` | `docs/archive/superseded/dev-prompts.md` | move | SUPERSEDED | migration plan | archived only | banner |
| — | `docs/archive/superseded/README.md` | create index | SUPERSEDED | task §9 | verified | structural |
| `docs/NURA FORMS SYSTEM.txt` | `docs/vision/content-forms.md` | move/rename | FUTURE_PLATFORM_VISION | migration plan / owner decision §7 | verified | future-vision banner; body preserved |
| — | `docs/vision/platform-independent/README.md` | create boundary | FUTURE_PLATFORM_VISION | proposed architecture | verified | structural |

## Current standards and research

| Old path | New path | Action | Classification | Basis | Links | Content |
|---|---|---|---|---|---|---|
| `docs/audit-astro-insight-contamination.md` | `docs/acceptance/audits/astro-insight-contamination.md` | move | CURRENT_ACCEPTANCE | migration plan | verified | banner |
| `docs/benchmark-competitors.md` | `docs/research/report-benchmarks/benchmark-competitors.md` | move | CURRENT_RESEARCH | migration plan | verified | dated/non-normative banner |
| `docs/industry-standard-analysis.md` | `docs/research/report-benchmarks/industry-standard-analysis.md` | move | CURRENT_RESEARCH | migration plan | verified | dated/non-normative banner |
| `docs/исследование рынка.md` | `docs/research/market/market-research.md` | move/rename | CURRENT_RESEARCH | migration plan | verified | dated/non-normative banner |
| `docs/matrix-algo.md` | `docs/standards/matrix-algorithm.md` | move/rename | CURRENT_TECHNICAL_DOCUMENTATION | migration plan | verified | status banner |
| `docs/design-system.md` | `docs/standards/design-system.md` | move | CURRENT_TECHNICAL_DOCUMENTATION | migration plan | verified | status banner |
| `docs/tone-of-voice.md` | `docs/standards/tone-of-voice.md` | move | CURRENT_TECHNICAL_DOCUMENTATION | migration plan | verified | status banner |

## Reconciliation stabilization

| Old path | New path | Action | Classification | Basis | Links | Content |
|---|---|---|---|---|---|---|
| `docs/_reconciliation/2026-07-28/AUDIT_SUMMARY.md` | `docs/reconciliation/2026-07-28/AUDIT_SUMMARY.md` | move | RECONCILIATION_EVIDENCE | task §11 | verified | status line |
| `docs/_reconciliation/2026-07-28/CURRENT_IMPLEMENTATION_VS_TARGET.md` | `docs/reconciliation/2026-07-28/CURRENT_IMPLEMENTATION_VS_TARGET.md` | move | RECONCILIATION_EVIDENCE | task §11 | verified | superseded-live-status notice |
| `docs/_reconciliation/2026-07-28/DOCUMENTATION_CONFLICT_MATRIX.md` | `docs/reconciliation/2026-07-28/DOCUMENTATION_CONFLICT_MATRIX.md` | move | RECONCILIATION_EVIDENCE | task §11 | verified | status line |
| `docs/_reconciliation/2026-07-28/DOCUMENTATION_INVENTORY.md` | `docs/reconciliation/2026-07-28/DOCUMENTATION_INVENTORY.md` | move | RECONCILIATION_EVIDENCE | task §11 | verified | status line |
| `docs/_reconciliation/2026-07-28/DOCUMENTATION_MIGRATION_PLAN.md` | `docs/reconciliation/2026-07-28/DOCUMENTATION_MIGRATION_PLAN.md` | move | RECONCILIATION_EVIDENCE | task §11 | verified | execution notice |
| `docs/_reconciliation/2026-07-28/OWNER_DECISIONS_REQUIRED.md` | `docs/reconciliation/2026-07-28/OWNER_DECISIONS_REQUIRED.md` | move | RECONCILIATION_EVIDENCE | task §11 | verified | decision precedence notice |
| `docs/_reconciliation/2026-07-28/PROPOSED_DOCUMENTATION_ARCHITECTURE.md` | `docs/reconciliation/2026-07-28/PROPOSED_DOCUMENTATION_ARCHITECTURE.md` | move | RECONCILIATION_EVIDENCE | task §11 | verified | status line |
| — | `docs/reconciliation/2026-07-28/MIGRATION_FILE_MAP.md` | create | RECONCILIATION_REPORT | task | verified | structural |
| — | `docs/reconciliation/2026-07-28/STAGE_2A_EXECUTION_REPORT.md` | create | RECONCILIATION_REPORT | task | verified | structural |

## Mixed files retained for Stage 2B

| Path | Action | Classification | Basis | Links | Content |
|---|---|---|---|---|---|
| `docs/audits/PAYMENT_FLOW_AUDIT.md` | keep + mark | MIXED current 890 / legacy 390 | migration plan | verified | banner |
| `docs/bot-spec.md` | keep + mark | MIXED current/legacy/target | migration plan | verified | banner |
| `docs/bot-ux-map.md` | keep + mark | MIXED current/legacy/target | migration plan | verified | banner |
| `docs/brand/nura-universe/README.md` | keep + mark | MIXED current brand/future world | migration plan | verified | banner |
| `docs/pricing.md` | keep + mark | MIXED legacy pricing | DM-06 | verified | banner |
| `docs/pricing-vs-report-analysis.md` | keep + mark | MIXED dated research | migration plan | verified | banner |
| `docs/prompt-spec.md` | keep + mark | MIXED current/stale/target | DM-07 | verified | banner |
| `docs/report-spec.md` | keep + mark | MIXED current/legacy/target | migration plan | verified | banner |
| `docs/tarot-integration-plan.md` | keep + mark | MIXED history/1.5 target | migration plan | verified | banner |
| `docs/tarot-integration-sessions.md` | keep + mark | MIXED history/current facts | migration plan | verified | banner |
| `docs/two-layer-architecture.md` | keep + mark | MIXED implemented/stale paths | migration plan | verified | banner |
| `AUTH_REMAINING_TASKS.md` | keep + mark | MIXED legacy plan/current compatibility | dirty `STATE.md` historical reference | verified | banner |
| `PLAN.md` | keep + mark | MIXED historical plan | migration plan | broken AGENTS link fixed | banner |
| `industry-standard-analysis.md` | keep + mark | MIXED duplicate research | non-identical repository copies | verified | banner |
| `pricing-vs-report-analysis.md` | keep + mark | MIXED duplicate research | non-identical repository copies | verified | banner |
| `ADMIN_BOT_SPEC.md` | keep + mark | CURRENT_TECHNICAL pending 2B placement | migration plan | verified | banner |
| `DEPLOY.md` | keep + mark | CURRENT_OPERATIONS stable path | migration plan / tooling safety | verified | banner |

## Intentionally not moved

| Paths | Classification | Reason | Next action |
|---|---|---|---|
| Three research PDFs under `docs/` | CURRENT_RESEARCH | Binary content cannot carry an in-document Markdown banner through this text-only migration; active router marks them non-normative | safe binary move/index metadata in Stage 2B |
| Root duplicate `Все_расклады_и_разборы,_которыми_я_занимаюсь.pdf` | SUPERSEDED_DUPLICATE_CANDIDATE | Byte-identical, but deletion/move deferred to avoid destructive binary handling | owner-approved deduplication in Stage 2B |
| `STATE.md` | SESSION_JOURNAL | Pre-existing external modifications; task explicitly forbids update | leave untouched |
