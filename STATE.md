# NURA — State

> Последнее обновление: **06.07.2026 — Сессия 79** — GPT-5 Codex

---

## Сессия 79 — 06.07.2026
- Модель: GPT-5 Codex
- Что сделано:
  - Проведён ручной browser QA-аудит живого пользовательского пути `https://nura-ai.ru`: лендинг → `mini.html` → `app/` → PWA-разделы `Главная`, `Таро`, `Чат`, `Профиль`, а также мобильный viewport `390x844`
  - Зафиксированы критические и high-severity разрывы в связке guest mini-report → PWA: мини-разбор генерируется, но не появляется в `reports`, а главный CTA `Открыть отчёт` уводит в `profile.html#subscription`
  - Выявлены реальные production-проблемы статики и ссылок: `personal-data-consent.html` и `marketing-consent.html` на домене отдают `404`, а прямой URL `https://nura-ai.ru/app/tarot` не открывается
  - Для плана исправлений дополнительно проверены фронтовые и backend-точки: `mini.html`, `frontend/pwa/app/index.html`, `frontend/pwa/app/profile.html`, `frontend/pwa/app/chat.html`, `frontend/pwa/app/tarot.html`, `frontend/pwa/app/nura-pwa.js`, `nura_app/api/routes/web.py`, `nura_app/core/services/auth.py`, `deploy.sh`
  - В корне репозитория сохранён отдельный подробный документ аудита: `NURA_SITE_QA_AUDIT_2026-07-06.md`
- Блокеры:
  - `graphify query`/`graphify update .` в этой среде по-прежнему не запускаются: локальный launcher ссылается на отсутствующий `C:\Users\Bayzel\AppData\Local\Programs\Python\Python311\python.exe`
- Следующие шаги:
  - Сначала починить критичный flow сохранения guest mini-report в PWA и убрать ложную навигацию `Открыть отчёт -> #subscription`
  - Затем синхронизировать production deploy статики: добавить в выкладку `mini.html`, `personal-data-consent.html`, `marketing-consent.html` и привести все ссылки на Таро к рабочему маршруту
  - После этого пройти повторный smoke QA на desktop и mobile с проверкой `reports`, `chat`, `telegram link`, legal pages и tabbar

---

## Сессия 77 — 04.07.2026
- Модель: GPT-5 Codex
- Что сделано:
  - `frontend/pwa/app/tarot.html`, `frontend/pwa/app/chat.html`, `frontend/pwa/app/profile.html`: убраны жёсткие редиректы `401 -> /mini.html` при обычной навигации по PWA; вместо этого добавлен мягкий guest fallback внутри экранов, чтобы tabbar не выбрасывал пользователя обратно на ввод данных
  - `frontend/pwa/app/nura-pwa.js`: вынесен общий auth modal для guest-доступа из PWA-экранов, с email magic link и ленивой загрузкой VK SDK для сохранения текущего auth flow
  - `mini.html`: мобильный burger перенесён из нижней панели в верхний левый fixed-control с safe-area; выпадающее меню перестроено в читаемый light drawer с контрастным overlay, улучшенными цветами и корректным z-index
  - `mini.html`: мобильный result topbar получил дополнительный левый отступ под новую кнопку меню, а нижняя панель оставлена только для prev/next-навигации по разделам мини-разбора
  - По коду дополнительно проверены остаточные точки `/mini.html` и `401`, чтобы мини-страница открывалась только по явным сценариям (мини-разбор, logout/delete fallback, отсутствие отчёта по явному действию)
- Блокеры:
  - `graphify update .` снова не выполнился: `graphify.exe` по-прежнему ссылается на отсутствующий `C:\Users\Bayzel\AppData\Local\Programs\Python\Python311\python.exe`
  - Локальный визуальный просмотр `mini.html` через встроенный browser skill не состоялся: `file://` был заблокирован URL policy встроенного браузера
- Следующие шаги:
  - Проверить вручную в браузере mobile widths `360px`, `390px`, `430px`: открытие menu drawer, отсутствие horizontal scroll и корректную работу prev/next
  - Отдельно починить локальный launcher `graphify.exe`, затем повторить `graphify update .`

## Сессия 76 — 04.07.2026
- Модель: GPT-5 Codex
- Что сделано:
  - Созданы новые юридические страницы `personal-data-consent.html` и `marketing-consent.html` в визуальном стиле `privacy.html`, с единым блоком ссылок на юридические документы
  - `index.html`: в footer добавлены ссылки на оба новых согласия, а подпись ссылки на `privacy.html` приведена к формулировке «Политика обработки данных»
  - `contacts.html`: блок юридических документов расширен ссылками на `personal-data-consent.html` и `marketing-consent.html`
  - `mini.html`: обновлён текст обязательного чекбокса, теперь он ссылается на оферту, политику и согласие на обработку персональных данных без добавления отдельного маркетингового чекбокса
  - `frontend/pwa/app/profile.html`: в настройки аккуратно добавлены ссылки на согласие на обработку данных и согласие на рассылки
  - `offer.html` и `privacy.html`: добавлен компактный блок переходов на все юридические документы без изменения бизнес-логики страниц
  - Через in-app browser проверены `personal-data-consent.html`, `marketing-consent.html`, `offer.html` и `privacy.html`: страницы открываются корректно, содержат по одному `h1`, не имеют битых символов и не дают горизонтального переполнения на ширине `390px`
- Блокеры:
  - `graphify update .` не выполнился: launcher `graphify.exe` по-прежнему ссылается на отсутствующий `C:\Users\Bayzel\AppData\Local\Programs\Python\Python311\python.exe`
- Следующие шаги:
  - Починить локальную установку `graphify` и повторить `graphify update .`
  - При необходимости отдельным этапом добавить такие же legal-ссылки в новые будущие HTML-экраны, если они появятся вне текущих точек входа

## Сессия 75 — 04.07.2026
- Модель: GPT-5 Codex
- Что сделано:
  - `privacy.html`: полностью обновлена страница Политики обработки персональных данных по новой редакции от 04.07.2026, при этом сохранены текущие шрифты, карточка, контейнер, отступы и мобильная адаптация
  - Создан точный бэкап предыдущей версии страницы: `privacy.backup.html`
  - Проверены и подтверждены основные ссылки на `/privacy.html` в `index.html`, `contacts.html`, `offer.html`, `mini.html`, `frontend/pwa/app/profile.html`
  - `frontend/pwa/app/profile.html`: ссылка из раздела настроек теперь ведёт на `/privacy.html`; рядом с подпиской добавлена ссылка на Политику
  - `frontend/pwa/app/tarot.html` и `mini.html`: рядом с оплатой добавлена ссылка на Политику без изменения бизнес-логики и обязательных чекбоксов
  - Локально через in-app browser проверены `privacy.html` на desktop и mobile, отсутствие дубля H1, отсутствие битых символов и работоспособность перехода из PWA-профиля на `/privacy.html`
- Блокеры:
  - `graphify update .` не выполнился: launcher `graphify.exe` по-прежнему ссылается на отсутствующий `C:\Users\Bayzel\AppData\Local\Programs\Python\Python311\python.exe`
- Следующие шаги:
  - Починить локальную установку `graphify` и повторить `graphify update .`
  - При необходимости отдельным этапом согласовать отдельный обязательный чекбокс непосредственно перед платёжным редиректом

## Сессия 74 — 04.07.2026
- Модель: GPT-5 Codex
- Что сделано:
  - Выполнен audit-pass главной PWA `frontend/pwa/app/index.html` после редизайна: сохранены JS-хуки, guest/auth/blocked flow, загрузка статусов отчёта и подписки, ссылки bottom tabbar
  - `frontend/pwa/app/nura-pwa.css` расширен до общего UI-слоя: reusable shell/page, header, tabbar, card, secondary button alias, muted text, status pill, quick action card, empty state, soft accent helpers
  - Исправлены нижние отступы под fixed tabbar и safe-area; обновлён cache-bust для общего CSS на PWA-страницах
  - `frontend/pwa/app/tarot.html` переведён на спокойный light-card стиль без тяжёлых фоновых изображений, при этом сохранены существующие `id`, `onclick` и JS-функции раскладов/подписки
  - `frontend/pwa/app/chat.html` переведён в единый light premium chat-shell: убран image-heavy empty state, сохранены текущие `/web/me`, `/web/chat`, localStorage и send/retry hooks
  - `frontend/pwa/app/profile.html` приведён к той же дизайн-системе: светлый hero-блок, унифицированные карточки, сохранены Telegram link/unlink, подписка, отчёты, logout/delete account flows
  - `theme.css` дополнен токенами `--gold-ink` и `--danger`, чтобы убрать лишние hardcoded accent-цвета из PWA-слоя
- Блокеры:
  - `graphify update .` не выполнялся повторно: ранее зафиксирован сломанный launcher `graphify.exe`, привязанный к отсутствующему Python path
  - Live preview через localhost/in-app browser по-прежнему ограничен, поэтому проверка в этой сессии была статической по коду
- Следующие шаги:
  - Прогнать PWA вручную в реальном мобильном браузере на 360px / 390px / 430px и проверить визуальный ритм, safe-area и кликабельные зоны
  - При необходимости вынести оставшиеся page-specific inline-блоки (например auth/install modal styles) в общий PWA stylesheet

## Сессия 73 — 04.07.2026
- Модель: GPT-5 Codex
- Что сделано:
  - `offer.html`: текст публичной оферты заменён на расширенную редакцию из `Публичная оферта.docx`, опубликована редакция от 04.07.2026
  - Сохранены существующие шрифты, палитра, контейнер 680 px, навигация и карточка реквизитов; для мобильных экранов реквизиты перестраиваются в одну колонку
  - Создан точный бэкап прежней страницы `offer.backup.html`
  - Ссылки на `/offer.html` добавлены рядом с оплатой полного отчёта в `mini.html` и подписки в `frontend/pwa/app/profile.html`, `frontend/pwa/app/tarot.html`
  - Существующий чекбокс в `mini.html` теперь ссылается на `/privacy.html` и `/offer.html`; новая платёжная логика и новые обязательные чекбоксы не добавлялись
  - Текст HTML машинно сверен с DOCX; в браузере проверены desktop и mobile: 1 H1, 23 раздела, без горизонтального переполнения и битых символов
- Блокеры:
  - `graphify update .` не выполнен: launcher `graphify.exe` повреждён, а доступный Python 3.11 не содержит модуль `graphify`
- Следующие шаги:
  - Восстановить установку `graphify` и повторить `graphify update .`
  - При необходимости отдельным этапом согласовать обязательный чекбокс принятия оферты непосредственно перед платёжным редиректом

