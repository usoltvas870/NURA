"""Atomic profile deletion with retained financial-record anonymization."""

import hashlib
import hmac
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.config import settings
from core.models import (
    FullReportTelegramDelivery,
    Order,
    Payment,
    PaymentAttempt,
    PaymentEvent,
    ReferralReward,
    Report,
    ReportGenerationJob,
    User,
)


class AccountDeletionService:
    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    async def delete(self, user_id: uuid.UUID) -> None:
        reference = hmac.new(
            settings.secret_key.encode(), str(user_id).encode(), hashlib.sha256
        ).hexdigest()
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            user = await session.get(User, user_id, with_for_update=True)
            if user is None:
                await session.rollback()
                return
            orders = (
                await session.execute(select(Order).where(Order.user_id == user_id).with_for_update())
            ).scalars().all()
            for order in orders:
                order.user_id = None
                order.telegram_id_snapshot = None
                order.report_id = None
                order.checkout_token = None
                order.checkout_expires_at = None
                order.customer_reference_hash = reference
                order.anonymized_at = now
                order.anonymization_reason = "account_deleted"
                attempts = (
                    await session.execute(select(PaymentAttempt).where(PaymentAttempt.order_id == order.id).with_for_update())
                ).scalars().all()
                for attempt in attempts:
                    attempt.confirmation_url = None
                    attempt.provider_metadata = {"product_code": "full_matrix"}
                    attempt.customer_reference_hash = reference
                    attempt.anonymized_at = now
                    attempt.anonymization_reason = "account_deleted"
                    events = (
                        await session.execute(select(PaymentEvent).where(PaymentEvent.payment_attempt_id == attempt.id).with_for_update())
                    ).scalars().all()
                    for event in events:
                        event.anonymized_at = now
                        event.anonymization_reason = "account_deleted"
            report_ids = select(Report.id).where(Report.user_id == user_id)
            await session.execute(
                delete(FullReportTelegramDelivery).where(
                    FullReportTelegramDelivery.user_id == user_id
                )
            )
            await session.execute(
                delete(ReportGenerationJob).where(ReportGenerationJob.report_id.in_(report_ids))
            )
            await session.execute(delete(Report).where(Report.user_id == user_id))
            await session.execute(delete(Payment).where(Payment.user_id == user_id))
            await session.execute(delete(ReferralReward).where((ReferralReward.referrer_id == user_id) | (ReferralReward.referred_id == user_id)))
            await session.delete(user)
            await session.commit()
