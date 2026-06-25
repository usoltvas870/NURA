# Admin Panel — Workflow для агентов

## Общее описание

Реализация панели администратора на `nura-ai.ru/admin` — агрегированная статистика, контроль здоровья сервиса, рассылка. **7 секций**: Dashboard, Пользователи, Финансы, Таро, Push, Здоровье, Рассылка.

Работа разбита на **4 последовательных этапа** (каждый — отдельная сессия агента). Этапы наслаиваются друг на друга: Этап 2 использует API из Этапа 1, Этап 3 дополняет код Этапов 1 и 2.

## Статус этапов

| Этап | Описание | Статус |
|------|----------|--------|
| 1 | Backend API | `completed` |
| 2 | Frontend | `completed` |
| 3 | Рассылка (Broadcast) | `completed` |
| 4 | Инфраструктура и деплой | `completed` |

---

## Правила для агента (общие)

1. **Прочитай этот документ полностью** перед началом работы — особенно секцию того этапа, который выполняешь.
2. Выполни все шаги этапа. Не пропускай проверки.
3. **В конце этапа** обнови таблицу статусов выше: замени `pending` своего этапа на `completed`. Если есть следующий этап — поставь ему `in_progress`.
4. **Напиши в чат 2-3 короткие строки** (шаблон в конце этапа) — это «эстафета» для следующего агента.
5. Не коммить, не пушить и не деплоить — только код.

---

## Этап 1: Backend API

**Статус:** `completed`

### Промпт для агента

Контекст:
- Backend: FastAPI async, `C:\git\NURA\nura_app\api\`
- База: PostgreSQL (SQLAlchemy 2.0 async), модели в `C:\git\NURA\nura_app\core\models.py`
- Конфиг: `C:\git\NURA\nura_app\core\config.py` (pydantic-settings, `.env`)
- Рабочая директория: `nura_app/`

Что нужно сделать:

#### 1.1 Прочитать существующие файлы (для понимания паттернов)

- `nura_app/core/config.py` — класс `Settings`, добавляем поле в конец
- `nura_app/api/routes/web.py` — пример структуры роутера (префикс, Depends, Pydantic-модели)
- `nura_app/api/main.py` — как регистрируются роутеры
- `nura_app/core/models.py` — модели User, Payment, Report
- `nura_app/core/database.py` — `get_async_sessionmaker()`, `get_redis()`

#### 1.2 `nura_app/core/config.py` — добавить поле

В класс `Settings`, после существующих полей (например, после `test_mode: bool = False`), добавить:

```python
admin_token: str | None = None
```

#### 1.3 Создать `nura_app/api/routes/admin_api.py`

FastAPI роутер с защитой через `Depends(verify_admin_token)`. Все эндпоинты требуют заголовок `X-Admin-Token`. Если токен не совпадает с `settings.admin_token` — 401.

##### Защита:

```python
from fastapi import APIRouter, Depends, Header, HTTPException
from core.config import settings

async def verify_admin_token(x_admin_token: str = Header(..., alias="X-Admin-Token")) -> None:
    if not settings.admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")

