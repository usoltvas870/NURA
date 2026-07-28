# Интеграция Таро в NURA — 9 шагов

> **STATUS: MIXED — SESSION HISTORY, NOT CURRENT STATUS**
>
> Сохранено без переписывания на Stage 2A. Для current evidence используйте [implementation status](implementation/current-status.md), для target — [product spec](product/NURA_1_0_1_5_PRODUCT_SPEC.md).

> **Основание:** `docs/tarot-integration-plan.md` — стратегический план.
> **Цель:** реализовать таро-ритуалы на всех трёх поверхностях (бот, лендинг, отчёт).
> **Реальность:** кодовая база не содержит таро-логики — `_tarot_card.html` заглушка использует `current_year_arcana` (годовой) как карту дня, бот не имеет кнопок/хендлеров таро, лендинг не упоминает таро, платежи поддерживают только 390₽ подписку.
>
> **ВАЖНО: Все файлы — относительно `nura_app/`.**
> Рабочая директория: `C:\git\NURA\nura_app\`.

---

## Что скорректировано относительно tarot-integration-plan.md

| Было в плане | Реальность | Поправка |
|-------------|-----------|----------|
| `has_matrix`, `matrix_data` в `User` | `matrix_data` в `Report`, флага `has_matrix` нет | Поля в `User` + чтение `matrix_data` из `Report` при генерации раскладов |
| Замена `send_daily_insights` на `send_daily_card` | `send_daily_insights` работает и нужен | **Новая** задача `send_daily_card`, обе работают параллельно |
| Карта дня = `current_year_arcana` | Это аркан **года**, а не дня | Нужен алгоритм дневного аркана (day_of_year + модуляция по DOB) |
| `payment_type` в `Payment` + разовые платежи | `metadata` содержит только `subscription: true` | Расширить метаданные + `payment_type` в БД |
| 890₽ матрица как продукт | Нет продукта «матрица» | Создать `create_one_time_payment` в PaymentService |
| Меню: «Ритуалы дня» вместо «Чат с NURA» | Чат — ключевой функционал | Добавить «Ритуалы» **поверх** существующего меню, не заменяя |
| Промпты в `core/prompts/` | Основные в `nura_app/core/prompts/`, копия в `C:\git\NURA\core\prompts/` — устаревшая | Писать в `nura_app/core/prompts/`, вторую удалить/синхронизировать |

---

## Легенда моделей

| Метка | Модель | Когда |
|-------|--------|-------|
| ⚡ Flash | DeepSeek V4 Flash | CRUD, хендлеры, шаблоны, CSS, бот-логика |
| 🔥 Pro | DeepSeek V4 Pro | Схема БД, платежи, архитектура 2+ модулей |
| 📝 Kimi | Kimi K2.6 | Промпт-инжиниринг, длинные структурированные тексты |


---

## ШАГ 1 — Схема БД + платежи + конфиг

**Модель:** 🔥 Pro (архитектура, 2+ модуля: models, payment, api, config)

**Файлы:** `core/config.py`, `core/models.py`, `core/services/payment.py`, `api/routes/payment.py`, `alembic/` (миграция)

**Промпт:**
```
Задача: подготовить data layer для таро — модель, платежи, конфиг.

--- ЧАСТЬ 1: core/config.py ---
Добавить поля:
tarot_subscription_price_rub: int = 390
matrix_one_time_price_rub: int = 890
bot_username уже есть.

--- ЧАСТЬ 2: core/models.py ---
User — добавить поля:
tarot_subscription: bool = False
tarot_subscription_until: datetime | None = None

Payment — добавить поле:
payment_type: str = "subscription"  # "subscription" | "matrix" | "tarot"

--- ЧАСТЬ 3: core/services/payment.py ---
Три статических метода:
1. create_subscription(...) — существующий, без изменений
2. create_tarot_payment(telegram_id: int) -> dict:
   - сумма: settings.tarot_subscription_price_rub
   - metadata: {"telegram_id": telegram_id, "payment_type": "tarot"}
   - save_payment_method: True
   - description: "NURA — Таро-ритуалы (подписка)"
3. create_matrix_payment(telegram_id: int) -> dict:
   - сумма: settings.matrix_one_time_price_rub
   - metadata: {"telegram_id": telegram_id, "payment_type": "matrix"}
   - save_payment_method: False
   - description: "NURA — Полная матрица судьбы (разовый отчёт)"

