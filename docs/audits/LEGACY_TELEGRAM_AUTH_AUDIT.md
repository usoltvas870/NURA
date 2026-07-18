# Legacy Telegram `tgauth_` Security Audit

## Remediation status

- LTA-001 closed: legacy HTTP entry points return a stateless `410 Gone` tombstone.
- LTA-002 closed: legacy polling no longer reads or consumes Redis state.
- Legacy HTTP entry points are retired.
- The bot legacy entry point is blocked before `UserRegistrationMiddleware`.
- The legacy flow is unreachable for authorization.
- Legacy authorization implementation, session issuance, and Redis token flow are removed.
- `tgauth_` remains only as a tombstone compatibility contract.
- Dead-code cleanup is completed.
- The audit body below is a historical pre-remediation snapshot retained as finding evidence.

**Scope.** Static and targeted-test audit of the legacy Telegram browser-login flow only. The newer `link_` profile-linking flow, production code, tests, configuration, `STATE.md`, Graphify, and the main worktree were not changed.

**Verdict: FAIL — do not retain this flow as-is.** The legacy endpoints have no production-UI caller and have two confirmed P1 session issues. Recommended architectural decision: **C — remove the legacy flow after a small, separately approved removal task.** This conclusion is about the checked-out code; deployment/runtime telemetry was not queried.

## Evidence map and production entry points

| Surface | Role | Evidence |
|---|---|---|
| `POST /api/v1/web/auth/start` | Public state-changing start; makes the bearer token and Telegram deep link | `nura_app/api/routes/web.py:587-600` |
| `GET /api/v1/web/auth/check?token=` | Public polling endpoint; consumes a completed token and sets a web-session cookie | `nura_app/api/routes/web.py:603-616` |
| Bot `/start tgauth_<token>` | Public Telegram entry point | `nura_app/bot/handlers/start.py:51-60`, `:143-191` |
| Bot middleware | Pre-creates/loads a user from trusted Telegram update identity before the handler | `nura_app/bot/main.py:53-58`; `nura_app/bot/middlewares/registration.py:15-24` |
| Session dependency | Looks up the cookie value in `users.web_session_id`, checks expiry, renews it, and reissues the cookie | `nura_app/api/dependencies.py:21-30`, `:40-59` |
| Persistence | `telegram_id` and `web_session_id` are unique DB columns | `nura_app/core/models.py:39-45` |
| Reverse proxy/CORS/SW | API is proxied without cache rules; CORS permits only NURA origins; SW bypasses `/api/` | `nura_app/nginx/nura-ai.ru.conf:83-90`; `nura_app/api/main.py:38-44`; `frontend/service-worker.js:14-42` |

No frontend HTML/JS caller for `/auth/start`, `/auth/check`, `auth_token`, or `tgauth_` was found. `frontend/pwa/app/profile.html:123-125` uses only `/generate-link-token`, `/confirm-telegram-link`, and `/cancel-telegram-link` for the new `link_` flow. The only code reference outside the legacy implementation is a dispatcher-preservation test (`nura_app/tests/test_telegram_link_bot_flow.py:260-269`). No Nginx/deploy route-specific reference was found beyond the general `/api/` proxy. Historical documentation contains obsolete `AUTH_TOKEN` examples (`docs/bot-spec-pwa-patch.md:41`, `docs/platform-strategy.md:300`) but no `tgauth_` caller.

## Reconstructed flow

