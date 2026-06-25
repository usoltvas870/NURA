# Admin Panel — план реализации

## Контекст

Нужна панель администратора на `nura-ai.ru/admin` для контроля работоспособности сервиса.
Показывает агрегированную статистику по пользователям, финансам, Таро, push-уведомлениям и здоровью компонентов.

**Про sqladmin**: в коде (`nura_app/api/admin.py`) есть sqladmin, смонтированный на `/admin`, но в nginx нет location для него — реально возвращает 404 и никем не используется. URL `/admin` свободен.

**Безопасность**: IP restriction в nginx (только IP администратора) + токен-аутентификация через `X-Admin-Token` header.

---

## Стек проекта (для понимания)

- **Frontend**: `/frontend/pwa/app/` — PWA, vanilla HTML/CSS/JS, без фреймворков
- **Backend**: `/nura_app/api/` — Python FastAPI (async)
- **DB**: PostgreSQL (async SQLAlchemy) + Redis
- **AI**: DeepSeek API (`deepseek-chat`)
- **Платежи**: Yookassa (890₽ — Матрица, 390₽/мес — Таро-подписка)
- **Deploy**: GitHub Actions → `nura-ai.ru`, nginx на VPS

**Модели БД** (`nura_app/core/models.py`):
- `users`: id, telegram_id, name, birth_date, main_archetype, subscription_status ("free"/"premium"), subscription_until, tarot_subscription, tarot_subscription_until, has_matrix, has_pwa_push, created_at
- `payments`: id, user_id, amount (в копейках), status ("pending"/"succeeded"/"failed"), payment_type ("web_matrix"/"web_tarot"/"subscription"), yookassa_id, created_at
- `reports`: id, user_id, report_type ("mini"/"full"/"compatibility"), token, created_at

**Существующие файлы** (читать перед реализацией):
- `nura_app/api/main.py` — регистрация роутеров, CORS
- `nura_app/api/routes/web.py` — пример структуры роутера
- `nura_app/core/config.py` — Settings (pydantic-settings), читает из `.env`
- `nura_app/core/database.py` — async PostgreSQL session
- `nura_app/nginx/nura-ai.ru.conf` — nginx конфиг

---

## Секции панели (8 штук)

1. **Dashboard** — KPI карточки + спарклайны (пользователи, выручка, подписки)
2. **Пользователи** — таблица с поиском, фильтрами, пагинацией
3. **Финансы** — выручка по периодам, breakdown по типам, история транзакций
4. **Таро** — раскладов сделано, топ типов
5. **Push** — подписчиков, отправлено уведомлений
6. **Здоровье сервиса** — статус OK/Error + latency для PostgreSQL, Redis, DeepSeek, Yookassa, Telegram bot
7. **Рассылка** — отправка сообщений в Telegram и/или Web Push всем пользователям (или по фильтру)

---

## Реализация — шаг за шагом

### Шаг 1. `nura_app/core/config.py`

Добавить поле в класс `Settings`:
```python
admin_token: str | None = None
```

### Шаг 2. Новый файл `nura_app/api/routes/admin_api.py`

FastAPI роутер с защитой через `Depends(verify_admin_token)`.

```python
from fastapi import APIRouter, Depends, Header, HTTPException
from core.config import settings

async def verify_admin_token(x_admin_token: str = Header(..., alias="X-Admin-Token")) -> None:
    if not settings.admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")

router = APIRouter(prefix="/api/v1/admin", dependencies=[Depends(verify_admin_token)])
```

**Эндпоинт `GET /api/v1/admin/stats`** — данные для Dashboard, Таро, Push.

Поля ответа:
- `users_total`, `users_new_24h`, `users_new_7d`
- `subscriptions_premium_active`, `subscriptions_tarot_active`
- `users_telegram_linked`, `users_push_subscribed`
- `revenue_total`, `revenue_30d`, `revenue_7d` (в копейках, делить на 100)
- `unique_paying_users`
- `payment_breakdown`: список `{payment_type, count, total_amount}`
- `reports_by_type`: словарь `{"mini": N, "full": N, "compatibility": N}`
- `registrations_by_day`: список `{date, value}` за последние 14 дней
- `revenue_by_day`: список `{date, value}` за последние 14 дней

