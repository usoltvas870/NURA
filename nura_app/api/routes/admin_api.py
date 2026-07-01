import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select, text

from core.config import settings
from core.database import get_async_sessionmaker, get_redis
from core.models import Payment, PromoCode, Report, ReportType, User
from core.repositories.report import ReportRepository
from core.repositories.user import UserRepository
from core.services.report import ReportService
from core.tasks import generate_full_report

DOCKER_SOCK = "/var/run/docker.sock"


async def verify_admin_token(x_admin_token: str = Header(..., alias="X-Admin-Token")) -> None:
    if not settings.admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


router = APIRouter(prefix="/api/v1/admin", dependencies=[Depends(verify_admin_token)])


class StatsResponse(BaseModel):
    users_total: int
    users_new_24h: int
    users_new_7d: int
    subscriptions_premium_active: int
    subscriptions_tarot_active: int
    users_telegram_linked: int
    users_push_subscribed: int
    revenue_total: int
    revenue_30d: int
    revenue_7d: int
    unique_paying_users: int
    payment_breakdown: list[dict]
    referrals_total: int
    referrals_new_7d: int
    top_referrers: list[dict]
    reports_by_type: dict
    registrations_by_day: list[dict]
    revenue_by_day: list[dict]


@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    session_factory = get_async_sessionmaker()
    async with session_factory() as session:

        def _scalar(result):
            val = result.scalar()
            return val if val is not None else 0

        r = await session.execute(text("SELECT COUNT(*) FROM users"))
        users_total = _scalar(r)

        r = await session.execute(
            text("SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '24 hours'")
        )
        users_new_24h = _scalar(r)

        r = await session.execute(
            text("SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '7 days'")
        )
        users_new_7d = _scalar(r)

        r = await session.execute(
            text(
                "SELECT COUNT(*) FROM users WHERE subscription_status = 'premium'"
                " AND (subscription_until IS NULL OR subscription_until > NOW())"
            )
        )
        subscriptions_premium_active = _scalar(r)

        r = await session.execute(
            text(
                "SELECT COUNT(*) FROM users WHERE tarot_subscription = true"
                " AND (tarot_subscription_until IS NULL OR tarot_subscription_until > NOW())"
            )
        )
        subscriptions_tarot_active = _scalar(r)

        r = await session.execute(
            text("SELECT COUNT(*) FROM users WHERE telegram_id IS NOT NULL")
        )
        users_telegram_linked = _scalar(r)

        r = await session.execute(
            text("SELECT COUNT(*) FROM users WHERE has_pwa_push = true")
        )
        users_push_subscribed = _scalar(r)

        r = await session.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'succeeded'")
        )
        revenue_total = _scalar(r)

        r = await session.execute(
            text(
                "SELECT COALESCE(SUM(amount), 0) FROM payments"
                " WHERE status = 'succeeded' AND created_at >= NOW() - INTERVAL '30 days'"
            )
        )
        revenue_30d = _scalar(r)

        r = await session.execute(
            text(
                "SELECT COALESCE(SUM(amount), 0) FROM payments"
                " WHERE status = 'succeeded' AND created_at >= NOW() - INTERVAL '7 days'"
            )
        )
        revenue_7d = _scalar(r)

        r = await session.execute(
            text("SELECT COUNT(DISTINCT user_id) FROM payments WHERE status = 'succeeded'")
        )
        unique_paying_users = _scalar(r)

        r = await session.execute(
            text(
                "SELECT payment_type, COUNT(*), COALESCE(SUM(amount), 0)"
                " FROM payments WHERE status = 'succeeded' GROUP BY payment_type"
            )
        )
        payment_breakdown = [
            {"payment_type": row[0], "count": row[1], "total_amount": row[2]}
            for row in r
        ]

        r = await session.execute(
            text("SELECT report_type, COUNT(*) FROM reports GROUP BY report_type")
        )
        reports_by_type = {"mini": 0, "full": 0, "compatibility": 0}
        for row in r:
            reports_by_type[row[0]] = row[1]

        r = await session.execute(
            text(
                "SELECT DATE(created_at AT TIME ZONE 'UTC') as day, COUNT(*) as cnt"
                " FROM users WHERE created_at >= NOW() - INTERVAL '14 days'"
                " GROUP BY day ORDER BY day"
            )
        )
        registrations_by_day = [{"date": str(row[0]), "value": row[1]} for row in r]

        r = await session.execute(
            text(
                "SELECT DATE(created_at AT TIME ZONE 'UTC') as day, COALESCE(SUM(amount), 0) as revenue"
                " FROM payments WHERE status = 'succeeded' AND created_at >= NOW() - INTERVAL '14 days'"
                " GROUP BY day ORDER BY day"
            )
        )
        revenue_by_day = [{"date": str(row[0]), "value": row[1]} for row in r]

        r = await session.execute(
            text("SELECT COUNT(*) FROM referral_rewards")
        )
        referrals_total = _scalar(r)

        r = await session.execute(
            text("SELECT COUNT(*) FROM referral_rewards WHERE rewarded_at >= NOW() - INTERVAL '7 days'")
        )
        referrals_new_7d = _scalar(r)

        r = await session.execute(
            text(
                "SELECT u.first_name, u.name, u.telegram_id, COUNT(rr.id) as cnt"
                " FROM referral_rewards rr"
                " JOIN users u ON rr.referrer_id = u.id"
                " GROUP BY u.id, u.first_name, u.name, u.telegram_id"
                " ORDER BY cnt DESC LIMIT 10"
            )
        )
        top_referrers = [
            {"name": row[0] or row[1] or f"ID:{row[2]}", "telegram_id": row[2], "count": row[3]}
            for row in r
        ]

        return StatsResponse(
            users_total=users_total,
            users_new_24h=users_new_24h,
            users_new_7d=users_new_7d,
            subscriptions_premium_active=subscriptions_premium_active,
            subscriptions_tarot_active=subscriptions_tarot_active,
            users_telegram_linked=users_telegram_linked,
            users_push_subscribed=users_push_subscribed,
            revenue_total=revenue_total,
            revenue_30d=revenue_30d,
            revenue_7d=revenue_7d,
            unique_paying_users=unique_paying_users,
            payment_breakdown=payment_breakdown,
            referrals_total=referrals_total,
            referrals_new_7d=referrals_new_7d,
            top_referrers=top_referrers,
            reports_by_type=reports_by_type,
            registrations_by_day=registrations_by_day,
            revenue_by_day=revenue_by_day,
        )


