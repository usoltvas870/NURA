# Telegram-first v1 readiness review

**STATUS: DATED LOCAL EVIDENCE — NOT A STANDING PRODUCT OR PRODUCTION CONTRACT**

This review is retained as evidence for its recorded baseline. Current authority: [canonical target](../../product/NURA_1_0_1_5_PRODUCT_SPEC.md), [current implementation](../../implementation/current-status.md), and [acceptance index](../README.md).

Review date: 28 July 2026.

## 1. Executive verdict

| Boundary | Verdict |
|---|---|
| LOCAL IMPLEMENTATION | **PASS** |
| LOCAL AUTOMATED ACCEPTANCE | **PASS** |
| EXTERNAL SANDBOX | **NOT EXECUTED** |
| PRODUCTION LAUNCH | **BLOCKED** |

Production remains blocked because real Telegram credentials and bot environment, the YooKassa test shop and receipt flow, the external HTTPS webhook/return flow, legal/support links, and production infrastructure/deployment gates have not been verified.

The readiness documentation is complete, but the current docs-stage cannot authorize the final cumulative commit. Read-only review found that `bot/main.py` exits successfully when the Telegram token is missing, and that the safe-suite does not fail on unknown skip/xfail/xpass changes or an unavailable Docker cleanup check. The exact worktree allowlist in `nura_app/tests/test_alembic_smoke_harness_contract.py` also predates this mandatory review file. These Python/test changes are outside this documentation-only stage and require separate narrow fix-stages followed by the relevant regression gates.

## 2. Scope of Telegram-first v1

Telegram-first v1 covers attributed onboarding, birth-date capture, one idempotent mini-report with Telegram text/PDF delivery and My Reports access, a free daily Tarot card, the lifetime five-message chat allowance, one-time Full Matrix checkout through YooKassa, verified webhook activation, durable full-report generation, automatic Telegram PDF delivery, repeated manual delivery, refund revocation and account-deletion replay.

The Telegram bot is the primary v1 interface. PWA documents are retained as legacy/history. Subscription, gift access, return messages, recurring payments and Telegram Stars are future scope, not current launch blockers.

## 3. What is implemented

- Durable Telegram identity/attribution and onboarding.
- Mini-report generation, canonical PDF persistence, idempotent delivery and repeat access.
- Free Daily Tarot and durable lifetime chat quota.
- One-time Full Matrix checkout, verified success/refund handling and fiscal configuration boundaries.
- Durable generation jobs, canonical full PDF, automatic delivery, My Reports and manual resend.
- Refund entitlement revocation and account deletion with anonymized financial retention.
- Log/Sentry redaction, fail-closed external-call guards and local service topology probes.
- Deterministic cumulative PostgreSQL/Redis acceptance runner and full safe-suite inventory/shards.

## 4. Local automated acceptance

- Golden path: PostgreSQL 16, Redis, real Alembic migrations, all cumulative segments PASS, fresh-process replay PASS.
- Service boot: FastAPI, Telegram runtime, Celery worker, Celery Beat, simultaneous stack and second boot PASS; external calls = 0.
- Failure/retry: webhook, generation and delivery failure/retry plus fresh-process replay PASS; duplicate side effects = 0.
- Security: open P0/P1/P2 = 0; Sentry envelope scrubbed; external attempts = 0; sentinel scan and cleanup PASS.
- Safe-suite: 80 discovered, 66 included, 14 excluded, 8 shards, 1082 collected, 1059 passed, 22 skipped, 1 deselected, 0 failed; immutability PASS.

Safe-suite manifest SHA-256: `9a0695a156a30651d03c971802580ddb775af34aab51f1839afbd1339539dfda`.

## 5. Cumulative diff audit

Every modified or untracked file has an accepted-stage origin and is intended for the final cumulative commit. No generated repository artifact or unintended/unexplained file was found. `T` means tracked and `U` means untracked.

