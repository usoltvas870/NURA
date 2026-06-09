# NURA — State

> Последнее обновление: **09.06.2026 — Сессия 19** — Claude Sonnet 4.6 (claude.ai)

---

## 🏗 Архитектурные решения (ADRs)

### Действующие

- **Async-first**: SQLAlchemy 2.0 async + asyncpg
- **AI через Celery**: генерация мини/полного отчёта в фоновых задачах
- **Nginx на хосте**: не в Docker, используется существующий nginx + Certbot SSL
- **API на 127.0.0.1:8000**: nginx проксирует /webhook/, /report/, /api/
- **Bot в polling mode**: без вебхука (проще для MVP)
- **Matrix of Destiny**: 22 аркана Таро как система психологических архетипов (не астрология)
- **Admin panel**: sqladmin на sync engine (порт 8000, /admin), отдельный от async-ядра
- **Video Assembler**: FFmpeg subprocess (не MoviePy), GPU autodetect, easing через filter_complex

### 🆕 ADR-001 — PWA как ядро продукта (09.06.2026)

**Решение:** PWA (`nura-ai.ru`) — основной интерфейс продукта. Telegram-бот — канал привлечения и push-fallback.

**Контекст:** Блокировки и замедление Telegram в РФ делают его ненадёжным основным каналом. PWA работает независимо от Telegram, уведомления идут через APNs/FCM напрямую.

**Разделение ролей:**

| Платформа | Роль | Что делает | Что НЕ делает |
|-----------|------|-----------|---------------|
| **PWA** (nura-ai.ru) | Дом пользователя | Отчёт, таро, чат, профиль, оплата | Виральный share в TG |
| **Telegram-бот** | Воронка + fallback | Мини-разбор, share совместимости, push-fallback, deep-link в PWA | Оплата подписки, полный чат, просмотр отчётов |

**Следствия:**
- Трафик из соцсетей (TikTok, Instagram, Threads) → лендинг `nura-ai.ru`, не в бота
- Оплата матрицы 890₽ и подписки 390₽/мес — только через веб (YooKassa redirect)
- Бот шлёт deep-link в PWA с auth-токеном после каждого ключевого действия
- Блокировка Telegram = потеря канала привлечения, но не потеря продукта

**Документация:** `docs/platform-strategy.md` ✅, `docs/pwa-spec.md` ✅, `docs/bot-spec-pwa-patch.md` ✅

### 🆕 ADR-002 — Дедупликация уведомлений (09.06.2026)

**Решение:** Пользователь никогда не получает одно уведомление дважды — и в PWA Push, и в Telegram.

**Правило:** Поле `has_pwa_push: bool` в таблице `users`. Celery-задача `send_daily_card` проверяет флаг:
- `has_pwa_push = True` → Web Push (APNs/FCM)
- `has_pwa_push = False` → Telegram-бот

**Следствия:** Нужна Alembic-миграция с добавлением поля `has_pwa_push` в `users`.

### 🆕 ADR-003 — Связка аккаунтов PWA ↔ Telegram (09.06.2026)

**Решение:** Связка через одноразовый link-токен, без принуждения.

**Механика:**
1. Пользователь в PWA нажимает "Подключить Telegram" (в профиле или после совместимости)
2. Генерируется UUID-токен, сохраняется в Redis (TTL 15 мин)
3. Пользователь переходит `t.me/nura_bot?start=link_TOKEN`
4. Бот принимает токен → находит web-пользователя → проставляет `telegram_id` в его запись
5. После связки: аккаунты объединены, пуши идут по правилу ADR-002

**Три точки входа в Telegram из PWA:**
- После расклада совместимости → кнопка "Поделиться в Telegram" (`tg://msg_url?...`)
- Профиль → Уведомления → "Подключить Telegram"
- Однократный баннер после первой покупки

---

## ✅ Current — что работает в проде

