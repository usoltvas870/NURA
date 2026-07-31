# Внешний sandbox-профиль NURA

> **CURRENT OWNER DECISION (2026-07-31):** отдельный sandbox VPS/hostname/bot
> сейчас не создаётся. Этот fail-closed профиль остаётся реализованным и
> regression-tested contract, но ближайший внешний путь — owner-only prelaunch
> на текущем VPS с current bot/DeepSeek и отключённой YooKassa. См.
> [current-vps-prelaunch.md](current-vps-prelaunch.md). Это изменение стратегии,
> а не доказательство deploy или внешнего запуска.

**Статус:** IMPLEMENTED LOCALLY — EXTERNAL SANDBOX NOT EXECUTED

**Baseline реализации:** `main` / `0be905226eebc1148d26bf89559d2ae5ce45096f` плюс локальный незакоммиченный worktree
**Alembic head:** `d8e9f0a1b2c3`

Этот документ описывает отдельный fail-closed runtime-профиль для будущего
внешнего sandbox NURA 1.0. Он не является доказательством запуска sandbox,
deploy-инструкцией или разрешением на внешние Telegram, YooKassa и AI вызовы.

## 1. Граница окружения

Внешний sandbox запускается только с `APP_ENV=sandbox`. Это отдельное
окружение, не эквивалентное `test`, `development`, `staging` или `production`.
Все процессы используют единый валидатор из
`nura_app/core/services/external_sandbox.py`.

До готовности блокируются:

- отсутствующий или некорректный `SANDBOX_ENVIRONMENT_ID`;
- production hostname, URL, CORS origin, database identity, Redis endpoint или
  Celery queue;
- HTTP, localhost или несовпадение public/report URL;
- включённые `TEST_MODE`, internal payment shortcut или функции вне минимального
  NURA 1.0 sandbox;
- отсутствующий secret-file, ingress contract, owner или budget;
- несовпадение подключённой БД с Alembic head `d8e9f0a1b2c3`.

Ошибка имеет bounded вид `sandbox_startup_gate_failed:<gate>` и не содержит
DSN, token или credential.

## 2. Идентичности ресурсов

`SANDBOX_ENVIRONMENT_ID` содержит 6–48 символов `[a-z0-9-]`, не равен
`production`, `prod` или `main` и не содержит secret-маркеры. Идентификатор
связывает:

| Ресурс | Контракт |
|---|---|
| Compose project | точное значение `SANDBOX_ENVIRONMENT_ID` |
| PostgreSQL | отдельный host с `sandbox`, имя БД содержит нормализованный environment ID |
| Redis | отдельный sandbox host и prefix `sandbox:<environment-id>:` |
| Celery | queue `nura-sandbox-<environment-id>` |
| Evidence | содержит тот же environment ID |
| Public URL | HTTPS hostname точно равен `SANDBOX_EXPECTED_HOSTNAME` |

Production volumes, external networks, container names и default queue `celery`
в sandbox Compose не используются. Runtime DSN обязан точно совпасть с
`SANDBOX_EXPECTED_DATABASE_HOST` и `SANDBOX_EXPECTED_DATABASE_NAME`; Redis data,
broker и result backend — с `SANDBOX_EXPECTED_REDIS_HOST` и тремя отдельными
expected DB indices. Production-like resource markers блокируются.

## 3. Secrets и dotenv

При `APP_ENV=sandbox` dotenv исключён из источников Pydantic Settings независимо
от наличия `nura_app/.env`. Критические значения принимаются только через
read-only regular-file contracts:

- `SECRET_KEY_FILE`;
- `DATABASE_URL_FILE`;
- `REDIS_PASSWORD_FILE`;
- `TELEGRAM_BOT_TOKEN_FILE`;
- `YOOKASSA_SECRET_KEY_FILE`;
- `DEEPSEEK_API_KEY_FILE`.

Plaintext environment alternatives для этих credentials блокируют загрузку
Settings. Reader запрещает symlink/hardlink и, на POSIX, group/world-writable
secret files. Preflight и startup errors не печатают содержимое secret-файлов.

Tracked файл `.env.sandbox.example` содержит только имена и non-secret
параметры. Настоящие credentials, DSN и identity evidence в Git не помещаются.

## 4. Telegram

`SANDBOX_TELEGRAM_ALLOWED_USER_IDS` — обязательный глобальный allowlist.
Inbound middleware выполняется до registration, attribution и handlers.
Заблокированный sender не создаёт User, не запускает onboarding, AI, checkout
или delivery. В лог попадает только короткий salted fingerprint.

Все runtime `Bot` создаются через `SandboxGuardedBot`. Guard проверяет `chat_id`
непосредственно перед вызовом Telegram transport. Delivery services также
ставят explicit guard до изменения progress/quota state. Получатель вне
allowlist приводит к typed terminal error
`sandbox_telegram_recipient_not_allowed`; transport не вызывается.
Production PWA/report URLs скрываются из sandbox markup/text. Standby bot с
выключенным polling не вызывает даже bot-level Telegram methods; Admin Bot в
этом профиле запрещён.

До polling обязательна redacted identity evidence, совпадающая с:

- `SANDBOX_TELEGRAM_BOT_ID`;
- `SANDBOX_TELEGRAM_BOT_USERNAME`;
- `SANDBOX_ENVIRONMENT_ID`.