1. An unauthenticated browser calls public `POST /api/v1/web/auth/start`; an optional cookie identifies an existing web user (`web.py:587-595`).
2. The route creates `str(uuid.uuid4())` (UUIDv4, about 122 random bits) and writes raw key `auth_token:<token>` in Redis with TTL **300 seconds** (`web.py:593-596`).
3. The Redis value is literal `"pending"` when no valid browser cookie was supplied; otherwise it is that user's existing raw `web_session_id` (`web.py:595`). It contains no explicit status, issuer, intended Telegram ID, browser binding, or hash.
4. The response returns the raw token and `https://t.me/<bot>?start=tgauth_<token>` (`web.py:597-600`). Thus the token is a bearer credential in the Telegram deep-link payload.
5. Telegram passes the payload to the bot. `/start` strips the prefix and calls `_handle_tg_auth_token` (`start.py:57-60`). Before that handler, `UserRegistrationMiddleware` obtains or creates a `User` with `event_from_user.id` (`registration.py:15-24`); the identity is taken from Telegram, not a browser parameter.
6. The handler atomically executes Redis `GETDEL auth_token:<token>` (`start.py:143-154`). Missing/expired values return an error.
7. If the value was an existing `web_session_id`, the handler finds that user, attempts to attach `message.from_user.id`, renews the session expiry, restores the same Redis key for **60 seconds**, and confirms in Telegram (`start.py:159-176`). It does not merge accounts.
8. If the value was `pending`, the handler obtains/creates the Telegram user, generates `uuid.uuid4().hex` as a 32-hex-character session ID, stores it in the user record, and restores the same Redis key for **300 seconds** (`start.py:178-187`; `user.py:503-522`).
9. The browser polls public `GET /auth/check?token=`. Missing means `expired`; `pending` remains `pending`; any other Redis value is treated as a session ID (`web.py:603-613`).
10. For a completed value the route executes **separate** `GET`, `DELETE`, and `Set-Cookie`; it sets `nura_session_id=<value>` and returns `{"status":"ok"}` (`web.py:607-616`). The cookie is `HttpOnly`, `Secure` according to settings, `SameSite=Lax`, root scoped, and has the configured 90-day max age (`dependencies.py:21-30`; `config.py:83-85`).
11. A normal authenticated request resolves that cookie against the unique DB `web_session_id`, rejects expiry, then renews the DB expiry and cookie (`dependencies.py:40-59`). The DB expiry is 90 days and sliding (`user.py:476-485`).
12. `POST /logout` clears the current user's DB session, deletes the new-flow pending confirmation, and clears the browser cookie (`web.py:544-556`). A prior `tgauth_` token containing that now-cleared session ID later fails the handler lookup (`start.py:159-163`); this is fail-closed.

## Account, conflict, replay, and concurrency contracts

- **Identity and creation:** Telegram identity comes from `message.from_user.id` (`start.py:165`, `:178-181`), not request data. The registration middleware and `get_or_create_by_telegram_id` use the same ID; PostgreSQL `ON CONFLICT DO NOTHING` then selects the unique user (`user.py:40-58`).
- **Existing user/link:** a non-`pending` token selects a user by the prior session value and calls `update_telegram_id`. That method refuses replacing a different already-linked ID (`user.py:366-380`). It does not pre-check whether the proposed Telegram ID belongs to another user; the DB unique constraint determines that at commit.
- **Merge:** no merge occurs in this legacy handler. The newer link flow has a safer conflict-aware method, but it is out of scope (`user.py:391-419`).
- **Token consume:** bot-side initial consumption is atomic (`GETDEL`), so two bot `/start`s cannot both turn the initial pending value into a session. Browser-side consume is not atomic: two `/auth/check` requests can both read a completed value before either deletes it.
- **Replay:** bot replay is rejected after `GETDEL`; browser replay is possible in the race window (Finding LTA-002). The restored completed key itself remains valid for 60 or 300 seconds unless consumed or expired.
- **Conflict:** switching a web user's already different Telegram ID returns a user-facing conflict. A collision where the proposed Telegram ID belongs to another row can raise `IntegrityError` into the broad handler exception instead of returning a controlled conflict (Finding LTA-004). No silent merge or replacement was verified.
- **Logout/session invalidation:** logout clears only the user addressed by its current optional cookie. It invalidates that DB session, so legacy completed tokens referring to it cannot be resolved by the bot. It does not revoke a separately issued legacy session for another browser unless it is that user's single `web_session_id`.
- **Parallel starts:** multiple starts create independent Redis keys. For `pending`, each completed Telegram auth overwrites that Telegram user's single DB `web_session_id`; older sessions then stop resolving. This is an availability/session-continuity effect, not an account merge.

## HTTP, cache, privacy, and logging assessment

- `/auth/start` is public `POST`, rate-limited at 10/hour; `/auth/check` is public **GET**, rate-limited at 60/minute (`web.py:587-605`). Both change state; the latter also writes an authentication cookie.
- CORS is allowlist-only and credentialed for the two NURA origins (`api/main.py:38-44`), but it does not protect top-level navigation, image, or form-style CSRF. `SameSite=Lax` does not prevent a response from setting a cookie during such a navigation.
- No endpoint-specific `Cache-Control: no-store` exists. Nginx applies no cache-control rule to `/api/` (`nginx/nura-ai.ru.conf:83-90`). The service worker deliberately returns before caching API requests (`frontend/service-worker.js:33-42`), so it does not create an additional cache path.
- The token is returned to the caller and embedded in a Telegram deep link; it can therefore appear in client-side network tooling and Telegram link/message history. The request-correlation middleware logs only method, URL **path** (not query), status, and timing (`api/middleware.py:42-49`), so it does not itself log the polling token. The legacy bot exception logger does log the raw Telegram ID (`start.py:189-191`).
- Normal legacy responses contain token/tg URL at start, a status at poll, and a Set-Cookie header on success. They do not return Telegram ID, user UUID, or session ID in JSON. Redis holds raw token and raw session ID. No raw Redis value is logged on the normal path.