--- ЧАСТЬ 4: api/routes/payment.py ---
Обновить webhook:
- Извлекать payment_type из metadata (по умолчанию "subscription")
- Если "tarot" → user_repo.update_tarot_subscription(user.id, True, 30 дней)
- Если "matrix" → user_repo.update_has_matrix(user.id, True)
- Если "subscription" → существующая логика (premium на 30 дней)

--- ЧАСТЬ 5: alembic миграция ---
Добавить поля в users: tarot_subscription (bool, default false),
tarot_subscription_until (timestamptz, nullable)
Добавить в payments: payment_type (varchar 20, default 'subscription')

После выполнения: ruff check core/models.py core/config.py core/services/payment.py api/routes/payment.py --fix
```

---

## ШАГ 2 — AI-промпты для таро (3 файла)

**Модель:** 📝 Kimi (промпт-инжиниринг)

**Файлы:** создать `core/prompts/tarot_daily_card.txt`, `core/prompts/tarot_weekly_spread.txt`, `core/prompts/tarot_question.txt`

**Промпт:**
```
Задача: создать 3 промпта для таро-раскладов. Все файлы в core/prompts/.
Tone-of-voice: ритуальный, метафоричный, на "ты". Запрещено: «гадание», «предсказание», «судьба как рок», «порча», «магия». Разрешено: «аркан», «расклад», «карта», «ритуал», «практика», «энергия».

--- Файл 1: tarot_daily_card.txt ---
Назначение: карта дня на основе даты рождения и текущей даты.
Вход: {user_name}, {birth_date}, {daily_arcana} (int 1-22), {matrix_context} (если есть — строка с позицией аркана в матрице пользователя).

Структура ответа JSON:
{
  "card_number": int,
  "card_name": str (название аркана),
  "key_phrase": str (ключевая фраза дня, 1 предложение),
  "interpretation": str (200-300 символов — как энергия аркана проявляется сегодня),
  "matrix_link": str (если matrix_context есть — как аркан связан с позицией в матрице),
  "advice": str (1-2 предложения — практическое действие на день),
  "affirmation": str (аффирмация дня, 1 фраза)
}

Требования:
- Интерпретация должна учитывать daily_arcana и дату рождения
- Если matrix_context передан — использовать его для углубления
- Тон: поддержка и любопытство, не запугивание

Верни ПОЛНЫЙ текст tarot_daily_card.txt.

--- Файл 2: tarot_weekly_spread.txt ---
Назначение: расклад на неделю — 3 карты (тело-ум-дух).
Вход: {user_name}, {birth_date}, {three_arcana: [body, mind, spirit]} (3 int 1-22), {matrix_context} (если есть).

Структура ответа JSON:
{
  "body": {"card_number": int, "card_name": str, "energy": str, "interpretation": str, "practice": str},
  "mind": {"card_number": int, "card_name": str, "energy": str, "interpretation": str, "practice": str},
  "spirit": {"card_number": int, "card_name": str, "energy": str, "interpretation": str, "practice": str},
  "overall": str (общий посыл недели, 2-3 предложения)
}

Каждая интерпретация: 150-200 символов. Практика: 1 предложение — конкретное действие на неделю.

Верни ПОЛНЫЙ текст tarot_weekly_spread.txt.

--- Файл 3: tarot_question.txt ---
Назначение: расклад по вопросу пользователя — 3 карты (прошлое-настоящее-будущее).
Вход: {user_name}, {birth_date}, {question}, {three_arcana: [past, present, future]} (3 int 1-22), {matrix_context} (если есть).

Структура ответа JSON:
{
  "past": {"card_number": int, "card_name": str, "meaning": str, "how_it_relates": str},
  "present": {"card_number": int, "card_name": str, "meaning": str, "how_it_relates": str},
  "future": {"card_number": int, "card_name": str, "meaning": str, "how_it_relates": str},
  "summary": str (сводка, 2-3 предложения),
  "advice": str (конкретный совет, 1-2 предложения)
}

Требования:
- Ответ привязан к вопросу пользователя (how_it_relates: «В контексте твоего вопроса про работу...»)
- Если matrix_context — указать позицию аркана в матрице
- Совет должен быть практическим, не эзотерическим

Верни ПОЛНЫЙ текст tarot_question.txt.
```

---

## ШАГ 3 — Бот: меню, навигация, роутер

**Модель:** ⚡ Flash

**Файлы:** `bot/keyboards/main_menu.py`, создать `bot/keyboards/tarot_keyboard.py`, создать `bot/handlers/tarot.py`, создать `bot/states/tarot_state.py`, создать `core/services/daily_arcana.py`

**Промпт:**
```
Задача: добавить таро-навигацию в бота — кнопка в главном меню, клавиатура ритуалов, роутер, FSM-состояния, алгоритм дневного аркана.