SQL-агрегации (через SQLAlchemy async или `text()`):
```sql
-- Всего пользователей
SELECT COUNT(*) FROM users;

-- Новые за 24ч / 7 дней
SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '24 hours';
SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '7 days';

-- Активные Premium подписки
SELECT COUNT(*) FROM users
WHERE subscription_status = 'premium'
  AND (subscription_until IS NULL OR subscription_until > NOW());

-- Активные Tarot подписки
SELECT COUNT(*) FROM users
WHERE tarot_subscription = true
  AND (tarot_subscription_until IS NULL OR tarot_subscription_until > NOW());

-- Telegram-linked / Push
SELECT COUNT(*) FROM users WHERE telegram_id IS NOT NULL;
SELECT COUNT(*) FROM users WHERE has_pwa_push = true;

-- Выручка (total / 30 дней / 7 дней)
SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'succeeded';
SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'succeeded' AND created_at >= NOW() - INTERVAL '30 days';
SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'succeeded' AND created_at >= NOW() - INTERVAL '7 days';

-- Breakdown по типам
SELECT payment_type, COUNT(*), COALESCE(SUM(amount), 0)
FROM payments WHERE status = 'succeeded'
GROUP BY payment_type;

-- Уникальные плательщики
SELECT COUNT(DISTINCT user_id) FROM payments WHERE status = 'succeeded';

-- Отчёты по типам
SELECT report_type, COUNT(*) FROM reports GROUP BY report_type;

-- Спарклайн регистраций (14 дней)
SELECT DATE(created_at AT TIME ZONE 'UTC') as day, COUNT(*) as cnt
FROM users WHERE created_at >= NOW() - INTERVAL '14 days'
GROUP BY day ORDER BY day;

-- Спарклайн выручки (14 дней)
SELECT DATE(created_at AT TIME ZONE 'UTC') as day, COALESCE(SUM(amount), 0) as revenue
FROM payments WHERE status = 'succeeded' AND created_at >= NOW() - INTERVAL '14 days'
GROUP BY day ORDER BY day;
```

---

**Эндпоинт `GET /api/v1/admin/users`**

Query params: `page: int = 1`, `per_page: int = 50`, `search: str | None`, `filter: str | None` (значения: `premium`, `tarot`, `telegram`, `push`)

JOIN с `payments` для подсчёта суммы трат на пользователя.

Поля каждого пользователя в ответе: `id`, `telegram_id`, `username`, `first_name`, `name`, `birth_date`, `main_archetype`, `subscription_status`, `subscription_until`, `tarot_subscription`, `has_matrix`, `has_pwa_push`, `created_at`, `payments_count`, `total_paid`.

Ответ: `{users: [...], total: N, page: N, per_page: N, pages: N}`

---

**Эндпоинт `GET /api/v1/admin/payments`**

Query params: `page: int = 1`, `per_page: int = 50`, `status: str | None`, `payment_type: str | None`

JOIN с `users` для имени пользователя.

Ответ: `{payments: [...], total: N, page: N, per_page: N, pages: N, total_succeeded_amount: N}`

---

**Эндпоинт `GET /api/v1/admin/health`**

Параллельные проверки через `asyncio.gather(return_exceptions=True)` с таймаутом 5s каждая:

| Компонент | Что делаем |
|---|---|
| PostgreSQL | `SELECT 1` через async session, замер latency |
| Redis | `await redis.ping()`, замер latency |
| DeepSeek | `GET https://api.deepseek.com/v1/models` с `Authorization: Bearer {key}` |
| Yookassa | `GET https://api.yookassa.ru/v3/me` с Basic Auth (`shop_id:secret`) |
| Telegram Bot | `GET https://api.telegram.org/bot{TOKEN}/getMe` |

Ответ:
```json
{
  "overall": "ok",
  "components": [
    {"name": "PostgreSQL", "status": "ok", "latency_ms": 3.2, "detail": null},
    {"name": "Redis", "status": "ok", "latency_ms": 0.8, "detail": null},
    {"name": "DeepSeek", "status": "error", "latency_ms": null, "detail": "Connection timeout"},
    ...
  ],
  "checked_at": "2026-06-25T12:00:00Z"
}
```
`overall` = "error" если хотя бы один компонент упал, "degraded" если есть ошибки второстепенных, "ok" если всё работает.

### Шаг 3. `nura_app/api/main.py`

Добавить регистрацию роутера (по аналогии с существующими):
```python
from api.routes.admin_api import router as admin_api_router
app.include_router(admin_api_router)
```

### Шаг 4. Новый файл `frontend/admin/index.html`

Одностраничный HTML (~700 строк), весь CSS и JS **инлайн**. Vanilla JS только через `.then()/.catch()`, никаких `async/await` в inline-скриптах, никаких фреймворков.

**Auth flow:**
- При загрузке: проверить `localStorage.getItem('nura-admin-token')`
- Если токена нет → показать форму ввода (экран логина)
- При вводе: запрос `GET /api/v1/admin/stats` с заголовком `X-Admin-Token: <token>`
- 401 → очистить localStorage, показать ошибку "Неверный токен"
- 200 → сохранить в localStorage, показать панель

