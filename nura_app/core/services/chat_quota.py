from dataclasses import dataclass
from collections.abc import Callable
from datetime import datetime, time, timedelta, timezone
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update

from core.config import settings
from core.models import ChatMessageUsage, User
from core.schemas.chat import ChatQuotaState
from core.services.prompt_governance import PIN_FIELDS
from core.services.prompt_governance import (
    finalize_generation_metadata,
    resolve_active_bundle,
)


class ChatChannel(StrEnum):
    TELEGRAM = "telegram"
    WEB = "web"


class ChatUsageStatus(StrEnum):
    RESERVED = "reserved"
    RESULT_READY = "result_ready"
    CONSUMED = "consumed"
    RELEASED = "released"


class ChatDeliveryStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    SENDING = "sending"
    RETRYABLE = "retryable"
    DELIVERED = "delivered"
    AWAITING_ACK = "awaiting_ack"
    FAILED = "failed"


class QuotaReservationKind(StrEnum):
    RESERVED_NEW = "reserved_new"
    DUPLICATE_RESERVED = "duplicate_reserved"
    DUPLICATE_RESULT = "duplicate_result"
    DUPLICATE_RELEASED = "duplicate_released"
    EXHAUSTED = "exhausted"


RESERVATION_STALE_AFTER = timedelta(minutes=5)


@dataclass(frozen=True)
class QuotaReservation:
    kind: QuotaReservationKind
    usage_id: object | None
    state: ChatQuotaState
    response_text: str | None = None
    error_code: str | None = None
    delivery_status: str | None = None
    generation_metadata: dict | None = None


@dataclass(frozen=True)
class TelegramDeliveryClaim:
    usage_id: object
    attempt: int
    response_text: str
    chat_id: int
    total_chunks: int
    next_chunk_index: int


@dataclass(frozen=True)
class DeliveryAcknowledgement:
    usage_id: object
    status: str
    state: ChatQuotaState


