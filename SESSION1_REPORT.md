# SESSION 1 — Отчёт об исправлении деплоя и PWA-инфраструктуры

> Дата: 22.06.2026
> Скрипт: `deploy.sh`, `frontend/service-worker.js`, `frontend/offline.html`, `frontend/icons/*`, `frontend/Dockerfile`, `frontend/nginx.conf`, `nura_app/.env`, `nura_app/.env.example`
> Основание: `REPORT.md` (ревзия), раздел «P0 — немедленно»

---

## Что исправлено

### 1. Конфликт имён Service Worker (K4 из REPORT.md)

| Файл | Действие |
|------|----------|
| `frontend/sw.js` | Удалён |
| `frontend/service-worker.js` | Создан (переименован) — полная реализация |
| `frontend/Dockerfile:4` | `sw.js` → `service-worker.js` |
| `frontend/nginx.conf:23` | `/sw.js` → `= /service-worker.js` (точное совпадение) |

Все 6 HTML-страниц регистрируют `/service-worker.js` — без изменений.
Прод nginx (`nura_app/nginx/nura-ai.ru.conf:18`) уже отдаёт `/service-worker.js` — без изменений.

**Итог:** имя файла, путь регистрации в HTML и оба nginx-конфига (Docker + прод) теперь указывают на одно имя — `service-worker.js`.

### 2. Полноценный Service Worker (K2 из REPORT.md)

Файл `frontend/service-worker.js` реализован согласно `docs/pwa-spec.md:197-256`:

- `CACHE_NAME = 'nura-v2'` + `STATIC_ASSETS` массив с реальными ассетами проекта
- `install`: `cache.addAll(STATIC_ASSETS)` + `skipWaiting()`
- `activate`: чистка старых кэшей при смене `CACHE_NAME` + `clients.claim()`
- `fetch`: cache-first для статики, network-first для навигационных запросов с fallback на `/offline.html`, пропуск API/report/webhook
- `push`: обработка входящих push-уведомлений (JSON payload, `showNotification`)
- `notificationclick`: открытие/фокусировка окна при клике на уведомление

### 3. deploy.sh — копирование недостающих файлов (K1 из REPORT.md)

В `deploy.sh` добавлены строки копирования:

| Файл | Назначение | Пропуск в старом deploy.sh |
|------|-----------|---------------------------|
| `frontend/manifest.json` | PWA-манифест | ❌ не копировался |
| `frontend/service-worker.js` | Service Worker | ❌ не копировался (был `sw.js`, но и он не копировался) |
| `frontend/pwa-install.js` | Установка PWA | ❌ glob `frontend/pwa/*.js` не захватывал |
| `frontend/offline.html` | Офлайн-страница | ❌ файла не существовало |
| `frontend/icons/*` | Иконки PWA | ❌ директории не существовало |
| `favicon.ico`, `favicon.png` | Фавиконки | ❌ не копировались |
| `hero.png` | Изображение лендинга | ❌ не копировалось |
| `frontend/nura-hero.webp` | Оптимизированное hero | ❌ не копировалось |

### 4. BOT_USERNAME (M3 из REPORT.md)

- `nura_app/.env` — добавлена строка `BOT_USERNAME=ai_nura_bot`
- `nura_app/.env.example` — создан полный `.env.example` с переменной `BOT_USERNAME`
- `nura_app/core/config.py:50` — уже содержит `bot_username: str | None = None` (pydantic-settings авточитает `BOT_USERNAME` из `.env`)

---

## Что создано с плейсхолдер-данными — требует ручной замены

### Иконки PWA

Созданы три файла-заглушки в `frontend/icons/`:

| Файл | Размер | Статус |
|------|--------|--------|
| `icon-192.png` | 192×192 | Плейсхолдер (буква N на amber-фоне) |
| `icon-512.png` | 512×512 | Плейсхолдер (буква N на amber-фоне) |
| `apple-touch-icon.png` | 180×180 | Плейсхолдер (буква N на amber-фоне) |

**Перед реальным деплоем необходимо:**
1. Сгенерировать профессиональные иконки из логотипа NURA (звезда ✦ + слово NURA)
2. Добавить maskable-иконку с `purpose: "maskable"` в manifest.json (сейчас нет)
3. Проверить, что все иконки проходят Lighthouse PWA-audit

### offline.html

Создан `frontend/offline.html` — страница в стилистике проекта (mini.html/success.html):
- Сообщение «Кажется, ты офлайн»
- Кнопка «Повторить попытку» с `location.reload()`
- Поддерживает светлую/тёмную тему из `localStorage`

