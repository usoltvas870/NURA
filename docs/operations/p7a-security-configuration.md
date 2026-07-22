# P7A security configuration contract

## Status and boundary

P7A prepares repository-side hardening for a controlled P7B rollout. It does
not change production configuration, rotate credentials, deploy an application
release, or align the production application SHA with `main`.

The read-only production observations in this document were collected on
2026-07-22 from application SHA `9da6ad8cf0146b26bdd2b60ebf99b54a58ccd532`.
No secret value was recorded.

## Confirmed production facts

- The effective application classification is `APP_ENV=development` and
  `settings.is_production=False`.
- `TEST_MODE=true`; session cookies are configured as Secure.
- YooKassa server-to-server verification is effectively enabled. The
  repository default is `YOOKASSA_VERIFY_ON_WEBHOOK=true`, and the production
  variable is unset, so the default applies.
- The YooKassa source-IP allowlist is empty.
- Redis authentication is enabled and Redis is healthy.
- Redis credentials are exposed in inspectable Docker metadata in three ways:
  the Redis server `--requirepass` command argument, the healthcheck `-a`
  argument, and the application-container environment through
  `REDIS_PASSWORD` plus credential-bearing Redis/Celery URLs.
- The Redis process title observed through `docker top` did not expose
  `--requirepass`; this does not mitigate the Docker configuration surfaces.
- The Redis service has no secret mount in the current production release.

The initial risk statement that YooKassa verification was disabled was not
confirmed. Provider verification is enabled, but production classification is
incorrect and the optional source-IP layer is not configured.

## Redis credential flow

### Previous flow

The host `.env` value was interpolated directly into the Redis command and
healthcheck. The same `.env` was passed wholesale to application containers,
and the Docker build context did not exclude `.env` before `COPY . .`.

### P7A flow

Compose creates `redis_password` from the existing host environment value and
mounts it only at `/run/secrets/redis_password`. This preserves the current
credential and does not rotate it.

- Redis starts through `redis-entrypoint.sh`. The helper reads the secret at
  runtime, creates a mode-0600 config in a mode-0700 tmpfs, and starts
  `redis-server` with only the config path in its arguments.
- Redis health uses `redis-healthcheck.sh`, which reads the file at runtime and
  supplies authentication through the short-lived `REDISCLI_AUTH` process
  environment. Neither password nor auth flag appears in the Docker
  healthcheck definition.
- Application services receive non-credential Redis endpoints and the secret
  file path. `core.config.Settings` URL-encodes the file value into the three
  runtime client URLs in process memory.
- `REDIS_PASSWORD` is explicitly removed from application-container
  environments even though the legacy shared `env_file` remains in use.
- `.dockerignore` excludes `.env` and `.env.*`, retaining only `.env.example`.

