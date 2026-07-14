import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from redis.asyncio import Redis

from core.schemas.chat import ChatQuotaState


CHAT_DAILY_LIMIT = 5
CHAT_TIMEZONE = ZoneInfo("Europe/Moscow")
CHAT_TIMEZONE_NAME = "Europe/Moscow"
# DeepSeek responses normally complete well below this; the extra buffer also
# releases slots when a worker dies before it can refund the reservation.
RESERVATION_LEASE_MS = 5 * 60 * 1000
TTL_BUFFER = timedelta(minutes=5)

_STATE_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ARGV[1])
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
local active = tonumber(redis.call('ZCARD', KEYS[2]) or '0')
return {used, active}
"""

_RESERVE_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ARGV[1])
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
local active = tonumber(redis.call('ZCARD', KEYS[2]) or '0')
if used + active >= tonumber(ARGV[2]) then
  return {0, used, active}
end
redis.call('ZADD', KEYS[2], ARGV[3], ARGV[4])
redis.call('PEXPIREAT', KEYS[1], ARGV[5])
redis.call('PEXPIREAT', KEYS[2], ARGV[5])
return {1, used, active + 1}
"""

_COMMIT_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ARGV[1])
local removed = redis.call('ZREM', KEYS[2], ARGV[2])
if removed == 0 then
  local used = tonumber(redis.call('GET', KEYS[1]) or '0')
  local active = tonumber(redis.call('ZCARD', KEYS[2]) or '0')
  return {0, used, active}
end
local used = redis.call('INCR', KEYS[1])
redis.call('PEXPIREAT', KEYS[1], ARGV[3])
redis.call('PEXPIREAT', KEYS[2], ARGV[3])
local active = tonumber(redis.call('ZCARD', KEYS[2]) or '0')
return {1, used, active}
"""

_REFUND_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ARGV[1])
redis.call('ZREM', KEYS[2], ARGV[2])
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
local active = tonumber(redis.call('ZCARD', KEYS[2]) or '0')
return {used, active}
"""


@dataclass(frozen=True)
class QuotaReservation:
    token: str | None
    state: ChatQuotaState


class ChatQuotaService:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def is_subscriber(
        *,
        tarot_subscription: bool,
        tarot_subscription_until: datetime | None,
        subscription_status: str | None,
        subscription_until: datetime | None,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)

        def is_active(until: datetime | None) -> bool:
            if until is None:
                return False
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            return until > current

        return (
            bool(tarot_subscription) and is_active(tarot_subscription_until)
        ) or (
            subscription_status == "premium" and is_active(subscription_until)
        )

    @staticmethod
    def _window(now: datetime | None = None) -> tuple[str, datetime, int]:
        current = now.astimezone(CHAT_TIMEZONE) if now else datetime.now(CHAT_TIMEZONE)
        reset_at = datetime.combine(current.date() + timedelta(days=1), time.min, CHAT_TIMEZONE)
        expires_at_ms = int((reset_at + TTL_BUFFER).timestamp() * 1000)
        return current.date().isoformat(), reset_at, expires_at_ms

    @staticmethod
    def _keys(user_id: object, day: str) -> tuple[str, str]:
        return (f"chat_quota:{user_id}:{day}", f"chat_quota_reservations:{user_id}:{day}")

    @staticmethod
    def _subscriber_state() -> ChatQuotaState:
        return ChatQuotaState(access="subscriber", can_send=True, daily_limit=None, used=None,
                              messages_left=None, reset_at=None, timezone=CHAT_TIMEZONE_NAME)

    @staticmethod
    def _free_state(used: int, active: int, reset_at: datetime) -> ChatQuotaState:
        left = max(0, CHAT_DAILY_LIMIT - used - active)
        return ChatQuotaState(
            access="free", can_send=left > 0, daily_limit=CHAT_DAILY_LIMIT, used=used,
            messages_left=left, reset_at=reset_at, timezone=CHAT_TIMEZONE_NAME,
            code=None if left > 0 else "daily_limit_reached",
        )

    async def state(self, user_id: object, *, subscriber: bool, now: datetime | None = None) -> ChatQuotaState:
        if subscriber:
            return self._subscriber_state()
        day, reset_at, _ = self._window(now)
        quota_key, reservation_key = self._keys(user_id, day)
        current_ms = int((now.astimezone(CHAT_TIMEZONE) if now else datetime.now(CHAT_TIMEZONE)).timestamp() * 1000)
        used, active = await self._redis.eval(_STATE_SCRIPT, 2, quota_key, reservation_key, current_ms)
        return self._free_state(int(used), int(active), reset_at)

    async def reserve(self, user_id: object, *, subscriber: bool, now: datetime | None = None) -> QuotaReservation:
        if subscriber:
            return QuotaReservation(None, self._subscriber_state())
        day, reset_at, expires_at_ms = self._window(now)
        quota_key, reservation_key = self._keys(user_id, day)
        current = now.astimezone(CHAT_TIMEZONE) if now else datetime.now(CHAT_TIMEZONE)
        current_ms = int(current.timestamp() * 1000)
        token = uuid.uuid4().hex
        allowed, used, active = await self._redis.eval(
            _RESERVE_SCRIPT, 2, quota_key, reservation_key, current_ms, CHAT_DAILY_LIMIT,
            current_ms + RESERVATION_LEASE_MS, token, expires_at_ms,
        )
        state = self._free_state(int(used), int(active), reset_at)
        return QuotaReservation(token if int(allowed) else None, state)

    async def commit(self, user_id: object, token: str | None, *, subscriber: bool, now: datetime | None = None) -> ChatQuotaState:
        if subscriber:
            return self._subscriber_state()
        if not token:
            raise RuntimeError("Missing quota reservation")
        day, reset_at, expires_at_ms = self._window(now)
        quota_key, reservation_key = self._keys(user_id, day)
        current = now.astimezone(CHAT_TIMEZONE) if now else datetime.now(CHAT_TIMEZONE)
        committed, used, active = await self._redis.eval(
            _COMMIT_SCRIPT, 2, quota_key, reservation_key, int(current.timestamp() * 1000), token, expires_at_ms,
        )
        if not int(committed):
            raise RuntimeError("Quota reservation expired before commit")
        return self._free_state(int(used), int(active), reset_at)

    async def refund(self, user_id: object, token: str | None, *, subscriber: bool, now: datetime | None = None) -> ChatQuotaState:
        if subscriber:
            return self._subscriber_state()
        day, reset_at, _ = self._window(now)
        quota_key, reservation_key = self._keys(user_id, day)
        current = now.astimezone(CHAT_TIMEZONE) if now else datetime.now(CHAT_TIMEZONE)
        used, active = await self._redis.eval(
            _REFUND_SCRIPT, 2, quota_key, reservation_key, int(current.timestamp() * 1000), token or "",
        )
        return self._free_state(int(used), int(active), reset_at)
