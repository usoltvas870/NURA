# Полная ревизия проекта NURA — отчёт

> Дата: 22.06.2026
> Метод: статический анализ кода (все файлы репозитория прочитаны)
> Основание: BROWSER_AUDIT.md (Codex) + полный обход кодовой базы

---

## Сводка

- **Всего найдено проблем:** 5 критичных / 6 средних / 5 мелких
- **Главный системный вывод:** прод **частично отстаёт от репозитория** — лендинг `index.html` должен быть актуален (deploy.sh его копирует), но ключевые PWA-файлы (`manifest.json`, `sw.js`, `pwa-install.js`, иконки) **не попадают на прод**. Файл `offline.html` не существует в репозитории вообще. PWA-воронка в коде готова (Фаза 2 согласно `docs/pricing.md`), но деплой-скрипт неполный — это причина расхождения.
- **Стек:** Python 3.11 + FastAPI (не Node.js, как указано в задании). Фронтенд — Vanilla JS.
- **Валидатор test_mode:** при `APP_ENV=production` (`.env:3`) `test_mode` принудительно `False` независимо от значения в env. Кнопка «Подключить подписку» всегда получает 403 на проде.

---

## Подтверждение находок Codex (BROWSER_AUDIT.md)

### [КРИТИЧНО] Прод-лендинг ведёт в Telegram вместо web/PWA-воронки

- **Статус:** Уточнено
- **Файл/строка:** `index.html:313` (CTA → `mini.html`), `index.html:320` (→ `/app/`), `index.html:501` (→ `mini.html`), `deploy.sh:1-20`
- **Что выяснилось:** Локальный `index.html` уже содержит все PWA/web CTAs (фаза 2 из `docs/pricing.md:48-49`). Deploy.sh копирует `index.html` на прод → после деплоя лендинг должен вести в web-воронку. **Проблема в том, что deploy.sh копирует ТОЛЬКО `index.html` и `frontend/pwa/app/*`, но НЕ копирует `manifest.json`, `sw.js`, `pwa-install.js`, иконки. Без них PWA-функционал (установка, офлайн, push) не работает.** Сам лендинг визуально должен быть актуален.
- **Файлы, не попадающие на прод через deploy.sh:**
  - `frontend/manifest.json` — не копируется
  - `frontend/sw.js` — не копируется (и зарегистрирован как `/service-worker.js`, а не `/sw.js`)
  - `frontend/pwa-install.js` — не копируется (glob `frontend/pwa/*.js` не захватывает `frontend/pwa-install.js`)
  - `offline.html` — **не существует в репозитории**
  - `icons/` — **директория не существует в репозитории**
- **Рекомендация:** Расширить `deploy.sh`:
  ```bash
  cp frontend/manifest.json /var/www/nura-ai.ru/manifest.json
  cp frontend/sw.js /var/www/nura-ai.ru/service-worker.js   # переименовать при копировании
  cp frontend/pwa-install.js /var/www/nura-ai.ru/pwa-install.js
  cp frontend/nura-hero.webp /var/www/nura-ai.ru/nura-hero.webp
  cp favicon.ico favicon.png /var/www/nura-ai.ru/
  ```
  Создать `offline.html` и директорию `icons/` с иконками согласно `docs/pwa-spec.md:87-131`.

---

### [КРИТИЧНО] Устаревшая цена 990₽/690₽ на проде вместо 890₽

- **Статус:** Подтверждено (если прод показывает старые цены — значит деплой не выполнялся)
- **Файл/строка:** Source of truth — `nura_app/core/config.py:62` (`matrix_one_time_price_rub: int = 890`). Другие места: `index.html:491,501` (890₽), `nura_app/api/routes/web.py:145-146` (amount=890). Документация: `docs/pricing.md:14` (890₽).
- **Что выяснилось:** Цена 890₽ консистентна во всех трёх местах (config, фронтенд, API). Старая цена 990/690 не найдена нигде в текущем коде. Если прод показывает 990/690 — index.html на сервере устарел (deploy.sh не запускался после изменения цены).
- **Рекомендация:** Выполнить `bash deploy.sh` на VPS. В будущем — вынести цену из хардкода в data-атрибут или загружать из `/api/v1/web/me`.

---

### [КРИТИЧНО] PWA offline/service worker сломан на уровне маршрута и кэша

