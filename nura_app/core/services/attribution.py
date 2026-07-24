import re
import secrets
import logging
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import AttributionLink, AttributionTouch, User
from core.repositories.attribution import AttributionRepository
from core.repositories.user import UserRepository

CODE_PATTERN = re.compile(r"[a-z0-9_-]{4,24}")
REQUIRED_METADATA_FIELDS = ("platform", "source", "campaign", "content_id", "topic")
logger = logging.getLogger(__name__)


class AttributionValidationError(ValueError):
    pass


def normalize_code(value: str) -> str:
    code = value.strip().lower()
    if not CODE_PATTERN.fullmatch(code):
        raise AttributionValidationError("invalid attribution code")
    return code


def normalize_metadata(
    value: str,
    field: str,
    *,
    required: bool = True,
    max_length: int = 128,
) -> str | None:
    normalized = value.strip()
    if required and not normalized:
        raise AttributionValidationError(f"{field} is required")
    if len(normalized) > max_length:
        raise AttributionValidationError(f"{field} is too long")
    return normalized or None


@dataclass(frozen=True)
class StartProcessingResult:
    user: User
    start_kind: str
    attribution_touch: AttributionTouch | None = None


class AttributionService:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        user_repository: UserRepository | None = None,
    ):
        self._users = user_repository or UserRepository(session_factory)
        self._attribution = AttributionRepository(session_factory)

    async def create_link(
        self, *, code: str | None = None, platform: str, source: str, campaign: str,
        content_id: str, topic: str, label: str | None = None,
    ) -> AttributionLink:
        values = {
            "platform": normalize_metadata(platform, "platform", max_length=64),
            "source": normalize_metadata(source, "source"),
            "campaign": normalize_metadata(campaign, "campaign"),
            "content_id": normalize_metadata(content_id, "content_id"),
            "topic": normalize_metadata(topic, "topic"),
            "label": normalize_metadata(label or "", "label", required=False),
            "is_active": True,
        }
        if code is not None:
            values["code"] = normalize_code(code)
            return await self._attribution.create_link(**values)
        for _ in range(5):
            values["code"] = secrets.token_urlsafe(8).lower().replace("-", "_")[:10]
            try:
                return await self._attribution.create_link(**values)
            except IntegrityError:
                continue
        raise RuntimeError("could not generate a unique attribution code")

    async def process_telegram_start(
        self, *, telegram_id: int, username: str | None, first_name: str | None,
        start_parameter: str | None,
    ) -> StartProcessingResult:
        if type(telegram_id) is not int or not 0 < telegram_id < 2**63:
            raise ValueError("invalid telegram identity")
        user = await self._users.get_or_create_by_telegram_id(
            telegram_id, username=username, first_name=first_name
        )
        if not start_parameter:
            return StartProcessingResult(user=user, start_kind="empty")
        if start_parameter.startswith("a_"):
            code_text = start_parameter[2:]
            try:
                code = normalize_code(code_text)
            except AttributionValidationError:
                return StartProcessingResult(user=user, start_kind="invalid_attribution")
            try:
                link = await self._attribution.get_link_by_code(code)
                status = "unknown" if link is None else ("resolved" if link.is_active else "inactive")
                touch = await self._attribution.record_touch(
                    user_id=user.id, raw_start_parameter=start_parameter,
                    normalized_code=code, resolution_status=status, link=link,
                )
            except Exception:
                logger.exception("attribution_touch_persistence_failed")
                return StartProcessingResult(user=user, start_kind="attribution_persistence_failed")
            return StartProcessingResult(user=user, start_kind="attribution", attribution_touch=touch)
        if start_parameter.startswith("ref_"):
            return StartProcessingResult(user=user, start_kind="referral")
        if start_parameter.startswith("link_"):
            return StartProcessingResult(user=user, start_kind="link")
        return StartProcessingResult(user=user, start_kind="legacy_or_unknown")
