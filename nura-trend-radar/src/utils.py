import os
import re
import random
import time
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv
from functools import wraps

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    env_path = PROJECT_ROOT / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        logging.getLogger(__name__).info(f"Loaded .env from {env_path}")


def get_config(key: str, default=None):
    return os.getenv(key, default)


def get_config_int(key: str, default: int) -> int:
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def get_config_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.lower() in ('true', '1', 'yes')


def setup_logging() -> None:
    log_level = get_config('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )


def random_sleep(min_sec: float = 2.0, max_sec: float = 5.0) -> None:
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)


async def async_random_sleep(min_sec: float = 2.0, max_sec: float = 5.0) -> None:
    delay = random.uniform(min_sec, max_sec)
    await asyncio.sleep(delay)


def read_source_file(filename: str) -> list[str]:
    filepath = PROJECT_ROOT / 'config' / filename
    if not filepath.exists():
        logging.getLogger(__name__).warning(f"Source file not found: {filepath}")
        return []
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = []
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                lines.append(line)
        return lines


def extract_video_id(url: str) -> str | None:
    pattern = r'(?:/video/)(\d+)'
    match = re.search(pattern, url)
    return match.group(1) if match else None


def get_cookie_path() -> Path:
    return Path(get_config('COOKIE_PATH', str(PROJECT_ROOT / 'data' / 'tiktok_cookies.json')))


async def retry(max_retries: int = 3, delay: float = 1.0):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for i in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if i < max_retries - 1:
                        wait = delay * (i + 1)
                        logging.getLogger(__name__).warning(
                            f"Retry {i + 1}/{max_retries} for {func.__name__}: {e}"
                            f" (wait {wait:.1f}s)"
                        )
                        await asyncio.sleep(wait)
            raise last_exc
        return wrapper
    return decorator