## Сессия 72 — 04.07.2026
- Модель: GPT-5 Codex
- Что сделано:
  - PWA home-screen: полностью пересобран `frontend/pwa/app/index.html` под светлый premium minimal без тяжёлых hero-изображений
  - Главная страница PWA теперь структурирована как стартовый экран-проводник: приветствие, главный фокус дня, быстрый доступ, блок матрицы, блок статуса
  - Сохранены существующие JS-хуки и бизнес-логика для `report-cta`, `greeting-name`, `status-copy`, `matrix-*`, `day-*`, guest/blocked/auth flow
  - `frontend/pwa/app/nura-pwa.css`: обновлены header/tabbar/page-spacing, чтобы PWA в целом выглядело более карточно и аккуратно на мобильных
  - Добавлен временный визуальный preview-файл `C:\tmp\nura-home-preview.html` для локальной проверки композиции вне backend-API
- Блокеры:
  - `graphify update .` не выполнился: локальный `graphify.exe` привязан к отсутствующему `C:\Users\Bayzel\AppData\Local\Programs\Python\Python311\python.exe`
  - Встроенный browser preview не смог открыть localhost-страницу, поэтому визуальная проверка через in-app browser осталась частично ограниченной
- Следующие шаги:
  - Починить локальную установку Python/graphify launcher и повторно выполнить `graphify update .`
  - Прогнать PWA home в реальном браузере на 360px / 390px / 430px и сверить кликабельные зоны
  - Распространить облегчённый стиль home-screen на `tarot.html`, `chat.html`, `profile.html`, если нужен единый light-app режим

## Сессия 71 — 04.07.2026
- Модель: DeepSeek V4 Flash
- Что сделано:
  - Лендинг: добавлена ссылка на публичную оферту `/offer.html` в подвал
  - Лендинг: добавлено cookie-уведомление (баннер) с сохранением согласия в localStorage

## Сессия 70 — 04.07.2026
- Модель: mimo-v2.5
- Что сделано:
  - **Recurring-задача для автопродления подписок:**
    - `core/repositories/user.py`: новый метод `get_users_for_recurring_charge()` — выбирает пользователей с `payment_method_id`, у которых подписка истекает в ближайшие 24ч
    - `core/services/payment.py`: новый метод `create_recurring_payment()` — создаёт платёж через YooKassa с сохранённым `payment_method_id`
    - `core/tasks.py`: новая задача `charge_recurring_subscriptions` — обрабатывает tarot и premium подписки, логирует результат, уведомляет админа при ошибках
    - Beat-schedule: задача запускается каждые 6 часов
  - **Исправлена цена подписки:**
    - `core/config.py`: удалён legacy-параметр `subscription_price_rub = 590` (не использовался корректно)
    - `core/services/payment.py`: `create_subscription()` теперь использует `tarot_subscription_price_rub` (390₽) вместо удалённого параметра (было 590₽, кнопка в боте показывала 390₽ — рассинхрон)
  - **Тесты:** все 30 тестов `test_payment.py` пройдены, ruff check без ошибок
- Блокеры: нет
- Следующие шаги:
  - Заполнить `YOKASSA_SHOP_ID` и `YOKASSA_SECRET_KEY` в `.env` на VPS
  - Заполнить `YOKASSA_IP_WHITELIST` (IP-адреса YooKassa)
  - Реализовать Pydantic-схемы для валидации входящих вебхуков
  - Добавить отправку подтверждения в TG для subscription/tarot платежей в `process_webhook()`

---

## Сессия 69 — 04.07.2026
- Модель: DeepSeek V4 Pro
- Что сделано:
  - **Мёртвый код `_build_retry_prompt` — активирован:**
    - `report_loop.py`: `_build_retry_prompt(issues)` — упрощённая сигнатура (только `issues: list[str]`), реально вызывается при retry
    - `ai.py`: `generate_full_report()` — новый параметр `issues: list[str] | None`. `_generate_part()` добавляет issues как retry-сообщение в messages
    - `generate_full_report_with_loop()`: на retry передаёт `result.issues` → AI получает обратную связь и исправляет конкретные проблемы
  - **tarot_loop exhausted → fallback:**
    - Исчерпание попыток возвращает `_FALLBACK_TAROT` (осмысленное сообщение), а не последний бракованный текст
    - Добавлено логирование issues при warning
  - **5 tarot bypass-ов закрыты:**
    - `ai.py`: `generate_tarot_daily_card()` переведён на `generate_tarot_text()` — автоматическая верификация (закрывает bypass 2 и 3 в tasks.py)
    - `tasks.py`: `send_weekly_tarot_spread` → `generate_tarot_text()` (закрыт bypass 4)
    - `tasks.py`: `send_monthly_tarot_portal` → `generate_tarot_text()` (закрыт bypass 5)
    - `bot/handlers/tarot.py`: `show_tarot_weekly` → пост-генерационная верификация через `ContentVerifier.verify_text()` для 4 текстовых полей (закрыт bypass 1)
  - **Тесты**: `test_tarot_pwa.py::TestAIServiceChatTrimming` — 3 теста обновлены: mock на `generate_tarot_text` вместо `AIService.chat`
  - **Проверка**: ruff — pass, pytest — 242 passed
- Блокеры: нет
- Следующие шаги: сквозная трассировка ошибок (Sentry + structured logs)

---

## Сессия 68 — 04.07.2026
- Модель: DeepSeek V4 Pro
- Что сделано:
  - **Chat history persistence в Redis**:
    - `bot/handlers/chat.py`: при входе — загрузка истории из Redis по ключу `chat:history:{telegram_id}`, при каждом сообщении — сохранение в Redis с TTL 7 дней, при очистке — удаление ключа. История ограничена 20 сообщениями.
    - `api/routes/web.py`: серверная история в Redis — приоритет над клиентской, сохранение после каждого ответа. Клиентская история используется как fallback если в Redis пусто.
  - **AI metrics — structured logging**:
    - `AIService.chat()`: параметр `method_name` (default "chat"), `time.perf_counter()` для замеров
    - Логирование `logger.info/error` с structured `extra`: method, model, prompt_tokens, completion_tokens, total_tokens, duration_ms, cached, status (success/fallback/failure/cached), attempt
    - Все 9 вызовов в `ai.py` передают уникальный `method_name`: mini_analysis, full_report_part_a/b, kitchen_report, compatibility, daily_insight, tarot_daily_card, tarot_weekly_spread, tarot_question, chat_response
    - Кэш-хиты логируются отдельно (status=cached, tokens=0)
  - **Circuit Breaker для full_report**:
    - `generate_full_report()`: замена параллельного `asyncio.gather` на последовательное выполнение
    - Если Part A падает с ошибкой → Part B не вызывается, сразу возвращается FALLBACK_FULL (экономия токенов)
    - Если Part A успешна → вызывается Part B, при ошибке Part B — частичный merge сохранённого Part A
    - `_generate_part()` принимает `part_label` для логирования
  - **Проверка**: ruff — pass, pytest — 242 passed
- Блокеры: нет
- Следующие шаги: tarot FSM → Redis, сквозная трассировка ошибок (Sentry + structured logs)

---

## Сессия 67 — 03.07.2026
- Модель: DeepSeek V4 Flash (opencode-go/deepseek-v4-flash)
- Что сделано:
  - **Удалён VideoPipeline и всё связанное с генерацией медиа** (видео + карусели):
    - Удалены сервисы: `video_pipeline.py`, `video_assembler.py`, `asset_validator.py`, `qa_checker.py`, `packager.py`, `carousel_assembler.py`
    - Удалены промпты: `video_scenario.txt`, `brief_parser.txt`, `carousel_parser.txt`
    - Удалены схемы: `core/schemas/brief.py`, `core/schemas/carousel.py`
    - Удалены тесты: `tests/test_carousel_assembler.py`
    - Удалены Celery-задачи: `assemble_video`, `assemble_video_job`, `assemble_carousel`, `assemble_carousel_job`
    - Почищены импорты в `core/__init__.py`, `core/schemas/__init__.py`
  - **Проверка**: lint — pass, tests — 315 passed, 4 xfailed
  - **Loop Engineering — Phase 0 + Phase 2 внедрены:**
    - **`core/services/verifier.py`** — SemanticVerifier: проверка длины, banned words, общих фраз, пустых полей, консистентности арканов, dashboard scores
    - **`core/loop_specs/`** — папка Loop Specification
    - **`core/loop_specs/report_loop.py`** — `generate_full_report_with_loop()`: Semantic Loop для full_report (Maker → ContentVerifier → retry до MAX_SEMANTIC_RETRIES=2)
    - **`AIService.chat()`** — опциональный Redis cache (`use_cache`, `cache_ttl`), `_cache_key()` на основе хеша сообщений
    - **`AIService._make_retry_callback()`** — фабрика retry-колбэка вместо 6 дублированных inline-определений (применена во всех 6 методах)
    - **`generate_full_report()`** — `asyncio.gather(return_exceptions=True)` + partial merge (если Part A падает, Part B сохраняется). Убран monolithic `try/except`
    - **`_process_full_report` в tasks.py** — использует `generate_full_report_with_loop` с semantic verification
    - **27 тестов** для ContentVerifier
  - **Проверка**: ruff — pass, pytest — 342 passed (+27 тестов), 4 xfailed
  - **Loop Engineering — Phase 4 частично + улучшения:**
    - **`check_name_in_text()` в ContentVerifier** — проверка обращения по имени в verify_text
    - **Degradation ladder в `AIService.chat()`** — Level 1 (3 retries, primary) → Level 2 (2 retries, low temp, max_tokens=500) → raise
    - **`generate_tarot_text()`** — параметр `user_name` для проверки имени
    - **`show_tarot_daily_card`** — передаёт user_name в generate_tarot_text
    - **Tarot fallback** — arcana-based сообщения вместо «Карты молчат»
    - **+6 тестов** для check_name_in_text
  - **Проверка:** ruff — pass, pytest — 348 passed, 4 xfailed
    - **Кэширование tarot (tasks.py):**
      - `DAILY_CARD_CACHE` — in-memory кэш `{(date, arcana)}` в `_send_daily_tarot_card_async`
      - `use_cache=True, cache_ttl=7*86400` в `_send_weekly_tarot_spread_async`
      - `use_cache=True, cache_ttl=31*86400` в `_send_monthly_tarot_portal_async`
    - **`core/loop_specs/tarot_loop.py`:** `generate_tarot_text()` — semantic loop для plain-text tarot (chat → ContentVerifier.verify_text → retry до 2 раз)
    - **`bot/handlers/tarot.py`:** 7 хендлеров переведены на `generate_tarot_text` (daily_card, spheres, twins, portal с кэшем, blocks, yes_no, question)
    - **`api/routes/tarot_pwa.py`:** 4 хендлера переведены на `generate_tarot_text` (life, doubles, portal с кэшем, yesno)
    - **Экономия токенов:** portal — 1 вызов/месяц вместо N, weekly — кэш по arcana_group, daily — 22 вызова/день вместо N
  - **Проверка:** ruff — pass, pytest — 342 passed, 4 xfailed
- Блокеры: нет
- Следующие шаги: Loop Engineering — Phase 1 (кэширование portal/weekly), Phase 3 (tarot plain-text loops)