class UserRow(BaseModel):
    id: str
    telegram_id: int | None
    username: str | None
    first_name: str | None
    name: str | None
    birth_date: str | None
    main_archetype: str | None
    auth_method: str | None
    vk_id: str | None
    email: str | None
    email_verified: bool
    subscription_status: str
    subscription_until: str | None
    tarot_subscription: bool
    has_matrix: bool
    has_pwa_push: bool
    created_at: str
    payments_count: int
    total_paid: int


class UsersResponse(BaseModel):
    users: list[UserRow]
    total: int
    page: int
    per_page: int
    pages: int


@router.get("/users", response_model=UsersResponse)
async def get_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str | None = None,
    filter: str | None = None,
):
    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        payment_subq = (
            select(
                Payment.user_id,
                func.count(Payment.id).label("payments_count"),
                func.coalesce(func.sum(Payment.amount), 0).label("total_paid"),
            )
            .where(Payment.status == "succeeded")
            .group_by(Payment.user_id)
            .subquery()
        )

        base = select(
            User,
            func.coalesce(payment_subq.c.payments_count, 0).label("payments_count"),
            func.coalesce(payment_subq.c.total_paid, 0).label("total_paid"),
        ).outerjoin(payment_subq, User.id == payment_subq.c.user_id)

        conditions = []
        if search:
            like = f"%{search}%"
            conditions.append(
                or_(
                    User.name.ilike(like),
                    User.username.ilike(like),
                    User.first_name.ilike(like),
                )
            )
        if filter:
            if filter == "premium":
                conditions.append(User.subscription_status == "premium")
            elif filter == "tarot":
                conditions.append(User.tarot_subscription == True)  # noqa: E712
            elif filter == "vk":
                conditions.append(User.vk_id != None)  # noqa: E711
            elif filter == "email":
                conditions.append(User.email != None)  # noqa: E711
            elif filter == "telegram":
                conditions.append(User.telegram_id != None)  # noqa: E711
            elif filter == "push":
                conditions.append(User.has_pwa_push == True)  # noqa: E712

        if conditions:
            base = base.where(*conditions)

        count_q = select(func.count()).select_from(base.subquery())
        total = (await session.execute(count_q)).scalar() or 0

        offset = (page - 1) * per_page
        base = base.order_by(User.created_at.desc()).offset(offset).limit(per_page)

        result = await session.execute(base)
        rows = result.all()

        users = []
        for user, payments_count, total_paid in rows:
            users.append(
                UserRow(
                    id=str(user.id),
                    telegram_id=user.telegram_id,
                    username=user.username,
                    first_name=user.first_name,
                    name=user.name,
                    birth_date=user.birth_date,
                    main_archetype=user.main_archetype,
                    auth_method=user.auth_method,
                    vk_id=user.vk_id,
                    email=user.email,
                    email_verified=user.email_verified,
                    subscription_status=user.subscription_status,
                    subscription_until=user.subscription_until.isoformat()
                    if user.subscription_until
                    else None,
                    tarot_subscription=user.tarot_subscription,
                    has_matrix=user.has_matrix,
                    has_pwa_push=user.has_pwa_push,
                    created_at=user.created_at.isoformat() if user.created_at else "",
                    payments_count=payments_count,
                    total_paid=total_paid,
                )
            )

        pages = (total + per_page - 1) // per_page if total > 0 else 1

        return UsersResponse(
            users=users,
            total=total,
            page=page,
            per_page=per_page,
            pages=pages,
        )


