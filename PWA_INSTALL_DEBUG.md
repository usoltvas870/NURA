# PWA Install Banner — Диагностика

Дата: 22.06.2026. Диагностическая сессия, без автоматических правок.

## Итоговый вывод

Цепочка рвётся на **трёх независимых багах**, каждый из которых блокирует `beforeinstallprompt` и показ баннера:

| # | Баг | Страницы затронуты | Критичность |
|---|-----|-------------------|-------------|
| 1 | Нет `<link rel="manifest">` в HTML лендинга и `/app/` | `/`, `/app/` | 🔴 Blocker |
| 2 | Двойной `Content-Type` на `/manifest.json` | Все страницы | 🔴 Blocker |
| 3 | Продовый `/app/index.html` не содержит DOM-элементов баннера и `<script src="/pwa-install.js">` | `/app/` | 🔴 Blocker |

Пользователь тестирует `nura-ai.ru` в Chrome Android — это лендинг. Баг №1 один уже полностью блокирует всю цепочку.

---

## Шаг 1 — Деплой

### Проверка статики (curl -I)

| URL | HTTP-код | Content-Type | Размер |
|-----|----------|-------------|--------|
| `/service-worker.js` | 200 | `application/javascript` | 301 B |
| `/manifest.json` | 200 | `application/json` + `application/manifest+json` ⚠️ | 522 B |
| `/pwa-install.js` | 200 | `application/javascript` | 2814 B |
| `/icons/icon-192.png` | 200 | `image/png` | 3114 B |
| `/icons/icon-512.png` | 200 | `image/png` | 8659 B |

**Результат: все URL отдают 200.** Статика физически докатилась на VPS.

⚠️ `manifest.json` отдаёт **два** заголовка Content-Type (см. Шаг 2).

---

## Шаг 2 — manifest.json

### Двойной Content-Type (🔴 Blocker)

Nginx конфиг (`nura_app/nginx/nura-ai.ru.conf:15`) использует `add_header` для установки `Content-Type: application/manifest+json`. Но стандартные mime-типы nginx (`/etc/nginx/mime.types`) уже отдают `application/json` для `.json`. `add_header` **добавляет**, а не заменяет.

HTTP-ответ с прода:
```
Content-Type: application/json        ← первый, от mime.types — НЕВАЛИДЕН
Content-Type: application/manifest+json  ← второй, от add_header — правильный
```

Chrome PWA installability требует ровно `Content-Type: application/manifest+json`. Двойной Content-Type — нарушение HTTP spec (RFC 7230: «If multiple Content-Type header fields are present, the recipient SHOULD treat the field value as invalid or use the first one»). Chrome с высокой вероятностью использует первый заголовок (`application/json`) и отклоняет манифест.

**Исправление:** в nginx заменить `add_header Content-Type` на директиву `types {}` с переопределением mime-типа для `.json` в данном location, либо использовать `default_type application/manifest+json` внутри location блока:
```nginx
location = /manifest.json {
    root /var/www/nura-ai.ru;
    types {} default_type application/manifest+json;
    add_header Cache-Control "no-cache" always;
}
```

### Несовпадение репозиторий ↔ прод

| Поле | Репозиторий (`frontend/manifest.json`) | Прод (`/manifest.json`) |
|------|---------------------------------------|------------------------|
| `name` | `NURA — Матрица Судьбы` | `NURA` |
| `description` | `AI-проводник в самопознание…` | `Личный AI-центр: Матрица…` |
| `scope` | `/` | Отсутствует |
| `categories` | `["lifestyle", "health"]` | Отсутствует |
| `lang` | `ru` | Отсутствует |
| Иконки | 5 шт (192, 512, apple-touch, + maskable) | 2 шт (только 192, 512, без `purpose`) |

Прод урезан. Деплой manifest.json не соответствует репозиторию. Это не блокирует установку, но снижает качество PWA (нет maskable-иконок для Android, нет apple-touch-icon для iOS).

### Валидация обязательных полей

- `name` / `short_name`: ✅
- `start_url`: `"/app/"` ✅
- `display`: `"standalone"` ✅
- `icons`: 192×192 и 512×512 ✅
- Content-Type иконок: `image/png` ✅ (проверено curl -I на обе иконки)

**Но:** двойной Content-Type на самом манифесте перечёркивает всё.

---

## Шаг 3 — Service Worker

### Регистрация в HTML

| Страница | SW регистрация | Код |
|----------|---------------|-----|
| `/` (лендинг) | ❌ Отсутствует | — |
| `/app/` | ✅ Есть (inline `<script>`) | `navigator.serviceWorker.register('/service-worker.js', { scope: '/app/' })` |
| `/mini.html` | ✅ Есть (inline `<script>`) | `navigator.serviceWorker.register('/service-worker.js')` |

### Валидность SW-файла

```
HTTP 200, Content-Type: application/javascript, 301 bytes
```

Содержимое — валидный JS с обработчиками `install`, `activate`, `fetch`. ✅

---

