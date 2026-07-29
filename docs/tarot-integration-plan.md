# NURA Tarot, Compatibility and Referral — Current and Target Map

## 1. Authority and scope

This document is an evidence-backed map of the current Tarot, compatibility and referral implementation with a crosswalk to the approved NURA 1.0/1.5 target. It is not a product specification and does not approve pricing, rollout, retention or feature visibility.

The filename `tarot-integration-plan.md` is retained for link stability. The document is no longer an imperative implementation plan. Historical execution context is preserved in [Tarot integration historical record](tarot-integration-sessions.md).

Authority order:

1. [NURA 1.0/1.5 Product Specification](product/NURA_1_0_1_5_PRODUCT_SPEC.md) is the only canonical target.
2. Reachable code, models, migrations, configuration and tests establish current implementation.
3. [Current implementation status](implementation/current-status.md) is a compact evidence-backed mirror, not a specification.
4. [Documentation migration decisions](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md), especially DM-03 and DM-04, govern legacy PWA and early 1.5 visibility.
5. [Bot specification](bot-spec.md), [Bot UX map](bot-ux-map.md), [Pricing and access map](pricing.md) and [Runtime prompt contracts](prompt-spec.md) provide accepted cross-document boundaries.
6. Old plans and session statements are historical evidence only.

Current implementation does not prove approved release scope. A registered handler, visible button, prompt file or local test is not production acceptance.

## 2. Status legend

- `CURRENT — IMPLEMENTED` — reachable current behavior supported by code and static test evidence.
- `TARGET — NURA 1.0` — canonical 1.0 contract; target does not prove implementation.
- `TARGET — NURA 1.5` — canonical 1.5A or 1.5B contract.
- `IMPLEMENTATION GAP` — required target or safety/consistency behavior is absent or contradicted by current wiring.
- `LEGACY COMPATIBILITY` — reachable behavior from the previous PWA/390 ₽ product model, not the current roadmap.
- `HISTORICAL / SUPERSEDED` — dated plan, completion statement or idea that is not live authority.
- `OWNER DECISION PENDING` — a genuinely unresolved product, migration, retention or rollout parameter.
- `OUT OF SCOPE` — outside this documentation-only write session.
- `EVIDENCE BOUNDARY` — repository evidence does not prove external sandbox or production behavior.

For an early 1.5 function currently visible in the primary path, the required classification is:

`IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04`

DM-04 itself is an accepted owner decision, not a pending question.

## 3. Current domain overview

| Capability | Current implementation | NURA 1.0 target | NURA 1.5 target | Legacy | Visibility |
|---|---|---|---|---|---|
| Daily Tarot card | Durable per-user/per-local-date result shared by Telegram and PWA | Free card after mini; same result within product day | Remains available | PWA is a compatibility client | Visible through main Tarot entry and PWA |
| Weekly focus | Telegram/PWA generation plus scheduled subscriber task; no durable reading history | No | 1.5A regular value and approved spread set | Uses 390 ₽ Tarot gate | Visible behind Tarot menu/paywall |
| Monthly compass | Current “Энергия/Портал месяца” handler and scheduled subscriber task; semantics do not equal the canonical monthly compass contract | No | 1.5A | Uses 390 ₽ Tarot gate and legacy PWA | Visible behind Tarot menu/paywall |
| Question reading | Telegram FSM and PWA API consumers; access differs by client; no durable reading row | No | 1.5A approved set | 390 ₽ Telegram gate; PWA exposes it free | Visible |
| Mini-spread | PWA API consumer only | No | Not canonical by name; may only enter an owner-approved 1.5 set | Legacy PWA | Direct PWA API/UI surface |
| Other expanded spreads | Spheres, doubles/twins, portal, blocks and yes/no handlers/prompts exist | No | Exact accepted 1.5A set pending | 390 ₽ and PWA assumptions | Visible or directly reachable |
| Expanded Tarot history | No durable `TarotReading` model or retrieval UX found; only daily draw is durable | No | Saved readings required in 1.5A | PWA browser cache is not canonical history | Not available as a profile history |
| Compatibility | Registered Telegram FSM, matrix calculation, AI analysis, latest report persistence and sharing | No | 1.5B | Access coupled to `has_matrix`, premium/Tarot 390 states and web report artifacts | Main-menu visible |
| Referral | `/start ref_*`, one-time inviter assignment, registration reward row and profile link | No | 1.5B | Early foundation predates target economics | Profile visible; deep link reachable |
| Gift access | No canonical entitlement implementation | No | 1.5A, 30 days after eligible full-report purchase, no auto-charge | None | Not available |
| Legacy premium/Tarot access | User flags, 390 ₽ checkouts, saved-method assumptions and recurring task exist | No | Not the 399 ₽ target | Yes | Paywalls/profile/PWA remain reachable |
| PWA Tarot | Daily card and multiple spread endpoints/UI exist | Not the primary 1.0 client | Not a target product surface by itself | Yes, under DM-03 | Reachable legacy web client |

