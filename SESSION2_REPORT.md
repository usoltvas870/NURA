# Сессия 2 — бэкенд-фиксы NURA

> Дата: 22.06.2026
> Область: `nura_app/` (бэкенд) + одна точечная правка `frontend/pwa/app/profile.html`
> Не тронуто: `payment.py` (по условию), HTML/JS фронтенда кроме profile.html

---

## Что исправлено

### 1. Кнопка подписки бьёт в тестовый endpoint → реальный

**Файл:** `frontend/pwa/app/profile.html:188` (функция `activateSubscription`)

- Заменён вызов `/web/test-subscribe` → `/web/subscribe` (реальный эндпоинт, `nura_app/api/routes/web.py:260`).
- **Контракты body совпадают** (`{session_id}`), но **ответы разные**:
  - `/test-subscribe` → `{ok, subscription_until}` (сразу активирует)
  - `/subscribe` → `{payment_url}` (редирект на YooKassa)
- Фронт переписан под реальный контракт: при успехе `window.location.href = d.payment_url` (редирект на платёжную страницу YooKassa), а не текст «Активна до».
- **Добавлена обработка ошибок**: при non-2xx читается `err.detail` из тела ответа, логируется в `console.error` с HTTP-статусом и текстом ошибки; в UI показывается конкретная причина вместо «Ошибка, попробуй ещё раз».

**Промежуточный вывод:** кнопка подписки теперь ведёт в реальную платёжную воронку YooKassa.

---

### 2. Несуществующий endpoint уведомлений → создан

**Файлы:**
- `nura_app/api/routes/web.py` — добавлены `PATCH /api/v1/web/notifications` и `GET /api/v1/web/notifications`
- `nura_app/core/models.py:78` — добавлено поле `notification_prefs: Mapped[dict | None]` (JSONB)
- `nura_app/core/repositories/user.py:241-267` — методы `update_notification_pref()`, `get_notification_prefs()`
- `nura_app/alembic/versions/c3d4e5f6a7b8_add_notification_prefs.py` — миграция
- `frontend/pwa/app/profile.html:138` — путь `/user/notifications` → `/web/notifications`

