# NURA: полный инвентарь документации

**STATUS: DATED RECONCILIATION INVENTORY — NON-NORMATIVE**

## Методика и границы корпуса

Инвентарь содержит **180** артефактов: 178 project-controlled files (`.md`, `.pdf` и `docs/NURA FORMS SYSTEM.txt`) и 2 приложенных canonical-файла. Исключены `.venv`, third-party licenses/docs, requirements/constraints, cache, binary assets и runtime prompt templates: последние проверялись как code contracts, но не считаются документацией. Generated Graphify Markdown включён, потому что он может ошибочно восприниматься как архитектурный документ. Файл `docs/telegram-first-v1-readiness-review.md` появился в shared worktree во время аудита и включён без редактирования.

Дата/актуальность ниже основана на file mtime, датах внутри файла, git/worktree status, code/test links и явных маркерах `plan`, `historical`, `superseded`, `current`. «Refs» означает наличие человеческих ссылок; generated Graphify/cache references не повышают authority.

Колонки `Код` и `Spec`: `Да` — в основном согласован; `Част.` — смешан/устарел; `Нет` — конфликтует; `N/A` — документ не описывает runtime/product behavior.

## Категории

| Категория | Количество |
|---|---:|
| `CURRENT_IMPLEMENTED_STATE` | 6 |
| `CANONICAL_TARGET_PRODUCT` | 2 |
| `CURRENT_TECHNICAL_DOCUMENTATION` | 104 |
| `LEGACY_PWA` | 12 |
| `FUTURE_PLATFORM_VISION` | 8 |
| `SUPERSEDED` | 36 |
| `MIXED` | 12 |
| `UNKNOWN_REQUIRES_DECISION` | 0 |
| **Всего** | **180** |

## A. Product, project, architecture, operations and research (59)

