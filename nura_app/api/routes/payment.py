from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.deps import limiter
from core.database import get_async_sessionmaker
from core.repositories import PaymentRepository, UserRepository
from core.services.payment import PaymentService
from core.services.report import ReportService
from core.tasks import generate_full_report

router = APIRouter(prefix="/api/v1/payment")


class PaymentCreateRequest(BaseModel):
    telegram_id: int


class PaymentCreateResponse(BaseModel):
    payment_id: str
    payment_url: str
    report_token: str


@router.post("")
async def create_payment(body: PaymentCreateRequest):
    report_token = ReportService.generate_token()
    try:
        result = await PaymentService.create_payment(
            body.telegram_id, report_token
        )
        return PaymentCreateResponse(
            payment_id=result["id"],
            payment_url=result["payment_url"],
            report_token=report_token,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook")
@limiter.limit("10/minute")
async def payment_webhook(request: Request):
    data = await request.json()
    event = data.get("event")
    payment_obj = data.get("object", {})

    if event != "payment.succeeded":
        return {"status": "ignored"}

    yookassa_id = payment_obj.get("id")
    metadata = payment_obj.get("metadata", {})

    telegram_id = metadata.get("telegram_id")
    report_token = metadata.get("report_token")

    if not telegram_id or not yookassa_id:
        raise HTTPException(status_code=400, detail="Missing telegram_id or payment id")

    session_factory = get_async_sessionmaker()
    payment_repo = PaymentRepository(session_factory)
    user_repo = UserRepository(session_factory)

    payment = await payment_repo.get_by_yookassa_id(yookassa_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    await payment_repo.update_status(payment.id, "succeeded")

    if report_token:
        user = await user_repo.get_by_telegram_id(telegram_id)
        if user is None or not user.birth_date:
            raise HTTPException(
                status_code=404, detail="User not found or birth date missing"
            )
        generate_full_report.delay(str(user.id), user.birth_date, report_token)

    return {"ok": True}
