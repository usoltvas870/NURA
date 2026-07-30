"""Persistence and concurrency primitives for Telegram broadcast campaigns."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import aliased

from core.config import settings
from core.models import (
    BroadcastAuditEntry,
    BroadcastCampaign,
    BroadcastCampaignState,
    BroadcastCTAClick,
    BroadcastCTAClickEvent,
    BroadcastDelivery,
    BroadcastDeliveryState,
    Order,
    OrderStatus,
    Report,
    ReportType,
    TelegramSuppression,
    User,
)


@dataclass(frozen=True)
class BroadcastDeliveryClaim:
    delivery_id: uuid.UUID
    campaign_id: uuid.UUID
    user_id: uuid.UUID
    attempt: int
    chat_id: int
    text: str
    media_type: str | None
    media_file_id: str | None
    media_message_id: int | None
    ctas: list[dict]
    click_token: str


class BroadcastRepository:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _aware(value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @staticmethod
    def _audit(
        campaign_id: uuid.UUID,
        actor: str,
        action: str,
        reason: str | None,
        evidence: dict | None = None,
    ) -> BroadcastAuditEntry:
        return BroadcastAuditEntry(
            id=uuid.uuid4(),
            campaign_id=campaign_id,
            actor=actor,
            action=action,
            reason=reason,
            evidence=evidence or {},
        )

    async def create_campaign(self, *, actor: str, values: dict, reason: str | None) -> BroadcastCampaign:
        async with self._session_factory() as session:
            campaign = BroadcastCampaign(
                id=uuid.uuid4(),
                public_id=secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16],
                created_by=actor,
                updated_by=actor,
                **values,
            )
            session.add(campaign)
            session.add(self._audit(campaign.id, actor, "created", reason, {"content_version": 1}))
            await session.commit()
            await session.refresh(campaign)
            return campaign

    async def get_campaign(self, public_id: str) -> BroadcastCampaign | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(BroadcastCampaign).where(BroadcastCampaign.public_id == public_id)
            )

    async def list_campaigns(self, *, limit: int, offset: int) -> list[BroadcastCampaign]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(BroadcastCampaign)
                .order_by(BroadcastCampaign.created_at.desc(), BroadcastCampaign.id.desc())
                .offset(offset)
                .limit(limit)
            )
            return list(result.scalars())

    async def update_campaign(
        self,
        public_id: str,
        *,
        actor: str,
        values: dict,
        reason: str | None,
    ) -> BroadcastCampaign | None:
        async with self._session_factory() as session:
            campaign = await session.scalar(
                select(BroadcastCampaign)
                .where(BroadcastCampaign.public_id == public_id)
                .with_for_update()
            )
            if campaign is None:
                return None
            if campaign.status not in (
                BroadcastCampaignState.DRAFT,
                BroadcastCampaignState.TESTED,
            ):
                raise ValueError("campaign_immutable")
            changed = False
            for key, value in values.items():
                if getattr(campaign, key) != value:
                    setattr(campaign, key, value)
                    changed = True
            if changed:
                campaign.content_version += 1
                campaign.status = BroadcastCampaignState.DRAFT
                campaign.tested_version = None
                campaign.tested_at = None
                campaign.test_message_ids = None
                campaign.preview_version = None
                campaign.preview_count = None
                campaign.previewed_at = None
                campaign.updated_by = actor
                session.add(
                    self._audit(
                        campaign.id,
                        actor,
                        "updated",
                        reason,
                        {"content_version": campaign.content_version},
                    )
                )
            await session.commit()
            await session.refresh(campaign)
            return campaign

    def _eligible_users_statement(
        self,
        campaign: BroadcastCampaign,
        *,
        now: datetime,
    ):
        suppression_exists = select(TelegramSuppression.id).where(
            TelegramSuppression.user_id == User.id,
            TelegramSuppression.active.is_(True),
        ).exists()
        delivered_in_window = (
            select(func.count(BroadcastDelivery.id))
            .join(BroadcastCampaign, BroadcastCampaign.id == BroadcastDelivery.campaign_id)
            .where(
                BroadcastDelivery.user_id == User.id,
                BroadcastDelivery.status == BroadcastDeliveryState.DELIVERED,
                BroadcastDelivery.delivered_at
                >= now - timedelta(days=settings.broadcast_frequency_window_days),
                BroadcastCampaign.campaign_type.in_(("editorial", "commercial")),
            )
            .correlate(User)
            .scalar_subquery()
        )
        statement = select(User.id, User.telegram_id).where(
            User.account_status == "active",
            User.telegram_id.is_not(None),
            User.editorial_messages_enabled.is_(True),
            ~suppression_exists,
            delivered_in_window < settings.broadcast_frequency_max,
        )
        if campaign.segment_type == "mini_completed_without_full_purchase":
            mini_exists = select(Report.id).where(
                Report.user_id == User.id,
                Report.report_type == ReportType.MINI.value,
                Report.matrix_data.is_not(None),
            ).exists()
            paid_exists = select(Order.id).where(
                Order.user_id == User.id,
                Order.status == OrderStatus.PAID,
            ).exists()
            statement = statement.where(mini_exists, ~paid_exists)
        elif campaign.segment_type == "full_report_purchasers":
            paid_exists = select(Order.id).where(
                Order.user_id == User.id,
                Order.status == OrderStatus.PAID,
            ).exists()
            statement = statement.where(paid_exists)
        elif campaign.segment_type == "onboarding_incomplete":
            statement = statement.where(
                or_(User.pd_consent_at.is_(None), User.birth_date.is_(None))
            )
        elif campaign.segment_type == "inactive":
            days = int((campaign.segment_parameters or {}).get("inactive_days", 0))
            if not 1 <= days <= 3650:
                raise ValueError("invalid_inactive_days")
            statement = statement.where(
                func.coalesce(User.last_activity_at, User.created_at)
                <= now - timedelta(days=days)
            )
        elif campaign.segment_type != "all_editorial_enabled":
            raise ValueError("invalid_segment")
        return statement

    async def estimate_recipients(
        self,
        public_id: str,
        *,
        actor: str,
        reason: str | None,
        now: datetime,
    ) -> tuple[BroadcastCampaign, int] | None:
        async with self._session_factory() as session:
            campaign = await session.scalar(
                select(BroadcastCampaign)
                .where(BroadcastCampaign.public_id == public_id)
                .with_for_update()
            )
            if campaign is None:
                return None
            if campaign.status not in (
                BroadcastCampaignState.DRAFT,
                BroadcastCampaignState.TESTED,
            ):
                raise ValueError("campaign_immutable")
            eligible = self._eligible_users_statement(campaign, now=now).subquery()
            count = int(await session.scalar(select(func.count()).select_from(eligible)) or 0)
            campaign.preview_version = campaign.content_version
            campaign.preview_count = count
            campaign.previewed_at = now
            session.add(
                self._audit(
                    campaign.id,
                    actor,
                    "estimated",
                    reason,
                    {"content_version": campaign.content_version, "preview_count": count},
                )
            )
            await session.commit()
            await session.refresh(campaign)
            return campaign, count

    async def mark_tested(
        self,
        public_id: str,
        *,
        expected_version: int,
        actor: str,
        reason: str | None,
        message_ids: list[int],
        now: datetime,
    ) -> BroadcastCampaign | None:
        async with self._session_factory() as session:
            campaign = await session.scalar(
                select(BroadcastCampaign)
                .where(BroadcastCampaign.public_id == public_id)
                .with_for_update()
            )
            if campaign is None:
                return None
            if campaign.content_version != expected_version:
                raise ValueError("stale_content_version")
            if campaign.status not in (
                BroadcastCampaignState.DRAFT,
                BroadcastCampaignState.TESTED,
            ):
                raise ValueError("campaign_immutable")
            campaign.status = BroadcastCampaignState.TESTED
            campaign.tested_version = expected_version
            campaign.tested_at = now
            campaign.test_message_ids = message_ids
            campaign.updated_by = actor
            session.add(
                self._audit(
                    campaign.id,
                    actor,
                    "tested",
                    reason,
                    {"content_version": expected_version, "message_count": len(message_ids)},
                )
            )
            await session.commit()
            await session.refresh(campaign)
            return campaign

    async def launch_campaign(
        self,
        public_id: str,
        *,
        expected_version: int,
        idempotency_hash: str,
        actor: str,
        reason: str | None,
        now: datetime,
    ) -> tuple[BroadcastCampaign, bool] | None:
        async with self._session_factory() as session:
            campaign = await session.scalar(
                select(BroadcastCampaign)
                .where(BroadcastCampaign.public_id == public_id)
                .with_for_update()
            )
            if campaign is None:
                return None
            if campaign.launch_idempotency_hash is not None:
                if campaign.launch_idempotency_hash != idempotency_hash:
                    raise ValueError("campaign_already_launched")
                return campaign, False
            if campaign.status not in (
                BroadcastCampaignState.DRAFT,
                BroadcastCampaignState.TESTED,
            ):
                raise ValueError("campaign_not_launchable")
            if campaign.content_version != expected_version:
                raise ValueError("stale_content_version")
            if campaign.tested_version != campaign.content_version:
                raise ValueError("exact_version_not_tested")
            if campaign.preview_version != campaign.content_version:
                raise ValueError("exact_version_not_estimated")

            statement = self._eligible_users_statement(campaign, now=now).order_by(User.id)
            last_id: uuid.UUID | None = None
            selected = 0
            while True:
                page = statement
                if last_id is not None:
                    page = page.where(User.id > last_id)
                rows = (
                    await session.execute(page.limit(settings.broadcast_selection_batch_size))
                ).all()
                if not rows:
                    break
                session.add_all(
                    BroadcastDelivery(
                        id=uuid.uuid4(),
                        campaign_id=campaign.id,
                        user_id=user_id,
                        telegram_chat_id_snapshot=telegram_id,
                        click_token=secrets.token_urlsafe(12),
                    )
                    for user_id, telegram_id in rows
                )
                await session.flush()
                selected += len(rows)
                last_id = rows[-1][0]

            campaign.launch_idempotency_hash = idempotency_hash
            campaign.launched_by = actor
            campaign.selected_count = selected
            campaign.queued_at = now
            if selected:
                campaign.status = BroadcastCampaignState.QUEUED
            else:
                campaign.status = BroadcastCampaignState.COMPLETED
                campaign.completed_at = now
            session.add(
                self._audit(
                    campaign.id,
                    actor,
                    "launched",
                    reason,
                    {
                        "content_version": campaign.content_version,
                        "segment_type": campaign.segment_type,
                        "idempotency_key_hash": idempotency_hash,
                        "preview_count": campaign.preview_count,
                        "test_version": campaign.tested_version,
                        "selected_count": selected,
                    },
                )
            )
            await session.commit()
            await session.refresh(campaign)
            return campaign, True

    async def cancel_campaign(
        self,
        public_id: str,
        *,
        actor: str,
        reason: str | None,
        now: datetime,
    ) -> BroadcastCampaign | None:
        async with self._session_factory() as session:
            campaign = await session.scalar(
                select(BroadcastCampaign)
                .where(BroadcastCampaign.public_id == public_id)
                .with_for_update()
            )
            if campaign is None:
                return None
            if campaign.status not in (
                BroadcastCampaignState.DRAFT,
                BroadcastCampaignState.TESTED,
                BroadcastCampaignState.QUEUED,
            ):
                raise ValueError("campaign_not_cancelable")
            claimed = await session.scalar(
                select(func.count(BroadcastDelivery.id)).where(
                    BroadcastDelivery.campaign_id == campaign.id,
                    BroadcastDelivery.attempt_count > 0,
                )
            )
            if claimed:
                raise ValueError("campaign_already_claimed")
            await session.execute(
                update(BroadcastDelivery)
                .where(
                    BroadcastDelivery.campaign_id == campaign.id,
                    BroadcastDelivery.status == BroadcastDeliveryState.QUEUED,
                )
                .values(status=BroadcastDeliveryState.CANCELED)
            )
            campaign.status = BroadcastCampaignState.CANCELED
            campaign.canceled_at = now
            session.add(self._audit(campaign.id, actor, "canceled", reason))
            await session.commit()
            await session.refresh(campaign)
            return campaign

    async def list_dispatchable_delivery_ids(
        self, campaign_id: uuid.UUID, *, now: datetime, limit: int
    ) -> list[uuid.UUID]:
        stale_before = now - timedelta(seconds=settings.telegram_delivery_claim_timeout_seconds)
        async with self._session_factory() as session:
            result = await session.execute(
                select(BroadcastDelivery.id)
                .where(
                    BroadcastDelivery.campaign_id == campaign_id,
                    or_(
                        BroadcastDelivery.status == BroadcastDeliveryState.QUEUED,
                        (
                            (BroadcastDelivery.status == BroadcastDeliveryState.FAILED_RETRYABLE)
                            & or_(
                                BroadcastDelivery.retry_not_before.is_(None),
                                BroadcastDelivery.retry_not_before <= now,
                            )
                        ),
                        (
                            (BroadcastDelivery.status == BroadcastDeliveryState.SENDING)
                            & (BroadcastDelivery.claimed_at < stale_before)
                        ),
                    ),
                )
                .order_by(BroadcastDelivery.created_at, BroadcastDelivery.id)
                .limit(limit)
            )
            return list(result.scalars())

    async def list_dispatchable_campaign_ids(self, *, now: datetime, limit: int) -> list[uuid.UUID]:
        delivery_exists = select(BroadcastDelivery.id).where(
            BroadcastDelivery.campaign_id == BroadcastCampaign.id,
            or_(
                BroadcastDelivery.status == BroadcastDeliveryState.QUEUED,
                (
                    (BroadcastDelivery.status == BroadcastDeliveryState.FAILED_RETRYABLE)
                    & or_(
                        BroadcastDelivery.retry_not_before.is_(None),
                        BroadcastDelivery.retry_not_before <= now,
                    )
                ),
                (
                    (BroadcastDelivery.status == BroadcastDeliveryState.SENDING)
                    & (
                        BroadcastDelivery.claimed_at
                        < now - timedelta(seconds=settings.telegram_delivery_claim_timeout_seconds)
                    )
                ),
            ),
        ).exists()
        async with self._session_factory() as session:
            result = await session.execute(
                select(BroadcastCampaign.id)
                .where(
                    BroadcastCampaign.status.in_(
                        (BroadcastCampaignState.QUEUED, BroadcastCampaignState.SENDING)
                    ),
                    delivery_exists,
                )
                .order_by(BroadcastCampaign.queued_at, BroadcastCampaign.id)
                .limit(limit)
            )
            return list(result.scalars())

    async def claim_delivery(
        self, delivery_id: uuid.UUID, *, now: datetime
    ) -> BroadcastDeliveryClaim | None:
        stale_before = now - timedelta(seconds=settings.telegram_delivery_claim_timeout_seconds)
        async with self._session_factory() as session:
            delivery = await session.scalar(
                select(BroadcastDelivery)
                .where(BroadcastDelivery.id == delivery_id)
                .with_for_update()
            )
            if delivery is None:
                return None
            eligible_status = (
                delivery.status == BroadcastDeliveryState.QUEUED
                or (
                    delivery.status == BroadcastDeliveryState.FAILED_RETRYABLE
                    and (
                        delivery.retry_not_before is None
                        or self._aware(delivery.retry_not_before) <= now
                    )
                )
                or (
                    delivery.status == BroadcastDeliveryState.SENDING
                    and delivery.claimed_at is not None
                    and self._aware(delivery.claimed_at) < stale_before
                )
            )
            if not eligible_status:
                return None
            if delivery.attempt_count >= settings.broadcast_retry_max_attempts:
                delivery.status = BroadcastDeliveryState.FAILED_TERMINAL
                delivery.failed_at = now
                delivery.retry_not_before = None
                delivery.claimed_at = None
                delivery.error_code = "retry_attempts_exhausted"
                await session.commit()
                return None
            user = await session.scalar(
                select(User).where(User.id == delivery.user_id).with_for_update()
            )
            campaign = await session.get(BroadcastCampaign, delivery.campaign_id)
            if user is None or campaign is None or campaign.status not in (
                BroadcastCampaignState.QUEUED,
                BroadcastCampaignState.SENDING,
            ):
                delivery.status = BroadcastDeliveryState.CANCELED
                await session.commit()
                return None
            suppression = await session.scalar(
                select(TelegramSuppression.id).where(
                    TelegramSuppression.user_id == user.id,
                    TelegramSuppression.active.is_(True),
                )
            )
            if user.account_status != "active" or user.telegram_id is None or suppression:
                delivery.status = BroadcastDeliveryState.CANCELED
                delivery.suppressed_at = now
                delivery.error_code = "recipient_inactive_or_suppressed"
                await session.commit()
                return None
            if not user.editorial_messages_enabled:
                delivery.status = BroadcastDeliveryState.SUPPRESSED_OPT_OUT
                delivery.suppressed_at = now
                delivery.error_code = "editorial_opt_out"
                await session.commit()
                return None
            if await self._frequency_slots_used(session, user.id, delivery.id, now) >= settings.broadcast_frequency_max:
                delivery.status = BroadcastDeliveryState.SUPPRESSED_FREQUENCY
                delivery.suppressed_at = now
                delivery.error_code = "frequency_cap"
                await session.commit()
                return None
            delivery.status = BroadcastDeliveryState.SENDING
            delivery.attempt_count += 1
            delivery.claimed_at = now
            delivery.retry_not_before = None
            delivery.failed_at = None
            delivery.error_code = None
            campaign.status = BroadcastCampaignState.SENDING
            if campaign.started_at is None:
                campaign.started_at = now
            await session.commit()
            return BroadcastDeliveryClaim(
                delivery_id=delivery.id,
                campaign_id=campaign.id,
                user_id=user.id,
                attempt=delivery.attempt_count,
                chat_id=delivery.telegram_chat_id_snapshot,
                text=campaign.text_snapshot,
                media_type=campaign.media_type,
                media_file_id=campaign.media_file_id,
                media_message_id=delivery.media_message_id,
                ctas=list(campaign.cta_snapshot),
                click_token=delivery.click_token,
            )

    async def _frequency_slots_used(
        self, session, user_id: uuid.UUID, delivery_id: uuid.UUID, now: datetime
    ) -> int:
        return int(
            await session.scalar(
                select(func.count(BroadcastDelivery.id))
                .join(BroadcastCampaign, BroadcastCampaign.id == BroadcastDelivery.campaign_id)
                .where(
                    BroadcastDelivery.user_id == user_id,
                    BroadcastDelivery.id != delivery_id,
                    BroadcastCampaign.campaign_type.in_(("editorial", "commercial")),
                    or_(
                        (
                            (BroadcastDelivery.status == BroadcastDeliveryState.DELIVERED)
                            & (
                                BroadcastDelivery.delivered_at
                                >= now - timedelta(days=settings.broadcast_frequency_window_days)
                            )
                        ),
                        BroadcastDelivery.status == BroadcastDeliveryState.SENDING,
                    ),
                )
            )
            or 0
        )

    async def recheck_claim(self, delivery_id: uuid.UUID, attempt: int, *, now: datetime) -> bool:
        async with self._session_factory() as session:
            delivery = await session.scalar(
                select(BroadcastDelivery)
                .where(BroadcastDelivery.id == delivery_id)
                .with_for_update()
            )
            if (
                delivery is None
                or delivery.status != BroadcastDeliveryState.SENDING
                or delivery.attempt_count != attempt
            ):
                return False
            user = await session.scalar(
                select(User).where(User.id == delivery.user_id).with_for_update()
            )
            if user is None or user.account_status != "active" or user.telegram_id is None:
                delivery.status = BroadcastDeliveryState.CANCELED
                delivery.suppressed_at = now
                delivery.error_code = "recipient_inactive"
            elif not user.editorial_messages_enabled:
                delivery.status = BroadcastDeliveryState.SUPPRESSED_OPT_OUT
                delivery.suppressed_at = now
                delivery.error_code = "editorial_opt_out"
            elif await session.scalar(
                select(TelegramSuppression.id).where(
                    TelegramSuppression.user_id == user.id,
                    TelegramSuppression.active.is_(True),
                )
            ):
                delivery.status = BroadcastDeliveryState.CANCELED
                delivery.suppressed_at = now
                delivery.error_code = "telegram_suppressed"
            elif await self._frequency_slots_used(session, user.id, delivery.id, now) >= settings.broadcast_frequency_max:
                delivery.status = BroadcastDeliveryState.SUPPRESSED_FREQUENCY
                delivery.suppressed_at = now
                delivery.error_code = "frequency_cap"
            else:
                await session.commit()
                return True
            delivery.claimed_at = None
            await session.commit()
            return False

    async def save_media_progress(
        self, delivery_id: uuid.UUID, attempt: int, message_id: int
    ) -> bool:
        return await self._fenced_update(
            delivery_id, attempt, media_message_id=message_id
        )

    async def complete_delivery(
        self, delivery_id: uuid.UUID, attempt: int, message_id: int, *, now: datetime
    ) -> bool:
        return await self._fenced_update(
            delivery_id,
            attempt,
            status=BroadcastDeliveryState.DELIVERED,
            text_message_id=message_id,
            delivered_at=now,
            claimed_at=None,
            failed_at=None,
            error_code=None,
        )

    async def fail_delivery(
        self,
        delivery_id: uuid.UUID,
        attempt: int,
        *,
        code: str,
        retryable: bool,
        retry_after: int | None,
        now: datetime,
    ) -> bool:
        remains_retryable = retryable and attempt < settings.broadcast_retry_max_attempts
        delay = retry_after if retry_after is not None else min(
            settings.broadcast_retry_max_seconds,
            30 * (2 ** max(attempt - 1, 0)),
        )
        return await self._fenced_update(
            delivery_id,
            attempt,
            status=(
                BroadcastDeliveryState.FAILED_RETRYABLE
                if remains_retryable
                else BroadcastDeliveryState.FAILED_TERMINAL
            ),
            failed_at=now,
            retry_not_before=(
                now + timedelta(seconds=min(delay, settings.broadcast_retry_max_seconds))
                if remains_retryable
                else None
            ),
            claimed_at=None,
            error_code=code[:64],
        )

    async def block_delivery(
        self,
        delivery_id: uuid.UUID,
        attempt: int,
        *,
        code: str,
        reason: str,
        now: datetime,
    ) -> bool:
        async with self._session_factory() as session:
            delivery = await session.scalar(
                select(BroadcastDelivery)
                .where(
                    BroadcastDelivery.id == delivery_id,
                    BroadcastDelivery.status == BroadcastDeliveryState.SENDING,
                    BroadcastDelivery.attempt_count == attempt,
                )
                .with_for_update()
            )
            if delivery is None:
                return False
            suppression = await session.scalar(
                select(TelegramSuppression)
                .where(TelegramSuppression.user_id == delivery.user_id)
                .with_for_update()
            )
            if suppression is None:
                session.add(
                    TelegramSuppression(
                        id=uuid.uuid4(),
                        user_id=delivery.user_id,
                        reason=reason,
                        created_by="telegram",
                    )
                )
            elif suppression.reason != "operator":
                suppression.reason = reason
                suppression.active = True
                suppression.released_at = None
            delivery.status = BroadcastDeliveryState.BLOCKED
            delivery.blocked_at = now
            delivery.claimed_at = None
            delivery.error_code = code[:64]
            await session.commit()
            return True

    async def _fenced_update(self, delivery_id: uuid.UUID, attempt: int, **values: object) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                update(BroadcastDelivery)
                .where(
                    BroadcastDelivery.id == delivery_id,
                    BroadcastDelivery.status == BroadcastDeliveryState.SENDING,
                    BroadcastDelivery.attempt_count == attempt,
                )
                .values(**values)
            )
            await session.commit()
            return result.rowcount == 1

    async def refresh_campaign(self, campaign_id: uuid.UUID, *, now: datetime) -> BroadcastCampaign | None:
        async with self._session_factory() as session:
            campaign = await session.scalar(
                select(BroadcastCampaign)
                .where(BroadcastCampaign.id == campaign_id)
                .with_for_update()
            )
            if campaign is None:
                return None
            rows = (
                await session.execute(
                    select(BroadcastDelivery.status, func.count(BroadcastDelivery.id))
                    .where(BroadcastDelivery.campaign_id == campaign_id)
                    .group_by(BroadcastDelivery.status)
                )
            ).all()
            counts = {status: int(count) for status, count in rows}
            campaign.delivered_count = counts.get(BroadcastDeliveryState.DELIVERED, 0)
            campaign.blocked_count = counts.get(BroadcastDeliveryState.BLOCKED, 0)
            campaign.suppressed_count = (
                counts.get(BroadcastDeliveryState.SUPPRESSED_OPT_OUT, 0)
                + counts.get(BroadcastDeliveryState.SUPPRESSED_FREQUENCY, 0)
                + counts.get(BroadcastDeliveryState.CANCELED, 0)
            )
            campaign.failed_count = (
                counts.get(BroadcastDeliveryState.FAILED_RETRYABLE, 0)
                + counts.get(BroadcastDeliveryState.FAILED_TERMINAL, 0)
            )
            active = sum(
                counts.get(status, 0)
                for status in (
                    BroadcastDeliveryState.QUEUED,
                    BroadcastDeliveryState.SENDING,
                    BroadcastDeliveryState.FAILED_RETRYABLE,
                )
            )
            if active == 0 and campaign.status not in (
                BroadcastCampaignState.CANCELED,
                BroadcastCampaignState.FAILED,
            ):
                campaign.status = BroadcastCampaignState.COMPLETED
                campaign.completed_at = now
                if campaign.failed_count:
                    campaign.error_code = "completed_with_failures"
            await session.commit()
            await session.refresh(campaign)
            return campaign

    async def record_click(
        self, token: str, cta_key: str, telegram_id: int, *, now: datetime
    ) -> str | None:
        async with self._session_factory() as session:
            delivery = await session.scalar(
                select(BroadcastDelivery)
                .where(
                    BroadcastDelivery.click_token == token,
                    BroadcastDelivery.telegram_chat_id_snapshot == telegram_id,
                    BroadcastDelivery.status.in_(
                        (BroadcastDeliveryState.SENDING, BroadcastDeliveryState.DELIVERED)
                    ),
                )
                .with_for_update()
            )
            if delivery is None:
                return None
            campaign = await session.get(BroadcastCampaign, delivery.campaign_id)
            cta = next(
                (
                    item
                    for item in (campaign.cta_snapshot if campaign else [])
                    if item.get("key") == cta_key
                ),
                None,
            )
            if cta is None:
                return None
            destination = str(cta.get("destination", ""))
            click = await session.scalar(
                select(BroadcastCTAClick)
                .where(
                    BroadcastCTAClick.delivery_id == delivery.id,
                    BroadcastCTAClick.cta_key == cta_key,
                )
                .with_for_update()
            )
            if click is None:
                click = BroadcastCTAClick(
                    id=uuid.uuid4(),
                    campaign_id=delivery.campaign_id,
                    delivery_id=delivery.id,
                    user_id=delivery.user_id,
                    cta_key=cta_key,
                    destination=destination,
                    first_clicked_at=now,
                    last_clicked_at=now,
                )
                session.add(click)
                await session.flush()
            else:
                click.click_count = min(click.click_count + 1, 1_000_000)
                click.last_clicked_at = now
            session.add(
                BroadcastCTAClickEvent(
                    id=uuid.uuid4(),
                    click_id=click.id,
                    campaign_id=delivery.campaign_id,
                    delivery_id=delivery.id,
                    user_id=delivery.user_id,
                    cta_key=cta_key,
                    destination=destination,
                    clicked_at=now,
                    attribution_expires_at=now
                    + timedelta(days=campaign.attribution_window_days),
                )
            )
            await session.commit()
            return destination

    async def release_automatic_suppression(self, user_id: uuid.UUID, *, now: datetime) -> None:
        async with self._session_factory() as session:
            suppression = await session.scalar(
                select(TelegramSuppression)
                .where(TelegramSuppression.user_id == user_id)
                .with_for_update()
            )
            if (
                suppression is not None
                and suppression.active
                and suppression.reason in {"bot_blocked", "chat_not_found"}
            ):
                suppression.active = False
                suppression.released_at = now
            await session.commit()

    async def set_editorial_preference(self, telegram_id: int, enabled: bool) -> bool | None:
        async with self._session_factory() as session:
            user = await session.scalar(
                select(User).where(User.telegram_id == telegram_id).with_for_update()
            )
            if user is None:
                return None
            user.editorial_messages_enabled = enabled
            prefs = dict(user.notification_prefs or {})
            prefs["news"] = enabled
            user.notification_prefs = prefs
            await session.commit()
            return enabled

    async def get_editorial_preference(self, telegram_id: int) -> bool | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(User.editorial_messages_enabled).where(User.telegram_id == telegram_id)
            )

    async def delivery_counts(self, campaign_id: uuid.UUID) -> dict[str, int]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(BroadcastDelivery.status, func.count(BroadcastDelivery.id))
                    .where(BroadcastDelivery.campaign_id == campaign_id)
                    .group_by(BroadcastDelivery.status)
                )
            ).all()
            return {status: int(count) for status, count in rows}

    async def click_counts(self, campaign_id: uuid.UUID) -> list[dict]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        BroadcastCTAClick.cta_key,
                        BroadcastCTAClick.destination,
                        func.count(func.distinct(BroadcastCTAClick.user_id)),
                        func.sum(BroadcastCTAClick.click_count),
                    )
                    .where(BroadcastCTAClick.campaign_id == campaign_id)
                    .group_by(BroadcastCTAClick.cta_key, BroadcastCTAClick.destination)
                )
            ).all()
            return [
                {
                    "cta_key": key,
                    "destination": destination,
                    "unique_clickers": int(unique_count),
                    "total_clicks": int(total_count or 0),
                }
                for key, destination, unique_count, total_count in rows
            ]

    @staticmethod
    def _attributed_paid_orders_statement(campaign_id: uuid.UUID):
        target_click = aliased(BroadcastCTAClickEvent)
        later_click = aliased(BroadcastCTAClickEvent)
        later_valid_click = (
            select(later_click.id)
            .where(
                later_click.user_id == Order.user_id,
                later_click.clicked_at <= Order.paid_at,
                later_click.attribution_expires_at >= Order.paid_at,
                or_(
                    later_click.clicked_at > target_click.clicked_at,
                    and_(
                        later_click.clicked_at == target_click.clicked_at,
                        later_click.id > target_click.id,
                    ),
                ),
            )
            .correlate(Order, target_click)
            .exists()
        )
        return (
            select(func.count(Order.id))
            .select_from(Order)
            .join(target_click, target_click.user_id == Order.user_id)
            .where(
                Order.status == OrderStatus.PAID,
                Order.user_id.is_not(None),
                Order.paid_at.is_not(None),
                target_click.campaign_id == campaign_id,
                target_click.clicked_at <= Order.paid_at,
                target_click.attribution_expires_at >= Order.paid_at,
                ~later_valid_click,
            )
        )

    async def attributed_paid_order_count(self, campaign_id: uuid.UUID) -> int:
        async with self._session_factory() as session:
            return int(
                await session.scalar(self._attributed_paid_orders_statement(campaign_id))
                or 0
            )
