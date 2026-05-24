# NURA — State

## ⚡ Video Assembler — Quick Start for Agent

```
Команды:
  python scripts/assemble.py scenarios/example.json                    # сборка из JSON
  python scripts/from_plan.py plan.csv --video videos/media/TH_001.mp4  # сборка из CSV-плана
  python scripts/from_plan.py plan.csv --video videos/media/TH_001.mp4 --search-stock  # +B-roll auto

Файлы:
  core/services/video_assembler.py   — ядро (Pydantic модели + FFmpeg filter_complex)
  core/services/stock_media.py       — стоки: локальный матчинг по имени файла / Pexels API
  scripts/from_plan.py               — CSV → JSON парсер (форматы: Тип 1/2/3)
  scripts/assemble.py                — CLI сборка из готового JSON
  scenarios/*.json, *.csv            — сценарии
  videos/media/                      — исходники (TH_001.mp4, B-roll)
  videos/output/                     — готовые MP4 + SRT

Форматы (колонка B):
  Тип 1 — Говорящая голова + zoom/transition + PiP стоки (subs: auto Whisper)
  Тип 2 — Фон + текст/стихи, full-screen stock + text overlay (subs: off)
  Тип 3 — Пергамент + текст, как Тип 2 + тёплая color grading (subs: off)

Ограничения:
  ! PEXELS_API_KEY нет в .env — автопоиск стоков не работает
  ! Ютуб/Пиксель не работают в РФ — стоки загружает пользователь вручную
  ! Музыка не реализована
  ! Колонка J (Карусель) — парсится и генерируется через CarouselAssembler
  ! Интеграция с ботом не прикручена

Документация: docs/engineering/video-assembler.md
```

## Current
- ✅ Landing page — деплой, SSL, Яндекс.Метрика
- ✅ Telegram bot — запуск, поллинг, /start, мини-разбор через DeepSeek
- ✅ API — FastAPI, health endpoint, rate limiting, admin panel (sqladmin)
- ✅ Database — PostgreSQL 16, 3 таблицы (users, reports, payments)
- ✅ Redis — кэш, брокер Celery
- ✅ Celery worker/beat — запущены
- ✅ Nginx — прокси, SSL, /webhook/, /report/, /api/
- 🟡 Платежи YooKassa — API есть, бот-обработчик недоработан
- ✅ Полный AI-отчёт — генерация, триггер от YooKassa webhook
- 🟡 Видео-сборщик — FFmpeg бэкенд готов, CLI и Celery-задача есть, интеграция с ботом не прикручена
- ✅ Carousel Assembler — Pydantic схемы, HTML-шаблоны, сервис (Playwright), CLI, Celery-задача, AI-промпт парсинга колонки J, интеграция в from_plan.py, тесты
- ✅ Совместимость — ручной ввод дат, мини-разбор (2-3 блока), CTA на подписку/полный отчёт
- ✅ Ежедневные инсайты — Celery-beat задача send_daily_insights
- ✅ Чат с NURA — FSM, лимит 5 сообщений для free, безлимит для premium
- ✅ Подписка 390₽/мес — YooKassa recurrent, Celery downgrade/check
- ✅ Регистрация пользователя при /start — UserRegistrationMiddleware
- ❌ PDF-генерация — код есть (WeasyPrint), не протестирована
- ❌ Alembic миграции — не созданы

## Известные блокеры
- 🔴 Нужен реальный Telegram Bot Token (в .env стоит рабочий, не менять без необходимости)
- 🔴 Нужен DeepSeek API Key (в .env стоит рабочий, не менять без необходимости)
- 🟡 Настроить Celery result backend — Redis reconnect warning
- 🟡 Alembic первая миграция (сейчас таблицы создаются через init_db.py)
- 🟡 PEXELS_API_KEY не добавлен в .env — автопоиск стоков не работает
- 💭 YooKassa — shop_id и secret_key не настроены (в .env плейсхолдеры)