--- ЧАСТЬ 1: bot/keyboards/main_menu.py ---
В main_menu_keyboard():
- Добавить аргумент has_tarot: bool = False
- Если has_tarot — показать кнопку "🃏 Ритуалы дня" вместо тизера
- Иначе — показать "🃏 Карта дня" (тизер, ведёт на /ritual)
- Итоговая раскладка:
  [matrix_btn, insights]
  [tarot_btn, chat, compatibility]
  [profile]
(сохранить все существующие кнопки, добавить таро-строку)

--- ЧАСТЬ 2: bot/keyboards/tarot_keyboard.py (НОВЫЙ) ---
Функции:
- tarot_menu_keyboard() -> InlineKeyboardMarkup:
  Кнопки: "🂡 Карта дня", "🂠 Расклад недели", "❓ Задать вопрос", "🏠 В меню"
- tarot_back_keyboard() -> InlineKeyboardMarkup:
  Кнопка "🔙 Назад к ритуалам" + "🏠 В меню"

--- ЧАСТЬ 3: bot/states/tarot_state.py (НОВЫЙ) ---
Классы FSM:
- TarotStates(StatesGroup):
  - waiting_question = State()  # для расклада по вопросу

--- ЧАСТЬ 4: core/services/daily_arcana.py (НОВЫЙ) ---
Функция calculate_daily_arcana(birth_date: str) -> int:
- Парсит birth_date (DD.MM.YYYY)
- Берёт day_of_year от текущей даты
- Суммирует цифры day_of_year + sum(digits of DD) + sum(digits of MM)
- Свёртка до 1-22 (если >22 — редуцировать через сумму цифр)
- Возвращает int 1-22

Функция calculate_spread_arcanas(birth_date: str, count: int = 3) -> list[int]:
- Берёт daily_arcana как seed
- Генерирует count арканов: для i от 0 до count-1:
  arcana = (daily_arcana + i * 7) % 22 + 1 (смещение, чтобы не повторялись)
- Возвращает list[int]

--- ЧАСТЬ 5: bot/handlers/tarot.py (НОВЫЙ) ---
Роутер tarot_router = Router().

5.1. /ritual command:
- Ответ: меню ритуалов (tarot_menu_keyboard)
- Текст: "🃏 Ритуалы дня\n\nВыбери, что хочешь узнать сегодня:"

5.2. Callback "tarot_menu":
- Показать tarot_menu_keyboard

5.3. Callback "tarot_daily_card":
- Рассчитать аркан дня по сегодняшней дате (единый для всех)
- Отправить промежуточное сообщение "🌒 Вычисляю карту дня..."
- Загрузить prompt `tarot_daily_card_handler.txt`, заполнить {arcana_name}, {arcana_number}, {date}
- Вызвать AIService.chat() с заполненным промптом
- При ошибке: fallback "Сегодня карта говорит тише обычного"
- Отправить результат: `🌒 Карта дня — {name}\n{─*20}\n\n{interpretation}\n\n_Аркан {num} · {date}_`
- Клавиатура: tarot_back_keyboard()

5.4. Callback "tarot_weekly_spread":
- Вызвать AIService.generate_tarot_weekly_spread(user.birth_date)
- Отправить результат

5.5. Callback "tarot_ask_question":
- Установить TarotStates.waiting_question
- "Напиши свой вопрос — и я сделаю расклад по ситуации."

5.6. Message handler в TarotStates.waiting_question:
- Получить текст вопроса
- Вызвать AIService.generate_tarot_question(user.birth_date, question)
- Отправить результат

5.7. Проверка подписки:
- В каждом хендлере проверять user.tarot_subscription
- Если нет подписки — показывать тизер с кнопкой покупки

Зарегистрировать tarot_router в bot/__init__.py или bot/handlers/__init__.py.

После выполнения: ruff check bot/keyboards/ bot/handlers/tarot.py bot/states/tarot_state.py core/services/daily_arcana.py --fix
```

---

## ШАГ 4 — AI-сервис: таро-методы + интеграция в бота

**Модель:** ⚡ Flash

**Файлы:** `core/services/ai.py`, `core/services/daily_arcana.py`, `core/repositories/user.py`

**Промпт:**
```
Задача: добавить таро-методы в AIService, подключить к daily_arcana.

--- ЧАСТЬ 1: core/services/ai.py ---

1.1 Тарифные константы:
Добавить в класс AIService или отдельно:
TAROT_DAILY_MODEL = settings.deepseek_model
TAROT_SPREAD_MODEL = settings.deepseek_model
TAROT_QUESTION_MODEL = settings.deepseek_model

