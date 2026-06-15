# NURA — План исправления технического долга и завершения активных задач

> **Для Hermes:** использовать nura-dev skill + CAVEMAN-протокол. Выполнять task-by-task.
>
> **Goal:** Закрыть технический долг, обнаруженный при аудите 15.06.2026, и довести до конца незакрытые задачи из STATE.md.
>
> **Source of Truth:** `STATE.md` + `docs/launch-checklist.md` + этот план.

---

## Сводка обнаруженных проблем (аудит 15.06.2026)

| # | Проблема | Серьёзность | Где |
|---|----------|------------|-----|
| 1 | `config.py` — пропавшие поля (дыра строк 37-76), `redis_url` с мусором, `database_url_sync` с `***` | 🔴 Критическая | `core/config.py` |
| 2 | `ARCANA_DATA` — 3 независимых источника с разными именами | 🔴 Критическая | `api/routes/tarot_pwa.py`, `bot/handlers/tarot.py`, `core/services/matrix.py` |
| 3 | `launch-checklist.md` — катастрофически устарел: PWA P0/P1, виральные механики, Alembic-миграции, реферальная система — всё ✅ ГОТОВО, но в чеклисте 🔴 | 🟡 Важная | `docs/launch-checklist.md` |
| 4 | YooKassa credentials — плейсхолдеры, блокирует монетизацию | 🔴 Блокер | `.env` на VPS |
| 5 | Тесты — 994 LOC на ~13K Python (~7.6%), нет интеграционных, нет тестов routes/bot/payments | 🟡 Важная | `tests/` |
| 6 | Fallback-тексты (~200 строк) захардкожены в `ai.py` | 🟡 Важная | `core/services/ai.py` |
| 7 | AI-сервис захардкожен на DeepSeek — нет абстракции провайдера | 💭 P2 | `core/services/ai.py` |
| 8 | `scripts/` — 15+ build-скриптов, часть одноразовые/экспериментальные | 💭 P2 | `scripts/` |
| 9 | `test_mode` в конфиге — bypass подписок в проде опасен | 🟡 Важная | `core/config.py` |
| 10 | PWA-фронт не в Docker — статика на хосте | 💭 P2 | `frontend/`, nginx |

## Активные незакрытые задачи из STATE.md (11.06.2026)

| # | Задача | Статус |
|---|--------|--------|
| A | 🔴 Сгенерировать реальный отчёт → `sample-report.html` + деплой на лендинг | 🔴 |
| B | 🟡 Фикс why-аккордеон — стиль кода с `//` в S3–S13 | 🟡 |
| C | 🟡 Диагностика: Карта здоровья + Психоблоки — проверка данных в БД | 🟡 |
| D | 🟡 PDF совместимости — ограничить до романтики для подписчиков | 🟡 |
| E | 🟡 send_daily_card — батчинг при росте базы (кэш по архетипу) | 🟡 |
| F | 💭 PEXELS_API_KEY — не добавлен | 💭 |
| G | 🟡 docs/tarot-integration-plan.md — добавить раздел «Таро в PWA» | 🟡 |

---

## Этап 1: Критическое (P0) — сегодня

### 1.1 Восстановить config.py

**Проблема:** поля `deepseek_api_key`, `deepseek_base_url`, `deepseek_model`, `celery_broker_url`, `celery_result_backend`, `telegram_bot_token`, `bot_username`, `yookassa_shop_id`, `yookassa_secret_key`, `report_base_url`, `subscription_price_rub`, `tarot_subscription_price_rub`, `matrix_one_time_price_rub` используются через `settings.XXX` но НЕ объявлены в классе. Работает чудом из-за `extra="ignore"` + `.env`.

Также: `redis_url` дефолт `"redis://localhost:***@nura_support"` — мусор. `database_url_sync` хардкодит `***`.

**Файл:** `nura_app/core/config.py`

