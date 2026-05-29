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
- ✅ Совместимость — лимитная модель: 1 расклад с Матрицей (has_matrix), безлимит с Таро ИЛИ premium; виральный share после расклада
- ✅ Ежедневные уведомления — Celery-beat задача send_daily_card (06:00 МСК, все активные пользователи)
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
- 🟡 Alembic миграции — не созданы (нужна миграция: has_matrix, has_tarot, compatibility_used в users)
- ✅ UX-рефакторинг бота (Сессия 15) — логика меню, доступ к совместимости, меню таро
- ✅ Отчёт совместимости V2 — новый шаблон, имена вместо арканов, 6 секций, технический слой скрыт
- ✅ Персонализация карты дня — уникальная карта для каждого пользователя на основе его матрицы
- ✅ bot/utils/arcana.py — утилиты вынесены в отдельный модуль

## Известные блокеры
- ✅ Отчёт совместимости — переработан в сессии 17 (V2)
- 🔴 Нужен реальный Telegram Bot Token (в .env стоит рабочий, не менять без необходимости)
- 🔴 Нужен DeepSeek API Key (в .env стоит рабочий, не менять без необходимости)
- ✅ Страница отчёта — `psychological_blocks` и `health_analysis` подключены, диспетчер переключён на модульный `full_report.html`
- 🟡 Таро-ритуалы — структура бота готова (menu, paywall, FSM), AI-промпты переписаны (запрет арканов, 3 абзаца, «Как использовать:»), анимация загрузки 🃏, HTML-форматирование
- 🟡 Настроить Celery result backend — Redis reconnect warning
- 🟡 Alembic первая миграция (сейчас таблицы создаются через init_db.py)
- 🟡 PEXELS_API_KEY не добавлен в .env — автопоиск стоков не работает
- 🟡 YooKassa — разовые платежи не реализованы (нужно для матрицы 890₽)
- 💭 YooKassa — shop_id и secret_key не настроены (в .env плейсхолдеры)
- 🟡 PDF совместимости — генерируется для всех типов отношений, в будущем ограничить PDF только романтикой для подписчиков
- 🟡 Карта дня в шедулере — генерация для всех пользователей одновременно может создать нагрузку на AI при росте базы; рассмотреть батчинг или кэширование по архетипу

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

### История сессий (хронология)

- **24.05.2026 — Сессия 7** — DeepSeek V4 Pro
  - Стратегический бенчмарк: парсинг 8 конкурентов + 956 отзывов → `docs/benchmark-competitors.md`
  - Зафиксирована продуктовая модель: матрица 890₽ (разово) + таро-ритуалы 390₽/мес (подписка)
  - Стратегия симбиоза Матрицы и Таро → `docs/tarot-integration-plan.md`
  - Launch checklist → `docs/launch-checklist.md`. Общий объём работ: ~161.5 часов

- **26.05.2026 — Сессия 8** — DeepSeek V4 Pro
  - Исправление навигации бота NURA
  - Удалён пустой `bot/handlers/matrix.py` → убран из `bot/main.py`
  - `has_tarot` передаётся в `main_menu_keyboard()` из `start.py`, `onboarding.py`, `payment.py`
  - Добавлен обработчик `buy_tarot_subscription` в `payment.py`
  - Таро-статус в профиле: `profile_tarot_text`, ветка в `profile_keyboard`

- **26.05.2026 — Сессия 9** — DeepSeek V4 Pro
  - Фикс пустого отчёта + PDF
  - API: диспетчеризация по `report_type` (MINI/FULL/FALLBACK→202)
  - `_is_fallback_analysis()`: детект FALLBACK_FULL по маркерам
  - `httpx timeout`: увеличен до 300с (было 30с → ReadTimeout на 32K токенах)
  - V2 шаблон: `@media print`, печатное оглавление с якорями на 17 секций

