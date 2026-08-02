# Production secret files and migration-aware prelaunch transition

> **STATUS: RUNBOOK — NOT EXECUTION PROOF**
>
> Этот документ описывает локально реализованный contract. Он не доказывает
> состояние VPS, не является authorization manifest и не разрешает backup,
> rotation, stop, migration, deploy, rollback, provider call или cleanup.

## 1. Secret profile

Production profile version: `production-files-v1`.

Host directory `/opt/nura/secrets/production/` принадлежит `root:root` и имеет
mode `0700`. Каждый secret — отдельный regular non-symlink file с одним hardlink,
владельцем `root:root` и mode `0400` либо `0600`. Container path всегда
`/run/secrets/<name>`. Single-line credentials не допускают NUL/CR/LF и
ограничены 16 KiB; VAPID private key использует отдельный UTF-8 multiline reader
с сохранением newline и лимитом 64 KiB. Ошибки содержат только bounded code.

| Secret file | Settings contract | Active production consumers |
|---|---|---|
| `postgres_password` | Docker `POSTGRES_PASSWORD_FILE` | postgres |
| `secret_key` | `SECRET_KEY_FILE` | api, bot, worker, Beat, admin-bot |
| `database_url` | `DATABASE_URL_FILE` | api, bot, worker, Beat, admin-bot |
| `redis_password` | `REDIS_PASSWORD_FILE` | Redis и все application services |
| `telegram_bot_token` | `TELEGRAM_BOT_TOKEN_FILE` | api admin health, bot, delivery/broadcast worker |
| `deepseek_api_key` | `DEEPSEEK_API_KEY_FILE` | api, bot, worker, admin-bot advisor |
| `vapid_private_key` | `VAPID_PRIVATE_KEY_FILE` | api, worker |
| `admin_bot_token` | `ADMIN_BOT_TOKEN_FILE` | worker notifications, admin-bot |
| `admin_token` | `ADMIN_TOKEN_FILE` | admin API |
| `smtp_password` | `SMTP_PASSWORD_FILE` | worker email delivery |
| `vk_client_secret` | `VK_CLIENT_SECRET_FILE` | API legacy VK auth consumer |

YooKassa support в Settings сохраняется для public production, но owner-only
prelaunch не содержит shop/key/return/receipt configuration и не монтирует
`yookassa_secret_key`.

Production `.env` содержит только non-secret configuration. Container `*_FILE`
paths задаёт Compose per-service, поэтому отсутствие mount невозможно скрыть
общим `env_file`. Owner-prelaunch Settings отклоняет plaintext alternatives;
offline preflight дополнительно отклоняет direct secret keys, `*_FILE` aliases в
`.env` и конфликтующие upper/lowercase aliases.

`database_url` заранее формирует оператор внутри private owner-only staging
boundary из отдельно ротированного PostgreSQL password. Значение записывается
атомарно с restrictive umask прямо в secret file, не передаётся CLI argument,
не печатается и не включается в evidence. Этот milestone не создаёт DSN и не
ротирует password.

## 2. Compose and rotation boundary

Tracked `nura_app/docker-compose.yml` использует host-backed Docker secrets.
PostgreSQL получает только `POSTGRES_PASSWORD_FILE`; application services —
`DATABASE_URL_FILE`. Redis entrypoint читает один mounted password, создаёт
private runtime config в tmpfs и не включает credential в Compose command.
Redis/Celery URLs до Settings load не содержат credentials; Settings добавляет
percent-encoded password только в памяти.

Каждый service монтирует только перечисленные в matrix secrets. YooKassa secret
отсутствует. Base Compose задаёт `RUN_MIGRATIONS=0`: migrations может применять
только one-time engine после всех gates. Bot polling параметризован и при
transition остаётся выключенным до финальной отдельной activation.

Rotation выполняет оператор после verified backup и до offline readiness. Engine
не генерирует, не копирует и не изменяет secret values. `docker compose config`
видит только host paths и container paths, а не содержимое files.

## 3. Offline preflight

Из `nura_app/` запускается read-only CLI:

```text
python tools/current_vps_prelaunch_preflight.py
```

Он не использует network, Docker, PostgreSQL, Redis или providers. Canonical JSON
содержит только gate names, secret basenames и результат
`READY_FOR_HOST_BACKUP_AND_RECOVERY` либо `BLOCKED`. Проверяются exact production
environment, один owner ID равный admin ID, payment/feature containment, governed
`report/v1` и `chat/v1`, secret metadata, Compose mounts, authenticated
Redis/Celery contract и target Alembic head. Execution mode дополнительно требует
существующий authorization manifest, но не считает его валидным до engine check.

## 4. Exact migration contract