## Findings

### LTA-001 — P1: login CSRF / silent account switch through state-changing GET

- **Affected code:** `nura_app/api/routes/web.py:603-616` (`auth_check`); cookie issuance in `nura_app/api/dependencies.py:21-30`.
- **Current behavior:** unauthenticated `GET /api/v1/web/auth/check?token=<completed-attacker-token>` deletes the token and sets `nura_session_id` to the session held in Redis. It has no browser-origin, CSRF, or one-time confirmation requirement.
- **Exploit:** an attacker starts and completes a legacy login for the attacker's own NURA account, then causes a victim browser to request the completed URL (for example, a link or embedded cross-origin request). The victim receives the attacker's session cookie and is silently switched into the attacker account.
- **Impact:** P1 under the task definition: silent account switch. It can expose the victim's subsequent activity/data entered in the application to the attacker's account and can misdirect purchases or profile actions.
- **Minimal fix:** replace the public state-changing GET with a same-origin, CSRF-protected POST bound to a browser-held nonce; reject cross-site requests. Issue the session only after an atomic server-side consume.
- **Required regression:** a cross-origin navigation/request with a completed attacker token must not set an authenticated session; a legitimate same-origin completion must still succeed exactly once.

### LTA-002 — P1: non-atomic browser token consume permits concurrent session issuance

- **Affected code:** `nura_app/api/routes/web.py:607-616` (`auth_check`).
- **Current behavior:** `GET` reads the completed Redis value, then separately deletes it and sets the cookie. There is no `GETDEL`, transaction, or Lua compare-and-delete.
- **Exploit:** two concurrent requests holding the same completed bearer token can both complete the `GET` before either `DELETE`. Both responses set the same valid web session cookie.
- **Impact:** P1: replay that genuinely grants multiple browser sessions. This is especially material because the bearer token is embedded in a Telegram deep link.
- **Minimal fix:** atomically consume only a completed record (for example `GETDEL` with explicit state validation, or a Lua script) before calling `set_session_cookie`; retain the browser-binding/CSRF protection from LTA-001.
- **Required regression:** race two `/auth/check` calls after completion; exactly one may receive `ok`/Set-Cookie and the other must receive a non-authenticated terminal status.

### LTA-003 — P2: raw bearer token is exposed in a Telegram deep link and no-store policy is declared

- **Affected code:** `nura_app/api/routes/web.py:593-600`, `nura_app/bot/handlers/start.py:143-187`, `nura_app/nginx/nura-ai.ru.conf:83-90`.
- **Current behavior:** Redis stores a raw token and session value; the API returns the token and a deep link containing it; neither endpoint declares `Cache-Control: no-store`.
- **Exploit/failure:** anyone with the deep link during its TTL can invoke the bot, and anyone with a completed token can race/consume polling. Browser/history, Telegram client, and intermediary retention enlarge the bearer-token exposure surface.
- **Impact:** session issuance if exposed token is used before expiry; also privacy leakage of a login correlation value.
- **Minimal fix:** eliminate the flow (recommended). If retained, avoid a reusable bearer token in a deep link, store only a token hash, bind completion to a browser nonce, use no-store/referrer policy, and minimize TTL.
- **Required regression:** responses from start/completion carry no-store; logs and telemetry do not contain raw token/session values; a captured link cannot authenticate an arbitrary browser.

### LTA-004 — P2: Telegram-ID collision is handled as a broad exception and logs personal identifier

- **Affected code:** `nura_app/core/repositories/user.py:366-380`; `nura_app/bot/handlers/start.py:165-191`.
- **Current behavior:** `update_telegram_id` checks whether the target web user already has a different Telegram ID but does not handle an existing owner of the proposed ID. The unique-constraint failure can escape to the broad exception handler, which calls `logger.exception(...telegram_id=%s)`.
- **Exploit/failure:** attempting to attach a Telegram account already linked to another NURA row can produce a generic failure, consume the initial token, and write the raw Telegram ID plus traceback context to logs.
- **Impact:** denial of the login attempt and unnecessary personal-ID disclosure in logs; no account takeover or merge was verified.
- **Minimal fix:** use the conflict-safe repository contract already used by the new flow (or catch `IntegrityError` locally), return a stable conflict response, and log only a non-reversible correlation value.
- **Required regression:** a duplicate Telegram ID produces the controlled conflict, does not alter either account, does not issue a session, and does not log raw Telegram ID.

