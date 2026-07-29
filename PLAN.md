# NURA — Historical Project Plan

> **STATUS: HISTORICAL / SUPERSEDED PROJECT PLAN**
>
> Snapshot of the July 2026 Loop Engineering board. It is not a current roadmap, backlog, acceptance record or product authority.

## 1. Authority and historical scope

The original `Now / Next / Ideas / Done` board mixed shipped engineering milestones with experiments and speculative follow-ups. It is retained to explain why several resilience, caching and AI-loop mechanisms exist, but its imperative language has been retired.

- Product target: [canonical NURA 1.0/1.5 specification](docs/product/NURA_1_0_1_5_PRODUCT_SPEC.md).
- Current implementation: code/tests plus [current implementation status](docs/implementation/current-status.md).
- Current documentation navigation: [docs authority router](docs/README.md).
- Historical session narrative: [STATE.md](STATE.md), which is a journal rather than a specification.

## 2. Original planning context

The board followed the 4 July 2026 Loop Engineering work. Its focus was AI-output resilience rather than the complete Telegram-first product roadmap. The snapshot grouped together:

- semantic verification and retry loops;
- Tarot and report caching;
- chat-history persistence and AI metrics;
- fallback/regeneration ideas;
- prompt experiments and observability follow-ups.

That scope explains the old priorities, but it cannot replace later owner decisions, the canonical product spec or evidence-backed current contracts.

## 3. Completed or incorporated milestones

The historical `Done` list is preserved as repository chronology, not as fresh acceptance:

| Historical milestone | Repository history | Current reading |
|---|---|---|
| `SemanticVerifier`, loop specs, retry factory and gather fix | `0d3e39a` | Incorporated into implementation; exact current behavior belongs to code/tests |
| Portal/weekly/daily Tarot caching | `0d3e39a` | Incorporated early Tarot implementation; version/release authority belongs to current Tarot docs |
| Semantic loop for full report and seven Tarot text handlers | `0d3e39a`, `4635647` | Incorporated implementation milestone, not external content acceptance |
| Degradation ladder, name check and Tarot personalization | `0d3e39a` | Incorporated implementation milestone; current consumers remain authoritative |
| Chat history in Redis | `e004d6d` | Incorporated; current retention/consumer behavior belongs to code and bot docs |
| Structured AI logging | `e004d6d` | Incorporated observability milestone; no production monitoring claim follows |
| Sequential full-report circuit breaker | `e004d6d` | Incorporated implementation milestone |
| Retry feedback activation and fallback fixes | `4635647` | Incorporated implementation milestone |
| Video/media pipeline removal | Historical `Done` entry | Preserved as chronology; this file does not re-establish the removed subsystem or prove full removal today |

## 4. Superseded product assumptions

- The board's `Now` and `Next` ordering is superseded. It must not determine current priorities.
- Tarot chat/FSM, compatibility and related work cannot be promoted from this board into NURA 1.0. Their current version boundaries are defined by the canonical spec and DM-04.
- A generic multi-model fallback, automatic report regeneration or prompt A/B framework was never made a committed product requirement by this file.
- «After deploy» and production-style implications in the old planning context are not external acceptance evidence.
- A duplicated A/B-testing item in both `Next` and `Ideas` was planning noise, not a second decision.

## 5. Ideas moved to future vision or research

The following old `Now / Next / Ideas` entries are retained as `dated experiment` or `not part of committed roadmap`:

| Old idea | Final classification |
|---|---|
| Tarot chat-history/FSM storage follow-up | Dated engineering question; current code/docs decide whether any gap remains |
| Sentry breadcrumbs from structured AI logs | Dated observability experiment; not a committed roadmap item |
| Multi-model fallback | Future technical possibility; not part of committed roadmap |
| Automatic delayed report regeneration | Future reliability idea; not part of committed roadmap |
| Prompt A/B testing | Dated experiment/research idea; not an accepted delivery phase |
| Semantic loop for compatibility | Early 1.5B engineering idea; not a NURA 1.0 task |

None of these ideas is declared rejected. Revival requires a separately scoped decision and current evidence review.

## 6. Current authoritative destinations

| Question | Current destination |
|---|---|
| What must NURA 1.0/1.5 deliver? | [Canonical product spec](docs/product/NURA_1_0_1_5_PRODUCT_SPEC.md) |
| What is implemented now? | [Current implementation status](docs/implementation/current-status.md) and code/tests |
| What are current report and AI prompt contracts? | [Report spec](docs/report-spec.md), [two-layer architecture](docs/two-layer-architecture.md), [prompt spec](docs/prompt-spec.md) |
| What is current Tarot/compatibility scope? | [Tarot domain map](docs/tarot-integration-plan.md) and [historical implementation record](docs/tarot-integration-sessions.md) |
| Where are migration classifications recorded? | [Migration file map](docs/reconciliation/2026-07-28/MIGRATION_FILE_MAP.md) |

## 7. Historical value

This file preserves the sequence from verifier/caching work to chat persistence, logging, circuit breaking and retry hardening. It also shows which speculative reliability ideas were considered immediately afterward. It does not preserve runnable task commands because those commands could override later authority and recreate stale priorities.

## 8. References

- [Documentation authority router](docs/README.md)
- [Canonical NURA 1.0/1.5 product spec](docs/product/NURA_1_0_1_5_PRODUCT_SPEC.md)
- [Current implementation status](docs/implementation/current-status.md)
- [Migration decisions](docs/decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md)
- [Migration file map](docs/reconciliation/2026-07-28/MIGRATION_FILE_MAP.md)
- Git history: `0d3e39a`, `e004d6d`, `4635647`