- **Статус:** Уточнено (проблема глубже, чем описано)
- **Файл/строка:**
  - Регистрация: `mini.html:10`, `success.html:10`, `frontend/pwa/app/index.html:9`, `frontend/pwa/app/profile.html:9`, `frontend/pwa/app/tarot.html:9`, `frontend/pwa/app/chat.html:154` — все регистрируют `/service-worker.js`
  - Файл SW: `frontend/sw.js:1-11` — имя файла `sw.js`, а не `service-worker.js`
  - Docker nginx: `frontend/nginx.conf:23` — отдаёт только `/sw.js`
  - Прод nginx: `nura_app/nginx/nura-ai.ru.conf:18-22` — отдаёт `/service-worker.js` (правильно)
  - `sw.js:1-11` — только `skipWaiting()` + `clients.claim()`, нет precache (`cache.addAll`), нет fallback на `offline.html`
  - `frontend/Dockerfile:4` — копирует `offline.html`, но **файл не существует в репозитории**
- **Что выяснилось:**
  1. **Двойной баг с именами:** HTML регистрирует `/service-worker.js`, файл называется `sw.js`. Прод nginx правильно маппит `/service-worker.js` → файл. Но deploy.sh не копирует sw.js → файла нет на проде.
  2. **SW не делает precache:** `sw.js` содержит минимальную реализацию (install/activate/fetch), но без `cache.addAll`, без `precache`, без `offline.html` fallback. Спецификация `docs/pwa-spec.md:197-256` описывает полноценный SW с precache и push, но реализована только заглушка.
  3. **offline.html не существует:** `docs/pwa-spec.md:37` утверждает «✅ Готово», но файла нет в репозитории.
  4. **Иконки не существуют:** `manifest.json` ссылается на `/icons/icon-192.png` и др. — директории `icons/` нет в репозитории.
- **Рекомендация:**
  1. Переименовать `frontend/sw.js` → `frontend/service-worker.js` ИЛИ исправить пути регистрации на `/sw.js`
  2. Реализовать precache + offline fallback согласно `docs/pwa-spec.md:197-256`
  3. Создать `frontend/offline.html`
  4. Создать `frontend/icons/` с иконками согласно спецификации
  5. Добавить копирование этих файлов в `deploy.sh`

---

### [КРИТИЧНО] Кнопка подписки в PWA профиле бьёт в тестовый endpoint

- **Статус:** Подтверждено
- **Файл/строка:** `frontend/pwa/app/profile.html:188` — вызов `/web/test-subscribe`; `nura_app/api/routes/web.py:366-369` — guard `not settings.test_mode` → 403; `nura_app/core/config.py:76-82` — `_protect_test_mode` принудительно False при `APP_ENV=production`
- **Что выяснилось:** Валидатор `_protect_test_mode` (config.py:78-82) делает `test_mode=False` при `APP_ENV=production` **независимо от значения в .env**. На проде (`.env:3` = `APP_ENV=production`) эндпоинт `/test-subscribe` всегда возвращает 403. Фронт никак не обрабатывает 403 — просто показывает «Ошибка, попробуй ещё раз». Реальный эндпоинт `/subscribe` (web.py:260-283) существует, но фронт его не вызывает.
- **Рекомендация:** `profile.html:188` → заменить `/web/test-subscribe` на `/web/subscribe`. Это хардкод, забытый после тестирования.

---

### [СРЕДНЕ] Переключатели уведомлений стучатся в несуществующий API

- **Статус:** Подтверждено
- **Файл/строка:** `frontend/pwa/app/profile.html:138` — `fetch(BASE + '/user/notifications', {method:'PATCH',...})`; поиск по всем route-файлам — ноль совпадений
- **Что выяснилось:** Маршрута `PATCH /api/v1/user/notifications` (полный URL из-за BASE) не существует. Нет даже близких аналогов (`/web/notifications`, `/push/preferences`). Фронт молча глотает ошибку (`.catch(function(){})`). Настройки сохраняются только в `localStorage` (profile.html:134-136).
- **Рекомендация:** Создать endpoint `PATCH /api/v1/web/notifications` или добавить поле `notification_prefs` в существующий профиль. Либо убрать неработающие выключатели до реализации.

---

### [СРЕДНЕ] История чата не сохраняет ответы NURA