| Путь / название | Назначение и фактическое содержание | Актуальность / refs / подсистемы | Код | Spec | Внутренние противоречия | Статус | Действие |
|---|---|---|:---:|:---:|---|---|---|
| `C:/Users/Bayzel/OneDrive/Desktop/NURA_1_0_1_5_PRODUCT_SPEC.md` — canonical spec | Единый target-contract NURA 1.0/1.5: Telegram funnel, 890, YooKassa, reports, chat, broadcasts, 399/gift/lifecycle/growth. | 2026-07-28; приложен; все product subsystems. | N/A | Да | Нет; open parameters явно перечислены в §42. | `CANONICAL_TARGET_PRODUCT` | `REPLACE_WITH_NEW_DOCUMENT` в `docs/product/` как единственный canonical source. |
| `C:/Users/Bayzel/OneDrive/Desktop/NURA_1_0_1_5_CANONICAL_SPEC.docx` — human copy | Word-копия Markdown с TOC, 191 heading и 19 tables; 99,7% normalized Markdown coverage. | 2026-07-28; производная; не repository-linked. | N/A | Да | Дополнительные повторы из TOC/formatting, продуктовых отличий не найдено. | `CANONICAL_TARGET_PRODUCT` | `MERGE_WITH_ANOTHER_DOCUMENT`: генерировать из MD; не делать отдельным source of truth. |
| `ADMIN_BOT_SPEC.md` — Admin Bot spec | Безопасный ops bot: status/restart/cache/help, monitoring; no deploy/DB commands. | 2026-07-20; refs из STATE/tests; admin/ops. | Да | N/A | Незначительный drift возможен в file map. | `CURRENT_TECHNICAL_DOCUMENTATION` | `UPDATE_IN_PLACE`, затем перенести в architecture/operations. |
| `AGENTS.md` — project agent rules | Repository map, architecture/security/change/approval/verification policy. | 2026-07-13; главный instruction entrypoint. | Да | Част. | Не содержит ссылок на новый canonical spec, что нормально до Этапа 2. | `CURRENT_TECHNICAL_DOCUMENTATION` | `UPDATE_IN_PLACE` позднее только как compact router. |
| `AGENTS_TODO.md` — auth recovery TODO | Потерянные/частично применённые PWA auth изменения и инструкции. | 2026-06-26; root AGENTS прямо снимает normative status. | Част. | Нет | Checklist смешивает выполненное и требуемое. | `LEGACY_PWA` | `MOVE_TO_LEGACY_PWA`. |
| `AUTH_REMAINING_TASKS.md` — auth remaining | Email/VK/PWA deployment tasks, отменённые SMS/Unisender идеи, product follow-ups. | 2026-07-01; code опередил часть статусов. | Част. | Нет | «Осталось» рядом с уже реализованными routes/tests. | `LEGACY_PWA` | `SPLIT`: compatibility contract + historical checklist. |
| `DEPLOY.md` — release contract | Coordinated manual release, immutable static artifact, activation/rollback/retention. | 2026-07-23; enforced tests; deployment. | Да | N/A | Нет material conflict. | `CURRENT_TECHNICAL_DOCUMENTATION` | `KEEP_AS_CURRENT`. |
| `industry-standard-analysis.md` — root report benchmark | Отраслевой объём/цены report; near-duplicate docs version. | 2026-07-02; refs главным образом STATE/Graphify; research. | N/A | Част. | «Текущее состояние» быстро устаревает. | `SUPERSEDED` | `MERGE_WITH_ANOTHER_DOCUMENT` (`docs/industry-standard-analysis.md`). |
| `NURA_SITE_QA_AUDIT_2026-07-06.md` — PWA/site audit | Production-era landing/mini/PWA path findings и fix plan. | Dated 2026-07-06; historical production snapshot. | Част. | Нет | Проверенные тогда факты не равны current worktree. | `LEGACY_PWA` | `MOVE_TO_LEGACY_PWA` acceptance evidence. |
| `PLAN.md` — plan | Now/Next/Ideas/Done project board. | 2026-07-04; linked from STATE; broad scope. | Част. | Част. | Не отделяет target, current и ideas. | `MIXED` | `SPLIT`, затем retire в пользу decision/status/roadmap sources. |
| `pricing-vs-report-analysis.md` — root analysis | Цена 890 vs report content; near-duplicate docs version. | 2026-07-02; duplicate topic. | Част. | Част. | Ссылки на отсутствующий `image-prompts.md`; planned sections как current. | `SUPERSEDED` | `MERGE_WITH_ANOTHER_DOCUMENT`. |
| `STATE.md` — session journal | 99+ sessions, decisions, diffs, checks, historical status. | Modified 2026-07-28; high inbound refs; all subsystems. | Част. | Част. | Duplicate session numbers; history смешана с authority/status. | `MIXED` | `SPLIT`: оставить journal, извлечь accepted decisions/current status. |
| `Все_расклады_и_разборы,_которыми_я_занимаюсь.pdf` — root source PDF | 46-page image-based source/reference of spreads/readings; no extractable text. | Created 2026-05-04; byte-identical docs copy. | N/A | N/A | Точный дубль. | `SUPERSEDED` | `MERGE_WITH_ANOTHER_DOCUMENT`: оставить одну research copy. |
| `docs/agent-prompts.md` — documentation agent prompts | Старый multi-step authoring workflow и commit commands. | 2026-05-14; linked by README; references missing docs. | Нет | Нет | `bot-spec-audit.md`/`docs-plan.md` отсутствуют. | `SUPERSEDED` | `MOVE_TO_SUPERSEDED_ARCHIVE`. |
| `docs/AGENTS.md` — docs rules | Docs roles, STATE/Graphify policy. | 2026-07-13; nested instruction; mojibake. | Да | Да | Visual encoding damage. | `CURRENT_TECHNICAL_DOCUMENTATION` | `UPDATE_IN_PLACE` (encoding + new authority links). |
| `docs/audit-astro-insight-contamination.md` — repository audit | Исторический evidence-based audit ложных Astro paths/contamination. | 2026-07-23; repository hygiene. | Да | N/A | Dated findings, не normative. | `CURRENT_IMPLEMENTED_STATE` | `KEEP_AS_CURRENT` как dated audit, позднее в acceptance/audits. |
| `docs/audits/LEGACY_TELEGRAM_AUTH_AUDIT.md` | Security audit/remediation legacy `tgauth_`, evidence/tests/removal inventory. | 2026-07-20; code-linked. | Да | N/A | Findings и remediation требуют status-aware чтения. | `CURRENT_IMPLEMENTED_STATE` | `KEEP_AS_CURRENT` as audit evidence. |
| `docs/audits/PAYMENT_FLOW_AUDIT.md` | Payment/security/current flow audit + remediation history. | 2026-07-20; many code/test links. | Част. | Нет | Current/old findings и 390 subscription mixed. | `CURRENT_IMPLEMENTED_STATE` | `SPLIT` evidence from legacy monetization conclusions. |
| `docs/auth_system_implementation_plan.md` | PWA-first guest/email/SMS/VK/merge/retention plan. | 2026-07-01; auth code partly implemented, SMS cancelled. | Част. | Нет | Plan snippets vs real package/routes. | `LEGACY_PWA` | `MOVE_TO_LEGACY_PWA`; extract compatibility architecture. |
| `docs/benchmark-competitors.md` | Market benchmark of Matrix reports, depth/price/gaps. | 2026-06-11; research links; report/product. | N/A | Част. | Old NURA price/status embedded. | `FUTURE_PLATFORM_VISION` | `UPDATE_IN_PLACE` as dated research, move to research/. |
| `docs/bot-spec.md` | Giant bot callbacks/screens/payments/Tarot/chat/tasks/data spec. | 2026-06-29; high refs; bot. | Част. | Нет | 390 recurring/PWA delivery/current+future mixed. | `MIXED` | `SPLIT` into Telegram architecture, UX/acceptance, legacy monetization. |
| `docs/bot-spec-pwa-patch.md` | Patch making PWA primary and bot secondary. | 2026-06-09; linked by old docs. | Част. | Нет | Directly reverses Telegram-first. | `LEGACY_PWA` | `MOVE_TO_LEGACY_PWA`. |
| `docs/bot-ux-map.md` | Bot screen map, subscription/Tarot/reports/chat/referral/broadcast states. | 2026-05-28; high refs. | Част. | Нет | 390 subscription and full-report access rules mixed. | `MIXED` | `SPLIT` current 1.0 UX from legacy/1.5. |
| `docs/bot-ux-map-pwa-patch.md` | PWA patch to bot UX, deep links and account linking. | 2026-06-29. | Част. | Нет | PWA-first recovery paths. | `LEGACY_PWA` | `MOVE_TO_LEGACY_PWA`. |
| `docs/brand/nura-universe/README.md` | Large brand/world/visual narrative and asset map. | 2026-07-17; currently low human refs; brand/content. | N/A | Част. | Scope much broader than current roadmap, core tone aligns. | `FUTURE_PLATFORM_VISION` | `SPLIT`: current brand standard vs optional universe vision. |
| `docs/design-system.md` | Theme tokens, typography/components/file map. | 2026-07-09; code-linked. | Част. | Да | Claims one token file while listing additional PWA layers. | `CURRENT_TECHNICAL_DOCUMENTATION` | `UPDATE_IN_PLACE`. |
| `docs/dev-prompts.md` | Old module-by-module implementation prompts with commit instructions. | 2026-06-11; linked by README. | Нет | Нет | Old paths, architecture and forbidden autonomous commit guidance. | `SUPERSEDED` | `MOVE_TO_SUPERSEDED_ARCHIVE`. |
| `docs/engineering/review-video-assembler-v2.md` | Review/test prompt for video assembler. | 2026-05-17; links video tool; isolated content tooling. | Да | N/A | Product roadmap relevance not defined. | `CURRENT_TECHNICAL_DOCUMENTATION` | `KEEP_AS_CURRENT`; owner decides active vs vision placement. |
| `docs/engineering/video-assembler.md` | FFmpeg assembler architecture, scenario schema, CLI, subtitles/GPU. | 2026-05-18; code/tool-linked. | Да | N/A | No product authority claim. | `CURRENT_TECHNICAL_DOCUMENTATION` | `KEEP_AS_CURRENT`. |
| `docs/industry-standard-analysis.md` | Report size/price market benchmark. | 2026-06-30; dated research. | N/A | Част. | Old «current NURA» claims. | `FUTURE_PLATFORM_VISION` | `UPDATE_IN_PLACE` as dated research. |
| `docs/launch-checklist.md` | Historical PWA-era launch plan; explicit superseded banner. | 2026-07-27; links sandbox runbook. | Част. | Нет | Correctly labels itself historical, but README placement misleads. | `SUPERSEDED` | `MOVE_TO_LEGACY_PWA` under acceptance archive. |
| `docs/matrix-algo.md` | Deterministic Matrix calculation positions/formulas/contracts. | 2026-05-15; high code/docs refs. | Да | Да | Some terminology/safety examples need review, algorithm core stable. | `CURRENT_TECHNICAL_DOCUMENTATION` | `UPDATE_IN_PLACE` with tests/evidence. |
| `docs/NURA FORMS SYSTEM.txt` | Three visual/persona forms for short video/HeyGen content. | 2026-05-16; not main docs index. | N/A | Част. | Optional content system presented broadly. | `FUTURE_PLATFORM_VISION` | `MOVE_TO_FUTURE_VISION`. |
| `docs/operations/backup-restore.md` | Disposable PostgreSQL backup/restore proof and limitations. | 2026-07-23; README + tools/tests. | Да | Да | Clearly local/disposable boundary. | `CURRENT_TECHNICAL_DOCUMENTATION` | `KEEP_AS_CURRENT`. |
| `docs/operations/p7a-security-configuration.md` | Redis/auth/env/webhook security config contract. | 2026-07-23; tests. | Да | Да | Dated rollout state should remain labeled. | `CURRENT_TECHNICAL_DOCUMENTATION` | `KEEP_AS_CURRENT`. |
| `docs/operations/p7b-state-b-handoff.md` | Release state machine, activation/recovery/forensics. | 2026-07-23; STATE/README/tests. | Да | N/A | No product scope conflict. | `CURRENT_TECHNICAL_DOCUMENTATION` | `KEEP_AS_CURRENT`. |
| `docs/platform-strategy.md` | ADR PWA as product core, landing-first traffic, channel fallback. | 2026-06-09; many old refs. | Част. | Нет | Opposite of canonical Telegram-first. | `LEGACY_PWA` | `MOVE_TO_LEGACY_PWA`. |
| `docs/pricing.md` | 890 one-time Matrix + 390 monthly Tarot subscription and access table. | 2026-06-22; high refs; code matches legacy. | Да | Нет | «Current/target» labels no longer valid. | `MIXED` | `SPLIT`: retired 390 model + canonical 1.0/1.5 payments. |
| `docs/pricing-vs-report-analysis.md` | 890 value/sections/gap plan. | 2026-06-30; root near-duplicate. | Част. | Част. | Missing image-prompts link; planned/current mixed. | `MIXED` | `MERGE_WITH_ANOTHER_DOCUMENT` into research/report architecture. |
| `docs/prompt-spec.md` | Prompt tone, schemas/examples, file registry and AI service contract. | 2026-05-14; high refs. | Част. | Част. | Wrong filenames/paths; current and ideal contracts mixed. | `MIXED` | `SPLIT` current AI architecture + editorial standard; update paths. |
| `docs/pwa/PWA_IMPLEMENTATION_RULES.md` | Current maintenance rules for legacy PWA files/release metadata. | 2026-07-20; PWA skill/AGENTS refs. | Да | Нет as roadmap | Technically current, product role legacy. | `LEGACY_PWA` | `MOVE_TO_LEGACY_PWA` but keep as active compatibility contract. |
| `docs/pwa/PWA_NORTH_STAR_DESIGN.md` | PWA design direction/status/boundaries. | 2026-07-20; PWA instruction refs. | Да | Нет as roadmap | «North Star» conflicts with no parallel PWA development. | `LEGACY_PWA` | `MOVE_TO_LEGACY_PWA`; rename authority in Stage 2. |
| `docs/pwa/PWA_PAGE_CONTRACTS.md` | Shared shell/pages/access/error/a11y behavior. | 2026-07-20; code-linked. | Да | Нет as primary product | Technically useful compatibility doc. | `LEGACY_PWA` | `MOVE_TO_LEGACY_PWA`. |
| `docs/pwa-spec.md` | Large PWA technical/product spec: manifest, push, install, pages, backend. | 2026-07-09; many refs. | Част. | Нет | Implemented/planned snippets mixed. | `LEGACY_PWA` | `SPLIT`; retain compatibility pieces in legacy archive. |
| `docs/README.md` | Main docs index and source-of-truth notes. | Modified 2026-07-27; high refs; currently dirty baseline. | Част. | Нет | Marks legacy/mixed docs current; missing links; Telegram section appended. | `MIXED` | `UPDATE_IN_PLACE` first in Stage 2 as authority router. |
| `docs/report-spec.md` | Report data, templates, HTML/PDF render, URL/access, sections. | 2026-06-12; high refs. | Част. | Част. | Web delivery mixed with Telegram target; status sections stale. | `MIXED` | `SPLIT` and replace with current reports architecture. |
| `docs/tarot-integration-plan.md` | Four-surface Tarot plan, 390 subscription and 6 spreads. | 2026-06-29; code partly implemented. | Част. | Нет | Plan/current status and old monetization mixed. | `MIXED` | `SPLIT`: implementation history + 1.5 target subset. |
| `docs/tarot-integration-plan-pwa-patch.md` | Patch adding PWA Tarot UI/payment/share. | 2026-06-29. | Част. | Нет | PWA primary subscription flow. | `LEGACY_PWA` | `MOVE_TO_LEGACY_PWA`. |
| `docs/tarot-integration-sessions.md` | 9+ step implementation journal/prompts/status. | 2026-06-11; code has progressed beyond opening baseline. | Нет/Част. | Нет | Begins «no Tarot code», later records implementation. | `MIXED` | `SPLIT` into history; current facts go to implementation status. |
| `docs/telegram-first-sandbox-runbook.md` | Local disposable PostgreSQL/Redis Telegram-first acceptance and opt-in external smoke. | Untracked baseline, 2026-07-27; linked by launch/tests. | Да | Да | Correctly avoids production claim. | `CURRENT_IMPLEMENTED_STATE` | `KEEP_AS_CURRENT`; move to acceptance/operations. |
| `docs/telegram-first-v1-readiness-review.md` | Dated final-readiness review: local PASS evidence, external/production NO-GO, cumulative diff inventory and newly found startup/safe-suite gaps. | Создан другим процессом в shared worktree 2026-07-28 во время аудита; current worktree evidence. | Да/Част. | Да | Фраза «readiness documentation is complete» конфликтует с найденным semantic drift; сам документ позже снижает stage до PARTIAL. | `CURRENT_IMPLEMENTED_STATE` | `KEEP_AS_CURRENT` as dated acceptance evidence; не считать product/docs authority. |
| `docs/tone-of-voice.md` | NURA voice, forbidden wording, channel examples, safety tone. | 2026-05-26; high refs. | Част. | Да | Missing audit link; prompt runtime mapping stale. | `CURRENT_TECHNICAL_DOCUMENTATION` | `UPDATE_IN_PLACE` as editorial standard. |
| `docs/two-layer-architecture.md` | User/kitchen report layers and original implementation plan. | 2026-06-11; code partly follows different paths. | Част. | Да | Future wording for implemented features. | `CURRENT_TECHNICAL_DOCUMENTATION` | `UPDATE_IN_PLACE` into current report architecture. |
| `docs/анализ структуры, глубины и ценностного предложения платных отчётов по «Матрице судьбы» на рынке России и СНГ.pdf` | 22-page WeasyPrint market/report structure research with sources. | 2026-05-16; not code-linked; report research. | N/A | Част. | Source appendix includes low-quality/unrelated results; treat as research only. | `FUTURE_PLATFORM_VISION` | `KEEP_AS_CURRENT` as dated research with caveat. |
| `docs/Все_расклады_и_разборы,_которыми_я_занимаюсь.pdf` | Canonical retained copy of 46-page image-based spread/source material. | 2026-06-17 mtime; SHA matches root duplicate. | N/A | Част. | No extractable text/authority metadata. | `FUTURE_PLATFORM_VISION` | `KEEP_AS_CURRENT` in research/content source; add provenance later. |
| `docs/исследование рынка.md` | Telegram-bot/Matrix market, pricing, audience/problems/strategy. | 2026-05-14; linked by agent prompts/benchmark. | N/A | Част. | Research recommendations can conflict with later canonical decisions. | `FUTURE_PLATFORM_VISION` | `KEEP_AS_CURRENT` as dated research. |
| `docs/Карта вечнозелёного спроса для Nura_ Конфигурация Viral Screening Radar в нише самопознания на TikTok.pdf` | 23-page acquisition/hashtag research. | 2026-05-21; research. | N/A | Част. | Platform data/links decay; not product contract. | `FUTURE_PLATFORM_VISION` | `KEEP_AS_CURRENT` as dated research. |
| `frontend/pwa/app/AGENTS.md` | PWA local source/safety/QA instruction. | 2026-07-13; mojibake; linked by PWA docs/skill. | Да | N/A | Product role not stated as legacy compatibility. | `CURRENT_TECHNICAL_DOCUMENTATION` | `UPDATE_IN_PLACE` later with legacy boundary. |
| `nura_app/templates/reports/AGENTS.md` | Report rendering/design/QA instruction. | 2026-07-13; mojibake; nested rule. | Да | Да | Encoding damage only. | `CURRENT_TECHNICAL_DOCUMENTATION` | `UPDATE_IN_PLACE` encoding/navigation only. |

