import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from api.dependencies import get_current_web_user, get_optional_web_user, set_session_cookie
from api.deps import limiter
from core.models import User
from core.schemas.auth import (
    EmailAuthRequest,
    EmailAuthResponse,
    GuestProfileCreate,
    GuestProfileFetchResponse,
    GuestProfileResponse,
    MergeGuestRequest,
    MergeGuestResponse,
    VKAuthResponse,
    VKTokenRequest,
)
from core.services.auth import AuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth")


@router.post("/guest", response_model=GuestProfileResponse)
@limiter.limit("10/minute")
async def create_guest_profile(
    request: Request,
    body: GuestProfileCreate,
):
    result = await AuthService().create_guest_profile(
        body.name, body.birth_date, body.quiz_answers
    )
    return GuestProfileResponse(
        guest_token=result["guest_token"],
        expires_at=result["expires_at"],
    )


@router.get("/guest/{guest_token}", response_model=GuestProfileFetchResponse)
@limiter.limit("30/minute")
async def get_guest_profile(
    request: Request,
    guest_token: str,
):
    data = await AuthService().get_guest(guest_token)
    if data is None:
        raise HTTPException(status_code=404, detail="Профиль не найден или истёк")
    return GuestProfileFetchResponse(**data)


@router.post("/email/send", response_model=EmailAuthResponse)
@limiter.limit("3/minute")
async def send_email_auth(
    request: Request,
    body: EmailAuthRequest,
    web_user: User | None = Depends(get_optional_web_user),
):
    result = await AuthService().start_email_auth(
        body.email, body.guest_token, web_user
    )
    return EmailAuthResponse(
        message=result["message"],
        expires_in=result["expires_in"],
    )


@router.get("/email/verify")
@limiter.limit("30/minute")
async def verify_email_auth(
    request: Request,
    response: Response,
    token: str,
    web_user: User | None = Depends(get_optional_web_user),
):
    res = await AuthService().verify_magic_link(token, web_user)
    if res is None:
        return RedirectResponse(url="/?error=token_expired")
    set_session_cookie(response, res["web_session_id"])
    return RedirectResponse(url="/app/")


@router.post("/merge", response_model=MergeGuestResponse)
@limiter.limit("10/minute")
async def apply_guest_data(
    request: Request,
    body: MergeGuestRequest,
    user: User = Depends(get_current_web_user),
):
    ok = await AuthService().apply_guest_data_and_create_report(body.guest_token, user)
    if not ok:
        raise HTTPException(
            status_code=400, detail="Гостевой профиль не найден или уже привязан"
        )
    return MergeGuestResponse(success=True, user_id=str(user.id))


@router.post("/generate-tg-link")
@limiter.limit("10/minute")
async def generate_telegram_link(
    request: Request,
    user: User = Depends(get_current_web_user),
):
    return await AuthService().generate_telegram_link(user)


@router.post("/vk", response_model=VKAuthResponse)
@limiter.limit("10/minute")
async def vk_auth(
    request: Request,
    body: VKTokenRequest,
    response: Response,
    web_user: User | None = Depends(get_optional_web_user),
):
    try:
        result = await AuthService().vk_auth(
            access_token=body.access_token,
            guest_token=body.guest_token,
            current_user=web_user,
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e) or "VK-токен не подтверждён")
    except httpx.HTTPStatusError as e:
        logger.error("VK ID user_info HTTP error: %s", e.response.status_code)
        raise HTTPException(status_code=502, detail="VK-авторизация недоступна. Попробуйте позже.")
    except Exception:
        logger.exception("vk_auth endpoint failed")
        raise HTTPException(status_code=502, detail="Не удалось авторизоваться через VK")
    set_session_cookie(response, result["web_session_id"])
    return VKAuthResponse(success=True, user_id=result["user_id"])