# NURA Tarot Integration — Historical Implementation Record

## 1. Authority and historical scope

This document preserves how the Tarot implementation plan and its execution notes evolved. It is history/evidence, not a live specification, task queue or current-status source.

Use:

- [NURA 1.0/1.5 Product Specification](product/NURA_1_0_1_5_PRODUCT_SPEC.md) for target scope;
- [Current implementation status](implementation/current-status.md) and [current Tarot/compatibility/referral map](tarot-integration-plan.md) for current evidence;
- [Documentation migration decisions](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md) for DM-03/DM-04;
- code, migrations and tests for implemented behavior.

The previous document combined executable prompts, proposed product rules and completion notes. Those instructions are not retained as runnable tasks because many paths, signatures and assumptions have been superseded. Their meaningful chronology, decisions, milestones and known limitations are preserved below.

## 2. Baseline chronology

Dates and commits are repository evidence where available. A commit indicates that a change entered Git history; it does not prove external acceptance or production deployment.

| Date / commit | Historical phase | What the historical material said or attempted | Later/current status | Authoritative destination |
|---|---|---|---|---|
| 2026-05-24 / `ed4c91a` | Initial Tarot product plan | Proposed four surfaces, seven spreads, 390 ₽ subscription, daily/weekly/monthly delivery, compatibility virality and separate Matrix/Tarot products | Product model is superseded; parts of implementation followed it | Canonical product spec; current domain map |
| 2026-05-24 / `809bec3`, `dbf8aee` | Data/payment/AI foundation | Tarot entitlement/payment fields and early AI methods appeared | Fields and legacy flows remain; target entitlement differs | Current code; pricing/payment docs |
| 2026-05-25 / `9b7404a` | First known session-journal snapshot | Opened with “codebase contains no Tarot logic” and nine imperative steps | The statement was already stale relative to 2026-05-24 commits and later became materially false | This historical record; current status |
| 2026-05-27 / `0490a12`, `1f5d3ec`, `e295b26`, `3253fce` | Bot and prompt expansion | Added Tarot menu/paywalls/FSM, AI daily interpretation, question/yes-no and additional prompts | Much of the runtime surface remains, with later refactors | Current domain map and runtime consumers |
| 2026-05-27 / `a0dd732`, `33c1d3d` | Compatibility access/virality | Added one-use compatibility marker, legacy subscription bypass and sharing ideas | Compatibility remains reachable and visible, but belongs to 1.5B | Current domain map; canonical §32.3 |
| 2026-05-28 / `a5520c9`, `a79da26`, `035ecf2`, `47b70d1` | UX/prompt formatting sessions | Refactored menu, rewrote several prompts, added HTML formatting and animated loading | Loading survives; current formatting and prompt consumers have changed | Current code and prompt registry |
| 2026-05-28 / `e107b1f`, `d2e19e9`, `3e02bc7` | Compatibility V2 | Added names/relation type, two-layer output, new prompt/template and sharing/report refinements | Core flow remains; privacy/product acceptance was not established | Current domain map; report/prompt docs |
| 2026-05-29 / `eba8bdd`, `b161993` | Personalization/scheduler | Personalized daily text and adjusted scheduler | Later durable daily service replaced the authoritative on-demand lifecycle; old producers are dormant | Daily application service; current domain map |
| 2026-06-09 / `bb4ab76` | PWA daily card | Added PWA daily API/screen | PWA remains legacy compatibility and now shares durable daily service | DM-03; current domain map |
| 2026-06-09 / `32c7563` | Referral foundation | Added reward table, `/start ref_*` and profile link | Registration ledger exists; reward economics/activation remain absent | Current domain map; canonical §32.1 |
| 2026-06-09 / `9b8623a` | Compatibility share card | Added generated share image | Reachable current sharing surface, not 1.5B acceptance | Current compatibility implementation |
| 2026-06-10 / `644fe8c`, `cc4dc65` | Spread fixes | Fixed keyboard/runtime issues and PWA spread result behavior | Current routes remain, with client access divergence | Current code/tests |
| 2026-06-29 / `3f9f4d7`, `7d44807` | PWA Tarot expansion/retention work | Unified arcana helpers, added weekly/monthly tasks and expanded PWA UX | Weekly/monthly are scheduled for legacy Tarot users; durable expanded history is still absent | Current domain map; legacy PWA archive |
| 2026-07-04 / `0d3e39a`, `4635647` | AI loop hardening | Added Tarot verifier/caching/degradation work | Reachable resilience code exists; not external content acceptance | Prompt contracts and current code |
| 2026-07-13 / `bdf9b09` | Tarot v2.1/mini-spread | Integrated an approved-at-that-time content iteration and PWA mini-spread | “Approved” was local historical context, not canonical 1.5 product acceptance | Current prompt consumers; owner-approved future set required |
| 2026-07-24 / `501ef3e` | General Telegram attribution | Added durable `a_*` campaign attribution | Separate from `ref_*` referral economics | Attribution service/current bot docs |
| 2026-07-26 / `ba87e04` | Durable free daily card | Added `DailyTarotDraw`, application/repository/timezone lifecycle and replay behavior | Current authoritative daily-card implementation | Current domain map; local acceptance evidence |
| 2026-07-28 / `7cc1122` | Documentation authority migration | Marked both Tarot documents mixed and routed target/current authority | Stage 2B now completes semantic separation | This record and current domain map |

