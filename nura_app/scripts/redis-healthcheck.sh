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

if [ ! -s "$secret_file" ]; then
    exit 1
fi

# --askpass reads stdin; the credential is never inherited through environment
# or command arguments by the healthcheck process.
cat "$secret_file" | redis-cli --no-auth-warning --askpass ping
