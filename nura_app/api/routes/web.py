import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.deps import limiter
from api.dependencies import (
    clear_session_cookie,
    get_current_web_user,
    get_optional_web_user,
    set_session_cookie,
)
from core.arcana_data import ARCANA
from core.config import settings
from core.database import get_async_sessionmaker, get_redis
from core.models import PromoCode, ReportType, User
from core.repositories.payment import PaymentRepository
from core.repositories.report import ReportRepository
from core.repositories.user import UserRepository

from core.services.ai import AIService
from core.services.matrix import MatrixService
from core.services.payment import PaymentService
from core.services.report import ReportService


class ReportItem(BaseModel):
    token: str
    report_type: str
    created_at: str
    url: str


class UserProfileResponse(BaseModel):
    name: str
    birth_date: str
    archetype: str | None
    archetype_number: int | None
    has_matrix: bool
    has_tarot: bool
    report_token: str | None
    subscription_status: str | None
    subscription_until: str | None
    tarot_until: str | None
    has_pwa_push: bool
    telegram_linked: bool
    reports: list[ReportItem]
    ref_link: str | None


async def _validate_promo_code(session_factory, code: str, price_kopecks: int) -> tuple[int, PromoCode]:
    async with session_factory() as session:
        result = await session.execute(
            select(PromoCode).where(PromoCode.code == code.strip().upper())
        )
        promo = result.scalar_one_or_none()
        if not promo or not promo.is_active:
            raise HTTPException(status_code=400, detail="Промокод недействителен")
        if promo.expires_at and promo.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="Промокод истёк")
        if promo.max_uses is not None and promo.used_count >= promo.max_uses:
            raise HTTPException(status_code=400, detail="Промокод исчерпан")
        discounted = int(price_kopecks * (100 - promo.discount_percent) / 100)
        promo.used_count += 1
        await session.commit()
        return discounted, promo


router = APIRouter(prefix="/api/v1/web")


class MiniAnalysisRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    birth_date: str = Field(..., pattern=r"^\d{2}\.\d{2}\.\d{4}$")
    pd_consent: bool = Field(..., description="Согласие на обработку ПД")


class MiniAnalysisResponse(BaseModel):
    main_archetype: str
    core_strength: str
    emotional_conflict: str
    relationship_pattern: str
    financial_block: str


class CreatePaymentRequest(BaseModel):
    email: str | None = None
    promo_code: str | None = None


class CreatePaymentResponse(BaseModel):
    payment_url: str


class AuthStartResponse(BaseModel):
    token: str
    tg_url: str


class AuthCheckResponse(BaseModel):
    status: str


@router.post("/mini-analysis", response_model=MiniAnalysisResponse)
@limiter.limit("3/hour")
async def mini_analysis(
    request: Request,
    body: MiniAnalysisRequest,
    response: Response,
    web_user: User | None = Depends(get_optional_web_user),
):
    if not body.pd_consent:
        raise HTTPException(status_code=400, detail="Необходимо согласие на обработку персональных данных")

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)

    if web_user is not None:
        user = web_user
        session_id = user.web_session_id
        await user_repo.update_web_user(user.id, name=body.name, birth_date=body.birth_date)
    else:
        existing = await user_repo.get_by_name_and_birth_date(body.name, body.birth_date)
        if existing is not None:
            user = existing
            session_id = uuid.uuid4().hex
            await user_repo.update_web_session(user.id, session_id)
        else:
            session_id = uuid.uuid4().hex
            try:
                user = await user_repo.create_web_user(
                    name=body.name,
                    birth_date=body.birth_date,
                    web_session_id=session_id,
                )
            except IntegrityError:
                existing = await user_repo.get_by_name_and_birth_date(body.name, body.birth_date)
                if existing is not None:
                    user = existing
                    session_id = uuid.uuid4().hex
                    await user_repo.update_web_session(user.id, session_id)
                else:
                    raise HTTPException(status_code=409, detail="Пользователь уже существует")

    await user_repo.set_pd_consent(user.id)

    try:
        matrix_data = MatrixService.calculate(body.birth_date)
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный формат даты")

    center_num = matrix_data.center
    center_name = ARCANA.get(center_num, {}).get("name", "Неизвестный")
    await user_repo.update_archetype(user.id, center_name, center_num)

    report_repo = ReportRepository(session_factory)
    await report_repo.create(
        user_id=user.id,
        report_type=ReportType.MINI,
        token=ReportService.generate_token(),
        matrix_data=matrix_data if isinstance(matrix_data, dict) else matrix_data.model_dump(),
    )

    try:
        analysis = await AIService.generate_mini_analysis(
            birth_date=body.birth_date,
            matrix_data=matrix_data,
        )
    except Exception:
        raise HTTPException(status_code=503, detail="AI сервис временно недоступен")

    set_session_cookie(response, session_id)

    return MiniAnalysisResponse(**analysis)


