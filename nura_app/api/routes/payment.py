import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.config import settings
from core.services.payment import PaymentService
from core.services.report import ReportService

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
async def payment_webhook(request: Request):
    data = await request.json()
    event = data.get("event")
    payment_obj = data.get("object", {})

    if event == "payment.succeeded":
        payment_id = payment_obj.get("id")
        metadata = payment_obj.get("metadata", {})
        telegram_id = metadata.get("telegram_id")
        report_token = metadata.get("report_token")
        return {"status": "ok", "payment_id": payment_id}

    return {"status": "ignored"}
