# Сессия 6 — Security-фиксы NURA

> Дата: 22.06.2026
> Область: `nura_app/api/routes/webhook.py`, `nura_app/api/routes/push.py`, `nura_app/api/main.py`, `nura_app/.env.example`, фронтенд push-отписки
> Не тронуто: `payment.py`, UI/UX
> Контекст: сессия 6, после 5 сессий ревизии. Только безопасность.

---

## ⚠️ Секреты в git history

Проверено: `git log --oneline -- nura_app/.env` и `git log --oneline -- .env` — **пусто**. Реальный `nura_app/.env` никогда не коммитился (попал в `.gitignore` до первого коммита). В git tracked только `.env.example` с плейсхолдерами (`change-me-*`).

**Вывод:** реальных секретов в git history нет. Смены секретов и очистки истории не требуется.

---

## Режим работы бота

**Бот работает на long-polling.**

- `nura_app/bot/main.py:100` — `await dp.start_polling(bot)`
- `set_webhook()` нигде в коде не вызывается (grep по `nura_app/` — 0 совпадений кроме `.env.example`).
- `TELEGRAM_WEBHOOK_URL` была в `.env.example`, но нигде в коде не читалась (grep `telegram_webhook_url` — 0 совпадений в Python).

**Итог:** эндпоинт `/webhook/telegram` — мёртвый код, оставшийся от другого режима работы (или от задумки переключиться на webhook). Как open proxy в Telegram Bot API он не используется ботом, но остаётся доступным извне через FastAPI.

---

## Задача 1 — `/webhook/telegram` без защиты (N4, критично)

**Решение:** режим long-polling → эндпоинт не нужен → удалён целиком.

**Изменения:**
- `nura_app/api/routes/webhook.py` — **удалён** (`git rm`-эквивалент через `Remove-Item`).
- `nura_app/api/main.py:12` — убран импорт `from api.routes.webhook import router as webhook_router`.
- `nura_app/api/main.py:29` — убран `app.include_router(webhook_router)`.
- `nura_app/.env.example:28` — убрана мёртвая переменная `TELEGRAM_WEBHOOK_URL` (не использовалась в коде).

**Проверка:** `grep "from api.routes.webhook|import webhook|webhook_router"` по `*.py` — 0 совпадений. Эндпоинт больше не暴露.

**Промежуточный вывод:** open-proxy в Telegram API устранён физическим удалением мёртвого кода.

---

## Задача 2 — `.env` в git

**Проверка:**
- `git ls-files -- nura_app/.env` → не tracked (error: pathspec did not match).
- `git log --oneline -- nura_app/.env` → пусто (никогда не коммитился).
- `git ls-files | grep .env` → только `nura_app/.env.example` и `nura-trend-radar/.env.example` (оба с плейсхолдерами).
- `nura_app/.gitignore:4` — паттерн `.env` (общий, ловит и корневой, и `nura_app/.env`). Корректен.
- `nura_app/.env` (рабочая копия) — содержит только плейсхолдеры `change-me-*` (APP_ENV=production, но секреты — плейсхолдеры).

**Действий по `git rm --cached` не потребовалось** — файл и так не в индексе.

**Содержимое `nura_app/.env.example`** — все те же переменные, что и реальный `.env`, только с плейсхолдерами. Дополнительно убрана мёртвая `TELEGRAM_WEBHOOK_URL` (см. Задачу 1).

**Промежуточный вывод:** `.env` никогда не попадал в git. `.env.example` — единственный env-файл в репозитории, плейсхолдеры корректны.

---

## Задача 3 — `/api/v1/push/unsubscribe` без авторизации (N3)

**Файлы:**
- `nura_app/api/routes/push.py:22-25` — `PushUnsubscribe` schema дополнена обязательным идентификатором: `session_id: str | None = None`, `telegram_id: int | None = None`.
- `nura_app/api/routes/push.py:62-85` — ручка `/unsubscribe` переписана:
  1. Если ни `session_id`, ни `telegram_id` не переданы → `401`.
  2. Пользователь ищется через `user_repo.get_by_web_session_id()` или `get_by_telegram_id()` (те же методы, что в `/subscribe`).
  3. Если пользователь не найден → `404`.
  4. **Проверка владельца endpoint:** `user.push_endpoint != body.endpoint` → `403 "Endpoint не принадлежит пользователю"`. Поле `push_endpoint` на модели `User` (`core/models.py:75`) хранит текущий endpoint подписки — атакующий, знающий чужой endpoint, не может отписать чужого пользователя без его `session_id`.
  5. Только после проверки вызывается `clear_push_subscription_by_endpoint`.