- **26.05.2026 — Сессия 10** — DeepSeek V4 Pro
  - Точечные улучшения отчёта
  - Промпт `full_report.txt`: строгий 7-дневный формат, `archetype_name` + `archetype_key`
  - `parse_recommendations()`: переписан, fallback если 0 элементов
  - `_dashboard.html` + `_styles.html`: увеличен дашборд (font-size, описания, min-height)
  - `render_report_html`: `archetype_key`, `year_arcana_name`, `current_year` в контекст

- **26.05.2026 — Сессия 11** — Claude Sonnet 4.6 (claude.ai)
  - Аудит и синхронизация документации
  - `bot-spec.md` + `bot-ux-map.md`: 🔮→◈ (8 вхождений), ценовая модель 890₽/390₽ (16 CTA)
  - `bot-ux-map.md`: флоу совместимости — убраны 2 лишних экрана, оставлен 1 ввод даты
  - `tone-of-voice.md`: добавлен §10 Исключения, исключение для «чакры» в `health_analysis`
  - `report-spec.md`: переписан с нуля под V2 (17 секций ✅, 5 📋)
  - `_psychological_blocks.html`: подключён к `full_report.html`
  - `_health_map.html`: эмодзи приведены к разрешённому списку tone-of-voice
  - Диспетчер: `render_report_v2_html` → `render_report_html` (модульная архитектура)
  - `STATE.md`: перенесён в корень проекта, хронология сессий исправлена
  - `README.md`: переписан под реальную структуру `docs/`

- **27.05.2026 — Сессия 12** — Claude Sonnet 4.6 (claude.ai)
  - Реализован полный handler раздела Таро (bot-spec §5)
  - `tarot_state.py`: `waiting_question` → `waiting_for_question`, добавлен `waiting_for_sphere`
  - `tarot_keyboard.py`: `tarot_menu_keyboard(has_tarot)` с двумя режимами (free: замки + CTA / subscribed: все расклады), новые `tarot_back_keyboard`, `tarot_paywall_keyboard`, `tarot_spheres_keyboard`
  - `tarot.py`: 11 handlers — `tarot_menu`, `tarot_daily_card` (free, алгоритм по дате), `tarot_weekly/question/spheres/twins/portal/yes_no` (paywall или заглушка), `tarot_sphere_*`, `handle_question_input` (FSM)
  - `settings.test_mode` bypass во всех 6 paywall-проверках
  - `core/tasks.py`: callback `tarot_weekly_spread` → `tarot_weekly` в Celery daily card

- **27.05.2026 — Сессия 13** — Claude Sonnet 4.6 (claude.ai)
  - `send_daily_insights` → `send_daily_card`: переименование + рефакторинг Celery-задачи
  - Фильтр пользователей: `premium` → все активные (`subscription_status != "blocked"`)
  - Текст: статичное уведомление «🌒 Твоя карта дня готова», кнопка [🌒 Получить карту] → `tarot_daily_card`
  - Расписание: `crontab(hour=9)` → `crontab(hour=3)` (06:00 МСК = 03:00 UTC)
  - Удалена AI-генерация инсайтов и импорт `INSIGHTS_BY_ARCHETYPE`
  - Обновлены: `tests/test_tasks.py` (импорт + 2 вызова), `integrity_check.py`

- **27.05.2026 — Сессия 14** — Claude Sonnet 4.6 (claude.ai)
  - Продуктовое решение: совместимость — не отдельный платный продукт, benefit тарифов
  - `docs/pricing.md`: «1 расклад совместимости» в Матрицу, «безлимит» в Таро; §3 «Логика совместимости»
  - `docs/bot-spec.md`: §4 переписан (убран пейволл 890₽, 4 сценария доступа); кнопка «📤 Отправить другу» (Telegram share); `generate_compat_share_text()`; §17 «Виральные механики»; совместимость в §9.2/9.3; `pay_compatibility` удалён
  - `docs/bot-ux-map.md`: Путь 5 — 4 ветки по флагам has_matrix/compatibility_used/has_tarot
  - `docs/tarot-integration-plan.md`: §9 «Виральная механика — Отправить другу», совместимость в пейволл
  - `nura_app/core/models.py`: поля `has_tarot`, `has_matrix`, `compatibility_used: bool` в модель User
  - `nura_app/init_db.py`: deprecation-комментарий (используй alembic)

