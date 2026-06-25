# NURA — Технический аудит

Формат: `[CRITICAL|WARNING|INFO] [файл:строка] Описание → Исправление`

---

## СЕССИЯ 1 — Фронтенд ↔ Бэкенд контракт (Области 1, 3, 9)

### CRITICAL

[CRITICAL] [frontend/pwa/app/profile.html:143] Читается несуществующее поле `d.matrix_arcane_num` из ответа `/web/me`. Backend (web.py:33-44) возвращает `has_matrix` (bool) и `archetype_number` (int), поля `matrix_arcane_num` нет → статус «Матрица Судьбы: Купить» никогда не обновляется до «Куплена» даже после оплаты, кнопка «Открыть» остаётся скрытой.
→ Заменить `if (d.matrix_arcane_num)` на `if (d.has_matrix)`. Idempotent: можно также показывать полноценный отчёт через `d.reports[].report_type === 'full'`.

[CRITICAL] [mini.html:185-186] Читаются `data.destiny` и `data.karmic_tail`, которых нет в `MiniAnalysisResponse` (web.py:54-60). Вернувшиеся два «заблюренных» блока «Личное предназначение» и «Кармический хвост» всегда показывают `…` — макет обещает контент, которого API не отдаёт.
→ Либо добавить `destiny`/`karmic_tail` в `MiniAnalysisResponse` + `AIService.generate_mini_analysis`, либо убрать эти два блока из мини-разбора (оставить заглушку «доступно в полном отчёте» без данных).

### WARNING

[WARNING] [frontend/pwa/app/chat.html:186] Детект безлимита проверяет только `d.has_tarot`. Backend (web.py:314-316) считает безлимитным и `subscription_status == "premium"` → пользователи с премиум-подпиской видят лимит-бар «из 5 бесплатных», хотя чат у них безлимитный (фактического лимита нет, но UI врёт).
→ `if (d.has_tarot || d.subscription_status === 'premium' || d.subscription_status === 'active')`.

[WARNING] [mini.html:169] На `/web/mini-analysis` отправляется поле `main_request`, не описанное в `MiniAnalysisRequest` (web.py:49-51). Pydantic v2 по умолчанию extra-поля игнорирует → поле silently теряется на сервере; остаётся только в `localStorage.nura_main_request`. Запрос пользователя не используется AI для персонализации, хотя mini.html:187 строит из него текст «Запрос: …».
→ Добавить `main_request: str | None = None` в `MiniAnalysisRequest` и пробрасывать в `AIService.generate_mini_analysis`, либо убрать из body если значение не нужно.

[WARNING] [frontend/pwa/app/nura-pwa.js:84] `window.NURA.BASE = 'https://nura-ai.ru/api/v1'` захардкожен prod-URL. В dev/preview (localhost) все fetch уходят на прод и踩 CORS. mini.html/success.html используют относительные `/api/v1/...` — фактически два разных BASE в одном проекте.
→ Использовать `window.NURA.BASE = (location.origin === 'https://nura-ai.ru') ? 'https://nura-ai.ru/api/v1' : '/api/v1'` (или читать из `<meta name="api-base">`), дедуплицировать с мини/саксесс.

[WARNING] [success.html:111] Polling-проверка `if(res.ok)` срабатывает и для 202 «Отчёт ещё готовится» (reports.py:107). При первом 202 происходит premature-редирект `window.location.href='/report/'+token`, где пользователь видит ту же «Отчёт ещё готовится» страницу с 202 — feedback выглядит зацикленным.
→ Различать статусы: `if(res.status===200){redirect}`; для 202 продолжать polling.

[WARNING] [frontend/pwa/app/index.html:206] `$('greeting-name').innerHTML = 'Привет, <em>' + N.escHtml(d.name) + '</em>';` —innerHTML с escaped контентом технически безопасен, но нарушает правило «избегать innerHTML» из AGENTS.md. Если `d.name` окажется пустым/null, упадёт `escHtml(null)`.
→ Guard: `if(d.name){ ... }`, предпочтительно `textContent` + отдельный `<em>` через `appendChild`.

[WARNING] [frontend/service-worker.js:1-22] `STATIC_ASSETS` содержит `/mini.html`, `/success.html`, `/theme.css`, `/nura-ds.css`, `/static/nura-ds.css`. 这些 файлы в репо лежат в корне и деплоятся в `/var/www/nura-ai.ru` и `/opt/nura`, но `/mini.html` и `/success.html` отдаются nginx из `root /opt/nura` (nginx conf:96-106), а не из `/var/www/nura-ai.ru`. SW淼addAll при install пойдёт в fetch этих URL — `mini.html/success.html` вернутся nginx, но `theme.css/nura-ds.css` тоже. Однако: `/mini.html` доступен только через `location = /mini.html { root /opt/nura; }` — SW-origin fetch пройдёт. Файлы реально существуют → не баг, но зависимость от nginx-конфига хрупкая.
→ Либо явно прокомментировать в SW, что эти ассеты резолвятся nginx-алиасами, либо дублировать их в `/var/www/nura-ai.ru`. Зафиксировать версионирование (см. ниже).

### INFO

[INFO] [nura_app/api/routes/tarot_pwa.py:93-128] POST `/tarot/spread` полностью реализован (6 типов раскладов: weekly/question/life/doubles/portal/yesno) **но frontal никогда его не вызывает** — tarot.html:265-272 при `has_tarot=true` просто подменяет onclick на `askNura(текст-вопрос)` → пользователь идёт в chat.html через `/web/chat`. Spread-эндпоинт мёртвый.-founder: продакт не получил заявленной функции.
→ Либо подключить расклады в PWA (отдельная страница с выбором spread_type), либо удалить эндпоинт и pacekeeper-код, чтобы не вводить в заблуждение.

[INFO] [nura_app/api/routes/push.py:28] `/push/vapid-public-key` реально **GET**, а план CODE_AUDIT_PLAN.md:26 указывает POST. Фронт (nura-pwa.js:122) использует GET → код консистентен, ошибка в плане.
→ Поправить план (не код).