## 4. Daily Tarot card — current contract

### 4.1 Entry and eligibility

`CURRENT — IMPLEMENTED`

- Telegram: `bot/handlers/tarot.py` handles `tarot_daily_card` through the registered Tarot router.
- PWA: `GET /api/v1/tarot/daily-card` uses the same channel-neutral application service and is rate-limited.
- An active user with a stored birth date can request the result.
- Access is independent of `subscription_status`, `tarot_subscription`, the chat quota and full-report payment.
- The main menu exposes a generic `🌒 Таро` entry, then the Tarot menu exposes the free card. A dedicated `/tarot` command from the canonical navigation is not present in current bot command wiring.

The free daily card is the only Tarot function in canonical NURA 1.0. It is not part of the legacy 390 ₽ expanded-Tarot entitlement.

### 4.2 Product day and timezone

The application resolves a local date from an aware UTC timestamp. It accepts a valid stored IANA timezone when available and otherwise uses `settings.default_daily_tarot_timezone`; the current default is `Europe/Moscow`.

The mapped `User` model has no persisted `timezone` column, so current repository-backed users normally fall back to the configured Moscow timezone. The selected timezone name is snapshotted on the draw row. The same UTC instant can therefore map to different local dates if a future/adapted user object supplies another valid timezone, but no current user-facing timezone management was found.

This is current implementation evidence. The canonical card contract requires one result in the established daily period; it does not by itself prove the current timezone mechanics.

### 4.3 Selection and persistence

- Card selection is deterministic, not random.
- The base card is derived from the digits of `DDMMYYYY`, reduced to 1–22.
- If `main_archetype_number` exists, the service combines the daily number with that center archetype and reduces again.
- `DailyTarotDraw` stores user, local date, timezone snapshot, lifecycle state, selected card, interpretation, attempt/error data and timestamps.
- A database uniqueness constraint on `(user_id, local_date)` enforces one row per user/product day.
- A repeated successful opening returns the saved card and saved interpretation without a new AI call.

### 4.4 Generation, retry and delivery

- A repository claim moves a pending/retryable/stale row to `generating` and prevents concurrent duplicate generation.
- Provider failure is retryable; invalid or empty content is non-retryable under the current error classification.
- Retry retains the already selected card.
- Telegram renders the saved interpretation as escaped HTML and splits oversized messages safely.
- PWA maps the same durable result to a structured response with card metadata and date label.
- Static tests cover same-day replay, concurrent requests, retry, incomplete profiles, timezone boundaries, DST fallback and persistence rejection.

Two older daily notification producers remain registered in `core/tasks.py`, but neither is present in the current Beat schedule. They use process-local caches and do not use `DailyTarotApplicationService`; the code explicitly marks them dormant until migration. Scheduled push is excluded from current daily-card acceptance.

### 4.5 Payment, quota and deletion