- **28.05.2026 — Сессия 15** — Claude Sonnet 4.6 (claude.ai)
  - Продуктовый рефакторинг UX бота по результатам аудита
  - **1.1** `bot/keyboards/main_menu.py`: кнопка «💎 Купить разбор 890₽» скрывается при `has_matrix=True` ИЛИ `subscription_status=premium`; убран устаревший параметр `purchased_matrix` (backward-compat alias); `bot/handlers/start.py` и `onboarding.py` — передают `subscription_status` вместо `purchased_matrix`
  - **1.2** `bot/handlers/compatibility.py`: добавлена вспомогательная функция `_has_unlimited_compat()` — `subscription_status=premium` теперь даёт безлимит наравне с `has_tarot=True`; убраны упоминания цены у подписчиков
  - **1.3** `bot/handlers/onboarding.py` (`show_my_matrix`): если `has_matrix=True` и есть FULL-отчёт → показывает кнопки «📄 Открыть отчёт» + «⬇️ Скачать PDF» прямо на экране матрицы; убрана кнопка «Получить полный разбор по подписке», заменена на «💎 Купить матрицу — 890 ₽»
  - **2.1** `bot/texts/chat.py`: удалена строка `«Чтобы выйти, напиши /exit или нажми кнопку ниже»` из `greeting_text_free` и `greeting_text_unlimited`
  - **2.2** `bot/keyboards/tarot_keyboard.py`: новая структура меню — Деньги/Отношения/Предназначение вынесены на верхний уровень; добавлена кнопка «✨ Ещё расклады →» (callback `tarot_more`); новая функция `tarot_more_keyboard()` с Расклад недели / Сферы / Теневые стороны / Энергия месяца; `bot/handlers/tarot.py`: добавлены handlers `tarot_money/relations/purpose` (с обратной совместимостью `tarot_sphere_*`), `tarot_more`, переименования «Двойники» → «Теневые стороны», «Портал месяца» → «Энергия месяца»
   - **2.3** `bot/texts/profile.py` + `bot/handlers/profile.py`: все функции текста профиля принимают `birth_date` и отображают «📅 Дата рождения: ...»; кнопка «💬 Чат с NURA» удалена из `profile_keyboard` (доступна через главное меню)

- **28.05.2026 — Сессия 16** — DeepSeek V4 Pro
  - Рефакторинг профиля → личный кабинет
  - `core/config.py`: новое поле `support_username: str = "@nura_support"`
  - `bot/keyboards/main_menu.py`:
    - `main_menu_keyboard`: «📄 Мои отчёты» + «👤 Профиль» в одной строке; «📄 Пример отчёта» убран
    - `profile_keyboard`: полностью переписан — 3 состояния (нет матрицы / есть матрица / подписчик), кнопки «Управление подпиской», «Поддержка», «В меню»; убран параметр `has_full_report`
  - `bot/handlers/profile.py`:
    - Обновлены вызовы `profile_keyboard` (убран `has_full_report`)
    - Новые хендлеры: `manage_subscription` (экран управления), `cancel_subscription_confirm` (подтверждение), `cancel_subscription_do` (флаг `cancelling`), `show_support` (ссылка на Telegram)
    - Добавлены импорты: `InlineKeyboardButton`, `InlineKeyboardMarkup`, `settings`, `User`
  - «Мои отчёты» и «Чат с NURA» вынесены в главное меню из профиля

- **28.05.2026 — Сессия 16 (задача 6)** — DeepSeek V4 Pro
  - Правила форматирования текстов бота + утилита `bot/utils/formatting.py`
  - Функции: `format_bot_text`, `format_tarot_result`, `format_compatibility_result`, `_split_into_paragraphs`
  - Все 6 таро-хендлеров переведены на `format_tarot_result` (жирный заголовок, разбивка на абзацы, курсив для карт)
  - 5 AI-промптов перезаписаны полностью (tarot_spheres/doubles/portal/question/yes_no):
    - Строгий запрет на названия арканов в тексте (только психологические качества)
    - Три абзаца с пустыми строками, первое предложение — ключевая мысль
    - Блок «Как использовать:» в конце каждого расклада
    - Запрещённые слова: энергия, вибрация, вселенная, карма, аркан, карта, таро
  - Системный промпт во всех 6 вызовах AIService.chat обновлён («психологический проводник, не называй арканы»)
  - Все 6 хендлеров используют `parse_mode="HTML"` для рендеринга `<b>`/`<i>` тегов