**Дизайн:**
- Тёмная тема, цвета в духе NURA:
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
- Шрифты: Playfair Display (заголовки), Manrope (текст) — подключить из Google Fonts
- Tab navigation вверху: Dashboard / Пользователи / Финансы / Таро / Push / Здоровье

**Dashboard секция:**
- CSS Grid 3 колонки с KPI карточками
- Каждая карточка: большое число + подпись + дельта (например, "+12 за 24ч")
- SVG спарклайны (inline, без библиотек) — 14 точек через `<polyline>`

Пример SVG спарклайна:
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

**Пользователи секция:**
- Input поиска с debounce 400ms
- Кнопки-фильтры: Все / Premium / Tarot / Telegram / Push
- `<table>` с колонками: Имя, Telegram, Архетип, Статус, Подписка, Создан, Платежей, Сумма
- Пагинация: кнопки Prev/Next + "страница N из M"

**Финансы секция:**
- 3 карточки: выручка за 7д / 30д / всего
- Таблица breakdown по типам платежей
- Таблица транзакций с фильтром по статусу

**Таро секция:**
- Карточки: мини-отчётов / полных / совместимости
- Активных Tarot-подписок

**Push секция:**
- Карточки: всего подписчиков на push / % от пользователей

**Здоровье секция:**
- Список компонентов с цветной точкой (зелёный/красный/жёлтый) + latency в ms
- Кнопка "Обновить сейчас"
- Время последней проверки

**Авто-обновление:** каждые 30 секунд обновлять активную вкладку (только Dashboard и Здоровье).

**Кнопка выхода** (в header): `localStorage.removeItem('nura-admin-token')` + перезагрузка.

### Шаг 5. `nura_app/nginx/nura-ai.ru.conf`

Добавить location **перед** блоком `location /app/` (строка ~121 в текущем конфиге):

```nginx
# Admin Panel
location /admin/ {
    allow ADMIN_IP;   # заменить на реальный IP администратора
    deny all;
    alias /var/www/nura-ai.ru/admin/;
    try_files $uri /admin/index.html;
    add_header Cache-Control "no-cache" always;
}
```

Также добавить редирект `/admin` → `/admin/`:
```nginx
location = /admin {
    allow ADMIN_IP;
    deny all;
    return 301 /admin/;
}
```

### Шаг 6. `deploy.sh` (файл в корне репо или на VPS)

Найти скрипт деплоя и добавить:
```bash
# Admin Panel
mkdir -p /var/www/nura-ai.ru/admin
cp frontend/admin/index.html /var/www/nura-ai.ru/admin/index.html
```

### Шаг 7. `.env` на VPS (вручную, не коммитить)

Добавить строку:
```
ADMIN_TOKEN=<сгенерировать 32+ случайных символа, например openssl rand -hex 32>
```

### Шаг X. Рассылка — новый раздел панели

#### Backend — два новых эндпоинта в `admin_api.py`

**`POST /api/v1/admin/broadcast`** — запуск рассылки:

```python
class BroadcastRequest(BaseModel):
    text: str                          # текст сообщения (Markdown для Telegram)
    channels: list[str]                # ["telegram", "push"] — один или оба
    filter: str = "all"                # "all" | "premium" | "free"
    push_title: str | None = None      # заголовок push-уведомления
    push_url: str | None = None        # URL для перехода по клику на push
```

Логика:
1. Валидировать запрос (текст не пустой, каналы из допустимых значений)
2. Поставить задачу в Celery: `send_broadcast.delay(text, channels, filter, push_title, push_url)`
3. Вернуть `{"task_id": "...", "status": "queued"}`

**`GET /api/v1/admin/broadcast/status/{task_id}`** — прогресс отправки:

```json
{
  "task_id": "abc123",
  "status": "running",
  "sent": 847,
  "total": 1500,
  "failed": 3,
  "finished_at": null
}
```

#### Celery-задача `send_broadcast` (добавить в `nura_app/bot/tasks.py` или `core/tasks.py`)

```python
@celery_app.task(bind=True)
def send_broadcast(self, text, channels, filter_type, push_title, push_url):
    # 1. Получить список пользователей по фильтру из БД
    # 2. Обновлять прогресс в Redis: redis.set(f"broadcast:{task_id}", json)
    # 3. Telegram: цикл по telegram_id
    #    - asyncio.run(bot.send_message(tg_id, text, parse_mode="Markdown"))
    #    - Пауза 1/30 сек между сообщениями (лимит Telegram: 30 msg/s)
    #    - При ошибке 403 (бот заблокирован) — пропустить, считать в failed
    # 4. Web Push: цикл по пользователям с has_pwa_push=True
    #    - Вызвать web_push.send(endpoint, p256dh, auth, title, text, url)
    #    - При ошибке 410 (подписка устарела) — сбросить has_pwa_push=False в БД
```