router = APIRouter(prefix="/api/v1/admin", dependencies=[Depends(verify_admin_token)])
```

##### Эндпоинты (все через `get_async_sessionmaker()` + SQLAlchemy async):

**`GET /api/v1/admin/stats`** — агрегированная статистика.

Используй `select` с `func.count()` / `func.sum()` / `func.coalesce()` через SQLAlchemy 2.0 async. Для спарклайнов — сырой SQL через `await session.execute(text("..."))`.

Поля ответа (Pydantic-модель):
- `users_total: int`
- `users_new_24h: int`
- `users_new_7d: int`
- `subscriptions_premium_active: int`
- `subscriptions_tarot_active: int`
- `users_telegram_linked: int`
- `users_push_subscribed: int`
- `revenue_total: int` (в копейках)
- `revenue_30d: int`
- `revenue_7d: int`
- `unique_paying_users: int`
- `payment_breakdown: list[dict]` — `payment_type, count, total_amount`
- `reports_by_type: dict` — `{"mini": N, "full": N, "compatibility": N}`
- `registrations_by_day: list[dict]` — `date, value` за последние 14 дней
- `revenue_by_day: list[dict]` — `date, value` за последние 14 дней

SQL-запросы (используй их как эталон, реализуй через SQLAlchemy или `text()`):

```sql
SELECT COUNT(*) FROM users;
SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '24 hours';
SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '7 days';
SELECT COUNT(*) FROM users WHERE subscription_status = 'premium' AND (subscription_until IS NULL OR subscription_until > NOW());
SELECT COUNT(*) FROM users WHERE tarot_subscription = true AND (tarot_subscription_until IS NULL OR tarot_subscription_until > NOW());
SELECT COUNT(*) FROM users WHERE telegram_id IS NOT NULL;
SELECT COUNT(*) FROM users WHERE has_pwa_push = true;
SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'succeeded';
SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'succeeded' AND created_at >= NOW() - INTERVAL '30 days';
SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'succeeded' AND created_at >= NOW() - INTERVAL '7 days';
SELECT payment_type, COUNT(*), COALESCE(SUM(amount), 0) FROM payments WHERE status = 'succeeded' GROUP BY payment_type;
SELECT COUNT(DISTINCT user_id) FROM payments WHERE status = 'succeeded';
SELECT report_type, COUNT(*) FROM reports GROUP BY report_type;
SELECT DATE(created_at AT TIME ZONE 'UTC') as day, COUNT(*) as cnt FROM users WHERE created_at >= NOW() - INTERVAL '14 days' GROUP BY day ORDER BY day;
SELECT DATE(created_at AT TIME ZONE 'UTC') as day, COALESCE(SUM(amount), 0) as revenue FROM payments WHERE status = 'succeeded' AND created_at >= NOW() - INTERVAL '14 days' GROUP BY day ORDER BY day;
```

**`GET /api/v1/admin/users`** — таблица пользователей с пагинацией и фильтрами.

Query params: `page: int = 1`, `per_page: int = 50`, `search: str | None`, `filter: str | None` (значения: `premium`, `tarot`, `telegram`, `push`).

JOIN с `payments` для подсчёта `payments_count` и `total_paid` (используй `func.coalesce(func.sum(Payment.amount), 0)` + фильтр `status = 'succeeded'`).

Поля ответа: `id`, `telegram_id`, `username`, `first_name`, `name`, `birth_date`, `main_archetype`, `subscription_status`, `subscription_until`, `tarot_subscription`, `has_matrix`, `has_pwa_push`, `created_at`, `payments_count`, `total_paid`.

Ответ: `{users: [...], total: N, page: N, per_page: N, pages: N}`.

**Поиск**: если `search` передан — `User.name.ilike(f'%{search}%') OR User.username.ilike(f'%{search}%') OR User.first_name.ilike(f'%{search}%')`.

**Фильтр**: если `filter` = "premium" → `subscription_status == 'premium'`; "tarot" → `tarot_subscription == True`; "telegram" → `telegram_id != None`; "push" → `has_pwa_push == True`.

**`GET /api/v1/admin/payments`** — таблица транзакций.

Query params: `page: int = 1`, `per_page: int = 50`, `status: str | None`, `payment_type: str | None`.

JOIN с `users` для `user_name` (используй `User.first_name` или `User.name`).

Ответ: `{payments: [...], total: N, page: N, per_page: N, pages: N, total_succeeded_amount: int}`.

**`GET /api/v1/admin/health`** — статус компонентов.

Параллельные проверки через `asyncio.gather(return_exceptions=True)` с таймаутом 5 секунд каждая:

| Компонент | Проверка |
|---|---|
| PostgreSQL | `SELECT 1` через async session, замер latency |
| Redis | `await redis.ping()`, замер latency |
| DeepSeek | `GET https://api.deepseek.com/v1/models` с `Authorization: Bearer {settings.deepseek_api_key}` через `httpx.AsyncClient` |
| Yookassa | `GET https://api.yookassa.ru/v3/me` с Basic Auth `{settings.yookassa_shop_id}:{settings.yookassa_secret_key}` через `httpx.AsyncClient` |
| Telegram Bot | `GET https://api.telegram.org/bot{settings.telegram_bot_token}/getMe` через `httpx.AsyncClient` |

Формат ответа:
```json
{
  "overall": "ok",
  "components": [
    {"name": "PostgreSQL", "status": "ok", "latency_ms": 3.2, "detail": null},
    {"name": "Redis", "status": "ok", "latency_ms": 0.8, "detail": null},
    {"name": "DeepSeek", "status": "error", "latency_ms": null, "detail": "Connection timeout"}
  ],
  "checked_at": "2026-06-25T12:00:00Z"
}
```