## Архитектурные решения (ADRs)
- **Async-first**: SQLAlchemy 2.0 async + asyncpg
- **AI через Celery**: генерация мини/полного отчёта в фоновых задачах
- **Nginx на хосте**: не в Docker, используется существующий nginx + Certbot SSL
- **API на 127.0.0.1:8000**: nginx проксирует /webhook/, /report/, /api/
- **Bot в polling mode**: без вебхука (проще для MVP)
- **Matrix of Destiny**: 22 аркана Таро как система психологических архетипов (не астрология)
- **Admin panel**: sqladmin на sync engine (порт 8000, /admin), отдельный от async-ядра
- **Video Assembler**: FFmpeg subprocess (не MoviePy), GPU autodetect, easing через filter_complex

## OpenCode окружение
- `.opencode/config.json` — model router (Flash/Pro/GLM), MCP (Playwright, Figma)
- `.opencode/agents/` — 41 агент (из Astro Insight, адаптируются под NURA)
- Playwright MCP ✅ для PDF-скриншотов
- Figma MCP ✅ для доступа к дизайнам

## Video Assembler (FFmpeg backend)
- **Сборка видео по JSON-сценарию** — FFmpeg subprocess, без MoviePy, GPU-ускорение (NVENC)
- **Файлы**:
  - `nura_app/core/services/video_assembler.py` — Pydantic-схемы + FFmpeg filter_complex + SRT + GPU detection
  - `scripts/assemble.py` — CLI `python scripts/assemble.py scenarios/foo.json`
  - `scripts/create_scenario.py` — интерактивный конструктор сценариев
  - `scenarios/template.json` — типовой шаблон сценария
- **Типы оверлеев**: text (drawtext), video/PiP (movie+overlay), image (movie+overlay), zoom (zoompan+easing)
- **Цветокоррекция**: colorbalance (R/G/B каналы для теней/средних/светов) + glow/bloom (split → gblur → blend screen) — per-scene
- **Транзишены**: xfade + acrossfade (~30 типов: dissolve, fade, slide, wipe, zoom, pixelize, hblur...)
- **Субтитры**: manual (чанки по 3s с adjustment под транзишены) / auto (faster-whisper)
- **Celery-задача**: `core.tasks.assemble_video` — асинхронная сборка
- **Фича: duration=0** — автоопределение длительности сцены как оставшаяся часть исходного видео
- **Выход**: `videos/output/{name}.mp4` + `{name}_subtitles.srt`
- **GPU fallback**: hevc_nvenc если доступен CUDA, иначе libx264
- **Документация**: `docs/engineering/video-assembler.md`
- **CSV-пайплайн**: `scripts/from_plan.py` — парсит Google Sheets CSV (колонки A-J), генерирует сценарий, ищет стоки (Pexels/Pixabay), собирает видео
- **Stock media**: `core/services/stock_media.py` — поиск и скачка B-roll по keywords
- **Цветокоррекция**: colorbalance + glow/bloom per-scene
 
## VPS
- `root@45.144.178.118`, ключ `C:\Users\Bayzel\.ssh\id_ed25519_astro`
- `/opt/nura/` — проект, `.env`, `docker-compose.yml`
- Landing: `/var/www/nura-ai.ru/index.html`

---

## Protocol: End of Session

Когда агент завершает работу — обновить этот файл.

### Что обновляет агент
1. **Current** — отметить сделанное, добавить/обновить статусы
2. **Known blockers** — если появились или решились
3. **Architecture decisions** — если принял новое ADR
4. **Последняя сессия** — кратко (1-3 строки): номер, модель, что сделано

### Последняя сессия
- **20.05.2026 — Сессия 5** — DeepSeek V4 Flash
- Финализация архитектуры:
  - Форматы: Тип 1 (говорящая голова), Тип 2 (фон+текст), Тип 3 (пергамент+текст) — dispatch по колонке B
  - Стоки: user upload → локальный матчинг по имени файла (primary), Pexels API (fallback)
  - Одна таблица на все форматы + карусель (колонка J)
- from_plan.py: _build_type1/2/3, _parse_carousel, _split_script_to_sentences
- stock_media.py: match_local_stock() — поиск B-roll среди загруженных пользователем файлов

- **22.05.2026 — Сессия 6** — DeepSeek V4 Flash
- Тесты Carousel Assembler (21 тест: схемы, рендеринг, сборка)
- Фикс пути TEMPLATE_DIR в carousel_assembler.py (nura_app/frontend/)
- Обновление STATE.md
- ruff check — 0 errors
