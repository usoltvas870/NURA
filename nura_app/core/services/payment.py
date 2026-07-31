import asyncio
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker
from yookassa import Configuration, Payment as YooPayment

from core.config import settings
from core.models import Payment as PaymentModel
from core.repositories.payment import PaymentRepository
from core.repositories.promo import PromoCodeRepository
from core.repositories.promo_reservation import PromoReservationRepository
from core.repositories.user import UserRepository
from core.services.report_lifecycle import ReportLifecycleCoordinator

logger = logging.getLogger(__name__)

Configuration.account_id = settings.yookassa_shop_id
Configuration.secret_key = settings.yookassa_secret_key


@dataclass(frozen=True)
class CheckoutAmount:
    product: Literal["web_matrix", "web_tarot"]
    base_amount_kopecks: int
    discount_amount_kopecks: int
    discount_percent: int
    final_amount_kopecks: int
    currency: Literal["RUB"]
    promo_code_id: uuid.UUID | None = None
    promo_code: str | None = None


class PromoCheckoutError(ValueError):
    def __init__(self, reason: Literal["invalid", "expired", "exhausted"]):
        self.reason = reason
        super().__init__(reason)


class PaymentService:
    @staticmethod
    def _require_payments_enabled() -> None:
        if settings.is_sandbox:
            raise RuntimeError("legacy_payments_disabled_for_external_sandbox")
        if not settings.payments_enabled:
            raise RuntimeError("payments_disabled_for_telegram_pilot")

    @staticmethod
    def _web_product_base_amount(
        product: Literal["web_matrix", "web_tarot"],
    ) -> int:
        if product == "web_matrix":
            return settings.matrix_one_time_price_rub
        if product == "web_tarot":
            return settings.tarot_subscription_price_rub
        raise ValueError("Unsupported web payment product")

    @staticmethod
    def _yookassa_amount(amount_kopecks: int) -> dict[str, str]:
        if isinstance(amount_kopecks, bool) or amount_kopecks <= 0:
            raise ValueError("Invalid payment amount")
        rubles, kopecks = divmod(amount_kopecks, 100)
        return {"value": f"{rubles}.{kopecks:02d}", "currency": "RUB"}

    @staticmethod
    async def resolve_web_checkout_amount(
        session_factory: async_sessionmaker,
        *,
        product: Literal["web_matrix", "web_tarot"],
        promo_code: str | None,
    ) -> CheckoutAmount:
        """Resolve the immutable server-side amount for a web checkout."""
        base_amount_kopecks = PaymentService._web_product_base_amount(product) * 100
        if not promo_code:
            return CheckoutAmount(
                product=product,
                base_amount_kopecks=base_amount_kopecks,
                discount_amount_kopecks=0,
                discount_percent=0,
                final_amount_kopecks=base_amount_kopecks,
                currency="RUB",
            )

        normalized_code = promo_code.strip().upper()
        promo = await PromoCodeRepository(session_factory).get_by_code(normalized_code)
        if promo is None or not promo.is_active:
            raise PromoCheckoutError("invalid")
        if promo.expires_at is not None:
            expires_at = promo.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < datetime.now(timezone.utc):
                raise PromoCheckoutError("expired")
        if not 0 < promo.discount_percent < 100:
            raise PromoCheckoutError("invalid")

        final_amount_kopecks = (
            base_amount_kopecks * (100 - promo.discount_percent) // 100
        )
        discount_amount_kopecks = base_amount_kopecks - final_amount_kopecks
        if final_amount_kopecks <= 0:
            raise PromoCheckoutError("invalid")
        return CheckoutAmount(
            product=product,
            base_amount_kopecks=base_amount_kopecks,
            discount_amount_kopecks=discount_amount_kopecks,
            discount_percent=promo.discount_percent,
            final_amount_kopecks=final_amount_kopecks,
            currency="RUB",
            promo_code_id=promo.id,
            promo_code=promo.code,
        )

    @staticmethod
    @staticmethod
    def _provider_verification_required() -> bool:
        """Production never accepts a webhook payload as proof of payment."""
        return settings.is_production or settings.yookassa_verify_on_webhook

    @staticmethod
    def _verified_remote_matches_payment(remote: object, payment: PaymentModel) -> bool:
        """Require the provider amount and currency to match the local intent."""
        remote_amount = getattr(remote, "amount", None)
        remote_value = getattr(remote_amount, "value", None)
        remote_currency = getattr(remote_amount, "currency", None)
        try:
            remote_money = Decimal(str(remote_value))
        except (InvalidOperation, TypeError, ValueError):
            return False
        expected_kopecks = payment.amount_kopecks
        if expected_kopecks is None:
            expected_kopecks = payment.amount * 100
        expected_money = Decimal(expected_kopecks) / Decimal(100)
        return (
            remote_money == expected_money
            and remote_money.as_tuple().exponent == -2
            and remote_currency == "RUB"
        )

    @staticmethod
    async def _consume_promo_for_claim(
        session_factory: async_sessionmaker,
        payment_repo: PaymentRepository,
        payment: PaymentModel,
    ) -> bool:
        reservation = await PromoReservationRepository(session_factory).get_by_payment_id(
            payment.id
        )
        if reservation is not None:
            if (
                reservation.user_id != payment.user_id
                or reservation.payment_type != payment.payment_type
                or reservation.promo_code_id != payment.promo_code_id
            ):
                return False
            await PromoReservationRepository(session_factory).mark_consumed(reservation.id)
            await payment_repo.mark_promo_consumed_without_accounting(payment.id)
            return True
        return await payment_repo.consume_promo(payment.id)

    @staticmethod
    async def _reservation_matches_verified_metadata(
        session_factory: async_sessionmaker,
        payment: PaymentModel,
        metadata: dict,
    ) -> bool:
        reservation = await PromoReservationRepository(session_factory).get_by_payment_id(
            payment.id
        )
        if reservation is None:
            return True
        if (
            reservation.user_id != payment.user_id
            or reservation.payment_type != payment.payment_type
            or reservation.promo_code_id != payment.promo_code_id
        ):
            return False
        if payment.payment_type == "web_matrix":
            return reservation.report_token == metadata.get("report_token")
        return reservation.report_token is None

    @staticmethod
    async def _revert_claim(
        payment_repo: PaymentRepository,
        payment: PaymentModel,
    ) -> None:
        await payment_repo.release_consumed_promo(payment.id)
        await payment_repo.update_status(payment.id, "pending")

    @staticmethod
    async def create_subscription(
        telegram_id: int,
        *,
        idempotence_key: str | None = None,
    ) -> dict:
        PaymentService._require_payments_enabled()
        idempotence_key = idempotence_key or uuid.uuid4().hex[:32]
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
                    "payment_type": "subscription",
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
    async def create_tarot_payment(
        telegram_id: int,
        *,
        idempotence_key: str | None = None,
    ) -> dict:
        PaymentService._require_payments_enabled()
        idempotence_key = idempotence_key or uuid.uuid4().hex[:32]
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
    async def create_telegram_payment(
        session_factory: async_sessionmaker,
        *,
        user_id: uuid.UUID,
        telegram_id: int,
        payment_type: Literal["subscription", "tarot"],
        idempotence_key: str,
    ) -> dict:
        """Create and persist a Telegram checkout before exposing its URL."""
        if payment_type == "subscription":
            provider_payment = await PaymentService.create_subscription(
                telegram_id,
                idempotence_key=idempotence_key,
            )
        elif payment_type == "tarot":
            provider_payment = await PaymentService.create_tarot_payment(
                telegram_id,
                idempotence_key=idempotence_key,
            )
        else:
            raise ValueError("Unsupported Telegram payment type")

        provider_payment_id = provider_payment.get("id")
        payment_url = provider_payment.get("payment_url")
        if not isinstance(provider_payment_id, str) or not isinstance(payment_url, str):
            raise RuntimeError("Invalid provider payment response")

        payment_repo = PaymentRepository(session_factory)
        try:
            await payment_repo.create(
                user_id=user_id,
                amount=settings.tarot_subscription_price_rub,
                yookassa_id=provider_payment_id,
                payment_type=payment_type,
            )
        except Exception:
            existing = await payment_repo.get_by_yookassa_id(provider_payment_id)
            if (
                existing is not None
                and existing.user_id == user_id
                and existing.payment_type == payment_type
                and existing.amount == settings.tarot_subscription_price_rub
            ):
                return provider_payment
            raise

        return provider_payment

    @staticmethod
    async def create_matrix_payment(telegram_id: int) -> dict:
        PaymentService._require_payments_enabled()
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
        user_id: uuid.UUID,
        report_token: str,
        checkout_amount: CheckoutAmount,
        *,
        idempotence_key: str | None = None,
    ) -> dict:
        PaymentService._require_payments_enabled()
        if checkout_amount.product != "web_matrix":
            raise ValueError("Invalid checkout amount product")
        idempotence_key = idempotence_key or uuid.uuid4().hex[:32]
        payment = YooPayment.create(
            {
                "amount": PaymentService._yookassa_amount(
                    checkout_amount.final_amount_kopecks
                ),
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
    async def create_web_tarot_payment(
        user_id: uuid.UUID,
        checkout_amount: CheckoutAmount,
        *,
        idempotence_key: str | None = None,
    ) -> dict:
        PaymentService._require_payments_enabled()
        if checkout_amount.product != "web_tarot":
            raise ValueError("Invalid checkout amount product")
        idempotence_key = idempotence_key or uuid.uuid4().hex[:32]
        payment = YooPayment.create(
            {
                "amount": PaymentService._yookassa_amount(
                    checkout_amount.final_amount_kopecks
                ),
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
        PaymentService._require_payments_enabled()
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
        PaymentService._require_payments_enabled()
        from yookassa import PaymentMethod as YooPaymentMethod

        YooPaymentMethod.cancel(payment_method_id)

    @staticmethod
    async def _process_verified_matrix_webhook(
        session_factory: async_sessionmaker,
        *,
        provider_payment_id: str,
        metadata: dict,
        verified_remote: object | None,
    ) -> dict:
        user_id_raw = metadata.get("user_id")
        report_token = metadata.get("report_token")
        if not isinstance(provider_payment_id, str) or not provider_payment_id:
            return {"status": "needs_review", "detail": "Missing payment id"}
        if not isinstance(user_id_raw, str) or not isinstance(report_token, str):
            return {"status": "needs_review", "detail": "Matrix mapping unavailable"}
        try:
            user_id = uuid.UUID(user_id_raw)
        except (ValueError, AttributeError):
            return {"status": "needs_review", "detail": "Matrix mapping unavailable"}

        payment = await PaymentRepository(session_factory).get_by_yookassa_id(
            provider_payment_id
        )
        if payment is None:
            logger.warning("payment_not_found")
            return {"status": "ignored", "reason": "payment_not_found"}
        if payment.payment_type != "web_matrix":
            return {"status": "needs_review", "detail": "Payment type mismatch"}
        if verified_remote is not None and not PaymentService._verified_remote_matches_payment(
            verified_remote, payment
        ):
            return {"status": "ignored", "reason": "amount_or_currency_mismatch"}

        try:
            async with session_factory() as session:
                outcome = await ReportLifecycleCoordinator(
                    session
                ).activate_verified_matrix_payment(
                    provider_payment_id=provider_payment_id,
                    verified_user_id=user_id,
                    verified_report_token=report_token,
                    confirmed_at=datetime.now(timezone.utc),
                )
                await session.commit()
        except ValueError:
            return {"status": "needs_review", "detail": "Matrix lifecycle conflict"}
        except Exception:
            logger.error("matrix_lifecycle_transaction_failed")
            return {"status": "needs_review", "detail": "Matrix activation unavailable"}
        if outcome == "idempotent":
            return {"ok": True, "idempotent": True}
        return {"ok": True}

    @staticmethod
    async def process_webhook(
        session_factory: async_sessionmaker, data: dict
    ) -> dict:
        PaymentService._require_payments_enabled()
        event = data.get("event")
        payment_obj = data.get("object", {})

        if event != "payment.succeeded":
            return {"status": "ignored"}

        yookassa_id = payment_obj.get("id")
        metadata = payment_obj.get("metadata") or {}
        verified_remote: object | None = None

        if PaymentService._provider_verification_required():
            if not isinstance(yookassa_id, str) or not yookassa_id:
                return {"status": "ignored", "reason": "verification_unavailable"}
            try:
                verified_remote = await asyncio.to_thread(
                    YooPayment.find_one, yookassa_id
                )
            except Exception:
                logger.warning("payment_verification_failed")
                return {"status": "ignored", "reason": "verification_unavailable"}
            remote_status = getattr(verified_remote, "status", None)
            remote_paid = getattr(verified_remote, "paid", None)
            remote_id = getattr(verified_remote, "id", None)
            if (
                remote_status != "succeeded"
                or remote_paid is not True
                or remote_id != yookassa_id
            ):
                logger.warning("provider_state_not_successful")
                return {"status": "ignored", "reason": "not_succeeded"}
            # Webhook bodies are untrusted transport data.  The provider's
            # verified object is the only source for ownership and type.
            remote_metadata = getattr(verified_remote, "metadata", None)
            if not isinstance(remote_metadata, dict):
                logger.warning("payment_verification_metadata_missing")
                return {"status": "ignored", "reason": "invalid_provider_response"}
            metadata = remote_metadata

        if not isinstance(metadata, dict):
            return {"status": "ignored", "reason": "invalid_provider_response"}
        telegram_id = metadata.get("telegram_id")
        payment_type = metadata.get("payment_type", "subscription")

        if payment_type == "web_matrix":
            return await PaymentService._process_verified_matrix_webhook(
                session_factory,
                provider_payment_id=yookassa_id,
                metadata=metadata,
                verified_remote=verified_remote,
            )
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
                    "payment_webhook_invalid_user_mapping"
                )
                return {"status": "needs_review", "detail": "Invalid user_id format"}

            payment_repo = PaymentRepository(session_factory)
            user_repo = UserRepository(session_factory)

            payment = await payment_repo.get_by_yookassa_id(yookassa_id)
            if payment is None:
                logger.warning("payment_not_found")
                return {"status": "ignored", "reason": "payment_not_found"}
            if payment.payment_type != payment_type:
                return {"status": "needs_review", "detail": "Payment type mismatch"}
            if verified_remote is not None and not PaymentService._verified_remote_matches_payment(
                verified_remote, payment
            ):
                return {"status": "ignored", "reason": "amount_or_currency_mismatch"}
            if not await PaymentService._reservation_matches_verified_metadata(
                session_factory, payment, metadata
            ):
                return {"status": "needs_review", "detail": "Reservation mismatch"}

            if payment.status == "succeeded":
                logger.info(
                    "web_matrix: idempotent skip — payment %s already succeeded "
                    "for user %s",
                )
                return {"ok": True, "idempotent": True}

            if payment.user_id != user_id:
                logger.error(
                    "web_matrix: user_id mismatch — payment.user_id=%s vs "
                    "metadata.user_id=%s, yookassa_id=%s, needs_review",
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
                )
                return {"ok": True, "idempotent": True}
            logger.info(
                "web_matrix: claimed payment %s for user %s, activating matrix",
            )

            user = await user_repo.get(user_id)
            if user is None:
                logger.error(
                    "web_matrix: user %s not found after claim — "
                    "reverting payment %s, needs_review",
                )
                await PaymentService._revert_claim(payment_repo, payment)
                return {
                    "status": "needs_review",
                    "detail": "Web user not found",
                }

            previous_has_matrix = user.has_matrix
            try:
                await user_repo.update_has_matrix(user.id, True)
            except Exception:
                logger.error(
                    "web_matrix: update_has_matrix failed for user %s, "
                    "reverting payment %s to pending",
                )
                await PaymentService._revert_claim(payment_repo, payment)
                raise

            logger.info(
                "web_matrix: matrix activated for user %s, payment %s",
            )
            if not await PaymentService._consume_promo_for_claim(
                session_factory, payment_repo, claimed
            ):
                await user_repo.update_has_matrix(user.id, previous_has_matrix)
                await payment_repo.update_status(claimed.id, "pending")
                return {"status": "needs_review", "detail": "Promo usage unavailable"}

            if user.birth_date:
                from core.services.report import ReportService
                from core.tasks import active_report_prompt_identity, generate_full_report

                report_token = metadata.get("report_token") or ReportService.generate_token()
                try:
                    pass
                except Exception:
                    logger.error(
                        "web_matrix: generate_full_report.delay failed "
                        "for user %s, payment %s",
                    )
            else:
                logger.warning(
                    "web_matrix: user %s has no birth_date — skipping report "
                    "generation for payment %s",
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
                    "payment_webhook_invalid_user_mapping"
                )
                return {"status": "needs_review", "detail": "Invalid user_id format"}

            payment_repo = PaymentRepository(session_factory)
            user_repo = UserRepository(session_factory)

            payment = await payment_repo.get_by_yookassa_id(yookassa_id)
            if payment is None:
                logger.warning("payment_not_found")
                return {"status": "ignored", "reason": "payment_not_found"}
            if payment.payment_type != payment_type:
                return {"status": "needs_review", "detail": "Payment type mismatch"}
            if verified_remote is not None and not PaymentService._verified_remote_matches_payment(
                verified_remote, payment
            ):
                return {"status": "ignored", "reason": "amount_or_currency_mismatch"}
            if not await PaymentService._reservation_matches_verified_metadata(
                session_factory, payment, metadata
            ):
                return {"status": "needs_review", "detail": "Reservation mismatch"}

            if payment.status == "succeeded":
                logger.info(
                    "web_tarot: idempotent skip — payment %s already succeeded "
                    "for user %s",
                )
                return {"ok": True, "idempotent": True}

            if payment.user_id != user_id:
                logger.error(
                    "web_tarot: user_id mismatch — payment.user_id=%s vs "
                    "metadata.user_id=%s, yookassa_id=%s, needs_review",
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
                )
                return {"ok": True, "idempotent": True}
            logger.info(
                "web_tarot: claimed payment %s for user %s, activating tarot",
            )

            user = await user_repo.get(user_id)
            if user is None:
                logger.error(
                    "web_tarot: user %s not found after claim — "
                    "reverting payment %s, needs_review",
                )
                await PaymentService._revert_claim(payment_repo, payment)
                return {
                    "status": "needs_review",
                    "detail": "Web user not found",
                }

            previous_tarot_subscription = user.tarot_subscription
            previous_tarot_until = user.tarot_subscription_until
            until = datetime.now(timezone.utc) + timedelta(days=30)
            try:
                await user_repo.update_tarot_subscription(user.id, True, until)
            except Exception:
                logger.error(
                    "web_tarot: update_tarot_subscription failed for user %s, "
                    "reverting payment %s to pending",
                )
                await PaymentService._revert_claim(payment_repo, payment)
                raise

            logger.info(
                "web_tarot: subscription activated for user %s until %s, payment %s",
            )
            if not await PaymentService._consume_promo_for_claim(
                session_factory, payment_repo, claimed
            ):
                await user_repo.update_tarot_subscription(
                    user.id, previous_tarot_subscription, previous_tarot_until
                )
                await payment_repo.update_status(claimed.id, "pending")
                return {"status": "needs_review", "detail": "Promo usage unavailable"}

            return {"ok": True}

        if not telegram_id or not yookassa_id:
            logger.error(
                "telegram webhook: missing telegram_id=%r or yookassa_id=%r, "
                "needs_review",
            )
            return {"status": "needs_review", "detail": "Missing telegram_id or payment id"}

        try:
            telegram_id_int = int(telegram_id)
        except (ValueError, TypeError):
            logger.error(
                "payment_webhook_invalid_telegram_mapping"
            )
            return {"status": "needs_review", "detail": "Invalid telegram_id format"}

        payment_repo = PaymentRepository(session_factory)
        user_repo = UserRepository(session_factory)

        payment = await payment_repo.get_by_yookassa_id(yookassa_id)
        if payment is None:
            raise ValueError("Payment not found")
        if payment.payment_type != payment_type:
            return {"status": "needs_review", "detail": "Payment type mismatch"}
        if verified_remote is not None and not PaymentService._verified_remote_matches_payment(
            verified_remote, payment
        ):
            return {"status": "ignored", "reason": "amount_or_currency_mismatch"}

        if payment.status == "succeeded":
            logger.info(
                "telegram: idempotent skip — payment %s already succeeded "
                "for telegram %s",
            )
            return {"ok": True, "idempotent": True}

        claimed = await payment_repo.claim_succeeded(yookassa_id)
        if claimed is None:
            logger.info(
                "telegram: lost race for payment %s — already claimed "
                "by concurrent webhook",
            )
            return {"ok": True, "idempotent": True}
        if not await PaymentService._consume_promo_for_claim(
            session_factory, payment_repo, claimed
        ):
            await PaymentService._revert_claim(payment_repo, payment)
            return {"status": "needs_review", "detail": "Promo usage unavailable"}

        logger.info(
            "telegram: claimed payment %s for telegram %s, type=%s",
        )

        user = await user_repo.get_by_telegram_id(telegram_id_int)
        if user is None:
            logger.error(
                "telegram: user telegram_id=%s not found after claim — "
                "reverting payment %s, needs_review",
            )
            await PaymentService._revert_claim(payment_repo, payment)
            return {
                "status": "needs_review",
                "detail": "User not found",
            }

        if payment.user_id != user.id:
            logger.error(
                "telegram: user_id mismatch — payment.user_id=%s vs "
                "user.id=%s (telegram=%s), yookassa_id=%s, needs_review",
            )
            await PaymentService._revert_claim(payment_repo, payment)
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
                )
                await PaymentService._revert_claim(payment_repo, payment)
                raise

            logger.info(
                "telegram: tarot activated for user %s until %s, payment %s",
            )

        elif payment_type == "matrix":
            try:
                await user_repo.update_has_matrix(user.id, True)
            except Exception:
                logger.error(
                    "telegram: update_has_matrix failed for user %s, "
                    "reverting payment %s to pending",
                )
                await PaymentService._revert_claim(payment_repo, payment)
                raise

            logger.info(
                "telegram: matrix activated for user %s, payment %s",
            )

            if user.birth_date:
                from core.services.report import ReportService
                from core.tasks import active_report_prompt_identity, generate_full_report

                report_token = ReportService.generate_token()
                try:
                    prompt_version, prompt_hash = active_report_prompt_identity()
                    generate_full_report.delay(
                        str(user.id),
                        user.birth_date,
                        report_token,
                        prompt_version,
                        prompt_hash,
                    )
                except Exception:
                    logger.error(
                        "telegram: generate_full_report.delay failed "
                        "for user %s, payment %s",
                    )
            else:
                logger.warning(
                    "telegram: user %s has no birth_date — skipping report "
                    "generation for payment %s",
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
                )

        else:
            try:
                await user_repo.update_subscription(user.id, "premium", until)
            except Exception:
                logger.error(
                    "telegram: update_subscription failed for user %s, "
                    "reverting payment %s to pending",
                )
                await PaymentService._revert_claim(payment_repo, payment)
                raise

            logger.info(
                "telegram: subscription activated for user %s until %s, payment %s",
            )

        return {"ok": True}
