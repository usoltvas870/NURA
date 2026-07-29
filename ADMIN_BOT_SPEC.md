# NURA Admin Bot — Current Operations Contract

> **STATUS: CURRENT OPERATIONS — ADMIN BOT CONTRACT**
>
> Evidence boundary: static inspection of committed code and existing tests. This document does not prove sandbox or production availability and does not authorize deploy or other external actions.

## 1. Authority and scope

The Admin Bot is a separate aiogram polling process for one configured Telegram administrator. Its current contract is container observation, four explicit commands, limited natural-language routing and scheduled health alerts.

Code/tests are authoritative for implementation. Product-level support/admin target is defined by the [canonical product spec](docs/product/NURA_1_0_1_5_PRODUCT_SPEC.md); the compact current mirror is [current status](docs/implementation/current-status.md).

The adjacent `/api/v1/admin/*` Admin API is a separate surface. Its user, payment, promo, report, health, log and broadcast endpoints do not automatically become Admin Bot commands.

## 2. Status legend

- `CURRENT — REGISTERED` — a command family or target is advertised, allowlisted and routed in the inspected code; registration does not prove that its runtime side effect succeeds.
- `CURRENT — IMPLEMENTED` — the inspected code path supports the stated current behavior; this still does not establish sandbox or production availability.
- `CURRENT OPERATIONS` — supported operator behavior, without a production-availability claim.
- `EVIDENCE BOUNDARY` — static/local evidence does not establish external deployment.
- `IMPLEMENTATION GAP` — code exists but is not wired into the current bot contract, or target behavior is incomplete.
- `HISTORICAL / SUPERSEDED` — old implementation-plan text that must not be executed.
- `OWNER DECISION PENDING` — deployment/topology or future capability not decided by this document.

## 3. Current runtime and entrypoint

`CURRENT — IMPLEMENTED`

- Entrypoint: `python -m admin_bot.main`.
- `admin_bot/main.py` creates `Bot`, `Dispatcher` and in-memory FSM storage, installs admin-only middleware and starts polling.
- Docker Compose declares a separate `admin-bot` service, passes application environment/secrets, mounts `/var/run/docker.sock`, waits for PostgreSQL, Redis and API health, and uses the same project network.
- `core/config.py` is the runtime configuration authority for `ADMIN_BOT_TOKEN` and `ADMIN_TELEGRAM_ID`.
- Missing/placeholder token or missing administrator ID fails closed: polling is not started and the process remains idle after logging the configuration error.

No alternative «second process in the user bot container» is part of the inspected current wiring.

## 4. Authorization boundary

`CURRENT — IMPLEMENTED`

- `AdminOnlyMiddleware` permits messages and callback queries only when `event.from_user.id` equals the single configured `ADMIN_TELEGRAM_ID`.
- Denied messages receive «Доступ запрещён» and are logged; denied callbacks are not handled.
- Secrets are read from settings and are not intentionally included in bot replies.
- The Admin API uses a separate `X-Admin-Token` dependency. Telegram whitelist authorization does not grant Admin API access, and Admin API authentication does not register bot commands.

This is a single-admin whitelist contract, not role-based access control or a multi-operator audit system.

## 5. Current supported operations