- **28.05.2026 — Сессия 16 (задача 6б)** — DeepSeek V4 Pro
  - Анимация загрузки: `bot/utils/loading.py` — контекстный менеджер `animated_loading`
  - Вращающиеся полукруги `◐ ◓ ◑ ◒` каждые 0.5 сек во время AI-генерации
  - 🃏 эмодзи карты вместо 🌒 луны в сообщениях загрузки
  - Все 6 раскладов: `async with animated_loading(...)` → try/except блок с re-indent

- **28.05.2026 — Сессия 17 (задача 1)** — DeepSeek V4 Pro
  - Compatibility report V2: имена вместо арканов в обложке, новый AI-промпт `compatibility_full.txt`, новый HTML-шаблон `compatibility_report.html`
  - `_process_compatibility_report()`: параметры `user_name`, `partner_name`, `relation_type` → передаются в AI и шаблон
  - `generate_compatibility_report.delay()`: добавлен `relation_type` в сигнатуру
  - Удалена функция `_notify_compatibility` — дублирующее уведомление убрано
  - `mini_compatibility_text()`: добавлен параметр `is_premium`, CTA-блок «Это только начало» скрыт для premium
  - `process_partner_date()`: кнопки «📄 Открыть отчёт» / «⬇️ Скачать PDF» первыми для premium; «✨ Подключить Таро» только для free

- **29.05.2026 — Сессия 17 (задача 2)** — DeepSeek V4 Pro
  - Подтверждение и синхронизация: все изменения задачи 1 уже были на удалённом репозитории
  - stash/pull/merge: разрешены конфликты в `tasks.py`, `compatibility.py`, `texts/compatibility.py`
  - Деплой на VPS: `docker compose restart bot celery-worker` — оба контейнера без ошибок

- **29.05.2026 — Сессия 17** — Claude Sonnet 4.6 (claude.ai)
  - **Отчёт совместимости V2** — полная переработка: новый промпт `compatibility_full.txt` (6 полей: portrait_user, portrait_partner, how_you_interact, tension_zones, pair_strengths, recommendation); имена людей вместо названий арканов; тип отношений влияет на формулировки; схема `CompatibilityFullResult` обновлена; FALLBACK обновлён под новые ключи
  - **Шаблон compatibility_report.html V2** — новый дизайн: обложка «Имя & Имя», 6 секций с именами в заголовках, рекомендация с золотой рамкой, скрытый `<details>` с техническим слоем
  - **tasks.py + ai.py** — generate_compatibility_report передаёт user_name, partner_name, relation_type во все слои
  - **Мини-текст совместимости в боте** — mini_compatibility_text переписана под новые поля, динамический лейбл по типу отношений
  - **Дублирующее уведомление** — удалён вызов _notify_compatibility из Celery-таски; цена 390 ₽ скрыта у premium-пользователей
  - **Персонализация карты дня** — добавлена функция _personal_arcana_number(today, center_arcana): формула (база_дня + аркан_центра_матрицы) → редукция 1-22; каждый пользователь получает уникальную карту дня
  - **tarot_daily_card.txt** — новый промпт: личное обращение по имени, учёт архетипа пользователя, 3 абзаца, конкретное действие, без названий арканов
  - **bot/utils/arcana.py** — создан модуль с arcana-утилитами (_daily_arcana_number, _personal_arcana_number) без циклических зависимостей; импортируется в tarot.py и tasks.py
  - **Синхронизация репозитория** — SSH-remote восстановлен, 7 мусорных файлов из корня nura_app/ удалены, все коммиты запушены на GitHub