@router.post("/create-payment", response_model=CreatePaymentResponse)
@limiter.limit("5/minute")
async def create_payment(
    request: Request,
    body: CreatePaymentRequest,
    user: User = Depends(get_current_web_user),
):
    session_factory = get_async_sessionmaker()

    if body.email:
        async with session_factory() as session:
            db_user = await session.get(type(user), user.id)
            if db_user:
                db_user.email = body.email
                await session.commit()

    report_token = ReportService.generate_token()
    amount = 89000
    if body.promo_code:
        amount, _ = await _validate_promo_code(session_factory, body.promo_code, amount)

    try:
        payment = await PaymentService.create_web_matrix_payment(
            user_id=user.id,
            report_token=report_token,
        )
    except Exception:
        raise HTTPException(status_code=503, detail="Платёжный сервис недоступен")

    payment_repo = PaymentRepository(session_factory)
    await payment_repo.create(
        user_id=user.id,
        amount=amount // 100,
        yookassa_id=payment["id"],
        payment_type="web_matrix",
    )

    return CreatePaymentResponse(payment_url=payment["payment_url"])


class GenerateLinkTokenResponse(BaseModel):
    token: str
    tg_url: str


class CheckLinkTokenResponse(BaseModel):
    user_id: str


@router.post("/generate-link-token", response_model=GenerateLinkTokenResponse)
@limiter.limit("10/minute")
async def generate_link_token(
    request: Request,
    user: User = Depends(get_current_web_user),
):
    token = uuid.uuid4().hex
    redis = get_redis()
    await redis.setex(f"link_token:{token}", 900, str(user.id))

    bot_username = settings.bot_username
    return GenerateLinkTokenResponse(
        token=token,
        tg_url=f"https://t.me/{bot_username}?start=link_{token}",
    )


@router.get("/check-link-token", response_model=CheckLinkTokenResponse)
@limiter.limit("30/minute")
async def check_link_token(
    request: Request,
    x_link_token: str = Header(..., alias="X-Link-Token"),
):
    redis = get_redis()
    key = f"link_token:{x_link_token}"
    user_id = await redis.execute_command("GETDEL", key)
    if not user_id:
        raise HTTPException(status_code=404, detail="Токен не найден или истёк")
    if isinstance(user_id, bytes):
        user_id = user_id.decode()
    return CheckLinkTokenResponse(user_id=user_id)


