import hmac
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone

from core.models import MiniReportGeneration
from core.config import settings
from core.repositories.mini_report_generation import MiniReportGenerationRepository

MINI_REPORT_GENERATION_VERSION = "mini-v1"


def build_mini_report_fingerprint(
    *, name: str, birth_date: str, generation_version: str = MINI_REPORT_GENERATION_VERSION
) -> str:
    """Hash canonical mini-report inputs without retaining raw PII in the key."""
    normalized_name = " ".join(
        unicodedata.normalize("NFC", name).strip().split()
    ).casefold()
    date_parts = re.fullmatch(r"\s*(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\s*", birth_date)
    if date_parts is None:
        raise ValueError("invalid_birth_date")
    day, month, year = (int(part) for part in date_parts.groups())
    if not normalized_name:
        raise ValueError("invalid_name")
    try:
        canonical_birth_date = datetime(year, month, day).date().isoformat()
    except ValueError as error:
        raise ValueError("invalid_birth_date") from error
    canonical = {
        "birth_date": canonical_birth_date,
        "generation_version": generation_version,
        "report_type": "mini",
        "name": normalized_name,
    }
    encoded = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hmac.digest(
        settings.secret_key.encode("utf-8"), encoded.encode("utf-8"), "sha256"
    ).hex()


class MiniReportGenerationService:
    """Small channel-neutral facade; runtime adapters are intentionally not wired here."""

    def __init__(self, repository: MiniReportGenerationRepository):
        self._repository = repository

    async def get_or_create_generation(
        self,
        *,
        fingerprint: str,
        user_id: uuid.UUID | None = None,
        guest_profile_id: uuid.UUID | None = None,
        generation_version: str = MINI_REPORT_GENERATION_VERSION,
    ) -> MiniReportGeneration:
        return await self._repository.get_or_create(
            fingerprint=fingerprint,
            user_id=user_id,
            guest_profile_id=guest_profile_id,
            generation_version=generation_version,
        )

    async def get_generation(self, generation_id: uuid.UUID) -> MiniReportGeneration | None:
        return await self._repository.get(generation_id)

    async def claim_generation(
        self, generation_id: uuid.UUID, *, allow_retry: bool = False
    ) -> int | None:
        return await self._repository.claim(
            generation_id, allow_retry=allow_retry, now=datetime.now(timezone.utc)
        )

    async def recover_stale_generation(
        self, generation_id: uuid.UUID, *, stale_before: datetime
    ) -> bool:
        return await self._repository.mark_stale_failed(
            generation_id, stale_before=stale_before, now=datetime.now(timezone.utc)
        )

    async def mark_completed(
        self,
        generation_id: uuid.UUID,
        *,
        expected_attempt_count: int,
        report_id: uuid.UUID | None = None,
    ) -> MiniReportGeneration:
        return await self._repository.mark_completed(
            generation_id,
            expected_attempt_count=expected_attempt_count,
            report_id=report_id,
            now=datetime.now(timezone.utc),
        )

    async def mark_failed(
        self, generation_id: uuid.UUID, *, expected_attempt_count: int, error_code: str
    ) -> MiniReportGeneration:
        return await self._repository.mark_failed(
            generation_id,
            expected_attempt_count=expected_attempt_count,
            error_code=error_code,
            now=datetime.now(timezone.utc),
        )

    async def finalize_result(
        self,
        generation_id: uuid.UUID,
        *,
        expected_attempt_count: int,
        matrix_data: dict,
        content: dict,
        report_token: str,
    ) -> uuid.UUID | None:
        return await self._repository.finalize_result(
            generation_id,
            expected_attempt_count=expected_attempt_count,
            matrix_data=matrix_data,
            content=content,
            report_token=report_token,
            now=datetime.now(timezone.utc),
        )
