import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import limiter
from core.config import settings
from core.database import get_async_sessionmaker, get_redis
from core.models import ReportType
from core.repositories.payment import PaymentRepository
from core.repositories.report import ReportRepository
from core.repositories.user import UserRepository
from core.services.ai import AIService
from core.services.matrix import MatrixService
from core.services.payment import PaymentService
from core.services.report import ReportService

router = APIRouter(prefix="/api/v1/web")


class MiniAnalysisRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    birth_date: str = Field(..., pattern=r"^\d{2}\.\d{2}\.\d{4}$")


class MiniAnalysisResponse(BaseModel):
    session_id: str
    main_archetype: str
    core_strength: str
    emotional_conflict: str
    relationship_pattern: str
    financial_block: str


class CreatePaymentRequest(BaseModel):
    session_id: str
    email: str | None = None


class CreatePaymentResponse(BaseModel):
    payment_url: str


@router.post("/mini-analysis", response_model=MiniAnalysisResponse)
@limiter.limit("10/minute")
async def mini_analysis(request: Request, body: MiniAnalysisRequest):
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)

    session_id = uuid.uuid4().hex

    user = await user_repo.create_web_user(
        name=body.name,
        birth_date=body.birth_date,
        web_session_id=session_id,
    )

    try:
        matrix_data = MatrixService.calculate(body.birth_date)
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный формат даты")

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

    return MiniAnalysisResponse(
        session_id=session_id,
        **analysis,
    )


@router.post("/create-payment", response_model=CreatePaymentResponse)
@limiter.limit("5/minute")
async def create_payment(request: Request, body: CreatePaymentRequest):
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)

    user = await user_repo.get_by_web_session_id(body.session_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    if body.email:
        async with session_factory() as session:
            db_user = await session.get(type(user), user.id)
            if db_user:
                db_user.email = body.email
                await session.commit()

    report_token = ReportService.generate_token()

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
        amount=890,
        yookassa_id=payment["id"],
        payment_type="web_matrix",
    )

    return CreatePaymentResponse(payment_url=payment["payment_url"])


class GenerateLinkTokenRequest(BaseModel):
    session_id: str


class GenerateLinkTokenResponse(BaseModel):
    token: str
    tg_url: str


class CheckLinkTokenResponse(BaseModel):
    user_id: str


@router.post("/generate-link-token", response_model=GenerateLinkTokenResponse)
@limiter.limit("10/minute")
async def generate_link_token(request: Request, body: GenerateLinkTokenRequest):
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_web_session_id(body.session_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

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
async def check_link_token(request: Request, token: str):
    redis = get_redis()
    key = f"link_token:{token}"
    user_id = await redis.get(key)
    if not user_id:
        raise HTTPException(status_code=404, detail="Токен не найден или истёк")
    await redis.delete(key)
    return CheckLinkTokenResponse(user_id=user_id)
