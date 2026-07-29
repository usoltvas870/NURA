"""One-time full Matrix checkout bounded to YooKassa.

The service owns the new order/attempt/event lifecycle.  Legacy ``Payment``
remains deliberately untouched for subscriptions and historical checkouts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
import re
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from core.models import (
    Order,
    OrderStatus,
    PaymentAttempt,
    PaymentEvent,
    Report,
    ReportGenerationState,
    ReportPaymentState,
    ReportType,
    User,
)
from core.repositories.payment_event import PaymentEventRepository
from core.repositories.report_lifecycle import ReportLifecycleRepository
from core.services.report_lifecycle import ReportLifecycleService


FULL_MATRIX_PRODUCT_CODE = "full_matrix"
FULL_MATRIX_AMOUNT_KOPECKS = 89_000
FULL_MATRIX_CURRENCY = "RUB"
FULL_MATRIX_WEBHOOK_EVENTS = frozenset(
    {"payment.succeeded", "payment.canceled", "refund.succeeded"}
)
FULL_MATRIX_PRODUCT_NAME = "Полная Матрица судьбы"
FULL_MATRIX_AMOUNT_VALUE = "890.00"
CHECKOUT_TOKEN_TTL = timedelta(minutes=30)
RETAIN_YEARS = 5
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}$")


class YooKassaProvider(Protocol):
    async def create_payment(self, *, idempotency_key: str, payload: dict) -> dict: ...

    async def get_payment(self, provider_payment_id: str) -> dict: ...

    async def get_refund(self, provider_refund_id: str) -> dict: ...


class ProductionYooKassaProvider:
    """Thin adapter; application code never calls the SDK directly."""

    async def create_payment(self, *, idempotency_key: str, payload: dict) -> dict:
        from yookassa import Configuration, Payment as YooPayment

        Configuration.account_id = settings.yookassa_shop_id
        Configuration.secret_key = settings.yookassa_secret_key
        payment = await asyncio.to_thread(YooPayment.create, payload, idempotency_key)
        return payment.json()

    async def get_payment(self, provider_payment_id: str) -> dict:
        from yookassa import Configuration, Payment as YooPayment

        Configuration.account_id = settings.yookassa_shop_id
        Configuration.secret_key = settings.yookassa_secret_key
        payment = await asyncio.to_thread(YooPayment.find_one, provider_payment_id)
        return payment.json()

    async def get_refund(self, provider_refund_id: str) -> dict:
        from yookassa import Configuration, Refund as YooRefund

        Configuration.account_id = settings.yookassa_shop_id
        Configuration.secret_key = settings.yookassa_secret_key
        refund = await asyncio.to_thread(YooRefund.find_one, provider_refund_id)
        return refund.json()


@dataclass(frozen=True)
class CheckoutOrderResult:
    checkout_token: str | None
    status: str


@dataclass(frozen=True)
class EventIntake:
    event_id: uuid.UUID
    outcome: str
    expected_attempt_count: int | None
    provider_id: str
    provider_object_id: str
    event_type: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _retain_until(now: datetime) -> datetime:
    return now + timedelta(days=365 * RETAIN_YEARS)


def _is_expired(value: datetime | None) -> bool:
    if value is None:
        return True
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= _now()


def _attempt_key(order: Order, number: int) -> str:
    return hashlib.sha256(f"nura.full-matrix.yookassa.v1|{order.public_id}|{number}".encode()).hexdigest()


def normalize_fiscal_email(value: str) -> str:
    """Validate a receipt-only email without creating an email identity."""
    if not isinstance(value, str):
        raise ValueError("checkout_email_invalid")
    email = value.strip().lower()
    _, parsed = parseaddr(email)
    if parsed != email or not _EMAIL_RE.fullmatch(email):
        raise ValueError("checkout_email_invalid")
    return email


def _payload_fingerprint(remote: dict) -> str:
    """Hash a minimal, non-PII provider projection for duplicate-event audit."""
    metadata = remote.get("metadata") if isinstance(remote.get("metadata"), dict) else {}
    projection = {
        "id": remote.get("id"),
        "status": remote.get("status"),
        "paid": remote.get("paid"),
        "amount": remote.get("amount"),
        "metadata": {"product_code": metadata.get("product_code"), "order_id": metadata.get("order_id")},
    }
    canonical = json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _notification_fingerprint(body: dict, provider_id: str, event_type: str) -> str:
    obj = body.get("object") if isinstance(body.get("object"), dict) else {}
    projection = {
        "event": event_type,
        "object_id": provider_id,
        "object_status": obj.get("status") if isinstance(obj.get("status"), str) else None,
        "payment_id": obj.get("payment_id") if isinstance(obj.get("payment_id"), str) else None,
    }
    return hashlib.sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest()


class FullMatrixCheckoutService:
    def __init__(self, session_factory: async_sessionmaker, provider: YooKassaProvider | None = None):
        self._session_factory = session_factory
        self._provider = provider or ProductionYooKassaProvider()

    @staticmethod
    def _require_payments_enabled() -> None:
        if not settings.payments_enabled:
            raise ValueError("payments_disabled_for_telegram_pilot")

    async def create_or_get_order(self, *, user_id: uuid.UUID) -> CheckoutOrderResult:
        """Create one active server-priced order for the Telegram identity."""
        self._require_payments_enabled()
        async with self._session_factory() as session:
            user = await session.get(User, user_id, with_for_update=True)
            if user is None:
                raise ValueError("checkout_user_not_found")
            existing = (
                await session.execute(
                    select(Order)
                    .where(Order.user_id == user_id, Order.status.in_([OrderStatus.CREATED, OrderStatus.PENDING]))
                    .order_by(Order.created_at.desc())
                    .with_for_update()
                )
            ).scalars().first()
            now = _now()
            if existing is not None:
                if (
                    existing.checkout_token is None
                    or existing.checkout_expires_at is None
                    or _is_expired(existing.checkout_expires_at)
                ):
                    existing.checkout_token = secrets.token_urlsafe(32)
                    existing.checkout_expires_at = now + CHECKOUT_TOKEN_TTL
                await session.commit()
                return CheckoutOrderResult(existing.checkout_token, existing.status)
            paid = (
                await session.execute(
                    select(Order)
                    .where(Order.user_id == user_id, Order.status == OrderStatus.PAID)
                    .order_by(Order.paid_at.desc())
                    .with_for_update()
                )
            ).scalars().first()
            if paid is not None:
                await session.commit()
                return CheckoutOrderResult(None, OrderStatus.PAID)
            order = Order(
                id=uuid.uuid4(),
                public_id=secrets.token_urlsafe(32),
                checkout_token=secrets.token_urlsafe(32),
                checkout_expires_at=now + CHECKOUT_TOKEN_TTL,
                user_id=user.id,
                telegram_id_snapshot=user.telegram_id,
                product_code=FULL_MATRIX_PRODUCT_CODE,
                amount_kopecks=FULL_MATRIX_AMOUNT_KOPECKS,
                currency=FULL_MATRIX_CURRENCY,
                idempotency_key=secrets.token_hex(32),
                retain_until=_retain_until(now),
            )
            session.add(order)
            await session.commit()
            return CheckoutOrderResult(order.checkout_token, order.status)

    async def checkout_page_is_available(self, checkout_token: str) -> bool:
        """Resolve the opaque browser capability before rendering checkout."""
        async with self._session_factory() as session:
            order = await self._get_order_by_checkout_token(
                session, checkout_token, lock=False
            )
            return bool(
                order is not None
                and order.user_id is not None
                and order.status in {OrderStatus.CREATED, OrderStatus.PENDING}
                and not _is_expired(order.checkout_expires_at)
            )

    async def start_checkout(self, checkout_token: str, fiscal_email: str) -> str:
        """Create/reuse a YooKassa attempt.  Client controls neither product nor amount."""
        self._require_payments_enabled()
        fiscal_email = normalize_fiscal_email(fiscal_email)
        receipt_error = settings.yookassa_receipt_configuration_error
        if receipt_error:
            raise ValueError(receipt_error)
        async with self._session_factory() as session:
            order = await self._get_order_by_checkout_token(session, checkout_token, lock=True)
            if order is None or order.status in {OrderStatus.PAID, OrderStatus.REFUNDED}:
                raise ValueError("checkout_not_available")
            if order.user_id is None:
                raise ValueError("checkout_anonymized")
            if _is_expired(order.checkout_expires_at):
                raise ValueError("checkout_expired")
            attempt = await self._get_active_attempt(session, order.id)
            if attempt is not None and attempt.status == "pending" and attempt.confirmation_url:
                if attempt.fiscal_email != fiscal_email:
                    raise ValueError("checkout_email_conflict")
                await session.commit()
                return attempt.confirmation_url
            attempt_count = len((await session.execute(select(PaymentAttempt.id).where(PaymentAttempt.order_id == order.id))).scalars().all())
            idempotency_key = _attempt_key(order, attempt_count + 1)
            public_id = order.public_id
            product_code = order.product_code
            amount_kopecks = order.amount_kopecks
            currency = order.currency
            if (
                product_code != FULL_MATRIX_PRODUCT_CODE
                or amount_kopecks != FULL_MATRIX_AMOUNT_KOPECKS
                or currency != FULL_MATRIX_CURRENCY
            ):
                raise ValueError("receipt_item_mismatch")
            payload = {
                "amount": {"value": FULL_MATRIX_AMOUNT_VALUE, "currency": FULL_MATRIX_CURRENCY},
                "confirmation": {"type": "redirect", "return_url": f"{settings.report_base_url}/api/v1/payment/full-matrix/return/{checkout_token}"},
                "capture": True,
                "save_payment_method": False,
                "description": FULL_MATRIX_PRODUCT_NAME,
                "receipt": {"customer": {"email": fiscal_email}, "items": [{
                    "description": FULL_MATRIX_PRODUCT_NAME, "quantity": "1.00",
                    "amount": {"value": FULL_MATRIX_AMOUNT_VALUE, "currency": FULL_MATRIX_CURRENCY},
                    "vat_code": settings.yookassa_receipt_vat_code,
                    "payment_mode": settings.yookassa_receipt_payment_mode,
                    "payment_subject": settings.yookassa_receipt_payment_subject,
                }]},
                "metadata": {"product_code": FULL_MATRIX_PRODUCT_CODE, "order_id": public_id},
            }
            remote = await self._provider.create_payment(idempotency_key=idempotency_key, payload=payload)
            provider_id, confirmation_url = self._validate_create_response(remote)
            now = _now()
            attempt = PaymentAttempt(
                id=uuid.uuid4(), order_id=order.id, provider="yookassa",
                provider_payment_id=provider_id, idempotency_key=idempotency_key,
                status="pending", amount_kopecks=FULL_MATRIX_AMOUNT_KOPECKS,
                currency=FULL_MATRIX_CURRENCY, confirmation_url=confirmation_url,
                fiscal_email=fiscal_email,
                provider_metadata={"product_code": FULL_MATRIX_PRODUCT_CODE, "order_id": public_id},
                test_mode=bool(settings.test_mode), retain_until=_retain_until(now),
            )
            session.add(attempt)
            await session.flush()
            order.active_payment_id = attempt.id
            order.status = OrderStatus.PENDING
            order.canceled_at = None
            order.payment_started_at = now
            await session.commit()
            return confirmation_url

    async def process_webhook(self, body: dict) -> dict:
        """Claim the durable event before exactly one worker reads the provider."""
        event_type = body.get("event") if isinstance(body.get("event"), str) else "unknown"
        if event_type not in FULL_MATRIX_WEBHOOK_EVENTS:
            return {"status": "ok", "result": "unsupported_event"}
        obj = body.get("object") if isinstance(body, dict) else None
        provider_object_id = obj.get("id") if isinstance(obj, dict) else None
        provider_id = (
            obj.get("payment_id")
            if event_type == "refund.succeeded" and isinstance(obj, dict)
            else provider_object_id
        )
        if (
            not isinstance(provider_object_id, str)
            or not provider_object_id
            or len(provider_object_id) > 100
            or not isinstance(provider_id, str)
            or not provider_id
            or len(provider_id) > 100
        ):
            raise ValueError("invalid_webhook_payload")
        intake = await self._intake_event(
            provider_object_id, provider_id, event_type, body
        )
        if intake.outcome != "claimed":
            return {"status": "ok", "result": intake.outcome}
        try:
            refund = None
            if event_type == "refund.succeeded":
                refund = await self._provider.get_refund(provider_object_id)
            remote = await self._provider.get_payment(provider_id)
        except Exception:
            await self._mark_event_failed(intake, "provider_lookup_failed", retryable=True)
            return {"status": "ok", "result": "retryable_failure"}
        try:
            return await self._complete_claimed_event(intake, remote, refund=refund)
        except ValueError as exc:
            await self._mark_event_failed(intake, str(exc), retryable=False)
            return {"status": "ok", "result": "verification_failed"}
        except Exception:
            await self._mark_event_failed(intake, "completion_failed", retryable=True)
            return {"status": "ok", "result": "retryable_failure"}

    async def _intake_event(
        self,
        provider_object_id: str,
        provider_id: str,
        event_type: str,
        body: dict,
    ) -> EventIntake:
        dedup_key = hashlib.sha256(
            f"yookassa|{provider_object_id}|{event_type}".encode()
        ).hexdigest()
        now = _now()
        async with self._session_factory() as session:
            events = PaymentEventRepository(session)
            event, _, mismatch = await events.get_or_create_event(
                provider="yookassa", provider_event_type=event_type,
                provider_object_id=provider_object_id, provider_payment_id=provider_id,
                order_id=None, payment_attempt_id=None, dedup_key=dedup_key,
                provider_status="unverified", verified=False, processing_status="received",
                attempt_count=0, retryable=False,
                payload_fingerprint=_notification_fingerprint(
                    body, provider_object_id, event_type
                ),
                retain_until=_retain_until(now),
            )
            if mismatch:
                await session.commit()
                return EventIntake(
                    event.id,
                    "payload_mismatch",
                    None,
                    provider_id,
                    provider_object_id,
                    event_type,
                )
            claim = await events.claim_event(event.id, now=now, claim_ttl=timedelta(seconds=settings.payment_event_claim_ttl_seconds))
            if claim is not None:
                outcome = "claimed"
            elif event.processing_status == "processed":
                outcome = "already_processed"
            elif event.processing_status == "failed" and not event.retryable:
                outcome = "terminal_failed"
            else:
                outcome = "in_progress"
            await session.commit()
            return EventIntake(
                event.id,
                outcome,
                claim.attempt_count if claim else None,
                provider_id,
                provider_object_id,
                event_type,
            )

    async def _mark_event_failed(self, intake: EventIntake, error_code: str, *, retryable: bool) -> None:
        async with self._session_factory() as session:
            await PaymentEventRepository(session).mark_failed(
                intake.event_id, expected_attempt_count=intake.expected_attempt_count or 0,
                now=_now(), error_code=error_code, error_detail=None, retryable=retryable,
            )
            await session.commit()

    async def _complete_claimed_event(
        self, intake: EventIntake, remote: dict, *, refund: dict | None = None
    ) -> dict:
        self._validate_remote(remote, intake.provider_id)
        if intake.event_type == "refund.succeeded":
            self._validate_refund(
                refund, intake.provider_object_id, intake.provider_id
            )
        metadata = remote.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("product_code") != FULL_MATRIX_PRODUCT_CODE:
            raise ValueError("not_full_matrix_payment")
        public_id = metadata.get("order_id")
        if not isinstance(public_id, str):
            raise ValueError("invalid_payment_metadata")
        async with self._session_factory() as session:
            preliminary_order = await self._get_order(session, public_id, lock=False)
            locked_user = (
                await session.get(User, preliminary_order.user_id, with_for_update=True)
                if preliminary_order is not None
                and preliminary_order.user_id is not None
                else None
            )
            order = await self._get_order(session, public_id, lock=True)
            attempt = (await session.execute(select(PaymentAttempt).where(PaymentAttempt.provider_payment_id == intake.provider_id).with_for_update())).scalar_one_or_none()
            if order is None or attempt is None or attempt.order_id != order.id:
                raise ValueError("payment_attempt_not_found")
            if isinstance(remote.get("test"), bool) and remote["test"] != attempt.test_mode:
                raise ValueError("provider_mode_mismatch")
            now = _now()
            event = await session.get(PaymentEvent, intake.event_id, with_for_update=True)
            if event is None or event.processing_status != "processing" or event.attempt_count != intake.expected_attempt_count:
                return {"status": "ok", "result": "fenced"}
            event.order_id, event.payment_attempt_id = order.id, attempt.id
            event.verified = True
            if event.anonymized_at is None:
                anonymized_source = (
                    attempt if attempt.anonymized_at is not None else order
                )
                if anonymized_source.anonymized_at is not None:
                    event.anonymized_at = anonymized_source.anonymized_at
                    event.anonymization_reason = (
                        anonymized_source.anonymization_reason
                    )
            status = str(remote.get("status"))
            if intake.event_type == "refund.succeeded":
                status = "refunded"
            event.provider_status = status
            if (
                intake.event_type == "payment.succeeded"
                and status == "succeeded"
                and remote.get("paid") is True
            ):
                if order.status not in {OrderStatus.CREATED, OrderStatus.PENDING}:
                    await PaymentEventRepository(session).mark_processed(event.id, expected_attempt_count=intake.expected_attempt_count or 0, now=now)
                    await session.commit()
                    return {"status": "ok", "result": "idempotent"}
                report = await self._create_or_get_paid_report(session, order, now)
                if locked_user is None or locked_user.id != order.user_id:
                    raise ValueError("order_user_not_found")
                attempt.status, attempt.paid_at = "succeeded", now
                order.status, order.paid_at = OrderStatus.PAID, now
                order.checkout_token, order.checkout_expires_at = None, None
                order.activation_started_at = now
                await ReportLifecycleService(session).confirm_order_and_prepare_generation(report.id, order.id, now)
                locked_user.has_matrix, order.activated_at = True, now
                await PaymentEventRepository(session).mark_processed(event.id, expected_attempt_count=intake.expected_attempt_count or 0, now=now)
                await session.commit()
                return {"status": "ok", "result": "activated", "order_id": order.public_id}
            if status == "canceled" and order.status in {OrderStatus.CREATED, OrderStatus.PENDING}:
                attempt.status, attempt.canceled_at = "canceled", now
                order.status, order.canceled_at = OrderStatus.CANCELED, now
            elif status == "refunded" and order.status in {
                OrderStatus.CREATED,
                OrderStatus.PENDING,
                OrderStatus.PAID,
            }:
                attempt.status = "refunded"
                attempt.paid_at = attempt.paid_at or now
                attempt.refunded_at = now
                attempt.canceled_at = None
                order.status = OrderStatus.REFUNDED
                order.paid_at = order.paid_at or now
                order.refunded_at = now
                order.canceled_at = None
                order.checkout_token = None
                order.checkout_expires_at = None
                if order.report_id is not None:
                    await ReportLifecycleRepository(
                        session
                    ).revoke_unfinished_order_report(order.report_id, now)
                if locked_user is not None and locked_user.id == order.user_id:
                    locked_user.has_matrix = False
            await PaymentEventRepository(session).mark_processed(event.id, expected_attempt_count=intake.expected_attempt_count or 0, now=now)
            await session.commit()
            return {"status": "ok", "result": status}

    @staticmethod
    def _validate_create_response(remote: dict) -> tuple[str, str]:
        confirmation = remote.get("confirmation") if isinstance(remote, dict) else None
        provider_id = remote.get("id") if isinstance(remote, dict) else None
        url = confirmation.get("confirmation_url") if isinstance(confirmation, dict) else None
        if not isinstance(provider_id, str) or not provider_id or not isinstance(url, str) or not url.startswith("https://"):
            raise ValueError("invalid_provider_checkout")
        return provider_id, url

    @staticmethod
    def _validate_remote(remote: dict, provider_id: str) -> None:
        amount = remote.get("amount") if isinstance(remote, dict) else None
        if (
            remote.get("id") != provider_id
            or not isinstance(amount, dict)
            or amount.get("value") != "890.00"
            or amount.get("currency") != FULL_MATRIX_CURRENCY
        ):
            raise ValueError("provider_payment_mismatch")

    @staticmethod
    def _validate_refund(
        refund: dict | None, provider_refund_id: str, provider_payment_id: str
    ) -> None:
        amount = refund.get("amount") if isinstance(refund, dict) else None
        if (
            not isinstance(refund, dict)
            or refund.get("id") != provider_refund_id
            or refund.get("payment_id") != provider_payment_id
            or refund.get("status") != "succeeded"
            or not isinstance(amount, dict)
            or amount.get("value") != FULL_MATRIX_AMOUNT_VALUE
            or amount.get("currency") != FULL_MATRIX_CURRENCY
        ):
            raise ValueError("provider_refund_mismatch")

    async def handles_webhook(self, body: dict) -> bool:
        """Route production-shaped full-Matrix notifications without trusting metadata."""
        event_type = body.get("event") if isinstance(body, dict) else None
        obj = body.get("object") if isinstance(body, dict) else None
        if event_type == "refund.succeeded":
            provider_object_id = obj.get("id") if isinstance(obj, dict) else None
            payment_id = obj.get("payment_id") if isinstance(obj, dict) else None
            if (
                not isinstance(provider_object_id, str)
                or not provider_object_id
                or len(provider_object_id) > 100
                or not isinstance(payment_id, str)
                or not payment_id
                or len(payment_id) > 100
            ):
                return True
            async with self._session_factory() as session:
                attempt_id = (
                    await session.execute(
                        select(PaymentAttempt.id).where(
                            PaymentAttempt.provider == "yookassa",
                            PaymentAttempt.provider_payment_id == payment_id,
                        )
                    )
                ).scalar_one_or_none()
                return attempt_id is not None
        metadata = obj.get("metadata") if isinstance(obj, dict) else None
        return bool(
            isinstance(metadata, dict)
            and metadata.get("product_code") == FULL_MATRIX_PRODUCT_CODE
        )

    @staticmethod
    async def _get_order(session: AsyncSession, public_id: str, lock: bool) -> Order | None:
        statement = select(Order).where(Order.public_id == public_id)
        if lock:
            statement = statement.with_for_update()
        return (await session.execute(statement)).scalar_one_or_none()

    @staticmethod
    async def _get_order_by_checkout_token(session: AsyncSession, checkout_token: str, lock: bool) -> Order | None:
        statement = select(Order).where(Order.checkout_token == checkout_token)
        if lock:
            statement = statement.with_for_update()
        return (await session.execute(statement)).scalar_one_or_none()

    @staticmethod
    async def _get_active_attempt(session: AsyncSession, order_id: uuid.UUID) -> PaymentAttempt | None:
        return (
            await session.execute(
                select(PaymentAttempt).where(PaymentAttempt.order_id == order_id).order_by(PaymentAttempt.created_at.desc()).with_for_update()
            )
        ).scalars().first()

    @staticmethod
    async def _create_or_get_paid_report(session: AsyncSession, order: Order, now: datetime) -> Report:
        if order.report_id is not None:
            report = await session.get(Report, order.report_id, with_for_update=True)
            if report is not None:
                return report
        if order.user_id is None:
            raise ValueError("order_user_anonymized")
        report = Report(
            id=uuid.uuid4(), user_id=order.user_id, report_type=ReportType.FULL.value,
            token=secrets.token_urlsafe(32), order_id=order.id,
            payment_state=ReportPaymentState.AWAITING_PAYMENT,
            generation_state=ReportGenerationState.NOT_REQUESTED,
        )
        session.add(report)
        await session.flush()
        order.report_id = report.id
        return report