**Важно по Telegram**: между сообщениями нужна задержка `time.sleep(1/25)` (~25 msg/s, с запасом от лимита 30/s). На 1000 пользователей — ~40 секунд.

#### Frontend — секция "Рассылка" в `index.html`

UI:
```
┌─────────────────────────────────────────────────┐
│  Текст сообщения                                │
│  ┌───────────────────────────────────────────┐  │
│  │                                           │  │
│  │  (textarea, 5 строк, поддержка Markdown)  │  │
│  │                                           │  │
│  └───────────────────────────────────────────┘  │
│                                                 │
│  Каналы:  [✓] Telegram    [✓] Web Push          │
│                                                 │
│  Push-заголовок: [________________]             │
│  Push-ссылка:    [________________]             │
│                                                 │
│  Получатели:  (●) Все  ( ) Premium  ( ) Free    │
│                                                 │
│  [  Отправить рассылку  ]                       │
│                                                 │
│  Статус: ████████░░░░░░  847 / 1500 отправлено  │
│  Ошибок: 3                                      │
└─────────────────────────────────────────────────┘
```

JS-логика:
```javascript
// Запуск рассылки
function startBroadcast() {
  var payload = {
    text: document.getElementById('broadcastText').value.trim(),
    channels: getCheckedChannels(),    // ['telegram', 'push']
    filter: getSelectedFilter(),       // 'all' | 'premium' | 'free'
    push_title: document.getElementById('pushTitle').value || null,
    push_url: document.getElementById('pushUrl').value || null
  };
  if (!payload.text) return showError('Текст не может быть пустым');
  if (!payload.channels.length) return showError('Выберите хотя бы один канал');

  apiFetch('/broadcast', { method: 'POST', body: JSON.stringify(payload) })
    .then(function(r) {
      broadcastTaskId = r.task_id;
      pollBroadcastStatus();
    });
}

// Опрос статуса каждые 2 секунды
var broadcastTaskId = null;
var broadcastPollTimer = null;

function pollBroadcastStatus() {
  if (!broadcastTaskId) return;
  apiFetch('/broadcast/status/' + broadcastTaskId)
    .then(function(r) {
      renderBroadcastProgress(r);
      if (r.status === 'running') {
        broadcastPollTimer = setTimeout(pollBroadcastStatus, 2000);
      } else {
        broadcastTaskId = null;
      }
    });
}

function renderBroadcastProgress(r) {
  var pct = r.total ? Math.round(r.sent / r.total * 100) : 0;
  document.getElementById('broadcastProgress').style.width = pct + '%';
  document.getElementById('broadcastSent').textContent = r.sent + ' / ' + r.total + ' отправлено';
  document.getElementById('broadcastFailed').textContent = 'Ошибок: ' + r.failed;
}
```

---

## Порядок выполнения

1. Прочитать `nura_app/core/config.py` → добавить `admin_token: str | None = None`
2. Прочитать `nura_app/api/routes/web.py` (для понимания паттерна) → создать `nura_app/api/routes/admin_api.py`
3. Прочитать `nura_app/api/main.py` → добавить `include_router(admin_api_router)`
4. Найти существующие Celery-задачи (поискать `celery` в `nura_app/`) → добавить задачу `send_broadcast`
5. Создать `frontend/admin/index.html`
6. Обновить `nura_app/nginx/nura-ai.ru.conf`
7. Обновить `deploy.sh`
8. Коммит + пуш в `main` → GitHub Actions запускает деплой (~1 мин)
9. **Вручную на VPS**: добавить `ADMIN_TOKEN` в `.env`, перезапустить backend (`systemctl restart nura` или аналог), перезагрузить nginx (`nginx -t && systemctl reload nginx`), **заменить `ADMIN_IP`** в nginx конфиге на реальный IP

---

## Проверка после деплоя

1. Открыть `nura-ai.ru/admin/` → форма ввода токена
2. Ввести неверный токен → сообщение об ошибке
3. Ввести верный токен → загружается Dashboard с реальными числами
4. Переключить каждую вкладку → данные подгружаются без ошибок
5. Вкладка Здоровье → все компоненты зелёные (или видна реальная проблема)
6. Подождать 30 сек → Dashboard обновился автоматически
7. Зайти с другого IP → nginx вернёт 403
8. Раздел Рассылка: написать тестовый текст, выбрать Telegram, фильтр "Premium", нажать отправить → прогресс-бар двигается, статус обновляется каждые 2 сек