[INFO] [frontend/pwa/app/profile.html:230-236] `logout()` чистит только `nura_session_id, nura_chat_log, nura_notif_prefs`. Остаются: `nura_q_YYYY-MM-DD`, `nura_tarot_date`, `nura_tarot_card`, `nura-theme`, `nura_push_subscribed`, `nura_push_endpoint`, `nura_main_request`, `nura_pending_question`. После повторного входа под другим аккаунтом счётчик лимитов выглядит «уже использован», push-флаги — «уже подписан».
→ Расширить logout до полного `Object.keys(localStorage).filter(k=>k.startsWith('nura_')).forEach(...)` с защитой темы (на вкус продакта).

[INFO] [localStorage карта] Ключ `nura_birth` из плана не устанавливается ни в одном файле (mini.html сохраняет `nura_session_id` и `nura_main_request`, но НЕ `nura_birth`). План-карта устарела.
→ Убрать `nura_birth` из плана либо внедрить запись `nura_birth` в mini.html:175 для переиспользования в profile.html.

[INFO] [mini.html:163] Ключ `nura_main_request` используется, но отсутствует в карте localStorage плана (Область 3).
→ Дополнить план.

[INFO] [frontend/pwa/app/chat.html:234-238] В `/web/chat` отправляется и `X-Session-Id` header, и `session_id` в body — backend web.py:310 использует только body. Header избыточен, но не вреден (drift с другими эндпоинтами, где работает `Depends(get_current_web_user)`).
→ Унифицировать: либо всё на `X-Session-Id`, либо body.

[INFO] [frontend/pwa/app/profile.html:182] В PATCH `/web/notifications` шлётся `X-Session-Id` header, но route (web.py:382-394) использует только body `session_id` и `get_by_web_session_id` — header игнорируется. Чисто шум, не баг.

[INFO] [nura_app/api/routes/web.py:360-366] Определены `TestSubscribeRequest`/`TestSubscribeResponse` классы, но в `MiniAnalysisResponse`/`ChatResponse` и т.д. — нормально; однако `test-subscribe` эндпоинт (web.py:409) не упомянут в плане (Область 1.1 карта эндпоинтов). Фактически есть POST `/api/v1/web/test-subscribe`.
→ Дополнить карту плана.

[INFO] [frontend/pwa/app/chat.html:156-157] localStorage `nura_q_YYYY-MM-DD` (клиентский счётчик) и Redis `chat_count:{user_id}` (сервер) могут разойтись при чистке localStorage. Сервер приоритетен через 402, но pip-bar основан на клиентском `qUsed` → пользователь может видеть «осталось 3» при фактическом исчерпании, или наоборот.
→ На `/web/me` / `/web/chat` возвращать серверный `messages_left` (он уже есть в `ChatResponse`) и использовать его как источник истины для UI-пипсов.

[INFO] [frontend/pwa/app/tarot.html:244-252] `/tarot/daily-card` fetch использует `N.fetchJSON`, который при `!r.ok` возвращает `null` (nura-pwa.js:90) — silent failure без логирования. catch-блок на `.then` не сработает (там просто `if (!d) return`). Ошибки吞. То же в chat.html:185 / index.html:202.
→ `fetchJSON` должен хотя бы `console.warn` на не-2xx.

[INFO] [frontend/pwa/app/nura-pwa.js:25-35] Условие `skipWaiting` в `install` смотрит на `self.registration.active` — стандартная защита от перехвата активного SW; OK. `clients.claim()` в activate есть — OK.

[INFO] [frontend/service-worker.js:59-61] `/api/`, `/report/`, `/webhook/` исключены из SW-кэширования — корректно. На навигационные запросы `caches.match('/offline.html')` как fallback — OK.

[INFO] [/tarot/daily-card 401 handling] Эндпоинт `/tarot/daily-card` использует `Depends(get_current_web_user)` (tarot_pwa.py:67), который в случае неверной сессии должен кидать 401/404. Frontend (tarot.html:244, index.html:229) не обрабатывает 404 редиректом на `/mini.html`, как chat.html. При протухшей сессии на index/tarot просто silent-молчание.
→ Добавить такую же 404→`/mini.html` обработку, как в chat.html:241.

---

=== ИТОГ СЕССИИ 1 ===
Проверено областей: 1, 3, 9
Найдено: 2 critical, 6 warning, 11 info
Следующая сессия: Критические баги и База данных (Области 2, 8) — bot/handlers, core/repositories, core/models, alembic

---

## СЕССИЯ 2 — Критические баги и База данных (Области 2, 8)

### CRITICAL

[CRITICAL] [nura_app/bot/handlers/chat.py:62] `r.payment_status == "paid"` обращается к несуществующему полю `Report.payment_status`. Поля в модели `Report` (models.py:86-108): `id, user_id, report_type, token, matrix_data, ai_analysis, kitchen_analysis, created_at` — никакого `payment_status` нет. При попытке любого пользователя с полным отчётом (`report_type == "full"`) войти в чат → SQLAlchemy бросит `AttributeError`, `_has_unlimited_chat` упадёт, callback `/chat_with_nura` (chat.py:67) завершается ошибкой → кнопка «Чат» в Telegram бесконечно spinner/«старое сообщение» для уже оплативших.
→ Удалить ветку `payment_status`; безлимитный чат для купивших матрицу определять через `user.has_matrix` (или через наличие `Report(report_type="full", matrix_data is not None)`): `if r.report_type == "full" and user.has_matrix: return True`.