- Daily-card opening does not consume the chat quota.
- An 890 ₽ full-report purchase does not change daily-card access.
- Legacy premium/Tarot status does not change eligibility for this free use case.
- `DailyTarotDraw.user_id` has `ON DELETE CASCADE`; account deletion therefore removes daily draw rows.
- No separate approved retention period or cleanup job for completed daily rows was found.

`OWNER DECISION PENDING — Tarot history retention` applies to retention policy, not to whether durable daily persistence exists.

## 5. Expanded Tarot — current implementation

All functions in this section are outside NURA 1.0. Their current reachability does not make them approved for release.

| Surface | Entry/consumer | Current access | Persistence/history | Canonical destination |
|---|---|---|---|---|
| Weekly | Telegram `tarot_weekly`; PWA `weekly`; scheduled Monday task | Telegram/PWA require `tarot_subscription`; `test_mode` bypasses Telegram gate | Response/message only; scheduled prompt cache is not user history | 1.5A weekly focus / approved spread set |
| Question | Telegram FSM `tarot_question`; PWA `question` | Telegram requires `tarot_subscription`; PWA treats it as free | No durable reading row | 1.5A approved spread set |
| Mini-spread | PWA `mini` | PWA treats it as free | No durable reading row | Only if included in approved 1.5A set |
| Spheres/life | Telegram callbacks; PWA `life` | Legacy Tarot gate | No durable reading row | Only if included in approved 1.5A set |
| Twins/doubles | Telegram `tarot_twins`; PWA `doubles` | Legacy Tarot gate | No durable reading row | Only if included in approved 1.5A set |
| Month portal | Telegram `tarot_portal`; PWA `portal`; scheduled monthly task | Legacy Tarot gate | No durable reading row; monthly cache is not history | 1.5A monthly compass requires a separate accepted contract |
| Blocks | Telegram `tarot_blocks` | Legacy Tarot gate | No durable reading row | Only if included in approved 1.5A set |
| Yes/no | Telegram FSM `tarot_yes_no`; PWA `yesno` | Telegram requires Tarot; PWA treats it as free | No durable reading row | 1.5A mandatory set, subject to approved output contract |

Current Telegram and PWA access policies are inconsistent: question and yes/no are paid through Telegram legacy gates but free in PWA; mini exists only in PWA. This is an implementation/legacy compatibility gap, not an owner-approved pricing rule.

The scheduled weekly and monthly tasks are in Beat and query users with `tarot_subscription=True`. They generate and deliver current legacy content but do not persist a canonical period-keyed reading. Current “Портал месяца” output is not evidence that the NURA 1.5 monthly compass contract is accepted or complete.

No dedicated expanded-Tarot feature flag was found. Handler registration, visible locked buttons and direct callbacks make these early 1.5 functions reachable.

`IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04`

## 6. Compatibility — current implementation

### 6.1 Current flow

`CURRENT — IMPLEMENTED` as an early/legacy runtime surface; not an approved public 1.5B release.

1. The registered `compatibility` callback is visible in the main menu.
2. The current user must have `has_matrix=True`.
3. The flow collects partner name, relationship type and partner birth date in FSM state.
4. It calculates both matrices and calls `AIService.generate_compatibility()` with `compatibility_full.txt` plus the shared non-chat `system_prompt.txt`.
5. It returns a compact Telegram result, can expose a tokenized HTML report, can expose PDF for romance, and can generate a share image.
6. The task replaces the user's previous compatibility `Report` row with the latest one. It saves matrix data and AI analysis and also writes personalized HTML/PDF to the legacy filesystem output directory.

### 6.2 Current access

- A `has_matrix` user gets one current free use tracked by the boolean `compatibility_used`.
- `tarot_subscription=True` or `subscription_status == "premium"` bypasses the one-use check.
- The compatibility helper reads those status flags directly and does not validate the corresponding `*_until` timestamp. It is therefore a legacy flag gate, not a trustworthy canonical entitlement resolver.
- These are legacy access rules. They do not establish the future compatibility price or 1.5 entitlement.
- There is no dedicated compatibility flag and no compatibility deep-link contract.