- **Статус:** Подтверждено
- **Файл/строка:** `frontend/pwa/app/chat.html:99` — `addBubble('user', text, t, true); saveMsg('user', text, t);`; `chat.html:113` — `addBubble('nura', d.reply, N.now(), true)` **без saveMsg**
- **Что выяснилось:** `saveMsg` (chat.html:143-146) вызывается только для сообщений пользователя. Ответ NURA (строка 113) только рендерится в DOM. При перезагрузке страницы `chatLog` из localStorage (строка 59) содержит только сообщения пользователя. Серверу в `history` (строка 102-104) отправляется обрезанный контекст — только сообщения пользователя без ответов NURA.
- **Рекомендация:** Добавить `saveMsg('nura', d.reply, N.now())` в `.then` на строке 113.

---

### [СРЕДНЕ] Install UI для PWA не может отрисоваться

- **Статус:** Подтверждено
- **Файл/строка:** `frontend/pwa-install.js:52,57,67,72` — ссылки на `#pwa-install-banner` и `#pwa-ios-modal`; `mini.html:226` — подключает `/pwa-install.js`
- **Что выяснилось:** Элементы `#pwa-install-banner` и `#pwa-ios-modal` не найдены ни в одном HTML-файле проекта. Grep по всему репозиторию: элементы упоминаются только в `pwa-install.js` и `BROWSER_AUDIT.md`. Разметка либо никогда не была создана, либо удалена при рефакторинге. Скрипт `pwa-install.js` полностью работоспособен (с точки зрения логики), но не имеет DOM-элементов для манипуляции.
- **Рекомендация:** Добавить HTML-разметку для `#pwa-install-banner` и `#pwa-ios-modal` в `mini.html` и `/app/index.html` согласно `docs/pwa-spec.md:520-564`.

---

### [СРЕДНЕ] Личный кабинет PWA открывает несуществующий web-route отчёта

- **Статус:** Подтверждено
- **Файл/строка:** `frontend/pwa/app/profile.html:148` — `N.fetchJSON(BASE + '/reports/' + id)` → `https://nura-ai.ru/api/v1/reports/matrix-full`; `nura_app/api/routes/reports.py:80` — роут `/report/{token}` (без префикса `/api/v1/reports`)
- **Что выяснилось:** Эндпоинт `/api/v1/reports/{id}` не существует. Правильный путь — `/report/{token}` (reports.py:80). Фронт передаёт строковый алиас `'matrix-full'` вместо `report_token`. При этом `/web/me` (web.py:199) уже возвращает `reports[].url` = `/report/{token}`. Фронт игнорирует готовый URL и пытается собрать свой.
- **Рекомендация:** `profile.html:146-149` — использовать `d.reports[0].url` из ответа `/web/me` вместо хардкода `'matrix-full'`.

---

### [МЕЛКО] На лендинге нет нормальных web-страниц для политики и контактов

- **Статус:** Подтверждено
- **Файл/строка:** `index.html:724-725` — обе ссылки ведут на `https://t.me/nura_support`
- **Что выяснилось:** В репозитории нет файлов `privacy.html`, `contacts.html` или аналогичных. Нет даже заготовок. Ссылки ведут в Telegram-поддержку — это намеренное решение на данный момент (MVP), но юридически рискованно (закон о персональных данных / 152-ФЗ требует политику конфиденциальности).
- **Рекомендация:** Создать `privacy.html` с политикой обработки данных и опубликовать на `https://nura-ai.ru/privacy`. Обновить ссылки в `index.html:724`.

---

## Новые критичные проблемы (не из BROWSER_AUDIT.md)

### 🔴 K1. deploy.sh неполный — прод лишён ключевых PWA-файлов

- **Файл/строка:** `deploy.sh:1-20`
- **Описание:** Скрипт копирует только `index.html`, `nura-ds.css`, `frontend/pwa/app/*` и `frontend/pwa/*.js`. Не копирует: `manifest.json`, `sw.js` (service worker), `pwa-install.js`, иконки. Nginx на проде настроен отдавать эти файлы (`nura_app/nginx/nura-ai.ru.conf:12-32`), но их нет на диске. PWA-функционал (установка на домашний экран, офлайн-режим, push-уведомления) не работает.
- **Почему критично:** Пользователи видят предложение «установить приложение», но установка не срабатывает. Платёжная воронка через веб работает, но ключевое преимущество (PWA) сломано.
- **Рекомендация:** Дополнить deploy.sh копированием недостающих файлов (см. рекомендацию к п. 0.1).