### LTA-005 — P3: legacy route has no production caller and no end-to-end coverage

- **Affected code:** legacy implementations above; test inventory below.
- **Current behavior:** no production UI calls legacy endpoints. The only direct `tgauth_` test stubs the handler and checks dispatch.
- **Failure:** removal/hardening could regress unnoticed; current P1 defects have no test coverage.
- **Impact:** maintenance and security debt rather than direct exploitation.
- **Minimal fix:** remove the dead legacy surface in a dedicated task. If retention is required, first add real route/bot/Redis race, conflict, logout, and privacy tests.
- **Required regression:** removal test asserting no production frontend reference and no legacy routes/handler remain, or a complete retained-flow contract suite.

## Existing test inventory

| Node ID | What it actually checks | Real route/handler / Redis | Replay, concurrency, conflict, logout |
|---|---|---|
| `tests/test_telegram_link_bot_flow.py::test_cmd_start_preserves_tgauth_dispatch` | `cmd_start` strips `tgauth_` and awaits a mocked `_handle_tg_auth_token` | Real dispatcher only; handler mocked; no Redis | None |

No test node was found for `auth_start`, `auth_check`, `_handle_tg_auth_token` behavior, raw `auth_token:` Redis content/TTL, browser replay, concurrent poll, conflict, logout invalidation, cache headers, or log redaction. The listed test is neither skipped nor xfailed. The nearby file's fake Redis is used for the **new** link-confirmation flow, not the legacy handler (`tests/test_telegram_link_bot_flow.py:18-80`). The E2E harness has logout/profile scenarios but no `tgauth_` endpoint (`nura_app/tests/e2e_harness.py:295-298`).

## Decision and removal inventory

**Decision C — remove.** The legacy path has no checked-in production frontend caller or documented fallback use, while Email, VK, and the newer Telegram `link_` flow are separate contracts. Removing it does not, from repository evidence, remove Email/VK functionality or Profile's new Telegram linking; nevertheless, production telemetry/support channels were not queried, so the removal task should first confirm no external/mobile caller.

The follow-up removal task should delete or replace:

- routes `POST /api/v1/web/auth/start` and `GET /api/v1/web/auth/check`, their `AuthStartResponse`/`AuthCheckResponse` models, and imports only used by them in `nura_app/api/routes/web.py`;
- `/start tgauth_` dispatch and `_handle_tg_auth_token` in `nura_app/bot/handlers/start.py`;
- Redis namespace `auth_token:<token>`; no other production code reference was found;
- the legacy dispatch preservation test in `nura_app/tests/test_telegram_link_bot_flow.py`;
- stale historical `AUTH_TOKEN` documentation examples after validating their intended contract.

Do **not** remove the separate `link_token:` and `telegram_link_pending:` Redis keys, Profile link UI, or the `link_` handler/confirmation service.

## Recommended small next tasks

1. Owner confirms no external client relies on `/api/v1/web/auth/start`, `/auth/check`, or `tgauth_`.
2. Remove the legacy route, bot branch, key namespace, test, and stale documentation in one reviewed change; add absence/reference tests.
3. Run the existing new `link_` backend and browser E2E contracts after removal.
4. Separately audit server access logs/telemetry retention for historical deep-link tokens and Telegram IDs; do not put credentials or logs in source control.

## Executed checks and change record

- `tests/test_telegram_link_bot_flow.py::test_cmd_start_preserves_tgauth_dispatch` — **passed** (1 passed). Pytest emitted a permission warning while trying to update its cache; no test file changed.
- `ruff check --no-cache api/routes/web.py bot/handlers/start.py core/services/auth.py core/repositories/user.py` — **passed**.
- `git diff --check` and final `git status --short` — to be run after writing this report.

**Changed file:** this audit report only. `STATE.md` and Graphify were not updated: **Graphify update is not required** for an audit report with no architecture/code change.

**Confirmation:** no production code, tests, new `link_` flow, or Profile code was changed; no real Telegram call or production credential was used; no staging, commit, or push was performed; `C:\git\NURA` was not modified.
