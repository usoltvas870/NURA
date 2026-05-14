# План разработки NURA

Порядок — от ядра к периферии. Каждый следующий шаг опирается на предыдущий.

---

## Этап 1 — База данных и модели

**Файлы:** `core/models.py`, `alembic/`

| Задача | Что сделать |
|--------|-------------|
| 1.1 | Обновить `User`: добавить `username`, `first_name`, `main_archetype`, `main_archetype_number`, `subscription_until`, `payment_method_id` |
| 1.2 | Обновить `Report`: добавить `report_type` enum ("mini" / "full" / "compatibility") |
| 1.3 | Сгенерировать и накатить миграции (`alembic revision --autogenerate`, `alembic upgrade head`) |
| 1.4 | Накатить на dev-базу |

---

## Этап 2 — Репозитории (Data Access Layer)

**Файлы:** `core/repositories/`

Сервисы должны работать через репозитории, а не через SQLAlchemy-сессии напрямую.

| Задача | Файл | Что делает |
|--------|------|------------|
| 2.1 | `core/repositories/__init__.py` | Экспорт всех репозиториев |
| 2.2 | `core/repositories/base.py` | Базовый `SQLAlchemyRepository` с CRUD (add, get, update, delete) |
| 2.3 | `core/repositories/user.py` | `UserRepository`: get_by_telegram_id, create, update_subscription, set_archetype |
| 2.4 | `core/repositories/report.py` | `ReportRepository`: get_by_token, get_by_user_id, create |
| 2.5 | `core/repositories/payment.py` | `PaymentRepository`: create, get_by_yookassa_id, update_status |

---

## Этап 3 — Core Services

**Файлы:** `core/services/`

### 3.1 — Матрица

| Задача | Что сделать |
|--------|-------------|
| 3.1 | Переписать `matrix.py` по `docs/matrix-algo.md`: точные формулы, все позиции, 22 аркана |
| 3.2 | Покрыть unit-тестами (10+ дат, сверка с эталонными расчётами) |

### 3.2 — AI

| Задача | Что сделать |
|--------|-------------|
| 3.3 | Переписать `ai.py` по `docs/prompt-spec.md`: новые system/user промпты, валидация JSON |
| 3.4 | Добавить fallback: при ошибке DeepSeek → возвращать шаблонный мини-разбор |
| 3.5 | Добавить retry + timeout (3 попытки, 30s timeout) |

### 3.3 — Платежи

| Задача | Что сделать |
|--------|-------------|
| 3.6 | Доработать `payment.py`: create_payment, check_payment, create_subscription, cancel_subscription |

### 3.4 — Отчёты

| Задача | Что сделать |
|--------|-------------|
| 3.7 | Переписать `report.py` по `docs/report-spec.md`: HTML-шаблон, PDF через WeasyPrint |

---

## Этап 4 — Celery Tasks

**Файлы:** `core/tasks.py`

| Задача | Что сделать |
|--------|-------------|
| 4.1 | Переписать `generate_mini_report` — убрать `task.get()`, вернуть асинхронный callback |
| 4.2 | Переписать `generate_full_report` — писать отчёт, сохранять, уведомлять пользователя |
| 4.3 | Добавить `generate_compatibility_report` |
| 4.4 | Добавить `send_daily_insights` — рассылка подписчикам (Celery-beat, каждый день 06:00 UTC) |
| 4.5 | Добавить `check_expiring_subscriptions` — уведомления за 3 дня (Celery-beat, 12:00 UTC) |
| 4.6 | Добавить `downgrade_expired_subscriptions` (Celery-beat, 00:00 UTC) |

---

## Этап 5 — API Routes

**Файлы:** `api/routes/`

| Задача | Что сделать |
|--------|-------------|
| 5.1 | Доработать `payment.py` — полноценный webhook YooKassa (проверка подписи, обновление статуса, запуск Celery) |
| 5.2 | Доработать `reports.py` — отдача HTML + PDF, проверка доступа |
| 5.3 | Добавить эндпоинт `POST /api/v1/chat` — для AI-чата через API (если нужно отдельно от бота) |

---

## Этап 6 — Бот: Middleware

**Файлы:** `bot/middlewares/`

| Задача | Что сделать |
|--------|-------------|
| 6.1 | `registration.py` — при каждом апдейте проверять User в БД, создавать при первом входе |
| 6.2 | `throttling.py` — 1 сообщение/сек |
| 6.3 | `anti_flood.py` — 10 сообщений/мин, бан 30 сек |
| 6.4 | Подключить middleware в `bot/main.py` |