### 6.3 Target and gaps

Canonical compatibility belongs to NURA 1.5B after 1.5A stabilization. The target requires separate consent for the second person's data, minimization, non-fatal wording and a separately approved price/inclusion rule.

Evidence-backed gaps:

- primary-menu visibility conflicts with DM-04;
- no dedicated release gate was found;
- no separate second-person consent step was found;
- current access is coupled to legacy flags;
- only the latest DB result is retained; there is no canonical compatibility history UX;
- database account deletion removes the compatibility report row, but `AccountDeletionService` does not delete legacy personalized filesystem artifacts;
- local tests cover handler gates and selected flow transitions, not external content/privacy acceptance.

`IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04`

## 7. Referral — current foundation

### 7.1 Current foundation

`CURRENT — IMPLEMENTED` only as a partial foundation.

- Profile output exposes `https://t.me/{bot_username}?start=ref_{telegram_id}`.
- `/start ref_*` is parsed by the registered start handler.
- The caller rejects self-referral before entering `_handle_referral`.
- `User.referred_by` stores the inviter's Telegram ID once; repeated attribution is rejected once the field is set.
- A valid inviter/invitee pair creates one `ReferralReward(event="registration")`; `referred_id` is unique.
- The inviter receives a registration notification when Telegram sending succeeds.
- Generic `a_*` campaign attribution is a separate foundation and must not be confused with the referral product.

The current “reward” is a ledger row, not an activated user benefit. No reachable purchase hook that creates `matrix_purchase`, no bonus amount/type, no entitlement activation, no balance/history UI and no payment application were found. Profile copy promises a future bonus after a purchase, but current code does not fulfill that promise.

Static referral test evidence is narrow: it checks routing to `_handle_referral`, not the full persistence, replay, self-referral, purchase or reward-activation lifecycle.

### 7.2 Target NURA 1.5B

Canonical 1.5B adds qualifying events, idempotent reward issuance, self-referral protection, abuse limits and transparent reward history. Suggested reward examples in the product spec are not approved economics.

### 7.3 Deletion boundary

- Account deletion explicitly deletes `ReferralReward` rows in which the user is inviter or invitee.
- Deleting the invitee deletes that user's `referred_by` field with the user row.
- When an inviter is deleted, other users' scalar `referred_by` Telegram-ID values are not explicitly cleared; the column has no foreign key. Cleanup/retention for these survivor values is an implementation/privacy gap.

`IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04` applies to the profile referral promotion.

## 8. Visibility and DM-04

| Feature | Runtime registered | Menu/profile visible | Direct callback/deep-link | Canonical version | DM-04 status |
|---|---|---|---|---|---|
| Daily card | Yes, Telegram and PWA | Main Tarot entry plus free card | `tarot_daily_card`; PWA endpoint | NURA 1.0 | Allowed 1.0 function; generic Tarot container also exposes 1.5 content |
| Expanded Tarot | Yes, Telegram/PWA; weekly/monthly tasks | Spread buttons and 390 ₽ paywalls visible | Direct callbacks and PWA API | NURA 1.5A | `IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04` |
| Compatibility | Yes | Main-menu button visible | `compatibility` callback | NURA 1.5B | `IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04` |
| Referral | Yes in `/start` and profile | Referral link and purchase-bonus copy visible in profile | `/start ref_*` | NURA 1.5B | `IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04` |

No dedicated Tarot/compatibility/referral release flags were found in current settings. `test_mode` is a development bypass, not a production feature gate. DM-04 does not prescribe the exact flag design; that mechanic remains to be implemented without changing the approved gating principle.

## 9. Legacy PWA and 390 ₽ entitlement

`LEGACY RECURRING 390 ₽ ENTITLEMENT — NOT NURA 1.0 AND NOT TARGET 399 ₽ ACCESS`

Current legacy evidence:

- `tarot_subscription_price_rub=390`;
- Telegram and PWA checkout routes for premium/Tarot exist;
- `User` stores premium/Tarot status, expiry and `payment_method_id`;
- verified initial legacy payment paths can activate a 30-day premium or Tarot state;
- a true Tarot flag gates expanded Tarot and bypasses the compatibility one-use limit; those handlers do not independently validate `tarot_subscription_until`;
- a `premium` status bypasses compatibility but does not satisfy Telegram/PWA expanded-Tarot checks, which read only `tarot_subscription`; the compatibility helper also does not validate `subscription_until`;
- a recurring task is scheduled and attempts renewal near expiry;
- PWA Tarot and web report routes remain reachable under DM-03 legacy compatibility.

Accepted pricing/payment evidence also records material lifecycle gaps: provider payment-method persistence is not established by current wiring, recurring extension is not backed by a dedicated verified-success contract, and the cancellation UI changes only `subscription_status` rather than cancelling the provider method. No conclusion may be drawn that existing mandates are disabled, migrated, refunded or supported indefinitely.

Target NURA 1.5 uses a distinct gift/paid entitlement model: 30-day gift where eligible, then a voluntary 399 ₽/30-day purchase with no baseline auto-renew. It must not be implemented by renaming the legacy 390 ₽ path.

`OWNER DECISION PENDING — legacy subscriber disposition`

`OWNER DECISION PENDING — support duration for legacy PWA/Tarot`

### 9.1 Current and target entitlement matrix

| User state | Daily card | Expanded Tarot | Compatibility | Referral | Classification |
|---|---|---|---|---|---|
| Ordinary user without `has_matrix` | Available with active account + birth date | Telegram paywalls; PWA question/yes-no/mini remain free legacy exceptions | Blocked by Matrix purchase CTA | Profile/deep-link foundation reachable | `CURRENT — IMPLEMENTED` plus early-feature visibility gap |
| `has_matrix=True`, no legacy flags | Available | Same as ordinary user; `has_matrix` is not Tarot entitlement | One current use, then legacy upsell | Foundation reachable | `CURRENT — IMPLEMENTED` legacy compatibility rule |
| Verified 890 ₽ full-report buyer | Available | Purchase alone grants no expanded Tarot | Current `has_matrix` marker enables the one-use path | Foundation reachable; no purchase reward hook found | `CURRENT — IMPLEMENTED`; no 1.5 entitlement |
| `tarot_subscription=True` | Available | Current Telegram/PWA legacy gates open; timestamp is not checked in these handlers | One-use limit bypassed | No additional implemented reward | `LEGACY COMPATIBILITY` |
| `subscription_status="premium"` | Available | Does not open expanded Tarot without Tarot flag | One-use limit bypassed; timestamp is not checked here | No additional implemented reward | `LEGACY COMPATIBILITY` |
| Expired timestamp but stale true/status flag | Available | May remain open where raw flag is used | May remain unlimited where raw flag/status is used | No effect | `IMPLEMENTATION GAP` in legacy entitlement resolution |
| Target 1.5 gift/paid user | Target: available | Target: approved set, history, weekly/monthly | 1.5B rule to be approved after core | 1.5B reward rule to be approved | `TARGET — NURA 1.5`; not implemented |

## 10. Target NURA 1.0 crosswalk

| Target requirement | Current evidence | Classification |
|---|---|---|
| Free daily card after mini | Daily use case requires an active user and birth date; current menu makes the card reachable | `CURRENT — IMPLEMENTED` with navigation differences |
| Same result during product day | Unique durable row and replay without AI regeneration | `CURRENT — IMPLEMENTED` |
| One result per user/day | DB unique constraint on user/local date | `CURRENT — IMPLEMENTED` |
| Reflection/action, no guaranteed prediction | Current prompt asks for three personal paragraphs and a concrete action, but does not explicitly require the canonical reflection question or disclaimer; deterministic enforcement is not proven | `IMPLEMENTATION GAP` / `EVIDENCE BOUNDARY` |
| Telegram-first compact navigation | Generic Tarot menu exposes early 1.5 spreads and paywalls; canonical `/tarot` command is absent | `IMPLEMENTATION GAP` |
| No expanded Tarot, compatibility or referral in 1.0 primary path | All three are currently visible | `IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04` |
| No subscription/recurring model in 1.0 | Legacy 390 ₽ path remains reachable | `LEGACY COMPATIBILITY` / visibility gap |

