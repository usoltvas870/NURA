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
    async def create_web_matrix_payment(
        user_id: uuid.UUID, report_token: str
    ) -> dict:
        idempotence_key = uuid.uuid4().hex[:32]
        payment = YooPayment.create(
            {
                "amount": {
                    "value": f"{settings.matrix_one_time_price_rub}.00",
                    "currency": "RUB",
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": f"{settings.report_base_url}/report/{report_token}",
                },
                "capture": True,
                "save_payment_method": False,
                "description": "NURA — Полная матрица судьбы (веб)",
                    "metadata": {
                        "user_id": str(user_id),
                        "payment_type": "web_matrix",
                        "report_token": report_token,
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

        if payment_type == "web_matrix":
            if not yookassa_id:
                raise ValueError("Missing payment id")
            user_id_str = metadata.get("user_id")
            if not user_id_str:
                raise ValueError("Missing user_id in web_matrix payment")

            payment_repo = PaymentRepository(session_factory)
            user_repo = UserRepository(session_factory)

            payment = await payment_repo.get_by_yookassa_id(yookassa_id)
            if payment is None:
                raise ValueError("Payment not found")

            await payment_repo.update_status(payment.id, "succeeded")

            user = await user_repo.get(uuid.UUID(user_id_str))
            if user is None:
                raise ValueError("Web user not found")

            await user_repo.update_has_matrix(user.id, True)

            if user.birth_date:
                from core.services.report import ReportService
                from core.tasks import generate_full_report

                report_token = metadata.get("report_token") or ReportService.generate_token()
                generate_full_report.delay(
                    str(user.id), user.birth_date, report_token
                )

            return {"ok": True}

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

            if user.birth_date:
                from core.services.report import ReportService
                from core.tasks import generate_full_report

                report_token = ReportService.generate_token()
                generate_full_report.delay(
                    str(user.id), user.birth_date, report_token
                )

            from core.tasks import _send_message as send_msg

            await send_msg(
                user.telegram_id,
                "✦ Оплата прошла успешно!\n\n"
                "Генерирую твою Матрицу Судьбы...\n"
                "Это займёт 1-2 минуты.",
            )
        else:
            await user_repo.update_subscription(user.id, "premium", until)

        return {"ok": True}