## B. Shared profiles for ancillary instruction/generated files

Every file in sections C-H is individually listed and inherits all fields from its profile.

| Profile | Предполагаемое назначение / фактическое содержание | Актуальность и refs | Подсистемы | Код / Spec | Противоречия | Статус / действие |
|---|---|---|---|---|---|---|
| `SKILL-ACTIVE` | NURA-specific Codex workflow/safety/QA instructions. | 2026-07-13; invoked by AGENTS; active. | agent workflow, design/docs/PWA/reports | Код Да; Spec N/A/Да | Нет material product claims. | `CURRENT_TECHNICAL_DOCUMENTATION` / `KEEP_AS_CURRENT` |
| `DESIGN-SYNC` | Generated/design handoff conventions and component prompt contracts. | 2026-06-26..07-04; path-based refs; active design tooling. | UI/design | Код Част.; Spec N/A | May lag actual tokens/components. | `CURRENT_TECHNICAL_DOCUMENTATION` / `UPDATE_IN_PLACE` through design-sync workflow |
| `GITHUB-INSTRUCTION` | GitHub agent roles and path-specific coding/testing/docs/security instructions. | 2026-06-11; tool-consumed, low human refs. | engineering workflow | Код N/A; Spec N/A | Overlaps root AGENTS; root rules must win. | `CURRENT_TECHNICAL_DOCUMENTATION` / `KEEP_AS_CURRENT` |
| `OPENCODE-ACTIVE` | Generic role/command/skill instructions used by OpenCode. | 2026-04..06; generic, not product truth. | engineering tooling | Код N/A; Spec N/A | May duplicate Codex rules; no product authority. | `CURRENT_TECHNICAL_DOCUMENTATION` / `KEEP_AS_CURRENT` |
| `OPENCODE-PLAN` | Admin upgrade implementation plan, not current product contract. | 2026-06-30; plan marker. | admin | Код Част.; Spec N/A | Planned/current mixed. | `MIXED` / `SPLIT` or archive after verification |
| `OPENCODE-NESTED` | NURA-local specialized agent instruction not byte-identical to root set. | 2026-04..07; tool-specific. | engineering/product/design | Код N/A; Spec N/A | Root vs nested authority not documented. | `CURRENT_TECHNICAL_DOCUMENTATION` / `KEEP_AS_CURRENT` pending OD-10 |
| `OPENCODE-DUPLICATE` | Byte-identical duplicate of same basename in root `.opencode/agents/`. | 2026-04-30; exact SHA duplicate. | tooling | N/A | Two candidate locations. | `SUPERSEDED` / `MERGE_WITH_ANOTHER_DOCUMENT` after OD-10 |
| `GRAPH-CURRENT` | Current generated Graphify human report; describes extracted code graph, not normative architecture. | mtime 2026-07-26; generated. | whole code graph | Code snapshot; Spec N/A | Identical to two dated copies. | `CURRENT_IMPLEMENTED_STATE` / `KEEP_AS_CURRENT` generated output |
| `GRAPH-SNAPSHOT` | Dated generated Graphify report snapshot. | 2026-06-17..07-26; generated/history. | whole code graph | Historical snapshot; Spec N/A | Stale by design; three exact duplicates. | `SUPERSEDED` / `MOVE_TO_SUPERSEDED_ARCHIVE` or retention policy |