NURA 1.0 does not include weekly/monthly readings, expanded history, compatibility, referral, gift access or paid Tarot access.

## 11. Target NURA 1.5 crosswalk

### 11.1 NURA 1.5A

Canonical 1.5A includes:

- 30-day gift access after an eligible full-report purchase, without automatic payment;
- voluntary 399 ₽ access for 30 days, without baseline auto-renew;
- an owner-approved set of spreads;
- saved readings and repeated opening without regeneration;
- weekly focus and monthly compass;
- expanded chat and lifecycle value.

Current expanded Tarot code is early implementation evidence only. It lacks canonical entitlement, approved spread-set governance, durable `TarotReading` history and consistent cross-client gates.

### 11.2 NURA 1.5B

Canonical 1.5B contains referral, gift purchase for another person, compatibility and additional growth loops after 1.5A acceptance. Current referral/compatibility code does not move these functions into 1.0 or prove their 1.5B acceptance.

## 12. Persistence, history and deletion

| Domain data | Current storage | Retrieval/history | Account deletion | Retention status |
|---|---|---|---|---|
| Daily card | `daily_tarot_draws`, unique user/local date | Same-day repeated opening; no profile history list | DB cascade with User | Rows persist without a dedicated cleanup policy; decision pending |
| Expanded Telegram/PWA spreads | Response/message; selected process/AI caches | No durable `TarotReading` or “Мои расклады” | No durable reading row to delete; provider/cache boundary not user-history proof | Target history/retention not implemented |
| Compatibility | Latest `Report` row plus HTML/PDF filesystem output | Latest report can be linked/listed through legacy report surfaces | DB report removed; filesystem files not removed by deletion service | Cleanup/privacy gap; policy not inferred |
| Referral attribution | `User.referred_by` scalar Telegram ID | No user-facing attribution history | User row removed; survivor references to deleted referrer not explicitly cleared | Cleanup/retention gap |
| Referral reward | `referral_rewards` registration row | Repository stats only; no user balance/history UI | Explicitly deleted for inviter or invitee | Reward economics/retention not approved |
| Legacy entitlement | User flags/expiry/method plus legacy `Payment` rows | Profile/paywall/payment surfaces | User and legacy `Payment` removed; broader financial retention belongs to payment contract | Legacy disposition pending |
| Chat/prompt Redis | Chat history keys are separate from Tarot readings | Not Tarot history | Account deletion removes two known chat-history keys | No claim about all provider/cache records |
| PWA daily browser cache | User-scoped localStorage cache for UX | Client replay aid, not authority | Logout clears known cache; account-deletion behavior in every browser is not proven | `LEGACY COMPATIBILITY` / evidence boundary |

Absence of a retention decision does not negate current daily or compatibility persistence. Conversely, browser/process cache does not establish durable history.

## 13. Prompt and AI boundary

Prompt bodies are not reproduced here. All current runtime prompts live in `nura_app/core/prompts/`; [Runtime prompt contracts](prompt-spec.md) governs the shared report/chat prompt boundary.