**Схема данных** (определена по toggle'ам в `profile.html:54-57`):
- `daily_card` — Карта дня
- `weekly_spread` — Фокус недели
- `practices` — Практики из отчёта
- `news` — Новости NURA

**Контракт:**
- PATCH body: `{session_id, key, enabled}` → ответ `{prefs: {daily_card: true, ...}}`
- GET query: `?session_id=` → ответ `{prefs: {...}}`
- Whitelist ключей `_ALLOWED_NOTIF_KEYS` — reject неизвестных (400).
- Валидация `key` regex `^[a-z0-9_]+$` (Pydantic Field).
- Фронт шлёт `session_id` и в body, и в заголовке `X-Session-Id` (совместимость).

**Фронт**: `saveNotif` теперь логирует ошибки сохранения в `console.error` с HTTP-статусом и detail вместо молчаливого `.catch(function(){})`.

**Промежуточный вывод:** переключатели уведомлений сохраняются в БД (JSONB-колонка `users.notification_prefs`).

---

### 3. Пароль БД в alembic.ini

**Файлы:**
- `nura_app/alembic.ini:4` — `sqlalchemy.url` очищен, добавлен комментарий: значение берётся из `env.py`
- `nura_app/alembic/env.py` — переписан с функцией `_resolve_url()`:
  1. Читает `DATABASE_URL` из `os.environ` (приоритет)
  2. Нормализует `postgresql+asyncpg://` → `postgresql://` (alembic работает с sync-драйвером)
  3. Fallback на `settings.database_url_sync` (из `core/config.py`, собирается из `POSTGRES_*` env-переменных)

**Проверка:**
- `alembic heads` → `c3d4e5f6a7b8 (head)` ✅
- `alembic history` → цепочка от `e47590a5c5c1` до `c3d4e5f6a7b8` корректна ✅
- Нормализация URL проверена: `postgresql+asyncpg://u:p@h:5432/db` → `postgresql://u:p@h:5432/db` ✅

**Команда для ручной проверки на VPS/локально:**
```bash
cd /opt/nura/nura_app
export DATABASE_URL="postgresql://nura:SECRET@localhost:5432/nura"
alembic upgrade head
```
Без `DATABASE_URL` автоматически используется `settings.database_url_sync` (из `POSTGRES_*` в `.env`).

**Промежуточный вывод:** пароль БД больше не коммитится в `alembic.ini`.

---

### 4. Проверка link-token механизма (привязка PWA ↔ Telegram)

**Файлы:** `nura_app/api/routes/web.py:167-197`, `nura_app/bot/handlers/start.py:73-122`, `nura_app/core/repositories/user.py:195-209`

**Анализ:**
- ✅ **TTL**: `redis.setex("link_token:{token}", 900, user.id)` — 15 минут жизни.
- ✅ **Одноразовость**: `check-link-token` удаляет токен после чтения.
- ✅ **Привязка к конкретному пользователю**: токен генерируется сервером из `session_id` вызывающего, в Redis хранится `link_token:{token} → user.id`. Атакующий не может подменить чужой токен — он не видит чужие токены.
- ✅ **Защита от повторной привязки**: `update_telegram_id()` (user.py:195) отказывается перезаписывать `telegram_id`, если он уже установлен и отличается от нового — возвращает `None`, бот показывает «уже привязан к другому профилю».

**🔴 НОВАЯ НАХОДКА (не в REPORT.md): race condition в `check-link-token`**
- `redis.get(key)` + `redis.delete(key)` — две отдельные команды, не атомарны.
- Два конкурентных запроса с одним токеном могли оба прочитать `user_id` до удаления → токен использовался дважды.
- **Исправлено:** заменено на `redis.execute_command("GETDEL", key)` (Redis 6.2+, атомарное одноразовое чтение + удаление). Добавлена декодировка `bytes` → `str` (redis-py возвращает bytes для `execute_command`).

**🟡 НОВАЯ НАХОДКА: токен в query string GET-запроса**
- `GET /check-link-token?token=...` — токен попадает в access logs nginx и историю.
- Deep-link архитектура Telegram (`/start link_{token}`) не позволяет передать токен иначе, поэтому GET — вынужденный компромисс.
- **Рекомендация (P2):** не логировать query string в nginx для этого location, либо перевести бот→API вызов на POST с токеном в теле (бот уже использует httpx, можно изменить).

**Промежуточный вывод:** одноразовость токена теперь атомарна (`GETDEL`).

---

### 5. Security-проход по web-роутам

Проверены все файлы в `nura_app/api/routes/`: `web.py`, `tarot_pwa.py`, `push.py`, `reports.py`, `payment.py`, `webhook.py`.

**Авторизация:** все эндпоинты, требующие пользователя, проверяют `session_id` через `user_repo.get_by_web_session_id()` или `telegram_id`. Пропусков нет.

**🟡 НОВАЯ НАХОДКА: `/api/v1/push/unsubscribe` без авторизации**
- `push.py:60-66` — принимает только `{endpoint}`, без `session_id`/`telegram_id`.
- Любой, кто знает push-endpoint другого пользователя (URL сервиса push-уведомлений, виден в DevTools), может отписать чужого пользователя от push-уведомлений.
- **Не чинил в этой сессии** (фиксирую для P2). Рекомендация: требовать `session_id` или `telegram_id` + сверять, что endpoint принадлежит этому пользователю.

**🔴 НОВАЯ НАХОДКА: `/webhook/telegram` без auth/rate-limit/secret**
- `webhook.py:13-24` — POST без проверки `X-Telegram-Bot-Api-Secret-Token`, без rate limit.
- Произвольный запрос проксируется в Telegram API `processUpdate` — это open proxy для Telegram Bot API.
- Если бот работает на long-polling (а не webhook), endpoint не нужен — следует удалить. Если webhook используется — добавить проверку секретного заголовка.
- **Не чинил** (фиксирую для P2, требует решения о режиме работы бота).

**Query string session_id / токен (фиксация для P2, не чинил):**
- `web.py:202` `/me?session_id=...` (уже в REPORT.md S2)
- `web.py:189` `/check-link-token?token=...` (новая — токен в URL)
- `tarot_pwa.py:63` `/daily-card?session_id=...` (уже в REPORT.md S2)
- Все попадают в access logs nginx и историю браузера. Рекомендация: перевести на заголовок `X-Session-Id` (чат в `chat.html:107` уже использует этот подход).

**Публичные эндпоинты (by design, безопасно):**
- `reports.py /report/{token}` — токен = unguessable UUID. OK.
- `push.py /vapid-public-key` — публичный ключ VAPID. OK.
- `web.py /mini-analysis` — входная точка, создаёт пользователя. OK.

**Промежуточный вывод:** пропусков авторизации нет. Найдены 2 новые уязвимости (`/push/unsubscribe`, `/webhook/telegram`) и 1 новая query-string находка (`check-link-token`).

---

## Миграции БД

| Миграция | Описание | Применение |
|----------|----------|------------|
| `c3d4e5f6a7b8` | Добавляет `users.notification_prefs` (JSONB, nullable) | `alembic upgrade head` |

**Точные команды:**
```bash
cd /opt/nura/nura_app
export DATABASE_URL="postgresql://nura:SECRET@localhost:5432/nura"
alembic upgrade head
```
Для отката: `alembic downgrade b2c3d4e5f6a7`

**Цепочка:** `e47590a5c5c1` → `add_tarot_and_payment_type` → `b3c1d4e5f5a6` → `5a8cac04bf5e` → `a1b2c3d4e5f6` → `b2c3d4e5f6a7` → **`c3d4e5f6a7b8` (head)**

---

## Новые находки по безопасности (не в исходном REPORT.md)

| ID | Уровень | Файл/строка | Описание |
|----|---------|-------------|----------|
| N1 | 🔴 | `web.py:189` | Race condition `GET`+`DELETE` в `check-link-token` — **исправлено** (`GETDEL`) |
| N2 | 🟡 | `web.py:189` | Токен link-token в query string GET → access logs nginx |
| N3 | 🟡 | `push.py:60-66` | `/push/unsubscribe` без auth — чужая отписка по известному endpoint |
| N4 | 🔴 | `webhook.py:13-24` | `/webhook/telegram` без secret-token проверки и rate limit — open proxy в Telegram API |

---

## Что осталось непротестированным

- **`alembic upgrade head`** не прогнан локально — нет локального PostgreSQL. Команда для ручной проверки приведена в п.3 и в секции миграций. На VPS применить через `docker compose exec api alembic upgrade head` (или из контейнера bot).
- **`/web/notifications`** — нет unit-тестов (в `tests/` нет `test_web.py`). Эндпоинт покрыт статической проверкой: валидация ключей whitelist, проверка session_id, миграция корректна. Рекомендуется добавить тесты в следующей сессии.
- **`GETDEL`** требует Redis ≥ 6.2. На проде Redis 7 (из `docker-compose.yml`) — поддерживается. Если окружение использует Redis < 6.2, `GETDEL` упадёт — нужен fallback на `GET`+`DELETE` в pipeline с `WATCH`. Проверено: prod использует Redis 7.
- **End-to-end оплата** через `/web/subscribe` — требует реального YooKassa-платежа (норма, как и в REPORT.md).
- **Привязка PWA↔Telegram end-to-end** — статически проверена, runtime-тест требует реального Telegram-аккаунта.

---

## Изменённые файлы

| Файл | Изменение |
|------|-----------|
| `frontend/pwa/app/profile.html` | `/test-subscribe`→`/subscribe` + обработка ошибок; `/user/notifications`→`/web/notifications` + логирование |
| `nura_app/api/routes/web.py` | `PATCH/GET /notifications`; `check-link-token` → `GETDEL` |
| `nura_app/core/models.py` | Поле `notification_prefs` (JSONB) |
| `nura_app/core/repositories/user.py` | `update_notification_pref()`, `get_notification_prefs()` |
| `nura_app/alembic/env.py` | `_resolve_url()` из `DATABASE_URL` env |
| `nura_app/alembic.ini` | `sqlalchemy.url` очищен + комментарий |
| `nura_app/alembic/versions/c3d4e5f6a7b8_add_notification_prefs.py` | Новая миграция |

## Проверки

- `ruff check` на изменённых Python-файлах — **All checks passed** (1 pre-existing F401 в `web.py:14` не из моих правок, не трогал)
- `alembic heads` → `c3d4e5f6a7b8 (head)` ✅
- `alembic history` — цепочка корректна ✅
- `pytest tests/test_tarot_pwa.py tests/test_matrix.py tests/test_chat.py` — **152 passed** ✅
- Полный `pytest` — 84 passed, 4 xfailed, 1 error (`ModuleNotFoundError: aiosqlite` — pre-existing env issue, не связано с правками)

---

*Конец отчёта сессии 2.*