1.2 _get_matrix_context(user) -> str:
- Принимает объект User
- Если у пользователя есть полный отчёт (Report с FULL) — читает matrix_data
- Формирует строку: "В твоей матрице аркан X стоит в позиции Y (название позиции)."
- Если нет отчёта — возвращает пустую строку

1.3 generate_tarot_daily_card(birth_date: str, user) -> dict:
- Вычисляет daily_arcana = calculate_daily_arcana(birth_date)
- Получает matrix_context = _get_matrix_context(user)
- Загружает промпт tarot_daily_card.txt
- Форматирует: {user_name}, {birth_date}, {daily_arcana}, {matrix_context}
- Отправляет запрос к AI, парсит JSON
- Возвращает dict с card_number, card_name, key_phrase, interpretation, matrix_link, advice, affirmation

1.4 generate_tarot_weekly_spread(birth_date: str, user) -> dict:
- Вычисляет three_arcana = calculate_spread_arcanas(birth_date, 3)
- Получает matrix_context
- Загружает промпт tarot_weekly_spread.txt
- Форматирует, отправляет, парсит JSON
- Возвращает dict с body, mind, spirit, overall

1.5 generate_tarot_question(birth_date: str, question: str, user) -> dict:
- Вычисляет three_arcana = calculate_spread_arcanas(birth_date, 3) — на дату + seed от вопроса
- Получает matrix_context
- Загружает промпт tarot_question.txt
- Форматирует, отправляет, парсит JSON
- Возвращает dict с past, present, future, summary, advice

1.6 Обработка ошибок:
- Если AI не вернул валидный JSON — вернуть fallback-текст
- Если matrix_context пуст — просто опустить секцию в ответе

--- ЧАСТЬ 2: core/repositories/user.py ---
Добавить методы:
- update_tarot_subscription(user_id, status: bool, until: datetime | None)
- get_users_with_tarot() -> list[User] (для celery)
- get_has_matrix(user_id) -> bool (проверка наличия FULL-отчёта)

После выполнения: ruff check core/services/ai.py core/repositories/user.py --fix
```

---

## ШАГ 5 — Celery: ежедневная карта таро

**Модель:** ⚡ Flash

**Файлы:** `core/tasks.py`

**Промпт:**
```
Задача: добавить Celery beat-задачу для ежедневной рассылки карты таро.
Путь: core/tasks.py.

--- ЧАСТЬ 1: Расписание ---
Добавить в celery_app.conf.beat_schedule:
"send-daily-tarot-card": {
    "task": "core.tasks.send_daily_tarot_card",
    "schedule": crontab(hour=9, minute=15),  # на 15 мин позже инсайтов
}

--- ЧАСТЬ 2: Задача send_daily_tarot_card ---
@celery_app.task(name="core.tasks.send_daily_tarot_card")
def send_daily_tarot_card() -> dict:
    return _run_async(_send_daily_tarot_card_async())

async def _send_daily_tarot_card_async() -> dict:
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    users = await user_repo.get_users_with_tarot()

    sent = 0
    blocked = 0
    for i, user in enumerate(users):
        if i > 0 and len(users) > 50:
            await asyncio.sleep(0.5)
        if not user.birth_date:
            continue

        try:
            card = await AIService.generate_tarot_daily_card(user.birth_date, user)
        except Exception:
            continue

        text = format_daily_card_message(user.first_name, card)
        keyboard = {
            "inline_keyboard": [
                [{"text": "🂠 Расклад недели", "callback_data": "tarot_weekly_spread"}],
                [{"text": "🏠 В меню", "callback_data": "main_menu"}],
            ],
        }
        ok = await _send_message(user.telegram_id, text, keyboard)
        if ok:
            sent += 1
        else:
            async with session_factory() as session:
                db_user = await session.get(User, user.id)
                if db_user is not None:
                    db_user.tarot_subscription = False
                    await session.commit()
            blocked += 1
    return {"sent": sent, "blocked": blocked, "total": len(users)}

--- ЧАСТЬ 3: format_daily_card_message ---
Функция (вне класса, в tasks.py или отдельно):
def format_daily_card_message(first_name: str, card: dict) -> str:
    lines = [
        f"🃏 Твоя карта дня — {card['card_number']}. {card['card_name']}",
        "",
        card['key_phrase'],
        "",
        card['interpretation'],
    ]
    if card.get('matrix_link'):
        lines += ["", card['matrix_link']]
    lines += [
        "",
        f"💡 {card['advice']}",
        "",
        f"✨ {card['affirmation']}",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "Хочешь глубже? Загляни в ритуалы дня.",
    ]
    return "\n".join(lines)

