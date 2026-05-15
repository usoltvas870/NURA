# Промпты для разработки NURA

10 шагов разработки. Выполнять строго по порядку — каждый шаг зависит от предыдущего.
Копируй промпт целиком и вставляй в Task tool.

---

## Шаг 1 — База данных и Репозитории

**Модель:** DeepSeek V4 Pro
**Агенты:** `database-optimizer` (модели + индексы), `backend-architect` (репозитории)
**Рецензент:** `code-reviewer`
**Вход:** `docs/bot-spec.md` (секция 14 — поля User)

```

Что сделать:

### 1. Модели
Файл: nura_app/core/models.py

Обновить модель User — добавить поля:
- username: str | None
- first_name: str | None
- main_archetype: str | None
- main_archetype_number: int | None
- subscription_until: datetime | None
- payment_method_id: str | None

Обновить модель Report — добавить поле:
- report_type: str — enum значений: "mini" | "full" | "compatibility"

Таблицы создавать через Base.metadata.create_all (если не используются миграции).

### 2. Репозитории
Создать файлы:

nura_app/core/repositories/__init__.py — экспорт всех репозиториев
nura_app/core/repositories/base.py — SQLAlchemyRepository с async-методами: add, get, get_all, update, delete
nura_app/core/repositories/user.py — UserRepository:
  - get_by_telegram_id(telegram_id: int) -> User | None
  - create(telegram_id, username, first_name) -> User
  - update_archetype(user_id, archetype, number)
  - update_subscription(user_id, status, until)
nura_app/core/repositories/report.py — ReportRepository:
  - get_by_token(token: str) -> Report | None
  - get_by_user_id(user_id: UUID) -> list[Report]
  - create(user_id, report_type, token, matrix_data, ai_analysis) -> Report
nura_app/core/repositories/payment.py — PaymentRepository:
  - create(user_id, amount, yookassa_id) -> Payment
  - get_by_yookassa_id(yookassa_id: str) -> Payment | None
  - update_status(payment_id, status)

Все репозитории принимают async_sessionmaker в конструкторе.

После записи сделай commit с сообщением "Add DB models and repositories"
```

---

## Шаг 2 — Core: Расчёт матрицы

**Модель:** DeepSeek V4 Pro
**Агент:** `backend-architect`
**Рецензент:** `technical-writer`
**Вход:** `docs/matrix-algo.md`, `nura_app/core/services/matrix.py` (текущий)

```
Прочитай docs/matrix-algo.md — алгоритм расчёта.
Прочитай nura_app/core/services/matrix.py — текущая реализация.
Прочитай nura_app/core/schemas.py — MatrixData.
Прочитай nura_app/core/repositories/user.py — UserRepository (для сохранения архетипа).

Файл: nura_app/core/services/matrix.py

Переписать MatrixService:
- calculate(birth_date: str) -> MatrixData — полный расчёт всех позиций по matrix-algo.md
- Все 22 аркана: номер, название (русское), эмодзи
- Позиции: центр, портретная зона, зона талантов, зона комфорта, кармический хвост, линия неба, линия земли, линия отношений, линия денег
- format_for_prompt(matrix_data: MatrixData) -> str — форматирование для AI
- format_for_report(matrix_data: MatrixData) -> dict — форматирование для отчёта
- get_archetype_name(number: int) -> str

Схема MatrixData в schemas.py — обновить, если нужно (добавить недостающие поля).

После записи сделай commit с сообщением "Add matrix calculation service"
```

---

## Шаг 3 — Core: AI-сервис

**Модель:** DeepSeek V4 Pro
**Агент:** `ai-engineer`
**Рецензент:** `technical-writer`
**Вход:** `docs/prompt-spec.md`, `nura_app/core/services/ai.py`, `nura_app/core/prompts/`