---

### 🔴 K2. offline.html не существует в репозитории

- **Файл/строка:** `frontend/Dockerfile:4` — `COPY ... offline.html ...`, но файла нет
- **Описание:** Docker-образ PWA не может быть собран (COPY упадёт). Документация `docs/pwa-spec.md:37` утверждает «offline.html ✅ Готово», `docs/launch-checklist.md:100` утверждает «offline.html ✅», но файл отсутствует.
- **Почему критично:** Блокирует Docker-сборку PWA-контейнера. Заявленный офлайн-режим не работает. Документация вводит в заблуждение.
- **Рекомендация:** Создать `frontend/offline.html` с брендированной страницей. Исправить статус в документации.

---

### 🔴 K3. Иконки PWA не существуют

- **Файл/строка:** `frontend/manifest.json:12-21` — ссылки на `/icons/icon-192.png` и др.
- **Описание:** Директория `icons/` не найдена в репозитории. Nginx настроен на отдачу из `/var/www/nura-ai.ru/icons/` (`nura-ai.ru.conf:24-27`), но файлов нет. Без иконок PWA не устанавливается (браузеры требуют минимум icon-192 и icon-512).
- **Почему критично:** PWA не может быть установлено на Android и iOS. Lighthouse PWA-аудит не может быть пройден.
- **Рекомендация:** Создать иконки согласно `docs/pwa-spec.md:124-131` (192×192, 512×512, maskable, apple-touch-icon).

---

### 🔴 K4. Имена файлов SW не совпадают с путями регистрации

- **Файл/строка:** HTML: `mini.html:10` и 5 других страниц — регистрируют `/service-worker.js`. Файл: `frontend/sw.js`. Docker nginx: `frontend/nginx.conf:23` — `/sw.js`. Прод nginx: `nura-ai.ru.conf:18` — `/service-worker.js`.
- **Описание:** Файл называется `sw.js`, но регистрируется как `/service-worker.js`. В Docker-окружении nginx отдаёт только `/sw.js` → регистрация SW падает молча (`.catch(function(){})`). На проде nginx отдаёт `/service-worker.js`, но deploy.sh не копирует файл → 404.
- **Почему критично:** Service Worker не регистрируется ни в одном окружении: в Docker — из-за несовпадения имён, на проде — из-за отсутствия файла.
- **Рекомендация:** Переименовать `frontend/sw.js` → `frontend/service-worker.js` ИЛИ заменить все пути регистрации на `/sw.js` и обновить `deploy.sh` для копирования файла.

---

### 🔴 K5. Frontend push-подписка не реализована

- **Файл/строка:** Поиск `pushManager.subscribe` по всем `.js`-файлам — 0 результатов
- **Описание:** Серверная часть Web Push полностью готова: `push.py` (VAPID, subscribe/unsubscribe), `web_push.py` (отправка через pywebpush). Но ни в одном JS-файле фронтенда нет кода `navigator.serviceWorker.ready.then(reg => reg.pushManager.subscribe(...))`. Без клиентской подписки push-уведомления не могут работать.
- **Почему критично:** Вся серверная инфраструктура push-уведомлений (VAPID-ключи, эндпоинты, pywebpush, Celery-задачи с дедупликацией) бесполезна без клиентской части.
- **Рекомендация:** Добавить код подписки на push в `nura-pwa.js` или отдельный `push-subscribe.js`. Подключить на страницах `/app/*`. Запрашивать разрешение на уведомления в подходящий момент (после покупки/подписки, не при первом входе).

---

## Проблемы средней важности

### 🟡 S1. PWA Docker-контейнер не используется в production

- **Файл/строка:** `nura_app/docker-compose.yml:108-116` — сервис `pwa` на порту 8080; `nura_app/nginx/nura-ai.ru.conf` — не проксирует порт 8080
- **Описание:** Прод nginx работает напрямую с хостовой файловой системой (`/var/www/nura-ai.ru/`). PWA Docker-контейнер запущен, но ни один location-блок не направляет трафик на `127.0.0.1:8080`. Контейнер потребляет ресурсы впустую. Более того, он использует свой `frontend/nginx.conf` (который содержит баг с именем SW), а не прод-конфиг.
- **Рекомендация:** Удалить сервис `pwa` из docker-compose.yml, если он не нужен. Либо настроить прод nginx на проксирование `/app/` через Docker.