## 3. Initial assumptions

### 3.1 The “no Tarot code” opening statement

The first known session-journal snapshot stated that the codebase contained no Tarot logic, the bot had no Tarot handlers/buttons and payments supported only a generic 390 ₽ subscription. This must be preserved as a historical claim because it motivated the step plan.

It must not be repeated as current fact. Git history shows Tarot/payment/AI changes on 2026-05-24, before the first known 2026-05-25 journal commit. Therefore the opening baseline was incomplete or stale even at its first committed snapshot. Subsequent May–July commits added handlers, PWA routes, prompts, tasks, compatibility/referral foundations and durable daily persistence.

### 3.2 Original architecture assumptions

The original plan treated four surfaces as one Tarot launch:

- landing page;
- Telegram bot;
- report page;
- PWA.

It also treated Matrix 890 ₽ and recurring Tarot 390 ₽ as independent products and used compatibility/sharing as a subscription-growth mechanism. These assumptions explain current legacy code, but they no longer govern the roadmap:

- Telegram-first is accepted;
- PWA is legacy compatibility under DM-03;
- NURA 1.0 includes only the free daily card from the Tarot domain;
- expanded Tarot belongs to 1.5A;
- compatibility and referral belong to 1.5B;
- target 1.5 uses gift/399 ₽ access without baseline auto-renew, not the old 390 ₽ recurring model.

### 3.3 Nine steps became twelve

The journal title said “9 steps”, then added Steps 10–12 for prompt rewriting, formatting and loading animation. This is retained as evidence of an evolving execution log, not a stable delivery plan.

## 4. Implemented milestones

### 4.1 Step 1 — data, payments and configuration

Historical intent:

- add Tarot subscription fields;
- add payment type;
- add 390 ₽ Tarot and 890 ₽ Matrix prices;
- route payment activation.

Current reconciliation:

- `User.tarot_subscription`, expiry and `Payment.payment_type` exist;
- `has_matrix` and compatibility fields exist;
- legacy 390 ₽ checkout/recurring code exists;
- dedicated 890 ₽ full-matrix checkout was later hardened independently;
- the legacy model is not the canonical 1.5 entitlement.

### 4.2 Steps 2–4 — prompts, bot navigation and AI consumers

Historical intent:

- create daily, weekly and question prompts;
- add Tarot menu/FSM/router;
- calculate daily/spread cards;
- integrate matrix context and subscription checks.

Implemented milestones:

- Tarot router is registered;
- daily/weekly/question and additional spread callbacks exist;
- Telegram and PWA prompt consumers exist;
- matrix-aware AI helper paths exist;
- legacy gates and paywalls exist.

Later changes:

- the authoritative daily lifecycle moved to `DailyTarotApplicationService` with durable persistence;
- the current daily algorithm is date-based and optionally personalized by center archetype, not the journal's original DOB digit algorithm;
- current question prompt/consumer contracts diverge between Telegram and PWA;
- current expanded-Tarot access differs between clients.

