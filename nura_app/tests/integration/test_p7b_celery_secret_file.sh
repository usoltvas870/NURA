#!/usr/bin/env bash
set -Eeuo pipefail

MSYS_NO_PATHCONV=1
export MSYS_NO_PATHCONV

compose_file="tests/integration/p7b-celery-secret-file.yml"
project="nura-p7b-celery-${GITHUB_RUN_ID:-local}-$$"
worker="${project}-celery-worker-1"
beat="${project}-celery-beat-1"
redis="${project}-redis-1"
attempt_file="$(mktemp)"
error_file="$(mktemp)"
wrong_secret="/tmp/nura-wrong-redis-password"
unreadable_secret="/tmp/nura-unreadable-redis-password"

cleanup() {
    docker compose --project-name "$project" --file "$compose_file" \
        down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -f "$attempt_file" "$error_file"
    unset REDIS_PASSWORD
}
trap cleanup EXIT HUP INT TERM
trap 'printf "p7b_celery_integration failure_line=%s secrets=redacted\n" "$LINENO" >&2' ERR

TARGET_SHA="${TARGET_SHA:-$(git rev-parse HEAD)}"
export TARGET_SHA
REDIS_PASSWORD="$(
    python -c 'import secrets; print(secrets.token_urlsafe(48), end="")'
)"
export REDIS_PASSWORD

start_ms="$(
    python -c 'import time; print(time.time_ns() // 1_000_000)'
)"
docker compose --project-name "$project" --file "$compose_file" \
    up --build --detach --wait --wait-timeout 180 redis celery-worker celery-beat
redis_ready_ms="$(
    python -c 'import time; print(time.time_ns() // 1_000_000)'
)"
worker_connected_ms=""
connection_attempt=1
while test "$connection_attempt" -le 30; do
    if docker logs "$worker" 2>&1 | grep -Fq 'Connected to redis'; then
        worker_connected_ms="$(
            python -c 'import time; print(time.time_ns() // 1_000_000)'
        )"
        break
    fi
    connection_attempt=$((connection_attempt + 1))
    sleep 1
done
test -n "$worker_connected_ms"

redis_state="$(docker inspect --format '{{.State.Health.Status}}' "$redis")"
test "$redis_state" = "healthy"
test "$(docker inspect --format '{{.State.Running}}' "$worker")" = "true"
test "$(docker inspect --format '{{.State.Running}}' "$beat")" = "true"
test "$(docker inspect --format '{{.RestartCount}}' "$worker")" = "0"
test "$(docker inspect --format '{{.RestartCount}}' "$beat")" = "0"
test "$(
    docker inspect --format \
        '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$worker"
)" = "$TARGET_SHA"

redis_secret_digest="$(
    docker exec "$redis" sha256sum /run/secrets/redis_password | awk '{print $1}'
)"
worker_secret_digest="$(
    docker exec "$worker" sha256sum /run/secrets/redis_password | awk '{print $1}'
)"
test "$redis_secret_digest" = "$worker_secret_digest"
test "$(
    docker exec "$worker" stat -c '%F|%U:%G|%a' /run/secrets/redis_password
)" = "regular file|root:root|444"

docker inspect "$redis" "$worker" "$beat" |
    python -c \
        'import os,sys; assert os.environ["REDIS_PASSWORD"] not in sys.stdin.read()'

docker exec -i "$worker" python - <<'PY'
from pathlib import Path
from urllib.parse import urlsplit

from core.config import settings
from core.tasks import celery_app

secret = Path(settings.redis_password_file or "").read_text(encoding="utf-8")
for value in (
    settings.redis_url,
    settings.celery_broker_url,
    settings.celery_result_backend,
    celery_app.conf.broker_url,
    celery_app.conf.result_backend,
):
    parsed = urlsplit(value)
    assert parsed.password == secret
    assert parsed.hostname == "redis"
assert urlsplit(settings.celery_broker_url).path == "/1"
assert urlsplit(settings.celery_result_backend).path == "/2"
PY