### Инфраструктура
- ✅ Landing page — деплой, SSL, Яндекс.Метрика (`/var/www/nura-ai.ru/index.html`)
- ✅ FastAPI бэкенд — health endpoint, rate limiting, admin panel (sqladmin)
- ✅ PostgreSQL 16 — таблицы users, reports, payments
- ✅ Redis — кэш, брокер Celery
- ✅ Celery worker/beat — запущены
- ✅ Nginx — прокси, SSL, /webhook/, /report/, /api/

### Продукт
- ✅ Мини-разбор в браузере — `mini.html` + `/api/v1/web/mini-analysis`
- ✅ Оплата матрицы через веб — `create_web_matrix_payment()`, `/api/v1/web/create-payment`
- ✅ Полный AI-отчёт V2 — генерация 15 секций, HTML/PDF, сайдбар, @media print
- ✅ Страница отчёта `/report/{token}` — деплоена
- ✅ Kitchen-слой бэкенд — AI-генерация 12 полей, хранение в БД (JSONB), API `/report/{token}/kitchen`
- ✅ Подписка 390₽/мес — YooKassa recurrent, Celery downgrade/check
- ✅ Telegram-бот — поллинг, /start, мини-разбор, таро-меню, FSM
- ✅ Таро-бот — 11 хендлеров, 6 раскладов, FSM, AI-промпты (без названий арканов), анимация загрузки
- ✅ Совместимость V2 — лимитная модель (has_matrix/compatibility_used/has_tarot), виральный share, HTML-шаблон
- ✅ Персонализация карты дня — уникальная карта по формуле (дата + центральный аркан матрицы)
- ✅ send_daily_card — Celery-beat 06:00 МСК, всем активным пользователям
- ✅ Чат с NURA — FSM, 5 сообщений free / безлимит premium
- ✅ Video Assembler — FFmpeg бэкенд, CLI, Celery-задача, GPU autodetect
- ✅ Carousel Assembler — Pydantic схемы, HTML-шаблоны, CLI

### Модель данных (users)
```
has_matrix: bool          # купил матрицу (890₽)
has_tarot: bool           # активная таро-подписка
compatibility_used: bool  # использовал первый бесплатный расклад
subscription_status: str  # free | premium | blocked
telegram_id: int | null   # null для веб-пользователей
web_session_id: str | null
email: str | null
has_pwa_push: bool | null
push_endpoint: str | null
push_p256dh: str | null
push_auth: str | null
referred_by: int | null   # telegram_id пригласившего
```

---

## 🟡 В процессе / незакрытые задачи

### Критический путь (блокирует монетизацию)
- 🔴 **YooKassa credentials** — shop_id и secret_key в `.env` плейсхолдеры. Без них оплата не работает в проде. Вставить реальные ключи и протестировать webhook.
- ✅ **Alembic миграция** — полная Alembic-цепочка, 6 миграций, head: b2c3d4e5f6a7.
- 🟡 **Webhook для web_matrix** — `process_webhook()` ветка `web_matrix` написана, но не протестирована end-to-end.

### Продукт — PWA (новые задачи из ADR-001)
- 🔴 **manifest.json + Service Worker** — не существуют. Блокируют установку PWA. (~6ч)
- 🔴 **Install UI** — iOS-инструкция (GIF) + Android auto-prompt. (~4ч)
- 🔴 **Web Push бэкенд** — VAPID ключи, `/api/push/subscribe`, `has_pwa_push` в БД. (~6ч)
- 🔴 **Дедупликация уведомлений** — `has_pwa_push` флаг в Celery `send_daily_card`. (~3ч)
- ✅ **has_pwa_push, push_endpoint, push_p256dh, push_auth** — миграция a1b2c3d4e5f6, поля в моделях.
- ✅ **web_session_id, email в users** — миграция 5a8cac04bf5e.
- ✅ **has_matrix, has_tarot, compatibility_used** — миграция b3c1d2e4f5a6.
- ✅ **open_pwa кнопка в боте** — onboarding, payment, главное меню.
- ✅ **Link-токен связка** — `/api/v1/web/link-telegram` + бот-хендлер `/start link_{TOKEN}`.
- ✅ **Реферальная система** — таблица referral_rewards, `/start ref_{id}`, уведомление реферера, ссылка в профиле.
- 🟡 **PWA экраны** — таро, чат, профиль как мобильное приложение. (~40ч)
- 🟡 **Подписка 390₽ через веб** — `POST /api/v1/web/subscribe`. (~4ч)

