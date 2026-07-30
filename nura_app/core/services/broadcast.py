"""Application service for the minimal persisted Telegram campaign contour."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from core.config import settings
from core.models import BroadcastCampaign, BroadcastCampaignState, BroadcastDeliveryState
from core.repositories.broadcast import BroadcastRepository
from core.schemas.broadcast import CampaignCreate, CampaignUpdate
from core.services.broadcast_telegram import (
    BroadcastTelegramAdapter,
    BroadcastTelegramError,
)

ALLOWED_DESTINATIONS = frozenset(
    {
        "main_menu",
        "chat",
        "tarot_daily",
        "my_reports",
        "buy_matrix",
        "profile",
        "settings",
    }
)


class BroadcastServiceError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class BroadcastCampaignService:
    def __init__(
        self,
        session_factory,
        adapter: BroadcastTelegramAdapter | None = None,
    ) -> None:
        self._repository = BroadcastRepository(session_factory)
        self._adapter = adapter

    @staticmethod
    def campaign_dict(campaign: BroadcastCampaign) -> dict:
        return {
            "campaign_id": campaign.public_id,
            "campaign_type": campaign.campaign_type,
            "status": campaign.status,
            "content_version": campaign.content_version,
            "text": campaign.text_snapshot,
            "media_type": campaign.media_type,
            "media_file_id": campaign.media_file_id,
            "ctas": list(campaign.cta_snapshot),
            "segment_type": campaign.segment_type,
            "segment_parameters": dict(campaign.segment_parameters or {}),
            "attribution_window_days": campaign.attribution_window_days,
            "created_by": campaign.created_by,
            "updated_by": campaign.updated_by,
            "launched_by": campaign.launched_by,
            "tested_version": campaign.tested_version,
            "tested_at": campaign.tested_at,
            "preview_version": campaign.preview_version,
            "preview_count": campaign.preview_count,
            "previewed_at": campaign.previewed_at,
            "queued_at": campaign.queued_at,
            "started_at": campaign.started_at,
            "completed_at": campaign.completed_at,
            "canceled_at": campaign.canceled_at,
            "selected_count": campaign.selected_count,
            "delivered_count": campaign.delivered_count,
            "blocked_count": campaign.blocked_count,
            "suppressed_count": campaign.suppressed_count,
            "failed_count": campaign.failed_count,
            "error_code": campaign.error_code,
            "created_at": campaign.created_at,
            "updated_at": campaign.updated_at,
        }

    async def create(self, body: CampaignCreate, *, actor: str) -> BroadcastCampaign:
        values = {
            "campaign_type": body.campaign_type,
            "text_snapshot": body.text,
            "media_type": body.media_type,
            "media_file_id": body.media_file_id,
            "cta_snapshot": [cta.model_dump() for cta in body.ctas],
            "segment_type": body.segment_type,
            "segment_parameters": body.segment_parameters,
            "attribution_window_days": body.attribution_window_days,
        }
        return await self._repository.create_campaign(
            actor=actor, values=values, reason=body.reason
        )

    async def get(self, public_id: str) -> BroadcastCampaign:
        campaign = await self._repository.get_campaign(public_id)
        if campaign is None:
            raise BroadcastServiceError("campaign_not_found")
        return campaign

    async def list(self, *, limit: int, offset: int) -> list[BroadcastCampaign]:
        return await self._repository.list_campaigns(limit=limit, offset=offset)

    async def update(
        self, public_id: str, body: CampaignUpdate, *, actor: str
    ) -> BroadcastCampaign:
        current = await self.get(public_id)
        values: dict[str, object] = {}
        if body.text is not None:
            values["text_snapshot"] = body.text.strip()
        if body.clear_media:
            values.update(media_type=None, media_file_id=None)
        elif body.media_type is not None:
            values.update(media_type=body.media_type, media_file_id=body.media_file_id)
        if body.ctas is not None:
            values["cta_snapshot"] = [cta.model_dump() for cta in body.ctas]
        segment_type = body.segment_type or current.segment_type
        if body.segment_type is not None:
            values["segment_type"] = body.segment_type
        if body.segment_parameters is not None:
            values["segment_parameters"] = body.segment_parameters
        elif body.segment_type is not None:
            values["segment_parameters"] = {}
        parameters = values.get("segment_parameters", current.segment_parameters or {})
        self._validate_segment(segment_type, parameters)
        if body.attribution_window_days is not None:
            values["attribution_window_days"] = body.attribution_window_days
        try:
            campaign = await self._repository.update_campaign(
                public_id,
                actor=actor,
                values=values,
                reason=body.reason,
            )
        except ValueError as error:
            raise BroadcastServiceError(str(error)) from None
        if campaign is None:
            raise BroadcastServiceError("campaign_not_found")
        return campaign

    @staticmethod
    def _validate_segment(segment_type: str, parameters: object) -> None:
        if segment_type == "inactive":
            if not isinstance(parameters, dict) or set(parameters) != {"inactive_days"}:
                raise BroadcastServiceError("inactive_days_required")
            value = parameters["inactive_days"]
            if type(value) is not int or not 1 <= value <= 3650:
                raise BroadcastServiceError("inactive_days_out_of_range")
        elif parameters:
            raise BroadcastServiceError("segment_parameters_not_allowed")

    async def estimate(
        self, public_id: str, *, actor: str, reason: str | None
    ) -> tuple[BroadcastCampaign, int]:
        try:
            result = await self._repository.estimate_recipients(
                public_id,
                actor=actor,
                reason=reason,
                now=datetime.now(timezone.utc),
            )
        except ValueError as error:
            raise BroadcastServiceError(str(error)) from None
        if result is None:
            raise BroadcastServiceError("campaign_not_found")
        return result

    async def test_send(
        self, public_id: str, *, actor: str, reason: str | None
    ) -> BroadcastCampaign:
        campaign = await self.get(public_id)
        admin_ids = settings.broadcast_admin_ids
        if not admin_ids:
            raise BroadcastServiceError("broadcast_admin_allowlist_empty")
        expected_version = campaign.content_version
        token = f"{campaign.public_id}.{expected_version}"
        message_ids: list[int] = []
        adapter = self._adapter or BroadcastTelegramAdapter()
        async with adapter:
            for chat_id in admin_ids:
                if campaign.media_type and campaign.media_file_id:
                    media = await adapter.send_media(
                        chat_id, campaign.media_type, campaign.media_file_id
                    )
                    message_ids.append(media.message_id)
                text = await adapter.send_text(
                    chat_id,
                    campaign.text_snapshot,
                    list(campaign.cta_snapshot),
                    token,
                    test=True,
                )
                message_ids.append(text.message_id)
        try:
            tested = await self._repository.mark_tested(
                public_id,
                expected_version=expected_version,
                actor=actor,
                reason=reason,
                message_ids=message_ids,
                now=datetime.now(timezone.utc),
            )
        except ValueError as error:
            raise BroadcastServiceError(str(error)) from None
        if tested is None:
            raise BroadcastServiceError("campaign_not_found")
        return tested

    async def launch(
        self,
        public_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        actor: str,
        reason: str | None,
    ) -> tuple[BroadcastCampaign, bool]:
        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        try:
            result = await self._repository.launch_campaign(
                public_id,
                expected_version=expected_version,
                idempotency_hash=key_hash,
                actor=actor,
                reason=reason,
                now=datetime.now(timezone.utc),
            )
        except (IntegrityError, ValueError) as error:
            code = "idempotency_key_conflict" if isinstance(error, IntegrityError) else str(error)
            raise BroadcastServiceError(code) from None
        if result is None:
            raise BroadcastServiceError("campaign_not_found")
        campaign, launched = result
        if launched and campaign.status == BroadcastCampaignState.QUEUED:
            from core.tasks import dispatch_broadcast_campaign

            dispatch_broadcast_campaign.delay(str(campaign.id))
        return campaign, launched

    async def cancel(
        self, public_id: str, *, actor: str, reason: str | None
    ) -> BroadcastCampaign:
        try:
            campaign = await self._repository.cancel_campaign(
                public_id,
                actor=actor,
                reason=reason,
                now=datetime.now(timezone.utc),
            )
        except ValueError as error:
            raise BroadcastServiceError(str(error)) from None
        if campaign is None:
            raise BroadcastServiceError("campaign_not_found")
        return campaign

    async def dispatch_campaign(self, campaign_id: uuid.UUID) -> dict[str, int]:
        processed = delivered = failed = 0
        adapter = self._adapter or BroadcastTelegramAdapter()
        async with adapter:
            while True:
                ids = await self._repository.list_dispatchable_delivery_ids(
                    campaign_id,
                    now=datetime.now(timezone.utc),
                    limit=settings.broadcast_delivery_batch_size,
                )
                if not ids:
                    break
                semaphore = asyncio.Semaphore(settings.broadcast_delivery_concurrency)

                async def run_one(delivery_id: uuid.UUID) -> str:
                    async with semaphore:
                        return await self._deliver_one(delivery_id, adapter)

                outcomes = await asyncio.gather(*(run_one(item) for item in ids))
                processed += len(outcomes)
                delivered += outcomes.count("delivered")
                failed += outcomes.count("failed")
        await self._repository.refresh_campaign(
            campaign_id, now=datetime.now(timezone.utc)
        )
        return {"processed": processed, "delivered": delivered, "failed": failed}

    async def _deliver_one(
        self, delivery_id: uuid.UUID, adapter: BroadcastTelegramAdapter
    ) -> str:
        claim = await self._repository.claim_delivery(
            delivery_id, now=datetime.now(timezone.utc)
        )
        if claim is None:
            return "skipped"
        try:
            if claim.media_type and claim.media_file_id and claim.media_message_id is None:
                if not await self._repository.recheck_claim(
                    claim.delivery_id, claim.attempt, now=datetime.now(timezone.utc)
                ):
                    return "skipped"
                media = await adapter.send_media(
                    claim.chat_id, claim.media_type, claim.media_file_id
                )
                if not await self._repository.save_media_progress(
                    claim.delivery_id, claim.attempt, media.message_id
                ):
                    return "skipped"
            if not await self._repository.recheck_claim(
                claim.delivery_id, claim.attempt, now=datetime.now(timezone.utc)
            ):
                return "skipped"
            text = await adapter.send_text(
                claim.chat_id,
                claim.text,
                claim.ctas,
                claim.click_token,
            )
            completed = await self._repository.complete_delivery(
                claim.delivery_id,
                claim.attempt,
                text.message_id,
                now=datetime.now(timezone.utc),
            )
            return "delivered" if completed else "skipped"
        except BroadcastTelegramError as error:
            now = datetime.now(timezone.utc)
            if error.blocked_reason:
                await self._repository.block_delivery(
                    claim.delivery_id,
                    claim.attempt,
                    code=error.code,
                    reason=error.blocked_reason,
                    now=now,
                )
            else:
                await self._repository.fail_delivery(
                    claim.delivery_id,
                    claim.attempt,
                    code=error.code,
                    retryable=error.retryable,
                    retry_after=error.retry_after,
                    now=now,
                )
            return "failed"
        except Exception:
            await self._repository.fail_delivery(
                claim.delivery_id,
                claim.attempt,
                code="delivery_internal_error",
                retryable=True,
                retry_after=None,
                now=datetime.now(timezone.utc),
            )
            return "failed"

    async def reconcile(self, *, limit: int = 20) -> dict[str, int]:
        campaign_ids = await self._repository.list_dispatchable_campaign_ids(
            now=datetime.now(timezone.utc), limit=limit
        )
        dispatched = 0
        from core.tasks import dispatch_broadcast_campaign

        for campaign_id in campaign_ids:
            dispatch_broadcast_campaign.delay(str(campaign_id))
            dispatched += 1
        return {"campaigns_dispatched": dispatched}

    async def record_click(
        self, token: str, cta_key: str, telegram_id: int
    ) -> str:
        if cta_key not in {"primary", "secondary"}:
            raise BroadcastServiceError("invalid_cta_key")
        destination = await self._repository.record_click(
            token, cta_key, telegram_id, now=datetime.now(timezone.utc)
        )
        if destination not in ALLOWED_DESTINATIONS:
            raise BroadcastServiceError("invalid_or_unowned_cta")
        return destination

    async def resolve_test_click(
        self, token: str, cta_key: str, telegram_id: int
    ) -> str:
        if telegram_id not in settings.broadcast_admin_ids:
            raise BroadcastServiceError("test_recipient_not_allowed")
        try:
            public_id, version_text = token.rsplit(".", 1)
            version = int(version_text)
        except (ValueError, AttributeError):
            raise BroadcastServiceError("invalid_test_cta") from None
        campaign = await self.get(public_id)
        if campaign.tested_version != version or campaign.content_version != version:
            raise BroadcastServiceError("stale_test_cta")
        cta = next(
            (item for item in campaign.cta_snapshot if item.get("key") == cta_key),
            None,
        )
        destination = cta.get("destination") if cta else None
        if destination not in ALLOWED_DESTINATIONS:
            raise BroadcastServiceError("invalid_test_cta")
        return str(destination)

    async def stats(self, public_id: str) -> dict:
        campaign = await self.get(public_id)
        counts = await self._repository.delivery_counts(campaign.id)
        clicks = await self._repository.click_counts(campaign.id)
        attributed = await self._repository.attributed_paid_order_count(campaign.id)
        return {
            "campaign_id": campaign.public_id,
            "content_version": campaign.content_version,
            "segment": {
                "type": campaign.segment_type,
                "parameters": campaign.segment_parameters or {},
            },
            "selected": campaign.selected_count,
            "queued": counts.get(BroadcastDeliveryState.QUEUED, 0),
            "delivered": counts.get(BroadcastDeliveryState.DELIVERED, 0),
            "blocked": counts.get(BroadcastDeliveryState.BLOCKED, 0),
            "suppressed_opt_out": counts.get(BroadcastDeliveryState.SUPPRESSED_OPT_OUT, 0),
            "suppressed_frequency": counts.get(BroadcastDeliveryState.SUPPRESSED_FREQUENCY, 0),
            "retryable_failures": counts.get(BroadcastDeliveryState.FAILED_RETRYABLE, 0),
            "terminal_failures": counts.get(BroadcastDeliveryState.FAILED_TERMINAL, 0),
            "ctas": clicks,
            "post_click_purchases": attributed,
        }

    async def set_preference(self, telegram_id: int, enabled: bool) -> bool:
        result = await self._repository.set_editorial_preference(telegram_id, enabled)
        if result is None:
            raise BroadcastServiceError("user_not_found")
        return result

    async def get_preference(self, telegram_id: int) -> bool:
        result = await self._repository.get_editorial_preference(telegram_id)
        if result is None:
            raise BroadcastServiceError("user_not_found")
        return result

    async def release_start_suppression(self, user_id: uuid.UUID) -> None:
        await self._repository.release_automatic_suppression(
            user_id, now=datetime.now(timezone.utc)
        )
