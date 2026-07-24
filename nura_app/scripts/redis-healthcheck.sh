#!/bin/sh
set -eu

# This is intentionally liveness-only: an auth-enabled Redis answers NOAUTH.
# Authentication is checked separately by core.redis_auth_probe.
redis-cli --no-auth-warning ping 2>&1 | grep -Fx "NOAUTH Authentication required."