@router.get("/me", response_model=UserProfileResponse)
@limiter.limit("60/minute")
async def get_user_profile(
    request: Request,
    user: User = Depends(get_current_web_user),
):
    session_factory = get_async_sessionmaker()
    report_repo = ReportRepository(session_factory)

    raw_reports = await report_repo.get_by_user_id(user.id)
    reports = []
    report_token = None
    for r in sorted(raw_reports, key=lambda x: x.created_at, reverse=True):
        if r.report_type == ReportType.FULL.value and report_token is None:
            report_token = r.token
        reports.append(ReportItem(
            token=r.token,
            report_type=r.report_type,
            created_at=r.created_at.strftime("%d.%m.%Y"),
            url=f"/report/{r.token}",
        ))

    ref_link = None
    if user.telegram_id:
        ref_link = f"https://t.me/{settings.bot_username}?start=ref_{user.telegram_id}"

    sub_until = None
    if user.subscription_until:
        sub_until = user.subscription_until.strftime("%d.%m.%Y")
    tarot_until = None
    if user.tarot_subscription_until:
        tarot_until = user.tarot_subscription_until.strftime("%d.%m.%Y")

    return UserProfileResponse(
        name=user.first_name or user.name or "Пользователь",
        birth_date=user.birth_date or "",
        archetype=user.main_archetype,
        archetype_number=user.main_archetype_number,
        has_matrix=bool(user.has_matrix),
        has_tarot=bool(user.tarot_subscription),
        report_token=report_token,
        subscription_status=user.subscription_status,
        subscription_until=sub_until,
        tarot_until=tarot_until,
        has_pwa_push=bool(user.has_pwa_push),
        telegram_linked=bool(user.telegram_id),
        reports=reports,
        ref_link=ref_link,
    )


class SubscribeRequest(BaseModel):
    promo_code: str | None = None


class SubscribeResponse(BaseModel):
    payment_url: str


@router.post("/subscribe", response_model=SubscribeResponse)
@limiter.limit("5/minute")
async def subscribe_tarot(
    request: Request,
    body: SubscribeRequest,
    user: User = Depends(get_current_web_user),
):
    session_factory = get_async_sessionmaker()

    amount = 39000
    if body.promo_code:
        amount, _ = await _validate_promo_code(session_factory, body.promo_code, amount)

    try:
        payment = await PaymentService.create_web_tarot_payment(user_id=user.id)
    except Exception:
        raise HTTPException(status_code=503, detail="Платёжный сервис недоступен")

    payment_repo = PaymentRepository(session_factory)
    await payment_repo.create(
        user_id=user.id,
        amount=amount // 100,
        yookassa_id=payment["id"],
        payment_type="web_tarot",
    )

    return SubscribeResponse(payment_url=payment["payment_url"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    messages_left: int


_WEB_CHAT_FREE_LIMIT = 5


@router.post("/chat", response_model=ChatResponse)
@limiter.limit("20/minute")
async def web_chat(
    request: Request,
    body: ChatRequest,
    user: User = Depends(get_current_web_user),
):
    session_factory = get_async_sessionmaker()
    report_repo = ReportRepository(session_factory)

    has_unlimited = (
        bool(user.tarot_subscription)
        or user.subscription_status == "premium"
        or user.has_matrix
    )
    redis = get_redis()
    counter_key = f"chat_count:{user.id}"

    if not has_unlimited:
        raw = await redis.get(counter_key)
        used = int(raw) if raw else 0
        if used >= _WEB_CHAT_FREE_LIMIT:
            raise HTTPException(
                status_code=402,
                detail=f"Лимит {_WEB_CHAT_FREE_LIMIT} бесплатных сообщений исчерпан",
            )

    matrix_data: dict = {}
    user_name = user.first_name or user.name or "пользователь"
    try:
        reports = await report_repo.get_by_user_id(user.id)
        for r in sorted(reports, key=lambda x: x.created_at, reverse=True):
            if r.matrix_data and r.report_type in ("mini", "full"):
                matrix_data = r.matrix_data
                break
    except Exception:
        pass

    try:
        reply = await AIService.chat_response(
            user_message=body.message,
            chat_history=body.history[-10:],
            matrix_data=matrix_data,
            user_name=user_name,
        )
    except Exception:
        raise HTTPException(status_code=503, detail="AI временно недоступен")

    messages_left = -1
    if not has_unlimited:
        new_count = await redis.incr(counter_key)
        if new_count == 1:
            await redis.expire(counter_key, 86400)
        messages_left = max(0, _WEB_CHAT_FREE_LIMIT - new_count)

    return ChatResponse(reply=reply, messages_left=messages_left)


class TestSubscribeResponse(BaseModel):
    ok: bool
    subscription_until: str


class NotificationPrefRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    enabled: bool


class NotificationPrefsResponse(BaseModel):
    prefs: dict[str, bool]


_ALLOWED_NOTIF_KEYS = {"daily_card", "weekly_spread", "practices", "news"}


@router.patch("/notifications", response_model=NotificationPrefsResponse)
@limiter.limit("30/minute")
async def update_notification_pref(
    request: Request,
    body: NotificationPrefRequest,
    user: User = Depends(get_current_web_user),
):
    if body.key not in _ALLOWED_NOTIF_KEYS:
        raise HTTPException(status_code=400, detail="Неизвестная настройка уведомлений")
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    await user_repo.update_notification_pref(user.id, body.key, body.enabled)
    prefs = await user_repo.get_notification_prefs(user.id)
    return NotificationPrefsResponse(prefs=prefs)


@router.get("/notifications", response_model=NotificationPrefsResponse)
@limiter.limit("60/minute")
async def get_notification_prefs(
    request: Request,
    user: User = Depends(get_current_web_user),
):
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    prefs = await user_repo.get_notification_prefs(user.id)
    return NotificationPrefsResponse(prefs=prefs)


@router.post("/test-subscribe", response_model=TestSubscribeResponse)
async def test_subscribe(
    request: Request,
    user: User = Depends(get_current_web_user),
):
    if not settings.test_mode:
        raise HTTPException(status_code=403, detail="Доступно только в тестовом режиме")

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)

    until_date = datetime.now(timezone.utc) + timedelta(days=30)
    await user_repo.update_subscription(user.id, "premium", until_date)
    await user_repo.update_tarot_subscription(user.id, True, until_date)

    return TestSubscribeResponse(
        ok=True,
        subscription_until=until_date.strftime("%d.%m.%Y"),
    )


@router.post("/logout")
async def logout(response: Response):
    clear_session_cookie(response)
    return {"ok": True}


@router.delete("/unlink-telegram")
@limiter.limit("10/minute")
async def unlink_telegram(
    request: Request,
    user: User = Depends(get_current_web_user),
):
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)

    if not user.telegram_id:
        raise HTTPException(status_code=400, detail="Telegram не подключён")

    has_other = await user_repo.has_other_auth_method(user.id)
    if not has_other:
        raise HTTPException(
            status_code=400,
            detail="Сначала привяжите email или VK, чтобы не потерять доступ к аккаунту",
        )

    await user_repo.unlink_telegram(user.id)
    return {"ok": True}