--- ЧАСТЬ 4: НЕ трогать ---
Не изменять send_daily_insights и _send_daily_insights_async.
Не изменять существующее расписание.

После выполнения: ruff check core/tasks.py --fix
```

---

## ШАГ 6 — Визуальный скин таро в боте (HTML-сообщения)

**Модель:** ⚡ Flash

**Файлы:** создать (опционально) `bot/helpers/tarot_formatter.py`, обновить `bot/handlers/tarot.py`

**Промпт:**
```
Задача: форматировать таро-сообщения в боте с HTML-разметкой.
Сине-золотой скин: фон #1a2a3a, акцент #c9a96e, рамка золотая.

--- bot/helpers/tarot_formatter.py (НОВЫЙ) ---

HTML_TAROT_CARD = '''\
<blockquote style="background:#1a2a3a;border:1px solid #c9a96e;border-radius:12px;padding:16px;margin:8px 0;">
  🃏 <b>Твоя карта дня — {number}. {name}</b>
</blockquote>
'''

HTML_TAROT_SPREAD = '''\
<blockquote style="background:#1a2a3a;border:1px solid #c9a96e;border-radius:12px;padding:16px;margin:8px 0;">
  <b>{title}</b>
  <i>{arcana_name}</i>
  {interpretation}
</blockquote>
'''

Функция format_tarot_message(card_data: dict, message_type: str = "daily") -> str:
  - Для daily: использует HTML_TAROT_CARD + интерпретацию + advice + affirmation
  - Для spread: использует HTML_TAROT_SPREAD × 3 + overall
  - Для question: HTML_TAROT_SPREAD × 3 (прошлое/настоящее/будущее) + summary + advice
  - Все сообщение обёрнуто в <b> разделители

Функция format_tarot_paywall() -> str:
  - "🃏 Таро-ритуалы — это ежедневные расклады на основе твоей матрицы."
  - CTA с кнопкой подписки

--- Обновить bot/handlers/tarot.py ---
В хендлерах вместо обычного text использовать format_tarot_message.
ParseMode везде HTML (уже установлен DefaultBotProperties).
Если у пользователя нет tarot_subscription — показывать paywall вместо расклада.

После выполнения: ruff check bot/helpers/ bot/handlers/tarot.py --fix
```

---

## ШАГ 7 — Лендинг: таро-контент + вёрстка

**Модель:** ⚡ Flash (один файл `index.html`, 1598 строк — стили + копирайтинг встроены)

**Файлы:** `C:\git\NURA\index.html`

**Промпт:**
```
Задача: обновить index.html — добавить таро-контент и тариф.
Текущий лендинг: Hero «Матрица Судьбы + AI-чат», 2 тарифа (бесплатно / 390₽), 4 benefits, 7 FAQ.
Нужно: два столпа (матрица + таро), 3 тарифа, +1 benefit, +2 FAQ, новый блок #tarot-preview, CTA две кнопки.

--- Тексты (встроить в HTML) ---

1. Hero (заголовок + подзаголовок):
   <h1>Матрица Судьбы + Таро-ритуалы<br>Узнай свой код и управляй энергией дня</h1>
   <p class="hero-sub">Единственный сервис, где арканы таро работают через твою матрицу — не гадание, а аналитика твоей энергии</p>

2. #benefits — добавить 5-ю карточку (последней):
   <div class="benefit-card">
     <div class="benefit-icon">🃏</div>
     <h3>Ежедневная карта Таро</h3>
     <p>Каждое утро — новый аркан, интерпретированный через позиции твоей матрицы. Не случайная карта, а энергия дня, привязанная к твоему коду судьбы.</p>
   </div>

3. #tarot-preview — новый блок перед #pricing:
   <section id="tarot-preview" style="background:linear-gradient(135deg,#1a2a3a,#0f1a2a);padding:100px 0;margin-top:60px">
     <div class="container">
       <h2 style="color:#c9a96e;font-family:'Cormorant Garamond',serif">Как работает таро в NURA</h2>
       <div class="tarot-steps">
         <div class="tarot-step"><span class="tarot-step-num">1</span><h4>Анализ твоей матрицы</h4><p>Мы знаем твои 22 аркана и их позиции</p></div>
         <div class="tarot-step"><span class="tarot-step-num">2</span><h4>Карта дня</h4><p>Каждое утро — новый аркан, связанный с твоей матрицей</p></div>
         <div class="tarot-step"><span class="tarot-step-num">3</span><h4>Расклады</h4><p>Неделя, вопрос, ситуация — с привязкой к твоим энергиям</p></div>
       </div>
       <div class="tarot-card-preview">
         <div class="tarot-mini-card">VIIII</div>
         <p class="tarot-hover-text">Наведи на карту ✦</p>
       </div>
     </div>
   </section>