---

## Этап 7 — Бот: FSM и Handlers

**Файлы:** `bot/`

Порядок — от простого к сложному. Каждый handler = отдельный router.

### 7.1 — Старт и меню

| Задача | Файл | Что сделать |
|--------|------|-------------|
| 7.1 | `handlers/start.py` | /start, /menu, /help, главное меню (4 кнопки + чат) |
| 7.2 | `states/__init__.py` | MatrixStates, CompatibilityStates, ChatStates |

### 7.2 — Матрица

| Задача | Файл | Что сделать |
|--------|------|-------------|
| 7.3 | `handlers/matrix.py` | Запрос даты → валидация → loading-анимация → мини-разбор → CTA |
| 7.4 | `states/matrix_state.py` | MatrixStates |

### 7.3 — Совместимость

| Задача | Файл | Что сделать |
|--------|------|-------------|
| 7.5 | `handlers/compatibility.py` | Две даты → loading → бесплатные блоки → CTA |
| 7.6 | `states/compatibility_state.py` | CompatibilityStates |

### 7.4 — Инсайты

| Задача | Файл | Что сделать |
|--------|------|-------------|
| 7.7 | `handlers/insights.py` | Инсайт дня по архетипу, кнопки "Ещё" / "Поделиться" |
| 7.8 | `data/insights.py` | Шаблоны инсайтов (22 аркана × 5-7 вариантов) |

### 7.5 — Профиль

| Задача | Файл | Что сделать |
|--------|------|-------------|
| 7.9 | `handlers/profile.py` | 4 варианта профиля, список отчётов, кнопки открыть/скачать PDF |

### 7.6 — Чат с NURA

| Задача | Файл | Что сделать |
|--------|------|-------------|
| 7.10 | `handlers/chat.py` | FSM chatting/idle, AI-ответы с контекстом матрицы |
| 7.11 | `states/chat_state.py` | ChatStates |

### 7.7 — Платежи

| Задача | Файл | Что сделать |
|--------|------|-------------|
| 7.12 | `handlers/payment.py` | pay_full_report, pay_compatibility, buy_subscription — создание платежа, ссылка, ожидание, уведомление |

---

## Этап 8 — Бот: Keyboards и Texts

**Файлы:** `bot/keyboards/`, `bot/texts/`

| Задача | Что сделать |
|--------|-------------|
| 8.1 | Вынести все тексты из handler'ов в `bot/texts/` по модулям |
| 8.2 | Написать все клавиатуры в `bot/keyboards/` |

---

## Этап 9 — Подключение и интеграция

| Задача | Что сделать |
|--------|-------------|
| 9.1 | Переключить FSM storage с MemoryStorage на RedisStorage |
| 9.2 | Подключить все router'ы в `bot/main.py` |
| 9.3 | Настроить webhook (вместо polling) |

---

## Этап 10 — Тесты

**Файлы:** `tests/`

| Задача | Что покрыть |
|--------|-------------|
| 10.1 | `test_matrix.py` — расчёт матрицы для 10+ дат |
| 10.2 | `test_ai.py` — парсинг JSON-ответа, fallback |
| 10.3 | `test_payment.py` — создание платежа, webhook |
| 10.4 | `test_bot_handlers.py` — FSM-переходы, callback_data |
| 10.5 | `test_middleware.py` — регистрация, throttle, anti-flood |

---

## Сводная очерёдность

```
Этап   Что           Результат
─────  ────────────  ───────────────────────────────
1      DB + models   Миграции накачены, модели актуальны
2      Repositories  Data access layer готов
3      Services      Матрица, AI, платежи, отчёты
4      Celery        Фоновые задачи + beat-расписание
5      API           Webhook YooKassa, отдача отчётов
6      Middleware     Регистрация, throttle, anti-flood
7      Handlers      Все 7 блоков бота (FSM, callback'и)
8      Keyboards     Клавиатуры + тексты в отдельных файлах
9      Integration   Redis, webhook, все router'ы
10     Tests         Покрытие core + bot
```

---

## После этапа 10 — деплой

```
1. docker compose build
2. docker compose up -d
3. Проверить /health
4. Проверить через бота: /start → матрица → платёж → отчёт
```