**Действия:**
1. Объявить все недостающие поля явно с `Optional[str] = None`:
   ```python
   deepseek_api_key: str | None = None
   deepseek_base_url: str = "https://api.deepseek.com/v1"
   deepseek_model: str = "deepseek-chat"
   telegram_bot_token: str | None = None
   bot_username: str | None = None
   yookassa_shop_id: str | None = None
   yookassa_secret_key: str | None = None
   report_base_url: str = "https://nura-ai.ru"
   subscription_price_rub: int = 590
   tarot_subscription_price_rub: int = 390
   matrix_one_time_price_rub: int = 890
   celery_broker_url: str = "redis://localhost:6379/1"
   celery_result_backend: str = "redis://localhost:6379/2"
   test_mode: bool = False
   ```
2. Исправить `redis_url` дефолт:
   ```python
   redis_url: str = "redis://localhost:6379/0"
   ```
3. Исправить `database_url_sync` — убрать `***`:
   ```python
   @property
   def database_url_sync(self) -> str:
       return (
           f"postgresql://{self.postgres_user}:"
           f"{self.postgres_password}@{self.postgres_host}:"
           f"{self.postgres_port}/{self.postgres_db}"
       )
   ```
4. Убрать `extra="ignore"` из model_config → заменить на `extra="forbid"` чтобы ловить опечатки.

**Верификация:** `python -c "from core.config import settings; print(settings.deepseek_model)"` в venv.

---

### 1.2 ARCANA_DATA — единый источник истины

**Проблема:** три определения арканов с разными именами и полями:
- `api/routes/tarot_pwa.py` — `ARCANA_DATA` (name, symbol, phrase, interpretation, advice, affirmation)
- `bot/handlers/tarot.py` — `ARCANA` (только name, отличается: "Маг" vs "Маг" ок, но "Верховная Жрица" vs "Жрица")
- `core/services/matrix.py` — `ARCANA` (name, emoji, key)

**Файлы:** создать `core/arcana_data.py`, рефакторить все три места.

**Действия:**
1. Создать `nura_app/core/arcana_data.py` с единым источником:
   ```python
   ARCANA: dict[int, dict] = {
       1: {"name": "Маг", "emoji": "✨", "symbol": "🪄", "key": "Воля, мастерство, начало",
           "phrase": "Воля и мастерство",
           "interpretation": "Сегодня твоя воля особенно сильна...",
           "advice": "Возьмись за дело, которое откладывал...",
           "affirmation": "Я создаю реальность силой намерения"},
       # ... 2-22
   }
   ```
2. В `core/services/matrix.py`: заменить `ARCANA = {...}` на `from core.arcana_data import ARCANA`.
3. В `bot/handlers/tarot.py`: заменить локальный `ARCANA` на импорт.
4. В `api/routes/tarot_pwa.py`: заменить локальный `ARCANA_DATA` на импорт.
5. Проверить имена: в bot было "Верховная Жрица" (строка 31 `bot/handlers/tarot.py`), в pwa — "Жрица" (строка 17 `tarot_pwa.py`). Выбрать один вариант, унифицировать во всём коде.

**Верификация:** `ruff check .` + `pytest tests/ -v`.

---

### 1.3 Обновить launch-checklist.md

**Проблема:** почти всё что помечено 🔴/🟡 уже ГОТОВО в STATE.md. Чеклист вводит в заблуждение.

**Файл:** `docs/launch-checklist.md`

**Действия:**
1. **Блок 1 (Alembic):** отметить все строки ✅ — миграции готовы (6 штук, head: b2c3d4e5f6a7).
2. **Блок 3 (Бот):** все P0/P1 ✅ — deep-link, виральные механики, рефералка, link-токен, карточка-картинка.
3. **Блок 4 (PWA P0):** все ✅ — manifest, SW, Web Push, VAPID, install UI.
4. **Блок 5 (PWA P1):** все ✅ — 4 экрана, таббар, Web Share, подписка через веб.
5. **Блок 6 (Миграция пользователей):** ✅ grandfather clause сделан.
6. **Блок 7 (Отчёт V2):** обновить статус — 15 секций ✅, kitchen ✅, психоблоки ✅, здоровье ✅. Остался why-аккордеон и sample-report.
7. **Сводка:** пересчитать итоговые часы (реально осталось ~20-30ч, не 206ч).
8. **Порядок запуска:** удалить (уже не актуально, почти всё сделано).