```
Прочитай docs/prompt-spec.md — полная спецификация промптов.
Прочитай nura_app/core/services/ai.py — текущая реализация.
Прочитай nura_app/core/prompts/mini_analysis.txt — текущий промпт.
Прочитай nura_app/core/prompts/full_report.txt — текущий промпт.
Прочитай nura_app/core/schemas.py — MiniAnalysisResult, FullReportResult.
Прочитай nura_app/core/config.py — настройки DeepSeek API.

Файл: nura_app/core/services/ai.py

Переписать AIService:
- generate_mini_analysis(birth_date: str, matrix_data: MatrixData) -> MiniAnalysisResult
- generate_full_report(birth_date: str, matrix_data: MatrixData) -> FullReportResult
- generate_compatibility(date1: str, matrix1: MatrixData, date2: str, matrix2: MatrixData) -> dict
- chat_response(user_message: str, chat_history: list, matrix_data: MatrixData) -> str

Для каждого метода:
- Загружать system prompt из prompt-spec.md
- Загружать user prompt из prompt-spec.md
- Формировать сообщения для DeepSeek API
- Парсить JSON-ответ
- Валидировать по JSON Schema
- Fallback: при ошибке возвращать шаблонные данные
- Retry: 3 попытки с timeout 30s

System prompt — захардкодить в коде (не из файла), с тоном NURA:
- Обращение на "ты"
- Тёплый, мудрый друг
- Без эзотерики и клише
- Не предсказывать будущее
- Ответы 2-4 предложения

После записи сделай commit с сообщением "Add AI service with prompts"
```

---

## Шаг 4 — Core: Платежи и Отчёты

**Модель:** DeepSeek V4 Flash
**Агент:** `backend-architect`
**Рецензент:** `code-reviewer`
**Вход:** `docs/report-spec.md`, `nura_app/core/services/payment.py`, `nura_app/core/services/report.py`

```
Прочитай docs/report-spec.md — структура отчёта.
Прочитай nura_app/core/services/payment.py — текущая реализация.
Прочитай nura_app/core/services/report.py — текущая реализация.
Прочитай nura_app/core/config.py — настройки YooKassa и отчётов.
Прочитай nura_app/core/schemas.py — PaymentCreate, PaymentResponse.
Прочитай index.html — бренд-стили NURA.

### PaymentService
Файл: nura_app/core/services/payment.py

Переписать PaymentService:
- create_payment(telegram_id: int, amount: int, description: str, metadata: dict) -> dict
  - Создаёт платёж в YooKassa
  - Возвращает {id, status, payment_url}
- check_payment(payment_id: str) -> dict
  - Проверяет статус платежа
- create_subscription(telegram_id: int) -> dict
  - Создаёт recurrent платёж через YooKassa с save_payment_method=True
- cancel_subscription(payment_method_id: str)
  - Отключает рекуррентный платёж

### ReportService
Файл: nura_app/core/services/report.py

Переписать ReportService:
- generate_html_report(report_data: dict, template_name: str) -> str
  - Рендерит HTML из шаблона + данных
- generate_pdf(html_content: str) -> bytes
  - Конвертирует HTML в PDF через WeasyPrint
- get_report_path(token: str) -> str
- save_report_files(token: str, html: str, pdf: bytes) -> dict
  - Сохраняет HTML и PDF на диск
  - Возвращает пути к файлам

Шаблон отчёта — создать отдельный файл:
frontend/reports/full_report.html — HTML-шаблон с переменными подстановки.

Шаблон должен содержать все секции из report-spec.md:
- Cover с лого NURA
- Главный архетип
- Сильные стороны
- Теневые стороны
- Отношения
- Деньги
- Жизненные циклы
- Рекомендации на 7 дней
- Совместимость (если есть)

CSS Design System для отчёта — взять цвета из index.html (чёрный, глубокий зелёный, оранжевый).

После записи сделай commit с сообщением "Add payment and report services"
```

---

## Шаг 5 — Celery Tasks

