# NURA Acceptance Evidence

## Production secret/migration implementation (2026-07-31)

Local code/tests define `production-files-v1`, an offline redacted preflight,
an exact hashed `d1e2f3a4b5c6 → d8e9f0a1b2c3` chain and a manifest-only transition
engine. Это `STATIC EVIDENCE` / `LOCAL UNIT/INTEGRATION`, не VPS inventory,
backup, authorization manifest, migration, deploy или production proof. Target
`T` ещё неизвестен; execution по контракту заблокирован до отдельного tracked
authorization milestone.

## Owner-only prelaunch local evidence (2026-07-31)

Owner decision заменяет ближайший execution path: отдельный external sandbox
stack на текущей стадии не создаётся; будущая проверка планируется на текущих
VPS, hostname и production bot в закрытом allowlisted режиме. YooKassa
отложена, payments выключены, current production DeepSeek path сохраняется.
Локальные code/tests подтверждают contract, но не являются VPS inventory,
backup, deploy, Telegram/AI call или production smoke evidence.

План перехода: [Current VPS owner-only prelaunch](../current-vps-prelaunch.md).
Он имеет уровень `RUNBOOK — NOT EXECUTION PROOF`. Существующее state считается
disposable только после backup и отдельного owner approval на очистку.

## Fail-closed external sandbox profile (2026-07-31)

Локальный worktree на baseline `0be905226eebc1148d26bf89559d2ae5ce45096f`
реализует отдельный `APP_ENV=sandbox`, общий startup validator, глобальные
Telegram guards, разделённые YooKassa test-shop/shortcut contracts, AI budget,
isolated full-stack Compose и offline preflight. Это `LOCAL UNIT/INTEGRATION` и
`STATIC EVIDENCE`, а не внешний запуск. Telegram/YooKassa/AI identity checks,
Compose start, DNS/TLS и deploy в implementation-сессии не выполнялись. См.
[описание профиля](../external-sandbox-profile.md).

## Local prompt-governance evidence (2026-07-31)

Checked-in report/chat manifests, resolver, pinning, nullable provenance migration, contract tests и sanitized human-review packet относятся к local automated evidence. Они не доказывают качество реального provider output. External AI/provider content sandbox остаётся отдельным `NOT EXECUTED` gate; см. [prompt governance](../prompt-governance.md) и [Telegram-first sandbox](telegram-first-sandbox.md).

Process exception (2026-07-31): stale test mock допустил один unintended DeepSeek request только с synthetic sandbox fixture data. После обнаружения DeepSeek endpoint был принудительно направлен на `127.0.0.1:9`; повторных внешних AI-запросов не было. Реальные пользовательские данные и production state не затрагивались. Этот запрос не является external AI sandbox execution evidence; владелец принял process exception.

**STATUS: CURRENT ACCEPTANCE EVIDENCE ROUTER**

## 1. Authority and scope

This index classifies evidence; it does not execute a runbook, replace the
[canonical product target](../product/NURA_1_0_1_5_PRODUCT_SPEC.md), or authorize
sandbox, production, legal, payment or deployment actions. Implemented state is
established by code, migrations, configuration and tests, with a compact mirror
in [current status](../implementation/current-status.md).

A result is usable only at its recorded evidence level. In particular, a local
PASS, a Compose service definition, or a `READY` implementation label is not an
external-sandbox result, launch approval or production-availability claim.

## 2. Evidence-level legend

- `STATIC EVIDENCE` — reachable code/configuration and test inspection without execution.
- `LOCAL UNIT/INTEGRATION` — automated tests using local or fake provider boundaries.
- `LOCAL POSTGRESQL/REDIS` — disposable local infrastructure and concurrency/durability coverage.
- `DATED ACCEPTANCE EVIDENCE` — immutable result for the date and baseline recorded by that evidence file.
- `RUNBOOK — NOT EXECUTION PROOF` — instructions and criteria only; unchecked until a separate evidence record is produced.
- `EXTERNAL SANDBOX — NOT EXECUTED` — real test-provider environment has no recorded completed run.
- `PRODUCTION — NOT PROVEN` — availability, topology and operating behavior have not been verified in production.
- `LEGAL/POLICY — NOT PROVEN` — applicable policy, consent and support gates have no accepted evidence here.