class PaymentRow(BaseModel):
    id: str
    user_name: str | None
    amount: int
    status: str
    payment_type: str
    created_at: str
    yookassa_id: str | None


class PaymentsResponse(BaseModel):
    payments: list[PaymentRow]
    total: int
    page: int
    per_page: int
    pages: int
    total_succeeded_amount: int


@router.get("/payments", response_model=PaymentsResponse)
async def get_payments(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    status: str | None = None,
    payment_type: str | None = None,
):
    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        base = select(
            Payment,
            User.first_name,
            User.name,
        ).outerjoin(User, Payment.user_id == User.id)

        count_q = select(func.count(Payment.id))

        if status:
            base = base.where(Payment.status == status)
            count_q = count_q.where(Payment.status == status)
        if payment_type:
            base = base.where(Payment.payment_type == payment_type)
            count_q = count_q.where(Payment.payment_type == payment_type)

        total = (await session.execute(count_q)).scalar() or 0

        amount_r = await session.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'succeeded'")
        )
        total_succeeded_amount = amount_r.scalar() or 0

        offset = (page - 1) * per_page
        base = base.order_by(Payment.created_at.desc()).offset(offset).limit(per_page)

        result = await session.execute(base)
        rows = result.all()

        payments = []
        for payment, user_first_name, user_name in rows:
            payments.append(
                PaymentRow(
                    id=str(payment.id),
                    user_name=user_first_name or user_name,
                    amount=payment.amount,
                    status=payment.status,
                    payment_type=payment.payment_type,
                    created_at=payment.created_at.isoformat() if payment.created_at else "",
                    yookassa_id=payment.yookassa_id,
                )
            )

        pages = (total + per_page - 1) // per_page if total > 0 else 1

        return PaymentsResponse(
            payments=payments,
            total=total,
            page=page,
            per_page=per_page,
            pages=pages,
            total_succeeded_amount=total_succeeded_amount,
        )


class UserDetailReport(BaseModel):
    report_type: str
    token: str
    url: str
    created_at: str


class UserDetailPayment(BaseModel):
    amount: int
    status: str
    payment_type: str
    created_at: str


class UserDetailResponse(BaseModel):
    id: str
    telegram_id: int | None
    username: str | None
    first_name: str | None
    name: str | None
    birth_date: str | None
    main_archetype: str | None
    main_archetype_number: int | None
    auth_method: str | None
    vk_id: str | None
    email: str | None
    email_verified: bool
    subscription_status: str
    subscription_until: str | None
    tarot_subscription: bool
    tarot_subscription_until: str | None
    has_matrix: bool
    has_pwa_push: bool
    web_session_expires_at: str | None
    created_at: str
    reports: list[UserDetailReport]
    payments: list[UserDetailPayment]


