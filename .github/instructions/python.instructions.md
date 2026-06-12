---
name: NURA Python
description: Backend architecture and Python rules
applyTo: "nura_app/**/*.py"
---

- Work from `nura_app` when running Python commands.
- Follow `routes -> services -> repositories -> models` dependencies.
- Routes use services and schemas; routes never access repositories directly.
- Services use repositories; models contain no API or service logic.
- Validate all boundary input with Pydantic schemas.
- Use SQLAlchemy 2.0 async APIs and parameterized queries only.
- Keep AI prompt text in `nura_app/core/prompts/`.
- Read configuration through `nura_app/core/config.py`; never hardcode secrets.
- Add type hints to changed Python code.
- Run focused tests first, then `ruff check .` and relevant `pytest` tests.
