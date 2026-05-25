from fastapi import APIRouter, HTTPException, Request

from api.deps import limiter
from core.database import get_async_sessionmaker
from core.services.payment import PaymentService

router = APIRouter(prefix="/api/v1/payment")


@router.post("/webhook")
@limiter.limit("10/minute")
async def payment_webhook(request: Request):
    data = await request.json()
    try:
        return await PaymentService.process_webhook(
            get_async_sessionmaker(), data
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
