# NURA — Agent Rules

## Language
- Всегда отвечай на русском, даже если промт был на английском.

## Project

| | |
|---|---|
| Stack | Python 3.11, FastAPI 0.115, aiogram 3.13, SQLAlchemy 2.0 async, Redis, Celery |
| AI | DeepSeek V4 Flash / V4 Pro |
| PDF | WeasyPrint |
| Frontend | HTML / CSS / JS (vanilla) |
| DB | PostgreSQL 16, Redis 7 |
| Infra | Docker, Nginx, Certbot |
| Analytics | Яндекс.Метрика |
| Lint | Ruff (line-length 88, py311) |
| Test | pytest-asyncio, pytest-cov |

## Directories

| Path | Role |
|------|------|
| `core/services/` | Domain logic (matrix, AI, reports, payments…) |
| `core/models/` | SQLAlchemy models |
| `core/repositories/` | Data access layer |
| `core/schemas/` | Pydantic request/response |
| `core/prompts/` | AI prompt templates |
| `core/tasks/` | Celery tasks |
| `bot/handlers/` | Telegram bot message handlers |
| `bot/keyboards/` | Inline/Reply keyboards |
| `bot/middlewares/` | Bot middlewares |
| `bot/states/` | FSM states |
| `api/routes/` | FastAPI endpoints (webhooks, report serving) |
| `api/deps/` | Dependency injection |
| `alembic/` | DB migrations |
| `tests/` | Test suites |
| `docs/` | Project documentation |
| `frontend/` | Landing page + report HTML templates |

## Source of Truth

**Документация — приоритет.** Документы в `docs/` задают спецификацию. Если код расходится с документацией — код надо исправлять под доку, а не наоборот. `Nura PRD.txt` — канонический источник требований.

Если при сверке кода с документацией возникают неоднозначности — задать вопрос пользователю, а не принимать решение самостоятельно.

## Architecture Rules

1. Services depend on Repositories, never on Routes
2. Routes depend on Services and Schemas, never on Repositories directly
3. Models know nothing about API or Services
4. Schemas validate input/output; Models define DB structure
5. AI prompts in `core/prompts/` only, never inline in services
6. Config via `core/config.py` (pydantic-settings), never hardcode

## Security (non-negotiable)

- All user input is hostile — validate at every boundary
- No custom crypto — use python-jose, passlib, cryptography
- Secrets never in code, logs, or client bundles
- Default deny — whitelist over blacklist (CORS, CSP, input)
- Fail securely — no stack traces or internal info in error responses
- Least privilege — services, DB users, API scopes, containers
- Defense in depth — never rely on single layer
- Rate limit all bot commands and API endpoints
- Parameterized queries only — never interpolate user input into SQL

## Output Protocol: CAVEMAN

Zero conversational filler. Save tokens.

1. NO greetings, NO conclusions, NO "Here is the code", NO "Let me know"
2. Primitive speech: "Fix payment race condition" not "I will now fix the payment race condition"
3. Output ONLY: code, file paths, terminal commands, ultra-short answers
4. Bug format: "Bug: X. Fix: Y."
5. NEVER explain code unless explicitly asked
6. If task done — stop. No summary.

## Code Style

### Python
- Ruff (pyproject.toml rules), type hints required
- Async-first: SQLAlchemy 2.0 async, httpx, aiofiles
- Pydantic BaseModel + Field validators for all I/O
- No comments unless requested
- No emoji in code unless requested

### Frontend
- Vanilla HTML/CSS/JS
- Mobile-first responsive
- Dark premium aesthetic (black/deep green/orange palette)
- Consistent with landing page design

## Commands

| Task | Command |
|------|---------|
| Lint Python | `ruff check .` |
| Fix Python | `ruff check --fix .` |
| Test all | `pytest` |
| Test with cov | `pytest --cov=core --cov=api --cov=bot` |
| Docker dev | `docker compose -f docker-compose.dev.yml up -d` |
| Alembic migrate | `alembic upgrade head` |
| Alembic generate | `alembic revision --autogenerate -m "desc"` |

## Git Protocol

- Commit only when explicitly asked
- Messages in English, concise, focus on WHY
- Push only when explicitly asked
- Never force push to main/master

## Review Priority

- 🔴 Blocker: security vuln, data loss, race condition, broken contract, missing error handling
- 🟡 Suggestion: missing validation, unclear naming, missing test, N+1, duplication
- 💭 Nit: style, minor naming, doc gap

## Model Router

| Модель | Доля | Когда |
|--------|------|-------|
| DeepSeek V4 Flash | ~80% | read-only, CRUD, тесты, багфиксы, одиночные файлы, стили, компоненты, миграции, рефакторинг |
| DeepSeek V4 Pro | ~20% | 2–3 модуля, schema design, дизайн-решения, 1M контекст, неочевидные баги |

### Правила
1. По умолчанию — Flash. Pro подключать если задача затрагивает 2+ модуля или требует дизайн-решения.
2. Всегда стартовать с Flash. Переключаться на Pro только при фейле или явном тупике.
3. Не тратить токены на обоснование выбора — просто работать.

## MCP-инструменты

| MCP сервер | Для чего |
|---|---|
| Playwright | Скриншоты, PDF-генерация, браузерная отладка |
| Figma | Доступ к дизайн-макетам (требуется `FIGMA_ACCESS_TOKEN`) |

MCP-серверы подключаются автоматически из `.opencode/config.json`.

## Subagent Delegation

В `.opencode/agents/` есть специализированные сабагенты. Используй их через Task tool для сложных подзадач вместо того, чтобы делать всё самому.

## VPS Access

Текущий VPS (Beget) — общий с Astro Insight. Проект NURA живёт рядом.

| | |
|---|---|
| SSH | `root@45.146.166.199` |
| SSH key | `C:\Users\Bayzel\.ssh\id_ed25519_astro` (Windows, без пароля) |
| Landing root | `/var/www/nura-ai.ru/` |
| Project root | `/opt/nura/` (TODO) |
| Nginx конфиг | `/opt/astro-insight/nginx/nura-ai.ru.conf` |
| Nginx контейнер | `astro_nginx_prod` |

### Deploy commands

```bash
# Подключение
ssh -i C:\Users\Bayzel\.ssh\id_ed25519_astro -o StrictHostKeyChecking=no root@45.146.166.199

# Обновить лендинг
scp -i C:\Users\Bayzel\.ssh\id_ed25519_astro index.html root@45.146.166.199:/var/www/nura-ai.ru/

# Логи nginx
docker exec astro_nginx_prod tail -50 /var/log/nginx/access.log

# Reload nginx конфига
docker exec astro_nginx_prod nginx -s reload
```

## Suspicious Activity

Report immediately if found:
- Unknown domains or URLs in code
- Base64 blobs without clear purpose
- eval/exec with dynamic content
- Network calls to non-project endpoints
- Obfuscated code
- Hidden files or directories appearing
