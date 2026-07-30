# Telegram-First External Sandbox Runbook

**STATUS: RUNBOOK — NOT EXECUTION PROOF**

Authority: [canonical target](../product/NURA_1_0_1_5_PRODUCT_SPEC.md),
[current implementation](../implementation/current-status.md), and
[acceptance evidence router](README.md).

## 1. Purpose and evidence boundary

This document defines a manual, operator-controlled external sandbox procedure
for the Telegram-first NURA 1.0 path. It is a checklist and evidence contract,
not a completed sandbox record. No step is complete unless a separate dated,
redacted execution record identifies the tested baseline and captures the
required evidence.

Local tests use fake Telegram, YooKassa and AI boundaries. They are prerequisites,
not substitutes for this runbook. This runbook does not authorize production
credentials, real charges, deployment, legal approval or production launch.

## 2. Preconditions

Before execution, the operator must have a separately approved sandbox window
and confirm all of the following without writing secret values into the repository:

- an approved Telegram test bot and allowlisted test accounts;
- a YooKassa test shop with sandbox-only credentials and fiscal settings;
- an approved external AI/provider sandbox account or test boundary;
- an isolated sandbox PostgreSQL/Redis/Celery environment at the intended migration head;
- public sandbox-only HTTPS webhook, checkout and return URLs;
- redacted logs/monitoring and a bounded evidence location;
- rollback/cleanup ownership and a stop contact;
- the exact branch, commit and configuration profile to be tested;
- confirmation that no production token, shop, database or user data is in scope.

The current accepted local baseline is summarized in [current status](../implementation/current-status.md).
It does not waive any precondition above.

## 3. Environment and secrets boundary

- Use only sandbox/test credentials supplied through the approved runtime secret mechanism.
- Do not paste tokens, secret keys, DSNs, cookies, receipt email, provider objects,
  webhook bodies, report contents or personal data into this document or evidence.
- Use synthetic user data and an allowlisted Telegram test account.
- Verify the Telegram bot identity and YooKassa shop mode before the first external action.
- Keep sandbox and production URLs, queues, databases, Redis namespaces and monitoring distinct.
- Stop on any unexpected production hostname, real-money request, non-test recipient,
  secret disclosure or unexplained external call.
- The browser return is informational; only the provider-verified webhook may activate payment.

## 4. Telegram scenarios

Execute and record each scenario separately:

1. Start the approved test bot from a controlled deep link and verify attribution.
2. Complete onboarding with synthetic data; verify repeat `/start` does not destroy state.
3. Generate one mini-report; verify readable Telegram text, one PDF and repeat access.
4. Open My Reports/materials and resend the existing mini artifact without regeneration.
5. Open Daily Tarot twice in the same product period and verify the same stored result.
6. Exercise five successful delivered chat responses, verify that the sixth request is
   blocked before generation, then verify a five-response reset after `00:00 Europe/Moscow`.
   Use only the approved test bot and fake/local providers where the runbook prescribes them.
7. Open the 890 ₽ Full Matrix checkout CTA and verify that it points only to the test shop.
8. After verified sandbox payment, receive the full Telegram text followed by PDF automatically and repeat manual
   delivery from My Reports without new Matrix, AI, PDF, order or payment side effects.
9. Block/unblock the test bot where the provider permits and verify bounded failure handling.
10. Verify user-facing errors contain no stack trace, secret, provider payload or PII.

### 4.1. Broadcast, CTA and opt-out acceptance boundary

#### Target acceptance scenario

After the NURA 1.0 broadcast contour is implemented, an approved external
sandbox run must verify all of the following on one identified baseline:

- a controlled test send to approved recipients;
- selection of an approved segment;
- a stable campaign identifier;
- an inline CTA that opens the intended bot function;
- a per-user delivery state;
- duplicate prevention on repeated dispatch;
- bounded blocked-user handling;
- editorial opt-out and suppression;
- campaign attribution and conversion evidence required by the canonical target.

#### Current execution status

`IMPLEMENTATION GAP — NOT EXECUTABLE YET`.