---

### 🟡 S2. Session ID передаётся в query string

- **Файл/строка:** `nura_app/api/routes/web.py:199` — `session_id: str` как query-параметр; `frontend/pwa/app/nura-pwa.js:22` — `sessionId` из localStorage
- **Описание:** session_id (UUID) передаётся в URL (`/web/me?session_id=...`, `/tarot/daily-card?session_id=...`). Это оставляет его в server access logs, browser history и потенциально в Referer-заголовках. Сам по себе UUID безопасен (не guessable), но лучшая практика — передавать в заголовке (`X-Session-Id`) или cookie.
- **Рекомендация:** Перевести все эндпоинты на приём session_id из заголовка `X-Session-Id` (чат уже использует этот подход в `chat.html:107`). Убрать из query string.

---

### 🟡 S3. Нет проверки сессии на всех эндпоинтах

- **Файл/строка:** `nura_app/api/routes/web.py:71-114`, `116-151`, `167-196`, `199-249`, `260-283`, `300-354`, `366-387`
- **Описание:** Каждый эндпоинт независимо проверяет `session_id` через `user_repo.get_by_web_session_id()`. Нет middleware/Dependency, который делал бы это централизованно. Код дублируется. При добавлении новых эндпоинтов легко забыть проверку.
- **Рекомендация:** Создать FastAPI Dependency `get_current_web_user` в `api/deps.py`, использовать во всех web-эндпоинтах.

---

### 🟡 S4. Валидатор test_mode не логирует попытки обхода

- **Файл/строка:** `nura_app/core/config.py:76-82`
- **Описание:** `_protect_test_mode` молча форсирует `False` в production. При попытке задать `TEST_MODE=true` в .env на проде — значение игнорируется без предупреждения. Разработчик может не понять, почему `/test-subscribe` не работает.
- **Рекомендация:** Добавить `logger.warning("test_mode forced to False in production")` при отключении.

---

### 🟡 S5. Пути к API в профиле не консистентны

- **Файл/строка:** `frontend/pwa/app/profile.html:138,148,188`
- **Описание:** Три разных подхода к вызову API в одном файле:
  - `fetch(BASE + '/user/notifications', {method:'PATCH', headers:{'X-Session-Id': session_id}, ...})` — заголовок
  - `N.fetchJSON(BASE + '/reports/' + id, {headers:{'X-Session-Id': session_id}})` — заголовок
  - `fetch(BASE + '/web/test-subscribe', {method:'POST', headers:{'Content-Type':'application/json'}, body:...})` — session_id в теле

  Не используется единый паттерн. Два из трёх путей нерабочие.
- **Рекомендация:** Унифицировать на `N.fetchJSON` с передачей session_id через заголовок `X-Session-Id`.

---

### 🟡 S6. Кнопка «Купить» в профиле ведёт в Telegram вместо веб-оплаты

- **Файл/строка:** `frontend/pwa/app/profile.html:46-47` — кнопки «Добавить» ведут на `https://t.me/ai_nura_bot`
- **Описание:** Совместимость и Прогноз на год отправляют пользователя в Telegram-бот вместо веб-чекаута. Это ломает PWA-воронку — пользователь установил приложение, но вынужден переключаться в Telegram.
- **Рекомендация:** Заменить ссылки на веб-эндпоинты `/web/subscribe` или аналогичные.

---

## Мелкие проблемы / технический долг

### 💭 M1. Неиспользуемое поле в .env

- **Файл/строка:** `nura_app/core/config.py:61` — `subscription_price_rub: int = 590`; `nura_app/.env:43` — `REPORT_PRICE_RUB=590`
- **Описание:** Поле `REPORT_PRICE_RUB` в .env не совпадает с `subscription_price_rub` и не используется в коде — цена матрицы берётся из `matrix_one_time_price_rub: int = 890` (config.py:62). Цена 590₽ — устаревшее значение. `docs/pricing.md:121` ссылается на `subscription_price_rub=390`, что тоже устарело (сейчас 390 = tarot_subscription_price_rub).
- **Рекомендация:** Удалить `REPORT_PRICE_RUB` из .env и `subscription_price_rub` из config.py, если они не используются.