[CRITICAL] [nura_app/bot/handlers/chat.py:98 + 154-168] Бот-лимит免费的5-сообщений **не привязан к дневному счётчику**. `chat_messages_left` хранится только в FSM-state (`state.update_data`), а не в Redis. Каждый `enter_chat` (callback `chat_with_nura`) сбрасывает счётчик обратно в `FREE_MESSAGES_LIMIT`. Чтобы получить бесконечный бесплатный чат в боте — достаточно после 5 сообщений выйти и снова тапнуть «Чат». В отличие от `/web/chat` (web.py:318-355), который(keys Redis `chat_count:{user_id}` с TTL 86400), бот вообще не пишет в Redis.
→ Внедрить серверный счётчик `bot_chat_count:{user_id}` в Redis (TTL 86400) и проверять в `chat_message`, как в web.py.

[CRITICAL] [nura_app/bot/handlers/start.py:78-82] `_handle_link_token` делает прямой `httpx.AsyncClient().get("http://127.0.0.1:8000/api/v1/web/check-link-token")`. Захардкоженный `http://127.0.0.1:8000` ломается в Docker (бот-контейнер и api-контейнер — разные процессы; `127.0.0.1` укажет на сам бот, а не на api). См. также docker-compose (Сессия 3). Связывание Telegram-аккаунта «из приложения» через эту кнопку молча упадёт с таймаутом/404.
→ Заменить на внутренний вызов без HTTP: `await ReportService... ` либо `await UserRepository.get_by_link_token(...)` через Redis-ключ `link_token:{token}` напрямую. Альтернатива: читать `settings.report_base_url` / `settings.api_internal_url`.

[CRITICAL] [nura_app/core/database.py:11-12] `get_async_sessionmaker()` НЕ singleton — на каждый вызов создаёт **новый `create_async_engine()` (pool_size=5) + новый `async_sessionmaker`**. Т.к. он вызывается в начале почти каждого route-handler (`web.py:75,120,210`, `payment_repo`/`report_repo`/`user_repo` в каждом запросе), на проде под нагрузкой число engine'ов и живых DB-коннектов растёт без верхнего предела → PostgreSQL упирается в `max_connections` (`FATAL: too many connections`), бот/web начинают падать. Уже не «ускорение», а утечка ресурсов.
→ Сделать ленивый модуль-уровень singleton: 
```python
_engine = None
_session_factory = None
def get_async_sessionmaker():
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=20)
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _session_factory
```

### WARNING

[WARNING] [nura_app/bot/handlers/start.py:142, 172] В `main_menu_keyboard(has_matrix=bool(user.birth_date), ...)` — передаётся наличие `birth_date` вместо реального `user.has_matrix`. Кнопка «Матрица» открывается всем, кто ввёл дату рождения, даже если полного отчёта/оплаты нет → после онбординга юзер видит «Матрицу» и жалует кнопку «Купить — 890 ₽» → confused UX. Зато callback-ветка `_show_authenticated_menu` (line 64-69) передаёт корректно `bool(user.has_matrix)`.
→ Унифицировать: `has_matrix=bool(user.has_matrix)` и в `cmd_menu`, и в `callback_main_menu`.

[WARNING] [nura_app/core/repositories/user.py:99-113] `update_has_matrix(True)` одновременно ставит `user.subscription_status = "premium"` **без `subscription_until`**. Matrice — разовая покупка, но продактовская модель «premium = безлимитный web-чат» (web.py:314-316 `subscription_status == "premium"` → unlimited) даёт купившему матрицу **пожизненный безлимитный web-чат бесплатно**. Если это задумка — зафиксировать в `docs/`. Если нет — `update_has_matrix` не должен трогать `subscription_status`; добавить отдельный статус `"matrix"` и в web.py:316 учитывать `has_matrix` отдельно.
→ Согласовать с продактом; рекомендую `has_matrix=True` как триггер `has_unlimited` в web.py, а `subscription_status` использовать только для ежемесячной подписки.

[WARNING] [nura_app/core/repositories/user.py:147-157] `get_has_matrix(user_id)` вообще не использует колонку `User.has_matrix` — ре-запрашивает `Report` таблицу на FULL type. Две несогласованные источника правды про «у юзера есть матрица»: колонка `users.has_matrix` и «есть FULL-Report с matrix_data». Они могут разойтись (например, после ручного апдейта БД / бага миграции).
→ Один источник: либо убрать колонку и всегда считать через Report-запрос, либо убрать `get_has_matrix` и везде использовать `user.has_matrix`.

[WARNING] [nura_app/alembic/versions/e47590a5c5c1_add_kitchen_analysis_to_reports.py:19-27] Корневая миграция (`down_revision = None`) делает `op.add_column("reports", "kitchen_analysis")` — но **не создаёт** таблиц `users`/`reports`/`payments`. Alembic-история предполагает, что базовая схема уже есть извне (Bootstrap делается через `init_db.py:13` `Base.metadata.create_all`). Для любой свежей БД порядок строго: `python init_db.py` → `alembic stamp head` (чтобы alembic не пытался выполнить add_column снова) → либо иначе миграция упадёт на `column ... already exists`. Это нигде не задокументировано в README.
→ Либо добавить начальную миграцию `0001_create_base_schema.py` с `op.create_table` для всех таблиц (и пусть она совпадает с `models.py`), либо задокументировать шаг bootstrap в `README` и `Dockerfile` (entrypoint: `init_db.py && alembic stamp head`).

[WARNING] [nura_app/bot/handlers/chat.py:33-48] `_get_user_matrix_data` тянет `await report_repo.get_by_user_id(user.id)` — но дальше в сообщениях `chat_message` (chat.py:133) ещё раз делает тот же `get_by_user_id` в случае `not matrix_data`. На каждом сообщении без кэшированного `matrix_data` — повторный full-table fetch всех репортов пользователя. N+1 на ровном месте.
→ После первого fetch'а кешировать `reports` в FSM-state.

### INFO

[INFO] [nura_app/core/repositories/__init__.py:1-11] `ReferralRepository` не экспортируется из `__init__.py` (`__all__` не содержит). Используется только через прямой `from core.repositories.referral import ReferralRepository` (start.py:206). Не баг, но непоследовательно.
→ Добавить `from core.repositories.referral import ReferralRepository` и в `__all__`.

