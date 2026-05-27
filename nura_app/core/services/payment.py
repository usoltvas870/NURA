from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker
from yookassa import Configuration, Payment as YooPayment

from core.config import settings
from core.models import Payment as PaymentModel
from core.repositories.payment import PaymentRepository
from core.repositories.user import UserRepository

Configuration.account_id = settings.yookassa_shop_id
Configuration.secret_key = settings.yookassa_secret_key


class PaymentService:
    @staticmethod
    async def create_subscription(telegram_id: int) -> dict:
        idempotence_key = uuid.uuid4().hex[:32]
        payment = YooPayment.create(
            {
                "amount": {
                    "value": f"{settings.subscription_price_rub}.00",
                    "currency": "RUB",
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": f"{settings.report_base_url}/subscription/success",
                },
                "capture": True,
                "save_payment_method": True,
                "description": "NURA — Ежедневные инсайты (подписка)",
                "metadata": {
                    "telegram_id": telegram_id,
                    "subscription": "true",
                },
            },
            idempotence_key,
        )
        return {
            "id": payment.id,
            "status": payment.status,
            "payment_url": payment.confirmation.confirmation_url,
            "payment_method_id": getattr(payment.payment_method, "id", None),
        }

    @staticmethod
    async def create_tarot_payment(telegram_id: int) -> dict:
        idempotence_key = uuid.uuid4().hex[:32]
        payment = YooPayment.create(
            {
                "amount": {
                    "value": f"{settings.tarot_subscription_price_rub}.00",
                    "currency": "RUB",
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": f"{settings.report_base_url}/subscription/success",
                },
                "capture": True,
                "save_payment_method": True,
                "description": "NURA — Таро-ритуалы (подписка)",
                "metadata": {
                    "telegram_id": telegram_id,
                    "payment_type": "tarot",
                },
            },
            idempotence_key,
        )
        return {
            "id": payment.id,
            "status": payment.status,
            "payment_url": payment.confirmation.confirmation_url,
            "payment_method_id": getattr(payment.payment_method, "id", None),
        }

    @staticmethod
    async def create_matrix_payment(telegram_id: int) -> dict:
        idempotence_key = uuid.uuid4().hex[:32]
        payment = YooPayment.create(
            {
                "amount": {
                    "value": f"{settings.matrix_one_time_price_rub}.00",
                    "currency": "RUB",
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": f"{settings.report_base_url}/subscription/success",
                },
                "capture": True,
                "save_payment_method": False,
                "description": "NURA — Полная матрица судьбы (разовый отчёт)",
                "metadata": {
                    "telegram_id": telegram_id,
                    "payment_type": "matrix",
                },
            },
            idempotence_key,
        )
        return {
            "id": payment.id,
            "status": payment.status,
            "payment_url": payment.confirmation.confirmation_url,
            "payment_method_id": getattr(payment.payment_method, "id", None),
        }

    @staticmethod
    async def save_matrix_payment(
        session_factory: async_sessionmaker,
        user_id: uuid.UUID,
        yookassa_payment_id: str,
    ) -> PaymentModel:
        payment_repo = PaymentRepository(session_factory)
        return await payment_repo.create(
            user_id=user_id,
            amount=890,
            yookassa_id=yookassa_payment_id,
            payment_type="matrix",
        )

    @staticmethod
    def get_test_matrix_payment() -> dict:
        return {
            "payment_id": "test_matrix_payment",
            "confirmation_url": None,
            "status": "test",
        }

    @staticmethod
    async def cancel_subscription(payment_method_id: str) -> None:
        from yookassa import PaymentMethod as YooPaymentMethod

        YooPaymentMethod.cancel(payment_method_id)

    @staticmethod
    async def process_webhook(
        session_factory: async_sessionmaker, data: dict
    ) -> dict:
        event = data.get("event")
        payment_obj = data.get("object", {})

        if event != "payment.succeeded":
            return {"status": "ignored"}

        yookassa_id = payment_obj.get("id")
        metadata = payment_obj.get("metadata", {})
        telegram_id = metadata.get("telegram_id")
        payment_type = metadata.get("payment_type", "subscription")

        if not telegram_id or not yookassa_id:
            raise ValueError("Missing telegram_id or payment id")

        payment_repo = PaymentRepository(session_factory)
        user_repo = UserRepository(session_factory)

        payment = await payment_repo.get_by_yookassa_id(yookassa_id)
        if payment is None:
            raise ValueError("Payment not found")

        await payment_repo.update_status(payment.id, "succeeded")

        user = await user_repo.get_by_telegram_id(telegram_id)
        if user is None:
            raise ValueError("User not found")

        until = datetime.now(timezone.utc) + timedelta(days=30)

        if payment_type == "tarot":
            await user_repo.update_tarot_subscription(user.id, True, until)
        elif payment_type == "matrix":
            await user_repo.update_has_matrix(user.id, True)
        else:
            await user_repo.update_subscription(user.id, "premium", until)

        return {"ok": True}
