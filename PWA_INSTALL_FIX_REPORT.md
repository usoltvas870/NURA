# PWA INSTALL FIX — Отчёт об исправлении трёх блокеров

> Дата: 22.06.2026
> Основание: `PWA_INSTALL_DEBUG.md` (диагностика), три блокера install-баннера
> Правит: код в репозитории и nginx-конфиг. Не выполняет деплой на VPS.

---

## 🔍 Природа бага №1: `<link rel="manifest">` отсутствует

**Вывод: это кодовый баг, упущенный во всех сессиях 1–9.**

`grep -r 'rel="manifest"'` по репозиторию показал:

| Файл | Статус до исправления |
|------|----------------------|
| `index.html` (лендинг) | ❌ Отсутствовал |
| `frontend/pwa/app/index.html` | ❌ Отсутствовал |
| `frontend/pwa/app/profile.html` | ❌ Отсутствовал |
| `frontend/pwa/app/tarot.html` | ❌ Отсутствовал |
| `frontend/pwa/app/chat.html` | ❌ Отсутствовал |
| `mini.html` | ✅ Был |
| `success.html` | ✅ Был |

Тег **никогда не был добавлен** в эти 5 файлов. Это не баг деплоя — прод честно отдавал то, что лежит в репозитории. Все прошлые сессии (1–9) пропустили этот дефект. `docs/launch-checklist.md` ошибочно помечал пункт «`<link rel="manifest">` на всех страницах» как ✅.

---

## ✅ Что исправлено в коде

### Исправление 1: Добавлен `<link rel="manifest" href="/manifest.json">` в 5 файлов

| Файл | Позиция |
|------|---------|
| `index.html:6` | После `<meta viewport>`, перед theme-скриптом |
| `frontend/pwa/app/index.html:4` | После `<meta viewport>`, перед theme-скриптом |
| `frontend/pwa/app/profile.html:4` | Аналогично |
| `frontend/pwa/app/tarot.html:4` | Аналогично |
| `frontend/pwa/app/chat.html:4` | Аналогично |

`mini.html:3` и `success.html:3` — уже содержали тег, без изменений.

### Исправление 2: nginx — двойной Content-Type на `/manifest.json`

Файл: `nura_app/nginx/nura-ai.ru.conf:12-16`

**Было:**
```nginx
location = /manifest.json {
    root /var/www/nura-ai.ru;
    add_header Cache-Control "no-cache" always;
    add_header Content-Type "application/manifest+json" always;
}
```

**Стало:**
```nginx
location = /manifest.json {
    root /var/www/nura-ai.ru;
    types {} default_type application/manifest+json;
    add_header Cache-Control "no-cache" always;
}
```

`types {}` отключает стандартную mime-таблицу nginx для этого location, а `default_type application/manifest+json` задаёт единственный корректный Content-Type. Это устраняет двойной заголовок (`application/json` + `application/manifest+json`), который нарушал HTTP spec и блокировал Chrome PWA installability.

**Проверка `frontend/nginx.conf`:** файл отсутствует — удаление из Сессии 7 применено корректно. Docker-конфиг nginx больше не существует.

---

## 🚢 Что требует ручного деплоя на VPS (код в репозитории уже корректен)

### deploy.sh проверен — копирование настроено верно

`deploy.sh:17` — `cp -r frontend/pwa/app/* /var/www/nura-ai.ru/app/` ✅
`deploy.sh:21` — `cp frontend/manifest.json /var/www/nura-ai.ru/manifest.json` ✅

Код в репозитории готов. Расхождение исключительно в том, что прод не обновлялся после Сессии 3.

### Чеклист команд (порядок важен)

```bash
# 1. Подключиться к VPS
ssh -i C:\Users\Bayzel\.ssh\id_ed25519_astro -o StrictHostKeyChecking=no root@45.144.178.118

# 2. Запустить деплой (скопирует HTML, manifest.json, nginx-конфиг, перезагрузит nginx)
cd /opt/nura && bash deploy.sh

# 3. Убедиться, что новый nginx-конфиг попал на хост (deploy.sh НЕ копирует его автоматически)
cp /opt/nura/nura_app/nginx/nura-ai.ru.conf /etc/nginx/sites-enabled/nura-ai.ru.conf
nginx -t && systemctl reload nginx

# 4. Проверить, что manifest.json отдаёт один Content-Type
curl -I https://nura-ai.ru/manifest.json | grep -i content-type
# Ожидаемый вывод: Content-Type: application/manifest+json (ровно одна строка)

# 5. Проверить, что <link rel="manifest"> на лендинге
curl -s https://nura-ai.ru/ | grep 'rel="manifest"'
# Ожидаемый вывод: <link rel="manifest" href="/manifest.json">

# 6. Проверить, что /app/ содержит баннер и pwa-install.js
curl -s https://nura-ai.ru/app/ | grep 'pwa-install.js'
# Ожидаемый вывод: <script src="/pwa-install.js"></script>
```

---

## 🔁 Организационное решение: проблема дрейфа прод/код

Это третий раз за девять сессий, когда расхождение между репозиторием и продом оказывается корневой причиной:

| Сессия | Проблема |
|--------|----------|
| Сессия 1 | deploy.sh не копировал PWA-файлы |
| Сессия 3–4 | Изменения в `/app/index.html` не докатились на прод |
| Эта сессия | Тег `<link rel="manifest">` отсутствовал в коде + прод не обновлялся |

**Причина:** деплой — ручной. Нет механизма, гарантирующего, что прод соответствует HEAD репозитория после завершения сессии.

### Рекомендация (не реализовывать в этой сессии — это отдельная задача)

**Вариант А (минимальный):** Добавить в `deploy.sh` финальный шаг, записывающий хэш деплоя:

```bash
echo "→ Writing deploy version..."
git rev-parse HEAD > /var/www/nura-ai.ru/VERSION
```

И отдельный скрипт `check_deploy.sh`, который сравнивает `git rev-parse HEAD` (локально в репо) с `/var/www/nura-ai.ru/VERSION` (на сервере) и сигнализирует о расхождении. Добавить вызов `check_deploy.sh` в конец каждой сессии как проверку.

**Вариант Б (рекомендуемый):** GitHub Action, автоматически деплоящий при пуше в `main`. Устраняет человеческий фактор — деплой происходит при каждом merge, а не когда кто-то вспомнит запустить `deploy.sh`.

```yaml
# .github/workflows/deploy.yml (концепт)
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to VPS
        uses: appleboy/ssh-action@v1
        with:
          host: 45.144.178.118
          username: root
          key: ${{ secrets.VPS_SSH_KEY }}
          script: cd /opt/nura && git pull origin main && bash deploy.sh
```

Вариант Б надёжнее, но требует настройки GitHub Secrets и безопасного хранения SSH-ключа.

---

## 📋 Статус блокеров после правок

| # | Баг | Статус в репозитории | Требуется для прода |
|---|-----|---------------------|---------------------|
| 1 | Нет `<link rel="manifest">` | ✅ Исправлен | Деплой `deploy.sh` |
| 2 | Двойной Content-Type на manifest.json | ✅ Исправлен в `nura-ai.ru.conf` | Ручное копирование nginx-конфига |
| 3 | `/app/index.html` без баннера и pwa-install.js | ✅ Код корректен с Сессии 3 | Деплой `deploy.sh` |

**Все три блокера устранены в коде.** Для активации на проде необходим ручной деплой по чеклисту выше.