class ExtendSubscriptionRequest(BaseModel):
    days: int = Field(30, ge=1, le=3650)


class GrantSubscriptionRequest(BaseModel):
    days: int = Field(30, ge=1, le=3650)


@router.get("/users/{user_id}", response_model=UserDetailResponse)
async def get_user_detail(user_id: str):
    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        user_uuid = uuid.UUID(user_id)
        user_result = await session.execute(
            select(User).where(User.id == user_uuid)
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        reports_result = await session.execute(
            select(Report)
            .where(Report.user_id == user_uuid)
            .order_by(Report.created_at.desc())
        )
        reports = reports_result.scalars().all()

        payments_result = await session.execute(
            select(Payment)
            .where(Payment.user_id == user_uuid)
            .order_by(Payment.created_at.desc())
            .limit(10)
        )
        payments = payments_result.scalars().all()

        return UserDetailResponse(
            id=str(user.id),
            telegram_id=user.telegram_id,
            username=user.username,
            first_name=user.first_name,
            name=user.name,
            birth_date=user.birth_date,
            main_archetype=user.main_archetype,
            main_archetype_number=user.main_archetype_number,
            auth_method=user.auth_method,
            vk_id=user.vk_id,
            email=user.email,
            email_verified=user.email_verified,
            subscription_status=user.subscription_status,
            subscription_until=user.subscription_until.isoformat()
            if user.subscription_until
            else None,
            tarot_subscription=user.tarot_subscription,
            tarot_subscription_until=user.tarot_subscription_until.isoformat()
            if user.tarot_subscription_until
            else None,
            has_matrix=user.has_matrix,
            has_pwa_push=user.has_pwa_push,
            web_session_expires_at=user.web_session_expires_at.isoformat()
            if user.web_session_expires_at
            else None,
            created_at=user.created_at.isoformat() if user.created_at else "",
            reports=[
                UserDetailReport(
                    report_type=r.report_type,
                    token=r.token,
                    url=f"{settings.report_base_url}/report/{r.token}",
                    created_at=r.created_at.isoformat() if r.created_at else "",
                )
                for r in reports
            ],
            payments=[
                UserDetailPayment(
                    amount=p.amount,
                    status=p.status,
                    payment_type=p.payment_type,
                    created_at=p.created_at.isoformat() if p.created_at else "",
                )
                for p in payments
            ],
        )


@router.post("/users/{user_id}/subscription/extend")
async def extend_user_subscription(user_id: str, body: ExtendSubscriptionRequest):
    user_uuid = uuid.UUID(user_id)
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.extend_subscription(user_uuid, body.days)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "subscription_until": user.subscription_until.isoformat()}


@router.post("/users/{user_id}/tarot/extend")
async def extend_user_tarot(user_id: str, body: ExtendSubscriptionRequest):
    user_uuid = uuid.UUID(user_id)
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.extend_tarot(user_uuid, body.days)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "tarot_subscription_until": user.tarot_subscription_until.isoformat()}


@router.post("/users/{user_id}/subscription/grant")
async def grant_user_subscription(user_id: str, body: GrantSubscriptionRequest):
    user_uuid = uuid.UUID(user_id)
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.grant_premium(user_uuid, body.days)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "subscription_until": user.subscription_until.isoformat()}


@router.post("/users/{user_id}/tarot/grant")
async def grant_user_tarot(user_id: str, body: GrantSubscriptionRequest):
    user_uuid = uuid.UUID(user_id)
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.grant_tarot(user_uuid, body.days)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "tarot_subscription_until": user.tarot_subscription_until.isoformat()}