---

## Сессия 66 — 02.07.2026
- Модель: DeepSeek V4 Flash (opencode-go/deepseek-v4-flash)
- Что сделано:
  - **Полная переработка VK-авторизации на официальный VK ID Web SDK**:
    - **Корневая причина**: VK деактивировал `id.vk.com/oauth2/token`, серверный обмен code→token невозможен. Использован официальный клиентский SDK с PKCE.
    - **mini.html**: `vkLogin()` заменён на VK ID SDK (`VKIDSDK`). PKCE через `crypto.getRandomValues()`, `SDK.Config.init()` + `SDK.Auth.login()`.
    - **vk-callback.html**: `SDK.Auth.exchangeCode(code, deviceId, codeVerifier)`. State-проверка, TTL 10 мин. Только `access_token` на бэкенд.
    - **Баг**: vk-callback.html был записан в Windows-1251 — русский текст не отображался. Исправлен на UTF-8.
    - **core/services/auth.py**: `vk_auth()` — принимает только `access_token` + `guest_token`. Валидация через VK ID `user_info`.
    - **core/schemas/auth.py**: `VKTokenRequest` — только `access_token` (required) + `guest_token`.
    - **nginx**: `location ^~ /assets/` для SDK бандла (`/opt/nura/assets/vendor/vkid-sdk.js`).
    - **Ключевой баг**: VK ID `user_info` возвращает `{"user": {"user_id": ..., "first_name": ..., "last_name": ..., "birthday": ...}}` — данные под ключом `"user"`. Код искал `user_id` на верхнем уровне → исправлено.
  - **E2E тест**: VK-авторизация прошла успешно — mini.html → VK диалог → vk-callback.html → /app/
  - **Блокеры CI/CD**: ручные правки на VPS (scp/Python) создавали локальный diff, блокирующий `git pull` в CI. Решение: не править файлы на VPS напрямую.
- Блокеры: нет
- Следующие шаги: мониторинг VK-авторизации в проде

---

## Сессия 65 — 02.07.2026
- Модель: DeepSeek V4 Flash (opencode-go/deepseek-v4-flash)
- Что сделано:
  - **Исправлены ложные срабатывания NURA Health Alert:**
    - `core/tasks.py`: URL health check изменён с `http://localhost:8000/health` на `http://api:8000/health` (Docker service name)
    - `admin_bot/services/docker_client.py`: тот же фикс для `check_api_health()`
    - `docker-compose.yml`: добавлен `PYTHONPATH=/app` для celery-worker и celery-beat
  - **Деплой на VPS**: контейнеры api, celery-worker, celery-beat, admin-bot пересобраны и перезапущены
  - **Разблокирован deploy.yml (frontend)**:
    - pre-flight check больше не проверяет untracked файлы (только `git diff`)
    - Добавлен `--ignore-cr-at-eol` для игнорирования CRLF-различий на VPS
    - `assets/` добавлен в `.gitignore`
  - **Зафиксированы незакоммиченные hotfix-ы**: VK OAuth (mini.html, vk-callback, auth-слой)
- Блокеры: нет
- Следующие шаги: мониторинг — ложные Health Alert должны исчезнуть

---

## Сессия 64 — 01.07.2026
- Модель: DeepSeek V4 Flash (opencode-go/deepseek-v4-flash)
- Что сделано:
  - **Admin Bot доработки по обратной связи:**
    - Убраны команды `/errors`, `/logs`, `/db query`, `/deploy` — оставлены только `/status`, `/restart`, `/cache clear`, `/help`
    - Исправлен баг: команды не работали из-за chat_router, зарегистрированного первым
    - Создан `chat.py` — обработчик текстовых сообщений с AI (DeepSeek), отвечает на русском с контекстом сервера
    - Добавлено выполнение действий из чата: «перезапусти api», «очисти кэш» — бот выполняет без команды
    - `monitor_health` alert'ы переведены на русский через `_russian_error()`
    - Из `deploy.py` вынесен `/cache` в отдельный `cache.py`
    - Обновлён `/help` с примерами текстовых запросов
  - **Деплой на VPS**: admin-bot запущен, все 7 контейнеров работают
- Блокеры: нет
- Следующие шаги: тестирование chat-режима и мониторинга

---

## Сессия 63 — 01.07.2026
- Модель: DeepSeek V4 Flash (opencode-go/deepseek-v4-flash)
- Что сделано:
  - **Диагностика VK — обнаружена причина**: `https://id.vk.com/oauth2/token` (VK ID token exchange endpoint) возвращает 404. VK полностью убрал/деактивировал серверный endpoint VK ID OAuth. `https://oauth.vk.com/access_token` (старый VK OAuth endpoint) работает корректно — возвращает `{"error":"invalid_grant"}`.
  - **Исправление**: флоу переключён с VK ID на VK OAuth:
    - `mini.html:188-198` — `vkLogin()`: URL авторизации изменён с `https://id.vk.com/authorize` на `https://oauth.vk.com/authorize`, добавлены `display=page` и `v=5.131`
    - `core/services/auth.py:262-342` — `vk_auth()`: token exchange переключён с `https://id.vk.com/oauth2/token` на `https://oauth.vk.com/access_token`; user info переключён с `https://id.vk.ru/oauth2/user_info` на `https://api.vk.com/method/users.get` (c VK API v5.131); парсинг ответа адаптирован под VK API формат (`response[0]`, поля `id/first_name/last_name/bdate`, email из token response)
    - Email извлекается из `access_token` ответа (scope=email), а не из user_info
    - `bdate` из VK API проверяется на наличие года (`len(bdate.split(".")) == 3`) — без года birthday не передаётся
  - **Email регистрация**: проверена — работает (POST `/api/v1/auth/email/send` → 200)
  - **Деплой**: файлы скопированы на VPS, API-контейнер пересобран (`docker compose up -d --build api`)
- Блокеры: нет
- Следующие шаги:
  - Протестировать VK auth flow end-to-end на проде
  - Если VK OAuth redirect_uri не совпадает — проверить настройки VK-приложения
---

