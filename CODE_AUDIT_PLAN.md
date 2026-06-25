# ПЛАН: Масштабное техническое ревью кода NURA

## Контекст

Проект практически завершён. Следующий шаг — полный технический аудит: найти баги, рассинхронизации, сломанные интеграции, пропущенные эндпоинты, несоответствия между фронтендом и бэкендом. Агент GLM 5.2 будет выполнять аудит по этому плану последовательно, фиксируя каждую находку по формату: файл → проблема → критичность → исправление.

---

## Область 1: Фронтенд ↔ Бэкенд — контракт API

### 1.1 Полная карта эндпоинтов — сверка

**Реальные эндпоинты backend** (из `nura_app/api/routes/`):

| Метод | Путь | Файл |
|-------|------|------|
| POST | /api/v1/web/mini-analysis | web.py |
| POST | /api/v1/web/create-payment | web.py |
| POST | /api/v1/web/generate-link-token | web.py |
| GET | /api/v1/web/check-link-token | web.py |
| GET | /api/v1/web/me | web.py |
| POST | /api/v1/web/subscribe | web.py |
| POST | /api/v1/web/chat | web.py |
| PATCH | /api/v1/web/notifications | web.py ✓ СУЩЕСТВУЕТ |
| GET | /api/v1/web/notifications | web.py |
| POST | /api/v1/push/vapid-public-key | push.py |
| POST | /api/v1/push/subscribe | push.py |
| POST | /api/v1/push/unsubscribe | push.py |
| GET | /api/v1/tarot/daily-card | tarot_pwa.py |
| POST | /api/v1/tarot/spread | tarot_pwa.py |
| GET | /report/sample | reports.py |
| GET | /report/{token} | reports.py |
| GET | /report/{token}/pdf | reports.py |
| POST | /api/v1/payment/webhook | payment.py |

**Что проверить в frontend:**
- Все вызовы из `chat.html` — сверить пути с таблицей выше
- Все вызовы из `profile.html` — PATCH `/api/v1/web/notifications` вызывается с полями `session_id, key, enabled`?
- Вызовы из `tarot.html` — GET `/api/v1/tarot/daily-card` и POST `/api/v1/tarot/spread`
- `nura-pwa.js` — `/api/v1/push/vapid-public-key` (GET, а не POST в коде?)

### 1.2 Форматы запросов

Проверить каждый вызов:

| Эндпоинт | Backend ожидает | Frontend отправляет |
|----------|----------------|---------------------|
| POST /web/chat | `{session_id: str, message: str, history: []}`, header `X-Session-Id` | Проверить chat.html — session_id в body И в header? |
| GET /web/me | Header `X-Session-Id` | profile.html, chat.html — откуда берёт session_id? |
| PATCH /web/notifications | `{session_id, key, enabled}` body | profile.html — что кладёт в body? |
| POST /push/subscribe | `{endpoint, keys:{p256dh, auth}, session_id}` | nura-pwa.js:136 |

### 1.3 HTTP-коды ответов

- `/web/chat` возвращает **402** при лимите (не 429). `chat.html` проверяет оба: `r.status === 402 || r.status === 429` — подтвердить
- `/web/me` возвращает **404** если сессия не найдена. Frontend делает редирект на `/mini.html`? Если нет — пользователь застрянет
- `/tarot/spread` возвращает **402** без подписки. `tarot.html` показывает paywall?

### 1.4 Поля ответа GET /web/me

Backend возвращает:
```
name, birth_date, archetype, archetype_number, has_matrix, has_tarot,
report_token, subscription_status, subscription_until, tarot_until,
has_pwa_push, telegram_linked, reports[], ref_link
```

Frontend читает (проверить в каждом файле):
- `d.has_matrix` (boolean) — НЕ `d.matrix_arcane_num` (поля нет!)
- `d.reports[]` — массив с `{report_type, token, url}`. Открывать через `/report/{token}`
- `d.telegram_linked` — есть ли логика в profile.html?
- `d.subscription_status` — значения: `"free"`, `"premium"`, `"active"`

---

## Область 2: Критические баги (уже найдены)

### 2.1 CRITICAL: Report.payment_status поля нет

**Файл:** `nura_app/bot/handlers/chat.py` строка ~62  
**Проблема:** `r.payment_status == "paid"` — поля `payment_status` в модели `Report` нет  
Модель Report: `id, user_id, report_type, token, matrix_data, ai_analysis, kitchen_analysis, created_at`  
**Исправление:** Убрать проверку или заменить на `r.report_type == "full"` / факт наличия report

### 2.2 CRITICAL: Hardcoded URL в bot

**Файл:** `nura_app/bot/handlers/start.py` строка ~79  
**Проблема:** `http://127.0.0.1:8000/api/v1/web/check-link-token` захардкожен  
**Исправление:** Использовать `settings.report_base_url` или внутренний API-клиент

### 2.3 MODERATE: ReferralRepository не экспортируется

**Файл:** `nura_app/core/repositories/__init__.py`  
**Проблема:** Не экспортирует `ReferralRepository` (определён в `referral.py`)  
**Исправление:** Добавить в `__init__.py`

