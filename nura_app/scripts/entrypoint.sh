#!/bin/sh
set -e

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    echo "Running alembic upgrade head..."
    alembic upgrade head
fi

exec "$@"