---

### 💭 M2. Дублирование CSS-переменных

- **Файл/строка:** `nura-ds.css` vs `nura-pwa.css:2-27` vs встроенные стили в `index.html:31-58`, `mini.html:23-40`, `success.html:22-38`
- **Описание:** Цветовая схема определена в каждом HTML-файле инлайн и в двух CSS-файлах. Изменение цвета требует правок в 6+ местах. Часть переменных отличается (например, `--bg-tab` есть в `nura-pwa.css` но не в `index.html`).
- **Рекомендация:** Вынести тему в один файл `theme.css`, подключать на всех страницах.

---

### 💭 M3. Поле `BOT_USERNAME` отсутствует в .env

- **Файл/строка:** `nura_app/.env:1-45` — нет `BOT_USERNAME`; `nura_app/api/routes/web.py:180` — `bot_username = settings.bot_username` → `None`
- **Описание:** Переменная `bot_username` не задана в `.env`. Если она не задана на проде, deep-link для связки PWA↔Telegram (`/generate-link-token`) сформирует некорректную ссылку `https://t.me/None?start=link_...`.
- **Рекомендация:** Добавить `BOT_USERNAME=ai_nura_bot` в `.env` на проде.

---

### 💭 M4. `success.html` содержит относительный путь, который не работает из `/success`

- **Файл/строка:** `success.html:90` — `onclick="location.href='profile.html#reports'"`
- **Описание:** `success.html` открывается по URL `https://nura-ai.ru/success?token=...`. `profile.html#reports` — относительный путь, который разрешится в `/app/profile.html#reports` (nginx заматчит `/app/` location), но `profile.html` лежит в `/app/profile.html` а не в корне.
- **Рекомендация:** Заменить на `location.href='/app/profile.html#reports'`.

---

### 💭 M5. `nura_app/alembic.ini` содержит пароль БД в открытом виде

- **Файл/строка:** `nura_app/alembic.ini:4` — `sqlalchemy.url = postgresql://nura:change-me-db-password@localhost:5432/nura`
- **Описание:** Пароль `change-me-db-password` — плейсхолдер, но в продакшене там будет реальный пароль. Alembic.ini коммитится в репозиторий.
- **Рекомендация:** Использовать `alembic/env.py` с чтением `DATABASE_URL` из переменных окружения вместо хардкода в `alembic.ini`.

---

## Несоответствия документации и кода

| Документ | Утверждение | Реальность |
|----------|------------|------------|
| `docs/pwa-spec.md:37` | `offline.html` ✅ Готово (сессия 19) | Файл не существует |
| `docs/pwa-spec.md:36` | Иконки PWA ✅ Готово (сессия 19) | Директория `icons/` не существует |
| `docs/pwa-spec.md:39` | Install UI ✅ Готово (сессия 20/23) | DOM-элементы `#pwa-install-banner` и `#pwa-ios-modal` отсутствуют |
| `docs/pwa-spec.md:40` | Web Push backend ✅ (отмечен как готовый в секции 2, но ❌ в строке 39) | Backend готов, но фронтенд-подписка отсутствует |
| `docs/launch-checklist.md:99-109` | SW регистрация на всех 4 PWA страницах ✅ | Регистрация есть, но SW не работает (имя/путь mismatch) |
| `docs/launch-checklist.md:56` | Обновить CTA на лендинге (матрица 890₽ + таро 390₽) — 🟡 P1 | Уже сделано в коде (index.html:501,540), статус устарел |
| `docs/pricing.md:44` | Текущие тарифы 0₽ / 390₽/мес (MVP) | Код перешёл на Фазу 2 (матрица 890₽ + таро 390₽), документация отстаёт |
| `docs/pwa-spec.md:83` | `start_url: "/app/"` | `frontend/manifest.json:5` — `start_url: "/app/"` ✅, но в спецификации указан `scope: "/"`, которого нет в реальном manifest.json |
| `docs/pwa-spec.md:199` | `CACHE_NAME = 'nura-v2'`, `STATIC_ASSETS = [...]` | `frontend/sw.js:1-11` — нет ни CACHE_NAME, ни STATIC_ASSETS, ни precache |

---

## Закрыты пункты «Не проверено» из BROWSER_AUDIT.md

### Реальные /app/* страницы на проде (локальный код)