---

## Команды для проверки на VPS

```bash
# 1. Залить изменения на VPS
ssh -i C:\Users\Bayzel\.ssh\id_ed25519_astro root@45.144.178.118
cd /opt/nura && git pull origin main

# 2. Запустить обновлённый deploy.sh (скопирует ВСЕ файлы)
bash deploy.sh

# 3. Проверить, что файлы попали на диск
ls -la /var/www/nura-ai.ru/service-worker.js
ls -la /var/www/nura-ai.ru/manifest.json
ls -la /var/www/nura-ai.ru/pwa-install.js
ls -la /var/www/nura-ai.ru/offline.html
ls -la /var/www/nura-ai.ru/icons/
ls -la /var/www/nura-ai.ru/favicon.ico
ls -la /var/www/nura-ai.ru/hero.png

# 4. Проверить заголовки SW (должен отдаваться с Content-Type: application/javascript)
curl -I https://nura-ai.ru/service-worker.js

# 5. Проверить manifest.json
curl -I https://nura-ai.ru/manifest.json
# Должен вернуть Content-Type: application/manifest+json

# 6. Проверить offline.html
curl -I https://nura-ai.ru/offline.html

# 7. Проверить иконки
curl -I https://nura-ai.ru/icons/icon-192.png
curl -I https://nura-ai.ru/icons/icon-512.png
curl -I https://nura-ai.ru/icons/apple-touch-icon.png

# 8. В браузере: открыть https://nura-ai.ru/app/
# → DevTools → Application → Service Workers → должен быть зарегистрирован
# → DevTools → Application → Manifest → должен показывать иконки

# 9. Lighthouse PWA audit
# → Chrome DevTools → Lighthouse → только PWA → должно быть > 90%
```

---

## Критичные находки по ходу работы

### 🔴 `.env` закоммичен в репозиторий

`nura_app/.env` содержит плейсхолдеры (`change-me-...`), но файл присутствует в git-репозитории. На проде этот файл переопределяется реальными значениями, но сам факт нахождения `.env` в репозитории — проблема безопасности:

- Если кто-то случайно закоммитит реальные секреты — они попадут в историю git
- `.gitignore` содержит `.env`, но, видимо, файл был добавлен до gitignore
- **Рекомендация:** `git rm --cached nura_app/.env` и оставить только `.env.example`

### 🟡 Два index.html — дублирование

В репозитории два лендинга:
- `index.html` (корень) — 839 строк, последние правки
- `frontend/index.html` (frontend/) — 741 строка, устаревшая копия

`deploy.sh` копирует `index.html` (корень) на прод. `frontend/Dockerfile` копирует `frontend/index.html` в контейнер. Это источник расхождений при будущих правках лендинга.

**Рекомендация:** удалить `frontend/index.html`, если Docker-образ PWA не используется на проде, либо синхронизировать.

### 💭 `nura_app/alembic.ini` — пароль БД в репозитории (M5 из REPORT.md)

`nura_app/alembic.ini:4` содержит `sqlalchemy.url = postgresql://nura:change-me-db-password@localhost:5432/nura`. Пароль плейсхолдер, но при реальном деплое туда попадёт настоящий. Не исправлялось в этой сессии (выходит за рамки «деплой и PWA»).

---

## Файлы, изменённые в этой сессии

| Файл | Действие |
|------|----------|
| `deploy.sh` | Дополнен копированием всех PWA-файлов |
| `frontend/service-worker.js` | Создан (переименован из sw.js + полная реализация) |
| `frontend/sw.js` | Удалён |
| `frontend/offline.html` | Создан |
| `frontend/icons/icon-192.png` | Создан (плейсхолдер) |
| `frontend/icons/icon-512.png` | Создан (плейсхолдер) |
| `frontend/icons/apple-touch-icon.png` | Создан (плейсхолдер) |
| `frontend/Dockerfile` | `sw.js` → `service-worker.js` |
| `frontend/nginx.conf` | `/sw.js` → `= /service-worker.js` |
| `nura_app/.env` | Добавлен `BOT_USERNAME=ai_nura_bot` |
| `nura_app/.env.example` | Создан (полный шаблон) |

**Не тронуты:** бизнес-логика бэкенда (`nura_app/` кроме `.env`), бизнес-логика фронтенда (`chat.html`, `profile.html`, `tarot.html`), prod-nginx конфиг (`nura_app/nginx/nura-ai.ru.conf`).

---

*Конец отчёта первой сессии.*