---

## Область 3: localStorage — согласованность ключей

Полная карта localStorage ключей — **проверить каждый файл** что ключи совпадают:

| Ключ | Назначение | Где используется |
|------|-----------|-----------------|
| `nura_session_id` | ID веб-сессии | nura-pwa.js, chat.html, profile.html, mini.html |
| `nura-theme` | light/dark тема | nura-pwa.js |
| `nura_push_subscribed` | флаг подписки | nura-pwa.js |
| `nura_push_endpoint` | endpoint пуш | nura-pwa.js |
| `nura_q_YYYY-MM-DD` | счётчик чата (клиент) | chat.html |
| `nura_limit_shown` | флаг лимит-баннера | chat.html |
| `nura_tarot_date` | дата карты дня | tarot.html |
| `nura_tarot_card` | данные карты | tarot.html |
| `nura_birth` | дата рождения | mini.html / profile.html |

**Что проверить:**
- Нет ли опечаток: `nura-session-id` vs `nura_session_id`
- `nura_q_YYYY-MM-DD` (клиент) vs Redis `chat_count:{user_id}` (сервер) — могут разойтись если localStorage очищен. Логика: сервер всегда приоритетен (402 → финальный ответ)
- Есть ли `localStorage.clear()` при разлогине? Какой механизм разлогина?

---

## Область 4: Service Worker и PWA-кэш

**Файл:** `frontend/service-worker.js` — `CACHE_NAME = 'nura-v15'`

### 4.1 Файлы в STATIC_ASSETS

Для каждого пути проверить физическое существование:
- `/app/nura-pwa.css` → `frontend/pwa/app/nura-pwa.css` существует?
- `/static/nura-ds.css` → откуда nginx раздаёт `/static/`? Смотреть `nginx/nura-ai.ru.conf`
- `/pwa-install.js` → `frontend/pwa-install.js` существует?
- `/manifest.json` → `frontend/manifest.json` существует?
- `/offline.html` → `frontend/offline.html` существует?

### 4.2 Версионирование JS/CSS в HTML

HTML файлы подключают ресурсы с query-param: `nura-pwa.js?v=9`  
SW кэширует URL точно — `?v=9` не совпадёт с записью без параметра.  
Проверить: все `<script src=...?v=N>` и `<link rel=stylesheet ...?v=N>` в `chat.html`, `tarot.html`, `profile.html`, `index.html` — версии актуальны и совпадают с реальными файлами?

---

## Область 5: Инфраструктура и Docker

### 5.1 PostgreSQL host в Docker

**Файл:** `nura_app/core/config.py`  
`postgres_host: str = "localhost"` — внутри Docker нужно `"postgres"` (имя сервиса из docker-compose.yml)  
**Проверить:** `.env` на VPS содержит `POSTGRES_HOST=postgres`? Если нет — БД недоступна

### 5.2 Полный чеклист env vars

Сверить `config.py` Settings со `.env` файлом на VPS (перечислить какие есть, каких нет):

```
POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST, POSTGRES_PORT
REDIS_URL
CELERY_BROKER_URL, CELERY_RESULT_BACKEND
TELEGRAM_BOT_TOKEN
BOT_USERNAME
DEEPSEEK_API_KEY
YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY
REPORT_BASE_URL
VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY
SECRET_KEY
APP_ENV
TEST_MODE
```

### 5.3 Docker Compose — сервисы и зависимости

**Файл:** `nura_app/docker-compose.yml`  
- `depends_on` корректны: `api` → `[postgres, redis]`, `celery-worker` → `[redis]`, `celery-beat` → `[redis]`?
- `reports_output` volume: смонтирован на `api` и `celery-worker` одинаковым путём?
- Health checks: есть у `postgres`? Без них `api` может стартовать до готовности БД

### 5.4 Celery задачи

**Файл:** `nura_app/core/tasks.py`  
- `task_time_limit: 300s, soft: 240s` — PDF-генерация укладывается в 240с?
- `send_daily_card` в 03:00 Moscow time — timezone корректная в docker?
- `generate_full_report` — если падает, пользователь никогда не получит отчёт. Есть retry? `max_retries=3`?
- Redis DB разделение: broker=db1, result=db2, app data=db0 — нет конфликтов?

---

## Область 6: Платёжный флоу

**Файлы:** `nura_app/api/routes/payment.py`, `nura_app/core/services/payment.py`

Проверить сквозной путь:
1. `POST /web/create-payment` → создаёт YooKassa платёж, возвращает `payment_url`
2. Пользователь оплачивает → YooKassa шлёт webhook на `POST /api/v1/payment/webhook`
3. Webhook обрабатывает `payment.succeeded`:
   - Типы: `web_matrix` → запускает `generate_full_report`
   - Типы: `web_tarot` → активирует `tarot_subscription`
   - Типы: `subscription` → активирует `premium`
4. После генерации — отчёт доступен по `/report/{token}`