Do not use an unqualified `PASS`: name the evidence level and baseline.

## 3. Current code/readiness baseline

The current reproducible committed code baseline is `main` at
`b70d6ccf8bbeac49b77015be09295a41060fc9bd`. The accepted current implementation
mirror records the following summary for that baseline:

| Evidence | Result | Level | Boundary |
|---|---:|---|---|
| Targeted regression set | `147 passed` | `LOCAL UNIT/INTEGRATION` | Relevant code paths; providers remain mocked/fake where required |
| Canonical safe suite | `1081 passed`, `22 skipped`, `1 deselected`, `0 failed` | `LOCAL UNIT/INTEGRATION` | Current committed code baseline, not external or production |
| Ruff | PASS | `STATIC EVIDENCE` | Python lint only |
| Independent final review | No actionable findings | `STATIC EVIDENCE` | Reviewed code diff, not runtime availability |

These results are recorded by the non-normative [current implementation mirror](../implementation/current-status.md)
for the committed baseline. This router does not turn that summary into a separate
dated execution record: raw execution transcripts are not stored here, and the
checks were not re-executed during documentation Write Session 6. Code/tests remain
the implementation authority. `git diff --check` is a repository-diff integrity
check, not product or production acceptance.

## 4. Dated acceptance evidence

[Telegram-first v1 readiness review](evidence/telegram-first-v1-readiness-review.md)
is `DATED ACCEPTANCE EVIDENCE` for 28 July 2026. It records a worktree-specific
safe-suite manifest (`9a0695a156a30651d03c971802580ddb775af34aab51f1839afbd1339539dfda`)
and `1082 collected`, `1059 passed`, `22 skipped`, `1 deselected`, `0 failed`.
The review does not assign that executed worktree a single committed SHA; its
date, inventory, manifest and stated limitations define its baseline.

That file remains immutable historical evidence. The newer `1081` result does
not rewrite or retroactively reattribute the `1059` run, and the `1059` run must
not be described as executed on `b70d6cc`.

## 5. PostgreSQL/Redis race evidence

The current baseline separately records `3 passed` for the focused local
PostgreSQL race set covering refund versus worker persistence/retry, delivery
versus refund ordering, and refund versus account deletion deadlock safety in
`nura_app/tests/test_telegram_first_postgres_failure_retry.py`.

This is `LOCAL POSTGRESQL/REDIS` evidence. It proves the inspected local
linearization, fencing and completion contracts under disposable infrastructure;
it does not prove production concurrency, provider ordering, network behavior,
database sizing, failover or operator recovery.

## 6. External sandbox status

`EXTERNAL SANDBOX — NOT EXECUTED` for all of the following:

- Telegram test bot credentials, allowlisted account, deep links, onboarding,
  mini/full delivery, retry, deletion and blocked-bot behavior;
- YooKassa test shop, fiscal receipt settings, public HTTPS webhook/return flow,
  success/refund/duplicate/out-of-order events and confirmation of no real charge;
- external AI/provider credentials, model behavior, content review and failure handling.

