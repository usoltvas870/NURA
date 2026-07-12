# NURA — Project Agent Rules

## Communication

- Отвечай пользователю на русском.
- Язык кода, имён и комментариев соблюдай по правилам соответствующей части проекта.

## Project

| | |
|---|---|
| Stack | Python 3.11, FastAPI 0.115, aiogram 3.13, SQLAlchemy 2.0 async, Redis, Celery |
| AI | DeepSeek; prompt templates только в `nura_app/core/prompts/` |
| Reports | Jinja2 + WeasyPrint |
| Frontend | Vanilla HTML/CSS/JS, mobile-first |
| Data | PostgreSQL 16, Redis 7 |
| Infra | Docker Compose, Nginx, Certbot |
| Quality | Ruff, pytest, pytest-asyncio |

Все Python-команды выполняй из `nura_app/`, где находятся `requirements.txt`, `pytest.ini`, `alembic.ini` и `docker-compose.yml`.

## Repository map

- `nura_app/core/services/` — доменная логика.
- `nura_app/core/models/` — структура БД.
- `nura_app/core/repositories/` — доступ к данным.
- `nura_app/core/schemas/` — Pydantic-схемы.
- `nura_app/core/prompts/` — единственное место для AI-промптов.
- `nura_app/core/tasks/` — Celery-задачи.
- `nura_app/core/config.py` — единственный источник runtime-конфигурации.
- `nura_app/bot/` — Telegram-бот.
- `nura_app/api/routes/` — FastAPI endpoints.
- `nura_app/alembic/` — миграции.
- `nura_app/tests/` — тесты.
- `nura_app/templates/reports/` — HTML/PDF-отчёты; применяй nested `AGENTS.md`.
- `frontend/pwa/app/` — PWA; применяй nested `AGENTS.md`.
- `docs/` — продуктовая и техническая документация; применяй nested `AGENTS.md`.

## Source of truth

- Approved product/architecture docs описывают целевое поведение.
- Текущий код показывает фактически реализованное поведение.
- `STATE.md` — журнал состояния и решений, но не нормативная спецификация.
- Prototype/preview не является production contract.
- При расхождении docs и code зафиксируй его, не меняй поведение молча и запроси решение владельца, если задача явно не задаёт приоритет.
- `AGENTS_TODO.md` не является автоматически действующей спецификацией. Используй его только после отдельного аудита и подтверждения.

## Architecture boundaries

1. Services используют Repositories; Repositories не зависят от Services.
2. Routes используют Services и Schemas и не обращаются к Repositories напрямую.
3. Models описывают только структуру данных и не знают об API или Services.
4. AI-промпты находятся только в `core/prompts/`.
5. Runtime-конфигурация добавляется только через `core/config.py` и settings.
6. Пользовательский ввод валидируется Pydantic-моделями и field validators.
7. Python-код async-first; type hints обязательны.

## Security invariants

- Считай весь пользовательский ввод враждебным и валидируй на каждой границе.
- Не создавай собственную криптографию; используй проверенные библиотеки проекта.
- Не помещай secrets в код, логи, отчёты или client bundles и не печатай содержимое `.env`.
- CORS и внешние интеграции работают по default-deny.
- API не должен возвращать stack traces.
- Новые bot-команды и API endpoints требуют rate limiting.
- Используй только parameterized queries; не интерполируй SQL.
- Пользовательский контент экранируй; избегай `innerHTML`.
- Немедленно сообщай о неизвестных доменах, необъяснимом base64, динамическом `eval`/`exec`, обфускации и скрытых сетевых вызовах.

## Commands

Выполняй из `nura_app/`:

| Task | Command |
|---|---|
| Lint | `ruff check .` |
| Targeted test | `pytest tests/<file>.py -v` |
| All tests | `pytest` |
| Coverage | `pytest --cov=core --cov=api --cov=bot` |

Не запускай исправляющий formatter/linter, миграции или Docker rebuild, если это не входит в явно согласованный scope.

## Testing rules

- Тесты используют SQLite; `conftest.py` адаптирует JSONB и UUID.
- Redis требуется интеграционным тестам.
- `APP_ENV=test` используется в CI.
- AI, платежи, Telegram API и другие внешние вызовы должны быть замоканы.
- Сначала запускай минимальный релевантный набор тестов; полный suite — пропорционально риску изменения.

## Change protocol

- Перед изменениями выполни `git status --short` и сохрани существующие пользовательские и чужие изменения.
- Меняй только файлы в явно заданном scope; unrelated diff не исправляй и не включай в результат.
- Перед пакетной правкой проверь, не реализовано ли изменение частично.
- После изменений выполни релевантные проверки, `git diff --check`, `git diff --stat` и `git status --short`.
- В финале перечисли изменённые файлы, выполненные проверки, ограничения и оставшиеся риски.
- Commit messages — краткие, на английском, с фокусом на WHY. Никогда не force-push в main/master.

## Approval matrix

Без отдельного подтверждения разрешены:

- чтение и поиск;
- аудит и диагностика;
- локальные read-only проверки и тесты;
- изменения строго в явно заданном пользователем scope.

Требуют отдельного подтверждения:

- новые или обновлённые зависимости;
- auth и управление сессиями;
- payments и billing;
- legal pages и consent flows;
- manifest и service worker;
- Nginx и инфраструктурная конфигурация;
- migrations, autogenerate и `alembic upgrade`;
- commit, push и PR;
- SSH, VPS и deploy.

Commit, push и PR разрешены только по прямому запросу. SSH, VPS и deploy требуют отдельного разрешения владельца именно в текущем сообщении; прежний доступ или предыдущая команда не считаются разрешением.

## STATE.md policy

Обновляй `STATE.md` только:

- после material code/config/product changes;
- по явному запросу владельца;
- при завершении существенного логического этапа, если этого требует согласованный project workflow.

Не обновляй `STATE.md` автоматически после read-only анализа, design discussion, prototype-only работы, просмотра файлов или неуспешной попытки без изменений.
