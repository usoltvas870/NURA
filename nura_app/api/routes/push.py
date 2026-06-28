import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.deps import limiter
from api.dependencies import get_optional_web_user
from core.config import settings
from core.database import get_async_sessionmaker
from core.models import User
from core.repositories.user import UserRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/push")


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict
    telegram_id: int | None = None


class PushUnsubscribe(BaseModel):
    endpoint: str
    telegram_id: int | None = None


@router.get("/vapid-public-key")
@limiter.limit("10/minute")
async def get_vapid_public_key(request: Request):
    if not settings.vapid_public_key:
        raise HTTPException(status_code=503, detail="Push не сконфигурирован")
    return {"public_key": settings.vapid_public_key}


@router.post("/subscribe")
@limiter.limit("5/minute")
async def subscribe(
    request: Request,
    body: PushSubscription,
    web_user: User | None = Depends(get_optional_web_user),
):
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)

    if web_user is not None:
        user = web_user
    elif body.telegram_id:
        user = await user_repo.get_by_telegram_id(body.telegram_id)
    else:
        user = None

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
async def unsubscribe(
    request: Request,
    body: PushUnsubscribe,
    web_user: User | None = Depends(get_optional_web_user),
):
    if web_user is None and not body.telegram_id:
        raise HTTPException(status_code=401, detail="Не авторизован")

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)

    if web_user is not None:
        user = web_user
    else:
        user = await user_repo.get_by_telegram_id(body.telegram_id)

    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user.push_endpoint != body.endpoint:
        raise HTTPException(status_code=403, detail="Endpoint не принадлежит пользователю")

    await user_repo.clear_push_subscription_by_endpoint(body.endpoint)
    logger.info("Push unsubscribed: user_id=%s", user.id)
    return {"ok": True}