## C. NURA Codex skills (5)

| Путь | Profile |
|---|---|
| `.agents/skills/nura-design-system/SKILL.md` | `SKILL-ACTIVE` |
| `.agents/skills/nura-docs-state-graphify/SKILL.md` | `SKILL-ACTIVE` |
| `.agents/skills/nura-pwa-visual-qa/SKILL.md` | `SKILL-ACTIVE` |
| `.agents/skills/nura-report-render-qa/SKILL.md` | `SKILL-ACTIVE` |
| `.agents/skills/nura-safe-change/SKILL.md` | `SKILL-ACTIVE` |

## D. Design sync docs (9)

| Путь | Profile |
|---|---|
| `.design-sync/conventions.md` | `DESIGN-SYNC` |
| `.design-sync/ds-bundle/README.md` | `DESIGN-SYNC` |
| `.design-sync/ds-bundle/components/Actions/Button/index.prompt.md` | `DESIGN-SYNC` |
| `.design-sync/ds-bundle/components/Cards/ArcaneDisplay/index.prompt.md` | `DESIGN-SYNC` |
| `.design-sync/ds-bundle/components/Cards/Card/index.prompt.md` | `DESIGN-SYNC` |
| `.design-sync/ds-bundle/components/Cards/DayCard/index.prompt.md` | `DESIGN-SYNC` |
| `.design-sync/ds-bundle/components/Cards/PhotoCard/index.prompt.md` | `DESIGN-SYNC` |
| `.design-sync/ds-bundle/components/Layout/AppHeader/index.prompt.md` | `DESIGN-SYNC` |
| `.design-sync/ds-bundle/components/Layout/TabBar/index.prompt.md` | `DESIGN-SYNC` |