**Модель:** DeepSeek V4 Flash
**Агенты:** `devops-automator` (настройка beat), `backend-architect` (логика задач)
**Рецензент:** `code-reviewer`
**Вход:** `nura_app/core/tasks.py`, `nura_app/core/services/`, `nura_app/core/config.py`

```
Прочитай nura_app/core/tasks.py — текущая реализация.
Прочитай nura_app/core/services/ai.py — AIService.
Прочитай nura_app/core/services/matrix.py — MatrixService.
Прочитай nura_app/core/services/report.py — ReportService.
Прочитай nura_app/core/config.py — redis_url, celery_broker_url.
Прочитай nura_app/core/repositories/user.py — UserRepository.
Прочитай docs/bot-spec.md — раздел 9 (подписка) и 10 (ежедневные инсайты).

Файл: nura_app/core/tasks.py

Переписать полностью:

1. generate_mini_report(user_id: str, birth_date: str, username: str) -> dict
   - Создаёт асинхронную сессию
   - Считает матрицу через MatrixService
   - Генерирует мини-анализ через AIService
   - Сохраняет Report в БД через ReportRepository
   - Обновляет User.main_archetype через UserRepository
   - ВОЗВРАЩАЕТ результат (не блокирует бота task.get())
   - Отправляет уведомление пользователю через Bot API (send_message)

2. generate_full_report(user_id: str, birth_date: str, report_token: str) -> dict
   - Расчёт матрицы + AI-анализ
   - Генерация HTML + PDF через ReportService
   - Сохранение файлов
   - Сохранение Report в БД
   - Отправка уведомления пользователю: ссылка на HTML + PDF

3. generate_compatibility_report(user_id: str, date1: str, date2: str) -> dict
   - Аналогично, но для совместимости

4. send_daily_insights()
   - Celery-beat: каждый день в 06:00 UTC
   - Выбрать всех User с subscription_status="premium"
   - Для каждого: получить архетип, выбрать случайный инсайт, отправить
   - Если BotBlocked → установить subscription_status="blocked"

5. check_expiring_subscriptions()
   - Celery-beat: каждый день в 12:00 UTC
   - Найти подписки, истекающие через 3 дня
   - Отправить уведомление о скором истечении

6. downgrade_expired_subscriptions()
   - Celery-beat: каждый день в 00:00 UTC
   - Найти истекшие подписки
   - Установить subscription_status="free"

Настройка Celery-beat в celery_app.conf.beat_schedule.

После записи сделай commit с сообщением "Add Celery tasks and beat schedule"
```

---

## Шаг 6 — API Routes

**Модель:** DeepSeek V4 Flash
**Агент:** `backend-architect`
**Рецензент:** `code-reviewer`
**Вход:** `nura_app/api/routes/payment.py`, `nura_app/api/routes/reports.py`, `nura_app/core/services/`

```
Прочитай nura_app/api/routes/payment.py — текущая реализация.
Прочитай nura_app/api/routes/reports.py — текущая реализация.
Прочитай nura_app/api/main.py — FastAPI app.
Прочитай nura_app/core/services/payment.py — PaymentService.
Прочитай nura_app/core/services/report.py — ReportService.
Прочитай nura_app/core/repositories/ — все репозитории.
Прочитай nura_app/core/config.py — настройки.
Прочитай nura_app/core/tasks.py — generate_full_report.

### Payment Routes
Файл: nura_app/api/routes/payment.py

Обновить:

POST /api/v1/payment/webhook — YooKassa webhook:
- Принимает notification от YooKassa
- Проверяет event == "payment.succeeded"
- Извлекает metadata (telegram_id, report_token)
- Находит Payment в БД по yookassa_id
- Обновляет статус Payment на "succeeded"
- Запускает generate_full_report.delay(telegram_id, birth_date, report_token)
- Отвечает {"ok": true}

### Reports Routes
Файл: nura_app/api/routes/reports.py

Обновить:

GET /report/{token} — отдаёт HTML-отчёт:
- Ищет Report по token
- Если нет → 404
- Если есть → читает HTML-файл → отдаёт Response(content_type="text/html")

GET /report/{token}/pdf — отдаёт PDF-отчёт:
- Аналогично, но с content_type="application/pdf"

### Main
Файл: nura_app/api/main.py

Проверить, что все router'ы подключены.
Rate limiting через slowapi на webhook (10 запросов/мин).

После записи сделай commit с сообщением "Add API payment webhook and report routes"
```