`overall` = "error" если есть errors, "degraded" если только Redis/DeepSeek недоступны, "ok" иначе.

#### 1.4 `nura_app/api/main.py` — зарегистрировать роутер

Добавить импорт и `include_router` по аналогии с существующими:

```python
from api.routes.admin_api import router as admin_api_router
app.include_router(admin_api_router)
```

#### 1.5 Проверка

```bash
cd nura_app && ruff check api/routes/admin_api.py api/main.py core/config.py
```

Исправь все ошибки линтера если есть (`ruff check --fix .`).

#### По завершении Этапа 1

1. Обнови таблицу статусов в начале этого файла: Этап 1 → `completed`.
2. Напиши в чат ровно такой текст:

```
Этап 1 завершён. Backend API готов: /api/v1/admin/stats, /users, /payments, /health.
Для продолжения: прочитай C:\git\NURA\ADMIN_PANEL_WORKFLOW.md и выполни Этап 2.
```

---

## Этап 2: Frontend

**Статус:** `completed`

### Промпт для агента

Контекст:
- Фронтенд: vanilla HTML/CSS/JS (без фреймворков, без async/await — только `.then()/.catch()`)
- Базовый URL: `https://nura-ai.ru`
- API готово из Этапа 1: `GET /api/v1/admin/stats`, `GET /api/v1/admin/users`, `GET /api/v1/admin/payments`, `GET /api/v1/admin/health`
- Существующий PWA фронтенд: `C:\git\NURA\frontend\pwa\app\` — можно посмотреть для стиля

Что нужно сделать:

#### 2.1 Создать `C:\git\NURA\frontend\admin\index.html`

Одностраничный HTML (все CSS и JS инлайн). Размер ~800-1000 строк.

**Дизайн-токены NURA:**

```css
--bg: #12100E;
--bg-card: #1C1A17;
--terra: #B8743F;
--text: #F0EDE7;
--text-m: rgba(240,237,231,.65);
--text-s: rgba(240,237,231,.38);
--green: #4CAF50;
--red: #E53935;
--yellow: #FFB300;
```

Шрифты: Playfair Display (заголовки), Manrope (текст) — подключить из Google Fonts.

**Auth flow:**
- При загрузке: проверить `localStorage.getItem('nura-admin-token')`
- Если нет → показать экран логина (форма ввода токена)
- При вводе: `GET /api/v1/admin/stats` с `X-Admin-Token: <token>`
- 401 → очистить localStorage, показать ошибку "Неверный токен"
- 200 → сохранить в localStorage, показать панель

**Header:**
- NURA logo/название слева
- Кнопка «Выход» справа — удаляет токен из localStorage, перезагружает страницу

**Tab navigation (вверху, sticky):**
Dashboard / Пользователи / Финансы / Таро / Push / Здоровье

При клике на таб — показать соответствующую секцию, скрыть остальные. Активный таб подсвечивается цветом `--terra`.

**Функция `apiFetch(path)`** — обёртка над `fetch()`, добавляет `X-Admin-Token` из localStorage, обрабатывает 401 (редирект на логин).

**Секция Dashboard:**
- CSS Grid 3 колонки с KPI карточками: Всего пользователей, Новых за 24ч, Новых за 7д, Премиум активных, Таро активных, Telegram-linked, Push-подписчиков, Выручка всего, Выручка 30д, Выручка 7д
- Каждая карточка: большое число + подпись + дельта ("+12 за 24ч" зелёным если >0)
- SVG спарклайны под двумя карточками (регистрации и выручка) — 14 точек через `<polyline>`, используются массивы `registrations_by_day` и `revenue_by_day` из ответа `/stats`

```javascript
function renderSparkline(container, points, color) {
  var max = Math.max.apply(null, points.map(function(p) { return p.value; })) || 1;
  var w = 200, h = 40;
  var pts = points.map(function(p, i) {
    return [(i / (points.length - 1)) * w, h - (p.value / max) * (h - 4) - 2].join(',');
  }).join(' ');
  container.innerHTML = '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" style="width:100%;height:40px">'
    + '<polyline points="' + pts + '" fill="none" stroke="' + color + '" stroke-width="2"/>'
    + '</svg>';
}
```

**Секция Пользователи:**
- Input поиска с debounce 400ms
- Кнопки-фильтры: Все / Premium / Таро / Telegram / Push
- `<table>` с колонками: Имя, Telegram, Архетип, Статус, Подписка, Создан, Платежей, Сумма
- Вызов `GET /api/v1/admin/users?page=...&per_page=50&search=...&filter=...`
- Пагинация: кнопки «Назад» / «Вперёд» + "страница N из M"

**Секция Финансы:**
- 3 большие карточки: выручка за 7д / 30д / всего (в рублях — делить на 100)
- Таблица breakdown по типам платежей (из `payment_breakdown`)
- Таблица транзакций с фильтрами по статусу и типу платежа
- Вызов `GET /api/v1/admin/payments?page=...&status=...&payment_type=...`

**Секция Таро:**
- Карточки: мини-отчётов, полных, совместимости (из `reports_by_type`)
- Карточка: активных Tarot-подписок

**Секция Push:**
- Карточка: всего подписчиков на push
- Процент от общего числа пользователей

**Секция Здоровье:**
- Список компонентов с цветной точкой (зелёный `--green`, красный `--red`, жёлтый `--yellow`) + latency в ms
- Кнопка «Обновить сейчас» — ручной запрос
- Время последней проверки

**Автообновление:**
- Каждые 30 секунд обновлять данные активной вкладки (Dashboard или Здоровье). Остальные вкладки не обновлять.
- Использовать `setInterval` с проверкой активного таба.

#### 2.2 Проверка

Открой `frontend/admin/index.html` в браузере локально — убедись что верстка не разваливается (хотя бы визуально). JS-логика сработает только при живом API, но синтаксис должен быть без ошибок.

#### По завершении Этапа 2

1. Обнови таблицу статусов в начале этого файла: Этап 2 → `completed`.
2. Напиши в чат ровно такой текст:

```
Этап 2 завершён. Frontend готов: 6 вкладок, тёмная тема NURA, автообновление.
Для продолжения: прочитай C:\git\NURA\ADMIN_PANEL_WORKFLOW.md и выполни Этап 3.
```

---

## Этап 3: Рассылка (Broadcast)

**Статус:** `completed`

### Промпт для агента

Контекст:
- Этапы 1 и 2 уже завершены — есть `api/routes/admin_api.py` и `frontend/admin/index.html`.
- Celery определён в `core/tasks.py` (переменная `celery_app`). Синхронные задачи Celery вызывают async через `_run_async(coro)`.
- Redis доступен через `get_redis()` из `core/database.py`.
- Web Push: `send_web_push()` из `core/services/web_push.py`.
- Модель User имеет поля: `telegram_id`, `has_pwa_push`, `push_endpoint`, `push_p256dh`, `push_auth`, `subscription_status`, `first_name`.

Перед началом прочитай:
- `nura_app/core/tasks.py` — формат Celery-задач, функция `_run_async`, как пользоваться `get_async_sessionmaker()`
- `nura_app/api/routes/admin_api.py` — куда добавлять новые эндпоинты
- `nura_app/frontend/admin/index.html` — куда добавлять UI секцию
- `nura_app/core/services/web_push.py` — сигнатура `send_web_push`

Что нужно сделать:

#### 3.1 Celery-задача `send_broadcast` — добавить в `core/tasks.py`

Добавить в конец файла (перед последним блоком если есть):

```python
@celery_app.task(name="core.tasks.send_broadcast", bind=True)
def send_broadcast(self, text: str, channels: list[str], filter_type: str,
                   push_title: str | None = None, push_url: str | None = None):
    return _run_async(_send_broadcast_async(
        self.request.id, text, channels, filter_type, push_title, push_url
    ))