attempt=1
first_pong_ms=""
while test "$attempt" -le 6; do
    : >"$attempt_file"
    : >"$error_file"
    if timeout 45 docker exec "$worker" \
        celery -A core.tasks inspect ping --timeout 5 \
        >"$attempt_file" 2>"$error_file"
    then
        if grep -Eiq '^[[:space:]]*pong[[:space:]]*$' "$attempt_file"; then
            first_pong_ms="$(
                python -c 'import time; print(time.time_ns() // 1_000_000)'
            )"
            break
        fi
    fi
    attempt=$((attempt + 1))
    sleep 5
done
test -n "$first_pong_ms"
python -c \
    'import runpy,sys; module=runpy.run_path("../scripts/p7b_rollout.py"); assert module["celery_output_category"](sys.stdin.read(), stderr=False) == "standalone_pong"' \
    <"$attempt_file"

test "$(
    docker exec "$worker" python -c \
        'from core.config import settings; import redis; print(redis.Redis.from_url(settings.celery_broker_url, socket_timeout=3).ping())'
)" = "True"

if docker exec -e REDIS_PASSWORD_FILE=/run/secrets/missing "$worker" \
    python -c 'from core.config import Settings; Settings(_env_file=None)' \
    >"$attempt_file" 2>"$error_file"
then
    exit 1
fi

python -c 'import secrets; print(secrets.token_urlsafe(48), end="")' |
    docker exec -i "$worker" sh -c \
        "umask 077; cat > '$wrong_secret'; chmod 0400 '$wrong_secret'"
if timeout 45 docker exec -e REDIS_PASSWORD_FILE="$wrong_secret" "$worker" \
    celery -A core.tasks inspect ping --timeout 5 \
    >"$attempt_file" 2>"$error_file"
then
    exit 1
fi
grep -Eiq \
    'authentication required|wrongpass|invalid username-password pair|authenticationerror|operationalerror' \
    "$error_file"

failed_attempts=0
while test "$failed_attempts" -lt 6; do
    if timeout 45 docker exec -e REDIS_PASSWORD_FILE="$wrong_secret" "$worker" \
        celery -A core.tasks inspect ping --timeout 5 \
        >"$attempt_file" 2>"$error_file"
    then
        exit 1
    fi
    failed_attempts=$((failed_attempts + 1))
done
test "$failed_attempts" = "6"

docker exec "$worker" sh -c \
    "umask 077; : > '$unreadable_secret'; chmod 000 '$unreadable_secret'"
if docker exec --user 65534:65534 \
    -e REDIS_PASSWORD_FILE="$unreadable_secret" "$worker" \
    python -c 'from core.config import Settings; Settings(_env_file=None)' \
    >"$attempt_file" 2>"$error_file"
then
    exit 1
fi

if timeout 45 docker exec "$worker" \
    celery -A core.missing inspect ping --timeout 5 \
    >"$attempt_file" 2>"$error_file"
then
    exit 1
fi

if docker logs "$worker" 2>&1 |
    grep -Eiq 'authentication required|wrongpass|noauth'
then
    exit 1
fi
if docker logs "$beat" 2>&1 |
    grep -Eiq 'authentication required|wrongpass|noauth'
then
    exit 1
fi
docker logs "$worker" 2>&1 |
    python -c \
        'import os,sys; assert os.environ["REDIS_PASSWORD"] not in sys.stdin.read()'
docker logs "$beat" 2>&1 |
    python -c \
        'import os,sys; assert os.environ["REDIS_PASSWORD"] not in sys.stdin.read()'

printf '%s\n' \
    "p7b_celery_integration status=ok secrets=redacted" \
    "redis_healthy_ms=$((redis_ready_ms - start_ms))" \
    "worker_broker_connected_ms=$((worker_connected_ms - start_ms))" \
    "first_valid_pong_ms=$((first_pong_ms - start_ms))" \
    "pong_attempt=$attempt" \
    "persistent_failure_attempts=$failed_attempts"