---

## Шаг 7 — Бот: Инфраструктура

**Модель:** DeepSeek V4 Flash
**Агенты:** `backend-architect` (middleware + main.py), `ux-architect` (keyboards), `technical-writer` (texts)
**Рецензент:** `code-reviewer`
**Вход:** `docs/bot-spec.md`, `nura_app/bot/main.py`, `nura_app/bot/middlewares/`, `nura_app/bot/keyboards/`, `nura_app/bot/states/`

```
Прочитай docs/bot-spec.md — все разделы (callback_data, FSM, клавиатуры, тексты).
Прочитай nura_app/bot/main.py — текущий entry point.
Прочитай nura_app/core/repositories/user.py — UserRepository.

### 1. Middleware
Создать:

bot/middlewares/registration.py:
- UserRegistrationMiddleware
- Каждый апдейт: проверить UserRepository.get_by_telegram_id()
- Если нет — создать User через UserRepository.create()
- Если первый вход — отправить "Приятно познакомиться, {name}!"

bot/middlewares/throttling.py:
- ThrottlingMiddleware
- 1 сообщение/сек
- При превышении: "Слишком быстро — давай по одной команде за раз ☕"

bot/middlewares/anti_flood.py:
- AntiFloodMiddleware
- 10 сообщений/мин → бан на 30 сек
- При превышении: "Ты слишком быстр. Давай сделаем паузу на полминуты ☕"

bot/middlewares/__init__.py — экспорт

### 2. FSM States
Создать:

bot/states/matrix_state.py — MatrixStates(waiting_birth_date)
bot/states/compatibility_state.py — CompatibilityStates(waiting_first_date, waiting_second_date)
bot/states/chat_state.py — ChatStates(idle, chatting)
bot/states/__init__.py

### 3. Keyboards (все)
Файл: bot/keyboards/main_menu.py

main_menu_keyboard() — InlineKeyboardMarkup:
- ✨ Рассчитать матрицу (calculate_matrix)
- ❤️ Совместимость (compatibility), 🌒 Инсайты (insights)
- 💬 Чат с NURA (chat_with_nura)
- 👤 Профиль (profile)

paywall_keyboard(token: str, report_type: str) — для мини-разбора:
- 🔮 Полный разбор за 590 ₽ (pay_full_report:{token})
- 🏠 В меню (main_menu)

compatibility_paywall_keyboard(token: str):
- 🔮 Полный разбор за 390 ₽ (pay_compatibility:{token})
- 🏠 В меню (main_menu)

profile_keyboard(has_matrix: bool, has_full_report: bool, is_subscriber: bool) — 4 варианта
insight_keyboard() — Поделиться / Ещё / В меню
chat_keyboard() — Выйти / Очистить историю
subscription_keyboard() — Оформить / Назад
reports_keyboard(reports: list, page: int) — список отчётов с пагинацией

bot/keyboards/__init__.py

### 4. Texts (все)
Создать bot/texts/ со всеми текстами из bot-spec.md:

bot/texts/start.py — приветствие, /start, /menu, /help
bot/texts/matrix.py — запрос даты, ошибки, loading, мини-разбор, CTA
bot/texts/compatibility.py — объяснение, запрос дат, loading, результат
bot/texts/insights.py — инсайт дня, нет матрицы, нет инсайтов
bot/texts/profile.py — 4 варианта профиля, список отчётов
bot/texts/chat.py — приветствие чата, прощание, пейволл
bot/texts/payment.py — ссылка на оплату, успех, ошибка, генерация, готово
bot/texts/subscription.py — предложение, оформлено, истекает, истекла
bot/texts/system.py — глобальная ошибка, rate limit, регистрация, кнопки заблокированы
bot/texts/__init__.py

Все тексты — функции с подстановками, возвращающие строку.
Пример:
def mini_analysis_text(archetype: str, strength: str, conflict: str, pattern: str, block: str) -> str

### 5. Main
Файл: bot/main.py

Обновить:
- FSM storage: MemoryStorage → RedisStorage (из config.redis_url)
- Включить все middleware (порядок: registration → throttling → anti_flood)
- Включить все router'ы
- Добавить глобальный error handler
- Режим: polling (webhook будет настроен позже)

bot/__init__.py — пустой

После записи сделай commit с сообщением "Add bot infrastructure: middlewares, states, keyboards, texts"
```