| Operation | Current behavior | Side effect | Status |
|---|---|---|---|
| `/status` | Lists project containers through the current name resolver, then checks `http://api:8000/health`; API and bot remain distinct, but both default Celery container names are displayed as `celery` | Read-only Docker/API access | `CURRENT — IMPLEMENTED`; `IMPLEMENTATION GAP` for distinct Celery identity/coverage |
| `/restart api` | Restarts the API container through Docker socket | Container restart | `CURRENT — IMPLEMENTED` |
| `/restart bot` | Restarts the user-bot container | Container restart | `CURRENT — IMPLEMENTED` |
| `/restart celery-worker` | Target is accepted by the registered handler, but the default Compose container resolves to `celery`; exact lookup for `celery-worker` finds no container ID and the handler reports failure | Intended container restart is not reached on the verified default-Compose path | `CURRENT — REGISTERED`; `IMPLEMENTATION GAP` |
| `/restart celery-beat` | Target is accepted by the registered handler, but the default Compose container resolves to `celery`; exact lookup for `celery-beat` finds no container ID and the handler reports failure | Intended container restart is not reached on the verified default-Compose path | `CURRENT — REGISTERED`; `IMPLEMENTATION GAP` |
| `/cache clear` | Calls Redis `FLUSHDB` through the configured Redis connection | Clears the entire selected Redis database, not a namespace-only cache | `CURRENT — IMPLEMENTED` |
| `/help` | Shows the four registered command families and natural-language examples | None | `CURRENT — IMPLEMENTED` |
| Plain text | Detects restart/cache intent; API/bot restart and cache clear route to their current operations, while `celery-worker`/`celery-beat` restart inherits the same exact-lookup failure; other text sends normalized container status plus the question to `AIService.chat()` | May restart API/bot or call Redis `FLUSHDB`; Celery restart is not reached on the verified path; otherwise AI call only | `CURRENT — IMPLEMENTED` with the Celery restart `IMPLEMENTATION GAP` |
| Scheduled `monitor_health` | Every five minutes checks API, normalized container states and recent error-like logs; Celery aliases can cause one Celery container to be scanned twice while the other is missed | Telegram alert; read-only inspection | `CURRENT — IMPLEMENTED`; complete Celery status/log coverage is `IMPLEMENTATION GAP` |

Only `help_router`, `status_router`, `restart_router`, `cache_router` and `chat_router` are registered. Files for `/logs` and `/errors` exist, but their routers are not included in the dispatcher and therefore they are `IMPLEMENTATION GAP`, not supported current commands.

The `/restart` command family, its advertised `celery-worker` and `celery-beat` targets, and the corresponding natural-language targets are registered. That registration does not make the Celery operations runtime-reachable. With default Compose naming, `nura_app-celery-worker-1` and `nura_app-celery-beat-1` are split on `-`, while `DockerClient.list_containers()` keeps only `parts[1]`; both therefore become `celery`. `get_container_id()` compares this alias exactly with the requested target, so neither `celery-worker` nor `celery-beat` obtains a container ID and `restart_container()` returns `False` without issuing a Docker restart request.

## 6. Current data and side effects

- Docker inspection, logs and restart use the mounted Docker socket. Restart targets are allowlisted to `api`, `bot`, `celery-worker` and `celery-beat` at handler level.
- `/cache clear` is a broad Redis database mutation. It can remove FSM, chat history, short-lived task state and other keys sharing that database; the current code does not preview or namespace the deletion.
- Natural-language restart/cache detection is rule-based before AI invocation. API/bot targets reach the same implemented restart path as their explicit commands; Celery targets reach the same registered-but-unresolved path described above. The AI response cannot execute an arbitrary shell command.
- AI advisory receives container status and the administrator's text. It is not a source checkout, deployment or database mutation interface.
- A generic `run_db_query()` helper exists in `DockerClient`, but no registered handler calls it. There is no registered database command in the current bot contract.
- User lookup, payment listing, subscription/tarot grants, report regeneration, promo management, health, logs and broadcast start/status exist on the separately authenticated Admin API. They are not exposed by the current Admin Bot.
- No refund endpoint or Admin Bot refund action was found. Support and refund workflows must not be inferred from generic admin capabilities.
- Broadcasts are initiated through the Admin API/Celery foundation, not through this bot. Current broadcast persistence/opt-out/analytics gaps remain governed by the accepted bot/current-status documents.

## 7. Error, retry and audit behavior

- Command handlers catch operational exceptions, write stack context to application logs and return a short error message to the authorized administrator.
- Docker list/log helpers degrade to empty results after logging failures; restart/cache helpers return boolean success.
- `monitor_health` reports API failures, stopped containers and parsed recent error lines, subject to the Celery identity limitation below. Failure to send an alert is logged but is not durably retried by the task itself.
- Container-state iteration retains two Celery inventory rows but labels both `celery`. Log scanning then calls `get_container_logs(c["name"])`; each `celery` lookup can select the first matching Celery container, so one container can be read twice and the other can be missed. Monitoring exists and can still report other issues, but complete Celery status/log coverage is not established.
- Log parsing filters common health/heartbeat noise and recognizes ERROR/CRITICAL/FATAL/Exception/Traceback/5xx patterns.
- The natural-language AI path returns a fixed fallback if the model call fails.
- No durable per-command audit ledger, approval workflow or multi-admin attribution was found. Application logs are the current audit evidence.