**Верификация:** сравнить с STATE.md построчно.

---

## Этап 2: STATED.md задачи (P1) — сегодня/завтра

### 2.1 Сгенерировать sample-report.html + деплой

**Задача A из STATE.md.** Эталонный отчёт уже есть: `https://nura-ai.ru/report/a33a768e958e4ceb9388a8cf43392fe8`. Нужно сохранить HTML в репозиторий и добавить ссылку на лендинг.

**Действия:**
1. Скопировать HTML из отчёта (curl с VPS или через существующий endpoint).
2. Сохранить как `nura_app/templates/reports/sample-report.html`.
3. Добавить на лендинг `index.html` секцию с кнопкой «Посмотри пример отчёта» → `/sample-report`.
4. Nginx: location `/sample-report` → отдаёт этот файл.
5. Деплой: `bash scripts/deploy.sh`.

**Верификация:** открыть `https://nura-ai.ru/sample-report` — видно отчёт.

---

### 2.2 Фикс why-аккордеон

**Задача B из STATE.md.** В kitchen-аккордеоне S3–S13 стиль кода с `//` слитно.

**Файлы:** `templates/reports/full_report_v2.html` (секции `_why_block`)

**Действия:**
1. Найти шаблон `_why_block` или inline-код why-секций.
2. Обернуть `// ...` строки в `<pre><code>` или добавить `<br>` после `//`.
3. Проверить на эталонном отчёте.
4. Деплой api.

**Верификация:** открыть отчёт с kitchen-данными, аккордеон раскрывается, код читаемый.

---

### 2.3 Диагностика: Карта здоровья + Психоблоки

**Задача C из STATE.md.** Проверить что секции не пустые в старых отчётах.

**Действия:**
1. Запросить `kitchen_analysis` для отчёта `a33a768e958e4ceb9388a8cf43392fe8`.
2. Проверить что `chakra_data` и `psych_blocks` есть.
3. Если пустые — догенерировать через AI.
4. Проверить 2-3 других отчёта из БД.
5. Если всё ок — закрыть задачу.

---

## Этап 3: Технический долг (P1) — неделя

### 3.1 Fallback-тексты вынести из ai.py

**Файлы:** `core/services/ai.py` (строки 97-258: FALLBACK_MINI, FALLBACK_FULL, FALLBACK_COMPATIBILITY, FALLBACK_CHAT, FALLBACK_TAROT_*)

**Действия:**
1. Создать `core/fallbacks.py`.
2. Переместить туда все FALLBACK_* словари.
3. В `ai.py` заменить на `from core.fallbacks import ...`.
4. ruff check + pytest.

---

### 3.2 Поднять покрытие тестами

**Текущее:** 994 строк тестов, ~7.6%.

**Действия:**
1. Тесты `core/services/matrix.py` — уже есть 76 строк, можно расширить edge cases (sum_digits граничные, calculate с високосным годом, format_for_prompt полнота вывода).
2. Тесты `api/routes/tarot_pwa.py` — новый файл `tests/test_tarot_pwa.py`, мокнуть HTTP-запросы, проверить коды ответов (200/402/404).
3. Тесты `api/routes/payment.py` — проверить webhook с моком YooKassa.
4. Тесты `bot/handlers/tarot.py` — unit-тесты с моком aiogram.
5. Цель: ≥40% coverage (~5000 строк тестов).

---

### 3.3 PDF совместимости — ограничить

**Задача D из STATE.md.** Сейчас PDF генерируется для всех типов отношений, нужно только для романтики.

**Файлы:** `core/tasks.py` → `_process_compatibility_report()`, `bot/handlers/compatibility.py`

**Действия:**
1. В хендлере совместимости: показывать кнопку «📥 Скачать PDF» только если `relation_type == "романтика"`.
2. В Celery-таске: добавить проверку `relation_type` перед генерацией PDF.
3. ruff check + тест.

---

### 3.4 send_daily_card — батчинг

**Задача E из STATE.md.** Сейчас при росте базы >50 пользователей включается `sleep(0.05)` между отправками — наивный подход.