---

## Шаг 8 — Бот: Handlers (часть 1)

**Модель:** DeepSeek V4 Flash
**Агенты:** `backend-architect` (FSM-логика), `ux-architect` (UX-флоу)
**Рецензент:** `code-reviewer`
**Вход:** `docs/bot-spec.md`, `nura_app/bot/handlers/`, `nura_app/bot/texts/`, `nura_app/core/services/matrix.py`, `nura_app/core/services/ai.py`, `nura_app/core/tasks.py`

```
Разработка handler'ов: /start, матрица, совместимость.

Прочитай docs/bot-spec.md — разделы 2 (главное меню), 3 (матрица), 4 (совместимость).
Прочитай nura_app/bot/texts/start.py — тексты главного меню.
Прочитай nura_app/bot/texts/matrix.py — тексты матрицы.
Прочитай nura_app/bot/texts/compatibility.py — тексты совместимости.
Прочитай nura_app/bot/keyboards/main_menu.py — клавиатуры.
Прочитай nura_app/bot/states/ — FSM состояния.
Прочитай nura_app/core/tasks.py — generate_mini_report.
Прочитай nura_app/core/repositories/user.py — UserRepository.

### /start handler
Файл: nura_app/bot/handlers/start.py

Обновить:
- /start, /menu → показать main_menu_keyboard() с приветствием
- /help → показать help-текст
- callback main_menu → то же самое
- callback profile → не обрабатывать (обрабатывается в profile.py)

### Matrix handler
Файл: nura_app/bot/handlers/matrix.py

Переписать полностью:

ask_birth_date (callback: calculate_matrix):
- Установить MatrixStates.waiting_birth_date
- Отправить текст запроса даты

process_birth_date (message, MatrixStates.waiting_birth_date):
- Валидация формата (ДД.ММ.ГГГГ)
- Валидация существования даты
- Ошибка → повторный ввод
- OK:
  - state.clear()
  - Запустить loading_animation (4 шага с edit_text)
  - Запустить generate_mini_report.delay() — асинхронно, без task.get()
  - Сохранить task_id в state
  - Ждать результата через callback / task tracking

show_mini_analysis (когда результат готов):
- Показать мини-разбор из 5 блоков
- Внизу: paywall_keyboard(token)

### Compatibility handler
Создать: nura_app/bot/handlers/compatibility.py

ask_compatibility (callback: compatibility):
- Отправить объяснение фичи
- Установить CompatibilityStates.waiting_first_date

process_first_date (message, CompatibilityStates.waiting_first_date):
- Валидация
- OK: установить waiting_second_date, запросить вторую дату

process_second_date (message, CompatibilityStates.waiting_second_date):
- Валидация
- Проверка: даты не совпадают
- OK: state.clear()
- Loading-анимация
- Mini-разбор совместимости (бесплатные блоки)
- CTA: купить полный разбор

validators — вынести в отдельную функцию в bot/handlers/validators.py:
- validate_date(date_str: str) -> bool
- Функция проверяет формат и существование даты

После записи сделай commit с сообщением "Add bot handlers: start, matrix, compatibility"
```