- `frontend/pwa/app/nura-pwa.js:97` — `unsubscribeFromPush(sessionId)` теперь шлёт `{ endpoint, session_id: sessionId }` в body (раньше `sessionId` приходил аргументом, но не использовался).
- `nura_app/templates/profile.html:578` — `togglePush()` (функция гардится `if (!sessionId)` на строке 534) теперь шлёт `{ endpoint, session_id: sessionId }`.

**Промежуточный вывод:** чужая отписка по известному endpoint невозможна — требуется валидный `session_id`/`telegram_id` и совпадение endpoint с записанным у пользователя.

---

## Задача 4 — повторный проход по push/webhook

**`push.py` целиком:**
- `/vapid-public-key` (GET, публичный) — публичный VAPID-ключ by design. Rate limit `10/minute`. OK.
- `/subscribe` (POST) — уже требовал `session_id`/`telegram_id` (push.py:40-49), 404 при отсутствии пользователя. Rate limit `5/minute`. OK.
- `/unsubscribe` (POST) — исправлен в Задаче 3. Rate limit `5/minute`. OK.

**`webhook.py`:** удалён в Задаче 1.

**Других push/webhook-эндпоинтов в проекте нет** (grep по `APIRouter` в `api/routes/` — `web.py`, `tarot_pwa.py`, `push.py`, `reports.py`, `payment.py` (не трогаем), `webhook.py` (удалён)). `payment.py /webhook` — YooKassa-вебук, защищён по условию задачи (не трогать) и по предыдущим сессиям.

**Промежуточный вывод:** других эндпоинтов с проблемой аутентификации не обнаружено.

---

## Проверки

- `ruff check api/routes/push.py api/main.py` — **All checks passed**.
- `pytest tests/test_tarot_pwa.py tests/test_matrix.py tests/test_chat.py` — **152 passed** (те же, что в SESSION2_REPORT.md).
- Полный `pytest` — 297 passed, 4 xfailed, 4 failed, 16 errors.
  - **4 failed** (`tests/test_tarot_handlers.py::TestInsightsHandler::*`) — `AttributeError: module 'bot.handlers' has no attribute 'insights'` (модуль `bot/handlers/insights.py` не существует, тест ссылается на несуществующий модуль). **Pre-existing**, не связано с моими правками (я не трогал `bot/handlers/`).
  - **16 errors** (`tests/test_payment.py::TestProcessWebhook::*`) — `ModuleNotFoundError: No module named 'aiosqlite'` (нет локальной установки aiosqlite). **Pre-existing**, зафиксировано ещё в SESSION2_REPORT.md (раздел "Что осталось непротестированным").
- Сводка по моим изменениям (`git status --short`):
  - `M frontend/pwa/app/nura-pwa.js`
  - `M nura_app/.env.example`
  - `M nura_app/api/main.py`
  - `M nura_app/api/routes/push.py`
  - `D nura_app/api/routes/webhook.py`
  - `M nura_app/templates/profile.html`
  - (graphify-out/* — автогенерация, не из моих правок)

**Блокеров нет:** все тесты, которые проходили раньше, проходят. Новых падений не внесено.

---

## Изменённые файлы

| Файл | Изменение |
|------|-----------|
| `nura_app/api/routes/webhook.py` | **Удалён** (мёртвый код, бот на long-polling) |
| `nura_app/api/main.py` | Убран импорт и `include_router(webhook_router)` |
| `nura_app/.env.example` | Убрана мёртвая `TELEGRAM_WEBHOOK_URL` |
| `nura_app/api/routes/push.py` | `PushUnsubscribe` + `session_id`/`telegram_id`; `/unsubscribe` — auth + проверка владельца endpoint (403) |
| `frontend/pwa/app/nura-pwa.js` | `unsubscribeFromPush` шлёт `session_id` в body |
| `nura_app/templates/profile.html` | `togglePush` при отписке шлёт `session_id` в body |

---

## Миграции БД

Новых миграций не требуется — изменения используют существующее поле `users.push_endpoint` (`core/models.py:75`).

---

*Конец отчёта сессии 6.*
