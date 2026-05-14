import uuid

from yookassa import Configuration, Payment as YooPayment

from core.config import settings

Configuration.account_id = settings.yookassa_shop_id
Configuration.secret_key = settings.yookassa_secret_key


class PaymentService:
    @staticmethod
    async def create_payment(telegram_id: int, report_token: str) -> dict:
        idempotence_key = uuid.uuid4().hex[:32]
        payment = YooPayment.create(
            {
                "amount": {
                    "value": f"{settings.report_price_rub}.00",
                    "currency": "RUB",
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": f"{settings.report_base_url}/report/{report_token}",
                },
                "capture": True,
                "description": "NURA — Полный AI-разбор Матрицы Судьбы",
                "metadata": {
                    "telegram_id": telegram_id,
                    "report_token": report_token,
                },
            },
            idempotence_key,
        )
        return {
            "id": payment.id,
            "status": payment.status,
            "payment_url": payment.confirmation.confirmation_url,
        }

    @staticmethod
    async def check_payment(payment_id: str) -> dict:
        payment = YooPayment.find_one(payment_id)
        return {
            "id": payment.id,
            "status": payment.status,
            "paid": payment.paid,
        }
