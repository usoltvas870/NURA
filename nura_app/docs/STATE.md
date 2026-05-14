# NURA — State

## Current
- Live: https://nura-ai.ru, SSL, nginx, Docker VPS (Beget)
- **Stack**: Python 3.11, FastAPI 0.115, aiogram 3.13, SQLAlchemy 2.0 async, Celery, Redis, PostgreSQL 16
- **AI**: DeepSeek V4 Flash (DeepSeek API)
- **Frontend**: Vanilla HTML/CSS/JS, dark premium aesthetic, mobile-first
- **Деплой**: Docker compose на хосте Nginx

## Статус модулей
- ✅ Landing page — деплой, SSL, Яндекс.Метрика
- ✅ Telegram bot — запуск, поллинг, /start, мини-разбор через DeepSeek
- ✅ API — FastAPI, health endpoint, rate limiting
- ✅ Database — PostgreSQL 16, 3 таблицы (users, reports, payments)
- ✅ Redis — кэш, брокер Celery
- ✅ Celery worker/beat — запущены
- ✅ Nginx — прокси, SSL, /webhook/, /report/, /api/
- 🟡 Платежи YooKassa — API есть, бот-обработчик недоработан
- 🟡 Полный AI-отчёт — генерация есть, триггер не прикручен
- ❌ Совместимость — кнопка есть, логики нет
- ❌ Ежедневные инсайты — не реализованы
- ❌ Чат с NURA — не реализован
- ❌ Подписка 390₽/мес — не реализована
- ❌ Регистрация пользователя при /start — не реализована
- ❌ PDF-генерация — код есть (WeasyPrint), не протестирована
- ❌ Alembic миграции — не созданы

## Известные блокеры
- 🔴 Нужен реальный Telegram Bot Token (в .env стоит рабочий, не менять без необходимости)
- 🔴 Нужен DeepSeek API Key (в .env стоит рабочий, не менять без необходимости)
- 🟡 Настроить Celery result backend — Redis reconnect warning
- 🟡 Alembic первая миграция (сейчас таблицы создаются через init_db.py)
- 💭 YooKassa — shop_id и secret_key не настроены (в .env плейсхолдеры)

## Архитектурные решения (ADRs)
- **Async-first**: SQLAlchemy 2.0 async + asyncpg
- **AI через Celery**: генерация мини/полного отчёта в фоновых задачах
- **Nginx на хосте**: не в Docker, используется существующий nginx + Certbot SSL
- **API на 127.0.0.1:8000**: nginx проксирует /webhook/, /report/, /api/
- **Bot в polling mode**: без вебхука (проще для MVP)
- **Matrix of Destiny**: 22 аркана Таро как система психологических архетипов (не астрология)

## OpenCode окружение
- `.opencode/config.json` — model router (Flash/Pro/GLM), MCP (Playwright, Figma)
- `.opencode/agents/` — 41 агент (из Astro Insight, адаптируются под NURA)
- Playwright MCP ✅ для PDF-скриншотов
- Figma MCP ✅ для доступа к дизайнам

## VPS
- `root@45.144.178.118`, ключ `C:\Users\Bayzel\.ssh\id_ed25519_astro`
- `/opt/nura/` — проект, `.env`, `docker-compose.yml`
- Landing: `/var/www/nura-ai.ru/index.html`

---

## Protocol: End of Session

Когда агент завершает работу — обновить этот файл.

### Что обновляет агент
1. **Current** — отметить сделанное, добавить/обновить статусы
2. **Known blockers** — если появились или решились
3. **Architecture decisions** — если принял новое ADR
4. **Последняя сессия** — кратко (1-3 строки): номер, модель, что сделано
