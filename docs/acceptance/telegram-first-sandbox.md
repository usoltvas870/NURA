# Telegram-first sandbox acceptance runbook

**STATUS: CURRENT LOCAL ACCEPTANCE RUNBOOK — NOT EXTERNAL OR PRODUCTION PROOF**

Authority: [canonical target](../product/NURA_1_0_1_5_PRODUCT_SPEC.md), [current implementation](../implementation/current-status.md), [acceptance index](README.md).

## Purpose and safety

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
full-report generation, automatic full-PDF delivery, and fresh-process
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
the refunded financial audit rows in anonymized form. Repeating deletion and
the old refund event remains safe and cannot recreate the user or entitlement.

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

## Safe-suite inventory contract

`tools/telegram_first_safe_suite.py` discovers actual `tests/**/test_*.py`
files, hashes them, applies only its checked-in exact exclusion tuple, assigns
every included file to exactly one of at most eight shards and verifies the one
approved Tarot asset deselection. It rejects missing expected exclusions,
duplicate/case-colliding paths, missing deselection nodes, failed collection,
failed shard execution, assignment gaps and worktree/manifest mutation. It
does not run excluded files and has no dynamic exclusion argument.

Current review limitation: the runner records skip/xfail/xpass counts but does
not yet fail on an unknown node or count change. Its Docker resource check also
uses non-raising commands and does not yet fail when the Docker daemon cannot
answer. Until a dedicated hardening stage closes these gaps, the accepted
aggregate and cleanup evidence remain historical evidence rather than a
general fail-closed guarantee for future suite changes.

Last accepted full safe-suite evidence:

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

## Required local processes in a real sandbox

- FastAPI API process for checkout pages and the payment webhook.
- Telegram bot process.
- Celery worker and Celery Beat for durable generation/delivery reconciliation.
- PostgreSQL and Redis.
- A public HTTPS reverse proxy for the YooKassa webhook and checkout URLs.

## Failure diagnosis and evidence retention

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

## Acceptance boundaries

- Local automated acceptance uses disposable infrastructure and fake external boundaries. Its current result is PASS.
- External sandbox acceptance uses an approved Telegram test bot, YooKassa test shop and public HTTPS routes. It has not been executed.
- Production launch requires separate legal/support and infrastructure/deployment evidence plus an explicit GO. It remains blocked.

## External sandbox smoke — explicit opt-in only

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
automatic Telegram PDF delivery; manual resend must reuse that report without
AI, Matrix, order, or payment side effects. Refunded orders must not be
delivered or shown in My Reports. Account deletion retains only anonymized
financial rows and removes production-defined Redis chat state.

## Release gates

Local acceptance passing means the project is ready for the operator's manual
external sandbox smoke. It does **not** mean production is ready. Production
remains blocked until the operator validates provider credentials, fiscal
configuration, HTTPS routing, legal/support URLs, monitoring, backups, and
the external Telegram/YooKassa smoke.
