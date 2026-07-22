#!/bin/sh
set -eu

secret_file="${REDIS_PASSWORD_FILE:-/run/secrets/redis_password}"
config_dir="/run/nura-redis"
config_file="${config_dir}/redis.conf"

if [ ! -r "$secret_file" ]; then
    echo "redis credential file is not readable" >&2
    exit 1
fi

raw_bytes=$(wc -c < "$secret_file")
single_line_bytes=$(tr -d '\000\r\n' < "$secret_file" | wc -c)
if [ "$raw_bytes" -ne "$single_line_bytes" ]; then
    echo "redis credential must not contain control terminators" >&2
    exit 1
fi

password=$(cat "$secret_file")
if [ -z "$password" ]; then
    echo "redis credential file is empty" >&2
    exit 1
fi

escaped_password=$(printf '%s' "$password" | sed 's/\\/\\\\/g; s/"/\\"/g')
umask 077
mkdir -p "$config_dir"
{
    printf '%s\n' 'appendonly yes'
    printf 'requirepass "%s"\n' "$escaped_password"
} > "$config_file"

unset password escaped_password
exec redis-server "$config_file"
