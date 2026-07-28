# Acceptance index — Telegram-first v1

**STATUS: CURRENT ACCEPTANCE ROUTER — LOCAL EVIDENCE IS NOT PRODUCTION PROOF**

This checklist separates accepted local evidence from operator-controlled external and production gates. A local PASS does not authorize an external call, real charge, production token or deployment.

## A. LOCAL AUTOMATED GATES — PASS

- [x] Alembic migrations: blank PostgreSQL 16 to `f9a0b1c2d3e4`, downgrade/re-upgrade and runtime dependency probe.
- [x] Required service boot: FastAPI, Telegram runtime, Celery worker, Celery Beat, simultaneous stack and second boot.
- [x] Cumulative PostgreSQL/Redis golden path, including all v1 segments and fresh-process replay.
- [x] Webhook, generation and delivery failure/retry chains; duplicate side effects = 0.
- [x] Security acceptance: open P0/P1/P2 = 0, Sentry envelope scrubbed, sentinel scan clean.
- [x] Full safe-suite: 80 discovered, 66 included, 14 excluded, 8 shards, 1082 collected, 1059 passed, 22 skipped, 1 deselected, 0 failed.
- [x] Owned containers, volumes, subprocesses, ports and security context cleanup PASS.
- [x] Real Telegram, YooKassa, AI and other non-loopback external calls = 0.

## B. EXTERNAL SANDBOX GATES — NOT EXECUTED

### Telegram

- [ ] Approved test/sandbox bot and real sandbox-only bot token.
- [ ] Bot username, deep link and selected webhook or polling mode.
- [ ] Allowlisted test Telegram account.
- [ ] Onboarding and attribution.
- [ ] Mini-report structured text and PDF delivery.
- [ ] Daily Tarot and chat quota: lifetime five-message quota — current implemented state; daily five-message quota — canonical target and implementation gap. После реализации daily quota требуется отдельная acceptance-проверка.
- [ ] Checkout CTA and My Reports.
- [ ] Full PDF automatic delivery and repeated manual delivery.
- [ ] Account deletion and bot-blocked behavior.

### YooKassa

- [ ] Test shop, Shop ID and sandbox secret.
- [ ] Fiscal receipt scenario and values for `YOOKASSA_RECEIPT_VAT_CODE`, `YOOKASSA_RECEIPT_PAYMENT_MODE` and `YOOKASSA_RECEIPT_PAYMENT_SUBJECT`.
- [ ] Public HTTPS webhook and return URL.
- [ ] `payment.succeeded`, `refund.succeeded` and receipt generation.
- [ ] Confirm absence of a real charge.
- [ ] Duplicate webhook and out-of-order refund/success behavior.

## C. PRODUCTION / LEGAL GATES — NOT EXECUTED

- [ ] Production TLS, reverse proxy and firewall review.
- [ ] Production secret store; no production credentials in local acceptance.
- [ ] Backup/restore and monitoring verification.
- [ ] Production domain and public URL verification.
- [ ] Offer and privacy policy.
- [ ] User agreement, if required.
- [ ] Support contact and support response process.

Production launch is blocked until every applicable item in B and C has evidence and a separate GO. Any real payment before the sandbox/test environment is confirmed is NO-GO.

## Evidence and runbooks

- [Local sandbox runbook](telegram-first-sandbox.md)
- [Dated Telegram-first v1 readiness evidence](evidence/telegram-first-v1-readiness-review.md)
- [Current implementation status](../implementation/current-status.md)
- [Canonical target acceptance](../product/NURA_1_0_1_5_PRODUCT_SPEC.md)

Stage 2A only reorganizes evidence. Full acceptance/operations consolidation is deferred to Stage 2B.