**Действия:**
1. Кэшировать карту дня по архетипу: `ARENA_CACHE[archetype_number]` → готовый текст, AI-вызов только 1 раз для каждого архетипа.
2. Использовать `asyncio.gather` с семафором (concurrency=5) вместо последовательных sleep.
3. Логировать: сколько отправлено, сколько провалено.

---

## Этап 4: P2 — когда будет время

### 4.1 AI-сервис: абстракция провайдера

**Сейчас:** `ai.py` жёстко привязан к DeepSeek (headers, URL, модель).

**План:**
- Базовый класс `AIProvider` с методом `chat(messages, params) -> str`.
- `DeepSeekProvider` — текущая логика.
- `OpenAIProvider` — для будущего переключения.
- `settings.ai_provider` — выбор провайдера.

### 4.2 CI/CD (GitHub Actions)

- Lint + test на каждый push.
- Деплой на VPS при merge в main.
- `.github/workflows/ci.yml`.

### 4.3 PWA фронт в Docker

- Dockerfile для nginx + статики PWA.
- docker-compose: контейнер `pwa`.
- Синхронизация статики через volume.

### 4.4 Очистить scripts/

- Удалить одноразовые build-скрипты (`build_fx.py`, `build_zoomin.py` итд).
- Оставить только `deploy.sh`, `assemble.py`, `from_plan.py`.

### 4.5 test_mode — обезопасить

- Добавить проверку `APP_ENV=production` — test_mode игнорируется в проде.
- Явный warning в логах.

---

## Сводка: время и приоритеты

| Этап | Задач | Часов | Приоритет |
|------|-------|-------|-----------|
| 1.1 config.py | 1 | 0.5 | 🔴 P0 |
| 1.2 ARCANA_DATA | 1 | 2 | 🔴 P0 |
| 1.3 launch-checklist | 1 | 1 | 🔴 P0 |
| 2.1 sample-report | 1 | 1.5 | 🔴 P0 (из STATE.md) |
| 2.2 why-аккордеон | 1 | 1 | 🟡 P1 |
| 2.3 диагностика здоровье | 1 | 1 | 🟡 P1 |
| 3.1 fallbacks out | 1 | 0.5 | 🟡 P1 |
| 3.2 тесты | 4 | 8-12 | 🟡 P1 |
| 3.3 PDF ограничение | 1 | 1 | 🟡 P1 |
| 3.4 батчинг | 1 | 2 | 🟡 P1 |
| 4.1 провайдер AI | 1 | 4 | 💭 P2 |
| 4.2 CI/CD | 1 | 3 | 💭 P2 |
| 4.3 PWA docker | 1 | 2 | 💭 P2 |
| 4.4 очистить scripts | 1 | 0.5 | 💭 P2 |
| 4.5 test_mode safe | 1 | 0.5 | 💭 P2 |
| **Всего P0** | **4** | **5** | |
| **Всего P0+P1** | **11** | **~18-22** | |
| **Всего** | **16** | **~28-32** | |

---

## Не в этом плане (сторонние блокеры)

- 🔴 **YooKassa credentials** — ждёт владельца. Когда появятся: E2E-тест оплаты, проверить webhook на VPS.
- 💭 **PEXELS_API_KEY** — не критично, стоки загружаются вручную.
- 🟡 **Celery result backend warning** — не блокирует, но в логах шум. Починить при рефакторинге конфига.

---

## Порядок выполнения

```
Сегодня:
  1.1 → 1.2 → 1.3          (конфиг + арканы + чеклист)
  2.1                       (sample-report)

Завтра:
  2.2 → 2.3                  (why-аккордеон + диагностика)

Неделя:
  3.1 → 3.4 → 3.3 → 3.2    (fallbacks → батчинг → PDF → тесты)

Когда время:
  4.1 → 4.2 → 4.5 → 4.3 → 4.4
```

---

**План создан:** 15.06.2026, DeepSeek V4 Flash.
**Source of Truth:** `STATE.md` (Сессия 39), `docs/launch-checklist.md`, аудит кода.