Docker Compose supports an environment variable as a secret source; this is a
Compose feature and not a Swarm `docker stack deploy` feature. See the
[Docker Compose secrets reference](https://docs.docker.com/reference/compose-file/secrets/).

## APP_ENV contract and behavioral delta

Only the exact canonical values `development`, `test`, `staging`, and
`production` are accepted. Aliases, case variants, whitespace variants, empty
values, and unknown values fail settings initialization.

`APP_ENV` has only these direct runtime consumers in the current repository:

1. `Settings.is_production`.
2. The production configuration validator.
3. YooKassa webhook verification enforcement.
4. The Sentry environment label.
5. Test/E2E harness guards outside runtime application code.

Auth mechanisms, CORS allowlists, SameSite/HttpOnly cookie attributes, SMTP,
VK, Telegram, rate-limit values, debug mode, logging level, CSRF behavior,
trusted-host middleware, HTTPS redirect behavior, and proxy trust are not
branched on `APP_ENV`. Session `Secure` is a separate setting and is now
required to be true in production. FastAPI debug is not enabled. There is no
TrustedHost or explicit CSRF middleware; CORS remains a fixed two-origin
allowlist. Uvicorn still trusts forwarded headers from `*`, so the YooKassa IP
allowlist must not be treated as an independent authentication mechanism until
proxy trust is narrowed in a separately approved infrastructure change.

Starting with `APP_ENV=production` now fails closed, using non-sensitive error
codes and hidden Pydantic input values, unless all of these hold:

- the application secret is non-default;
- session cookies are Secure;
- test mode is false;
- YooKassa provider verification and credentials are configured;
- Redis, Celery broker, and Celery backend URLs are authenticated after
  secret-file resolution.

The actual P7B delta is small but material: the Sentry label becomes
`production`, production validation becomes active, the provider lookup can no
longer be disabled, and `TEST_MODE=true` becomes a startup blocker instead of
granting bypass behavior. Development and test retain their existing opt-in
test-mode and verification-disabled capabilities.

## Webhook verification

The repository exposes one external webhook endpoint:
`POST /api/v1/payment/webhook`, provider YooKassa.

YooKassa does not define an HMAC signature or timestamp header for this
integration. NURA therefore does not invent one. The implemented verification
is provider-standard:

1. Parse only a JSON object and reject malformed/non-object payloads with a
   generic 400 response.
2. Extract only the provider payment identifier from the untrusted body.
3. Fetch the payment from YooKassa server-to-server.
4. Require matching identifier, `succeeded` status, `paid=true`, provider
   metadata, expected local amount and RUB currency.
5. Map the provider object to an existing local pending payment.
6. Claim the local payment atomically; duplicate notifications return an
   idempotent result.
7. Return a retryable 503 when provider verification is unavailable.

The official guidance recommends checking current object status and optionally
the documented source IP ranges; see
[YooKassa incoming notifications](https://yookassa.ru/developers/using-api/webhooks).
There is no timestamp window because the provider contract supplies no signed
timestamp. Replay resistance comes from current-status lookup and the durable,
atomic local payment claim. Logs use categorical failure messages and do not
write the raw body, authorization headers, credentials, or provider exception
text.

## Controlled P7B rollout

P7B requires a new explicit owner approval because it changes production.

1. Confirm the exact P7A merge SHA, green CI, healthy production baseline, and
   that the production SHA remains intentionally independent until rollout.
2. Confirm the existing Redis volume and append-only persistence. No database
   migration or PostgreSQL backup/restore action is introduced by P7A. Before
   recreating Redis, confirm there is no operationally critical unconsumed
   Celery work whose retry timing would make the maintenance window unsafe.
3. Deploy the exact approved P7A release through the protected coordinated
   production workflow while retaining `APP_ENV=development` and
   `TEST_MODE=true`. This first activates the Redis secret-file transport and
   `.dockerignore` behavior without changing application classification.
4. Verify Redis and all dependent services are healthy. Inspect only command,
   healthcheck, mount destinations, and environment variable names: no Redis
   credential may appear in Docker command/healthcheck metadata or application
   container environment. Confirm unauthenticated Redis access is rejected.
5. Run a non-sensitive production-readiness preflight against the deployed
   code. The only expected blocker from the observed current configuration is
   `production_test_mode_forbidden`; investigate any additional categorical
   blocker before continuing.
6. Change exactly `TEST_MODE=false` and `APP_ENV=production`. Do not rotate
   Redis or YooKassa credentials. Recreate the five application services; Redis
   does not require a second recreation for this classification change.
7. Verify `/health`, all five application services, Celery ping, worker/beat,
   database/Redis health, and zero startup configuration errors.
8. Send or observe a legitimate low-risk YooKassa notification. Confirm the
   server-to-server lookup succeeds and a duplicate notification is
   idempotent. Do not enable the IP allowlist until trusted proxy handling has
   a separately reviewed exact configuration.

Rollback triggers include startup validation failure, Redis authentication or
health failure, inability of any application service to connect to Redis,
webhook verification 5xx outside a provider incident, or entitlement behavior
that differs from the verified payment state. Roll back through the protected
rollback workflow to the exact prior release SHA and restore the two previous
non-secret flags if classification caused the failure. The Redis volume is
preserved. Existing secrets are neither changed nor rotated; rotation requires
a separate owner-approved operation after the secret-file path is stable.