Pure validator и injectable verifier реализованы. Реальный `getMe` в
implementation-сессии не выполнялся. Polling по умолчанию выключен.

## 5. YooKassa

`ENABLE_INTERNAL_PAYMENT_SHORTCUT` и `YOOKASSA_EXPECT_TEST_MODE` независимы.
Для внешнего sandbox обязательно:

- shortcut — `false`;
- provider test mode — `true`;
- webhook verification — `true`;
- receipt configuration — полная;
- expected shop ID совпадает с runtime shop ID;
- redacted identity evidence подтверждена до checkout/webhook.

Канонический `buy_matrix` создаёт provider checkout. `PaymentAttempt.test_mode`
фиксирует provider-test режим. Entitlement активирует только
provider-verified webhook. Поле `remote.test` должно быть именно boolean `true`;
`false`, `null`, отсутствие и строковые значения блокируются. Return route
остаётся информационным.
Все legacy `PaymentService` provider methods (390 ₽ subscriptions, web,
recurring и cancellation) в sandbox блокируются до YooKassa SDK.

Evidence хранит SHA-256 shop ID, test-mode flag, receipt flag, hostname и
environment ID — без credential и raw provider response. Реальный YooKassa API
в implementation-сессии не вызывался.

## 6. AI egress и бюджет

В sandbox `DEEPSEEK_BASE_URL` и `DEEPSEEK_MODEL` обязаны точно совпасть с
`SANDBOX_AI_ALLOWED_BASE_URL` и `SANDBOX_AI_ALLOWED_MODEL`. Endpoint должен быть
внешним HTTPS и не может молча унаследовать production/default значение.

Перед каждым фактическим provider attempt атомарный Redis Lua gate резервирует:

- один внешний вызов;
- максимальное число completion tokens для этого attempt.

Ключи находятся под sandbox Redis prefix. Общий call/token budget переживает
рестарт worker. Retry, fallback и JSON repair считаются отдельными попытками.
Cache hit не резервирует новый вызов. Недоступный Redis, исчерпанный budget,
неверный endpoint/model или некорректная reservation блокируют вызов до HTTP.
Prompt, user content и API key gate не логирует.

## 7. Full-stack Compose и ingress

`nura_app/docker-compose.sandbox.yml` описывает отдельные PostgreSQL, Redis,
API, Telegram bot, Celery worker и Celery Beat, project-owned volumes и сети.
API только `expose`-ится во внутреннюю сеть. Worker слушает только sandbox queue.
Beat содержит только chat delivery и report generation
dispatch/reconciliation.

`nura_app/config/sandbox-nginx.conf.sample` — неприменяемый sample. Публичный
ingress contract допускает только:

- `/health`;
- `/ready`;
- `/api/v1/payment/webhook`;
- `/api/v1/payment/full-matrix/checkout/{public_id}`;
- `/api/v1/payment/full-matrix/return/{public_id}`.

Admin API, auth, tokenized reports, PWA и debug routes не входят в публичный
contract. Контракт исполняется внутри API middleware до routing; tracked Nginx
sample остаётся дополнительным внешним слоем. Реальные proxy, DNS и TLS этой
работой не настраиваются.

## 8. Offline preflight

Из `nura_app/`:

```powershell
python tools/external_sandbox_preflight.py
```

Команда не выполняет network I/O, не запускает services, не создаёт payment,
не отправляет Telegram, не вызывает AI и не применяет migration. Вывод —
canonical redacted JSON с PASS/FAIL по каждому gate и итогом
`READY_FOR_EXTERNAL_IDENTITY_CHECK` или `BLOCKED`.

Режимы `--external-identity-check telegram|yookassa` оставлены как явная
будущая граница и сейчас возвращают `BLOCKED`: bundled network adapter
намеренно отсутствует. Их нельзя запускать без отдельного разрешения владельца
в будущей execution-сессии.

## 9. Owner prerequisites

Перед отдельной sandbox execution-сессией владелец должен предоставить:

1. уникальный environment ID и sandbox hostname;
2. отдельные PostgreSQL/Redis resources и новые empty volumes;
3. Telegram test bot и минимальный список test-user IDs;
4. YooKassa test shop и подтверждённые receipt parameters;
5. отдельный AI key, approved endpoint/model и числовой budget;
6. Docker secret files с безопасными permissions;
7. evidence owner, cleanup owner и retention/cleanup plan;
8. отдельное разрешение на external identity checks, Compose start, DNS/TLS и
   любые provider actions.

После будущих identity checks redacted evidence должна быть проверена до
включения polling и payment. `READY_FOR_EXTERNAL_IDENTITY_CHECK` не означает
готовность к deploy или внешнему трафику.

## 10. Stop criteria

Немедленно остановить подготовку при любом из условий:

- production hostname, bot, DB, Redis, queue, volume, credential или recipient;
- real-money/non-test YooKassa mode;
- Telegram recipient вне allowlist;
- неизвестный AI endpoint/model или исчерпанный budget;
- Alembic head не равен `d8e9f0a1b2c3`;
- dotenv/plaintext secret влияет на sandbox;
- preflight выдаёт хотя бы один FAIL;
- необъяснимый внешний вызов, secret/PII в output или отсутствие cleanup owner.

Текущее состояние — только локальная реализация и fake/offline evidence.
Внешний sandbox, deploy и provider execution остаются `NOT EXECUTED`.