@router.get("/session-check")
async def session_check(user: User = Depends(get_current_web_user)):
    return {"authenticated": True}


@router.post("/auth/start", response_model=AuthStartResponse)
@limiter.limit("10/hour")
async def auth_start(
    request: Request,
    user: User | None = Depends(get_optional_web_user),
):
    token = str(uuid.uuid4())
    redis = get_redis()
    session_value = user.web_session_id if user else "pending"
    await redis.setex(f"auth_token:{token}", 300, session_value)
    return AuthStartResponse(
        token=token,
        tg_url=f"https://t.me/{settings.bot_username}?start=tgauth_{token}",
    )


@router.get("/auth/check", response_model=AuthCheckResponse)
@limiter.limit("60/minute")
async def auth_check(request: Request, response: Response, token: str):
    redis = get_redis()
    value = await redis.get(f"auth_token:{token}")
    if value is None:
        return AuthCheckResponse(status="expired")
    if isinstance(value, bytes):
        value = value.decode()
    if value == "pending":
        return AuthCheckResponse(status="pending")
    await redis.delete(f"auth_token:{token}")
    set_session_cookie(response, value)
    return AuthCheckResponse(status="ok")


@router.delete("/account")
@limiter.limit("3/hour")
async def delete_account(
    request: Request,
    response: Response,
    user: User = Depends(get_current_web_user),
):
    session_factory = get_async_sessionmaker()
    report_repo = ReportRepository(session_factory)
    payment_repo = PaymentRepository(session_factory)
    user_repo = UserRepository(session_factory)

    await report_repo.delete_by_user_id(user.id)
    await payment_repo.delete_by_user_id(user.id)
    await user_repo.delete(user.id)

    clear_session_cookie(response)
    return {"ok": True}
