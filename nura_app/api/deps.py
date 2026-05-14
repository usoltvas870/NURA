import hmac
import hashlib
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_redis
from core.config import settings


async def verify_telegram_auth(auth_data: dict) -> bool:
    token = settings.telegram_bot_token
    check_hash = auth_data.pop("hash", None)
    if not check_hash:
        return False

    data_check_arr = []
    for key in sorted(auth_data.keys()):
        data_check_arr.append(f"{key}={auth_data[key]}")

    secret_key = hashlib.sha256(token.encode()).digest()
    data_check_string = "\n".join(data_check_arr)
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    return computed_hash == check_hash