[INFO] [nura_app/core/models.py:26] `ReportType.COMPATIBILITY = "compatibility"` — enum value, описан и в `reports.py:157` есть handler, но **нигде в коде** `ReportType.COMPATIBILITY.value` не создаётся в БД. Бот/handlers/compatibility.py, web (web.py mini/full) — все создают только `MINI`/`FULL`. Compatibility-handler существует, но нет пути, который записывал бы отчёт этого типа → `compatibility_report.html` шаблон практически usage 0.
→ Подключить создание COMPATIBILITY-репорта в маршрутах/боте либо удалить.

[INFO] [nura_app/init_db.py:8-9,13] `create_all` помечен как deprecated, но всё ещё единственный способ создать БД «с нуля» (т.к. корневой alembic не создаёт таблицы). Двойственность источников setup'а.
→ См. WARNING выше — объединить в одну стратегию.

[INFO] [nura_app/bot/handlers/chat.py:84-86] `name = user.first_name or user.username or "пользователь"` — есть на 3-х уровнях (chat.py:84, 124, 187; start.py:60, 136, 166), копипаста маленького helper'а. DRY.
→ Вынести в `bot/utils/formatting.py:user_display_name(user)`.

[INFO] [nura_app/alembic/versions/] Цепочка ревизий датирована `2026-05-24 .. 2026-06-22`. Линейная, single head = `c3d4e5f6a7b8` (notification_prefs). Мультиhead'ов нет — OK. Проверить наличие `alembic_version` таблицы на VPS (`alembic current`) нельзя из этой среды; рекомендую на VPS: `docker compose exec api alembic current` и сравнить с `c3d4e5f6a7b8`. Если ниже — `alembic upgrade head`.

[INFO] [nura_app/bot/handlers/chat.py:158] `if messages_left == 0:` после line 154-156 (где `if messages_left > 0:` уменьшает). Если `messages_left == -1` (unlimited) — ветки `>0` и `==0` пропускаются, ОК. Но `messages_left == 0` проверяется **после декремента** что значит paywall на самом LAST свободном сообщении, правильное поведение. Семантика OK.

[INFO] [nura_app/core/database.py:18-21] `_redis` — singleton ✓ OK. Но нет `await _redis.close()` на shutdown бота/api — при restart контейнера остаются «висящие» соединения. INFO.

[INFO] [nura_app/core/repositories/payment.py:48-49] `with_for_update()` OK для PostgreSQL. В тестах на SQLite — no-op (warning printed), идемпотентность сохраняется за счёт `if status == "succeeded": return None` (CAS-like). OK.

[INFO] [models vs migration] В модели `User.web_session_id` указано `unique=True, index=True`; миграция `5a8cac04bf5e` создаёт `op.create_index(..., unique=True)`. В postgres unique indexом покрывает и lookups — дублирование `index=True` в модели без отдельного `create_index` допустимо. OK.

---

=== ИТОГ СЕССИИ 2 ===
Проверено областей: 2, 8
Найдено: 4 critical, 4 warning, 8 info
Следующая сессия: PWA/Service-Worker и Инфраструктура (Области 4, 5) — service-worker, nginx, manifest, config, docker-compose, tasks

---

## СЕССИЯ 3 — PWA/Service-Worker и Инфраструктура (Области 4, 5)

### CRITICAL

[CRITICAL] [nura_app/core/tasks.py:274-282 + 205-213] `generate_full_report` и `generate_mini_report` объявлены БЕЗ `autoretry_on`/`max_retries`. По умолчанию Celery `task_retries = 0`. При `task_soft_time_limit=240` (tasks.py:37) — если AI/WeasyPrint превысит 240с, Celery бросит `SoftTimeLimitExceeded`, задача умрёт без повторной попытки и **без уведомления пользователя**. Пользователь уже оплатил 890 ₽, отчёт не создан, в `/report/{token}` остаётся 202 «готовится» навсегда. Telegram-нотификация (`_notify_full_report`) тоже не отправляется.
→ Добавить `@celery_app.task(name="core.tasks.generate_full_report", autoretry_on=(SoftTimeLimitExceeded, TimeoutError, Exception), max_retries=2, retry_backoff=30)` — с guard'ом против AI-не-восстановимых ошибок (валидация ввода не должна retry'ться). Дополнительно: при исчерпании ретраев — отправлять в Telegram сообщение «генерация не удалась, пишите в поддержку» + log sentry.

[CRITICAL] [nura_app/core/tasks.py:457 + 502-513] `ARCANE_CACHE: dict[int, str] = {}` — модульная глобальная переменная, key = `daily_arcana` (только номер аркана), **без даты**. Cache заполняется при первом расчёте карты дня и **никогда не инвалидатируется**. В следующий раз, когда тот же arcana выпадет в другой день — `ARCANE_CACHE[daily_arcana]` вернёт текст вчерашней карты (с упоминанием другой даты/совета). Celery-worker живёт днями/неделями; будет показывать залоченный контент. Также `ARCANE_CACHE` не thread/process-safe между разными worker-процессами ( farklı forked children), но хотя бы один из них держит устаревший текст.
→ Key = `(today, daily_arcana)`, value = текст. Reset Cache на каждом запуске `_send_daily_card_async`: `ARCANE_CACHE.clear()` в начале. Либо Redis-кеш с TTL 25h.

### WARNING

[WARNING] [nura_app/core/tasks.py:251-253 + 169-171] И `_process_full_report`, и `_process_mini_report` делают `existing = await get_by_user_id_and_type(...)` → `await report_repo.delete(existing.id)` **перед** созданием нового report. Если между delete и create что-то падает (AI timeout, exception в `gather`), старый отчёт уже удалён, а нового нет — пользователь теряет доступ к купленной матрице (статус `has_matrix=true`, а FULL-репорта и HTML/PDF нет). Заходя в `/report/{token}` видит 404 «Отчёт не найден».
→ Сначала создать новый (`report_repo.create`), потом удалить старый (или обновлять in-place: `existing.matrix_data = ...; existing.ai_analysis = ...; session.commit()`).