4. #pricing — переделать на 3 колонки:
   - Бесплатно: мини-матрица + 5 сообщений в чате
   - Матрица 890 ₽ (разово, featured оранжевый): полный отчёт 15 секций, PDF, навигация
   - Таро-подписка 390 ₽/мес (сине-золотой): ежедневная карта дня, расклад недели, расклад по вопросу

5. #faq — добавить 2 вопроса в конец списка:
   <div class="faq-item">
     <h3>Чем таро-ритуалы отличаются от обычного гадания?</h3>
     <p>В основе каждого расклада — твоя матрица судьбы. Мы не гадаем, а анализируем энергию арканов в контексте твоих 22 позиций. Это аналитика, а не предсказание.</p>
   </div>
   <div class="faq-item">
     <h3>Нужна ли полная матрица для ритуалов?</h3>
     <p>Базовая карта дня доступна по дате рождения. Полные расклады с привязкой ко всем позициям матрицы — после покупки полной матрицы.</p>
   </div>

6. CTA — заменить на две кнопки:
   <a href="..." class="btn-primary">Купить матрицу 890 ₽</a>
   <a href="https://t.me/Nura_ai_bot" class="btn-secondary">🃏 Попробовать карту дня</a>

--- CSS (добавить в существующий <style>) ---

:root {
  --tarot-blue: #1a2a3a;
  --tarot-gold: #c9a96e;
}