@router.post("/users/{user_id}/regenerate-matrix")
async def regenerate_user_matrix(user_id: str):
    user_uuid = uuid.UUID(user_id)
    session_factory = get_async_sessionmaker()

    async with session_factory() as session:
        user_result = await session.execute(
            select(User).where(User.id == user_uuid)
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        if not user.birth_date:
            raise HTTPException(status_code=400, detail="Нет даты рождения")

        birth_date = user.birth_date

    report_repo = ReportRepository(session_factory)
    existing_report = await report_repo.get_by_user_id_and_type(user_uuid, ReportType.FULL)
    if existing_report:
        await report_repo.delete(existing_report.id)

    new_token = ReportService.generate_token()
    generate_full_report.delay(
        user_id=str(user_uuid), birth_date=birth_date, report_token=new_token
    )

    return {"ok": True}


class HealthComponent(BaseModel):
    name: str
    status: str
    latency_ms: float | None
    detail: str | None


class HealthResponse(BaseModel):
    overall: str
    components: list[HealthComponent]
    checked_at: str


@router.get("/health", response_model=HealthResponse)
async def get_health():
    checked_at = datetime.now(timezone.utc).isoformat()

    async def check_postgres():
        start = time.monotonic()
        try:
            async def _run():
                session_factory = get_async_sessionmaker()
                async with session_factory() as session:
                    await session.execute(text("SELECT 1"))

            await asyncio.wait_for(_run(), timeout=5.0)
            latency = (time.monotonic() - start) * 1000
            return {"name": "PostgreSQL", "status": "ok", "latency_ms": round(latency, 1), "detail": None}
        except asyncio.TimeoutError:
            return {"name": "PostgreSQL", "status": "error", "latency_ms": None, "detail": "Connection timeout"}
        except Exception as e:
            return {"name": "PostgreSQL", "status": "error", "latency_ms": None, "detail": str(e)}

    async def check_redis():
        start = time.monotonic()
        try:
            redis = get_redis()
            await asyncio.wait_for(redis.ping(), timeout=5.0)
            latency = (time.monotonic() - start) * 1000
            return {"name": "Redis", "status": "ok", "latency_ms": round(latency, 1), "detail": None}
        except asyncio.TimeoutError:
            return {"name": "Redis", "status": "error", "latency_ms": None, "detail": "Connection timeout"}
        except Exception as e:
            return {"name": "Redis", "status": "error", "latency_ms": None, "detail": str(e)}

    async def check_deepseek():
        start = time.monotonic()
        if not settings.deepseek_api_key:
            return {"name": "DeepSeek", "status": "error", "latency_ms": None, "detail": "API key not configured"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.deepseek.com/v1/models",
                    headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                )
                latency = (time.monotonic() - start) * 1000
                if resp.status_code == 200:
                    return {"name": "DeepSeek", "status": "ok", "latency_ms": round(latency, 1), "detail": None}
                return {"name": "DeepSeek", "status": "error", "latency_ms": None, "detail": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"name": "DeepSeek", "status": "error", "latency_ms": None, "detail": str(e)}

    async def check_yookassa():
        start = time.monotonic()
        if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
            return {
                "name": "Yookassa",
                "status": "error",
                "latency_ms": None,
                "detail": "API credentials not configured",
            }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.yookassa.ru/v3/me",
                    auth=(settings.yookassa_shop_id, settings.yookassa_secret_key),
                )
                latency = (time.monotonic() - start) * 1000
                if resp.status_code == 200:
                    return {"name": "Yookassa", "status": "ok", "latency_ms": round(latency, 1), "detail": None}
                return {"name": "Yookassa", "status": "error", "latency_ms": None, "detail": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"name": "Yookassa", "status": "error", "latency_ms": None, "detail": str(e)}

    async def check_telegram():
        start = time.monotonic()
        if not settings.telegram_bot_token:
            return {"name": "Telegram Bot", "status": "error", "latency_ms": None, "detail": "Bot token not configured"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe",
                )
                latency = (time.monotonic() - start) * 1000
                if resp.status_code == 200 and resp.json().get("ok"):
                    return {"name": "Telegram Bot", "status": "ok", "latency_ms": round(latency, 1), "detail": None}
                return {"name": "Telegram Bot", "status": "error", "latency_ms": None, "detail": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"name": "Telegram Bot", "status": "error", "latency_ms": None, "detail": str(e)}

    results = await asyncio.gather(
        check_postgres(),
        check_redis(),
        check_deepseek(),
        check_yookassa(),
        check_telegram(),
        return_exceptions=True,
    )

    components = []
    for r in results:
        if isinstance(r, Exception):
            components.append(HealthComponent(name="Unknown", status="error", latency_ms=None, detail=str(r)))
        else:
            components.append(HealthComponent(**r))

    error_components = [c for c in components if c.status == "error"]
    if not error_components:
        overall = "ok"
    elif all(c.name in ("Redis", "DeepSeek") for c in error_components):
        overall = "degraded"
    else:
        overall = "error"

    return HealthResponse(overall=overall, components=components, checked_at=checked_at)


class PromoCodeCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=64)
    discount_percent: int = Field(..., ge=1, le=100)
    max_uses: int | None = None
    expires_at: str | None = None


class PromoCodeResponse(BaseModel):
    id: str
    code: str
    discount_percent: int
    max_uses: int | None
    used_count: int
    expires_at: str | None
    is_active: bool
    created_at: str
    model_config = {"from_attributes": True}


class PromoCodeListResponse(BaseModel):
    codes: list[PromoCodeResponse]
    total: int


class BroadcastRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    channels: list[str] = Field(..., min_length=1)
    filter: str = "all"
    push_title: str | None = None
    push_url: str | None = None

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, v):
        allowed = {"telegram", "push"}
        for ch in v:
            if ch not in allowed:
                raise ValueError(f"Invalid channel: {ch}")
        return v

    @field_validator("filter")
    @classmethod
    def validate_filter(cls, v):
        if v not in ("all", "premium", "free"):
            raise ValueError("Filter must be all, premium, or free")
        return v


@router.get("/promo-codes", response_model=PromoCodeListResponse)
async def get_promo_codes():
    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        result = await session.execute(
            select(PromoCode).order_by(PromoCode.created_at.desc())
        )
        codes = result.scalars().all()
        total = len(codes)
        response = [
            PromoCodeResponse(
                id=str(c.id),
                code=c.code,
                discount_percent=c.discount_percent,
                max_uses=c.max_uses,
                used_count=c.used_count,
                expires_at=c.expires_at.isoformat() if c.expires_at else None,
                is_active=c.is_active,
                created_at=c.created_at.isoformat() if c.created_at else "",
            )
            for c in codes
        ]
        return PromoCodeListResponse(codes=response, total=total)


@router.post("/promo-codes", response_model=PromoCodeResponse)
async def create_promo_code(body: PromoCodeCreate):
    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        expires_at = None
        if body.expires_at:
            expires_at = datetime.fromisoformat(body.expires_at)
        promo = PromoCode(
            code=body.code.strip().upper(),
            discount_percent=body.discount_percent,
            max_uses=body.max_uses,
            expires_at=expires_at,
        )
        session.add(promo)
        await session.commit()
        await session.refresh(promo)
        return PromoCodeResponse(
            id=str(promo.id),
            code=promo.code,
            discount_percent=promo.discount_percent,
            max_uses=promo.max_uses,
            used_count=promo.used_count,
            expires_at=promo.expires_at.isoformat() if promo.expires_at else None,
            is_active=promo.is_active,
            created_at=promo.created_at.isoformat() if promo.created_at else "",
        )


@router.patch("/promo-codes/{code_id}/toggle", response_model=PromoCodeResponse)
async def toggle_promo_code(code_id: str):
    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        code_uuid = uuid.UUID(code_id)
        result = await session.execute(
            select(PromoCode).where(PromoCode.id == code_uuid)
        )
        promo = result.scalar_one_or_none()
        if promo is None:
            raise HTTPException(status_code=404, detail="Promo code not found")
        promo.is_active = not promo.is_active
        await session.commit()
        await session.refresh(promo)
        return PromoCodeResponse(
            id=str(promo.id),
            code=promo.code,
            discount_percent=promo.discount_percent,
            max_uses=promo.max_uses,
            used_count=promo.used_count,
            expires_at=promo.expires_at.isoformat() if promo.expires_at else None,
            is_active=promo.is_active,
            created_at=promo.created_at.isoformat() if promo.created_at else "",
        )


@router.delete("/promo-codes/{code_id}")
async def delete_promo_code(code_id: str):
    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        code_uuid = uuid.UUID(code_id)
        result = await session.execute(
            select(PromoCode).where(PromoCode.id == code_uuid)
        )
        promo = result.scalar_one_or_none()
        if promo is None:
            raise HTTPException(status_code=404, detail="Promo code not found")
        await session.delete(promo)
        await session.commit()
        return {"ok": True}


