# NURA PWA — Техническая спецификация

> Версия: 1.0 · Дата: 09.06.2026 · Статус: Утверждён
>
> Документ описывает полную техническую реализацию PWA для `nura-ai.ru`.
> Читать вместе с `docs/platform-strategy.md` — там описана продуктовая логика.

---

## 1. Что такое PWA для NURA

PWA (`nura-ai.ru`) — это тот же сайт, но с тремя дополнениями:

1. **`manifest.json`** — браузер знает что это приложение, показывает предложение установить
2. **Service Worker** — обработчик push-уведомлений и кэш статики
3. **Продуктовые экраны** — страницы `/app/*` с мобильным UX (нижний таббар, нет адресной строки)

После установки сайт открывается как нативное приложение — без адресной строки, с иконкой на главном экране, с уведомлениями.

**Важно:** PWA — не отдельный проект и не отдельный домен. Это тот же `nura-ai.ru`, надстройка поверх существующего FastAPI бэкенда.

---

## 2. Текущее состояние (что уже есть)

| Компонент | Статус | Где |
|-----------|--------|-----|
| HTTPS + SSL | ✅ Готово | nginx + Certbot |
| Лендинг `index.html` | ✅ Готово | `/var/www/nura-ai.ru/` |
| Мини-анализ `mini.html` | ✅ Готово | `/opt/nura/mini.html` |
| Страница успеха `success.html` | ✅ Готово | `/opt/nura/success.html` |
| Страница отчёта `/report/{token}` | ✅ Готово | FastAPI |
| `manifest.json` | ✅ Готово (сессия 19) | — |
| Service Worker | ✅ Готово (сессия 19) | — |
| iOS meta-теги | ✅ Готово (сессия 19) | — |
| Иконки PWA | ✅ Готово (сессия 19) | — |
| `offline.html` | ✅ Готово (сессия 19) | — |
| Install UI | ❌ Нет | — |
| Web Push backend | ❌ Нет | — |
| PWA экраны `/app/*` | ❌ Нет | — |

---

## 3. Файловая структура

```
/var/www/nura-ai.ru/           ← статика (nginx)
├── index.html                  ← лендинг
├── mini.html                   ← мини-анализ
├── success.html                ← после оплаты
├── manifest.json               ← 🆕 PWA манифест
├── service-worker.js           ← 🆕 Service Worker
├── offline.html                ← 🆕 fallback при оффлайне
└── icons/                      ← 🆕 иконки PWA
    ├── icon-192.png
    ├── icon-512.png
    ├── icon-192-maskable.png
    ├── icon-512-maskable.png
    └── apple-touch-icon.png    ← 180×180 для iOS

/opt/nura/nura_app/
└── api/routes/
    └── push.py                 ← 🆕 Web Push endpoints
```

---

## 4. manifest.json

Файл кладётся в `/var/www/nura-ai.ru/manifest.json`.

```json
{
  "name": "NURA — Матрица Судьбы",
  "short_name": "NURA",
  "description": "AI-проводник в самопознание через Матрицу Судьбы и Таро",
  "start_url": "/app",
  "scope": "/",
  "display": "standalone",
  "orientation": "portrait",
  "background_color": "#0A0E0C",
  "theme_color": "#0A0E0C",
  "icons": [
    {
      "src": "/icons/icon-192.png",
      "sizes": "192x192",
      "type": "image/png",
      "purpose": "any"
    },
    {
      "src": "/icons/icon-512.png",
      "sizes": "512x512",
      "type": "image/png",
      "purpose": "any"
    },
    {
      "src": "/icons/icon-192-maskable.png",
      "sizes": "192x192",
      "type": "image/png",
      "purpose": "maskable"
    },
    {
      "src": "/icons/icon-512-maskable.png",
      "sizes": "512x512",
      "type": "image/png",
      "purpose": "maskable"
    },
    {
      "src": "/icons/apple-touch-icon.png",
      "sizes": "180x180",
      "type": "image/png",
      "purpose": "any"
    }
  ],
  "categories": ["lifestyle", "health"],
  "lang": "ru"
}
```

