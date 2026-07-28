"""Test-only child-process probe for the production Telegram runtime factory.

It deliberately stops before command registration or polling, which are the first
operations that contact Telegram.  The caller must run it with ``APP_ENV=test``.
"""

from __future__ import annotations

import asyncio
import os
import sys

from bot.main import create_runtime


async def main() -> int:
    if os.environ.get("APP_ENV") != "test":
        print("telegram_boot_probe_requires_test_environment", flush=True)
        return 2

    bot, dispatcher = create_runtime()
    try:
        await dispatcher.emit_startup(bot=bot)
        print("TELEGRAM_RUNTIME_READY", flush=True)
        await asyncio.to_thread(sys.stdin.readline)
        await dispatcher.emit_shutdown(bot=bot)
        print("TELEGRAM_RUNTIME_STOPPED", flush=True)
        return 0
    finally:
        await bot.session.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
