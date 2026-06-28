from datetime import datetime, timezone

from fastapi import Cookie, HTTPException, Response

from core.config import settings
from core.database import get_async_sessionmaker
from core.models import User
from core.repositories.user import UserRepository

SESSION_COOKIE_NAME = "nura_session_id"


def set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=settings.web_session_ttl_seconds,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
    )


async def get_current_web_user(
    response: Response,
    nura_session_id: str | None = Cookie(None, alias=SESSION_COOKIE_NAME),
) -> User:
    if not nura_session_id:
        raise HTTPException(status_code=401, detail="Не авторизован")
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_web_session_id(nura_session_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Сессия не найдена")
    now = datetime.now(timezone.utc)
    if user.web_session_expires_at and user.web_session_expires_at < now:
        raise HTTPException(status_code=401, detail="Сессия истекла")
    await user_repo.renew_session_expiry(user.id)
    set_session_cookie(response, nura_session_id)
    return user


async def get_optional_web_user(
    nura_session_id: str | None = Cookie(None, alias=SESSION_COOKIE_NAME),
) -> User | None:
    if not nura_session_id:
        return None
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_web_session_id(nura_session_id)
    if user is None:
        return None
    now = datetime.now(timezone.utc)
    if user.web_session_expires_at and user.web_session_expires_at < now:
        return None
    await user_repo.renew_session_expiry(user.id)
    return user