## E. GitHub agent/instruction docs (9)

| Путь | Profile |
|---|---|
| `.github/agents/nura.agent.md` | `GITHUB-INSTRUCTION` |
| `.github/agents/planner.agent.md` | `GITHUB-INSTRUCTION` |
| `.github/agents/reviewer.agent.md` | `GITHUB-INSTRUCTION` |
| `.github/agents/security.agent.md` | `GITHUB-INSTRUCTION` |
| `.github/instructions/docs.instructions.md` | `GITHUB-INSTRUCTION` |
| `.github/instructions/frontend.instructions.md` | `GITHUB-INSTRUCTION` |
| `.github/instructions/infrastructure.instructions.md` | `GITHUB-INSTRUCTION` |
| `.github/instructions/python.instructions.md` | `GITHUB-INSTRUCTION` |
| `.github/instructions/tests.instructions.md` | `GITHUB-INSTRUCTION` |

## F. Root OpenCode docs (38)

Все строки, кроме указанного plan, имеют profile `OPENCODE-ACTIVE`.

| Путь | Profile |
|---|---|
| `.opencode/agents/ai-engineer.md` | `OPENCODE-ACTIVE` |
| `.opencode/agents/api-tester.md` | `OPENCODE-ACTIVE` |
| `.opencode/agents/backend-architect.md` | `OPENCODE-ACTIVE` |
| `.opencode/agents/code-reviewer.md` | `OPENCODE-ACTIVE` |
| `.opencode/agents/database-optimizer.md` | `OPENCODE-ACTIVE` |
| `.opencode/agents/devops-automator.md` | `OPENCODE-ACTIVE` |
| `.opencode/agents/frontend-developer.md` | `OPENCODE-ACTIVE` |
| `.opencode/agents/security-engineer.md` | `OPENCODE-ACTIVE` |
| `.opencode/agents/software-architect.md` | `OPENCODE-ACTIVE` |
| `.opencode/agents/technical-writer.md` | `OPENCODE-ACTIVE` |
| `.opencode/agents/workflow-architect.md` | `OPENCODE-ACTIVE` |
| `.opencode/commands/build-fix.md` | `OPENCODE-ACTIVE` |
| `.opencode/commands/plan.md` | `OPENCODE-ACTIVE` |
| `.opencode/commands/security.md` | `OPENCODE-ACTIVE` |
| `.opencode/commands/tdd.md` | `OPENCODE-ACTIVE` |
| `.opencode/plans/ADMIN_UPGRADE_PLAN.md` | `OPENCODE-PLAN` |
| `.opencode/skills/aiogram/SKILL.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/alembic/SKILL.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/async-python/SKILL.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/celery/SKILL.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/context-budget/SKILL.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/error-handling/SKILL.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/fastapi-patterns/SKILL.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/graphify/SKILL.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/graphify/references/add-watch.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/graphify/references/exports.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/graphify/references/extraction-spec.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/graphify/references/github-and-merge.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/graphify/references/hooks.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/graphify/references/query.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/graphify/references/transcribe.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/graphify/references/update.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/pdf/SKILL.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/pytest/SKILL.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/security-review/SKILL.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/sqlalchemy/SKILL.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/tdd-workflow/SKILL.md` | `OPENCODE-ACTIVE` |
| `.opencode/skills/ui-ux-pro-max/SKILL.md` | `OPENCODE-ACTIVE` |