**Требования к иконкам:**
- Фон: `#0A0E0C` (--bg) — основной тёмный фон бренда
- Акцент: `#C9A55C` (--m-accent) — золото матрицы, основной цвет символа ✦
- Вторичный фон круга: `#111613` (--bg-soft)
- Текст NURA: `#C9A55C` (золото, не белый)
- `icon-192.png` и `icon-512.png` — символ ✦ + надпись NURA на тёмном фоне
- `maskable` варианты — с отступом 12% со всех сторон (safe zone для Android)
- `apple-touch-icon.png` — 180×180, для тега `<link rel="apple-touch-icon">`

**Палитра CSS-переменных (из index.html):**
| Переменная | Значение | Назначение |
|---|---|---|
| `--bg` | `#0A0E0C` | Основной фон |
| `--bg-soft` | `#111613` | Вторичный фон |
| `--ink` | `#F2EFE7` | Текст (тёплый белый) |
| `--m-accent` | `#C9A55C` | Золото матрицы — основной акцент |
| `--m-leaf` | `#6BA37A` | Изумрудный |
| `--t-accent` | `#D8B36A` | Золото таро |
| `--t-violet` | `#7E7AC8` | Фиолетовый таро |

---

## 5. iOS meta-теги

Добавить в `<head>` всех страниц (`index.html`, `mini.html`, `success.html`, `/report/` шаблон):

```html
<!-- PWA манифест -->
<link rel="manifest" href="/manifest.json">

<!-- iOS PWA -->
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="NURA">
<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">

<!-- Цвет темы для Android Chrome -->
<meta name="theme-color" content="#0A0E0C">

<!-- Viewport с поддержкой safe area -->
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
```

---

## 6. Service Worker

Файл `/var/www/nura-ai.ru/service-worker.js`.

### 6.1 Регистрация (добавить в каждую HTML-страницу)

```html
<script>
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/service-worker.js')
        .then(reg => console.log('SW registered:', reg.scope))
        .catch(err => console.log('SW error:', err));
    });
  }
</script>
```

### 6.2 Содержимое service-worker.js

```javascript
const CACHE_NAME = 'nura-v1';
const STATIC_ASSETS = [
  '/',
  '/mini',
  '/offline.html',
  '/icons/icon-192.png',
];

// Установка — кэшируем статику
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// Активация — удаляем старые кэши
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch — Network First для API, Cache First для статики
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API запросы — всегда сеть
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  // Отчёты — всегда сеть (персональные данные)
  if (url.pathname.startsWith('/report/')) {
    return;
  }

  // Статика — кэш с fallback на сеть
  event.respondWith(
    caches.match(event.request).then(cached => {
      return cached || fetch(event.request).catch(() =>
        caches.match('/offline.html')
      );
    })
  );
});

// ════════════════════════════════════════
// WEB PUSH — обработка входящих пушей
// ════════════════════════════════════════

self.addEventListener('push', (event) => {
  if (!event.data) return;

  const data = event.data.json();

  const options = {
    body: data.body || 'Открой NURA',
    icon: '/icons/icon-192.png',
    // badge не указываем — iOS игнорирует, Android отображает
    vibrate: [100, 50, 100],
    data: {
      url: data.url || '/app'
    },
    // Группировка уведомлений одного типа
    tag: data.tag || 'nura-default',
    renotify: false
  };

  event.waitUntil(
    self.registration.showNotification(data.title || 'NURA', options)
  );
});

// Клик по уведомлению — открываем нужный экран
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const targetUrl = event.notification.data?.url || '/app';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clientList => {
      // Если приложение уже открыто — переходим в него
      for (const client of clientList) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      // Иначе открываем новое окно
      return clients.openWindow(targetUrl);
    })
  );
});
```

---

## 7. Web Push Backend

### 7.1 VAPID ключи

Генерируются один раз, хранятся в `.env`:

```bash
# Генерация (один раз)
pip install pywebpush
python -c "from pywebpush import webpush; print(webpush.generate_vapid_keys())"
```

В `.env`:
```
VAPID_PRIVATE_KEY=<generated_private_key>
VAPID_PUBLIC_KEY=<generated_public_key>
VAPID_CLAIMS_EMAIL=admin@nura-ai.ru
```