### 4.3 Step 5 — scheduled daily card

Historical intent was a 09:15 daily Tarot Beat task for Tarot subscribers, alongside existing insights.

Current reconciliation:

- two daily Tarot notification producers are registered but explicitly dormant and absent from Beat;
- weekly and monthly legacy Tarot tasks are scheduled;
- on-demand daily card uses the durable application service;
- dated local acceptance excludes scheduled daily push.

### 4.4 Step 6 and Steps 10–12 — presentation, prompts and loading

The journal later marked prompt rewriting, HTML formatting and animated loading complete on 2026-05-28.

Preserved historical value:

- safety/tone moved away from fatal prediction language;
- user-facing loading was added;
- escaping/HTML rendering became an explicit concern;
- multiple spread prompts were rewritten around psychological qualities and actions.

Current reconciliation:

- `animated_loading` remains used by Tarot handlers;
- safe Telegram escaping/splitting is current, but the historical `format_tarot_result` API described in the journal is no longer the current formatting contract;
- not every handler uses the same system instruction or output schema;
- prompt-file presence and a historical “completed” marker do not prove current acceptance.

### 4.5 Step 7 — landing

The journal contained a large imperative HTML/CSS prompt for a Tarot-first landing with a third 390 ₽ product. That content is preserved here only by classification:

`HISTORICAL / SUPERSEDED — legacy recurring Tarot landing concept`

It is not a current task or target. Landing/product copy must follow the canonical spec and the current design/landing workflow, not this journal.

### 4.6 Step 8 — report Tarot block

The journal planned to replace a yearly-arcana placeholder with daily Tarot data in report rendering. Later code added daily arcana helpers and report integration, but report rendering/current delivery has its own accepted authority.

Current destination: [Report system specification](report-spec.md). The old step does not define current report data, retention or delivery.

### 4.7 Step 9 — “final integration” checklist

The old checklist mixed intended signatures, filenames, callbacks, landing changes, payment behavior and test/autofix instructions. It is not safe to rerun:

- several names/signatures differ from current code;
- some requested behavior is now legacy or contradicts canonical target;
- it requested broad autofix and full tests outside the scope of this history record;
- it treated 390 ₽ subscription and four-surface launch as current product rules.

Its lasting value is the dependency idea—data/prompts before consumers and consumers before system integration—not its commands or acceptance claims.

## 5. Superseded statements

| Old statement or plan | Historical baseline | Current status | Destination |
|---|---|---|---|
| “The codebase contains no Tarot logic” | First known journal snapshot, 2026-05-25 | Stale even relative to 2026-05-24 Git history; extensively false now | Current status/domain map |
| “Telegram has no Tarot button/handler” | Initial assumption | Tarot router and buttons are registered and visible | Current bot code/map |
| “PWA Tarot is the implemented primary surface” | Old four-surface plan | PWA remains reachable but is legacy compatibility | DM-03; legacy PWA archive |
| “390 ₽/month Tarot is a current product” | May/June legacy product model | Reachable legacy entitlement; not NURA 1.0 and not target 399 ₽ access | Pricing/payment docs |
| “Matrix and Tarot are permanently independent products” | Old plan | Not current authority; 1.5 gift/paid access bundles an approved value set after full-report purchase | Canonical §§24–29 |
| “Seven spreads are the accepted set” | Old plan | Current code has a different/more fragmented set; canonical exact 1.5A set remains pending | Canonical §28 and owner decision |
| “Daily card changes at 00:00 MSK because plan says so” | Old plan | Current durable service derives a local date and normally falls back to configured Europe/Moscow; code, not plan, proves mechanics | Daily application/timezone service |
| “Daily scheduler sends every day” | Steps 5/9 | Daily producers are registered but not scheduled; weekly/monthly remain scheduled | Current `core/tasks.py` |
| “All six handlers use historical formatting helper” | Step 11 completion note | Current handlers use escaping/splitting/loading; historical helper API is no longer current | Current handler/formatting code |
| “Compatibility/referral virality is ready product behavior” | Old growth ideas | Compatibility is early reachable 1.5B; referral is partial registration foundation | Current domain map/canonical §32 |
| “Local tests/final checklist prove launch” | Old Step 9 framing | Local tests are not external sandbox or production proof | Acceptance index |

