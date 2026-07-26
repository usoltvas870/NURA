"""Timezone rules for the durable daily Tarot lifecycle."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.config import Settings
from core.models import User


def resolve_daily_tarot_timezone(user: User, config: Settings) -> str:
    """Use a valid stored IANA timezone when available, otherwise the validated default."""
    candidate = getattr(user, "timezone", None)
    if isinstance(candidate, str):
        try:
            ZoneInfo(candidate)
            return candidate
        except (ValueError, ZoneInfoNotFoundError):
            pass
    return config.default_daily_tarot_timezone


def local_date_for_timezone(now_utc: datetime, timezone_name: str) -> date:
    if now_utc.tzinfo is None:
        raise ValueError("daily_tarot_now_must_be_timezone_aware")
    return now_utc.astimezone(timezone.utc).astimezone(ZoneInfo(timezone_name)).date()
