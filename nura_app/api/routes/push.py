import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.deps import limiter
from core.config import settings
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/push")


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict
    session_id: str | None = None
    telegram_id: int | None = None


class PushUnsubscribe(BaseModel):
    endpoint: str
    session_id: str | None = None
    telegram_id: int | None = None


@router.get("/vapid-public-key")
@limiter.limit("10/minute")
async def get_vapid_public_key(request: Request):
    if not settings.vapid_public_key:
        raise HTTPException(status_code=503, detail="Push не сконфигурирован")
    return {"public_key": settings.vapid_public_key}


@router.post("/subscribe")
@limiter.limit("5/minute")
async def subscribe(request: Request, body: PushSubscription):
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)

    user = None
    if body.session_id:
        user = await user_repo.get_by_web_session_id(body.session_id)
    elif body.telegram_id:
        user = await user_repo.get_by_telegram_id(body.telegram_id)

    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await user_repo.update_push_subscription(
        user_id=user.id,
        endpoint=body.endpoint,
        p256dh=body.keys.get("p256dh"),
        auth=body.keys.get("auth"),
        has_pwa_push=True,
    )
    logger.info("Push subscribed: user_id=%s", user.id)
    return {"ok": True}


@router.post("/unsubscribe")
@limiter.limit("5/minute")
async def unsubscribe(request: Request, body: PushUnsubscribe):
    if not body.session_id and not body.telegram_id:
        raise HTTPException(status_code=401, detail="Требуется session_id или telegram_id")

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)

    user = None
    if body.session_id:
        user = await user_repo.get_by_web_session_id(body.session_id)
    elif body.telegram_id:
        user = await user_repo.get_by_telegram_id(body.telegram_id)

    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user.push_endpoint != body.endpoint:
        raise HTTPException(status_code=403, detail="Endpoint не принадлежит пользователю")

    await user_repo.clear_push_subscription_by_endpoint(body.endpoint)
    logger.info("Push unsubscribed: user_id=%s", user.id)
    return {"ok": True}