**Что проверить:**
- `/success.html` — что делает после оплаты? Проверяет `GET /web/me` пока не появится отчёт?
- Идемпотентность: `claim_succeeded()` с SELECT FOR UPDATE предотвращает дубли?
- При падении Celery задачи: пользователь заплатил, отчёт не создан — есть ли уведомление?

---

## Область 7: Bot-специфичные проверки

**Файлы:** `nura_app/bot/handlers/`

- `start.py` callback `callback_sample_report` (~180) — отправляет ссылку на `/report/sample`? Текст кнопки?
- `chat.py` — бесплатный лимит: 5 сообщений/день. Как считает? Redis ключ `bot_chat_count:{user_id}`? Отличается от web-лимита `chat_count:{user_id}`?
- `tarot.py` — все spread_type: `weekly`, `question`, `life`, `doubles`, `portal`, `yesno` — все обработаны в боте?
- `onboarding.py` — формат даты `DD.MM.YYYY`. Валидация через `validators.py`? Что если пользователь вводит `1.6.1995`?
- `payment.py` строки 70-77 — lazy import `generate_full_report` внутри callback. Работает корректно?

---

## Область 8: База данных

**Файлы:** `nura_app/core/models.py`, `nura_app/core/repositories/`

- Индексы: `web_session_id` — уникальный + indexed ✓. `telegram_id` — уникальный + indexed ✓. `token` в Report — уникальный + indexed ✓.
- Alembic: есть ли `alembic/versions/`? Выполнить `alembic current` vs `alembic heads` — мигрирована ли БД до последней версии?
- `notification_prefs` — JSONB. Allowed keys: `daily_card`, `weekly_spread`, `practices`, `news`. Валидация только на уровне API (не БД) — нормально?
- Async session: `session_factory` создаётся в `get_async_sessionmaker()` — вызывается ли повторно или singleton?

---

## Область 9: Сквозные пользовательские сценарии

Трассировать каждый путь код-по-коду:

### Сценарий A: Новый веб-пользователь
1. `index.html` CTA → `/mini.html`
2. Ввод даты → `POST /api/v1/web/mini-analysis` → создаёт User + web_session_id
3. localStorage: сохраняет `nura_session_id`
4. Редирект: куда? `/app/chat.html`? `/report/{token}`?

### Сценарий B: Чат → лимит → оплата
1. 5 сообщений → 402 → CTA в chat.html
2. Нажимает кнопку → `POST /web/create-payment`
3. Редирект на `payment_url` (YooKassa)
4. Оплата → webhook → Celery генерирует отчёт
5. Пользователь возвращается на `/success.html` → что видит?

### Сценарий C: Возврат (сессия есть)
1. `GET /web/me` с `X-Session-Id`
2. 200 → показывает профиль
3. 404 → редирект на `/mini.html`
4. Проверить: нет ли бесконечного редиректа если `/mini.html` сам делает GET /web/me?

---

## Инструкция агенту: разбивка на сессии

Перед тем как начинать аудит — **сначала прочитай весь этот план целиком** и выполни следующее:

1. Оцени каждую Область (1–9) по двум параметрам:
   - **Количество файлов** для чтения (примерное)
   - **Объём вывода** (сколько находок ожидается)

2. Сгруппируй Области в **сессии** так, чтобы каждая сессия:
   - Помещалась в ~80 000 токенов контекста (вход + выход)
   - Заканчивалась на логической границе (не разрывать одну Область на две сессии)
   - Начиналась с краткого резюме результатов предыдущей сессии

3. Выведи план сессий в формате:

```
=== ПЛАН СЕССИЙ ===

СЕССИЯ 1: [Название]
Области: X, Y, Z
Файлы для чтения: [список]
Ожидаемый вывод: ~N строк

СЕССИЯ 2: [Название]
...
```

4. **Только после вывода плана сессий** — приступай к выполнению Сессии 1.

5. В конце каждой сессии выводи:
```
=== ИТОГ СЕССИИ N ===
Проверено областей: X
Найдено: N critical, M warning, K info
Следующая сессия: [что будет проверяться]
```

6. Все находки записывай в единый файл `audit-report.md` в формате:
```
[CRITICAL|WARNING|INFO] [файл:строка] Описание → Исправление
```

---

## Формат вывода для GLM 5.2

По каждой проверенной области:
1. Прочитать указанные файлы
2. Зафиксировать находку: `[ФАЙЛ:СТРОКА] Описание проблемы`
3. Оценить: **CRITICAL** / **WARNING** / **INFO**
4. Предложить: конкретное исправление (что менять, на что)

### Приоритеты

**CRITICAL (сломан флоу):**
- `Report.payment_status` не существует — логика в chat.py падает молча
- Захардкоженный URL в start.py — бот не работает при смене порта API
- Отсутствующие env vars в `.env` на VPS

**WARNING (потенциальный баг):**
- localStorage vs Redis лимит-десинхрон
- SW STATIC_ASSETS включает несуществующие пути
- Celery задачи без retry при падении
- Health checks в docker-compose

**INFO (улучшение):**
- ReferralRepository не в __init__.py
- Непоследовательный формат error responses
- Lazy imports в bot/handlers/payment.py