### 7.2 Модель БД

Alembic-миграция — добавить в таблицу `users`:

```sql
ALTER TABLE users ADD COLUMN has_pwa_push BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN push_endpoint TEXT;
ALTER TABLE users ADD COLUMN push_p256dh TEXT;
ALTER TABLE users ADD COLUMN push_auth TEXT;
```

### 7.3 Новый файл `api/routes/push.py`

```python
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository
from api.deps import limiter

router = APIRouter(prefix="/api/v1/push")


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict  # {p256dh: str, auth: str}
    session_id: str | None = None  # для веб-пользователей
    telegram_id: int | None = None  # для TG-пользователей


class PushUnsubscribe(BaseModel):
    endpoint: str


@router.post("/subscribe")
@limiter.limit("10/minute")
async def subscribe(request: Request, body: PushSubscription):
    """Сохранить push-подписку пользователя."""
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)

    # Найти пользователя по session_id или telegram_id
    user = None
    if body.session_id:
        user = await user_repo.get_by_web_session_id(body.session_id)
    elif body.telegram_id:
        user = await user_repo.get_by_telegram_id(body.telegram_id)

    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await user_repo.update_push_subscription(
        user_id=user.id,
        endpoint=body.endpoint,
        p256dh=body.keys.get("p256dh"),
        auth=body.keys.get("auth"),
        has_pwa_push=True
    )
    return {"ok": True}


@router.post("/unsubscribe")
async def unsubscribe(request: Request, body: PushUnsubscribe):
    """Удалить push-подписку."""
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    await user_repo.clear_push_subscription_by_endpoint(body.endpoint)
    return {"ok": True}


@router.get("/vapid-public-key")
async def get_vapid_public_key():
    """Отдать публичный VAPID ключ клиенту."""
    from core.config import settings
    return {"public_key": settings.vapid_public_key}
```

### 7.4 Отправка Web Push (utility)

Новый файл `core/services/web_push.py`:

```python
from pywebpush import webpush, WebPushException
from core.config import settings
import json
import logging

logger = logging.getLogger(__name__)


async def send_web_push(
    endpoint: str,
    p256dh: str,
    auth: str,
    title: str,
    body: str,
    url: str = "/app",
    tag: str = "nura-default"
) -> bool:
    """
    Отправить Web Push уведомление.
    Возвращает True при успехе, False при ошибке (подписка устарела → нужно сбросить has_pwa_push).
    """
    try:
        webpush(
            subscription_info={
                "endpoint": endpoint,
                "keys": {"p256dh": p256dh, "auth": auth}
            },
            data=json.dumps({
                "title": title,
                "body": body,
                "url": url,
                "tag": tag
            }),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={
                "sub": f"mailto:{settings.vapid_claims_email}"
            }
        )
        return True
    except WebPushException as e:
        # 410 Gone — подписка недействительна
        if e.response and e.response.status_code == 410:
            logger.info("Push subscription expired: %s", endpoint[:50])
            return False
        logger.error("Push send error: %s", e)
        return False
```

### 7.5 Обновление Celery-задачи send_daily_card

В `core/tasks.py` обновить `send_daily_card`:

```python
async def _send_to_user(user, card_text: str, card_title: str):
    """Отправить карту дня пользователю через правильный канал."""
    if user.has_pwa_push and user.push_endpoint:
        # Web Push — через APNs/FCM
        success = await send_web_push(
            endpoint=user.push_endpoint,
            p256dh=user.push_p256dh,
            auth=user.push_auth,
            title=card_title,
            body=card_text[:120] + "...",  # краткий preview
            url="/app/tarot",
            tag="daily-card"
        )
        if not success:
            # Подписка устарела — сбросить флаг, fallback в Telegram
            await user_repo.update_push_subscription(
                user_id=user.id, has_pwa_push=False,
                endpoint=None, p256dh=None, auth=None
            )
            if user.telegram_id:
                await _send_message(user.telegram_id, card_text)
    elif user.telegram_id:
        # Telegram fallback
        await _send_message(user.telegram_id, card_text)
```

---

## 8. Install UI

### 8.1 Android — auto-prompt