## 6. Current destinations

| Question | Current authority |
|---|---|
| What is implemented now? | [Current Tarot, compatibility and referral map](tarot-integration-plan.md), then code/tests |
| What belongs to NURA 1.0/1.5? | [Canonical product specification](product/NURA_1_0_1_5_PRODUCT_SPEC.md) |
| Why are early 1.5 features still in code but supposed to be hidden? | DM-04 in [migration decisions](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md) |
| What is the current bot visibility? | [Bot UX map](bot-ux-map.md) and current keyboards/handlers |
| What is legacy 390 ₽ access? | [Pricing map](pricing.md) and [payment audit](audits/PAYMENT_FLOW_AUDIT.md) |
| What prompt files/consumers are current? | [Runtime prompt contracts](prompt-spec.md) plus the current domain map |
| What report artifacts/deletion gaps exist? | [Report system specification](report-spec.md) |
| What local/external acceptance exists? | [Acceptance index](acceptance/README.md) and dated evidence |
| What was moved/classified in Stage 2A? | [Migration file map](reconciliation/2026-07-28/MIGRATION_FILE_MAP.md) |

## 7. Historical gaps and limitations

### 7.1 What was never established by the journal

- an approved NURA 1.5 spread set;
- canonical Tarot history retention;
- a canonical entitlement model;
- compatibility price/inclusion and consent lifecycle;
- referral reward economics, activation and anti-fraud;
- legacy subscriber migration/disposition;
- external Telegram/AI/YooKassa acceptance;
- production deployment/usage evidence.

### 7.2 Unique-content retention

| Old content category | Treatment in this consolidation | Evidence / destination |
|---|---|---|
| Meaningful chronology | Preserved as dated commit/phase table | §2 |
| Architectural motivation | Preserved: four surfaces, separate products, dependency order | §§3–4 |
| Completed implementation milestones | Preserved and reconciled with current code | §4 |
| Old “no code” baseline | Preserved as an explicitly stale historical claim | §§3.1 and 5 |
| Imperative code-generation prompts | Correctly removed as runnable instructions; summarized by intent | §4 |
| Exact old code snippets/signatures | Correctly removed where superseded | Current code is authority |
| Legacy 390 ₽ commercial rules | Redirected and classified, not retained as target | Pricing/payment docs |
| PWA-first normative language | Redirected to legacy compatibility | DM-03 and legacy PWA archive |
| Speculative landing/growth copy | Correctly removed from live guidance | Canonical target/design workflow |
| Prompt tone/formatting rationale | Preserved as historical milestone | §4.4; prompt contracts |
| Broad test/autofix commands | Correctly removed from history authority | Project validation rules/current task scope |
| Current technical details | Redirected to the current domain map | `tarot-integration-plan.md` |

No meaningful implementation chronology is intentionally lost. Verbatim multi-page prompts and stale task commands were removed because they obscured authority and could recreate superseded behavior.

### 7.3 Evidence boundary

This history was reconstructed from Git log, the previous two Tarot documents, current code, static tests and dated documentation evidence. It does not claim that every historical commit was deployed, used by real customers or accepted in an external sandbox.

## 8. References

- [Current Tarot, compatibility and referral map](tarot-integration-plan.md)
- [NURA 1.0/1.5 Product Specification](product/NURA_1_0_1_5_PRODUCT_SPEC.md)
- [Current implementation status](implementation/current-status.md)
- [Documentation migration decisions](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md)
- [Documentation router](README.md)
- [Bot specification](bot-spec.md)
- [Bot UX map](bot-ux-map.md)
- [Pricing and access map](pricing.md)
- [Payment flow audit](audits/PAYMENT_FLOW_AUDIT.md)
- [Runtime prompt contracts](prompt-spec.md)
- [Report system specification](report-spec.md)
- [Acceptance index](acceptance/README.md)
- [Dated Telegram-first v1 readiness evidence](acceptance/evidence/telegram-first-v1-readiness-review.md)
- [Stage 2A migration file map](reconciliation/2026-07-28/MIGRATION_FILE_MAP.md)