| Path | State | Category | Originating accepted stage | Purpose / kind | Final commit | Concern |
|---|---:|---|---|---|---:|---|
| `STATE.md` | T | documentation | cumulative stages / readiness | durable project state / docs | yes | none after removal of added temporary log paths |
| `docs/README.md` | T | documentation | sandbox/readiness | current-v1 documentation routing / docs | yes | none |
| `docs/launch-checklist.md` | T | documentation | sandbox/readiness | local/external/production gates / docs | yes | none |
| `docs/telegram-first-sandbox-runbook.md` | U | documentation | sandbox acceptance | runner/operator instructions / docs | yes | none |
| `docs/telegram-first-v1-readiness-review.md` | U | documentation | final readiness | verdict, evidence and operator decision / docs | yes | exact worktree allowlist must be updated in a separate test stage |
| `nura_app/api/logging.py` | U | production security fix | log redaction/security | access-log and Sentry scrubbing / runtime | yes | none |
| `nura_app/api/main.py` | T | production security fix | log redaction/security | installs scrubbers / runtime | yes | none |
| `nura_app/api/routes/payment.py` | T | production integration fix | checkout/refund/security | verified event routing and capability check / runtime | yes | none |
| `nura_app/api/routes/reports.py` | T | production security fix | log redaction/security | removes report capability from warning / runtime | yes | none |
| `nura_app/api/routes/web.py` | T | application/repository lifecycle fix | account deletion replay | supplies Redis cleanup boundary / runtime | yes | none |
| `nura_app/bot/handlers/errors.py` | T | production security fix | log redaction/security | avoids raw exception payloads / runtime | yes | none |
| `nura_app/bot/handlers/start.py` | T | application/repository lifecycle fix | account deletion replay | supplies Redis cleanup boundary / runtime | yes | none |
| `nura_app/bot/main.py` | T | service-boot test/tool | final local service boot | runtime factory and dependency lifecycle seam / runtime | yes | missing token is logged but process exits 0; separate runtime fix required |
| `nura_app/core/config.py` | T | acceptance infrastructure | sandbox isolation | opt-out from ambient dotenv / runtime seam | yes | none |
| `nura_app/core/models.py` | T | application/repository lifecycle fix | Daily Tarot golden path | removes ORM/schema-only drift / runtime | yes | none |
| `nura_app/core/repositories/report.py` | T | application/repository lifecycle fix | mini persistence / refund replay | canonical mini PDF and paid full-report visibility / runtime | yes | none |
| `nura_app/core/repositories/report_lifecycle.py` | T | application/repository lifecycle fix | full report generation | accepts order-linked payment confirmation / runtime | yes | none |
| `nura_app/core/services/account_deletion.py` | T | application/repository lifecycle fix | refund/account deletion replay | anonymization and Redis cleanup / runtime | yes | none |
| `nura_app/core/services/full_matrix_checkout.py` | T | production integration fix | checkout/webhook/refund | durable verified success/refund behavior / runtime | yes | none |
| `nura_app/core/services/telegram_report_delivery.py` | T | application/repository lifecycle fix | full delivery/retry | fencing, entitlement and repeat-delivery behavior / runtime | yes | none |
| `nura_app/tests/conftest.py` | T | acceptance infrastructure | cumulative runners | isolated test environment bootstrap / test | yes | none |
| `nura_app/tests/test_alembic_smoke_harness_contract.py` | T | acceptance infrastructure | cumulative worktree safety | exact cumulative allowlist / test | yes | missing mandatory readiness file in allowlist |
| `nura_app/tests/test_daily_tarot_migration_contract.py` | T | golden-path test | Daily Tarot | asserts ORM/migration parity / test | yes | none |
| `nura_app/tests/test_full_matrix_account_deletion.py` | T | failure/retry test | refund/account deletion replay | retained finance and Redis cleanup / test | yes | none |
| `nura_app/tests/test_full_matrix_checkout.py` | T | failure/retry test | checkout/refund/security | success/refund/replay verification / test | yes | none |
| `nura_app/tests/test_matrix_report_worker_lifecycle.py` | T | failure/retry test | full report generation | order-linked claim/reconciliation / test | yes | none |
| `nura_app/tests/test_mini_report_telegram_delivery.py` | T | golden-path test | mini-report delivery | canonical artifact and replay / test | yes | none |
| `nura_app/tests/test_report_generation_reconciliation.py` | T | failure/retry test | generation retry | reconciliation replay / test | yes | none |
| `nura_app/tests/test_sandbox_settings_isolation.py` | U | acceptance infrastructure | sandbox acceptance | dotenv isolation contract / test | yes | none |
| `nura_app/tests/test_security_rendering_gate.py` | T | security test | security rendering gate | expanded rendering/redaction contracts / test | yes | none |
| `nura_app/tests/test_telegram_first_postgres_failure_retry.py` | U | failure/retry test | failure/retry review | PostgreSQL retry chain / test | yes | none |
| `nura_app/tests/test_telegram_first_postgres_golden_path.py` | U | golden-path test | cumulative golden path | ordered v1 journey and replays / test | yes | none |
| `nura_app/tests/test_telegram_first_safe_suite_contract.py` | U | safe-suite test/tool | full safe-suite | exact assignment/exclusion contract / test | yes | none |
| `nura_app/tests/test_telegram_first_security_acceptance.py` | U | security test | log redaction/security | security matrix probes / test | yes | environment skips are explicit, not hidden |
| `nura_app/tests/test_telegram_first_service_boot.py` | U | service-boot test/tool | final local service boot | topology and cleanup contract / test | yes | Docker availability skip is explicit |
| `nura_app/tools/sitecustomize.py` | U | acceptance infrastructure | sandbox isolation | child-process import/environment seam / tool | yes | none |
| `nura_app/tools/telegram_first_bot_boot_probe.py` | U | service-boot test/tool | final local service boot | production dispatcher boot without polling / tool | yes | none |
| `nura_app/tools/telegram_first_safe_suite.py` | U | safe-suite test/tool | full safe-suite | inventory, shards and immutability / tool | yes | unknown skip/xfail and unavailable Docker cleanup check do not fail the run |
| `nura_app/tools/telegram_first_sandbox_acceptance.py` | U | acceptance infrastructure | sandbox through security | disposable orchestration and runner modes / tool | yes | none |
| `nura_app/tools/telegram_first_security_context.py` | U | security test | log redaction/security | safe registry, evidence and cleanup / tool | yes | none |
| `nura_app/tools/telegram_first_security_guard.py` | U | security test | log redaction/security | blocks marked non-loopback attempts / tool | yes | none |
| `nura_app/tools/telegram_first_sentry_probe.py` | U | security test | log redaction/security | scrubbed SDK envelope probe / tool | yes | none |
| `nura_app/tools/telegram_first_service_boot.py` | U | service-boot test/tool | service boot/failure cleanup | process topology and Windows Job cleanup / tool | yes | none |