[WARNING] [nura_app/core/tasks.py:593] `text = f"🌒 <b>Карта дня для {user_name}</b>\n..."` — `format_daily_card_message` используется только в `_send_daily_card_async` для cached-текста, но `_send_daily_tarot_card_async` строит `text` inline. OK функционально. Не баг, но два шаблона одной темы поддерживаются separately — INFO.

[WARNING] [nura_app/core/config.py:13] `postgres_host: str = "localhost"` — по умолчанию `localhost`. Внутри Docker (api/bot/celery) нужно `postgres` (имя сервиса из compose). `.env.example:8` корректно ставит `POSTGRES_HOST=postgres`, но если на VPS `.env` отсутствует/обрезан — все контейнеры сломаются «connection refused к localhost». Plan 5.1 явно указывает проверить.
→ На VPS: `docker compose exec api env | grep POSTGRES_HOST` должен показать `postgres`. Если `localhost` — поправить `.env` и перезапустить.

[WARNING] [nura_app/core/tasks.py:660] `check_expiring_subscriptions` шлёт `_send_message(user.telegram_id, ...)` **без проверки `user.telegram_id is not None`**. Web-only premium-подписчики (`telegram_id=None`) попадают в select (line 636-642 фильтрует только по `subscription_status="premium"`). `_send_message` (line 88) вызовет `bot.send_message(chat_id=None, ...)` → aiogram `TypeError` → цикл падает, оставшиеся пользователи не получают напоминание.
→ Добавить `if not user.telegram_id: continue` в цикл, или filter на уровне SQL `User.telegram_id.isnot(None)`.