Браузер сам показывает баннер "Добавить на главный экран" если:
- Есть `manifest.json` с корректными полями
- Зарегистрирован Service Worker с fetch handler
- Сайт открывался минимум 2 раза с интервалом 5+ минут

Можно перехватить и показать в нужный момент (после покупки):

```javascript
let deferredPrompt;

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
  // Показываем свою кнопку установки
  showInstallButton();
});

function triggerInstall() {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  deferredPrompt.userChoice.then(choice => {
    if (choice.outcome === 'accepted') {
      trackEvent('pwa_installed', { platform: 'android' });
    }
    deferredPrompt = null;
    hideInstallButton();
  });
}
```

**Правильный момент показа** — после получения отчёта, не при первом входе:

```javascript
// После успешной оплаты / открытия отчёта
if (deferredPrompt && !localStorage.getItem('install_dismissed')) {
  showInstallBanner();
}
```

### 8.2 iOS — инструкция

На iOS `beforeinstallprompt` недоступен. Нужно показать модальное окно с инструкцией.

**Когда показывать:**
```javascript
function isIOS() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
}

function isPWAInstalled() {
  return window.matchMedia('(display-mode: standalone)').matches
    || window.navigator.standalone === true;
}

function getIOSVersion() {
  const match = navigator.userAgent.match(/OS (\d+)_(\d+)/);
  return match ? parseInt(match[1]) : 0;
}

// Показывать iOS-инструкцию если:
// - iPhone/iPad
// - Не установлена как PWA
// - Не закрыл ранее
// - После покупки (не при первом входе)
function shouldShowIOSInstall() {
  return isIOS()
    && !isPWAInstalled()
    && !localStorage.getItem('ios_install_dismissed')
    && getIOSVersion() >= 16; // Web Push только на iOS 16.4+
}
```

**HTML модального окна** (добавить на страницу отчёта и success.html):

```html
<div id="ios-install-modal" class="install-modal" style="display:none">
  <div class="install-modal-content">
    <button class="install-modal-close" onclick="dismissIOSInstall()">✕</button>
    <div class="install-modal-icon">
      <img src="/icons/icon-192.png" alt="NURA" width="64" height="64">
    </div>
    <h3>Добавь NURA на главный экран</h3>
    <p>Получай карту дня прямо на экране — без открытия Telegram и браузера</p>
    <div class="install-steps">
      <div class="install-step">
        <span class="step-num">1</span>
        <span>Нажми <strong>«Поделиться»</strong> внизу Safari</span>
        <!-- иконка стрелки вверх из квадрата -->
      </div>
      <div class="install-step">
        <span class="step-num">2</span>
        <span>Выбери <strong>«На экран Домой»</strong></span>
      </div>
      <div class="install-step">
        <span class="step-num">3</span>
        <span>Нажми <strong>«Добавить»</strong></span>
      </div>
    </div>
    <!-- GIF-анимация с реальным iPhone — показывает шаги -->
    <img src="/icons/ios-install-guide.gif" alt="Инструкция установки" class="install-guide-gif">
    <button class="install-modal-dismiss" onclick="dismissIOSInstall()">
      Может потом
    </button>
  </div>
</div>

<script>
function showIOSInstall() {
  document.getElementById('ios-install-modal').style.display = 'flex';
}
function dismissIOSInstall() {
  document.getElementById('ios-install-modal').style.display = 'none';
  localStorage.setItem('ios_install_dismissed', '1');
}
// Показать после небольшой задержки чтобы пользователь успел осмотреться
if (shouldShowIOSInstall()) {
  setTimeout(showIOSInstall, 3000);
}
</script>
```

### 8.3 Момент показа install UI

| Страница | Когда показывать |
|----------|-----------------|
| `success.html` | Через 3 сек после загрузки (пользователь только что заплатил) |
| `/report/{token}` | Через 30 сек (пользователь начал читать) |
| `/app/tarot` | После первого расклада |
| Остальные | Не показывать |

---

## 9. Web Share API

Используется для кнопки "Поделиться" в двух местах:

**После расклада совместимости** — приоритет на Telegram:
```javascript
async function shareCompatibility(text, refUrl) {
  const tgUrl = `tg://msg_url?url=${encodeURIComponent(refUrl)}&text=${encodeURIComponent(text)}`;

  // Попытка открыть Telegram напрямую
  window.location.href = tgUrl;

  // Fallback через Web Share API через 500ms если TG не открылся
  setTimeout(() => {
    if (navigator.share) {
      navigator.share({
        title: 'NURA — Матрица совместимости',
        text: text,
        url: refUrl
      });
    } else {
      // Копировать в буфер
      navigator.clipboard.writeText(refUrl);
      showToast('Ссылка скопирована');
    }
  }, 500);
}
```

**Поделиться отчётом** — нативный диалог:
```javascript
function shareReport(token) {
  const reportUrl = `https://nura-ai.ru/report/${token}`;
  if (navigator.share) {
    navigator.share({
      title: 'Моя Матрица Судьбы — NURA',
      text: 'Посмотри мой AI-разбор по Матрице Судьбы',
      url: reportUrl
    });
  } else {
    navigator.clipboard.writeText(reportUrl);
    showToast('Ссылка скопирована');
  }
}
```

---

## 10. Продуктовые экраны PWA (`/app/*`)

### 10.1 Структура маршрутов

```
/app          → главный экран (матрица + приветствие)
/app/tarot    → раздел таро (карта дня + расклады)
/app/chat     → чат с NURA
/app/profile  → профиль (отчёты, подписка, уведомления)
```

### 10.2 Навигация — нижний таббар

Присутствует на всех `/app/*` страницах. Скрыт в браузерном режиме, виден в standalone.

```html
<nav class="app-tabbar">
  <a href="/app" class="tab-item" data-tab="home">
    <span class="tab-icon">◈</span>
    <span class="tab-label">Матрица</span>
  </a>
  <a href="/app/tarot" class="tab-item" data-tab="tarot">
    <span class="tab-icon">🌒</span>
    <span class="tab-label">Таро</span>
  </a>
  <a href="/app/chat" class="tab-item" data-tab="chat">
    <span class="tab-icon">💬</span>
    <span class="tab-label">Чат</span>
  </a>
  <a href="/app/profile" class="tab-item" data-tab="profile">
    <span class="tab-icon">👤</span>
    <span class="tab-label">Профиль</span>
  </a>
</nav>
```

CSS с учётом safe area (iPhone X+):
```css
.app-tabbar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: calc(56px + env(safe-area-inset-bottom));
  padding-bottom: env(safe-area-inset-bottom);
  background: #0E2419;
  border-top: 1px solid rgba(151, 197, 161, 0.15);
  display: flex;
  align-items: flex-start;
  padding-top: 8px;
  z-index: 100;
}
```

### 10.3 Экран /app (главный)

Показывает если пользователь авторизован:
- Имя пользователя + архетип
- Кнопка "Открыть матрицу" → `/report/{token}`
- Блок карты дня (сегодняшняя карта)
- CTA установить PWA (если не установлена)

Если не авторизован → редирект на `/mini`.

### 10.4 Экран /app/tarot

- Сегодняшняя карта дня (бесплатно)
- Сетка из 6 раскладов (с замком для free)
- Кнопка "Оформить подписку 390₽/мес"

### 10.5 Экран /app/chat

- История диалога с NURA
- Поле ввода
- Лимит для free (5 сообщений) с CTA на подписку

### 10.6 Экран /app/profile

Секции:
- Мои отчёты (список с кнопками открыть/PDF)
- Подписка (статус, дата продления, отмена)
- Уведомления:
  ```
  Как получать карту дня:
  ● Web Push — прямо на экран  [рекомендуется]
  ○ Telegram — в мессенджере
  ```
- Подключить Telegram (кнопка запускает link-токен механику)

---

## 11. Обновления nginx.conf

Добавить в `/etc/nginx/sites-enabled/nura-ai.ru.conf`:

```nginx
# PWA manifest и service worker — без кэширования
location = /manifest.json {
    root /var/www/nura-ai.ru;
    add_header Cache-Control "no-cache" always;
    add_header Content-Type "application/manifest+json" always;
}

location = /service-worker.js {
    root /var/www/nura-ai.ru;
    add_header Cache-Control "no-cache" always;
    add_header Service-Worker-Allowed "/" always;
}

# PWA app routes → FastAPI (или статические HTML-файлы)
location /app {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# Push API
# Уже покрыт существующим location /api/ → proxy FastAPI
```

---

## 12. Сегменты iOS и поддержка

| iOS версия | PWA устанавливается | Web Push | Что делать |
|------------|--------------------|---------| -----------|
| 16.4+ | ✅ | ✅ (только в standalone) | Полный функционал |
| 16.0–16.3 | ✅ | ❌ | Установка без пуша, Telegram fallback |
| 15.x | ✅ (без пуша) | ❌ | Telegram fallback |
| < 15 | ⚠️ Частично | ❌ | Telegram fallback |

**Определение сегмента в JS:**

```javascript
function getNotificationStrategy() {
  if (!isIOS()) return 'web_push';                            // Android/Desktop

  const ver = getIOSVersion();
  if (ver >= 16 && !isPWAInstalled()) return 'install_first'; // нужна установка
  if (ver >= 16 && isPWAInstalled()) return 'web_push';       // полный функционал
  return 'telegram_fallback';                                  // iOS < 16
}
```

---

## 13. Чеклист разработчика

### Перед деплоем

- [x] `manifest.json` — все поля заполнены, иконки доступны по URL
- [x] Иконки созданы: 192, 512 (any + maskable), apple-touch-icon 180
- [x] `service-worker.js` — регистрируется без ошибок в DevTools
- [x] iOS meta-теги добавлены на все страницы
- [x] `nginx.conf` обновлён (manifest, SW, /app маршруты)
- [ ] VAPID ключи сгенерированы, добавлены в `.env`
- [x] Alembic-миграция применена: `has_pwa_push`, `push_endpoint`, `push_p256dh`, `push_auth`
- [ ] `api/routes/push.py` подключён в `api/main.py`
- [ ] `send_daily_card` обновлён с дедупликацией

### Тестирование

- [ ] Android Chrome: предложение установки появляется
- [ ] Android Chrome: Web Push доставляется
- [ ] iOS 16.4+ Safari: инструкция по установке показывается
- [ ] iOS 16.4+ (установлена): Web Push доставляется
- [ ] iOS 15: Telegram fallback работает
- [ ] Lighthouse PWA аудит: все критерии пройдены (installable, SW, HTTPS)
- [ ] Оффлайн: `offline.html` показывается при отсутствии сети
- [ ] Карта дня НЕ дублируется (Web Push + Telegram одновременно)

### Lighthouse цели

| Метрика | Цель |
|---------|------|
| Performance | ≥ 85 |
| PWA (installable) | ✅ |
| LCP | < 2.5s |
| CLS | < 0.1 |

---

## 14. Оценка трудозатрат

| Задача | Часов | Приоритет |
|--------|-------|-----------|
| manifest.json + иконки | 2 | 🔴 P0 |
| iOS meta-теги на всех страницах | 1 | 🔴 P0 |
| service-worker.js (push + кэш) | 4 | 🔴 P0 |
| Web Push backend (`api/routes/push.py`) | 4 | 🔴 P0 |
| `core/services/web_push.py` | 2 | 🔴 P0 |
| Alembic-миграция новых полей | 1 | 🔴 P0 |
| Обновление `send_daily_card` (дедупликация) | 2 | 🔴 P0 |
| nginx.conf обновление | 1 | 🔴 P0 |
| Install UI: Android (auto-prompt) | 2 | 🔴 P0 |
| Install UI: iOS (модальное окно + GIF) | 3 | 🔴 P0 |
| **Итого P0** | **22** | |
| Экраны `/app/*` (главный, таро, чат, профиль) | 40 | 🟡 P1 |
| Web Share API (совместимость + отчёт) | 3 | 🟡 P1 |
| Link-токен связка PWA ↔ Telegram | 4 | 🟡 P1 |
| Подписка 390₽ через веб | 4 | 🟡 P1 |
| **Итого P1** | **51** | |
| **Итого полная PWA** | **~73** | |

---

*Документ утверждён: 09.06.2026.
Следующий в плане обновления документации: `bot-spec.md` (обновление роли бота).*
