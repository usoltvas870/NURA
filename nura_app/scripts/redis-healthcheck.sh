#!/bin/sh
set -eu

secret_file="${REDIS_PASSWORD_FILE:-/run/secrets/redis_password}"
if [ ! -r "$secret_file" ]; then
    exit 1
fi

raw_bytes=$(wc -c < "$secret_file")
single_line_bytes=$(tr -d '\000\r\n' < "$secret_file" | wc -c)
if [ "$raw_bytes" -ne "$single_line_bytes" ]; then
    exit 1
fi

REDISCLI_AUTH=$(cat "$secret_file")
if [ -z "$REDISCLI_AUTH" ]; then
    exit 1
fi
export REDISCLI_AUTH
exec redis-cli --no-auth-warning ping