| Feature | Prompt / loader | Consumer | Output | Version / acceptance | Classification |
|---|---|---|---|---|---|
| Daily card | `tarot_daily_card.txt` via `AIService._load_prompt()` | `generate_tarot_daily_card()` → Tarot loop; daily application, Telegram/PWA | Plain interpretation text persisted in daily row | Local lifecycle accepted; content/provider sandbox not accepted | `CURRENT — IMPLEMENTED` |
| Weekly | `tarot_weekly_spread.txt` | AIService for interactive Telegram/PWA; separate scheduled task consumer | Structured JSON in interactive flow; text in scheduled flow | Shared `system_prompt.txt` coupling in AIService; no independent feature release | `CURRENT — IMPLEMENTED`, early 1.5 |
| Question | `tarot_question.txt` | Telegram loads template directly; PWA calls `AIService.generate_tarot_question()` | Telegram text; PWA expects structured JSON | Current template placeholders match Telegram but not AIService arguments; formatting fails before AIService error handling and PWA maps the exception to 503 | `IMPLEMENTATION GAP` |
| Mini-spread | `tarot_mini_spread.txt` | PWA → AIService | Structured JSON | No accepted 1.5 set/contract | `LEGACY COMPATIBILITY` / early 1.5 |
| Spheres | `tarot_spheres.txt` | Telegram handler and PWA route | Plain/structured wrapper | No independent acceptance | `CURRENT — IMPLEMENTED`, early 1.5 |
| Doubles/twins | `tarot_doubles.txt` | Telegram handler and PWA route | Plain/structured wrapper | No independent acceptance | `CURRENT — IMPLEMENTED`, early 1.5 |
| Month portal | `tarot_portal.txt` | Telegram, PWA and scheduled task | Plain/structured wrapper | Does not prove canonical monthly-compass contract | `CURRENT — IMPLEMENTED`, early 1.5 |
| Blocks | `tarot_blocks.txt` | Telegram handler | Plain text | No independent acceptance | `CURRENT — IMPLEMENTED`, early 1.5 |
| Yes/no | `tarot_yes_no.txt` | Telegram FSM and PWA route | Plain/structured wrapper | No independent acceptance | `CURRENT — IMPLEMENTED`, early 1.5 |
| Compatibility | `compatibility_full.txt` plus shared `system_prompt.txt` | `AIService.generate_compatibility()` | Validated compatibility JSON → report/message | Local consumer exists; 1.5B privacy/content acceptance absent | `CURRENT — IMPLEMENTED`, early 1.5B |
| Referral | None | No AI consumer found | No AI output | N/A | `CURRENT — FOUNDATION`, non-AI |

`tarot_daily_card_handler.txt` and `compatibility_mini.txt` exist, but no current Python consumer was found. File presence alone does not make them runtime contracts.

Several compatibility/Tarot consumers share report `system_prompt.txt`; they are not independently accepted release units. Content Studio guidance is editorial and is not a runtime prompt authority.

## 14. Implementation gaps

1. `IMPLEMENTATION GAP — CURRENT VISIBILITY CONFLICTS WITH DM-04` for expanded Tarot, compatibility and referral promotion.
2. No dedicated release gates were found; `test_mode` is not a feature flag.
3. Expanded-Tarot entitlement differs between Telegram and PWA.
4. Raw legacy Tarot/compatibility gates do not consistently validate entitlement expiry timestamps.
5. No canonical `Entitlement` implementation for gift/399 access exists.
6. No durable `TarotReading`, period-keyed weekly/monthly persistence or “Мои расклады” history exists.
7. Current scheduled weekly/monthly delivery does not establish the canonical 1.5 regular-value contract.
8. PWA question generation uses an AIService/template placeholder contract that does not match the current prompt file.
9. The current daily prompt/output does not explicitly require the canonical reflection question or disclaimer; current acceptance proves lifecycle, not complete target content.
10. Compatibility lacks a separate second-person consent step and canonical privacy/history lifecycle.
11. Compatibility filesystem artifacts are not removed by account deletion.
12. Referral has registration attribution/ledger only; purchase qualification, activated reward, transparent history and payment application are absent.
13. Referral survivor `referred_by` values are not cleared when an inviter account is deleted.
14. Legacy 390 ₽ recurring/cancellation/provider-method lifecycle is incomplete and conflicts with the target model.
15. External Telegram/AI/YooKassa acceptance for these domains has not been executed.