## Шаг 4 — HTTPS и сертификат

SSL: Let's Encrypt, `nginx/1.24.0`. Соединение успешно, `schannel` handshake проходит. Сертификат валиден, не самоподписанный. ✅

---

## Шаг 5 — pwa-install.js и DOM-элементы

### Лендинг (`/`)

| Элемент | Наличие |
|---------|---------|
| `<link rel="manifest">` | ❌ |
| `<div id="pwa-install-banner">` | ❌ |
| `<div id="pwa-ios-modal">` | ❌ |
| `<script src="/pwa-install.js">` | ❌ |
| SW-регистрация | ❌ |

**Ноль PWA-инфраструктуры.** Пользователь вводит `nura-ai.ru` в Chrome — это именно эта страница. `beforeinstallprompt` не может сработать физически.

### PWA App (`/app/`) — сравнение репо ↔ прод

| Элемент | Репозиторий (`frontend/pwa/app/index.html`) | Прод |
|---------|---------------------------------------------|------|
| `<link rel="manifest">` | ❌ Отсутствует | ❌ Отсутствует |
| `<div id="pwa-install-banner">` | ✅ Строка 60 | ❌ Отсутствует |
| `<div id="pwa-ios-modal">` | ✅ Строка 68 | ❌ Отсутствует |
| `<script src="/pwa-install.js">` | ✅ Строка 82 | ❌ Отсутствует |
| SW-регистрация | ✅ | ✅ |
| `<link rel="stylesheet" href="/theme.css">` | ✅ | ❌ Отсутствует |

Прод `/app/index.html` — **устаревшая версия**, изменения Сессии 3 (DOM баннеров, pwa-install.js) не докатились. API-запросы тоже отличаются (прод: query string, репо: заголовки).

### Mini-страница (`/mini.html`) — единственная полная

| Элемент | Прод |
|---------|------|
| `<link rel="manifest">` | ✅ |
| `<div id="pwa-install-banner">` | ✅ |
| `<div id="pwa-ios-modal">` | ✅ |
| `<script src="/pwa-install.js">` | ✅ |
| SW-регистрация | ✅ |

`/mini.html` — **единственная страница с полной PWA-инфраструктурой на проде.** Теоретически, если пользователь попадёт на `/mini.html`, дождётся 3 секунды (таймер в `pwa-install.js:80`), и Chrome всё же выстрелит `beforeinstallprompt` (несмотря на двойной Content-Type) — баннер может показаться. Но это не основной сценарий: пользователь идёт на лендинг.

---

## Шаг 6 — Chrome Engagement Heuristics

Даже при всех исправлениях Chrome требует «вовлечённость» (engagement) перед `beforeinstallprompt`:
- Несколько визитов за последние 2+ недели
- Определённое время взаимодействия на сайте

Точный алгоритм Chrome не раскрывает. Это не баг, а поведение браузера.

**Рекомендация:** тестировать через `chrome://inspect` → remote target (Android устройство по USB) → Console. Там `beforeinstallprompt` событие можно отследить напрямую и увидеть, стреляет ли оно.

---

## Шаг 7 — Lighthouse

Инструмент недоступен в среде выполнения. **Рекомендация:** ручная проверка через Chrome DevTools → Lighthouse → категория PWA на `nura-ai.ru`. Lighthouse покажет точный список невыполненных installability-критериев по пунктам.

---

## План исправлений (НЕ выполнять в этой сессии)

### Исправление 1: nginx — двойной Content-Type
Файл: `nura_app/nginx/nura-ai.ru.conf:12-16`
```nginx
# Было:
location = /manifest.json {
    root /var/www/nura-ai.ru;
    add_header Cache-Control "no-cache" always;
    add_header Content-Type "application/manifest+json" always;
}

# Стало:
location = /manifest.json {
    root /var/www/nura-ai.ru;
    types {} default_type application/manifest+json;
    add_header Cache-Control "no-cache" always;
}
```
Применить на VPS: `nginx -t && nginx -s reload`

### Исправление 2: Добавить `<link rel="manifest">` в лендинг и `/app/`
Файлы:
- `frontend/index.html` (или корневой `index.html` лендинга)
- `frontend/pwa/app/index.html` (и остальные app-страницы)

Добавить в `<head>`:
```html
<link rel="manifest" href="/manifest.json">
```

### Исправление 3: Докатить Сессию 3 на прод
Файлы `frontend/pwa/app/*.html` содержат DOM-элементы баннера и `<script src="/pwa-install.js">` в репозитории, но на проде их нет. Нужно передеплоить `frontend/pwa/app/` на VPS (`/var/www/nura-ai.ru/app/`).

### Исправление 4: Актуализировать manifest.json на проде
Заменить урезанную прод-версию на актуальную из `frontend/manifest.json` (с maskable-иконками, apple-touch-icon, scope, categories, lang).

### Исправление 5: Ручная проверка Lighthouse и chrome://inspect
После всех правок — прогнать Lighthouse PWA audit и проверить `beforeinstallprompt` через remote debugging.