### Продукт — Telegram-бот
- ✅ **Реферальная система** — `/start ref_{id}`, referral_rewards, уведомление реферера, реф-ссылка в профиле.
- 🟡 **Виральные механики — карточка-картинка (Pillow) для share** — ограниченная видимость, share-совместимость. (Спринт 1)
- 🟡 **Kitchen UI в боте** — кнопка «🔍 Показать расчёт». (~2ч)
- 🟡 **Kitchen UI в отчёте** — аккордеон «Почему я так думаю?». (~3ч)
- 🟡 **Заглушки таро-раскладов** — weekly, doubles, portal, yes/no требуют финального тестирования.

### Документация (обновление из Сессии 18)
- ✅ **`docs/platform-strategy.md`** — создан (ADR-001/002/003, роли платформ, пути пользователя)
- ✅ **`docs/pwa-spec.md`** — создан (manifest, SW, Web Push, install UI, экраны /app/*)
- ✅ **`docs/bot-spec-pwa-patch.md`** — создан (патч: §1.0, §16, deep-link, link-токен, новые callbacks)
- ✅ **`docs/launch-checklist.md`** — переписан (YooKassa блокер, PWA P0/P1, статусы, ~206ч общий итог)
- ✅ **`docs/README.md`** — обновлён (новые документы, карта зависимостей, приоритеты источников)
- 🟡 **`docs/tarot-integration-plan.md`** — нужно добавить раздел «Таро в PWA» (следующая сессия)

### Технический долг
- 🟡 Celery result backend — Redis reconnect warning
- 🟡 PDF совместимости — сейчас для всех типов, ограничить до романтики для подписчиков
- 🟡 send_daily_card — батчинг при росте базы (кэш по архетипу)
- 💭 PEXELS_API_KEY — не добавлен, стоки загружаются вручную

---

## 🔴 Известные блокеры

| Блокер | Статус | Комментарий |
|--------|--------|-------------|
| Telegram Bot Token | ✅ Снят | В .env стоит рабочий, не менять |
| DeepSeek API Key | ✅ Снят | В .env стоит рабочий, не менять |
| Отчёт совместимости | ✅ Снят | V2 готов (Сессия 17) |
| YooKassa credentials | 🔴 Активен | shop_id и secret_key — плейсхолдеры |
| Alembic миграция | ✅ Снят | полная Alembic-цепочка, 6 миграций, head: b2c3d4e5f6a7 |

---

## ⚡ Video Assembler — Quick Start for Agent

```
Команды:
  python scripts/assemble.py scenarios/example.json
  python scripts/from_plan.py plan.csv --video videos/media/TH_001.mp4
  python scripts/from_plan.py plan.csv --video videos/media/TH_001.mp4 --search-stock

Файлы:
  core/services/video_assembler.py   — ядро (Pydantic модели + FFmpeg filter_complex)
  core/services/stock_media.py       — стоки
  scripts/from_plan.py               — CSV → JSON парсер
  scripts/assemble.py                — CLI сборка из JSON
  videos/media/                      — исходники
  videos/output/                     — готовые MP4 + SRT

Ограничения:
  ! PEXELS_API_KEY нет в .env
  ! Музыка не реализована
  ! Интеграция с ботом не прикручена
```

---

## 🖥 VPS

```
SSH: root@45.144.178.118
Key: C:\Users\Bayzel\.ssh\id_ed25519_astro
Project: /opt/nura/
Code: /opt/nura/nura_app/
Landing: /var/www/nura-ai.ru/index.html
```

### Docker контейнеры

| Контейнер | Роль |
|-----------|------|
| `nura_app-bot-1` | Telegram бот (aiogram, polling) |
| `nura_app-api-1` | FastAPI (вебхуки, отчёты, web API) |
| `nura_app-celery-worker-1` | Celery worker |
| `nura_app-celery-beat-1` | Celery beat (карта дня, проверка подписок) |
| `nura_app-postgres-1` | PostgreSQL 16 |
| `nura_app-redis-1` | Redis (FSM + Celery) |

### Deploy commands

```bash
ssh -i C:\Users\Bayzel\.ssh\id_ed25519_astro root@45.144.178.118
cd /opt/nura && git pull origin master && cd nura_app && docker compose up -d --build
docker logs nura_app-bot-1 --tail 50
docker compose restart bot celery-worker
```

---

## 📋 Планы доработки (актуальные)

| Документ | Что | Часы | Статус |
|----------|-----|------|--------|
| `docs/platform-strategy.md` | Стратегия платформ, ADRs, пути пользователя | — | ✅ Готов |
| `docs/pwa-spec.md` | Техническая спецификация PWA | — | ✅ Готов |
| `docs/bot-spec-pwa-patch.md` | Патч бота под PWA-архитектуру | — | ✅ Готов |
| `docs/launch-checklist.md` | Актуальный план задач, ~206ч | — | ✅ Обновлён |
| `docs/README.md` | Индекс документации | — | ✅ Обновлён |
| `docs/tarot-integration-plan.md` | Добавить раздел «Таро в PWA» | — | 🟡 Следующая сессия |
| `docs/report-upgrade-sessions.md` | Страница отчёта: 16 шагов | 81 | 📝 В работе (шаги 1-7 частично) |
| PWA P0 (manifest + SW + push) | Техническая основа PWA | 22 | 🔴 Не начато |
| Виральные механики (Спринт 1) | Карточка + реферальная ссылка | ~3 дня | 🟡 Частично (рефералка готова, карточка — нет) |

### Ключевые продуктовые решения (зафиксированы)

- **Матрица судьбы** — разовый продукт, **890 ₽**, доступ навсегда
- **Таро-ритуалы** — подписка, **390 ₽/мес**, ядро удержания
- **PWA = ядро** — основной интерфейс, независим от Telegram (ADR-001)
- **Telegram = воронка + fallback** — привлечение, share, push для тех кто не установил PWA
- **Оплата** — только через веб (YooKassa redirect), бот отправляет только ссылку
- **Трафик из соцсетей** — всегда на `nura-ai.ru`, никогда напрямую в бота
- **Двухслойная архитектура**: User Layer + Kitchen Layer (бэкенд готов, фронтенд — нет)
- **Дедупликация уведомлений** — `has_pwa_push` флаг, один канал на пользователя (ADR-002)
- **Связка PWA ↔ Telegram** — через link-токен, добровольно, три точки входа (ADR-003)

---

## 📖 Protocol: End of Session

Когда агент завершает работу — обновить этот файл.

### Что обновляет агент
1. **Current** — отметить сделанное (✅), обновить незакрытые (🟡/🔴)
2. **Known blockers** — если появились или решились
3. **Architecture decisions** — если принял новое ADR
4. **История сессий** — добавить запись

---

## 📅 История сессий (хронология)

- **24.05.2026 — Сессия 7** — DeepSeek V4 Pro
  - Стратегический бенчмарк: парсинг 8 конкурентов + 956 отзывов → `docs/benchmark-competitors.md`
  - Зафиксирована продуктовая модель: матрица 890₽ (разово) + таро-ритуалы 390₽/мес (подписка)
  - Стратегия симбиоза Матрицы и Таро → `docs/tarot-integration-plan.md`
  - Launch checklist → `docs/launch-checklist.md`. Общий объём работ: ~161.5 часов

- **26.05.2026 — Сессия 8** — DeepSeek V4 Pro
  - Исправление навигации бота: `has_tarot` во все хендлеры, обработчик `buy_tarot_subscription`
  - Таро-статус в профиле: `profile_tarot_text`, ветка в `profile_keyboard`

- **26.05.2026 — Сессия 9** — DeepSeek V4 Pro
  - Фикс пустого отчёта + PDF: диспетчеризация MINI/FULL/FALLBACK, httpx timeout 300с
  - V2 шаблон: `@media print`, печатное оглавление с якорями

- **26.05.2026 — Сессия 10** — DeepSeek V4 Pro
  - Промпт `full_report.txt`: строгий 7-дневный формат, `archetype_name` + `archetype_key`
  - `parse_recommendations()`: переписан с fallback; дашборд увеличен

- **26.05.2026 — Сессия 11** — Claude Sonnet 4.6 (claude.ai)
  - Аудит и синхронизация документации: `bot-spec.md`, `report-spec.md` V2, `tone-of-voice.md`
  - Диспетчер: `render_report_v2_html` → `render_report_html` (модульная архитектура)
  - `STATE.md` перенесён в корень проекта

- **27.05.2026 — Сессия 12** — Claude Sonnet 4.6 (claude.ai)
  - Реализован полный handler раздела Таро: `tarot_state.py`, `tarot_keyboard.py`, `tarot.py` (11 handlers)
  - `settings.test_mode` bypass во всех 6 paywall-проверках

- **27.05.2026 — Сессия 13** — Claude Sonnet 4.6 (claude.ai)
  - `send_daily_insights` → `send_daily_card`: рефакторинг Celery, все активные пользователи
  - Расписание: `crontab(hour=3)` (06:00 МСК = 03:00 UTC)

- **27.05.2026 — Сессия 14** — Claude Sonnet 4.6 (claude.ai)
  - Совместимость — не отдельный платный продукт, benefit тарифов
  - `pricing.md` обновлён: 1 расклад в матрице, безлимит в таро
  - `bot-spec.md` §4: 4 сценария доступа, кнопка «📤 Отправить другу»
  - `core/models.py`: поля `has_tarot`, `has_matrix`, `compatibility_used`

- **28.05.2026 — Сессия 15** — Claude Sonnet 4.6 (claude.ai)
  - UX-рефакторинг бота: кнопка «💎 Купить разбор 890₽», `manage_subscription`, `show_support`
  - «Мои отчёты» и «Чат с NURA» вынесены в главное меню

- **28.05.2026 — Сессия 16** — DeepSeek V4 Pro
  - Форматирование: `bot/utils/formatting.py`, все таро-хендлеры → `format_tarot_result`
  - 5 AI-промптов переписаны: запрет арканов, 3 абзаца, «Как использовать:»
  - Анимация загрузки: `bot/utils/loading.py`, контекстный менеджер `animated_loading`

- **28–29.05.2026 — Сессия 17** — DeepSeek V4 Pro + Claude Sonnet 4.6 (claude.ai)
  - Отчёт совместимости V2: новый промпт `compatibility_full.txt`, шаблон с именами, 6 секций
  - Персонализация карты дня: `_personal_arcana_number()`, `bot/utils/arcana.py`
  - Промпт `tarot_daily_card.txt`: личное обращение, учёт архетипа, без названий арканов
  - Синхронизация репозитория: SSH-remote восстановлен, мусорные файлы удалены

- **09.06.2026 — Сессия 18** — Claude Sonnet 4.6 (claude.ai)
  - **Стратегическое решение**: PWA как ядро продукта (ADR-001). Telegram = воронка + fallback.
  - **Три ADR зафиксированы**: ADR-001 (PWA как ядро), ADR-002 (дедупликация уведомлений `has_pwa_push`), ADR-003 (link-токен связка аккаунтов)
  - **Полное обновление документации сессии 18**:
    - ✅ Создан `docs/platform-strategy.md` — главный стратегический документ
    - ✅ Создан `docs/pwa-spec.md` — полная техническая спецификация PWA
    - ✅ Создан `docs/bot-spec-pwa-patch.md` — патч бота (§1.0, §16, deep-link, callbacks)
    - ✅ Переписан `docs/launch-checklist.md` — актуальные статусы, PWA P0/P1, ~206ч
    - ✅ Обновлён `docs/README.md` — карта зависимостей, новые документы
    - ✅ Обновлён `STATE.md` — ADRs, все статусы актуальны
   - **Создан `NURA_Platform_Architecture_v2.docx`** и **`NURA_Viral_Mechanics_v2.docx`** для внешнего использования

- **09.06.2026 — Сессия 19** — Claude Sonnet 4.6 (claude.ai)
  - Alembic: 4 PWA-поля (has_pwa_push, push_endpoint, push_p256dh, push_auth) — миграция a1b2c3d4e5f6
  - Аудит БД ↔ models.py: 22+7+8 колонок — полная синхронизация
  - open_pwa_keyboard() во всех ключевых хендлерах бота (онбординг, покупка, главное меню)
  - Link-токен механика: POST /generate-link-token + GET /check-link-token + /start link_{TOKEN}
  - get_redis() синглтон в core/database.py
  - update_telegram_id() с защитой от конфликтов в UserRepository
  - Реферальная система: таблица referral_rewards, /start ref_{id}, уведомление реферера, реф-ссылка в профиле
  - Alembic цепочка: e47590a5c5c1 → add_tarot_and_payment_type → b3c1d2e4f5a6 → 5a8cac04bf5e → a1b2c3d4e5f6 → b2c3d4e5f6a7 (head)

- **09.06.2026 — Сессия 20** — Claude Sonnet 4.6 (claude.ai)
  - PWA P0 полностью закрыт:
  - manifest.json + 5 иконок (актуальные цвета #C9A55C, #0A0E0C)
  - service-worker.js (кэш + push handler + notificationclick)
  - offline.html (брендированный)
  - iOS meta-теги: index.html, mini.html, success.html, _base.html
  - nginx.conf: manifest/SW/icons/offline — без кэша, Service-Worker-Allowed: /
  - VAPID ключи сгенерированы, в .env
  - api/routes/push.py: subscribe / unsubscribe / vapid-public-key
  - core/services/web_push.py: отправка pywebpush, обработка 410
  - core/repositories/user.py: update_push_subscription, clear_push_subscription_by_endpoint
  - core/tasks.py: _notify_user — дедупликация Web Push → Telegram fallback (ADR-002)
  - pwa-install.js: Android beforeinstallprompt баннер + iOS 3-шаговая инструкция
  - Install UI внедрён в index.html и mini.html
  - pwa-spec.md обновлён: актуальная палитра, статусы §2, чеклист §13
  - Git remote переведён на SSH: git@github.com:usoltvas870/NURA.git

- **09.06.2026 — Сессия 21** — Claude Sonnet 4.6 (claude.ai)
  - Лендинг P0 закрыт (Блок 2):
  - Nav CTA: «Открыть бот» → «Открыть NURA» → /app
  - Hero CTA 2: «Через Telegram» → «🌐 Открыть NURA» → /app, убран opacity
  - Hero hint: «мини-разбор бесплатно · без регистрации»
  - 15 ссылок t.me/ai_nura_bot → /app (0 ссылок на бот осталось)
  - #report-sample: добавлены CTA кнопки ✨ + 🌐
  - target="_blank" убран у всех /app кнопок
  - Футер: текст ссылки приведён в соответствие с href
  - index.html синхронизирован /var/www/ ↔ /opt/nura/ ↔ git
