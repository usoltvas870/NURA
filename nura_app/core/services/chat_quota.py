from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from sqlalchemy import func, select, update

from core.config import settings
from core.models import ChatMessageUsage, User
from core.schemas.chat import ChatQuotaState


class ChatChannel(StrEnum):
    TELEGRAM = "telegram"
    WEB = "web"


class ChatUsageStatus(StrEnum):
    RESERVED = "reserved"
    RESULT_READY = "result_ready"
    CONSUMED = "consumed"
    RELEASED = "released"


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


class ChatQuotaService:
    """Shared durable request, result, and free-quota ledger."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

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
    def _free_state(consumed: int, reserved: int = 0) -> ChatQuotaState:
        limit = settings.chat_free_message_limit
        left = max(0, limit - consumed - reserved)
        return ChatQuotaState(access="free", can_send=left > 0, daily_limit=limit, used=consumed,
                              messages_left=left, code=None if left else "lifetime_limit_reached")

    async def state(self, user_id: object, *, subscriber: bool) -> ChatQuotaState:
        if subscriber:
            return self._subscriber_state()
        async with self._session_factory() as session:
            await self._release_stale(session, user_id)
            consumed, reserved = await self._counts(session, user_id)
            await session.commit()
        return self._free_state(consumed, reserved)

    async def reserve(self, user_id: object, request_key: str, channel: ChatChannel,
                      *, subscriber: bool) -> QuotaReservation:
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
                    return QuotaReservation(QuotaReservationKind.DUPLICATE_RESULT, usage.id, state, usage.response_text)
                if usage.status == ChatUsageStatus.RELEASED.value:
                    return QuotaReservation(QuotaReservationKind.DUPLICATE_RELEASED, usage.id, state,
                                            error_code=usage.error_code)
                return QuotaReservation(QuotaReservationKind.DUPLICATE_RESERVED, usage.id, state)
            state = await self._state_in_session(session, user_id, subscriber)
            if not subscriber and not state.can_send:
                await session.commit()
                return QuotaReservation(QuotaReservationKind.EXHAUSTED, None, state)
            usage = ChatMessageUsage(user_id=user_id, request_key=request_key, channel=channel.value,
                                     billable=not subscriber, status=ChatUsageStatus.RESERVED.value)
            session.add(usage)
            await session.flush()
            state = await self._state_in_session(session, user_id, subscriber)
            await session.commit()
            return QuotaReservation(QuotaReservationKind.RESERVED_NEW, usage.id, state)

    async def store_result(self, usage_id: object, response_text: str) -> None:
        if not response_text or not response_text.strip():
            raise ValueError("quota_result_empty")
        async with self._session_factory() as session:
            usage = await session.get(ChatMessageUsage, usage_id, with_for_update=True)
            if usage is None or usage.status != ChatUsageStatus.RESERVED.value:
                raise RuntimeError("quota_result_not_reservable")
            usage.response_text = response_text
            usage.result_ready_at = datetime.now(timezone.utc)
            usage.status = ChatUsageStatus.RESULT_READY.value
            await session.commit()

    async def consume(self, usage_id: object) -> ChatQuotaState:
        async with self._session_factory() as session:
            usage = await session.get(ChatMessageUsage, usage_id, with_for_update=True)
            if usage is None or usage.status not in {ChatUsageStatus.RESULT_READY.value, ChatUsageStatus.CONSUMED.value}:
                raise RuntimeError("quota_result_not_ready")
            if usage.status == ChatUsageStatus.RESULT_READY.value:
                usage.status = ChatUsageStatus.CONSUMED.value
                usage.consumed_at = datetime.now(timezone.utc)
            state = await self._state_in_session(session, usage.user_id, not usage.billable)
            await session.commit()
        return state

    async def release(self, usage_id: object, *, reason: str) -> ChatQuotaState:
        async with self._session_factory() as session:
            usage = await session.get(ChatMessageUsage, usage_id, with_for_update=True)
            if usage is None:
                raise RuntimeError("quota_reservation_not_found")
            if usage.status == ChatUsageStatus.RESERVED.value:
                usage.status = ChatUsageStatus.RELEASED.value
                usage.released_at = datetime.now(timezone.utc)
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
        return self._free_state(consumed, reserved)

    @staticmethod
    async def _counts(session, user_id: object) -> tuple[int, int]:
        rows = await session.execute(select(ChatMessageUsage.status, func.count()).where(
            ChatMessageUsage.user_id == user_id,
            ChatMessageUsage.billable.is_(True),
            ChatMessageUsage.status.in_(
                (
                    ChatUsageStatus.CONSUMED.value,
                    ChatUsageStatus.RESERVED.value,
                    ChatUsageStatus.RESULT_READY.value,
                )
            ),
        ).group_by(ChatMessageUsage.status))
        counts = dict(rows.all())
        return (
            int(counts.get(ChatUsageStatus.CONSUMED.value, 0)),
            int(counts.get(ChatUsageStatus.RESERVED.value, 0))
            + int(counts.get(ChatUsageStatus.RESULT_READY.value, 0)),
        )

    @staticmethod
    async def _release_stale(session, user_id: object) -> None:
        cutoff = datetime.now(timezone.utc) - RESERVATION_STALE_AFTER
        await session.execute(update(ChatMessageUsage).where(
            ChatMessageUsage.user_id == user_id,
            ChatMessageUsage.status == ChatUsageStatus.RESERVED.value,
            ChatMessageUsage.reserved_at < cutoff,
        ).values(status=ChatUsageStatus.RELEASED.value, released_at=datetime.now(timezone.utc),
                 release_reason="stale_reservation", error_code="stale_reservation"))