```

Асинхронная реализация `_send_broadcast_async` (в том же файле):

1. Получить список пользователей по фильтру из БД:
   - `filter_type == "premium"` → `User.subscription_status == "premium"`
   - `filter_type == "free"` → `User.subscription_status == "free"`
   - `filter_type == "all"` → все пользователи

2. Инициализировать прогресс в Redis: `redis.set(f"broadcast:{task_id}", json.dumps({"status": "running", "sent": 0, "total": total, "failed": 0, "finished_at": None}))`

3. Telegram-рассылка (если "telegram" в channels):
   - Только пользователи с `telegram_id is not None`
   - `asyncio.run()` не нужен — задача уже async
   - Вызов: `await bot.send_message(chat_id=user.telegram_id, text=text, parse_mode="HTML")`
   - Пауза `await asyncio.sleep(1/25)` (~25 msg/s, с запасом от лимита Telegram 30/s)
   - Для доступа к боту: импортировать `from bot.main import bot` (проверь точный путь в коде)
   - При `TelegramForbiddenError` (403) — пропустить пользователя, увеличить `failed`
   - При других ошибках — логировать, увеличить `failed`
   - После каждого сообщения обновлять прогресс в Redis

4. Web Push рассылка (если "push" в channels):
   - Только пользователи с `has_pwa_push == True` и непустыми `push_endpoint`, `push_p256dh`, `push_auth`
   - Вызов: `await send_web_push(user.push_endpoint, user.push_p256dh, user.push_auth, push_title, text[:200], push_url or "/app", "broadcast")`
   - При `PushSubscriptionExpired` (410) — сбросить `has_pwa_push = False` в БД, увеличить `failed`
   - После каждого обновлять прогресс в Redis

5. По завершении: `redis.set("broadcast:{task_id}", json.dumps({"status": "completed", "sent": sent, "total": total, "failed": failed, "finished_at": datetime.now().isoformat()}))`

**Важно:** redis используется синхронно в контексте Celery? Нет — `get_redis()` из `core/database.py` возвращает `redis.asyncio.Redis`, так что используем `await redis.set(...)`.

#### 3.2 Эндпоинты рассылки — добавить в `api/routes/admin_api.py`

Добавить в конец файла, внутри существующего роутера:

**`POST /api/v1/admin/broadcast`**:

```python
class BroadcastRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    channels: list[str] = Field(..., min_length=1)
    filter: str = "all"
    push_title: str | None = None
    push_url: str | None = None

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, v):
        allowed = {"telegram", "push"}
        for ch in v:
            if ch not in allowed:
                raise ValueError(f"Invalid channel: {ch}")
        return v

    @field_validator("filter")
    @classmethod
    def validate_filter(cls, v):
        if v not in ("all", "premium", "free"):
            raise ValueError("Filter must be all, premium, or free")
        return v