Unintended/unexplained files: **0**.

### Safe-suite contract review

- Exclusions are one checked-in tuple of 14 paths; the runner accepts no dynamic exclusion input and rejects missing expected exclusions.
- All 66 included files are assigned exactly once across eight deterministic shards; excluded files have no shard and are never passed to pytest.
- The only deselection is the checked-in Tarot derivative node. Its existence is validated before a manifest is built.
- Collection and execution exit codes are checked per shard; any failure makes the runner non-zero. Missing/duplicate assignments and worktree/manifest mutation also fail the run.
- No `xfail` was introduced. Environment-dependent skips in the security/service tests are explicit and were counted in the accepted aggregate. However, the runner does not pin approved skip nodes/reasons or reject future skip/xfail/xpass drift; this requires hardening before commit readiness can be accepted.
- Docker cleanup commands use non-raising execution and their return codes are not part of the failure gate. A daemon failure can therefore look like an empty resource inventory; this requires a fail-closed cleanup-check fix.
- Alembic head is read through `python -m alembic heads`; the exact worktree contract remains strict rather than silently ignoring extra files.

## 6. Local acceptance evidence index

| Stage | Scope / production boundary | Durable state | Key proof | Result | Relevant files | Limitation |
|---|---|---|---|---|---|---|
| Security Rendering Gate | untrusted content to HTML/PDF/Telegram | escaped rendering contract | targeted rendering tests | PASS | `test_security_rendering_gate.py` | external clients fake |
| Telegram Identity and Attribution | Telegram update to User/attribution | canonical identity/link | real aiogram PostgreSQL path | PASS | golden-path test | sandbox bot pending |
| Mini-report Persistence and Idempotency | generation repository | one generation/report | replay without duplicates | PASS | report repository, mini tests | AI fake |
| Mini-report Application Use Case | service/task boundary | completed mini state | production task seam | PASS | golden-path test | broker not required here |
| Mini-report Telegram Delivery | Telegram adapter | canonical PDF and receipts | text/PDF replay proof | PASS | delivery service/tests | Telegram fake |
| My Reports and Repeated Delivery | callbacks/service ownership | reusable mini/full reports | repeated callback proof | PASS | golden-path test | real bot pending |
| Lifetime Five-Message Chat Limit | Telegram/Web quota boundary | five durable usages | sixth request exhausted after restart | PASS | golden-path/failure contracts | no subscription scope |
| Free Daily Tarot Card | handler/application/repository | one completed daily draw | same/fresh-process replay | PASS | model and golden-path tests | AI/Telegram fake |
| One-time Full Matrix Checkout | checkout/provider boundary | pending order/attempt | durable non-activating checkout | PASS | checkout service/tests | test shop pending |
| Full Matrix Delivery/Repeated Access | generation/delivery boundary | canonical full PDF and receipts | automatic/manual replay | PASS | lifecycle/delivery tests | external delivery pending |
| start_and_onboarding | real aiogram to PostgreSQL | completed User/onboarding | fresh Dispatcher/process replay | PASS | golden-path test | in-memory Telegram transport |
| mini_report | task/service/repository | mini artifact and deliveries | generation/delivery replay | PASS | golden-path test | fake AI/Telegram |
| daily_tarot | handler/application/repository | durable draw | same/fresh-process replay | PASS | golden-path test | scheduled push excluded |
| lifetime_chat | handler/service/repository | durable quota ledger | duplicate and sixth-request replay | PASS | golden-path test | v1 free quota only |
| checkout | API/service/repository | order and attempt | capability and create proof | PASS | golden-path/checkout tests | no real charge |
| verified_webhook | API/provider verification | paid event/report/job | duplicate fresh-process replay | PASS | checkout/failure tests | provider fake |
| full_report_generation | task/repository lifecycle | completed job and artifact | task replay without Matrix/AI/PDF | PASS | lifecycle/golden tests | AI fake |
| automatic_delivery | registered task/Telegram boundary | automatic receipt/file ID | fresh-process no-send replay | PASS | delivery/golden tests | Telegram fake |
| manual_resend | My Reports callback/task | separate manual receipt | double callback and replay | PASS | golden-path test | invalid file-ID separately covered |
| full_restart_durability | fresh application process | unchanged PostgreSQL/Redis snapshot | child-process replay | PASS | golden-path test | not a DB/container restart |
| refund_and_account_deletion_replay | verified refund/deletion | revoked entitlement, anonymized finance | duplicate refund/delete replay | PASS | checkout/deletion tests | external refund pending |
| final local service boot | required runtime topology | no domain mutation | two full boots | PASS | service-boot tool/test | reverse proxy excluded |
| failure/retry integration | webhook/generation/delivery | terminal idempotent states | PostgreSQL retry chain | PASS | failure-retry test/tool | external providers fake |
| log redaction/security | logs, Sentry, sockets | bounded safe evidence | 18-row matrix; open P0/P1/P2=0 | PASS | logging/security tools/tests | production monitoring pending |
| full safe-suite shards | repository test inventory | manifest and immutable worktree | 8 shards; 1059 pass; 0 fail | PASS | safe-suite tool/test | accepted run not repeated for docs |