[WARNING] [frontend/service-worker.js:2-22 + HTML ?v=9] SW `STATIC_ASSETS` предзаполняет версию-less URL'ы (`/app/nura-pwa.css`, `/app/nura-pwa.js`, `/theme.css`, `/pwa-install.js`). Но в HTML всё подключается с `?v=9` (chat.html:21-23, index.html:22-23, и т.д.). `caches.match(e.request)` сравнивает URL со строкой запроса — версия-qualified URL (e.g. `/theme.css?v=9`) НЕ матчит преcкешированную запись (`/theme.css`). Каждый хит идёт в сеть, кэш заполняется только после первого онлайн-посещения (service-worker.js:74-79). Получается: precache не даёт офлайн-доступа на первой загрузке, и при bumping `?v=N` старые stale записи остаются навсегда. Ок только если SW update cleanup их снесёт (cache_name=nura-v15 → новые `nura-v16` чистит старые). Но между версиями одного `v` остаются дубликаты.
→ Унифицировать: либо в STATIC_ASSETS включать `?v=9` (с привязкой к СACHE_NAME и bump'ом при изменении), либо убрать версионные query из HTML и полагаться только на SW cache-name bump.

[WARNING] [nura_app/.env.example] Файл не содержит переменных: `ADMIN_TOKEN`, `SENTRY_DSN`, `TEST_MODE`. `config.py` их читает, но в `.env.example` их нет → при setup с нуля у администратора нет подсказок, что эти opt vars существуют. Также `.env.example` лежит в `nura_app/` (правильно, \.env не коммитится), но в repo-root его дубликат отсутствует.
→ Дополнить `.env.example`: `ADMIN_TOKEN=`, `SENTRY_DSN=`, `TEST_MODE=false` с комментариями.

[WARNING] [nura_app/core/tasks.py:60-65] `_run_async` делает `asyncio.new_event_loop()` + `asyncio.set_event_loop(loop)` на каждом вызове задачи, без закрытия предыдущего event loop'а. При prefork-пуле это OK (каждый task в одном fork-процессе sequentially), но при `--concurrency=2` + threads или `gevent` пуле может гонять. Также создаёт новый event loop и убивает его — connection pool от SQLAlchemy async engine, созданный в одном loop, при следующем task в новом loop будет «attached to different loop» error (asyncpg binds connection to event loop). Combined with `get_async_sessionmaker()` НЕ-singleton (Session 2 CRITICAL) — каждый task создаёт новый engine, но если поправить на singleton, втором task'е asyncpg упадёт с «event loop is closed».
→ Сделать `_run_async` приват singleton-per-worker event loop: создать один loop в worker, переиспользовать (`loop.run_until_complete`), не закрывать. Покрыть unit-тестом «две Celery задачи подряд не падают».

### INFO

[INFO] [frontend/service-worker.js:2-22] **Все** перечисленные ассеты физически существуют в репо (`offline.html`, `mini.html` repo-root, `success.html` repo-root, `/app/*.html`, `manifest.json`, `pwa-install.min.js`, `theme.css` root, `nura-ds.css` root, `frontend/icons/*`) и `deploy.sh:8-30` копирует их в `/var/www/nura-ai.ru` и `/opt/nura`. `static/nura-ds.css` создаётся через `deploy.sh:15`. План Obласти 4.1 — все ассеты в наличии, не баг.

[INFO] [nura_app/nginx/nura-ai.ru.conf:96-112] `/mini.html` и `/success.html` раздаются из `root /opt/nura` (не `/var/www/nura-ai.ru`), чтобы их можно было править прямо в git-репо VPS без копирования в `/var/www`. Хрупко: если кто-то替换ит `/opt/nura` репо на symlink, `try_files` ломается. Функционально OK на settings, риск зависимость от структуры `/opt/nura`.

[INFO] [frontend/manifest.json:6] `"scope": "/"` + SW registration `scope: '/app/'` (chat.html:310, profile.html:16, tarot.html:16) — несоответствие: manifest scope=root предполагает управления корневым SW. В HTML регистрируется SW с scope `/app/`, но (line 4: `<link rel="manifest" href="/manifest.json">`) фaйт чипается через nginx `location = /manifest.json` (root /var/www/nura-ai.ru). В Chrome установка PWA: контроллер по `/app/` — браузер показывает install prompt на страницах `/app/`. OK functionally.

[INFO] [Docker compose healthchecks] postgres + redis + api имеют healthcheck (postgres+redis: `pg_isready`/`ping` ; api: `curl -f /health`). Все остальные depends_on — `condition: service_healthy` ✓. bot/celery-worker/celery-beat **не** имеют healthcheck — compose restart:unless-stopped их перезапустит только на exit, не на hang. Plan 5.3 OK.
→ Добавить healthcheck на bot (например, `python -c "from aiogram import Bot; ..."` просто проверка polling alive) — optional.

[INFO] [nura_app/docker-compose.yml:43-66] `api`盛世 монтирует `/var/run/docker.sock:ro` и `/var/log/nginx:ro` — дебаг/инспек. Учитывая что api читает лог nginx (rate-limiter slowapi через `X-Forwarded-For`), это оправдано. Но монтирование docker.sock в приложение — security risk (если api compromise, attacker получит root на VPS). Лучше прокси через named-pipe/socket-only token.
→ Pin docker daemon access или удалить mounted sock если не используется (если nginx логи нужны только — оставить log mount, убрать docker.sock).

[INFO] [nura_app/core/config.py:74-80] `_protect_test_mode` field-validator гасит `test_mode` в production ✓ OK. Но `app_env` по умолчанию `"development"`, а не `"production"`. Если `APP_ENV` не задан на VPS → все контейнеры в development → `test_mode` можно включить через `.env`. Подстановка в проде — risk.
→ В Dockerfile / compose гарантировать `APP_ENV=production` по умолчанию или fail-fast если не задан.

[INFO] [nura_app/core/tasks.py:451-452 + 553-555] В `beat_schedule` две карточные задачи: `send-daily-card` (03:00) всем + `send_daily_tarot_card` (09:15) только с подпиской. Двойная отправка карты `« emoji 🌒 твоя карта дня»` разным аудиториям. Если у юзера с tarot_subscription идут обе — он получает два сообщения в день (3 ночи и 9:15). Запутанно.
→ Унифицировать: одна задача, разная текстовка по `tarot_subscription`.

[INFO] [frontend/pwa/app/nura-pwa.css] Файл существует ✓. В HTML же дублированный путь через `<link href="nura-pwa.css?v=9">` (относительный) и CDN шрифты. OK.

[INFO] [frontend/pwa-install.js:124-138] `triggerInstall` — стандартный flow. `_deferredPrompt.userChoice.then` без `await` — Chrome не любит await при prompt(); OK. INFO.

[INFO] [nura_app/core/tasks.py:486] `today = date.today()` использует server local date, но celery `timezone="Europe/Moscow"` (line 32) применяется только к cron-расписанию, не к `date.today()` внутри task. На VPS UTC (dpkg-reconfigure tzdata обычно UTC) → карта дня считается по UTC, доставается пользователям в 03:00 МСК, сегодня по МСК ещё может быть вчерашний день. Микро-discrepancy.
→ `from datetime import datetime; today = datetime.now(timezone(timedelta(hours=3))).date()`. (Moscow = UTC+3.)

[INFO] [nura_app/.env.example] `REDIS_URL=redis://redis:6379/0` — broker=db1, result=db2, app/db=db0 (config.py:33-37 defaults). Соответствует Plan 5.4 о разделении Redis DB. OK ✓.

---

=== ИТОГ СЕССИИ 3 ===
Проверено областей: 4, 5
Найдено: 2 critical, 7 warning, 10 info
Следующая сессия: Платёжный флоу и Bot-специфика (Области 6, 7) — payment routes/services, bot handlers

---

## СЕССИЯ 4 — Платёжный флоу и Bot-специфика (Области 6, 7)

### CRITICAL

[CRITICAL] [nura_app/core/services/payment.py:311 + 536] `user.birth_date.isoformat()` — `User.birth_date` это `String(10)` в формате `"DD.MM.YYYY"` (models.py:45, tests/test_payment.py:25 используют `birth_date: str = "01.01.2000"`). У `str` нет `.isoformat()` → `AttributeError`. Это в `try/except` вокруг `generate_full_report.delay(...)`, поэтому исключение съедается логом, а Celery-задача **никогда не ставится в очередь**. Пользователь оплатил матрицу (web_matrix и Telegram-matrix), `update_has_matrix=True` поставилось, но **HTML/PDF-отчёт не генерируется**, `/report/{token}` крутит 202 «готовится».一千.
→ Заменить на `user.birth_date` (просто строку) — задача принимает `birth_date: str` (tasks.py:217): `generate_full_report.delay(str(user.id), user.birth_date, report_token)`.

[CRITICAL] [nura_app/bot/handlers/payment.py:155-157] `initiate_tarot_subscription` (callback `buy_tarot_subscription`) вызывает **`PaymentService.create_subscription`** (590₽/мес Premium), а НЕ `create_tarot_payment` (390₽/мес Tarot, payment.py:51). Текст кнопки в UI говорит «390 ₽/мес», реально списывается 590. Метадата платежа = `"subscription": "true"` → webhook попадает в `else`-branch (payment service:567-582) → активируется `subscription_status="premium"` через `update_subscription`, а **НЕ** `tarot_subscription`. `create_tarot_payment` **нигде в коде не вызывается** — мёртвый метод (подтверждено `grep`).
→ `subscription = await PaymentService.create_tarot_payment(telegram_id=user.telegram_id)`.

[CRITICAL] [nura_app/core/services/payment.py:31 + 61 + 91] YooKassa `return_url` = `f"{settings.report_base_url}/subscription/success"`. **Пути `/subscription/success` нет ни в nginx.conf, ни в репо** — есть только `/success` и `/success.html` (nginx:108-112). Telegram-пользователи после оплаты (subscription / matrix / tarot через бота) редиректятся на 404. Только web-flow'ы корректные (line 123 → `/report/{token}`, line 154 → `/app/profile?tab=subscription`).
→ Унифицировать на `/success?token={report_token}` или `/app/?paid=...`; для подписок — `/app/profile?tab=subscription#subscription` или явный `/success?type=subscription`.

[CRITICAL] [nura_app/core/services/payment.py:23-42 + 53-72 + 83-102 + 115-135 + 146-165] Все `YooPayment.create(..)` вызовы синхронные (YooKassa Python SDK synchronous). Однако функции объявлены `async def` и вызываются из `await` в FastAPI route / aiogram callback. Синхронный HTTP-запрос к YooKassa **блокирует event loop** (~300-800мс_each). Под нагрузкой.aiogram bot polling остановится на это время, другие callback'и/query зависнут, Telegram пошлёт timeout-retry → дубли платежей. FastAPI-api тем временем перестаёт обрабатывать остальные запросы.
→ Обернуть в `await asyncio.to_thread(YooPayment.create, payload, idem_key)` (или runs в executor'е). Либо aiohttp-клиент к YooKassa REST напрямую.

### WARNING

[WARNING] [nura_app/core/services/payment.py:269-296 + 567-577] При падении `update_has_matrix`/`update_subscription`/`update_tarot_subscription` (после `claim_succeeded`) код откатывает `payment.status = "pending"`. Но YooKassa уже списала деньги (capture=True) и **не пришлёт повторный webhook** для pending-платежа → пользователь заплатил и навсегда остался без продукта. Сам `claim_succeeded` с FOR UPDATE уже атомарно перевёл статус, revert = потеря информации о проведении платежа. Нужно наоборот: payment остаётся `succeeded` + отдельная очередь `needs_review` для ручного разбора.
→ Удалить `payment_repo.update_status(payment.id, "pending")` в error-ветках. Заменить на логирование в Sentry + запись в `payments.failure_reason`. При failed update_has_matrix — пометить user в очередь ручного разбора (`support_queue`).

[WARNING] [nura_app/core/services/payment.py:122-124] Веб-матрица: `return_url = f"{settings.report_base_url}/report/{report_token}"`. После оплаты пользователь попадает сразу на `/report/{report_token}`, который при незаконченной Celery-генерации вернёт **202 + GENERATING_HTML** (reports.py:107). Нет polling-логики (success.html с polling-функцией не задействуется для web_matrix). Plan Area 6 явно ожидает `success.html`. Вручную пользователь должен обновить страницу, что не очевидно.
→ Вернуть на `/success.html?token={report_token}` (sùccess.html ужеpolls `/report/{token}` до 200).

[WARNING] [nura_app/core/services/payment.py:153-154] Web-tarot: `return_url = f"{settings.report_base_url}/app/profile?tab=subscription"`. Но `profile.html` (frontend) обрабатывает только hash `#subscription` (profile.html:118-120), а query-параметр `?tab=subscription` игнорируется. После tarot-оплаты профиль открывается на вкладке «Отчёты», а не «Подписка» → пользователь думает, что подписка не активировалась.
→ Поменять на `/app/profile.html#subscription`.

[WARNING] [nura_app/bot/handlers/payment.py:99] Кнопка «🌐 Оформить в NURA» указывает на `https://nura-ai.ru/app/profile?action=subscribe` — query-парам `action=subscribe` в profile.html не предусмотрен (только хеши `#subscription`, `#reports`). Бесполезный URL.
→ `https://nura-ai.ru/app/profile.html#subscription`.

[WARNING] [nura_app/core/services/payment.py:482-490] В Telegram-ветке (fall-through) нет проверки корректности `payment_type` для подписок; если metadata не содержит `payment_type`, принимается `"subscription"` (default, line 214). Что при оплате matrix-через-бота — metadata содержит `payment_type=matrix` → handled; но если юзер повторит оплату `tarot`, payment_type=tarot в метаданных попадает в нужную ветку. Но веб-тарot `web_tarot`-веток создаёт платеж с metadata `payment_type=web_tarot` (line 161), а я уже показал что bot-тарot создаёт `subscription` — несовпадение.
→ Унифицировать имена payment_type во всём проекте: `matrix`, `tarot`, `subscription`, `web_matrix`, `web_tarot`.

[WARNING] [nura_app/bot/handlers/onboarding.py:88-89] `MatrixService.calculate(user.birth_date)` вызывается на каждом callback `my_matrix`. Ре-расчёт матрицы каждый раз по «показать мою матрицу» (частый action в меню бота). Не сохраняется, не кэшируется, но это CPU pure-python расчёт — быстро. Дублирует работу, что уже приказано в DB `matrix_data` (ReportRow.matrix_data).
→ Читать из `Report.matrix_data` (mini_report), а не пересчитывать.

[WARNING] [nura_app/bot/handlers/onboarding.py:34-37] `process_onboarding_birth_date` принимает параметр `user=None` (line 34) — но нигде в коде не передается (router doesn't inject `user`). Декоратор aiogram `@router.message(OnboardingStates.waiting_for_birth_date)` вызывает с `Message`+`FSMContext`. `user=None` — dead param, потенциально вводит в заблуждение.
→ Убрать `user=None` параметр или явно прокомментировать «mock/test hook».

[WARNING] [nura_app/bot/handlers/tarot.py:298-309] `show_tarot_twins` (callback `tarot_twins`) обрабатывает «Теневые стороны» через `tarot_doubles.txt`-промпт. Но callback_data в keyboard надо проверить — если есть кнопка `tarot_doubles` где-то, она ни к какому handler'у не привязана. В `tarot_pwa.py:33` spread_type pattern `doubles` имеется. Plan 7: "doubles handled in bot?" — ответ: ДА, через `tarot_twins`. INFO/WARNING по дублированию имён.

[WARNING] [nura_app/bot/handlers/tarot.py:412-425 + 451-466] `show_tarot_blocks` обрабатывает callback `tarot_blocks` —.ClampSpread типа «Что мешает». Документировано в Plan'е нет. Не баг, но дополнительный spread не указан в плане. INFO/WARNING по неполноте плана.

### INFO

[INFO] [nura_app/bot/handlers/payment.py:62, 70-72, 211-220] Lazy imports `from core.tasks import generate_full_report` и `from core.repositories.report import ReportRepository` внутри callback — обычный паттерн для избегания циклических импортов (Plan Area 7 отмечает). Работает корректно, но слегка мешает тестированию mock'ом. INFO.

[INFO] [nura_app/bot/handlers/tarot.py:115-128] Daily-card bot spread: `center_arcana = user.main_archetype_number or _daily_arcana_number(today)` — fallback корректен. `_personal_arcana_number(today, center_arcana)`. OK functionally. INFO.

[INFO] [nura_app/bot/handlers/onboarding.py:108-124] Если mini_report.ai_analysis["main_archetype"] — fallback-текст («дай мне ещё одну попытку»), бот удаляет отчёт и пере-запискует генерацию. Само-contained recovery logic. ОК, но fragile magic-strings (лучше enum is_fallback flag). INFO.

[INFO] [nura_app/bot/handlers/payment.py:198-204] `buy_matrix` (callback) если `user.has_matrix` — сообщение «Матрица уже куплена». OK. Но Plan Area 7 (chatbot: «sample_report кнопка → /report/sample»): в start.py:179-200 callback_sample_report выводит **текст с описанием**, НЕ ссылку на `/report/sample`. Хотя `/report/sample` эндпоинт существует (reports.py:80-89). Информационное сообщение с кнопкой «Купить 890 ₽», без прямого открытия примера.
→ Добавить кнопку «👁 Открыть пример» с `url=f"{settings.report_base_url}/report/sample"`.

[INFO] [bot/handlers/validators.py:7-14] `validate_date("1.5.1995")` → regex fail → `false` (требует zero-padded). Пользователь получит «Введи дату в формате ДД.ММ.ГГГГ» — обратная связь OK. INFO (Plan 7 вопрос — отвечён).

[INFO] [nura_app/bot/handlers/payment.py:298-299] `arch = report.matrix_data.get("archetype_name") if report.matrix_data else None` — reading из `matrix_data` напрямую в bot, без service layer; нарушает «Models → Service → Repo». INFO — small leak.

[INFO] [nura_app/core/services/payment.py:46-48 + 75-78 + ...] `payment_method_id` возвращается из всех create_* функций, но **нигде не используется** для recurring billing. В БД Payment нет колонки `payment_method_id` (models.py:111-134), в `save_matrix_payment` не сохраняется. `save_payment_method: True` у подписок вроде useless без recurring. INFO — recurring billing не реализован.

[INFO] [nura_app/bot/handlers/tarot.py:54-78] Bot tarot menu роутится на `tarot_menu` callback — полностью дублирует фронтендовую страницу `/app/tarot.html` (только 6 spread_types без PWA-only UI фишек). Двойное сопровождение. INFO.

[INFO] [Plan 6.2 — success.html?token=...] `process_webhook` (payment.py:308-313) Эн-queued Celery через `.delay()` с `report_token`. Если Celery worker вообще не запущен / перегружен — `.delay()` вернёт AsyncResult, исключение НЕ выбрасывается (нет исключения даже если очередь недоступна, если redis_connect fails). Юзер остаётся с `has_matrix=True` но без отчёта. INFO/WARN: monitor Celery queue depth.

---

=== ИТОГ СЕССИИ 4 ===
Проверено областей: 6, 7
Найдено: 4 critical, 7 warning, 9 info

---

# ИТОГОВЫЙ СВОДНЫЙ ОТЧЁТ

| Сессия | Области | CRITICAL | WARNING | INFO |
|--------|---------|----------|---------|------|
| 1 — Фронтенд↔Бэкенд | 1, 3, 9 | 2 | 6 | 11 |
| 2 — Критические баги и БД | 2, 8 | 4 | 4 | 8 |
| 3 — PWA и Инфра | 4, 5 | 2 | 7 | 10 |
| 4 — Платежи и Bot | 6, 7 | 4 | 7 | 9 |
| **ИТОГО** | **1-9** | **12** | **24** | **38** |

## ТОП-5 критических для немедленного фикса

1. **`user.birth_date.isoformat()` в платёжном webhook** (payment.py:311, 536) — сломан весь платный флоу генерации отчёта после оплаты матрицы (web + Telegram). Пользователь платит 890₽, отчёт не генерируется. Replace на `user.birth_date`.

2. **Bot tarot-подписка активирует Premium вместо Tarot** (bot/handlers/payment.py:155) — списывается 590₽ вместо 390₽, активируется не тот продукт. Заменить `create_subscription` → `create_tarot_payment`.

3. **`Report.payment_status` AttributeError в chat.py:62** — Telegram-чат для пользователей с полным отчётом падает. Убрать проверку или заменить на `user.has_matrix`.

4. **`get_async_sessionmaker()` не singleton** (database.py:11) — каждый route создаёт новый SQLAlchemy engine → утечка коннектов к PostgreSQL под нагрузкой. Конвертировать в module-level singleton.

5. **YooKassa return_url → `/subscription/success` (404)** в бот-флоу подписок/матрицы — после оплаты всех telegram-пользователей кидает на 404. Унифицировать на `/success?...` или `/app/profile.html#...`.

## СЛЕДУЮЩИЕ ШАГИ (рекомендация)

- После фикса топ-5 — повторный smoke-тест трёх сценариев Plan Area 9 (A: новый web-user; B: чат→лимит→оплата; C: возврат сессии).
- Прогнать `pytest` после фиксов (особенно `tests/test_payment.py`, `tests/test_chat.py`, `tests/test_tarot_handlers.py`).
- Поднять Sentry alerting на `core.services.payment.process_webhook` `needs_review` returns.
- Включить monitoring Redis очереди Celery ( очереда web_matrix-задач не должна копиться > N минут).

---

КОНЕЦ ОТЧЁТА