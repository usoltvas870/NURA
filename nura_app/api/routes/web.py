import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from api.deps import limiter
from api.dependencies import (
    clear_session_cookie,
    get_current_web_user,
    get_optional_web_user,
)
from core.config import settings
from core.database import get_async_sessionmaker, get_redis
from core.models import ReportType, User
from core.repositories.payment import PaymentRepository
from core.repositories.promo_reservation import PromoReservationRepository
from core.repositories.report import ReportRepository
from core.repositories.user import UserRepository
from core.repositories.guest import GuestProfileRepository
from core.repositories.mini_report_generation import MiniReportGenerationRepository

from core.services.mini_report_application import (
    GuestMiniReportSubject,
    MiniReportApplicationService,
    MiniReportRequest,
    MiniReportResultKind,
    UserMiniReportSubject,
)
from core.services.mini_report_generation import MiniReportGenerationService
from core.services.payment import PaymentService, PromoCheckoutError
from core.services.report_lifecycle import ReportLifecycleCoordinator
from core.services.account_deletion import AccountDeletionService

from core.services.chat_application import ChatApplicationService, ChatResultKind
from core.services.chat_history import finalize_chat_history_once
from core.services.chat_quota import ChatChannel, ChatQuotaService
from core.services.auth import (
    TelegramConfirmationInvalidError,
    TelegramConfirmationNotFoundError,
    TelegramLinkConfirmationService,
)
from core.schemas.chat import ChatQuotaState, ChatRequest, ChatResponse

logger = logging.getLogger(__name__)


class ReportItem(BaseModel):
    token: str
    report_type: str
    created_at: str
    url: str


class UserProfileResponse(BaseModel):
    user_id: str
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


_PROMO_ERROR_DETAILS = {
    "invalid": "Промокод недействителен",
    "expired": "Промокод истёк",
    "exhausted": "Промокод исчерпан",
}


router = APIRouter(prefix="/api/v1/web")


def _parse_idempotency_key(request: Request) -> str:
    headers = getattr(request, "headers", None)
    values: list[object]
    if headers is None:
        values = []
    elif hasattr(headers, "getlist"):
        values = list(headers.getlist("Idempotency-Key"))
    elif isinstance(headers, dict):
        values = [
            value
            for name, value in headers.items()
            if name.lower() == "idempotency-key"
        ]
    else:
        values = []
    if len(values) != 1 or not isinstance(values[0], str):
        raise HTTPException(status_code=422, detail="invalid_idempotency_key")
    raw_key = values[0]
    try:
        parsed = uuid.UUID(raw_key)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="invalid_idempotency_key") from None
    if raw_key != str(parsed) or parsed.version != 4:
        raise HTTPException(status_code=422, detail="invalid_idempotency_key")
    return raw_key


def _checkout_keys(user_id: uuid.UUID, payment_type: str, raw_key: str) -> tuple[str, str]:
    scoped_key = hashlib.sha256(
        f"nura.web-checkout.v1|{user_id}|{payment_type}|standard|{raw_key}".encode()
    ).hexdigest()
    report_token = hashlib.sha256(
        f"nura.web-report.v1|{scoped_key}".encode()
    ).hexdigest()
    return scoped_key, report_token


def _provider_key(scoped_key: str, checkout_amount) -> str:
    promo_identity = checkout_amount.promo_code_id or "none"
    return hashlib.sha256(
        f"nura.web-provider.v1|{scoped_key}|{promo_identity}|"
        f"{checkout_amount.final_amount_kopecks}|{checkout_amount.currency}".encode()
    ).hexdigest()


def _provider_checkout_url(payment: dict) -> str:
    provider_id = payment.get("id")
    payment_url = payment.get("payment_url")
    if (
        not isinstance(provider_id, str)
        or not provider_id
        or not isinstance(payment_url, str)
        or not payment_url.startswith(("https://", "http://"))
    ):
        raise ValueError("invalid_provider_checkout")
    return payment_url