@router.post("/broadcast")
async def start_broadcast(body: BroadcastRequest):
    from core.tasks import send_broadcast
    task = send_broadcast.delay(
        text=body.text,
        channels=body.channels,
        filter_type=body.filter,
        push_title=body.push_title,
        push_url=body.push_url,
    )
    return {"task_id": task.id, "status": "queued"}
```

**`GET /api/v1/admin/broadcast/status/{task_id}`**:

```python
@router.get("/broadcast/status/{task_id}")
async def get_broadcast_status(task_id: str):
    import json
    redis = get_redis()
    raw = await redis.get(f"broadcast:{task_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Task not found")
    return json.loads(raw)
```

#### 3.3 UI секция «Рассылка» — добавить в `frontend/admin/index.html`

Добавить новый таб «Рассылка» (после Здоровья, перед Push или в конец).

Интерфейс:
- Textarea для текста сообщения (5 строк, placeholder "Текст сообщения (HTML поддерживается)")
- Чекбоксы каналов: Телеграм / Web Push
- Радиокнопки фильтра получателей: Все / Premium / Free
- Поле ввода «Push-заголовок» (показывать только если выбран Web Push)
- Поле ввода «Push-ссылка» (показывать только если выбран Web Push)
- Кнопка «Отправить рассылку»
- Прогресс-бар (div с динамической шириной) + текст "847 / 1500 отправлено"
- Текст «Ошибок: 3»

JS-логика:
- `startBroadcast()` — собирает payload, вызывает `POST /api/v1/admin/broadcast`, получает `task_id`
- `pollBroadcastStatus()` — каждые 2 секунды вызывает `GET /api/v1/admin/broadcast/status/{task_id}`
- `renderBroadcastProgress(r)` — обновляет прогресс-бар и текст
- Пока рассылка идёт — кнопка неактивна
- После завершения — кнопка снова активна, показываем результат

#### 3.4 Проверка

```bash
cd nura_app && ruff check core/tasks.py api/routes/admin_api.py
```

#### По завершении Этапа 3

1. Обнови таблицу статусов в начале этого файла: Этап 3 → `completed`.
2. Напиши в чат ровно такой текст:

```
Этап 3 завершён. Рассылка готова: Celery-задача, эндпоинты, UI.
Для продолжения: прочитай C:\git\NURA\ADMIN_PANEL_WORKFLOW.md и выполни Этап 4.
```

---

## Этап 4: Инфраструктура и деплой

**Статус:** `pending`

### Промпт для агента

Контекст:
- Все предыдущие этапы завершены.
- Nginx конфиг: `C:\git\NURA\nura_app\nginx\nura-ai.ru.conf`
- Deploy скрипт: `C:\git\NURA\deploy.sh`
- Проект на VPS: `/opt/nura/`
- Статика на VPS: `/var/www/nura-ai.ru/`

Что нужно сделать:

#### 4.1 `nura_app/nginx/nura-ai.ru.conf` — добавить admin location

Добавить ДО блока `location /app/` (строка ~121 в текущем конфиге):

```nginx
# Admin Panel
location /admin/ {
    allow ADMIN_IP;   # заменить на реальный IP администратора при деплое
    deny all;
    alias /var/www/nura-ai.ru/admin/;
    try_files $uri /admin/index.html;
    add_header Cache-Control "no-cache" always;
}
```

И редирект с `/admin` на `/admin/` (рядом с другими `location = /...` блоками, например перед `/mini`):

```nginx
location = /admin {
    allow ADMIN_IP;
    deny all;
    return 301 /admin/;
}
```

#### 4.2 `deploy.sh` — добавить копирование admin панели

В корневом `C:\git\NURA\deploy.sh`, после строки с копированием PWA app (строка ~17), добавить:

```bash
echo "→ Copying admin panel..."
mkdir -p /var/www/nura-ai.ru/admin
cp frontend/admin/index.html /var/www/nura-ai.ru/admin/index.html
```

#### 4.3 Финальный линт

```bash
cd nura_app && ruff check .
```

Исправь все ошибки.

#### 4.4 Инструкция для ручного деплоя (НЕ выполнять агенту — только написать)

Сохрани инструкцию в чат в конце работы:

```
Ручные действия на VPS после деплоя кода:
1. В `.env` на VPS добавить: ADMIN_TOKEN=<openssl rand -hex 32>
2. В `nura_app/nginx/nura-ai.ru.conf` заменить `ADMIN_IP` на реальный IP
3. Перезапустить backend: docker compose up -d --build api bot celery-worker
4. Проверить nginx: nginx -t && systemctl reload nginx
5. Открыть https://nura-ai.ru/admin/ и ввести токен
```

#### По завершении Этапа 4

1. Обнови таблицу статусов в начале этого файла: Этап 4 → `completed`.
2. Напиши в чат ровно такой текст:

```
Этап 4 завершён. Инфраструктура готова: nginx, deploy.sh, линт пройден.