**Вывод:** Локальный код всех 4 страниц (`/app/index.html`, `/app/chat.html`, `/app/tarot.html`, `/app/profile.html`) прочитан и проанализирован. Все страницы функциональны, но содержат баги (см. выше). Deploy.sh копирует `/app/*` → на проде код должен совпадать с локальным. **Подтвердить без доступа к VPS невозможно.**

### Telegram deep-link / login / Mini App

**Вывод:** NURA **не является** Telegram Mini App. В коде нет `window.Telegram.WebApp.initData`, нет валидации подписи initData на бэкенде. Бот — стандартный Telegram-бот (через aiogram). Связка PWA↔Telegram реализована через link-токен (`/generate-link-token` → `https://t.me/{bot}?start=link_{TOKEN}`). **Уязвимостей, связанных с Mini App, нет, потому что Mini App не используется.**

### End-to-end оплата и post-payment flow

**Вывод (статический анализ):** Webhook корректно реализован (`payment.py:202-299`):
- Принимает `payment.succeeded` от YooKassa
- Проверяет идемпотентность (повторная доставка того же события → idempotent skip)
- Использует `SELECT ... FOR UPDATE` для защиты от гонки (claim_succeeded, `payment.py:37-59`)
- При ошибке обновления пользователя — откатывает статус платежа в pending
- Непроверенным остаётся сам факт интеграции с YooKassa (shop_id/secret_key в .env — плейсхолдеры `change-me`). **End-to-end тест требует реального платежа — это нормально.**

### Push-уведомления end-to-end

**Вывод:** Серверная часть готова (`push.py`, `web_push.py`). Клиентская подписка (`pushManager.subscribe()`) **отсутствует** на фронтенде. End-to-end невозможен без клиентской части.

### Адаптивность по живому DOM

**Вывод (статический анализ):**
- Viewport meta-тег: ✅ на всех страницах
- Media queries: `index.html` — 1024px, 768px; `nura-pwa.css` — 760px, 380px; `mini.html` — 380px
- Mobile-first подход: ✅ (базовые стили для mobile, @media для desktop)
- Без живого браузера нельзя подтвердить визуальное качество, но явных пропусков (отсутствие viewport, отсутствие media queries) нет.

---

## Рекомендации по дальнейшим шагам

Приоритеты упорядочены: **сначала решить вопрос с деплоем, потом критические баги, потом остальное.**

### 🔴 P0 — Немедленно (блокирует базовый функционал)

1. **Выполнить деплой на VPS** (`bash deploy.sh` из `/opt/nura`). Без этого лендинг и PWA на проде не соответствуют коду.
2. **Дополнить deploy.sh** недостающими файлами (manifest.json, service-worker.js/sw.js, pwa-install.js, иконки). Создать `offline.html` и `icons/`.
3. **Исправить имя файла SW или путь регистрации** — привести к единому имени во всех HTML и nginx-конфигах.
4. **Починить кнопку подписки** (profile.html:188 — `/test-subscribe` → `/subscribe`).
5. **Добавить `bot_username` в .env** на проде — без этого не работает связка PWA↔Telegram.

### 🟡 P1 — Критические баги, не блокирующие базовый функционал

6. **Добавить saveMsg для ответов NURA** в чате (chat.html:113).
7. **Создать endpoint `/api/v1/web/notifications`** или добавить поле в профиль.
8. **Добавить HTML-разметку для install UI** (`#pwa-install-banner`, `#pwa-ios-modal`).
9. **Исправить открытие отчёта** в профиле — использовать `d.reports[0].url` вместо хардкода `'matrix-full'`.
10. **Реализовать клиентскую push-подписку** (`pushManager.subscribe`) на фронтенде.

### 💭 P2 — Технический долг и улучшения

11. Создать `privacy.html` с политикой конфиденциальности.
12. Унифицировать CSS-темы в одном файле.
13. Перевести session_id из query string в заголовки.
14. Создать централизованную Dependency для проверки web-сессии.
15. Удалить неиспользуемые поля из .env и config.py.
16. Удалить или интегрировать PWA Docker-контейнер.
17. Вынести пароль БД из `alembic.ini` в переменные окружения.
18. Исправить относительный путь в success.html:90.
19. Обновить документацию (`pwa-spec.md`, `launch-checklist.md`, `pricing.md`) до актуального состояния кода.

---

*Конец отчёта.*