@router.post("/broadcast")
async def start_broadcast(body: BroadcastRequest):
    from core.tasks import send_broadcast

    task = send_broadcast.delay(
        text=body.text,
        channels=body.channels,
        filter_type=body.filter,
        push_title=body.push_title,
        push_url=body.push_url,
    )
    return {"task_id": task.id, "status": "queued"}


@router.get("/broadcast/status/{task_id}")
async def get_broadcast_status(task_id: str):

    redis = get_redis()
    raw = await redis.get(f"broadcast:{task_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Task not found")
    return json.loads(raw)


ALLOWED_CONTAINERS = {"api", "bot", "celery-worker", "celery-beat", "postgres", "redis", "nginx"}


@router.get("/logs")
async def get_logs(
    container: str = Query("api", description="Container name"),
    lines: int = Query(100, ge=10, le=1000),
    level: str = Query("all", description="ERROR|WARNING|INFO|all"),
):
    if container not in ALLOWED_CONTAINERS:
        raise HTTPException(status_code=400, detail=f"Unknown container: {container}")

    if container == "nginx":
        return await _read_nginx_logs(lines, level)

    if not os.path.exists(DOCKER_SOCK):
        return {"lines": [], "container": container, "total": 0,
                "error": "Docker socket not available"}

    try:
        transport = httpx.HTTPTransport(uds=DOCKER_SOCK)
        async with httpx.AsyncClient(transport=transport, timeout=10.0) as client:
            list_resp = await client.get("http://localhost/containers/json")
            list_resp.raise_for_status()
            containers = list_resp.json()

            project = "nura_app"
            target_id = None
            for c in containers:
                names = c.get("Names", [])
                expected = f"/{project}-{container}-1"
                if expected in names:
                    target_id = c["Id"]
                    break

            if not target_id:
                return {"lines": [], "container": container, "total": 0,
                        "error": f"Container {project}-{container}-1 not found"}

            log_resp = await client.get(
                f"http://localhost/containers/{target_id}/logs",
                params={"stdout": "true", "stderr": "true", "tail": lines, "timestamps": "false"},
            )
            log_resp.raise_for_status()
            raw = log_resp.text

    except Exception as e:
        return {"lines": [], "container": container, "total": 0, "error": str(e)}

    parsed = _parse_docker_logs(raw, level)
    return {"lines": parsed, "container": container, "total": len(parsed)}


def _parse_docker_logs(raw: str, level: str) -> list[str]:
    out: list[str] = []
    for line in raw.split("\n"):
        clean = line
        if len(clean) >= 8:
            try:
                _ = int(clean[:8].strip(), 16)
                clean = clean[8:]
            except ValueError:
                pass
        clean = clean.strip()
        if not clean:
            continue
        if level != "all":
            upper = clean.upper()
            if level == "ERROR" and "ERROR" not in upper:
                continue
            if level == "WARNING" and "WARNING" not in upper and "WARN" not in upper:
                continue
            if level == "INFO" and ("ERROR" in upper or "WARNING" in upper or "WARN" in upper):
                continue
        out.append(clean)
    return out


async def _read_nginx_logs(lines: int, level: str) -> dict:
    candidates = ["/var/log/nginx/error.log", "/var/log/nginx/access.log"]
    all_lines: list[str] = []
    for path in candidates:
        if not os.path.exists(path):
            continue
        content = await asyncio.to_thread(_tail_file, path, lines)
        for line in content:
            line = line.strip()
            if not line:
                continue
            if level != "all":
                upper = line.upper()
                if level == "ERROR" and "ERROR" not in upper:
                    continue
                if level == "WARNING" and "WARNING" not in upper:
                    continue
            all_lines.append(f"[nginx:error] {line}" if "error" in path else f"[nginx:access] {line}")
    all_lines = all_lines[-lines:]
    return {"lines": all_lines, "container": "nginx", "total": len(all_lines)}


def _tail_file(path: str, n: int) -> list[str]:
    with open(path, "r", errors="replace") as f:
        f.seek(0, 2)
        size = f.tell()
        buf = ""
        chunk_size = 4096
        pos = size
        count = 0
        while pos > 0 and count <= n:
            read_size = min(chunk_size, pos)
            pos -= read_size
            f.seek(pos)
            buf = f.read(read_size) + buf
            count = buf.count("\n")
        return buf.splitlines()[-n:]