Ручные действия на VPS после деплоя кода:
1. В `.env` на VPS добавить: ADMIN_TOKEN=<openssl rand -hex 32>
2. В `nura_app/nginx/nura-ai.ru.conf` заменить `ADMIN_IP` на реальный IP
3. docker compose up -d --build api bot celery-worker (из nura_app/)
4. nginx -t && systemctl reload nginx
5. Открыть https://nura-ai.ru/admin/ и ввести токен

Все этапы завершены. Проект готов к деплою.
```

---

## Завершение

После прохождения всех 4 этапов проект admin-панели полностью готов. Остаются только ручные действия на VPS (добавление ADMIN_TOKEN, замена IP, перезапуск). Ниже ожидаемая структура созданных/изменённых файлов:

| Файл | Этап | Действие |
|------|------|----------|
| `nura_app/core/config.py` | 1 | Добавлено поле `admin_token` |
| `nura_app/api/routes/admin_api.py` | 1, 3 | Создан (6 эндпоинтов + 2 для рассылки) |
| `nura_app/api/main.py` | 1 | Добавлен `include_router` |
| `nura_app/core/tasks.py` | 3 | Добавлена задача `send_broadcast` |
| `frontend/admin/index.html` | 2, 3 | Создан (7 секций: Dashboard, Пользователи, Финансы, Таро, Push, Здоровье, Рассылка) |
| `nura_app/nginx/nura-ai.ru.conf` | 4 | Добавлены location `/admin/` и `/admin` |
| `deploy.sh` | 4 | Добавлено копирование admin-панели |