## 15. Owner decisions

These unresolved parameters must not be inferred from current code or historical plans:

- exact approved expanded-Tarot set and naming;
- Tarot history depth and retention;
- Tarot/compatibility product rules and future pricing where canonical authority leaves them open;
- referral qualifying events, reward economics, anti-fraud limits and user-visible ledger;
- legacy 390 ₽ subscriber and saved-method disposition;
- legacy PWA/Tarot support duration;
- exact DM-04 gating mechanics and rollout dates;
- early-buyer gift migration;
- future prompt rollout/acceptance thresholds.

The following are not pending: daily card is in NURA 1.0; expanded Tarot is 1.5A; referral and compatibility are 1.5B; the 390 ₽ recurring model is legacy; Telegram-first and DM-04 are accepted directions.

## 16. Acceptance boundary

| Evidence layer | What is established | What is not established |
|---|---|---|
| Static code/migration review | Router registration, menu visibility, data fields, prompt consumers, gates and deletion code | Runtime provider behavior or user acceptance |
| Local unit/integration tests | Daily lifecycle/timezone/replay; selected Tarot/PWA gates; compatibility handler branches; checkout contracts | Full referral lifecycle, all prompt semantics, production topology |
| Local PostgreSQL/Redis acceptance | Durable daily draw, replay and account deletion are in dated v1 evidence | Scheduled Tarot push, compatibility/referral external flow |
| Dated acceptance evidence | Free daily Tarot local segment is PASS with fake AI/Telegram | Expanded Tarot, compatibility and referral release acceptance |
| External Telegram/AI/YooKassa sandbox | Not executed for this consolidated domain scope | Real bot UX, model quality, real checkout/renewal and provider callbacks |
| Production | Not executed / not proven | Deployment, real users, legal/privacy/support readiness |

Tests were read as static evidence in this documentation session and were not rerun by explicit instruction.

## 17. References

Authority and accepted documentation:

- [Documentation router](README.md)
- [NURA 1.0/1.5 Product Specification](product/NURA_1_0_1_5_PRODUCT_SPEC.md)
- [Current implementation status](implementation/current-status.md)
- [Documentation migration decisions](decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md)
- [Bot specification](bot-spec.md)
- [Bot UX map](bot-ux-map.md)
- [Pricing and access map](pricing.md)
- [Payment flow audit](audits/PAYMENT_FLOW_AUDIT.md)
- [Runtime prompt contracts](prompt-spec.md)
- [Report system specification](report-spec.md)
- [Acceptance index](acceptance/README.md)
- [Dated Telegram-first v1 readiness evidence](acceptance/evidence/telegram-first-v1-readiness-review.md)
- [Stage 2A migration file map](reconciliation/2026-07-28/MIGRATION_FILE_MAP.md)
- [Tarot integration historical record](tarot-integration-sessions.md)

Primary implementation evidence:

- `nura_app/bot/main.py`
- `nura_app/bot/handlers/tarot.py`
- `nura_app/bot/handlers/compatibility.py`
- `nura_app/bot/handlers/start.py`
- `nura_app/bot/handlers/profile.py`
- `nura_app/bot/keyboards/main_menu.py`
- `nura_app/bot/keyboards/tarot_keyboard.py`
- `nura_app/api/routes/tarot_pwa.py`
- `nura_app/core/services/daily_tarot_application.py`
- `nura_app/core/services/daily_tarot_timezone.py`
- `nura_app/core/services/daily_arcana.py`
- `nura_app/core/services/ai.py`
- `nura_app/core/services/account_deletion.py`
- `nura_app/core/services/attribution.py`
- `nura_app/core/services/payment.py`
- `nura_app/core/repositories/daily_tarot_draw.py`
- `nura_app/core/repositories/referral.py`
- `nura_app/core/repositories/user.py`
- `nura_app/core/models.py`
- `nura_app/core/tasks.py`
- relevant Alembic migrations and static tests under `nura_app/tests/`
