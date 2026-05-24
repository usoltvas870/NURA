import uuid

from yookassa import Configuration, Payment as YooPayment

from core.config import settings

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
    async def cancel_subscription(payment_method_id: str) -> None:
        from yookassa import PaymentMethod as YooPaymentMethod

        YooPaymentMethod.cancel(payment_method_id)