The [broadcast/CTA/opt-out target scenario](telegram-first-sandbox.md#41-broadcast-cta-and-opt-out-acceptance-boundary)
is `LOCALLY EXECUTABLE — EXTERNAL SANDBOX NOT EXECUTED`. The accepted
[bot technical specification](../bot-spec.md#410-broadcasts) and
[bot UX map](../bot-ux-map.md#311-broadcast-receipt-cta-and-opt-out) record the
local persisted campaign, per-user delivery, logical CTA/click events,
deduplication, opt-out/suppression and bounded attribution contract. This local
evidence only makes a separately authorized sandbox run eligible; it is neither
a completed nor a failed external sandbox result and proves no production send.

The [Telegram-first external sandbox runbook](telegram-first-sandbox.md) is an
instruction set only. No checkbox or procedure in it may be marked complete
without a separate dated, redacted execution record.

## 7. Production readiness boundary

`PRODUCTION — NOT PROVEN` and `LEGAL/POLICY — NOT PROVEN`.

Tracked deployment instructions and Compose topology do not establish a running
service. No accepted evidence here proves production TLS/firewall state, secret
management, public URLs, backup/restore, monitoring, incident/support SLA,
Telegram delivery, YooKassa charges/refunds, external AI behavior, offer,
privacy policy, user agreement or consent flow. Production launch requires
separate owner GO decisions after applicable sandbox, legal and operations gates.

## 8. Runbooks and operational instructions

| Document | Purpose | Baseline/date | Evidence type | Current authority status | Production proof? |
|---|---|---|---|---|---|
| This README | Route and classify evidence | Current documentation worktree | Router, not evidence | Current acceptance router | No |
| [External sandbox runbook](telegram-first-sandbox.md) | Define Telegram/YooKassa/AI sandbox scenarios and evidence capture | Current instructions; execution status explicit in the file | `RUNBOOK — NOT EXECUTION PROOF` | Current runbook | No |
| [Dated readiness review](evidence/telegram-first-v1-readiness-review.md) | Preserve the local readiness review and its limitations | 2026-07-28; manifest-specific worktree baseline | `DATED ACCEPTANCE EVIDENCE` | Immutable dated evidence | No |
| [Astro-insight audit](audits/astro-insight-contamination.md) | Preserve a scoped dated contamination audit | Baseline/date stated in the file | Dated audit evidence | Scoped evidence only | No |
| [Legacy Telegram auth audit](audits/legacy-telegram-auth.md) | Preserve a scoped legacy-auth audit | Explicit execution date and commit/worktree baseline are not recorded in the document | `SCOPED AUDIT — EXPLICIT DATE/BASELINE NOT RECORDED IN DOCUMENT` | Scoped legacy-auth evidence only | No |
| Root [DEPLOY.md](../../DEPLOY.md) | Define release and rollback instructions | Current operations contract | `RUNBOOK — NOT EXECUTION PROOF` | Current deployment instructions | No |
| Root [Admin Bot contract](../../ADMIN_BOT_SPEC.md) | Describe current operator surface and known Celery resolver gap | Static code/test inspection | `STATIC EVIDENCE` / current operations | Current operations contract | No |

The legacy-auth audit remains useful only for the retired-flow contracts within
its stated scope. Git blob/history provides repository provenance but does not
replace the absent in-document execution date or commit/worktree baseline. The
audit is neither current full-auth acceptance nor production proof.

## 9. Evidence update rules

1. Preserve dated evidence unchanged; create a new dated record for a new execution.
2. Record branch/commit, date, environment, command, result, skips/deselections,
   redacted artifacts and cleanup outcome for every new run.
3. Never promote local/fake-provider evidence to external sandbox or production.
4. Never infer deployment or service availability from configuration or Compose.
5. Keep secrets, tokens, DSNs, provider payloads, receipt data and PII out of evidence.
6. Update current counts only from primary repository evidence for the named baseline.
7. Preserve unresolved implementation gaps and owner decisions; an acceptance router
   does not fix or decide them.

## 10. References

- [Canonical target acceptance criteria](../product/NURA_1_0_1_5_PRODUCT_SPEC.md)
- [Current implementation mirror](../implementation/current-status.md)
- [Documentation authority router](../README.md)
- [Documentation migration decisions](../decisions/NURA_DOCUMENTATION_MIGRATION_DECISIONS.md)
- [Stage 2A reconciliation report](../reconciliation/2026-07-28/STAGE_2A_EXECUTION_REPORT.md)

Stage 2B established the current acceptance classifications and boundaries
reflected in this router. Acceptance status changes only when new dated execution
evidence is recorded. Documentation review or router updates do not promote
runbooks, local tests or static inspection to external sandbox or production proof.
