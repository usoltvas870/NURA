from fastapi import APIRouter, HTTPException, Request

from api.deps import limiter
from core.database import get_async_sessionmaker
from core.repositories import PaymentRepository, UserRepository

router = APIRouter(prefix="/api/v1/payment")


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
    is_subscription = metadata.get("subscription") == "true"

    if not telegram_id or not yookassa_id:
        raise HTTPException(status_code=400, detail="Missing telegram_id or payment id")

    session_factory = get_async_sessionmaker()
    payment_repo = PaymentRepository(session_factory)
    user_repo = UserRepository(session_factory)

    payment = await payment_repo.get_by_yookassa_id(yookassa_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    await payment_repo.update_status(payment.id, "succeeded")

    if is_subscription:
        user = await user_repo.get_by_telegram_id(telegram_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        from datetime import datetime, timedelta, timezone
        until = datetime.now(timezone.utc) + timedelta(days=30)
        await user_repo.update_subscription(user.id, "premium", until)

    return {"ok": True}