## 7. Known technical limitations

- Local acceptance uses fake Telegram, YooKassa and AI boundaries; it is not external sandbox evidence.
- Fresh-process replay proves application-process durability, not PostgreSQL/Redis/container restart recovery.
- Delivery retains the documented send-before-terminal-commit and entitlement TOCTOU windows; the evidence does not claim mathematical exactly-once transport.
- Celery Beat is booted with a disposable schedule and stopped before a periodic business task becomes due.
- The public HTTPS reverse proxy, production monitoring, backups and restore are outside the local proof.
- The exact worktree allowlist contract needs the mandatory readiness review path added in a separate test-authorized stage.
- `bot/main.py` currently returns normally after logging a missing/placeholder Telegram token, producing a misleading zero process exit; a startup regression and non-zero failure boundary are required.
- Safe-suite future skip/xfail drift and Docker cleanup-check availability are not fail-closed; exact approved skip policy and cleanup command status must become part of the contract.

## 8. External sandbox gates

Status: **NOT EXECUTED**.

Telegram requires an approved test bot, sandbox-only token, username/deep link, webhook or polling decision, allowlisted test account, onboarding, mini text/PDF, Daily Tarot, chat quota, checkout CTA, My Reports, full PDF delivery/repeat, deletion and blocked-bot behavior.