---

## Шаг 9 — Бот: Handlers (часть 2)

**Модель:** DeepSeek V4 Flash
**Агенты:** `ai-engineer` (чат), `backend-architect` (платежи), `product-manager` (инсайты/профиль)
**Рецензент:** `code-reviewer`
**Вход:** `docs/bot-spec.md`, разделы 5-8

```
Разработка handler'ов: инсайты, профиль, чат, платежи.

Прочитай docs/bot-spec.md — разделы 5 (инсайты), 6 (профиль), 7 (чат), 8 (платежи).
Прочитай nura_app/bot/handlers/ — существующие handler'ы.
Прочитай nura_app/bot/states/ — ChatStates.
Прочитай nura_app/bot/keyboards/main_menu.py — все клавиатуры.
Прочитай nura_app/bot/texts/ — все тексты.
Прочитай nura_app/core/repositories/user.py — UserRepository.
Прочитай nura_app/core/repositories/report.py — ReportRepository.
Прочитай nura_app/core/services/ai.py — AIService.chat_response.
Прочитай nura_app/core/services/payment.py — PaymentService.

### Insights handler
Создать: nura_app/bot/handlers/insights.py

show_insight (callback: insights):
- Проверить: есть ли у User.main_archetype?
- НЕТ → "Сначала рассчитай матрицу" + кнопка calculate_matrix
- ДА → показать инсайт дня:
  - Выбрать случайный шаблон для архетипа
  - Показать текст + insight_keyboard()

another_insight (callback: another_insight):
- Выбрать другой шаблон (не повторять сегодняшний)
- Если все шаблоны показаны → "Ты сегодня уже достаточно услышал" + subscription

share_insight (callback: share_insight):
- Отправить текущий инсайт текстом с пометкой "скопируй это сообщение"

### Profile handler
Создать: nura_app/bot/handlers/profile.py

show_profile (callback /command profile):
- Получить User из БД
- Определить статус: нет матрицы / мини / полный отчёт / подписка
- Показать соответствующий текст и клавиатуру

view_reports (callback: view_reports):
- Получить список Report для User
- Показать список с кнопками открыть/скачать
- Если отчётов нет → "У тебя пока нет ни одного отчёта"

### Chat handler
Создать: nura_app/bot/handlers/chat.py

enter_chat (callback: chat_with_nura):
- Проверить доступ: подписка или есть полный отчёт?
- НЕТ → показать пейволл
- ДА:
  - Установить ChatStates.chatting
  - Отправить персонализированное приветствие + chat_keyboard()

chat_message (message, ChatStates.chatting):
- Вызвать AIService.chat_response с контекстом (последние 10 сообщений + матрица)
- Отправить ответ
- Сохранить сообщение в историю

exit_chat (callback/command: chat_exit):
- Сбросить ChatStates.idle
- Отправить прощание + кнопка в меню

clear_chat (callback: chat_clear):
- Очистить историю диалога (удалить из state или из Redis)
- "История диалога очищена"

### Payment handler
Создать: nura_app/bot/handlers/payment.py

initiate_full_report_payment (callback: pay_full_report:{token}):
- Проверить: платёж уже был?
- БЫЛ → ссылка на отчёт
- НЕТ:
  - Создать Payment через PaymentService.create_payment
  - Отправить ссылку на оплату (InlineKeyboardButton с URL)
  - "Ожидаем подтверждения оплаты..."
  - Запустить polling статуса / дождаться webhook

initiate_compatibility_payment (callback: pay_compatibility:{token}):
- Аналогично, но для совместимости

initiate_subscription (callback: buy_subscription):
- Создать recurrent платёж через PaymentService.create_subscription
- Отправить ссылку на оплату

### Error handler
Создать: nura_app/bot/handlers/errors.py

global_error_handler:
- Ловит любые исключения в dispatcher
- Отправляет пользователю: "Что-то пошло не так. Попробуй ещё раз через минуту."
- Логирует ошибку

### Регистрация router'ов
Файл: nura_app/bot/main.py

Подключить все новые router'ы:
- insights_router
- profile_router (переписать)
- chat_router
- payment_router
- errors (error handler)

После записи сделай commit с сообщением "Add bot handlers: insights, profile, chat, payment"
```