.tarot-steps { display:grid; grid-template-columns:repeat(3,1fr); gap:24px; margin:40px 0; }
.tarot-step { padding:24px; background:rgba(255,255,255,0.03); border:1px solid rgba(201,169,110,0.2); border-radius:12px; text-align:center; }
.tarot-step-num { display:inline-block; width:36px; height:36px; line-height:36px; border-radius:50%; background:var(--tarot-gold); color:#1a2a3a; font-weight:700; margin-bottom:12px; }
.tarot-step h4 { color:var(--tarot-gold); font-family:'Cormorant Garamond',serif; margin:0 0 8px; }
.tarot-step p { color:var(--muted); font-size:14px; margin:0; }

.tarot-card-preview { text-align:center; margin-top:40px; }
.tarot-mini-card { display:inline-block; width:80px; height:112px; background:linear-gradient(135deg,#1a2a3a,#2a3a4a); border:2px solid var(--tarot-gold); border-radius:8px; line-height:112px; font-family:'Cormorant Garamond',serif; font-size:28px; color:var(--tarot-gold); transition:transform .4s ease; margin-bottom:12px; }
.tarot-mini-card:hover { transform:rotateY(180deg); }
.tarot-hover-text { font-size:12px; color:rgba(201,169,110,0.5); }

.pricing-tarot { background:linear-gradient(135deg,#1a2a3a,#0f1a2a); border:1px solid var(--tarot-gold); }
.pricing-tarot .pricing-name { color:var(--tarot-gold); }
.pricing-tarot .pricing-price { color:#fff; }

@media (max-width:768px) {
  .tarot-steps { grid-template-columns:1fr; }
}

Сохранить все существующие секции и стили без изменений. Верни ПОЛНЫЙ обновлённый index.html.
```
```

---

## ШАГ 8 — Отчёт: исправление таро-блока

**Модель:** ⚡ Flash

**Файлы:** `templates/reports/_tarot_card.html`, `core/services/daily_arcana.py`, `core/services/report.py`, `full_report.html`

**Промпт:**
```
Задача: исправить _tarot_card.html — заменить current_year_arcana (годовой) на daily_arcana.
Текущая заглушка использует аркан года как карту дня — это неверно.

--- ЧАСТЬ 1: core/services/daily_arcana.py ---
Добавить функцию get_today_arcana_with_name(birth_date: str, arcana_names: dict) -> dict:
- Вычисляет daily_arcana = calculate_daily_arcana(birth_date)
- Получает название из arcana_names
- Возвращает {"number": int, "name": str}

--- ЧАСТЬ 2: core/tasks.py (_process_full_report) ---
Добавить в report_data:
- "daily_tarot_arcana": get_today_arcana_with_name(birth_date, matrix.arcana_names)
Оставить current_year_arcana — он нужен для других секций отчёта.

--- ЧАСТЬ 3: templates/reports/_tarot_card.html ---
Заменить:
{% if current_year_arcana %}
...
{{ current_year_arcana }}
{% endif %}

На:
{% if daily_tarot_arcana %}
<div class="tarot-card-daily">
  <div class="tarot-card-visual">
    <span class="tarot-card-num">{{ daily_tarot_arcana.number }}</span>
    <span class="tarot-card-name">{{ daily_tarot_arcana.name }}</span>
  </div>
  <p class="tarot-card-insight">
    Сегодня твой день проходит под энергией аркана {{ daily_tarot_arcana.number }} — {{ daily_tarot_arcana.name }}.
    Это не случайность: энергия этого аркана резонирует с твоей матрицей именно сегодня.
    Прислушайся: о чём она говорит тебе?
  </p>
</div>
{% endif %}

--- ЧАСТЬ 4: templates/reports/full_report.html ---
Убедиться что _tarot_card.html включается с правильными данными:
{% include '_tarot_card.html' %}
(daily_tarot_arcana передаётся через контекст)

--- ЧАСТЬ 5 (опционально): _tarot_card.html визуал ---
Добавить CSS-анимацию: свечение золотом по краям карты, лёгкая пульсация.
Цвета: --tarot-blue: #1a2a3a, --tarot-gold: #c9a96e (уже есть в _styles.html).
```

---

## ШАГ 9 — Финальная интеграция + тесты

**Модель:** 🔥 Pro (все модули)

**Файлы:** все изменённые

**Промпт:**
```
Финальная проверка целостности интеграции таро.

Проверить:

1. core/models.py:
   - User: tarot_subscription (bool), tarot_subscription_until (datetime | None)
   - Payment: payment_type (str, default 'subscription')

2. core/services/payment.py:
   - create_subscription — без изменений
   - create_tarot_payment — metadata.payment_type = "tarot"
   - create_matrix_payment — metadata.payment_type = "matrix"

3. api/routes/payment.py:
   - Извлекает payment_type из metadata
   - payment_type == "tarot" → update_tarot_subscription
   - payment_type == "matrix" → update_has_matrix
   - payment_type == "subscription" → существующая логика

4. core/services/daily_arcana.py:
   - calculate_daily_arcana(birth_date) -> int 1-22 (алгоритм: day_of_year + DOB модуляция)
   - calculate_spread_arcanas(birth_date, count) -> list[int]
   - get_today_arcana_with_name(birth_date, arcana_names) -> dict

5. core/services/ai.py:
   - generate_tarot_daily_card(birth_date, user) -> dict
   - generate_tarot_weekly_spread(birth_date, user) -> dict
   - generate_tarot_question(birth_date, question, user) -> dict
   - _get_matrix_context(user) -> str

6. core/prompts/:
   - tarot_daily_card.txt — JSON: card_number, card_name, key_phrase, interpretation, matrix_link, advice, affirmation
   - tarot_weekly_spread.txt — JSON: body, mind, spirit, overall
   - tarot_question.txt — JSON: past, present, future, summary, advice

7. core/tasks.py:
   - send_daily_tarot_card — Celery beat в 9:15
   - format_daily_card_message — форматирует карту в текст
   - send_daily_insights — НЕ изменён

8. bot/handlers/tarot.py:
   - /ritual → меню ритуалов
   - tarot_daily_card → генерация + отправка
   - tarot_weekly_spread → генерация + отправка
   - tarot_ask_question → FSM → генерация + отправка
   - Проверка подписки перед каждым раскладом

9. bot/keyboards/main_menu.py:
   - Кнопка таро в главном меню (после/вместо в зависимости от has_tarot)
   - Все существующие кнопки сохранены

10. bot/keyboards/tarot_keyboard.py:
    - tarot_menu_keyboard — 4 кнопки
    - tarot_back_keyboard — 2 кнопки

11. templates/reports/_tarot_card.html:
    - Использует daily_tarot_arcana вместо current_year_arcana
    - Визуальная карта с анимацией

12. C:\git\NURA\index.html:
    - Hero обновлён
    - #benefits +1 карточка
    - #tarot-preview новый блок
    - #pricing 3 продукта
    - #faq +2 вопроса
    - CTA две кнопки

Напиши скрипт проверки целостности (Python, без зависимостей от проекта):
- Проверить все импорты в новых файлах
- Проверить, что все callback_data уникальны (tarot_daily_card, tarot_weekly_spread, tarot_ask_question, tarot_menu)
- Проверить, что tarot_router зарегистрирован
- Вывести отчёт: "✅ OK" или "❌ Проблема: ..."

Запусти ruff check . --fix и pytest (если есть тесты).
```

---

## Таблица зависимостей

| Шаг | Зависит от | Суть |
|-----|-----------|------|
| 1 | — | Схема БД + платежи + конфиг |
| 2 | — | AI-промпты для таро (3 файла) |
| 3 | 1 | Бот: меню, навигация, роутер, daily_arcana |
| 4 | 2, 3 | AI-сервис: таро-методы |
| 5 | 4, 3 | Celery: ежедневная карта таро |
| 6 | 3, 4 | Визуальный скин в боте |
| 7 | 1 | Лендинг: контент + вёрстка |
| 8 | 4 | Отчёт: исправление таро-блока |
| 9 | все | Финальная интеграция + тесты |
| 10 | 6 | Переработка AI-промптов (запрет арканов, 3 абзаца, «Как использовать:») |
| 11 | 6 | Утилита форматирования + HTML-рендеринг (жирный, курсив, parse_mode) |
| 12 | 6 | Анимация загрузки 🃏 (вращающиеся полукруги, animated_loading) |

**Порядок запуска:**
(1 + 2 параллельно) → (3 + 7 параллельно) → (4 + 8 параллельно) → 5 → 6 → 9

---

## ШАГ 10 — Переработка AI-промптов (задача 6)

**Модель:** ⚡ Flash

**Статус:** ✅ Выполнено (28.05.2026)

**Файлы:**
- `core/prompts/tarot_doubles.txt` — перезаписан
- `core/prompts/tarot_spheres.txt` — перезаписан
- `core/prompts/tarot_yes_no.txt` — перезаписан
- `core/prompts/tarot_question.txt` — перезаписан
- `core/prompts/tarot_portal.txt` — перезаписан

**Суть:**
Все 5 промптов полностью перезаписаны со строгими правилами:
1. Запрет на названия арканов и их номера в тексте (только психологические качества)
2. Текст из 3 абзацев с пустыми строками
3. Первое предложение каждого абзаца — ключевая мысль
4. Блок «Как использовать:» в конце с конкретным действием
5. Запрещённые слова: энергия, вибрация, вселенная, карма, аркан, карта, таро, предначертано
6. Максимум 150-350 слов в зависимости от расклада

**Системный промпт** в `bot/handlers/tarot.py` обновлён во всех 6 вызовах:
```
Ты — NURA, психологический проводник.
Никогда не называй арканы, карты и их номера в тексте ответа.
Переводи их в психологические качества и состояния.
Пиши живым человеческим языком без эзотерического жаргона.
```

---

## ШАГ 11 — Утилита форматирования + HTML-рендеринг (задача 6)

**Модель:** ⚡ Flash

**Статус:** ✅ Выполнено (28.05.2026)

**Файлы:**
- `bot/utils/__init__.py` — создан
- `bot/utils/formatting.py` — создан

**Функции:**
- `format_bot_text(text)` — очистка от лишних переносов и HTML-тегов
- `format_tarot_result(title, body, cards, action)` — структура: `<b>заголовок</b>` + разделитель + абзацы (3 предложения, первое жирное) + разделитель + `<i>карты</i>`
- `format_compatibility_result(user_name, partner_name, ...)` — формат совместимости с именами
- `_split_into_paragraphs(text, sentences_per_para=3)` — разбивка на абзацы с bold первого предложения

**Интеграция:**
Все 6 таро-хендлеров в `tarot.py` используют `format_tarot_result` вместо ручной сборки f-строк.
Все 6 вызовов `edit_text`/`answer` используют `parse_mode="HTML"` для рендеринга `<b>`/`<i>`.

---

## ШАГ 12 — Анимация загрузки (задача 6б)

**Модель:** ⚡ Flash

**Статус:** ✅ Выполнено (28.05.2026)

**Файлы:**
- `bot/utils/loading.py` — создан

**Контекстный менеджер `animated_loading(message, text)`:**
- Пока выполняется async-операция (AI-запрос), циклически обновляет текст сообщения
- Вращающиеся полукруги `◐ ◓ ◑ ◒` каждые 0.5 сек
- 🃏 эмодзи карты вместо 🌒 луны в сообщениях загрузки
- При выходе из контекста анимация останавливается

**Интеграция в `tarot.py`:**
Все 6 раскладов обёрнуты в `async with animated_loading(msg, "🃏 Текст загрузки"):`
с корректным re-indent try/except блоков (+4 пробела).
