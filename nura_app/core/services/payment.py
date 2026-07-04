import asyncio
import logging
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker
from yookassa import Configuration, Payment as YooPayment

from core.config import settings
from core.models import Payment as PaymentModel
from core.repositories.payment import PaymentRepository
from core.repositories.user import UserRepository

logger = logging.getLogger(__name__)

Configuration.account_id = settings.yookassa_shop_id
Configuration.secret_key = settings.yookassa_secret_key


class PaymentService:
    @staticmethod
    async def create_subscription(telegram_id: int) -> dict:
        idempotence_key = uuid.uuid4().hex[:32]
        payment = YooPayment.create(
            {
                "amount": {
                    "value": f"{settings.tarot_subscription_price_rub}.00",
                    "currency": "RUB",
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": f"{settings.report_base_url}/success",
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
                    "return_url": f"{settings.report_base_url}/success",
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
                    "return_url": f"{settings.report_base_url}/success",
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
    async def create_web_tarot_payment(user_id: uuid.UUID) -> dict:
        idempotence_key = uuid.uuid4().hex[:32]
        payment = YooPayment.create(
            {
                "amount": {
                    "value": f"{settings.tarot_subscription_price_rub}.00",
                    "currency": "RUB",
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": f"{settings.report_base_url}/app/success",
                },
                "capture": True,
                "save_payment_method": True,
                "description": "NURA — Таро-практики (подписка)",
                "metadata": {
                    "user_id": str(user_id),
                    "payment_type": "web_tarot",
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
    async def create_recurring_payment(
        payment_method_id: str,
        amount_rub: int,
        description: str,
        metadata: dict,
    ) -> dict:
        idempotence_key = uuid.uuid4().hex[:32]
        payment = YooPayment.create(
            {
                "amount": {
                    "value": f"{amount_rub}.00",
                    "currency": "RUB",
                },
                "payment_method_id": payment_method_id,
                "confirmation": {
                    "type": "redirect",
                    "return_url": f"{settings.report_base_url}/success",
                },
                "capture": True,
                "description": description,
                "metadata": metadata,
            },
            idempotence_key,
        )
        return {
            "id": payment.id,
            "status": payment.status,
            "payment_method_id": payment_method_id,
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
        metadata = payment_obj.get("metadata") or {}
        telegram_id = metadata.get("telegram_id")
        payment_type = metadata.get("payment_type", "subscription")

        if settings.yookassa_verify_on_webhook and yookassa_id:
            try:
                remote = await asyncio.to_thread(
                    YooPayment.find_one, yookassa_id
                )
            except Exception:
                logger.warning(
                    "yookassa verification failed for payment %s, "
                    "ignoring webhook",
                    yookassa_id, exc_info=True,
                )
                return {"status": "ignored", "reason": "verification_unavailable"}
            remote_status = getattr(remote, "status", None)
            remote_paid = getattr(remote, "paid", None)
            if remote_status != "succeeded" or remote_paid is not True:
                logger.warning(
                    "yookassa verification mismatch for payment %s: "
                    "remote status=%r paid=%r, ignoring webhook",
                    yookassa_id, remote_status, remote_paid,
                )
                return {"status": "ignored", "reason": "not_succeeded"}

        if payment_type == "web_matrix":
            if not yookassa_id:
                logger.error("web_matrix webhook: missing yookassa_id, needs_review")
                return {"status": "needs_review", "detail": "Missing payment id"}

            user_id_str = metadata.get("user_id")
            if not user_id_str:
                logger.error("web_matrix webhook: missing user_id, needs_review")
                return {"status": "needs_review", "detail": "Missing user_id in web_matrix payment"}

            try:
                user_id = uuid.UUID(user_id_str)
            except (ValueError, AttributeError):
                logger.error(
                    "web_matrix webhook: invalid user_id=%r, needs_review", user_id_str
                )
                return {"status": "needs_review", "detail": "Invalid user_id format"}

            payment_repo = PaymentRepository(session_factory)
            user_repo = UserRepository(session_factory)

            payment = await payment_repo.get_by_yookassa_id(yookassa_id)
            if payment is None:
                raise ValueError("Payment not found")

            if payment.status == "succeeded":
                logger.info(
                    "web_matrix: idempotent skip — payment %s already succeeded "
                    "for user %s",
                    yookassa_id, payment.user_id,
                )
                return {"ok": True, "idempotent": True}

            if payment.user_id != user_id:
                logger.error(
                    "web_matrix: user_id mismatch — payment.user_id=%s vs "
                    "metadata.user_id=%s, yookassa_id=%s, needs_review",
                    payment.user_id, user_id, yookassa_id,
                )
                return {
                    "status": "needs_review",
                    "detail": "Payment user_id mismatch",
                }

            claimed = await payment_repo.claim_succeeded(yookassa_id)
            if claimed is None:
                logger.info(
                    "web_matrix: lost race for payment %s — already claimed "
                    "by concurrent webhook",
                    yookassa_id,
                )
                return {"ok": True, "idempotent": True}

            logger.info(
                "web_matrix: claimed payment %s for user %s, activating matrix",
                yookassa_id, user_id,
            )

            user = await user_repo.get(user_id)
            if user is None:
                logger.error(
                    "web_matrix: user %s not found after claim — "
                    "reverting payment %s, needs_review",
                    user_id, yookassa_id,
                )
                await payment_repo.update_status(payment.id, "pending")
                return {
                    "status": "needs_review",
                    "detail": "Web user not found",
                }

            try:
                await user_repo.update_has_matrix(user.id, True)
            except Exception:
                logger.error(
                    "web_matrix: update_has_matrix failed for user %s, "
                    "reverting payment %s to pending",
                    user_id, yookassa_id, exc_info=True,
                )
                await payment_repo.update_status(payment.id, "pending")
                raise

            logger.info(
                "web_matrix: matrix activated for user %s, payment %s",
                user_id, yookassa_id,
            )

            if user.birth_date:
                from core.services.report import ReportService
                from core.tasks import generate_full_report

                report_token = metadata.get("report_token") or ReportService.generate_token()
                try:
                    generate_full_report.delay(
                        str(user.id),
                        user.birth_date,
                        report_token,
                    )
                except Exception:
                    logger.error(
                        "web_matrix: generate_full_report.delay failed "
                        "for user %s, payment %s",
                        user.id, yookassa_id, exc_info=True,
                    )
            else:
                logger.warning(
                    "web_matrix: user %s has no birth_date — skipping report "
                    "generation for payment %s",
                    user_id, yookassa_id,
                )

            return {"ok": True}

        if payment_type == "web_tarot":
            if not yookassa_id:
                logger.error("web_tarot webhook: missing yookassa_id, needs_review")
                return {"status": "needs_review", "detail": "Missing payment id"}

            user_id_str = metadata.get("user_id")
            if not user_id_str:
                logger.error("web_tarot webhook: missing user_id, needs_review")
                return {
                    "status": "needs_review",
                    "detail": "Missing user_id in web_tarot payment",
                }

            try:
                user_id = uuid.UUID(user_id_str)
            except (ValueError, AttributeError):
                logger.error(
                    "web_tarot webhook: invalid user_id=%r, needs_review", user_id_str
                )
                return {"status": "needs_review", "detail": "Invalid user_id format"}

            payment_repo = PaymentRepository(session_factory)
            user_repo = UserRepository(session_factory)

            payment = await payment_repo.get_by_yookassa_id(yookassa_id)
            if payment is None:
                raise ValueError("Payment not found")

            if payment.status == "succeeded":
                logger.info(
                    "web_tarot: idempotent skip — payment %s already succeeded "
                    "for user %s",
                    yookassa_id, payment.user_id,
                )
                return {"ok": True, "idempotent": True}

            if payment.user_id != user_id:
                logger.error(
                    "web_tarot: user_id mismatch — payment.user_id=%s vs "
                    "metadata.user_id=%s, yookassa_id=%s, needs_review",
                    payment.user_id, user_id, yookassa_id,
                )
                return {
                    "status": "needs_review",
                    "detail": "Payment user_id mismatch",
                }

            claimed = await payment_repo.claim_succeeded(yookassa_id)
            if claimed is None:
                logger.info(
                    "web_tarot: lost race for payment %s — already claimed "
                    "by concurrent webhook",
                    yookassa_id,
                )
                return {"ok": True, "idempotent": True}

            logger.info(
                "web_tarot: claimed payment %s for user %s, activating tarot",
                yookassa_id, user_id,
            )

            user = await user_repo.get(user_id)
            if user is None:
                logger.error(
                    "web_tarot: user %s not found after claim — "
                    "reverting payment %s, needs_review",
                    user_id, yookassa_id,
                )
                await payment_repo.update_status(payment.id, "pending")
                return {
                    "status": "needs_review",
                    "detail": "Web user not found",
                }

            until = datetime.now(timezone.utc) + timedelta(days=30)
            try:
                await user_repo.update_tarot_subscription(user.id, True, until)
            except Exception:
                logger.error(
                    "web_tarot: update_tarot_subscription failed for user %s, "
                    "reverting payment %s to pending",
                    user_id, yookassa_id, exc_info=True,
                )
                await payment_repo.update_status(payment.id, "pending")
                raise

            logger.info(
                "web_tarot: subscription activated for user %s until %s, payment %s",
                user_id, until.isoformat(), yookassa_id,
            )

            return {"ok": True}

        if not telegram_id or not yookassa_id:
            logger.error(
                "telegram webhook: missing telegram_id=%r or yookassa_id=%r, "
                "needs_review",
                telegram_id, yookassa_id,
            )
            return {"status": "needs_review", "detail": "Missing telegram_id or payment id"}

        try:
            telegram_id_int = int(telegram_id)
        except (ValueError, TypeError):
            logger.error(
                "telegram webhook: invalid telegram_id=%r, needs_review", telegram_id
            )
            return {"status": "needs_review", "detail": "Invalid telegram_id format"}

        payment_repo = PaymentRepository(session_factory)
        user_repo = UserRepository(session_factory)

        payment = await payment_repo.get_by_yookassa_id(yookassa_id)
        if payment is None:
            raise ValueError("Payment not found")

        if payment.status == "succeeded":
            logger.info(
                "telegram: idempotent skip — payment %s already succeeded "
                "for telegram %s",
                yookassa_id, telegram_id_int,
            )
            return {"ok": True, "idempotent": True}

        claimed = await payment_repo.claim_succeeded(yookassa_id)
        if claimed is None:
            logger.info(
                "telegram: lost race for payment %s — already claimed "
                "by concurrent webhook",
                yookassa_id,
            )
            return {"ok": True, "idempotent": True}

        logger.info(
            "telegram: claimed payment %s for telegram %s, type=%s",
            yookassa_id, telegram_id_int, payment_type,
        )

        user = await user_repo.get_by_telegram_id(telegram_id_int)
        if user is None:
            logger.error(
                "telegram: user telegram_id=%s not found after claim — "
                "reverting payment %s, needs_review",
                telegram_id_int, yookassa_id,
            )
            await payment_repo.update_status(payment.id, "pending")
            return {
                "status": "needs_review",
                "detail": "User not found",
            }

        if payment.user_id != user.id:
            logger.error(
                "telegram: user_id mismatch — payment.user_id=%s vs "
                "user.id=%s (telegram=%s), yookassa_id=%s, needs_review",
                payment.user_id, user.id, telegram_id_int, yookassa_id,
            )
            await payment_repo.update_status(payment.id, "pending")
            return {
                "status": "needs_review",
                "detail": "Payment user_id mismatch",
            }

        until = datetime.now(timezone.utc) + timedelta(days=30)

        if payment_type == "tarot":
            try:
                await user_repo.update_tarot_subscription(user.id, True, until)
            except Exception:
                logger.error(
                    "telegram: update_tarot_subscription failed for user %s, "
                    "reverting payment %s to pending",
                    user.id, yookassa_id, exc_info=True,
                )
                await payment_repo.update_status(payment.id, "pending")
                raise

            logger.info(
                "telegram: tarot activated for user %s until %s, payment %s",
                user.id, until.isoformat(), yookassa_id,
            )

        elif payment_type == "matrix":
            try:
                await user_repo.update_has_matrix(user.id, True)
            except Exception:
                logger.error(
                    "telegram: update_has_matrix failed for user %s, "
                    "reverting payment %s to pending",
                    user.id, yookassa_id, exc_info=True,
                )
                await payment_repo.update_status(payment.id, "pending")
                raise

            logger.info(
                "telegram: matrix activated for user %s, payment %s",
                user.id, yookassa_id,
            )

            if user.birth_date:
                from core.services.report import ReportService
                from core.tasks import generate_full_report

                report_token = ReportService.generate_token()
                try:
                    generate_full_report.delay(
                        str(user.id),
                        user.birth_date,
                        report_token,
                    )
                except Exception:
                    logger.error(
                        "telegram: generate_full_report.delay failed "
                        "for user %s, payment %s",
                        user.id, yookassa_id, exc_info=True,
                    )
            else:
                logger.warning(
                    "telegram: user %s has no birth_date — skipping report "
                    "generation for payment %s",
                    user.id, yookassa_id,
                )

            try:
                from core.tasks import _send_message as send_msg

                await send_msg(
                    user.telegram_id,
                    "✦ Оплата прошла успешно!\n\n"
                    "Генерирую твою Матрицу Судьбы...\n"
                    "Это займёт 1-2 минуты.",
                )
            except Exception:
                logger.error(
                    "telegram: send_msg failed for user %s, payment %s",
                    user.id, yookassa_id, exc_info=True,
                )

        else:
            try:
                await user_repo.update_subscription(user.id, "premium", until)
            except Exception:
                logger.error(
                    "telegram: update_subscription failed for user %s, "
                    "reverting payment %s to pending",
                    user.id, yookassa_id, exc_info=True,
                )
                await payment_repo.update_status(payment.id, "pending")
                raise

            logger.info(
                "telegram: subscription activated for user %s until %s, payment %s",
                user.id, until.isoformat(), yookassa_id,
            )

        return {"ok": True}