---

## Шаг 10 — Тесты

**Модель:** DeepSeek V4 Flash
**Агент:** `test-results-analyzer`
**Рецензент:** `code-reviewer`
**Вход:** `nura_app/core/services/matrix.py`, `nura_app/core/services/ai.py`, `nura_app/core/services/payment.py`

```
Прочитай nura_app/core/services/matrix.py — MatrixService.
Прочитай nura_app/core/services/ai.py — AIService.
Прочитай nura_app/core/services/payment.py — PaymentService.

Создать тесты:

### tests/test_matrix.py
- test_calculate_returns_matrix_data — вызов calculate с валидной датой
- test_calculate_22_arcana — проверить, что все 22 аркана определены
- test_calculate_sample_date_01_01_2000 — конкретная дата с конкретным результатом
- test_calculate_sample_date_15_06_1998 — ещё одна дата
- test_calculate_sample_date_31_12_2024 — граничная дата
- test_calculate_invalid_date — пустая строка, неверный формат
- test_get_archetype_name_returns_correct_name — для аркана 3 → "Императрица"
- test_get_archetype_name_invalid_number — 99 → None
- test_format_for_prompt_returns_string — форматирование не падает

### tests/test_ai.py
- test_mini_analysis_returns_correct_fields — проверить структуру MiniAnalysisResult
- test_full_report_returns_correct_fields — проверить структуру FullReportResult
- test_mini_analysis_fallback_on_error — таймаут → fallback-данные
- test_full_report_fallback_on_invalid_json — невалидный JSON → fallback

### tests/test_payment.py
- test_create_payment_returns_url — создание платежа возвращает ссылку
- test_check_payment_returns_status — проверка статуса

### tests/test_tasks.py
- test_mini_report_creates_report — вызов generate_mini_report
- test_mini_report_saves_to_db — проверка сохранения в БД

### tests/conftest.py
- Фикстуры: async session, test db, test user, test report

### tests/__init__.py
- Пустой

Использовать pytest-asyncio. БД — тестовая (SQLite или test PostgreSQL).
Убедись, что тесты запускаются через: pytest

После записи сделай commit с сообщением "Add tests"
```

---

## Быстрая шпаргалка

| Шаг | Что делает | Модель | Агент(ы) | Запускать после |
|-----|-----------|--------|----------|-----------------|
| 1 | DB модели + репозитории | V4 Pro | database-optimizer, backend-architect | — |
| 2 | Расчёт матрицы | V4 Pro | backend-architect | шага 1 |
| 3 | AI-сервис + промпты | V4 Pro | ai-engineer | шага 2 |
| 4 | Платежи + отчёты | V4 Flash | backend-architect | шага 3 |
| 5 | Celery tasks + beat | V4 Flash | devops-automator, backend-architect | шага 4 |
| 6 | API routes (webhook) | V4 Flash | backend-architect | шага 5 |
| 7 | Бот: middleware, states, keyboards, texts | V4 Flash | backend-architect, ux-architect, technical-writer | шага 6 |
| 8 | Бот: start, matrix, compatibility | V4 Flash | backend-architect, ux-architect | шага 7 |
| 9 | Бот: insights, profile, chat, payment | V4 Flash | ai-engineer, backend-architect, product-manager | шага 8 |
| 10 | Тесты | V4 Flash | test-results-analyzer | шага 9 |
