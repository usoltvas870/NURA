"""Authenticated Redis readiness probe for the isolated Telegram pilot."""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from core.config import NURA_TG_REDIS_PASSWORD_FILE, _read_secret_file


async def authenticated_redis_pong() -> bool:
    """Return only whether the fixed-file credential can authenticate Redis."""
    password = _read_secret_file(NURA_TG_REDIS_PASSWORD_FILE, "redis_password")
    client = Redis(host="redis", port=6379, password=password, decode_responses=False)
    try:
        return bool(await client.ping())
    finally:
        await client.aclose()


def main() -> int:
    try:
        return 0 if asyncio.run(authenticated_redis_pong()) else 1
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