## Сессия 62 — 01.07.2026
- Модель: GLM-5.2 (opencode-go)
- Что сделано:
  - **Баг VK: пользователь создавался при ошибке авторизации** (`core/services/auth.py`, `api/routes/auth.py`, `core/repositories/user.py`):
    - `vk_auth()` теперь валидирует ответ VK `user_info` (dict, нет `error`, `user_id` совпадает с фронта) ДО создания пользователя
    - `create_web_user()` принимает `vk_id` напрямую — атомарное создание с VK ID, без отдельного `set_vk_id` после
    - Эндпоинт `/api/v1/auth/vk` ловит `ValueError` (401), `HTTPStatusError` (502), общие ошибки (502) — без stack trace в ответе
  - **mini.html UX**: текст под «Забери свой отчёт» → «Создай аккаунт за один клик — и полный отчёт откроется в приложении.»; «Получить на Email» → «Зарегистрироваться через Email»; «Magic Link — без пароля» → «Без пароля — вход по ссылке»; «Отправить ссылку» → «Создать аккаунт» (btn-soft вместо btn-primary); auth-success → «Аккаунт создан. Проверь почту — там ссылка для подтверждения входа.»
  - **mini.html VK-кнопка**: новый класс `.btn-vk` (синий #0077FF, белый текст, SVG-иконка VK), отличается от email-кнопки
  - **vk-callback.html**: различение ошибок (VK SDK vs сервер vs отказ), проверка `data.access_token/user_id` перед fetch, кнопка «Попробовать ещё раз» (ссылка на /mini), fetch не вызывается при падении exchangeCode
  - **VK флоу: переведён на сервер-сайд обмен code→token** (`core/services/auth.py`, `core/config.py`, `api/routes/auth.py`, `core/schemas/auth.py`, `vk-callback.html`):
    - VKSDK `exchangeCode()` заменён на прямой запрос к `/api/v1/auth/vk` с `code` (без VK SDK на клиенте)
    - Бэкенд сам обменивает code на access_token через `id.vk.com/oauth2/token` (сервер-сайд, с `client_secret`)
    - Добавлен `vk_redirect_uri` в `Settings`
    - Удалён `@vkid/sdk` скрипт из mini.html и vk-callback.html — флоу не зависит от VK SDK
  - **mini.html текст**: убраны «абстрактный текст» и «болит», заменено на «Дата рождения — ключ к твоей личной матрице. А запрос помогает NURA сфокусироваться на главном, чтобы разбор получился точным и личным.»
  - **Архитектурное изменение: User только при авторизации** (`api/routes/web.py`, `core/services/auth.py`, `core/repositories/guest.py`, `mini.html`, `tests/test_auth.py`):
    - mini-analysis больше НЕ создаёт User и Report — только GuestProfile (report_data с анализом + матрицей)
    - User создаётся ТОЛЬКО в момент авторизации: email или VK
    - `merge_guest` → `apply_guest_data_and_create_report`: копирует name/birth_date из GuestProfile в User, затем создаёт MINI Report из guest.report_data
    - `merge_users` удалён — каждый способ входа = отдельный аккаунт, без слияния
    - GuestProfileRepository: добавлен `save_report_data`
    - mini.html: guest_token передаётся в mini-analysis запрос
  - ruff: passed, test_auth: 16/16 passed, test_tarot_handlers: fixed mock bug (create_subscription → create_tarot_payment)
  - VK callback page: 200 OK на проде
  - API логи: чисто, без ошибок
- Блокеры: нет
- Следующие шаги: проверить VK-флоу на проде после деплоя; возможно убрать гостевой профиль-призрак при неудачной VK-авторизации (сейчас guest создаётся на этапе мини-анализа — это ожидаемое поведение, не баг)

---

## Сессия 61 — 01.07.2026
- Модель: DeepSeek V4 Pro
- Что сделано:
  - **Исправление VK авторизации** (`28fb181`):
    - **Nginx**: добавлен `location = /vk-callback.html` в `/etc/nginx/sites-enabled/nura-ai.ru` (файл лежал в `/opt/nura/`, но Nginx отдавал 404)
    - **vk-callback.html**: `redirectUrl` изменён с `window.location.href` (с query params) на `window.location.origin + window.location.pathname` (чистый URL)
    - **core/services/auth.py**: добавлен `client_secret` в POST-запрос к `id.vk.ru/oauth2/user_info`
    - **VK app settings**: redirect URI изменён с `https://nura-ai.ru/api/v1/auth/vk/callback` на `https://nura-ai.ru/vk-callback.html`
    - API контейнер пересобран и перезапущен
  - **Десктопный layout mini.html**:
    - Добавлены media queries для 768px (680px ширина) и 1024px (760px ширина)
    - Форма мини-разбора на десктопе в 2 колонки
  - **Welcome-экран для зарегистрированных**:
    - Новая секция `#stage-welcome` вместо баннера сверху
    - Персонализация имени через `/api/v1/web/me`
    - Кнопка «Перейти в приложение» + ссылка «Начать заново»
- Блокеры: нет
- Следующие шаги:
  - Протестировать VK auth flow end-to-end
  - Проверить welcome-экран на десктопе и мобиле

---

## Сессия 60 — 01.07.2026
- Модель: DeepSeek V4 Flash
- Что сделано: **Реализация Admin Bot** по спецификации ADMIN_BOT_SPEC.md:
  - `core/config.py` — добавлены `admin_bot_token`, `admin_telegram_id`
  - `admin_bot/` — полная структура: config, middleware (AdminOnlyMiddleware), main (polling entry point)
  - `admin_bot/handlers/` — 6 роутеров: status, errors, logs, restart, deploy (включая /cache clear и /db query), help
  - `admin_bot/services/` — DockerClient (Docker socket через httpx, логи, рестарт, health check, deploy, Redis cache clear, DB query), LogParser (фильтрация ошибок с noise-исключением), AIAdvisor (DeepSeek-анализ ошибок)
  - `core/tasks.py` — добавлена задача `monitor_health` (каждые 5 мин: health check, docker ps, сканирование логов на ERROR, alert админу) и helper `_send_admin_message`
  - `docker-compose.yml` — добавлен сервис `admin-bot` с монтированием Docker socket
  - `.env.example` — добавлены `ADMIN_BOT_TOKEN`, `ADMIN_TELEGRAM_ID`
- Ruff: `All checks passed!`; pytest: 335 passed, 1 pre-existing failure
- Блокеры: нет
- Следующие шаги:
  - Создать бота `/newbot` → `@nura_admin_bot` в BotFather, прописать токен в `.env` на VPS
  - Установить команды бота через BotFather
  - Прописать `ADMIN_TELEGRAM_ID` в `.env` на VPS
  - Пересобрать контейнеры: `docker compose up -d --build admin-bot`

---

## Сессия 59 — 01.07.2026
- Модель: DeepSeek V4 Pro (deepseek-v4-pro)
- Что сделано:
  - **Проверка и актуализация AUTH_REMAINING_TASKS.md**: миграция применена, VK ключи прописаны, Celery Beat работает, SMS удалён
  - **Замена транспорта email: Unisender → Beget SMTP** (`e2c4b32`):
    - Добавлены SMTP-поля в `core/config.py` (smtp_host, smtp_port, smtp_secure, smtp_user, smtp_password, smtp_from)
    - `core/tasks.py:send_magic_link_email` переписан с `httpx → Unisender API` на `aiosmtplib → Beget SMTP`
    - HTML-шаблон письма «Вход в NURA» (светлый премиальный стиль, кнопка, text/plain fallback)
    - Безопасное логирование (email маскируется: `t***@example.com`)
    - `requirements.txt`: добавлен `aiosmtplib>=3.0`, убран httpx из tasks.py
    - `.env.example`: SMTP секция добавлена, UNISENDER_API_KEY помечен deprecated
    - Тесты 16/16 проходят, линтер чист
  - **Деплой**: код запушен в GitHub, но VPS недоступен (SSH + HTTP timeout) — деплой отложен
  - **SMTP на VPS**: добавлен `SMTP_PASSWORD` в .env, контейнеры пересобраны, отправка проверена (0.33s)
  - **Очистка корня проекта**: удалены 8 устаревших документов
  - **VK ID**: OneTap заменён на прямой OAuth redirect + создан vk-callback.html
  - **Email magic link URL**: исправлен путь с `/auth/verify` на `/api/v1/auth/email/verify`, ответ API изменён на RedirectResponse (→ `/app/`)
  - **Celery warning**: добавлен `broker_connection_retry_on_startup=True`
  - **Duplicate telegram_id (race condition)**: добавлен `get_or_create_by_telegram_id()` с `INSERT ... ON CONFLICT DO NOTHING`, заменён во всех 4 вызовах
- Блокеры: нет
- Следующие шаги:
  - Протестировать VK ID flow на production
  - Настроить Sentry мониторинг

---

## Сессия 58 — 02.07.2026
- Модель: DeepSeek V4 Pro (deepseek-v4-pro)
- Что сделано:
  - **Telegram как интеграция, не web-login**: Telegram убран с основного экрана входа (на mini.html уже только Email + VK). Telegram теперь только привязка в профиле.
  - **Отвязка Telegram в профиле**: добавлена кнопка «Отключить Telegram» в PWA-профиль (`frontend/pwa/app/profile.html`) и серверный шаблон (`templates/profile.html`)
  - **Backend endpoint**: `DELETE /api/v1/web/unlink-telegram` — очищает telegram_id, проверяет что есть другой способ входа (email_verified или vk_id)
  - **Репозиторий**: `UserRepository.has_other_auth_method()` + `UserRepository.unlink_telegram()`
  - **Бот**: обновлён `welcome_back_text` — предлагает веб-приложение для полного доступа; кнопка «Войти через Email или VK» в главном меню для всех пользователей
  - Файлы: `core/repositories/user.py`, `api/routes/web.py`, `frontend/pwa/app/profile.html`, `nura_app/templates/profile.html`, `bot/texts/start.py`, `bot/keyboards/main_menu.py`
  - **Админка**: добавлены колонки Email (с ✓/без подтверждения) и VK в таблицу пользователей; email + статус верификации в модалку деталей; поля `email`, `email_verified` в API `UserRow` и `UserDetailResponse`
  - Файлы админки: `api/routes/admin_api.py`, `frontend/admin/index.html`
- Блокеры: нет
- Следующие шаги: деплой на VPS, ручное тестирование отвязки TG

---

## Сессия 57 — 02.07.2026
- Модель: DeepSeek V4 Pro (deepseek-v4-pro)
- Что сделано:
  - **VK ID фикс имени**: добавлено логирование полного ответа `id.vk.ru/oauth2/user_info` (строка 309); обработка альтернативных полей имени (first_name, name, display_name); убрано лишнее форматирование пробелов при отсутствии фамилии
  - **Деплой**: исправления задеплоены на VPS, все 6 контейнеров healthy
- Блокеры:
  - Email magic link не работает — требуется `UNISENDER_API_KEY` в `.env` на VPS. Пользователь сгенерирует ключ в ЛК Unisender
- Следующие шаги: добавить UNISENDER_API_KEY на VPS, протестировать VK ID проверку имени, протестировать email auth

---

## Сессия 56 — 02.07.2026
- Модель: glm-5.2 (opencode-go/glm-5.2)
- Что сделано:
  - **VK ID интеграция**: реализован полный флоу авторизации через VK ID (One Tap кнопка), обмен кода на access_token, получение данных пользователя через `id.vk.ru/oauth2/user_info`, создание/обновление пользователя по `vk_id`
  - **Merge пользователей**: добавлена логика объединения аккаунтов — если пользователь вошёл через email/VK/SMS и есть другой веб-аккаунт (из квиза), данные (отчёты, платежи, реферальные награды) переносятся, старый аккаунт удаляется
  - **Удалён SMS auth**: полностью удалён SMS как метод авторизации (кнопки, формы, backend эндпоинты, Celery задача, Pydantic схемы) — оставлен только Email magic link + VK ID
  - **Улучшен UX auth экрана**: убрана надпись "Полный доступ", добавлены отступы, текст разбит на строки, добавлена ссылка "Уже есть аккаунт? Войти →" для тех кто с другого устройства
  - **Проверка сессии**: при загрузке mini.html проверяется `/api/v1/web/session-check`, если есть активная сессия — показывается баннер "С возвращением! [Перейти в приложение →]"
  - **Админка**: добавлены колонки `vk_id` и `auth_method` в таблицу пользователей, фильтры VK/Email, поля в модалке деталей пользователя
  - **Миграция БД**: применена `c4d5e6f7a8b9_add_auth_and_guest.py` (колонки users + таблица guest_profiles)
  - **Деплой**: все контейнеры пересобраны и запущены на VPS, база очищена (0 пользователей)
- ruff: `All checks passed!`; pytest: `19 passed` (auth)
- Блокеры: нет
- Не реализовано: Email magic link не работает (Unisender API ключ не прописан в `.env`)
- Следующие шаги: прописать `UNISENDER_API_KEY` в `.env` на VPS, протестировать email auth flow, проверить что VK ID сохраняет имя пользователя (возможно, VK ID API возвращает поля в другом формате)

---

## Сессия 55 — 01.07.2026
- Модель: glm-5.2 (opencode-go/glm-5.2) — оркестратор, реализация через субагентов
- Что сделано: реализация плана `docs/auth_system_implementation_plan.md` (Фаза 1 + Фаза 2)
  - **Слой данных**: `core/models.py` — новые поля User (`phone`, `auth_method`, `email_verified`, `phone_verified`, `vk_id`) + новая модель `GuestProfile`; `core/config.py` — настройки `unisender_api_key`, `sms_ru_api_id`, `vk_client_id/secret`, TTL'ы guest/magic-link/sms; `core/schemas/auth.py` (11 Pydantic-схем, email через regex без зависимости email-validator); `core/repositories/guest.py` (`GuestProfileRepository`); методы в `UserRepository` (`get_by_email/phone/vk_id`, `set_email_verified/phone_verified/auth_method/phone/vk_id/email`); миграция `alembic/versions/c4d5e6f7a8b9_add_auth_and_guest.py` (колонки users + partial unique indexes + таблица guest_profiles)
  - **Сервис и задачи**: `core/services/auth.py` (`AuthService` — guest/email-magic-link/sms/merge/tg-link/cleanup переиспользует текущую веб-сессию, ключи Redis `guest_profile:`/`magic_link:`/`sms_code:`/`link_token:`); `core/tasks.py` — задачи `send_magic_link_email` (Unisender), `send_sms_code` (sms.ru), `cleanup_expired_guest_profiles` + beat-расписание; no-op без API-ключей (без retry-штормов в dev)
  - **API**: `api/routes/auth.py` (9 эндпоинтов `/api/v1/auth/*`: guest, email send/verify, sms send/verify, merge, generate-tg-link, vk-501-stub) + регистрация в `api/main.py`; лимиты slowapi по плану
  - **Frontend**: `mini.html` — создание guest-профиля при сабмите квиза, stage-auth (leadwall) после мини-результата с inline-формами Email/SMS, автоформат телефона, verify-страница `/auth/verify?token=...` → редирект в PWA; нет prompt/alert, пользовательский ввод через textContent
  - **Telegram**: deep-link уже реализован в `bot/handlers/start.py` (`link_`), переиспользован без дублирования
  - **Тесты**: `nura_app/tests/test_auth.py` (19 тестов, все зелёные) — repo-тесты на реальной SQLite + service-тесты через `_FakeRedis` и MagicMock для Celery (direct-call паттерн, как `test_report_ttl`)
  - Исправление: tz-безопасное сравнение `expires_at` в `AuthService.get_guest` (SQLite возвращает naive datetime)
- ruff: `All checks passed!`; pytest: `19 passed` (auth); полный прогон — 338 passed, 1 failed в `test_tarot_handlers.py` (файл игнорируется CI, ошибка в mock платежей — не связана с auth)
- Блокеры: нет
- Не реализовано (вне кода): Фаза 3 VK ID (требует регистрацию VK-приложения — endpoint оставлен стабом 501), Фаза 4 (рефералка/рассылки/аналитика — продуктовые задачи)
- Следующие шаги: применить миграцию на VPS (`alembic upgrade head`), выставить `UNISENDER_API_KEY`/`SMS_RU_API_ID` в `.env`, прогнать flow на staging, при появлении VK-кредентов реализовать `/api/v1/auth/vk`; при расширении — добавить route-level тесты через общий `client` fixture

---

## Сессия 54 — 30.06.2026
- Модель: qwen3.7-plus (opencode-go/qwen3.7-plus)
- Что сделано:
  - **Полное исправление дублирования веб-пользователей**: `POST /api/v1/web/mini-analysis` теперь проверяет существование пользователя по `(name, birth_date)` перед созданием нового
  - `core/repositories/user.py`: добавлены методы `get_by_name_and_birth_date()` и `update_web_session()`
  - `api/routes/web.py`: логика — если пользователь с такими данными уже существует, обновляется его `web_session_id` вместо создания нового; добавлена обработка `IntegrityError` для race condition
  - `core/models.py`: добавлен composite unique constraint `uq_user_name_birth_date` на `(name, birth_date)`
  - `alembic/versions/b3c4d5e6f7a8_add_unique_name_birth_date.py`: миграция для constraint
- Блокеры: нет
- Следующие шаги: применить миграцию на VPS (`alembic upgrade head`), перезапустить API

---

## Сессия 53 — 30.06.2026
- Модель: DeepSeek V4 Pro (opencode-go/deepseek-v4-pro)
- Что сделано:
  - **Исправлен баг дублирования веб-пользователей**: `POST /api/v1/web/mini-analysis` теперь проверяет существующую сессию (`get_optional_web_user`) и переиспользует пользователя вместо создания нового
  - `core/repositories/user.py`: добавлен метод `update_web_user()` для обновления имени/даты рождения существующего веб-пользователя
  - **Исправлена кнопка «Войти через Telegram»**: добавлен отсутствующий `BOT_USERNAME=ai_nura_bot` в `.env` на VPS. Без него `tg_url` генерировался как `https://t.me/None?start=tgauth_...` и вёл на левый канал
  - Перезапущен API-контейнер на VPS для применения `.env` и нового кода
- Блокеры: нет
- Следующие шаги: коммит изменений, мерж pending PR

---

## Сессия 52 — 30.06.2026
- Модель: DeepSeek V4 Pro (opencode-go/deepseek-v4-pro)
- Что сделано: полная реализация плана ADMIN_UPGRADE_PLAN (4 фазы доработки админ-панели):
  - **Фаза 1 — Действия над пользователем**:
    - `api/routes/admin_api.py`: +6 эндпоинтов (GET /users/{id}, extend subscription/tarot, grant subscription/tarot, regenerate-matrix)
    - `core/repositories/user.py`: +4 метода (extend_subscription, extend_tarot, grant_premium, grant_tarot)
    - Схемы: UserDetailResponse, UserDetailReport, UserDetailPayment, ExtendSubscriptionRequest, GrantSubscriptionRequest
  - **Фаза 2 — PromoCode**:
    - `core/models.py`: модель PromoCode
    - `alembic/versions/`: миграция add_promo_codes
    - `api/routes/admin_api.py`: CRUD промокодов (GET/POST/PATCH/DELETE /promo-codes)
    - `api/routes/web.py`: применение промокода в create-payment и subscribe (валидация, скидка, инкремент used_count)
    - `frontend/admin/index.html`: таб «Промокоды» с созданием/переключением/удалением
    - `frontend/pwa/app/profile.html`: поле ввода промокода при оплате
  - **Фаза 3 — Рефералы**:
    - `api/routes/admin_api.py`: поля referrals_total, referrals_new_7d, top_referrers в GET /stats
    - `frontend/admin/index.html`: таб «Рефералы» с KPI и топом рефереров
  - **Фаза 4 — Воронка**:
    - `frontend/admin/index.html`: KPI «Mini-анализов» и «Конверсия в полный» на Dashboard
  - **Фаза 1 (фронтенд)**: модальное окно с детальной карточкой пользователя и кнопками действий
- Изменённые файлы: `api/routes/admin_api.py`, `api/routes/web.py`, `core/models.py`, `core/repositories/user.py`, `alembic/versions/*`, `frontend/admin/index.html`, `frontend/pwa/app/profile.html`
- Блокеры: нет
- Следующие шаги: деплой на VPS

---

## Сессия 51 — 30.06.2026
- Модель: DeepSeek V4 Pro (opencode-go/deepseek-v4-pro)
- Что сделано: добавление новых табов и KPI в админ-панель, промокод-поле в профиле PWA:
  - **Admin panel (`frontend/admin/index.html`)**:
    - Добавлены табы «Промокоды» и «Рефералы» в навигацию
    - Добавлены HTML-секции: Promo (форма создания + таблица) и Referrals (KPI + топ рефереров)
    - Обновлён `loadTabContent` switch/case для новых табов
    - В `renderKpi` (Dashboard) добавлены метрики: Mini-анализов, Конверсия в полный
    - Добавлены JS-функции: `loadPromos()`, `renderPromoTable(codes)`, создание (POST /promo-codes), переключение (PATCH /promo-codes/{id}/toggle), удаление (DELETE /promo-codes/{id}), `loadReferrals()`
    - togglePromo использует PATCH (прямой fetch), deletePromo — DELETE
  - **PWA Profile (`frontend/pwa/app/profile.html`)**:
    - Добавлено поле ввода промокода перед кнопкой «Подключить подписку»
    - Обновлена `activateSubscription()`: читает `promoCodeField`, отправляет `promo_code` в теле запроса если заполнено
- Изменённые файлы: `frontend/admin/index.html`, `frontend/pwa/app/profile.html`
- Блокеры: API-эндпоинты /promo-codes и /stats (referrals_total, referrals_new_7d, top_referrers) должны быть реализованы на бэкенде
- Следующие шаги: реализация бэкенд-эндпоинтов для промокодов и реферальной статистики

## Сессия 50 — 30.06.2026
- Модель: DeepSeek V4 Pro (opencode-go/deepseek-v4-pro)
- Что сделано: исправление цепочки авторизации и пользовательского пути:
  - **Telegram auth flow исправлен** — `api/routes/web.py`: `auth/start` теперь сохраняет `web_session_id` существующего пользователя в Redis вместо `"pending"`; `bot/handlers/start.py`: `_handle_tg_auth_token` при получении web_session_id находит веб-пользователя, линкует telegram_id (через `update_telegram_id`), продлевает сессию — вместо создания дублирующей записи
  - **Profile reports динамический рендер** — `frontend/pwa/app/profile.html`: статическая строка мини-отчёта заменена на `renderReports()` (JS), генерирует карточки mini/full/compatibility/forecast из API-данных с правильными URL; `openReport(id)` исправлен — поиск по `report_type`, `window.open` → `location.href`; статическая матрица скрывается при наличии full-отчёта; дата форматируется через парсинг DD.MM.YYYY
  - **Config validation** — `core/config.py`: `bot_username` валидатор пустой строки → None
- Изменённые файлы: `api/routes/web.py`, `bot/handlers/start.py`, `frontend/pwa/app/profile.html`, `core/config.py`
- Блокеры: нет
- Следующие шаги: деплой на VPS, тестирование E2E: мини-анализ → Telegram auth → просмотр отчёта в PWA

## Сессия 49 — 30.06.2026
- Модель: DeepSeek V4 Pro (opencode-go/deepseek-v4-pro)
- Что сделано: исправление `frontend/pwa/app/profile.html` — страница профиля PWA:
  - Заменена статическая строка мини-отчёта (строка 72) на динамический контейнер `<div id="reports-list"></div>`
  - Добавлена JS-функция `renderReports(reports)`, генерирующая карточки отчётов на основе API-данных: mini (sparkles, sage), full (grid-dots, terra), compatibility (heart-handshake), forecast (trending-up). Кнопки используют URL из `report.url` через `location.href`. Пустое состояние — сообщение «У тебя пока нет отчётов». Дата создания форматируется через русские месяцы. Юзерские данные экранируются через `N.escHtml()`.
  - Статическая карточка «Матрица Судьбы» (строка 73) получает `id="static-matrix-card"` и скрывается при `has_matrix === true` — вместо старой логики переключения кнопок (Купить/Открыть). Если full-отчёт есть — он появляется в динамическом списке.
  - Функция `openReport(id)` исправлена: поиск по `report_type === id` вместо хардкода `'full'`, `window.open` заменён на `location.href` для работы в PWA standalone-режиме.
  - Вызов `renderReports(d.reports)` добавлен в then-обработчик загрузки `/api/v1/web/me`.
  - Карточки «Совместимость» и «Прогноз на год» с кнопкой «Добавить» сохранены после динамического списка.
- Изменённые файлы: `frontend/pwa/app/profile.html`
- Блокеры: нет
- Следующие шаги: деплой статики через `deploy.sh`

## Сессия 48 — 30.06.2026
- Модель: Qwen 3.7 Plus (opencode-go/qwen3.7-plus)
- Что сделано: выполнение плана из задачи (возраст, мобильное меню, SVG, дашборд, документы) + интеграция P1/P2:
  - **Возраст 39→31**: исправлен в `sample-report.html:2458` (01.06.1995 · 31 год). В `full_report_v2.html` возраст вычисляется динамически (`report.py:232`), формула корректна.
  - **Мобильное меню — контраст**: `.mn-current` цвет `var(--m-accent)` → `var(--ink)` + `font-weight: 500`, `.mobile-nav-panel a` цвет `var(--ink-mute)` → `var(--ink-soft)`, `.num` цвет `var(--ink-faint)` → `var(--ink-mute)` + `font-weight: 500`.
  - **SVG матрицы — сакральная геометрия**: полная переработка SVG на обложке (S1). Добавлены: Flower of Life паттерн (7 кругов), гексагон, glow-эффекты, угловые акценты. ViewBox 360→400, ячейки увеличены.
  - **Дашборд — горизонтальный layout**: `.dashboard` переведён с `grid` на `flex` с горизонтальной прокруткой (`overflow-x: auto`, `scroll-snap-type: x mandatory`). Карточки `flex: 0 0 200px`. На планшете `flex-wrap: wrap`, на мобильном `flex-direction: column`.
  - **P1 Психологические блоки**: интегрированы после S12 (`{% include '_psychological_blocks.html' %}`), добавлены в сайдбар. Отображаются если `psych_blocks` определены.
  - **P2 Карта здоровья**: интегрирована после S8 (`{% include '_health_map.html' %}`), добавлена в сайдбар. Отображается если `chakra_data` определены.
  - **Kitchen-слой**: подтверждено что реализован для всех секций S3-S13 (why-s3 через why-s13). Показывает позиции матрицы, арканы и логику расчёта.
  - **Документ с промптами для изображений**: создан `image-prompts.md` — 11 промптов (RU+EN) для генерации фонов секций отчёта (cover, archetype, karmic, ancestral, purpose, strengths, shadow, relationships, money, cycles, daily card).
  - **Анализ прайс-листа vs отчёта**: создан `pricing-vs-report-analysis.md` — сравнение заявленного (30-50 стр., 21+ секций) с фактическим (19 реализовано + 3 запланировано = 22 секции).
  - **Отраслевой стандарт**: создан `industry-standard-analysis.md` — анализ конкурентов. Ключевая находка: **matrix-profi.ru предлагает 105-107 страниц за 1400 ₽**. NURA (30-50 стр. за 890 ₽) соответствует среднему сегменту.
- Изменённые файлы: `nura_app/templates/reports/full_report_v2.html`, `nura_app/templates/reports/sample-report.html`
- Созданные файлы: `image-prompts.md`, `pricing-vs-report-analysis.md`, `industry-standard-analysis.md`
- Блокеры: нет
- Следующие шаги: сгенерировать фоновые изображения по `image-prompts.md`; деплой на VPS для проверки

## Сессия 47 — 29.06.2026
- Модель: DeepSeek V4 Pro (opencode-go/qwen3.7-plus)
- Что сделано: масштабное обновление дизайна sample-report.html:
  - **Sidebar**: фон изменён с `#F7F4EE→#EFEEE9` на `#F5F0E5→#EDE7DA` + `box-shadow: inset -1px 0 0 var(--line-strong), 2px 0 16px rgba(44,42,30,0.05)` — визуальное отделение от страницы.
  - **Типографика**: body font-size 17→17.5px, line-height 1.6→1.75. Контраст текста: `--ink-soft` 0.72→0.82, `--ink-mute` 0.48→0.58, `--ink-faint` 0.32→0.38. Prose: padding увеличен, font-size 17→18px, line-height 1.75→1.8.
  - **Визуальный ритм**: section padding 120→140px, ch-head margin 40→48px, h2 font-size clamp(38px→40px, 4vw→4.5vw, 52px→56px). Pull-quotes: border 2→3px, font-size 22→23px.
  - **Плейсхолдеры арканов**: новая система `.arcana-placeholder` с 4 размерами (arc-lg 120×180, arc-md 80×120, arc-sm 48×48, arc-icon 40×40). Размещены: обложка (крупная карточка), архетип (средняя у заголовка), кармический хвост (3 карточки в timeline), таланты (3 иконки), дашборд (5 иконок в карточках).
  - **CSS-классы для layout**: `.arcana-row`, `.arc-aside`, `.tl-item-arcana`, `.dash-card .arcana-placeholder { margin-top: auto }` — вместо inline-стилей.
  - **Мобильная версия**: адаптивные размеры плейсхолдеров на ≤880px и ≤520px. `flex-wrap: wrap` на flex-обёртках.
  - **@media print**: arcana-placeholder получают `border: 1px solid #ddd; background: #fafafa`. Исправлен конфликт `.disclaimer` (убран из `display: none !important`).
  - **Print bugfix**: убран `.disclaimer` из списка скрытых элементов — теперь disclaimer'ы отображаются в PDF.
- Изменённые файлы: `nura_app/templates/reports/sample-report.html`
- Блокеры: нет
- Следующие шаги: генерация реальных изображений арканов для замены плейсхолдеров; деплой на VPS

## Сессия 46 — 29.06.2026
- Модель: DeepSeek V4 Pro
- Что сделано: исправление вёрстки sample-report.html:
  - **Sticky sidebar**: `main.content { overflow: hidden }` менял `min-height` грид-элемента на `0`, из-за чего `.shell` не рос выше 100vh — sidebar переставал sticky. Заменено на `overflow-x: clip`.
  - **why-body width**: добавлен `max-width: var(--reading-w)` — блок «Почему я так думаю» больше не уезжает на всю ширину.
  - **Белые карточки**: `.prose`, `.karmic-body`, `.rod-col`, `.rod-info`, `.pattern`, `.conflict`, `.money-block`, `.money-karma`, `.compat`, `.fcast`, `.day`, `.why-card`, `.trait-col`, `.soul-task`, `.dl-card`, `.rel-role-card`, `.rp-card`, `.pros-list` — переведены на `bg #FFF`, `box-shadow: 0 2px 12px rgba(44,42,30,0.06)`, `border-radius: var(--radius-md)`. Убраны `border: 1px solid rgba(...)`.
  - **Двойное оформление**: `.prose` внутри `.karmic-body`/`.rod-col`/`.rod-info` — сброшены bg/padding/shadow чтобы избежать карточки-в-карточке.
  - **Отбивка**: унифицирована на 24px (`margin` у `.pattern`, `.conflict`, `.soul-task`, `.pros-list`, `.rel-role-card`, `.rel-patterns`, `.compat-grid`, `.money-blocks`, `.trait-grid`).
  - **@media print**: добавлены сбросы белых карточек для новых элементов (`.soul-task`, `.trait-col`, `.dl-card`, `.rel-role-card`, `.rp-card`, `.money-karma`, `.why-card`, `.prose`).
  - Палитра, шрифты, HTML-структура, cover, dashboard, sidebar (кроме sticky), мобильная вёрстка — не тронуты.
- Изменённые файлы: `nura_app/templates/reports/sample-report.html`
- Блокеры: нет
- Следующие шаги: деплой на VPS для проверки https://nura-ai.ru/report/sample

## Сессия 45 — 29.06.2026
- Модель: DeepSeek V4 Pro
- Что сделано: исправление CI/CD (8 упавших тестов tarot_pwa):
  - `mock_arcana` фикстура патчила `calculate_daily_arcana`, но `get_daily_card` использует `personalize_arcana` — добавлен патч обеих функций
  - `_build_mock_user` не задавал `main_archetype`/`main_archetype_number` → MagicMock ломал Pydantic-валидацию — поля добавлены
  - `key_phrase=card_text` (AI-текст) в `DailyCardResponse` — исправлено на `arcana["phrase"]`, `affirmation=""` → `arcana["affirmation"]`
  - `replaceAll` сломал имена фикстур (`mock_ai_chat_error` → `mock_ai_chat,_error`) — восстановлено
  - Все 99 тестов проходят, ruff all checks passed
- Изменённые файлы: `api/routes/tarot_pwa.py`, `tests/test_tarot_pwa.py`
- Блокеры: нет

## Сессия 44 — 29.06.2026
- Модель: DeepSeek V4 Pro
- Что сделано: полная переработка sample-report.html (пример отчёта):
  - Дизайн-система сверилась с лендингом — соответствует (те же цвета `#B8743F`/`#6B8068`, шрифты Manrope/Playfair)
  - 11 монолитных prose-секций разбиты на структурированные блоки с `<p>` абзацами, `<strong>` заголовками и `.pull` цитатами
  - Добавлено 11 pull-quote блоков с ключевыми мыслями (по одному на секцию)
  - Исправлена копипаста в 7 чакрах — каждая получила уникальный текст анализа
  - Исправлен organism/global-analysis/global-practice блоки
  - Исправлена противоречивая дата рождения на обложке (22 марта → 01 июня)
  - Секции: 03-Архетип, 04-Карма, 05-Род, 06-Предназначение, 07-Таланты, 08-Тень, 09-Отношения, 10-Деньги, 11-Сценарии, 12-Конфликты, 13-Циклы + Чакры
- Изменённые файлы: `nura_app/templates/reports/sample-report.html`
- Блокеры: нет
- Следующие шаги: деплой на VPS для проверки https://nura-ai.ru/report/sample

## Сессия 43 — 29.06.2026
- Модель: DeepSeek V4 Pro
- Что сделано: обновление `docs/bot-spec.md`:
  - EDIT 1: глобальная замена «Расклад по вопросу» → «По вопросу» и «Да/Нет» → «Да / Нет» в §5 (ASCII-схемы, таблица §5.14, инлайн-текст)
  - EDIT 2: добавлены подписи-саблейблы в ASCII-сетку практик §5.3–§5.4 (Тело · Ум · Дух, Прошлое / Настоящее / Будущее и др.)
  - EDIT 3: добавлены поля `tarot_subscription: bool`, `tarot_subscription_until: datetime | None` в модель User §14
  - EDIT 4: добавлен §8.10 «Flow — веб-подписка на Таро (PWA)» с описанием цепочки: бот → PWA → POST /api/v1/web/subscribe → YooKassa → /app/success → tarot.html?subscribed=1
  - EDIT 5: добавлены `open_pwa` и `open_pwa_report:{token}` в реестр callback_data §1.2
- Изменённые файлы: `docs/bot-spec.md`
- Блокеры: нет
- Следующие шаги: деплой PWA Tarot UX на VPS

## Сессия 42 — 29.06.2026
- Модель: DeepSeek V4 Pro
- Что сделано: PWA Tarot UX Upgrade по плану `PWA_TAROT_UX_UPGRADE_PLAN.md`:
  - **Фаза 1 (Critical):** Skeleton + кэш карты дня (localStorage, 1ч TTL), контекст Матрицы (API поле `user_archetype_name`), Paywall с прямым платежом (`POST /web/subscribe` вместо редиректа на профиль)
  - **Фаза 2 (Medium):** Визуальные экраны раскладов (spread sheet), новая сетка из 6 практик по спецификации, заголовок «Таро-ритуалы», онбординг-блок, Install Banner (pwa-install.js + HTML блоки, счётчик визитов)
  - **Фаза 3 (Low):** Стреак-счётчик (localStorage), авто-редирект после оплаты (`/app/success -> tarot.html?subscribed=1`), обновлён CACHE_NAME в service-worker (`nura-v16`)
  - **Синхронизация документации:** 23 расхождения исправлены в 9 документах — `pwa-spec.md`, `bot-spec.md`, `tarot-integration-plan.md`, `tarot-integration-plan-pwa-patch.md`, `bot-ux-map-pwa-patch.md`, `README.md`
  - **graphify:** добавлен в пользовательский PATH (`~\.local\bin`), `graphify update .` перестроил граф (2982 узла, 4624 связи)
- Изменённые файлы (код): `tarot_pwa.py`, `payment.py`, `tarot.html`, `success.html` (новый), `service-worker.js`
- Изменённые файлы (доки): `pwa-spec.md`, `bot-spec.md`, `tarot-integration-plan.md`, `tarot-integration-plan-pwa-patch.md`, `bot-ux-map-pwa-patch.md`, `README.md`, `STATE.md`
- Блокеры: отсутствуют
- Следующие шаги: деплой на VPS, тестирование всех сценариев

---

## Сессия 41 — 29.06.2026
- Модель: DeepSeek V4 Pro
- Что сделано:
  - Аудит безопасности VPS: nginx (убран backup-конфиг), Redis (пароль + `--requirepass`), Postgres (`scram-sha-256` + пароль, urlencode в `config.py`), SSH (`PermitRootLogin prohibit-password`, `PasswordAuthentication no`), UFW (active, ports 22/80/443)
  - Исправлен STATE.md (UTF-16 → UTF-8, был битый с 18 июня)
  - Graphify добавлен в PATH (`~/.local/bin`)
  - AGENTS.md: добавлен Session Protocol (обязательное обновление STATE.md после сессии) + актуализирована секция graphify
  - Все пароли сохранены в `.env` на сервере
- Блокеры: отсутствуют
- Следующие шаги: мониторинг работы сервера после hardening, обновление локального `.env` при необходимости

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
- ✅ Nginx — прокси, SSL, /webhook/, /report/, /api/, /app (SPA routing)

### Продукт
- ✅ Мини-разбор в браузере — `mini.html` + `/api/v1/web/mini-analysis`
- ✅ Оплата матрицы через веб — `create_web_matrix_payment()`, `/api/v1/web/create-payment`
- ✅ Полный AI-отчёт V2 — генерация 19 секций, HTML/PDF, сайдбар, @media print, психоблоки, карта здоровья
- ✅ P1 Психологические блоки — интегрированы после S12, отображаются если `psych_blocks` определены
- ✅ P2 Карта здоровья — интегрирована после S8, отображается если `chakra_data` определены
- ✅ Kitchen-слой S3-S13 — аккордеоны "Почему я так думаю?" для всех секций (позиции+энергии+логика)
- ✅ Промпт full_report.txt — 2 параллельных запроса (Part A + Part B), min 400-600 слов/поле, max_tokens 32000, результат ~11900 слов (Сессия 34)
- ✅ S2 Дашборд — dashboard_insights, 5 карточек с AI-текстом (Сессия 35)
- ✅ S4 Кармический хвост — убраны заглушки «Загружается», единый karmic-body блок (Сессия 36)
- ✅ S14 Семь дней — парсинг 7 рекомендаций без \n (Сессия 36)
- ✅ Карта здоровья + Психоблоки — фикс: include _health_map.html, парсинг psych_blocks в V2, условные пункты меню (Сессия 37)
- 🟡 Kitchen-аккордеон S3–S13 — стиль кода в why-блоках с // (в процессе, Сессия 37)
- 🟡 sample-report.html — цвета исправлены, текст генерируем из реального отчёта
- ✅ Страница отчёта `/report/{token}` — деплоена
- ✅ Kitchen-слой бэкенд — AI-генерация 12 полей, хранение в БД (JSONB), API `/report/{token}/kitchen`
- ✅ Kitchen-аккордеон в отчёте V2 («Почему я так думаю?» в S3–S13) — Сессия 32, улучшен в Сессии 35 (позиции+энергии+логика) и Сессии 36 (только релевантные позиции на секцию)
- ✅ Подписка 390₽/мес — YooKassa recurrent, Celery downgrade/check
- ✅ Telegram-бот — поллинг, /start, мини-разбор, таро-меню, FSM
- ✅ Таро-бот — 11 хендлеров, 6 раскладов, FSM, AI-промпты (без названий арканов), анимация загрузки
- ✅ Совместимость V2 — лимитная модель (has_matrix/compatibility_used/has_tarot), виральный share, HTML-шаблон
- ✅ Персонализация карты дня — уникальная карта по формуле (дата + центральный аркан матрицы)
- ✅ send_daily_card — Celery-beat 06:00 МСК, всем активным пользователям
- ✅ Чат с NURA — FSM, 5 сообщений free / безлимит premium
- ✅ Video Assembler — FFmpeg бэкенд, CLI, Celery-задача, GPU autodetect
- ✅ Carousel Assembler — Pydantic схемы, HTML-шаблоны, CLI
- ✅ Экран профиля /app/profile — 4 вкладки (отчёты, подписка, уведомления, настройки), hero-блок с архетипом
- ✅ POST /api/v1/web/subscribe — оформление таро-подписки 390₽/мес через веб (YooKassa)
- ✅ create_web_tarot_payment + webhook ветка web_tarot — полный цикл оплаты подписки через PWA
- ✅ PWA главный экран `/app` — SPA: приветствие, архетип, карта дня, матрица, install banner, таббар
- ✅ GET /api/v1/web/me — endpoint профиля для PWA
- ✅ POST /api/v1/web/chat — чат с NURA через браузер (5 free / безлимит premium, Redis counter)
- ✅ /app/chat.html — экран чата PWA (bubbles, typing, hints, localStorage, paywall)

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
- ✅ **Webhook hardening** — все три ветки `process_webhook()` (web_matrix, web_tarot, telegram) защищены: идемпотентность, TOCTOU-safe claim (`SELECT FOR UPDATE`), auth-проверка `payment.user_id`, metadata null-safe, откат статуса при сбое, `birth_date.isoformat()` для Celery, логирование. (Сессия 38)

### Продукт — PWA (новые задачи из ADR-001)
- ✅ **manifest.json + Service Worker** — созданы, развёрнуты, прошли аудит. (Сессия 20 + 29)
- ✅ **Install UI** — Android beforeinstallprompt + iOS 3-шаговая инструкция. (Сессия 20)
- 🟡 **Web Push бэкенд** — VAPID ключи в .env, API написаны, но push-доставка не тестирована E2E. (Сессия 20)
- 🟡 **Дедупликация уведомлений** — `has_pwa_push` флаг в Celery `send_daily_card`. (Сессия 20)
- ✅ **has_pwa_push, push_endpoint, push_p256dh, push_auth** — миграция a1b2c3d4e5f6, поля в моделях.
- ✅ **web_session_id, email в users** — миграция 5a8cac04bf5e.
- ✅ **has_matrix, has_tarot, compatibility_used** — миграция b3c1d2e4f5a6.
- ✅ **open_pwa кнопка в боте** — onboarding, payment, главное меню.
- ✅ **Link-токен связка** — `/api/v1/web/link-telegram` + бот-хендлер `/start link_{TOKEN}`.
- ✅ **Реферальная система** — таблица referral_rewards, `/start ref_{id}`, уведомление реферера, ссылка в профиле.
- ✅ **GET /api/v1/web/me** — endpoint профиля пользователя (имя, архетип, матрица, таро, токен отчёта).
- ✅ **/app/index.html** — главный экран PWA (SPA): приветствие, архетип-badge, кнопка матрицы, карта дня, быстрые кнопки, install banner, таббар.
- ✅ **nginx /app** — location /app + /app/ с try_files для SPA routing.
- ✅ **PWA экраны** — таро, профиль, чат, главный — все 4 готовы. (Сессии 23-26)
- ✅ **Подписка 390₽ через веб** — `POST /api/v1/web/subscribe`. (Сессия 25)
- ✅ **Lighthouse PWA аудит** — 13/13 чеков пройдено (ручной через curl, нет Chrome на VPS). (Сессия 29)
- 🟡 **manifest.json Content-Type** — исправлен (было дублирование, фикс nginx `types {}`). (Сессия 29)
- ✅ **SW регистрация на всех PWA страницах** — добавлена на index/tarot/chat/profile. (Сессия 29)
- ✅ **P1 Психологические блоки** — интегрированы в отчёт после S12. (Сессия 48)
- ✅ **P2 Карта здоровья** — интегрирована в отчёт после S8. (Сессия 48)
- ✅ **Kitchen-слой S3-S13** — аккордеоны для всех секций. (Сессия 48)

### Продукт — Telegram-бот
- ✅ **Реферальная система** — `/start ref_{id}`, referral_rewards, уведомление реферера, реф-ссылка в профиле.
- ✅ **Виральные механики — карточка-картинка (Pillow) для share** — Сессия 28, share-совместимость.
- ✅ **Kitchen UI в боте** — кнопка «🔍 Показать расчёт». (Сессия 30)
- ✅ **Kitchen UI в отчёте** — аккордеон S3–S13 в отчёте (Сессия 32)
- ✅ **Таро-расклады в боте** — weekly, doubles, portal, yes/no работают (Сессия 31)
- ✅ **Экран результата расклада в PWA** — все 6 типов, has_tarot gate, Web Share (Сессия 31)

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
| PWA P0 (manifest + SW + push) | Техническая основа PWA | 22 | ✅ Готово (Сессия 20+29) |
| PWA аудит | Lighthouse/curl аудит, фикс SW регистрации, Content-Type, start_url | — | ✅ Готово (Сессия 29) |
| Виральные механики (Спринт 1) | Карточка + реферальная ссылка | ~3 дня | ✅ Готово |

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

##  Следующие задачи (приоритет)

1. 🟡 **Сгенерировать фоновые изображения** → по `image-prompts.md` для премиального вида отчёта
2. 🟡 **Деплой на VPS** → проверка https://nura-ai.ru/report/sample с новыми секциями
3. 🔴 **YooKassa** — ждём владельца (shop_id + secret_key)

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

- **16.06.2026 — Сессия 40** — DeepSeek V4 Flash
  - Светлая тема: токены из Claude Design применены в nura-ds.css (34 токена)
  - Лендинг: [data-theme="light"] переписан, захардкоженные rgba → CSS-переменные
  - PWA: hero-card тёмная, spread-cards белые, matrix-card sage, day-card белая
  - Статус светлой темы: ✅ Готово (было 🟡)

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

- **09.06.2026 — Сессия 22** — Claude Sonnet 4.6 (claude.ai)
  - Блок 6 (миграция пользователей) закрыт:
  - Grandfather clause: premium → has_matrix=True (идемпотентно, данные уже консистентны)
  - Уведомление отправлено 2 premium-пользователям в Telegram
  - Все P0-блоки закрыты кроме YooKassa credentials (на стороне владельца)

- **09.06.2026 — Сессия 22 (продолжение)** — DeepSeek V4 Pro
  - E2E тестирование: 18/18 проверок пройдено
  - Критический путь подтверждён: мини-анализ -> платёж -> webhook -> has_matrix -> отчёт -> PWA
  - process_webhook web_matrix работает корректно
  - generate_full_report Celery-задача запускается
  - PWA файлы (manifest, SW, иконки, offline, pwa-install.js) — все 200
  - Исправлен AGENTS.md: Celery модуль core.tasks (не core.celery_app)

- **09.06.2026 — Сессия 23** — Qwen 3.7 Max
  - GET /api/v1/web/me — новый endpoint профиля пользователя (имя, архетип, матрица, таро, токен отчёта)
  - /app/index.html — главный экран PWA (SPA):
    - Идентификация через session_id (localStorage + URL param)
    - Приветствие + имя + архетип-badge
    - Кнопка «Открыть Матрицу» → /report/{token} (если есть)
    - Empty state → /mini.html (если нет матрицы)
    - Карта дня (локальный расчёт по дате рождения)
    - Быстрые кнопки: Таро / Чат / Отчёты / Подписка
    - Install banner: Android prompt + iOS 3-шаговая инструкция
    - Нижний таббар с safe area (4 раздела)
    - Loader с анимацией при старте
  - nginx: location /app + /app/ с try_files для SPA
- **09.06.2026 — Сессия 24** — DeepSeek V4 Flash
  - api/routes/tarot_pwa.py: GET /api/v1/tarot/daily-card — персональная карта дня по birth_date
  - /app/tarot.html — экран Таро PWA:
    - Карта дня: hero-блок с арканом, фразой, советом, аффирмацией
    - Кнопка «Поделиться» → Web Share API + clipboard fallback
    - Сетка 6 раскладов (заблокированы без подписки)
    - Paywall modal: bottom sheet с описанием подписки
    - CTA «Подключить за 390₽/мес» → /app/profile?tab=subscription
    - Loader + skeleton при загрузке
    - Safe area iOS, нижний таббар
  - nginx: location = /app/tarot → tarot.html

- **09.06.2026 — Сессия 25** — DeepSeek V4 Flash
  - UserProfileResponse расширен: reports[], subscription_until, tarot_until, has_pwa_push, telegram_linked, ref_link
  - POST /api/v1/web/subscribe — endpoint для оформления таро-подписки (→ YooKassa)
  - /app/profile.html — экран профиля PWA (4 вкладки):
    - Отчёты: список отчётов с переходом по /report/{token}
    - Подписка: статус + оффер 390₽/мес с кнопкой оплаты
    - Уведомления: toggle Web Push + привязка Telegram (generate-link-token)
    - Настройки: реферальная ссылка, данные аккаунта, поддержка, выход
  - create_web_tarot_payment() в PaymentService + webhook ветка web_tarot в process_webhook
  - nginx: location = /app/profile → profile.html

- **09.06.2026 — Сессия 26** — Qwen 3.7 Max
  - POST /api/v1/web/chat — endpoint чата с NURA через браузер:
    - AIService.chat_response с history[-10:] и matrix_data из отчётов
    - Redis counter chat_count:{user_id} — 5 бесплатных, TTL 24ч, -1 для подписчиков
    - 402 при исчерпании лимита
  - /app/chat.html — экран чата PWA:
    - Full-height layout (100dvh) с fixed header и input area
    - Bubbles: пользователь (золото) / NURA (зелёный)
    - Typing indicator (анимированные точки)
    - localStorage история (последние 20 сообщений)
    - Hint-кнопки при пустой истории (подсказки по матрице)
    - Limit bar при ≤3 сообщений + paywall block при 0
    - Auto-resize textarea, Enter → отправка, Shift+Enter → перенос
    - Кнопка «Очистить» историю с подтверждением
  - nginx: location = /app/chat → chat.html
  - PWA P1 ЗАКРЫТ — все 4 экрана готовы:
    - /app → index.html ✅
    - /app/tarot → tarot.html ✅
    - /app/profile → profile.html ✅
    - /app/chat → chat.html ✅

- **09.06.2026 — Сессия 27** — DeepSeek V4 Flash
  - Яндекс.Метрика 109200181: 8 страниц, 8 целей на всех PWA-экранах и лендинге
  - metrika.js универсальный скрипт с page_id автоопределением
  - Файлы: analytics.js + metrika.js + pwa-pages-analytics.md

- **09.06.2026 — Сессия 28** — DeepSeek V4 Pro
  - core/services/share_card.py: generate_compat_card() — PNG 1080×1080
  - Pallete: #0A0E0C / #C9A55C / #97C5A1 / #E8E0D0
  - Шрифты DejaVu (системные), декоративные звёзды, бейджи имён
  - bot/handlers/compatibility.py: кнопка «🖼 Поделиться карточкой»
  - callback share_compat_card: генерация + answer_photo
  - compat_how_interact сохранён в FSM state
  - Тест: PNG 37KB, ruff clean, бот active

- **10.06.2026 — Сессия 29** — DeepSeek V4 Flash
  - Lighthouse PWA аудит (ручной, через curl — нет Chrome на VPS): 13/13 чеков пройдено
  - **Проблемы и фиксы:**
    - SW регистрация отсутствовала на всех 4 PWA страницах `/app/*` — добавлена
    - `manifest.json` Content-Type дублировался (application/json + application/manifest+json) — фикс nginx `types {}`
    - `start_url: "/app"` → 301 редирект на `/app/` — исправлен на `/app/`
  - `docs/pwa-spec.md` обновлён: чеклист, результаты аудита, статусы
  - `STATE.md` обновлён

- **10.06.2026 — Сессия 30** — DeepSeek V4 Flash
  - Kitchen UI в боте: callback `show_kitchen`, расчёт из matrix_data без AI-вызова
  - Кнопка «🔍 Показать расчёт» добавлена под мини-разбором

- **10.06.2026 — Сессия 31** — DeepSeek V4 Flash
  - Диагностика и фикс таро-раскладов в боте (weekly/doubles/portal/yes_no)
  - POST /api/v1/tarot/spread — новый endpoint для PWA
  - Экран результата расклада в PWA (inline, 6 типов, Web Share, loading/error)
  - Input-экран для расклада «По вопросу» и «Да/Нет»
  - `open_pwa` кнопка после показа расчёта

- **10.06.2026 — Сессия 32** — DeepSeek V4 Flash
  - `_psychological_blocks.html` подключён к `full_report_v2.html` (после S12)
  - `_health_map.html` подключён к `full_report_v2.html` (после S8)
  - Kitchen-аккордеон «Почему я так думаю?» добавлен в S4–S13
  - Сайдбар обновлён (секции здоровья и психоблоков)

- **10.06.2026 — Сессия 33** — DeepSeek V4 Pro
  - Промпт full_report.txt полностью переписан: min 400-600 слов/поле, системная роль, {name}/{birth_date}
  - FULL_REPORT_PARAMS: temperature 0.7→0.8, top_p 0.9→0.95
  - Разбивка на 2 параллельных AI-запроса через asyncio.gather (Part A — личность, Part B — жизнь)
  - full_report_part_a.txt (9 полей) + full_report_part_b.txt (8 полей)
  - generate_full_report() принимает name, передаёт в промпт для персонализации
  - _process_full_report() получает user_name ДО AI-вызова
  - CoT-инструкция обновлена: 10 шагов, акцент на объём, персонализация через {name}
  - Целевой объём AI-текста: ~10000+ слов (было ~2600)

- **10.06.2026 — Сессия 34** — DeepSeek V4 Pro
  - full_report.txt переработан: системная роль NURA, {name}+{birth_date}, min 400-600 слов на поле, запрет эзотерического жаргона
  - ai.py: 2 параллельных запроса asyncio.gather (Part A 9 полей + Part B 8 полей)
  - max_tokens 32000, temperature 0.8, top_p 0.95
  - Результат: 11903 слов (было 4896) — рост ×2.4, паритет с рынком
  - 7/7 тестов, ruff clean, деплой api+celery-worker+bot

- **10.06.2026 — Сессия 35** — DeepSeek V4 Pro
  - dashboard_insights: новое AI-поле в Part B, 5 карточек S2 с персонализированным текстом
  - Kitchen-аккордеон S4–S13: why-блоки показывают позиции + арканы + логику (а не только logic)
  - S5 Родовые программы: устранено дублирование (был один текст в двух колонках, теперь единый блок с линиями отца/матери)
  - Деплой api + celery-worker

- **10.06.2026 — Сессия 36** — DeepSeek V4 Flash
  - S4: убраны заглушки «Загружается», karmic_tail_analysis единым блоком
  - Kitchen: промпт ограничен релевантными позициями на секцию (3-5 арканов), поддержка str/list в схеме и шаблоне
  - S14: фикс парсинга 7 дней практик (split по пробелу вместо \n)
  - Эталонный отчёт: https://nura-ai.ru/report/a33a768e958e4ceb9388a8cf43392fe8

- **11.06.2026 — Сессия 37** — DeepSeek V4 Flash
  - Фикс Карта здоровья + Психоблоки в V2-отчёте:
    - report.py: `_build_v2_report_data()` — добавлен парсинг `psychological_blocks` через `parse_psych_blocks()`, поле `psych_blocks` передаётся в контекст
    - full_report_v2.html: добавлен `{% include '_health_map.html' %}` после секции 08
    - full_report_v2.html: пункты «Карта здоровья» и «Психоблоки» в сайдбаре и TOC обёрнуты в `{% if chakra_data %}` / `{% if psych_blocks %}`
   - Сгенерирован тестовый отчёт с проверкой секций: https://nura-ai.ru/report/66c3fda5
   - Деплой api + celery-worker

- **11.06.2026 — Сессия 38** — DeepSeek V4 Pro
   - Полный аудит безопасности `process_webhook()` — найдено 13 багов и edge cases
   - **PaymentRepository.claim_succeeded()** — новый метод с `SELECT FOR UPDATE` для атомарного TOCTOU-safe claim'а платежа
   - **Ветка web_matrix**: идемпотентность, auth-проверка `payment.user_id`, metadata null-safe (`or {}`), откат статуса при сбое `update_has_matrix`, `birth_date.isoformat()`, try/except для `generate_full_report.delay()`, warning при отсутствии birth_date, логирование
   - **Ветка web_tarot**: те же фиксы (idempotency, auth, rollback, logging)
   - **Telegram-ветка**: те же фиксы + валидация `telegram_id`, `try/except` для `send_msg`, auth-проверка `payment.user_id == user.id`
   - Перманентные ошибки → 200 + `{"status": "needs_review"}` (вместо 404 → бесконечные ретраи YooKassa)
   - Только «Payment not found» → `ValueError` → 404 (транзиентная гонка, ретрай оправдан)
   - ruff clean, закоммичено, запушено

- **11.06.2026 — Сессия 39** — DeepSeek V4 Flash
   - Лендинг: hero-изображение nura-hero.png → nura-hero.webp (-95%, 1.8MB → 87KB)
   - Лендинг: hero-layout — max-width перенесён с .hero-inner на .hero-text (560px), .hero-inner упрощён (width:100%, без grid)
   - Лендинг: фикс бага — .hero-inner width:100% переопределял .container, текст уходил к левому краю
   - Nginx: добавлен Cache-Control: no-cache, no-store, must-revalidate для HTML страниц (браузер больше не кеширует старую версию)
   - Файлы лендинга синхронизированы: git ↔ /opt/nura/ ↔ /var/www/nura-ai.ru/
## Сессия 78 — 05.07.2026
- Модель: GPT-5 Codex
- Что сделано: дана инструкция по запуску `codex` в терминале VS Code; локально проверено, что команда `codex` доступна и отвечает на `codex --help`
- Блокеры: нет
- Следующие шаги: при необходимости помочь с `codex login`, профилями и запуском в конкретном проекте