async def _complete_web_checkout(
    *,
    session_factory,
    user: User,
    checkout_amount,
    scoped_key: str,
    provider_key: str,
    report_token: str | None,
) -> str:
    if checkout_amount.product == "web_matrix":
        async with session_factory() as session:
            coordinator = ReportLifecycleCoordinator(session)
            reservation, _ = await coordinator.create_or_get_matrix_placeholder(
                user_id=user.id,
                idempotency_key=scoped_key,
                report_token=report_token or "",
                promo_code_id=checkout_amount.promo_code_id,
                final_amount_kopecks=checkout_amount.final_amount_kopecks,
                currency=checkout_amount.currency,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
            await session.commit()

        provider_payment = await PaymentService.create_web_matrix_payment(
            user_id=user.id,
            report_token=report_token or "",
            checkout_amount=checkout_amount,
            idempotence_key=provider_key,
        )
        payment_url = _provider_checkout_url(provider_payment)
        provider_payment_id = provider_payment["id"]
        async with session_factory() as session:
            coordinator = ReportLifecycleCoordinator(session)
            await coordinator.attach_matrix_provider_intent(
                reservation_id=reservation.id,
                provider_payment_id=provider_payment_id,
                user_id=user.id,
                amount_kopecks=checkout_amount.final_amount_kopecks,
                promo_code_id=checkout_amount.promo_code_id,
            )
            await session.commit()
        return payment_url

    reservation = None
    if checkout_amount.promo_code_id is not None:
        reservation = await PromoReservationRepository(session_factory).create_or_get(
            promo_code_id=checkout_amount.promo_code_id,
            user_id=user.id,
            payment_type=checkout_amount.product,
            final_amount_kopecks=checkout_amount.final_amount_kopecks,
            currency=checkout_amount.currency,
            idempotency_key=scoped_key,
            report_token=report_token,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

    payment = await PaymentService.create_web_tarot_payment(
            user_id=user.id,
            checkout_amount=checkout_amount,
            idempotence_key=provider_key,
    )
    payment_url = _provider_checkout_url(payment)

    if reservation is not None:
        if reservation.provider_payment_id is None:
            await PromoReservationRepository(session_factory).attach_provider_payment(
                reservation.id, payment["id"]
            )
        elif reservation.provider_payment_id != payment["id"]:
            raise ValueError("reservation_attachment_conflict")
    local_payment = await PaymentRepository(session_factory).create_or_get_by_yookassa_id(
        user_id=user.id,
        amount=checkout_amount.final_amount_kopecks // 100,
        amount_kopecks=checkout_amount.final_amount_kopecks,
        yookassa_id=payment["id"],
        payment_type=checkout_amount.product,
        promo_code_id=checkout_amount.promo_code_id,
    )
    if reservation is not None:
        if reservation.payment_id is None:
            await PromoReservationRepository(session_factory).attach_local_payment(
                reservation.id, local_payment.id
            )
        elif reservation.payment_id != local_payment.id:
            raise ValueError("reservation_attachment_conflict")
    return payment_url


class MiniAnalysisRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    birth_date: str = Field(..., pattern=r"^\d{2}\.\d{2}\.\d{4}$")
    pd_consent: bool = Field(..., description="Согласие на обработку ПД")
    guest_token: str | None = None


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
    guest_repo = GuestProfileRepository(session_factory)
    if web_user is not None:
        owner = UserMiniReportSubject(web_user.id)
    elif body.guest_token:
        guest = await guest_repo.get_by_token(body.guest_token)
        if guest is None:
            raise HTTPException(status_code=400, detail="Гостевой профиль не найден")
        owner = GuestMiniReportSubject(guest.id)
    else:
        raise HTTPException(status_code=400, detail="Не найден гостевой профиль")

    service = MiniReportApplicationService(
        MiniReportGenerationService(MiniReportGenerationRepository(session_factory)),
        ReportRepository(session_factory),
        guest_repo,
    )
    result = await service.generate(
        MiniReportRequest(owner=owner, name=body.name, birth_date=body.birth_date)
    )
    if result.kind == MiniReportResultKind.INVALID_INPUT:
        raise HTTPException(status_code=400, detail="Неверные данные")
    if result.kind == MiniReportResultKind.IN_PROGRESS:
        raise HTTPException(status_code=409, detail="Идёт генерация")
    if result.kind in {MiniReportResultKind.FAILED_RETRYABLE, MiniReportResultKind.FAILED_NON_RETRYABLE}:
        raise HTTPException(status_code=503, detail="AI сервис временно недоступен")
    return MiniAnalysisResponse(**(result.content or {}))


@router.post("/create-payment", response_model=CreatePaymentResponse)
@limiter.limit("5/minute")
async def create_payment(
    request: Request,
    body: CreatePaymentRequest,
    user: User = Depends(get_current_web_user),
):
    session_factory = get_async_sessionmaker()
    raw_key = _parse_idempotency_key(request)
    scoped_key, report_token = _checkout_keys(
        user.id, "web_matrix", raw_key
    )
    if body.email:
        async with session_factory() as session:
            db_user = await session.get(type(user), user.id)
            if db_user:
                db_user.email = body.email
                await session.commit()

    try:
        checkout_amount = await PaymentService.resolve_web_checkout_amount(
            session_factory,
            product="web_matrix",
            promo_code=body.promo_code,
        )
    except PromoCheckoutError as error:
        raise HTTPException(
            status_code=400,
            detail=_PROMO_ERROR_DETAILS[error.reason],
        ) from None
    provider_key = _provider_key(scoped_key, checkout_amount)

    try:
        payment_url = await _complete_web_checkout(
            session_factory=session_factory,
            user=user,
            checkout_amount=checkout_amount,
            scoped_key=scoped_key,
            provider_key=provider_key,
            report_token=report_token,
        )
    except ValueError as error:
        if str(error) == "promo_capacity_exhausted":
            raise HTTPException(status_code=400, detail=_PROMO_ERROR_DETAILS["exhausted"]) from None
        if str(error) == "idempotency_key_conflict":
            raise HTTPException(status_code=409, detail="idempotency_key_conflict") from None
        if str(error) in {"invalid_promo_reservation", "invalid_reservation_transition", "reservation_attachment_conflict", "payment_attachment_conflict"}:
            raise HTTPException(status_code=409, detail="checkout_conflict") from None
        raise HTTPException(status_code=503, detail="checkout_unavailable") from None
    except Exception:
        raise HTTPException(status_code=503, detail="Платёжный сервис недоступен") from None

    return CreatePaymentResponse(payment_url=payment_url)


class GenerateLinkTokenResponse(BaseModel):
    token: str
    tg_url: str


class TelegramLinkStatusResponse(BaseModel):
    status: Literal["idle", "pending_confirmation", "linked"]
    display_label: str | None = None
    expires_in: int | None = None
    attempts_remaining: int | None = None


class ConfirmTelegramLinkRequest(BaseModel):
    code: str = Field(pattern=r"^[0-9]{6}$")


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


async def _consume_link_token(
    x_link_token: str,
) -> str:
    redis = get_redis()
    key = f"link_token:{x_link_token}"
    user_id = await redis.execute_command("GETDEL", key)
    if not user_id:
        raise HTTPException(status_code=404, detail="Токен не найден или истёк")
    if isinstance(user_id, bytes):
        user_id = user_id.decode()
    return user_id


@router.get("/telegram-link-status", response_model=TelegramLinkStatusResponse)
async def telegram_link_status(user: User = Depends(get_current_web_user)):
    if user.telegram_id is not None:
        return TelegramLinkStatusResponse(status="linked")
    return TelegramLinkStatusResponse(**(await TelegramLinkConfirmationService().get_status(user.id)))


@router.post("/confirm-telegram-link")
@limiter.limit("10/minute")
async def confirm_telegram_link(
    request: Request,
    body: ConfirmTelegramLinkRequest,
    user: User = Depends(get_current_web_user),
):
    confirmation_service = TelegramLinkConfirmationService()
    try:
        telegram_id = await confirmation_service.verify_confirmation(user.id, body.code)
    except TelegramConfirmationNotFoundError:
        raise HTTPException(status_code=404, detail="telegram_confirmation_not_found") from None
    except TelegramConfirmationInvalidError:
        raise HTTPException(status_code=400, detail="telegram_confirmation_invalid") from None

    user_repo = UserRepository(get_async_sessionmaker())
    if not await user_repo.link_telegram_id_safely(user.id, telegram_id):
        await confirmation_service.delete_pending(user.id, event="telegram_link_conflict")
        raise HTTPException(status_code=409, detail="telegram_account_conflict")
    await confirmation_service.delete_pending(user.id, event="telegram_link_confirmed")
    return {"ok": True}


@router.delete("/cancel-telegram-link")
@limiter.limit("10/minute")
async def cancel_telegram_link(
    request: Request,
    user: User = Depends(get_current_web_user),
):
    await TelegramLinkConfirmationService().delete_pending(user.id)
    return {"ok": True}


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
        user_id=str(user.id),
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
    raw_key = _parse_idempotency_key(request)
    scoped_key, _ = _checkout_keys(user.id, "web_tarot", raw_key)

    try:
        checkout_amount = await PaymentService.resolve_web_checkout_amount(
            session_factory,
            product="web_tarot",
            promo_code=body.promo_code,
        )
    except PromoCheckoutError as error:
        raise HTTPException(
            status_code=400,
            detail=_PROMO_ERROR_DETAILS[error.reason],
        ) from None
    provider_key = _provider_key(scoped_key, checkout_amount)

    try:
        payment_url = await _complete_web_checkout(
            session_factory=session_factory,
            user=user,
            checkout_amount=checkout_amount,
            scoped_key=scoped_key,
            provider_key=provider_key,
            report_token=None,
        )
    except ValueError as error:
        if str(error) == "promo_capacity_exhausted":
            raise HTTPException(status_code=400, detail=_PROMO_ERROR_DETAILS["exhausted"]) from None
        if str(error) == "idempotency_key_conflict":
            raise HTTPException(status_code=409, detail="idempotency_key_conflict") from None
        if str(error) in {"invalid_promo_reservation", "invalid_reservation_transition", "reservation_attachment_conflict", "payment_attachment_conflict"}:
            raise HTTPException(status_code=409, detail="checkout_conflict") from None
        raise HTTPException(status_code=503, detail="checkout_unavailable") from None
    except Exception:
        raise HTTPException(status_code=503, detail="Платёжный сервис недоступен") from None

    return SubscribeResponse(payment_url=payment_url)


def _web_history_key(uid) -> str:
    return f"chat:history:{uid}"


def _web_chat_request_key(user_id: object, raw_request_key: str) -> str:
    return hashlib.sha256(
        f"nura.web-chat.v1|{user_id}|{raw_request_key}".encode()
    ).hexdigest()


def _safe_chat_history(value: object) -> list[dict[str, str]]:
    """Accept only bounded conversational turns; never forward client system roles."""
    if not isinstance(value, list):
        return []
    safe: list[dict[str, str]] = []
    for item in value[-10:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        safe.append({"role": role, "content": content[:2000]})
    return safe


def _chat_subscriber(user: User) -> bool:
    return ChatQuotaService.is_subscriber(
        tarot_subscription=bool(user.tarot_subscription),
        tarot_subscription_until=user.tarot_subscription_until,
        subscription_status=user.subscription_status,
        subscription_until=user.subscription_until,
    )


@router.get("/chat/state", response_model=ChatQuotaState)
@limiter.limit("60/minute")
async def web_chat_state(
    request: Request,
    user: User = Depends(get_current_web_user),
):
    quota = ChatQuotaService(get_async_sessionmaker())
    return await quota.state(user.id, subscriber=_chat_subscriber(user))


@router.post("/chat", response_model=ChatResponse)
@limiter.limit("20/minute")
async def web_chat(
    request: Request,
    body: ChatRequest,
    user: User = Depends(get_current_web_user),
):
    raw_request_key = _parse_idempotency_key(request)
    session_factory = get_async_sessionmaker()
    report_repo = ReportRepository(session_factory)

    has_unlimited = _chat_subscriber(user)
    redis = get_redis()
    quota_service = ChatQuotaService(session_factory)

    history_key = _web_history_key(user.id)
    raw_history = await redis.get(history_key)
    if raw_history:
        try:
            server_history: list[dict] = _safe_chat_history(json.loads(raw_history))
        except (json.JSONDecodeError, TypeError):
            server_history = _safe_chat_history(body.history)
    else:
        server_history = _safe_chat_history(body.history)

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

    request_key = _web_chat_request_key(user.id, raw_request_key)
    result = await ChatApplicationService(quota_service).respond(
        user_id=user.id,
        request_key=request_key,
        channel=ChatChannel.WEB,
        subscriber=has_unlimited,
        message=body.message,
        history=server_history,
        matrix_data=matrix_data,
        user_name=user_name,
        history_finalizer=lambda reply: finalize_chat_history_once(
            redis, user_id=user.id,
            request_key=request_key,
            user_message=body.message,
            assistant_response=reply,
        ),
    )
    if result.kind == ChatResultKind.QUOTA_EXHAUSTED:
        return JSONResponse(status_code=402, content=result.quota.model_dump(mode="json"))
    if result.kind not in {ChatResultKind.COMPLETED_NEW, ChatResultKind.COMPLETED_REPLAYED}:
        raise HTTPException(status_code=503, detail="chat_unavailable")
    return ChatResponse(reply=result.reply or "", quota=result.quota)

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
async def logout(
    response: Response,
    user: User | None = Depends(get_optional_web_user),
):
    if user is not None:
        await UserRepository(get_async_sessionmaker()).clear_web_session(user.id)
        try:
            await TelegramLinkConfirmationService().delete_pending(user.id)
        except Exception:
            logger.warning("telegram_link_pending_cleanup_failed")
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


_LEGACY_TELEGRAM_AUTH_RETIRED_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _legacy_telegram_auth_retired() -> None:
    raise HTTPException(
        status_code=410,
        detail="legacy_telegram_auth_retired",
        headers=_LEGACY_TELEGRAM_AUTH_RETIRED_HEADERS,
    )


@router.post("/auth/start")
@limiter.limit("10/hour")
async def auth_start(request: Request) -> None:
    _legacy_telegram_auth_retired()


@router.get("/auth/check")
@limiter.limit("60/minute")
async def auth_check(request: Request) -> None:
    _legacy_telegram_auth_retired()


@router.delete("/account")
@limiter.limit("3/hour")
async def delete_account(
    request: Request,
    response: Response,
    user: User = Depends(get_current_web_user),
):
    session_factory = get_async_sessionmaker()
    await AccountDeletionService(session_factory, get_redis()).delete(user.id)

    clear_session_cookie(response)
    return {"ok": True}
