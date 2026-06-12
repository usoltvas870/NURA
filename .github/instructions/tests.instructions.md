---
name: NURA Tests
description: Test conventions for NURA
applyTo: "nura_app/tests/**/*.py"
---

- Use pytest and pytest-asyncio with `asyncio_mode = auto`.
- Test public behavior and failure paths, not implementation details.
- Keep tests deterministic; mock external AI, payment, Telegram, and network calls.
- Cover authorization, validation, idempotency, rollback, and concurrency where relevant.
- Do not use production credentials, production databases, or live payment endpoints.