class ChatQuotaService:
    """Shared durable request, result, and free-quota ledger."""

    def __init__(self, session_factory, *, now_provider: Callable[[], datetime] | None = None) -> None:
        self._session_factory = session_factory
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        value = self._now_provider()
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    @staticmethod
    def is_subscriber(*, tarot_subscription: bool, tarot_subscription_until: datetime | None,
                      subscription_status: str | None, subscription_until: datetime | None,
                      now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)

        def active(until: datetime | None) -> bool:
            return bool(until and (until if until.tzinfo else until.replace(tzinfo=timezone.utc)) > current)

        return (tarot_subscription and active(tarot_subscription_until)) or (
            subscription_status == "premium" and active(subscription_until)
        )

    @staticmethod
    def _subscriber_state() -> ChatQuotaState:
        return ChatQuotaState(access="subscriber", can_send=True, daily_limit=None, used=None, messages_left=None)

    @staticmethod
    def _free_state(
        consumed: int, reserved: int = 0, *, now: datetime | None = None
    ) -> ChatQuotaState:
        limit = settings.chat_free_message_limit
        left = max(0, limit - consumed - reserved)
        zone = ZoneInfo(settings.chat_quota_timezone)
        local_now = (now or datetime.now(timezone.utc)).astimezone(zone)
        reset_at = datetime.combine(
            local_now.date() + timedelta(days=1), time.min, tzinfo=zone
        ).astimezone(timezone.utc)
        return ChatQuotaState(
            access="free", can_send=left > 0, daily_limit=limit, used=consumed,
            messages_left=left, reset_at=reset_at, timezone=settings.chat_quota_timezone,
            code=None if left else "daily_limit_reached",
        )

    async def state(self, user_id: object, *, subscriber: bool) -> ChatQuotaState:
        if subscriber:
            return self._subscriber_state()
        async with self._session_factory() as session:
            await self._release_stale(session, user_id)
            consumed, reserved = await self._counts(session, user_id)
            await session.commit()
        return self._free_state(consumed, reserved, now=self._now())

    async def reserve(
        self,
        user_id: object,
        request_key: str,
        channel: ChatChannel,
        *,
        subscriber: bool,
        generation_metadata: dict | None = None,
    ) -> QuotaReservation:
        if generation_metadata is None:
            bundle = resolve_active_bundle("chat.free")
            generation_metadata = bundle.pin("chat.free")
            generation_metadata["requested_model"] = settings.deepseek_model
        async with self._session_factory() as session:
            await session.execute(select(User.id).where(User.id == user_id).with_for_update())
            await self._release_stale(session, user_id)
            usage = await session.scalar(select(ChatMessageUsage).where(
                ChatMessageUsage.user_id == user_id,
                ChatMessageUsage.request_key == request_key,
            ).with_for_update())
            if usage is not None:
                state = await self._state_in_session(session, user_id, subscriber)
                await session.commit()
                if usage.status in {ChatUsageStatus.RESULT_READY.value, ChatUsageStatus.CONSUMED.value}:
                    return QuotaReservation(
                        QuotaReservationKind.DUPLICATE_RESULT, usage.id, state,
                        usage.response_text, delivery_status=usage.delivery_status,
                        generation_metadata=usage.generation_metadata,
                    )
                if usage.status == ChatUsageStatus.RELEASED.value:
                    return QuotaReservation(QuotaReservationKind.DUPLICATE_RELEASED, usage.id, state,
                                            error_code=usage.error_code)
                return QuotaReservation(QuotaReservationKind.DUPLICATE_RESERVED, usage.id, state)
            state = await self._state_in_session(session, user_id, subscriber)
            if not subscriber and not state.can_send:
                await session.commit()
                return QuotaReservation(QuotaReservationKind.EXHAUSTED, None, state)
            usage = ChatMessageUsage(
                user_id=user_id,
                request_key=request_key,
                channel=channel.value,
                billable=not subscriber,
                status=ChatUsageStatus.RESERVED.value,
                generation_metadata=generation_metadata,
            )
            session.add(usage)
            await session.flush()
            state = await self._state_in_session(session, user_id, subscriber)
            await session.commit()
            return QuotaReservation(QuotaReservationKind.RESERVED_NEW, usage.id, state)

    async def store_result(
        self,
        usage_id: object,
        response_text: str,
        generation_metadata: dict | None = None,
    ) -> None:
        if not response_text or not response_text.strip():
            raise ValueError("quota_result_empty")
        async with self._session_factory() as session:
            usage = await session.get(ChatMessageUsage, usage_id, with_for_update=True)
            if usage is None or usage.status != ChatUsageStatus.RESERVED.value:
                raise RuntimeError("quota_result_not_reservable")
            if generation_metadata is None and isinstance(
                usage.generation_metadata, dict
            ):
                generation_metadata = finalize_generation_metadata(
                    usage.generation_metadata,
                    provider=None,
                    model=None,
                    generation_source="fallback",
                )
            if generation_metadata is None:
                raise RuntimeError("quota_prompt_metadata_missing")
            if not isinstance(usage.generation_metadata, dict) or any(
                usage.generation_metadata.get(field) != generation_metadata.get(field)
                for field in PIN_FIELDS
            ):
                raise RuntimeError("quota_prompt_pin_mismatch")
            usage.response_text = response_text
            usage.generation_metadata = generation_metadata
            usage.result_ready_at = self._now()
            usage.status = ChatUsageStatus.RESULT_READY.value
            usage.delivery_status = (
                ChatDeliveryStatus.AWAITING_ACK.value
                if usage.channel == ChatChannel.WEB.value
                else ChatDeliveryStatus.PENDING.value
            )
            usage.delivery_retryable = True
            usage.delivery_error_code = None
            await session.commit()

    async def consume(self, usage_id: object) -> ChatQuotaState:
        async with self._session_factory() as session:
            usage = await session.get(ChatMessageUsage, usage_id, with_for_update=True)
            if usage is None or usage.status not in {ChatUsageStatus.RESULT_READY.value, ChatUsageStatus.CONSUMED.value}:
                raise RuntimeError("quota_result_not_ready")
            if usage.status == ChatUsageStatus.RESULT_READY.value:
                usage.status = ChatUsageStatus.CONSUMED.value
                usage.consumed_at = self._now()
            state = await self._state_in_session(session, usage.user_id, not usage.billable)
            await session.commit()
        return state

    async def configure_telegram_delivery(
        self, usage_id: object, *, chat_id: int, total_chunks: int
    ) -> None:
        if total_chunks <= 0:
            raise ValueError("telegram_delivery_chunks_invalid")
        async with self._session_factory() as session:
            usage = await session.get(ChatMessageUsage, usage_id, with_for_update=True)
            if usage is None or usage.channel != ChatChannel.TELEGRAM.value:
                raise RuntimeError("telegram_delivery_not_found")
            if usage.status == ChatUsageStatus.CONSUMED.value:
                return
            if usage.status != ChatUsageStatus.RESULT_READY.value or not usage.response_text:
                raise RuntimeError("telegram_delivery_not_ready")
            if usage.delivery_total_chunks is not None and usage.delivery_total_chunks != total_chunks:
                raise RuntimeError("telegram_delivery_chunks_changed")
            usage.telegram_chat_id_snapshot = chat_id
            usage.delivery_total_chunks = total_chunks
            if usage.delivery_status != ChatDeliveryStatus.SENDING.value:
                usage.delivery_status = ChatDeliveryStatus.QUEUED.value
                usage.delivery_retryable = True
                usage.delivery_error_code = None
            await session.commit()

    async def claim_telegram_delivery(self, usage_id: object) -> TelegramDeliveryClaim | None:
        now = self._now()
        stale_before = now - timedelta(seconds=settings.telegram_delivery_claim_timeout_seconds)
        async with self._session_factory() as session:
            eligible = (
                ChatMessageUsage.delivery_status.in_((
                    ChatDeliveryStatus.QUEUED.value, ChatDeliveryStatus.RETRYABLE.value,
                ))
                | ((ChatMessageUsage.delivery_status == ChatDeliveryStatus.SENDING.value)
                   & (ChatMessageUsage.delivery_claimed_at < stale_before))
            )
            result = await session.execute(update(ChatMessageUsage).where(
                ChatMessageUsage.id == usage_id,
                ChatMessageUsage.channel == ChatChannel.TELEGRAM.value,
                ChatMessageUsage.status == ChatUsageStatus.RESULT_READY.value,
                eligible,
            ).values(
                delivery_status=ChatDeliveryStatus.SENDING.value,
                delivery_claimed_at=now,
                delivery_attempt_count=ChatMessageUsage.delivery_attempt_count + 1,
                delivery_retryable=True,
                delivery_failed_at=None,
                delivery_error_code=None,
            ).returning(ChatMessageUsage.delivery_attempt_count))
            attempt = result.scalar_one_or_none()
            if attempt is None:
                await session.commit()
                return None
            usage = await session.get(ChatMessageUsage, usage_id)
            await session.commit()
            if (
                usage is None or not usage.response_text or not usage.telegram_chat_id_snapshot
                or usage.delivery_total_chunks is None
            ):
                return None
            return TelegramDeliveryClaim(
                usage_id=usage.id, attempt=int(attempt), response_text=usage.response_text,
                chat_id=usage.telegram_chat_id_snapshot, total_chunks=usage.delivery_total_chunks,
                next_chunk_index=usage.delivery_next_chunk_index,
            )

    async def mark_telegram_chunk_delivered(
        self, usage_id: object, attempt: int, chunk_index: int
    ) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(update(ChatMessageUsage).where(
                ChatMessageUsage.id == usage_id,
                ChatMessageUsage.status == ChatUsageStatus.RESULT_READY.value,
                ChatMessageUsage.delivery_status == ChatDeliveryStatus.SENDING.value,
                ChatMessageUsage.delivery_attempt_count == attempt,
                ChatMessageUsage.delivery_next_chunk_index == chunk_index,
            ).values(delivery_next_chunk_index=chunk_index + 1))
            await session.commit()
            return result.rowcount == 1

    async def complete_telegram_delivery(self, usage_id: object, attempt: int) -> ChatQuotaState | None:
        async with self._session_factory() as session:
            user_id = await session.scalar(select(ChatMessageUsage.user_id).where(ChatMessageUsage.id == usage_id))
            if user_id is None:
                return None
            await session.execute(select(User.id).where(User.id == user_id).with_for_update())
            usage = await session.get(ChatMessageUsage, usage_id, with_for_update=True)
            if usage is None:
                return None
            if usage.status == ChatUsageStatus.CONSUMED.value:
                state = await self._state_in_session(session, usage.user_id, not usage.billable)
                await session.commit()
                return state
            if (
                usage.status != ChatUsageStatus.RESULT_READY.value
                or usage.delivery_status != ChatDeliveryStatus.SENDING.value
                or usage.delivery_attempt_count != attempt
                or usage.delivery_total_chunks is None
                or usage.delivery_next_chunk_index != usage.delivery_total_chunks
            ):
                await session.commit()
                return None
            now = self._now()
            usage.delivery_status = ChatDeliveryStatus.DELIVERED.value
            usage.delivery_retryable = False
            usage.delivery_claimed_at = None
            usage.delivery_completed_at = now
            usage.status = ChatUsageStatus.CONSUMED.value
            usage.consumed_at = now
            state = await self._state_in_session(session, usage.user_id, not usage.billable)
            await session.commit()
            return state

    async def fail_telegram_delivery(
        self, usage_id: object, attempt: int, *, error_code: str, retryable: bool
    ) -> ChatQuotaState | None:
        async with self._session_factory() as session:
            usage = await session.get(ChatMessageUsage, usage_id, with_for_update=True)
            if (
                usage is None or usage.status != ChatUsageStatus.RESULT_READY.value
                or usage.delivery_status != ChatDeliveryStatus.SENDING.value
                or usage.delivery_attempt_count != attempt
            ):
                await session.commit()
                return None
            now = self._now()
            usage.delivery_claimed_at = None
            usage.delivery_failed_at = now
            usage.delivery_error_code = error_code
            usage.delivery_retryable = retryable
            if retryable:
                usage.delivery_status = ChatDeliveryStatus.RETRYABLE.value
            else:
                usage.delivery_status = ChatDeliveryStatus.FAILED.value
                usage.status = ChatUsageStatus.RELEASED.value
                usage.released_at = now
                usage.release_reason = error_code
                usage.error_code = error_code
                usage.response_text = None
                usage.result_ready_at = None
            state = await self._state_in_session(session, usage.user_id, not usage.billable)
            await session.commit()
            return state

    async def acknowledge_web_delivery(
        self, user_id: object, usage_id: object
    ) -> DeliveryAcknowledgement | None:
        async with self._session_factory() as session:
            owner_id = await session.scalar(select(ChatMessageUsage.user_id).where(ChatMessageUsage.id == usage_id))
            if owner_id is None or owner_id != user_id:
                await session.commit()
                return None
            await session.execute(select(User.id).where(User.id == user_id).with_for_update())
            usage = await session.get(ChatMessageUsage, usage_id, with_for_update=True)
            if usage is None or usage.channel != ChatChannel.WEB.value:
                await session.commit()
                return None
            if usage.status == ChatUsageStatus.CONSUMED.value and usage.delivery_status == ChatDeliveryStatus.DELIVERED.value:
                state = await self._state_in_session(session, user_id, not usage.billable)
                await session.commit()
                return DeliveryAcknowledgement(usage.id, usage.delivery_status, state)
            if usage.status != ChatUsageStatus.RESULT_READY.value or usage.delivery_status != ChatDeliveryStatus.AWAITING_ACK.value:
                await session.commit()
                return None
            now = self._now()
            usage.delivery_status = ChatDeliveryStatus.DELIVERED.value
            usage.delivery_retryable = False
            usage.delivery_completed_at = now
            usage.status = ChatUsageStatus.CONSUMED.value
            usage.consumed_at = now
            state = await self._state_in_session(session, user_id, not usage.billable)
            await session.commit()
            return DeliveryAcknowledgement(usage.id, usage.delivery_status, state)

    async def list_reconcilable_telegram_delivery_ids(self, *, limit: int) -> list[object]:
        if limit <= 0 or limit > 100:
            return []
        now = self._now()
        stale_before = now - timedelta(seconds=settings.telegram_delivery_claim_timeout_seconds)
        expiry_before = now - timedelta(seconds=settings.chat_delivery_result_ttl_seconds)
        async with self._session_factory() as session:
            result = await session.execute(select(ChatMessageUsage.id).where(
                ChatMessageUsage.channel == ChatChannel.TELEGRAM.value,
                ChatMessageUsage.status == ChatUsageStatus.RESULT_READY.value,
                ChatMessageUsage.result_ready_at >= expiry_before,
                (
                    ChatMessageUsage.delivery_status.in_((
                        ChatDeliveryStatus.QUEUED.value, ChatDeliveryStatus.RETRYABLE.value,
                    ))
                    | ((ChatMessageUsage.delivery_status == ChatDeliveryStatus.SENDING.value)
                       & (ChatMessageUsage.delivery_claimed_at < stale_before))
                ),
            ).order_by(ChatMessageUsage.result_ready_at, ChatMessageUsage.id).limit(limit))
            return list(result.scalars().all())

    async def release(self, usage_id: object, *, reason: str) -> ChatQuotaState:
        async with self._session_factory() as session:
            usage = await session.get(ChatMessageUsage, usage_id, with_for_update=True)
            if usage is None:
                raise RuntimeError("quota_reservation_not_found")
            if usage.status == ChatUsageStatus.RESERVED.value:
                usage.status = ChatUsageStatus.RELEASED.value
                usage.released_at = self._now()
                usage.release_reason = reason
                usage.error_code = reason
            elif usage.status != ChatUsageStatus.RELEASED.value:
                raise RuntimeError("quota_reservation_not_releasable")
            state = await self._state_in_session(session, usage.user_id, not usage.billable)
            await session.commit()
        return state

    async def _state_in_session(self, session, user_id: object, subscriber: bool) -> ChatQuotaState:
        if subscriber:
            return self._subscriber_state()
        consumed, reserved = await self._counts(session, user_id)
        return self._free_state(consumed, reserved, now=self._now())

    def _daily_window(self) -> tuple[datetime, datetime]:
        zone = ZoneInfo(settings.chat_quota_timezone)
        local_now = self._now().astimezone(zone)
        start = datetime.combine(local_now.date(), time.min, tzinfo=zone)
        end = start + timedelta(days=1)
        return start.astimezone(timezone.utc), end.astimezone(timezone.utc)

    async def _counts(self, session, user_id: object) -> tuple[int, int]:
        start, end = self._daily_window()
        rows = await session.execute(select(ChatMessageUsage.status, func.count()).where(
            ChatMessageUsage.user_id == user_id,
            ChatMessageUsage.billable.is_(True),
            (
                ((ChatMessageUsage.status == ChatUsageStatus.CONSUMED.value)
                 & (ChatMessageUsage.consumed_at >= start)
                 & (ChatMessageUsage.consumed_at < end))
                | ChatMessageUsage.status.in_(
                    (ChatUsageStatus.RESERVED.value, ChatUsageStatus.RESULT_READY.value)
                )
            ),
        ).group_by(ChatMessageUsage.status))
        counts = dict(rows.all())
        return (
            int(counts.get(ChatUsageStatus.CONSUMED.value, 0)),
            int(counts.get(ChatUsageStatus.RESERVED.value, 0))
            + int(counts.get(ChatUsageStatus.RESULT_READY.value, 0)),
        )

    async def _release_stale(self, session, user_id: object) -> None:
        now = self._now()
        cutoff = now - RESERVATION_STALE_AFTER
        await session.execute(update(ChatMessageUsage).where(
            ChatMessageUsage.user_id == user_id,
            ChatMessageUsage.status == ChatUsageStatus.RESERVED.value,
            ChatMessageUsage.reserved_at < cutoff,
        ).values(status=ChatUsageStatus.RELEASED.value, released_at=now,
                 release_reason="stale_reservation", error_code="stale_reservation"))
        delivery_cutoff = now - timedelta(seconds=settings.chat_delivery_result_ttl_seconds)
        await session.execute(update(ChatMessageUsage).where(
            ChatMessageUsage.user_id == user_id,
            ChatMessageUsage.status == ChatUsageStatus.RESULT_READY.value,
            ChatMessageUsage.result_ready_at < delivery_cutoff,
            ChatMessageUsage.delivery_status.in_((
                ChatDeliveryStatus.PENDING.value, ChatDeliveryStatus.QUEUED.value,
                ChatDeliveryStatus.SENDING.value, ChatDeliveryStatus.RETRYABLE.value,
                ChatDeliveryStatus.AWAITING_ACK.value,
            )),
        ).values(
            status=ChatUsageStatus.RELEASED.value, released_at=now,
            release_reason="delivery_expired", error_code="delivery_expired",
            response_text=None, result_ready_at=None,
            delivery_status=ChatDeliveryStatus.FAILED.value,
            delivery_retryable=False, delivery_claimed_at=None,
            delivery_failed_at=now, delivery_error_code="delivery_expired",
        ))
