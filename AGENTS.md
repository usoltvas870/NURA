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
| `frontend/` | Landing page (корень проекта) |
| `templates/` | Jinja2-шаблоны отчётов (`reports/`) и слайдов (`carousel/`) |

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

### Code (ядро — ~85%)

| Модель | Доля | Когда |
|--------|------|-------|
| DeepSeek V4 Flash | ~60% | CRUD, тесты, багфиксы, одиночные файлы, стили, миграции, рефакторинг, компоненты |
| DeepSeek V4 Pro | ~15% | 2–3 модуля, schema design, неочевидные баги, архитектурные решения, 1M контекст |
| GLM-5.1 | ~10% | Сложный код, альтернативный взгляд на архитектуру, задачи где Flash/Pro упёрлись |

### Design & Visual (мультимодальность)

| Модель | Когда |
|--------|-------|
| MiMo-V2.5-Pro | Анализ скриншотов/макетов, сравнение UI с Figma, визуальные баги, генерация CSS по картинке |
| DeepSeek V4 Pro | Дизайн-решения, рассуждения о композиции, ревью UI |

### Copy & Content (тексты)

| Модель | Когда |
|--------|-------|
| MiniMax M2.7 | Маркетинговые тексты, посты, описания, креатив, копирайтинг для лендинга |
| Kimi K2.6 | Длинные структурированные тексты, статьи, документация, аналитические отчёты, промпт-инжиниринг |

### Document Analysis (документы)

| Модель | Когда |
|--------|-------|
| Kimi K2.6 | Анализ спецификаций, docs/, PDF-отчёты, большие контексты (до 2M токенов), RAG |
| DeepSeek V4 Pro | Глубокая аналитика по документации |

### Fallback

| Модель | Когда |
|--------|-------|
| Qwen3.6 Plus | Flash/Pro недоступны, свежий взгляд на код, простые запросы без контекста |

### Правила
1. По умолчанию — **DeepSeek V4 Flash**.
2. **DeepSeek V4 Pro** — когда задача затрагивает 2+ модуля или нужна архитектура.
3. **GLM-5.1** — когда Flash/Pro упёрлись в тупик, нужен альтернативный подход к сложному коду.
4. **MiMo-V2.5-Pro** — только если в задаче есть скриншот/изображение (Figma, UI, баг-скрин).
5. **MiniMax M2.7 / Kimi K2.6** — только если задача явно про текст, контент или промпты.
6. **Qwen3.6 Plus** — fallback при недоступности DeepSeek или для "свежей головы".
7. Стартовать с самой лёгвой модели под задачу. Переключаться на более мощную при фейле.
8. Не тратить токены на обоснование выбора — просто работать.

## MCP-инструменты

MCP-серверы настраиваются в `~/.hermes/config.yaml` секция `mcp_servers` и подключаются автоматически при старте.

| MCP сервер | Для чего | Требует API ключ |
|---|---|---|
| Sequential Thinking | Структурированные рассуждения для сложных архитектурных решений | нет |
| Context7 | Live docs lookup (Python/React/FastAPI) | нет |
| Playwright | Скриншоты, E2E-тесты, браузерная отладка | нет |
| Figma | Доступ к дизайн-макетам | `FIGMA_ACCESS_TOKEN` |
| GitHub | PR/issues/CI из чата | `GITHUB_PERSONAL_ACCESS_TOKEN` |

## Subagent Delegation (Hermes)

Используй `delegate_task(goal=..., context=...)` для сложных подзадач:
- параллельные независимые работы (через `tasks=[{goal, ...}]`)
- исследования, ресёрч, ревью
- задачи, которые не влезают в контекст

## Slash-команды (Hermes)

Доступны встроенные команды Hermes: `/plan`, `/model`, `/compact`, `/compress`, `/retry`, `/undo`, `/yolo`, `/help` и другие. Полный список: `/help` в сессии.

## Skills (Hermes — загружаются при старте или через `/skill name`)

| Skill | Назначение |
|-------|-----------|
| `research-first` | Исследование перед написанием кода — поиск готовых решений на PyPI/npm/GitHub |
| `test-driven-development` | Red-Green-Refactor для pytest-asyncio |
| `security-and-hardening` | Безопасность FastAPI/PWA: OWASP, SSRF, Rate Limiting, инъекции |
| `systematic-debugging` | 4-фазный поиск root cause |
| `plan` | Планирование и декомпозиция |
| `nura-dev` | Специфика разработки NURA |
| `workflow-architect` | Проектирование workflow деревьев |

## VPS Access

Проект NURA развёрнут на отдельном VPS.

| | |
|---|---|
| SSH | `root@45.144.178.118` |
| SSH key | `C:\Users\Bayzel\.ssh\id_ed25519_astro` (Windows, без пароля) |
| Landing | `https://nura-ai.ru` — статика в `/opt/nura/index.html` |
| Project root | `/opt/nura/` |
| Code | `/opt/nura/nura_app/` |

### Docker контейнеры (в `/opt/nura/nura_app/`)

| Контейнер | Роль |
|---|---|
| `nura_app-bot-1` | Telegram бот (aiogram) |
| `nura_app-api-1` | FastAPI (вебхуки, отчёты) |
| `nura_app-celery-worker-1` | Celery worker |
| `nura_app-celery-beat-1` | Celery beat |
| `nura_app-postgres-1` | PostgreSQL |
| `nura_app-redis-1` | Redis (FSM + Celery) |

### Deploy commands

```bash
# Подключение
ssh -i C:\Users\Bayzel\.ssh\id_ed25519_astro -o StrictHostKeyChecking=no root@45.144.178.118

# Pull + rebuild bot
cd /opt/nura && git pull origin master && cd nura_app && docker compose up -d --build bot

# Pull + rebuild всё
cd /opt/nura && git pull origin master && cd nura_app && docker compose up -d --build

# Логи бота
docker logs nura_app-bot-1 --tail 50

# Перезапуск контейнера
docker compose restart bot
```

## Suspicious Activity

Report immediately if found:
- Unknown domains or URLs in code
- Base64 blobs without clear purpose
- eval/exec with dynamic content
- Network calls to non-project endpoints
- Obfuscated code
- Hidden files or directories appearing

## Trend Radar

Проект `nura-trend-radar/` — локальный инструмент сбора TikTok-видео по 50 источникам.

### Быстрый старт
```bash
cd nura-trend-radar
# 1. Убедись что Chrome запущен с --remote-debugging-port=9222
# 2. Войди в TikTok в этом Chrome
python run_radar.py
```

### Частые проблемы
- **Топ из плейлистов** → `rm data/videos.db` (удалить БД)
- **Все 0 видео** → куки протухли, переэкспорт или CHROME_DEBUG_PORT
- **AI пустой** → баланс DeepSeek или ключ
- **networkidle таймаут** → уже пофиксено (load + fallback)

Полная документация: `nura-trend-radar/docs/radar_guide.md`