The current generic transport and aggregate sent/failed totals documented by
the accepted [bot technical specification](../bot-spec.md#410-broadcasts) and
[bot UX map](../bot-ux-map.md#311-broadcast-receipt-cta-and-opt-out) do not prove
the target campaign, delivery, CTA, deduplication, opt-out/suppression or
attribution contract. The external scenario therefore cannot be executed in
full until that contour exists. This is an implementation gate, not a failed
sandbox result; the scenario has not been performed and must not be marked
complete. Do not send an uncontrolled broadcast to real users.

#### Exit condition

This scenario becomes executable only after evidence-backed implementation of
the corresponding NURA 1.0 contour. The later execution must still use an
approved sandbox window and produce a separate dated, redacted evidence record.

## 5. YooKassa scenarios

1. Create exactly one 890 RUB `full_matrix` test payment with receipt fields populated
   from sandbox configuration and `save_payment_method` disabled.
2. Confirm the UI and provider identify the transaction as sandbox/test and that no real charge occurs.
3. Verify `payment.succeeded` through the public sandbox webhook and confirm amount,
   currency, product and provider identity checks before activation.
4. Replay the same success event and verify no duplicate entitlement, report, job or delivery.
5. Exercise an abandoned/failed payment and a user retry; verify the original profile/report state remains.
6. Execute a sandbox refund and verify the provider-verified refund path.
7. Exercise duplicate and out-of-order success/refund events; capture the final durable state.
8. Verify return-page navigation alone cannot activate the order.

## 6. Report generation and delivery scenarios

- Confirm payment success persists before generation begins.
- Verify one durable generation job and one canonical full PDF artifact.
- Verify temporary AI/render failure is retryable without another payment.
- Verify automatic delivery creates one durable receipt and fresh-process replay does not resend.
- Verify manual resend reuses the stored artifact or Telegram file ID and does not regenerate content.
- Verify the current implementation boundary honestly: the persisted full-report
  text precedes the PDF, while external Telegram sandbox behavior remains unproven.
- Inspect representative mini/full content for formatting and safety without storing the report body in evidence.

## 7. Refund and retry scenarios

- Refund before or during generation must fence later worker persistence and delivery.
- Refund during delivery must converge on a revoked, non-deliverable order state.
- A refunded report must be hidden from My Reports and manual resend must fail safely.
- Replayed refund/success/provider events must not recreate access or duplicate side effects.
- Retry must preserve the same logical order/job/artifact identities and never create a second charge.
- Record provider event IDs only in a redacted or hashed form approved for evidence.

## 8. Account deletion/privacy scenarios

- Request deletion through the current user flow using synthetic test data.
- Verify active user/report/delivery data and production-defined Redis chat state are removed.
- Verify only the de-identification fields implemented by the current deletion contract;
  do not classify retained financial rows as fully anonymized.
- Record the current privacy gap: retained `PaymentAttempt.fiscal_email` is not cleared
  by `AccountDeletionService`. Use synthetic data and require a separate owner/legal
  decision before treating fiscal retention or full anonymization as accepted.
- Repeat deletion and an old refund event; verify neither recreates the user nor entitlement.
- Confirm logs, alerts and evidence contain no birth date, chat/report content, receipt email,
  access token, cookie, secret, raw webhook or stack trace.
- Legal retention and production privacy approval remain separate gates.

## 9. Evidence capture requirements

For every scenario record:

- date/time, operator and approved window identifier;
- repository branch, full commit SHA, Alembic head and sandbox environment name;
- command or manual step identifier and expected result;
- redacted Telegram/YooKassa/AI identifiers sufficient to correlate the run;
- durable database/job/delivery state before and after, without content or credentials;
- external-attempt count, HTTP/provider result category and bounded log references;
- cleanup result and any defect/stop condition;
- explicit evidence level: external sandbox, never production.

Evidence must be stored in a new, separately authorized dated record. Do not edit
older dated evidence to make it appear that it ran on the new baseline.

## 10. PASS/FAIL criteria

`PASS — EXTERNAL SANDBOX` requires all mandatory scenarios to complete on one
identified baseline with test-only providers, no real charge, no duplicate durable
side effect, no secret/PII disclosure, correct refund/deletion outcomes and complete
redacted evidence. Provider-specific partial results must be labelled separately;
Telegram PASS cannot imply YooKassa or AI PASS.

`FAIL — EXTERNAL SANDBOX` applies to any incorrect durable state, duplicate side
effect, missed refund fence, secret/PII exposure, real-money risk, production contact,
unexplained external call, incomplete cleanup, or missing required evidence.

An unexecuted or partially executed checklist is neither PASS nor production ready.

## 11. Exit conditions

- Stop immediately on a wrong bot/shop/environment, production credential, real charge,
  unexpected recipient, provider ambiguity, secret/PII exposure or destructive state drift.
- Stop the affected scenario on the first unbounded duplicate or inconsistent durable state.
- Preserve only bounded, redacted evidence; do not retry blindly.
- Clean up owned sandbox resources and verify no owned process/container/temporary route remains.
- File the defect and require a separate code/test session for implementation fixes.
- Production remains blocked regardless of sandbox result until separate legal,
  infrastructure, monitoring, backup/restore, support and owner GO gates pass.

## 12. Current execution status

| Layer | Status | What exists | What is not proven |
|---|---|---|---|
| Local fake-provider tests | Accepted at their recorded baselines | Unit/integration, disposable PostgreSQL/Redis and local race evidence | External provider or production behavior |
| External Telegram sandbox | `NOT EXECUTED` | This runbook | Bot identity, UX, delivery, blocked-bot and retry behavior |
| Broadcast/CTA/opt-out target boundary | `IMPLEMENTATION GAP — NOT EXECUTABLE YET` | Target scenario only; accepted bot docs record the current gap | Campaign, per-user delivery, CTA, deduplication, opt-out/suppression and attribution; external execution was not performed |
| External YooKassa sandbox | `NOT EXECUTED` | This runbook | Test-shop payment, receipt, webhook, refund and ordering behavior |
| External AI/provider sandbox | `NOT EXECUTED` | Local fake-provider contracts | Provider credentials, content quality, latency, failure and cost behavior |
| Production | `NOT PROVEN` | Deployment instructions and tracked topology only | Availability, launch approval, legal/operations readiness and real traffic |

No step in this document was executed during documentation Write Session 6.

## 13. References

- [Acceptance evidence router](README.md)
- [Dated Telegram-first readiness evidence](evidence/telegram-first-v1-readiness-review.md)
- [Current implementation mirror](../implementation/current-status.md)
- [Canonical NURA 1.0/1.5 target](../product/NURA_1_0_1_5_PRODUCT_SPEC.md)
- [Current Telegram technical specification](../bot-spec.md)
- [Current Telegram UX map](../bot-ux-map.md)
- [Current pricing/access map](../pricing.md)
- [Payment audit evidence](../audits/PAYMENT_FLOW_AUDIT.md)
- Root [deployment instructions](../../DEPLOY.md)

## Appendix A. Local acceptance runner reference

This runbook validates the local Telegram-first MVP path without accessing
Telegram, YooKassa, or production data. The command creates labelled,
disposable PostgreSQL 16 and Redis containers and removes them in `finally`.
It disables dotenv loading for its child processes, uses an allowlisted process
environment, and never prints credentials.

Run from `nura_app/`:

```powershell
python tools/telegram_first_sandbox_acceptance.py
```

Runner modes have distinct purposes:

- default runner: performs migration/runtime probing, service boot, security, failure/retry, cumulative golden path and the scoped contract suite in one disposable PostgreSQL 16/Redis environment;
- `--service-boot-only`: proves the required FastAPI, Telegram, Celery worker and Celery Beat topology twice without polling or business-task dispatch;
- `--security-only`: runs the isolated PostgreSQL security matrix, redaction/Sentry probes and fail-closed cleanup evidence;
- `--failure-retry-only`: proves webhook, generation and delivery failure/retry plus fresh-process replay without duplicate side effects;
- `--golden-path-only`: runs the ordered cumulative Telegram-first PostgreSQL golden-path segments and durability replay;
- `--safe-suite-only`: runs the deterministic file-sharded pytest suite and per-shard cleanup/immutability checks without creating the main acceptance sandbox.

### Chat delivery boundary (local implementation)

Free-chat now stores one request key, response and delivery record. Telegram delivery persists the completed chunk index after every send and resumes at that index after a retry; it commits the daily quota only after all chunks are durable. Retryable transport failures keep the reservation, while terminal or expired deliveries release it. The legacy PWA receives a stable delivery ID and must call its owned ACK endpoint after rendering; that ACK is idempotent and is the only web quota-commit point. This is local code/test evidence only: no Telegram, PWA browser, AI, YooKassa or production sandbox was executed by this change.

To run the completed cumulative PostgreSQL golden path:

```powershell
python tools/telegram_first_sandbox_acceptance.py --golden-path-only
```

To run only the required local service topology proof:

```powershell
python tools/telegram_first_sandbox_acceptance.py --service-boot-only
```

To run only the isolated PostgreSQL failure/retry chain:

```powershell
python tools/telegram_first_sandbox_acceptance.py --failure-retry-only
```

The runner creates the failure/retry database inside the same disposable
PostgreSQL 16 container as the cumulative database and reuses the same Redis
server. `NURA_FAILURE_RETRY_DATABASE_URL` is distinct from
`NURA_GOLDEN_PATH_DATABASE_URL`; the failure test therefore cannot mutate the
cumulative persona and does not start nested containers. Both databases are
removed with the owning PostgreSQL container in `finally`.

The default runner order is migration/runtime probing, required-service boot,
the isolated failure/retry chain, the cumulative golden path, and the scoped
contract suite, with security acceptance included before failure/retry. Each
`--*-only` mode retains its independent meaning.
The security stage also invokes the service-boot proof. Because one service-boot
proof performs two stack cycles, the default runner currently performs four
stack cycles in total: two before security and two inside security.
The failure/retry stage runs both the PostgreSQL chain and the directly relevant
mini, Tarot, chat, checkout/webhook, generation/reconciliation, delivery, refund,
and deletion contract files. Cleanup is fail-closed: an owned container or
anonymous volume that remains after bounded removal makes the runner fail.

This mode applies Alembic head once, prepares the synthetic attribution link
through the project CLI, and runs the ordered cumulative nodes in fresh pytest
processes against the same runner-owned PostgreSQL database: start/onboarding,
mini-report, Daily Tarot, lifetime chat, checkout, verified webhook, and
full-report generation, automatic full-text-then-PDF delivery, and fresh-process
idempotency replays.
It uses real aiogram updates, routers, Dispatcher, and MemoryStorage with
in-memory Telegram transports. The onboarding `.delay(...)` handoff is
reconstructed from the durable User, then the registered generation and
delivery tasks run synchronously through the existing test seam without a
Celery broker. Mini AI and Telegram are fake; the production Matrix service,
PDF renderer, persistence lifecycles, My Reports, and delivery tasks are real.
Daily Tarot uses the production handler/application/repository lifecycle with a
fixed aware UTC clock and real timezone/card-selection helpers. Its AI and
Telegram transports are fake; scheduled push tasks are not invoked. The
segment also proves that Daily Tarot leaves the five-message lifetime chat
quota untouched.

The full-report segment preserves the report and generation job created by the
verified webhook. The production dispatcher transitions the job from
`pending_dispatch` to `queued`, then the registered
`core.tasks.process_report_generation_job` task is invoked synchronously. It
uses the production Matrix calculation, full-report response validation, PDF
renderer, artifact hash/MIME/size persistence, report/job completion, and one
automatic-delivery dispatch. The existing queued delivery is then continued
through the registered `core.tasks.deliver_full_report` task synchronously.
It uses the durable claim/fencing lifecycle and sends the persisted canonical
PDF through the fake Telegram boundary; it does not recalculate Matrix, AI, or
PDF output. The production contract currently sends the PDF with its caption,
without a separate ready message. A fresh-process replay proves no second
Telegram send occurs.

The manual-resend segment then reaches the production `My Reports` aiogram
callbacks (`reports:list`, `reports:view`, `reports:send`) for that same full
report. Ownership is resolved through `MyReportsService`; the callback ID is
the stable logical-request key. A double callback creates or reuses one manual
delivery row, and the registered full-delivery task claims it with the normal
fencing protocol. It reuses the automatic delivery's persisted Telegram
`file_id`, so the fake boundary receives a file-ID document request rather
than PDF bytes. The test proves one new message ID, no Matrix/AI/PDF/YooKassa
side effects, no mutation of the canonical artifact or automatic receipt, and
no additional send on a fresh-process replay. The invalid-file-ID upload
fallback remains covered by the focused delivery regression suite.

The final `full_restart_durability` node starts one additional, real pytest
child process using the same `sys.executable`, PostgreSQL URL and Redis URL.
It recreates its engine, session factory, repositories, services and task
runtime from environment configuration only. The child reads the complete
cumulative persona through production repositories/services, replays Daily
Tarot, duplicate/exhausted chat quota, verified webhook, completed generation
and both completed full-report deliveries, and proves that fake external
boundaries are not reached. Parent and child compare the accepted PostgreSQL
entity/receipt and artifact hash/size snapshot plus Redis chat-history snapshot
before and after the child. It is an application-process restart proof, not a Redis or container
restart; PostgreSQL remains the source of truth for the lifetime quota.

The final destructive node, `refund_and_account_deletion_replay`, uses the
same paid order, completed reports, and delivered receipts. A production-shaped
YooKassa refund webhook is verified through `FullMatrixCheckoutService`; it
persists the `payment.refunded` event, marks the order and attempt refunded,
revokes `has_matrix`, hides the full report from My Reports, and blocks a new
manual resend without a Telegram, Matrix, AI, or PDF side effect. A fresh
process repeats the same event identity without another provider lookup.
The production `AccountDeletionService` then removes the active account and
report/delivery rows, clears the user's Redis chat-history keys, and retains
refunded financial audit rows. Current field clearing does not remove
`PaymentAttempt.fiscal_email`, so the retained rows are not evidence of full
anonymization or legal retention acceptance. Repeating deletion and the old
refund event remains safe and cannot recreate the user or entitlement.

The runner sets `APP_ENV=test`, migrates a blank PostgreSQL database to the
current Alembic head, performs one `downgrade -1`/repeat-upgrade proof, and
runs the scoped contract suite. It uses fakes at the Telegram, YooKassa, and
AI boundaries. It also makes direct runtime configuration probes against its
own PostgreSQL 16 and Redis containers. The selected contract tests retain
their own fixtures; `tests/test_celery_async_postgres.py` creates a separate
PostgreSQL container for its process-local async Celery lifecycle proof.

The source of truth for disposable PostgreSQL 16/Redis ownership, labels,
ports, child-process environment and cleanup is
`tools/telegram_first_sandbox_acceptance.py`. The runner owns only the resources
it creates and fails closed if those labelled resources remain. Local
acceptance must use fake Telegram, YooKassa and AI boundaries; real external
calls are prohibited.

### A.1. Safe-suite inventory contract

`tools/telegram_first_safe_suite.py` discovers actual `tests/**/test_*.py`
files, hashes them, applies only its checked-in exact exclusion tuple, assigns
every included file to exactly one of at most eight shards and verifies the one
approved Tarot asset deselection. It rejects missing expected exclusions,
duplicate/case-colliding paths, missing deselection nodes, failed collection,
failed shard execution, assignment gaps and worktree/manifest mutation. It
does not run excluded files and has no dynamic exclusion argument.

Current review limitation: the runner records skip/xfail/xpass counts but does
not yet fail on an unknown node or count change. At committed baseline `b70d6cc`,
Docker inventory/query errors and cleanup failure are fail-closed and fail the
suite; the older dated `1059` review's non-raising Docker-check limitation is
historical and must not be promoted to the current runner. The remaining
skip/xfail/xpass drift gap means future aggregates still require explicit review.

Historical dated safe-suite evidence preserved for the earlier runner baseline
(not the current `b70d6cc` summary and not a new execution):

- 80 files discovered: 74 tracked and 6 untracked;
- 66 included, 14 exact exclusions, 8 shards;
- 1082 collected, 1059 passed, 22 skipped, 1 approved deselection;
- 0 failed, 0 collection errors, 0 missing files, 0 duplicate files;
- manifest SHA-256: `9a0695a156a30651d03c971802580ddb775af34aab51f1839afbd1339539dfda`;
- working-tree immutability PASS.

For inventory-only reconfirmation, run:

```powershell
python tools/telegram_first_safe_suite.py --inventory-only
```

Do not rerun the full shards for documentation-only changes.

The full runner also starts the required v1 processes twice against the same
disposable PostgreSQL 16 and Redis: Uvicorn `api.main:app` on a loopback random
port, a real Celery `core.tasks` worker using the `solo` pool and a private
queue, and a separate Telegram runtime child process. API `/ready` proves DB
and Redis connectivity, Celery responds to `control.ping` and exposes the
mini-generation, full-generation, and full-delivery tasks, and the Telegram
child creates the production `Bot`/`Dispatcher`, registers routers and runs
startup/shutdown hooks. The child stops before command registration and polling,
so its real Telegram API call count remains zero. Domain record counts are
compared before and after each boot; synthetic secrets are checked against
captured service logs.

Celery Beat is included because the canonical production Compose topology starts
it. The proof gives it a disposable schedule database and stops it before a
periodic interval is due, so no scheduled business task is executed. `admin-bot`,
the PWA development server and external reverse proxy are excluded from this
local proof.

### A.2. Required local processes in a real sandbox

- FastAPI API process for checkout pages and the payment webhook.
- Telegram bot process.
- Celery worker and Celery Beat for durable generation/delivery reconciliation.
- PostgreSQL and Redis.
- A public HTTPS reverse proxy for the YooKassa webhook and checkout URLs.

### A.3. Failure diagnosis and evidence retention

On failure, diagnose in this order:

1. identify the first non-zero runner stage and preserve its bounded summary;
2. confirm the Alembic head and that the child environment points only to the runner-owned databases and Redis;
3. inspect the failing stage's safe log category without copying credentials, payloads, report contents or temporary paths into durable documentation;
4. confirm owned subprocesses, containers, volumes, ports and security context were removed;
5. rerun only the narrow failing mode after the cause is understood.

The operator should retain the command/mode, branch, HEAD, Alembic revision,
exit code, aggregate test counts, safe-suite manifest SHA-256, cleanup result,
external-attempt count and a redacted defect summary. Do not retain tokens,
DSNs, receipt email, provider objects, webhook payloads, report/PDF contents,
synthetic sentinel values or machine-specific temporary paths in repository
documentation.

### A.4. Acceptance boundaries

- `DATED LOCAL AUTOMATED ACCEPTANCE — PASS` applies only to the earlier manifest-specific `1059` baseline above; disposable infrastructure and fake external boundaries do not prove the current code baseline or any external environment.
- External sandbox acceptance uses an approved Telegram test bot, YooKassa test shop and public HTTPS routes. It has not been executed.
- Production launch requires separate legal/support and infrastructure/deployment evidence plus an explicit GO. It remains blocked.

### A.5. Historical external-smoke notes

Do not send a real Telegram message or create a YooKassa payment unless the
operator has deliberately set `ALLOW_SANDBOX_EXTERNAL_SMOKE=1` in the
dedicated sandbox environment. This repository command does not implement the
external smoke itself.

Before that smoke, the operator must confirm:

- Telegram test-bot token, bot username, and an allowlisted test chat.
- YooKassa test-shop credentials, receipt/fiscal values, and a 890 RUB test
  receipt for `full_matrix`; `save_payment_method` remains disabled.
- Public HTTPS webhook, checkout, return, legal, and support URLs.
- PostgreSQL/Redis/Celery sandbox services, migration backup/rollback plan,
  logs and monitoring.

The browser return page is informational only. The provider-verified webhook
is the sole activation path. A paid order produces one full report and one
automatic Telegram text-then-PDF delivery; manual resend must reuse that report without
AI, Matrix, order, or payment side effects. Refunded orders must not be
delivered or shown in My Reports. Account deletion removes production-defined
Redis chat state and retains financial rows; `PaymentAttempt.fiscal_email`
currently remains, so full anonymization and legal retention stay unproven.

### A.6. Release gates

Local acceptance is only a prerequisite for a separately approved external
sandbox window. It does not authorize the smoke, supply sandbox GO, or mean
production is ready. Production remains blocked until the operator validates
provider credentials, fiscal configuration, HTTPS routing, legal/support URLs,
monitoring, backups and the external Telegram/YooKassa/AI sandbox, followed by
separate owner GO decisions.

### A.7. Full-report text + PDF local contract

For a completed, paid full report, local tests must prove persisted text chunks
are sent before the stored PDF, with fenced progress after every successful
Telegram call. Retry is at-least-once at the external boundary and must not
regenerate AI content, Matrix data, checkout, payment or chat quota. Historical
PDF-only rows are not retro-delivered. This runbook is not external-sandbox
execution proof.
