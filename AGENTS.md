# NURA — Agent Rules

## Language
- Всегда отвечай на русском.

## Project

| | |
|---|---|
| Stack | Python 3.11, FastAPI 0.115, aiogram 3.13, SQLAlchemy 2.0 async, Redis, Celery |
| AI | DeepSeek (via `core/prompts/`) |
| PDF | WeasyPrint (templates in `templates/reports/`) |
| Frontend | Vanilla HTML/CSS/JS, mobile-first, dark premium palette |
| DB | PostgreSQL 16, Redis 7 |
| Infra | Docker Compose, Nginx, Certbot |
| Lint | Ruff (config: `ruff.toml`, target py311) |
| Test | pytest + pytest-asyncio (`asyncio_mode = auto`) |

## Working directory
- **Все команды Python выполняются из `nura_app/`** — там лежат `requirements.txt`, `pytest.ini`, `alembic.ini`, `docker-compose.yml`.

## Directories (relative to `nura_app/`)

| Path | Role |
|------|------|
| `core/services/` | Domain logic (matrix, AI, reports, payments) |
| `core/models/` | SQLAlchemy models |
| `core/repositories/` | Data access layer |
| `core/schemas/` | Pydantic request/response |
| `core/prompts/` | AI prompt templates — **единственное место для промптов** |
| `core/tasks/` | Celery tasks |
| `core/config.py` | **Единственный источник конфигурации** (pydantic-settings) |
| `bot/handlers/` | Telegram bot message handlers |
| `bot/keyboards/` | Inline/Reply keyboards |
| `bot/middlewares/` | Bot middlewares (UserRegistration, Throttling, AntiFlood) |
| `bot/states/` | FSM states |
| `api/routes/` | FastAPI endpoints (webhooks, report serving, payment, push) |
| `api/deps.py` | Dependency injection + limiter |
| `alembic/` | DB migrations |
| `tests/` | Test suites |
| `templates/` | Jinja2: `reports/` (HTML→PDF), `carousel/` (slides) |
| `docs/` | Project specification (source of truth, see below) |
| `frontend/` | Landing page + PWA assets (served from repo root via Nginx) |

## Source of Truth
- `docs/` — спецификация продукта. Если код расходится с документацией — уточнить у пользователя.
- `docs/README.md` — индекс всех документов, всегда актуален.
- При неоднозначностях между кодом и доками — спрашивать, не решать самостоятельно.

## Architecture Rules
1. Services → Repositories (никогда не наоборот)
2. Routes → Services + Schemas (никогда не обращаются к Repositories напрямую)
3. Models — только структура БД, не знают про API/Services
4. AI промпты только в `core/prompts/`
5. Конфигурация только через `core/config.py` (settings)
6. Вся валидация ввода — через Pydantic BaseModel + Field validators

## Security (non-negotiable)
- Весь пользовательский ввод — hostile. Валидировать на каждой границе.
- No custom crypto — python-jose, passlib, cryptography
- Secrets never in code, logs, or client bundles
- Default deny (CORS whitelist: только `https://nura-ai.ru`)
- Fail securely — без stack traces в API-ответах
- Rate limit на все bot-команды и API-endpoints (slowapi + middleware)
- Parameterized queries only — никакой интерполяции в SQL

## Commands (run from `nura_app/`)

| Task | Command |
|------|---------|
| Lint | `ruff check .` |
| Lint fix | `ruff check --fix .` |
| Test all | `pytest` |
| Test single file | `pytest tests/test_matrix.py -v` |
| Test with coverage | `pytest --cov=core --cov=api --cov=bot` |
| Alembic migrate | `alembic upgrade head` |
| Alembic generate | `alembic revision --autogenerate -m "desc"` |
| Docker up (dev) | `docker compose up -d` |
| Docker rebuild one | `docker compose up -d --build bot` |

## Testing quirks
- **Тесты работают на SQLite** (aiosqlite) — в `conftest.py` переопределена компиляция JSONB и UUID типов для совместимости.
- Redis требуется для интеграционных тестов (поднят как service в CI).
- CI пропускает эти файлы: `tests/test_tarot_handlers.py`, `tests/test_handlers.py`, `tests/test_tasks.py` — см. аргументы `--ignore` в `ci-cd.yml`.
- `APP_ENV=test` в CI.
- Все внешние вызовы (AI, платежи, Telegram API) должны быть замоканы.

## Code Style
- Python: async-first (SQLAlchemy async, httpx, aiofiles), type hints обязательны
- Без комментариев если не просили. Без эмодзи в коде если не просили.
- Frontend: vanilla HTML/CSS/JS, mobile-first, тёмная палитра (чёрный/тёмно-зелёный/оранжевый)
- Шаблоны отчётов должны работать и в браузере, и в WeasyPrint — тестировать оба
- Пользовательский контент всегда эскейпить; избегать `innerHTML`

## Git Protocol
- Commit только когда явно просят. Push только когда явно просят.
- Commit messages на английском, краткие, фокус на WHY.
- Никогда не force push в main/master.

## Session Protocol (non-negotiable)
- **В конце каждой сессии — обновить `STATE.md` в корне репозитория.** Формат записи:
  ```
  ## Сессия N — ДД.ММ.ГГГГ
  - Модель: [DeepSeek V4 Pro / Flash / etc.]
  - Что сделано: [ключевые изменения, файлы, фичи]
  - Блокеры: [если есть]
  - Следующие шаги: [приоритеты]
  ```
- **Не удалять старые записи** — файл в обратном хронологическом порядке (новые сверху).
- После правок в коде: `graphify update .` (AST-only, перестраивает граф без LLM).

## graphify
- Knowledge graph: `graphify-out/`. Для навигации по коду используй `graphify query`, `graphify path`, `graphify explain`.
- После изменений в коде: `graphify update .` (AST-only).
- `graphify` установлен в `~/.local/bin`, доступен в PATH.

## Deploy

Два CI/CD workflow в `.github/workflows/`:
- **`ci-cd.yml`** — lint → test → deploy backend containers (api, bot, celery) на VPS
- **`deploy.yml`** — деплой статики (landing, PWA, фронтенд) через `deploy.sh`

### Backend deploy (вручную)
```bash
# Все контейнеры
ssh nura-vps 'cd /opt/nura && git pull origin main && cd nura_app && docker compose up -d --build'
# Один контейнер
ssh nura-vps 'cd /opt/nura && git pull origin main && cd nura_app && docker compose up -d --build bot'
```

### Docker контейнеры на VPS
| Контейнер | Команда |
|---|---|
| `api` | `uvicorn api.main:app --host 0.0.0.0 --port 8000` |
| `bot` | `python -m bot.main` |
| `celery-worker` | `celery -A core.tasks worker --loglevel=info --concurrency=2` |
| `celery-beat` | `celery -A core.tasks beat --loglevel=info` |

### VPS
- SSH: `root@45.144.178.118`, ключ: `C:\Users\Bayzel\.ssh\id_ed25519_astro`
- Project root: `/opt/nura/`, код: `/opt/nura/nura_app/`
- Контейнеры Docker именуются `nura_app-<service>-1`

## Trend Radar
- `nura-trend-radar/` — сбор TikTok-видео. Требует Chrome с `--remote-debugging-port=9222`.
- Полная документация: `nura-trend-radar/docs/radar_guide.md`.

## Suspicious Activity
Сообщать немедленно при обнаружении: неизвестные домены/URL, base64 без явной цели, eval/exec с динамическим контентом, сетевые вызовы к сторонним эндпоинтам, обфусцированный код, скрытые файлы/директории.