YooKassa requires a test shop, sandbox credentials, fiscal settings, public HTTPS webhook/return routes, success/refund/receipt flows, confirmation of no real charge, duplicate webhook and out-of-order refund/success checks.

## 9. Production and legal gates

Status: **NOT EXECUTED**. Required evidence includes TLS, reverse proxy, firewall, production secret store, backup/restore, monitoring, domain/URLs, offer, privacy policy, any required user agreement, support contact and response process.

## 10. Go/no-go rules

The final cumulative commit is GO only when the diff is fully explained, unintended files = 0, documents agree, accepted local evidence is preserved, external gates remain explicitly pending, secrets/PII are absent, the exact documentation/state contracts pass, and no commit has yet been created.

Production is NO-GO until Telegram and YooKassa external sandbox, legal/support verification, and infrastructure/deployment review pass. Any real payment before the sandbox/test environment is confirmed is NO-GO. Any production bot token used in local acceptance is NO-GO.

## 11. Operator sequence

1. Run a narrow Telegram startup fail-closed fix-stage and its entrypoint/service-boot regressions.
2. Run a narrow safe-suite hardening stage for exact approved skips/xfail policy and fail-closed Docker cleanup checks.
3. Update the exact worktree allowlist for this mandatory readiness review and repeat its contract.
4. Reconfirm inventory-only, safe-suite contract, exact documentation/state contracts, Alembic head and diff integrity.
5. Create the separate final cumulative acceptance commit only after those checks pass.
6. Prepare the Telegram sandbox/test bot and YooKassa test shop/fiscal settings.
7. Confirm legal/support URLs and run the external end-to-end sandbox.
8. Review logs, payment, refund and PDF delivery evidence.
9. Complete production infrastructure review and deploy only after a separate explicit GO.

## 12. Rollback and stop conditions

Stop immediately on any production credential in local acceptance, real charge, non-loopback external attempt, secret/PII disclosure, unexplained file, migration/head drift, failed cleanup, duplicate durable side effect, failed contract, or mismatch between documentation and runtime. Preserve only redacted bounded evidence; do not attempt production, commit around a failed gate, or delete unexplained files automatically.

## 13. Current final decision

The previously accepted local evidence remains recorded, but this review found one startup defect and two safe-suite assurance gaps not covered by that evidence. External sandbox is not executed and production launch is blocked. Together with the mandatory document's exact allowlist mismatch, the present documentation stage is **PARTIAL** and the cumulative commit is **NO-GO** until the separate runtime/test fix-stages pass.

## 14. Next stage

Immediate corrective stages: make missing Telegram token startup fail non-zero; make safe-suite skip/xfail policy and Docker cleanup checks fail closed; then add `docs/telegram-first-v1-readiness-review.md` to the exact worktree allowlist under explicit test-change scope.

After that PASS, the next internal stage is **FINAL CUMULATIVE ACCEPTANCE DIFF COMMIT**. External sandbox and production work remain separate and pending.