Current revision: `d1e2f3a4b5c6`. Target head: `d8e9f0a1b2c3`.

Ordered forward chain:

1. `b1c2d3e4f5a6`
2. `c1d2e3f4a5b6`
3. `d2e3f4a5b6c7`
4. `d6e7f8a9b0c1`
5. `d7e8f9a0b1c2`
6. `e8f9a0b1c2d3`
7. `f9a0b1c2d3e4`
8. `b4c5d6e7f8a9`
9. `c5d6e7f8a9b0`
10. `c6d7e8f9a0b1`
11. `d8e9f0a1b2c3`

Aggregate contract digest:
`0277a4602fcc948e60450c80ec55121529f14443ee9616b38d3a4ead2549d0ad`.
`tools/current_vps_migration_contract.py` проверяет full graph single head,
parent order, filenames и SHA-256 каждого migration file. Цепочка reviewed как
additive/backward-compatible для exact application fleet `9da6ad8…`; это
разрешает только application/static compensation после migrated DB. Database
downgrade не обещается и engine его не выполняет.

## 5. Two-commit authorization

Этот implementation milestone создаёт engine и tests, но не создаёт manifest с
неизвестным target SHA. После owner review, commit, push и CI resulting commit
становится target `T`. Отдельный маленький milestone создаёт tracked canonical
manifest по пути `docs/operations/authorizations/current-vps-prelaunch-*.json`.

Manifest schema v2 фиксирует authorization base/source/target/engine commits,
engine file SHA-256, current/target DB revisions, ordered migrations,
aggregate digest, secret profile, backup evidence schema, capacity thresholds,
backward-compatibility/no-downgrade acknowledgements, opaque owner approval IDs,
bounded UTC window, artifact/manifest SHA-256 и checksum. Manifest не содержит
secrets, DSN, Telegram IDs или PII. Из-за невозможности включить SHA commit в
его собственный blob manifest фиксирует `authorization_base_commit_sha=T`.
Engine выводит authorization commit как exact `origin/main`, требует его
единственным родителем `T`, разрешает в нём изменение только exact manifest
path и сравнивает tracked blob побайтно. Arbitrary CLI transition override не
поддерживается.

## 6. Preconditions and capacity

До build, service stop или database mutation engine требует:

- отдельный `recover-stale` уже вернул P7B к canonical `9da6ad8…`;
- successful release state, отсутствие staged transaction и duplicate fleet;
- clean canonical `main` checkout, который является ancestor exact target, и
  доказанный `source_application_sha → target_application_sha` fast-forward;
- exact DB revision `d1e2f3a4b5c6`;
- checksummed verified PostgreSQL, Redis, configuration и release-state evidence:
  каждый record содержит absolute path внутри approved backup root, а engine
  после candidate build и непосредственно перед writer stop повторно открывает
  direct-child artifact через `O_NOFOLLOW`/backup-root descriptor, проверяет
  same-fd metadata до/после чтения, path inode, owner/mode/link count,
  фактический размер и streaming SHA-256;
- safe secret profile и offline preflight PASS;
- payments/YooKassa containment и exact owner allowlist;
- exact artifact/manifest identities;
- минимум 6 GiB free disk, 50,000 inodes и либо 3 GiB available RAM, либо уже
  созданный active swap минимум 2 GiB.

Engine никогда не создаёт swap. Текущий documented VPS (около 1.9 GiB RAM без
swap) блокируется до отдельного owner approval и заранее выполненного capacity
remediation. Prebuilt-image mode не реализован и не может быть выбран manifest.

## 7. Execution and failure boundary

Порядок: verified stale recovery → all read-only gates, включая exact running
fleet image IDs/tags/OCI revisions → candidate build и exact-target execution
bundle → stop writers → exact migration → target activation с polling off →
`/ready`, worker ping, running Beat и payment-disabled verification →
owner-only/YooKassa-free local identity при polling off → bot polling last →
polling verification → immutable receipt. Backup evidence требуется уже до первой
mutation; это намеренно строже старого checklist.

Failure до migration оставляет application/database без transition. Migration
failure останавливает процесс, сохраняет evidence и не вызывает downgrade.
Failure activation после successful migration вызывает только coordinated
application/static compensation к exact `9da6ad8…`; DB остаётся на
`d8e9f0a1b2c3`, после чего old fleet повторно проверяется. Cleanup отсутствует и
требует отдельного approval.

## 8. Approval points

Отдельное текущее approval требуется перед VPS access, backup, secret rotation,
capacity remediation/swap, stop writers, migration, activation, external
Telegram/DeepSeek smoke, rollback и cleanup. Local tests и preflight не являются
execution evidence.
