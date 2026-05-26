# NURA — State

## 📋 Планы доработки (май 2026)

В результате стратегического бенчмарка (8 конкурентов, 956 отзывов) разработаны 3 документа:

| Документ | Что | Часы | Статус |
|----------|-----|------|--------|
| `benchmark-competitors.md` | Стратегия: рынок, gap-анализ, цены, таро-стратегия, глоссарий | — | ✅ Готов |
| `report-upgrade-sessions.md` | **Только страница отчёта**: 16 шагов реализации | 81 | 📝 План |
| `tarot-integration-plan.md` | Таро на всех поверхностях: лендинг, бот, промпты, БД | 40 | 📝 План |
| `launch-checklist.md` | Всё, что не покрыто планами: лендинг, миграция, бот, тесты, деплой | 40.5 | 📝 План |
| `pricing.md` | Обновлённая модель: матрица 890₽ разово + таро-подписка 390₽/мес | — | ✅ Готов |

### Ключевые продуктовые решения (зафиксированы)

- **Матрица судьбы** — разовый продукт, **890 ₽**, доступ навсегда
- **Таро-ритуалы** — подписка, **390 ₽/мес**, ядро удержания
- **Двухслойная архитектура**: User Layer + Kitchen Layer (бэкенд готов, фронтенд — нет)
- **Три поверхности**: лендинг (nura-ai.ru) → бот (Telegram) → страница отчёта (HTML/PDF)
- **Два визуальных скина**: матрица (чёрно-зелёный) + таро (сине-золотой)
- **Tone-of-voice**: два режима — психологический (матрица) + ритуальный (таро)

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
- ✅ Database — PostgreSQL 16, таблицы users, reports, payments
- ✅ Redis — кэш, брокер Celery
- ✅ Celery worker/beat — запущены
- ✅ Nginx — прокси, SSL, /webhook/, /report/, /api/
- ✅ Полный AI-отчёт — генерация (9 полей), триггер от YooKassa webhook
- ✅ Kitchen-слой — бэкенд: AI-генерация (12 полей), хранение в БД (JSONB), API /report/{token}/kitchen
- ✅ Совместимость — ручной ввод дат, мини-разбор (2-3 блока)
- ✅ Ежедневные инсайты — Celery-beat задача send_daily_insights
- ✅ Чат с NURA — FSM, лимит 5 сообщений для free, безлимит для premium
- ✅ Подписка 390₽/мес — YooKassa recurrent, Celery downgrade/check
- ✅ Регистрация пользователя при /start — UserRegistrationMiddleware
- ✅ Carousel Assembler — Pydantic схемы, HTML-шаблоны, сервис, CLI, Celery-задача, тесты
- ✅ Video Assembler — FFmpeg бэкенд, CLI, Celery-задача, GPU autodetect
- 🟡 Платежи YooKassa — рекуррентные работают, разовые платежи (матрица 890₽) не реализованы
- 🟡 Kitchen-слой — фронтенд не реализован (ни в HTML-отчёте, ни в боте)
- 🟡 Видео-сборщик — интеграция с ботом не прикручена
- ✅ Full AI report V2 — дизайн деплоед, AI-текст во всех 15 секциях, @media print для PDF
- ✅ Навигация по отчёту — сайдбар + мобильное меню + печатное оглавление с якорями (#s1–#s15, #r1, #r2)
- ✅ PDF-генерация — WeasyPrint с @media print (светлая тема, системные шрифты, A4, page-breaks)
- ✅ Диспетчеризация рендеринга — API различает MINI/FULL/COMPATIBILITY отчёты по report_type
- ✅ Detector FALLBACK_FULL — при отсутствии реального AI-анализа отдаётся 202 «отчёт готовится»
- 🟡 Страница отчёта — план апгрейда (16 шагов) частично выполнен: V2 шаблон, печатный CSS, TOC, диспетчеризация типов
- ❌ Alembic миграции — не созданы

## Известные блокеры
- 🔴 Нужен реальный Telegram Bot Token (в .env стоит рабочий, не менять без необходимости)
- 🔴 Нужен DeepSeek API Key (в .env стоит рабочий, не менять без необходимости)
- 🔴 Страница отчёта — частично выполнена: V2 шаблон, печатный CSS, TOC. Остались: kitchen frontend, psychological_blocks/health_analysis секции
- 🔴 Таро-ритуалы не реализованы (40ч) — без этого подписка не удержит пользователей
- 🟡 Настроить Celery result backend — Redis reconnect warning
- 🟡 Alembic первая миграция (сейчас таблицы создаются через init_db.py)
- 🟡 PEXELS_API_KEY не добавлен в .env — автопоиск стоков не работает
- 🟡 YooKassa — разовые платежи не реализованы (нужно для матрицы 890₽)
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
- **26.05.2026 — Сессия 9** — DeepSeek V4 Pro
- Фикс пустого отчёта + PDF:
  - API: диспетчеризация рендеринга по `report_type` (MINI→mini_report.html, FULL→V2, FALLBACK→202)
  - `_is_fallback_analysis()`: детект FALLBACK_FULL по маркерам
  - `FullReportResult`: убраны min_length/max_length (слишком строгие)
  - `KitchenReportResult.psychological_blocks`/`health_analysis`: стали опциональными
  - `httpx timeout`: увеличен до 300с для full/kitchen/compat (было 30с → ReadTimeout на 32K токенах)
  - V2 шаблон: комплексный `@media print` (светлая тема, A4, page-breaks, системные шрифты)
  - Печатное оглавление с якорными ссылками на 17 секций
  - Удалены старые PDF/HTML кэши, сгенерирован новый FULL-отчёт с реальным AI-текстом
- **26.05.2026 — Сессия 8** — DeepSeek V4 Pro
- Исправление навигации бота NURA:
  - Удалён пустой `bot/handlers/matrix.py` (роутер без хендлеров) → убран из `bot/main.py`
  - `has_tarot` передаётся в `main_menu_keyboard()` из `start.py`, `onboarding.py`, `payment.py`
  - Добавлен обработчик `buy_tarot_subscription` в `payment.py` (тест-режим + боевой через `PaymentService.create_subscription`)
  - Таро-статус в профиле: новый блок `profile_tarot_text`, ветка в `profile_keyboard`, проверка в `_show_profile`
- **24.05.2026 — Сессия 7** — DeepSeek V4 Pro
- Стратегический бенчмарк: парсинг 8 конкурентов + 956 отзывов → `docs/benchmark-competitors.md`
- Зафиксирована продуктовая модель: матрица 890₽ (разово) + таро-ритуалы 390₽/мес (подписка)
- Глоссарий: лендинг / бот / страница отчёта / User Layer / Kitchen Layer
- Стратегия симбиоза Матрицы и Таро → `docs/tarot-integration-plan.md`
- План апгрейда страницы отчёта: 10 шагов → 16 шагов → `docs/report-upgrade-sessions.md`
- Launch checklist: 40.5ч доделок вне основных планов → `docs/launch-checklist.md`
- Обновлён `docs/pricing.md`, `docs/STATE.md`
- Общий объём работ: ~161.5 часов