Local code paths do not establish production retention, alert delivery or operator response procedures.

## 8. Deployment and environment boundary

- The inspected compose topology runs `admin-bot` as a separate service with Docker socket access.
- Runtime secrets/configuration come from the existing settings/env mechanism; this document does not contain token values or assert that BotFather/VPS configuration is complete.
- The bot does not perform source checkout, production build or deploy. There is no production-deploy command or deployment service method.
- Production release is outside this bot and is permitted only through the approved manual GitHub Actions workflow documented in [DEPLOY.md](DEPLOY.md), with its own current-task authorization.
- Static inspection and local tests do not prove that the service is running in sandbox or production.

`OWNER DECISION PENDING` — any change to production topology, Docker-socket exposure, multi-admin authorization or operational approval workflow.

## 9. Current limitations

- Single Telegram administrator ID; no roles or second approver.
- In-memory FSM storage for this bot process.
- `/logs` and `/errors` code is dormant because routers are not registered.
- Default Compose names for `celery-worker` and `celery-beat` collapse to the shared `celery` alias in `DockerClient`; explicit and natural-language Celery restart therefore remain registered operations with a current runtime `IMPLEMENTATION GAP`.
- `/status` cannot reliably distinguish the worker from Beat, and scheduled log monitoring can duplicate one Celery scan while omitting the other; this limitation does not imply that all Admin Bot monitoring is non-functional.
- No user/payment/refund/support/broadcast command surface in the bot itself.
- No persistent command audit ledger.
- Redis clear is database-wide rather than scoped.
- AI advice is informational and may fail; it is not an acceptance or remediation engine.
- Scheduled alerts are best-effort and do not prove incident delivery or acknowledgement.

## 10. Superseded implementation plan

The previous document's «нужно создать», BotFather checklist, optional container alternatives and eight-step implementation order were historical planning text. The module, compose service, registered commands and monitor task now exist, so that sequence must not be rerun as a backlog.

The historical plan also mentioned `/logs`, `/errors`, an Admin API bridge and AI error analysis as if they were all active bot operations. Current router registration is narrower and governs this contract.

## 11. Acceptance boundary

| Evidence layer | Established | Not established |
|---|---|---|
| Static inspection | Entrypoint, middleware, registered routers/targets, API/bot restart paths, Redis `FLUSHDB`, compose wiring, scheduled task and no-deploy boundary | Successful Celery worker/Beat restart or complete distinct Celery status/log coverage |
| Existing local tests | No deploy or database command, command-family registration and fail-closed deprecated deploy path | Coverage of hyphenated default-Compose name resolution, successful Celery restart or complete Celery monitoring |
| Dated documentation | Current status marks support/admin locally ready | Production permissions, BotFather configuration, alert receipt or operator SLA |
| Production | Not checked in this session | Any availability/readiness claim |

Tests were read as static evidence and were not run by explicit instruction for Write Session 5.

Closing the Celery gap requires future evidence that service/container resolution preserves distinct `celery-worker` and `celery-beat` identities for default Compose names, focused tests for that resolution, successful restart evidence for both targets, and separate `/status` and log-monitoring coverage for both containers. This is an acceptance boundary, not a code-fix plan for this documentation session.

## 12. References

- [Documentation authority router](docs/README.md)
- [Canonical product spec](docs/product/NURA_1_0_1_5_PRODUCT_SPEC.md)
- [Current implementation status](docs/implementation/current-status.md)
- [Current bot specification](docs/bot-spec.md)
- [Deployment contract](DEPLOY.md)
- `nura_app/admin_bot/main.py`
- `nura_app/admin_bot/middleware.py`
- `nura_app/admin_bot/handlers/`
- `nura_app/admin_bot/services/docker_client.py`
- `nura_app/core/tasks.py` (`monitor_health`)
- `nura_app/api/routes/admin_api.py`
- `nura_app/core/config.py`
- `nura_app/docker-compose.yml`
- `nura_app/tests/test_admin_bot_deploy_contract.py`