## G. Nested OpenCode agent docs (40)

Exact duplicates of root agents use `OPENCODE-DUPLICATE`; all other rows use `OPENCODE-NESTED`.

| Путь | Profile |
|---|---|
| `nura_app/.opencode/agents/AGENTS_INDEX.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/accessibility-auditor.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/ai-engineer.md` | `OPENCODE-DUPLICATE` |
| `nura_app/.opencode/agents/analytics-reporter.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/api-tester.md` | `OPENCODE-DUPLICATE` |
| `nura_app/.opencode/agents/backend-architect.md` | `OPENCODE-DUPLICATE` |
| `nura_app/.opencode/agents/behavioral-nudge-engine.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/behavioral-ui-specialist.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/bot-spec.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/codebase-onboarding-engineer.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/code-reviewer.md` | `OPENCODE-DUPLICATE` |
| `nura_app/.opencode/agents/compliance-auditor.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/content-creator.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/Cross-Platform Adaptation Specialist.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/database-optimizer.md` | `OPENCODE-DUPLICATE` |
| `nura_app/.opencode/agents/design-implementer.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/design-system-guardian.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/devops-automator.md` | `OPENCODE-DUPLICATE` |
| `nura_app/.opencode/agents/feedback-synthesizer.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/frontend-developer.md` | `OPENCODE-DUPLICATE` |
| `nura_app/.opencode/agents/growth-hacker.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/incident-response-commander.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/infrastructure-maintainer.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/minimal-change-engineer.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/Mobile Responsive Design Expert.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/Mobile Web  PWA Specialist.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/mobile-pwa-tma-specialist.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/performance-benchmarker.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/product-manager.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/security-engineer.md` | `OPENCODE-DUPLICATE` |
| `nura_app/.opencode/agents/seo-specialist.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/software-architect.md` | `OPENCODE-DUPLICATE` |
| `nura_app/.opencode/agents/sre-site-reliability-engineer.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/technical-writer.md` | `OPENCODE-DUPLICATE` |
| `nura_app/.opencode/agents/test-results-analyzer.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/trend-researcher.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/ui-designer.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/ux-architect.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/wcag-auditor.md` | `OPENCODE-NESTED` |
| `nura_app/.opencode/agents/workflow-architect.md` | `OPENCODE-DUPLICATE` |

## H. Graphify Markdown reports (20)

| Путь | Profile |
|---|---|
| `graphify-out/GRAPH_REPORT.md` | `GRAPH-CURRENT` |
| `graphify-out/2026-06-17/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-06-18/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-06-19/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-06-21/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-06-22/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-06-24/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-06-25/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-06-26/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-06-28/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-06-29/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-06-30/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-07-01/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-07-02/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-07-03/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-07-04/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-07-06/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-07-09/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-07-14/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |
| `graphify-out/2026-07-26/GRAPH_REPORT.md` | `GRAPH-SNAPSHOT` |

## Coverage conclusion

Inventory rows: A=59, C=5, D=9, E=9, F=38, G=40, H=20; total **180**. No source file was moved, renamed, archived, deleted or edited during classification.
