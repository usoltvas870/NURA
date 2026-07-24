"""Channel-neutral application use case for mini report generation."""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from core.models import MiniReportGenerationState
from core.fallbacks import FALLBACK_MINI
from core.repositories.guest import GuestProfileRepository
from core.repositories.report import ReportRepository
from core.services.ai import AIService
from core.services.matrix import MatrixService
from core.services.mini_report_generation import (
    MiniReportGenerationService,
    build_mini_report_fingerprint,
)
from core.services.report import ReportService

_MINI_CONTENT_FIELDS = frozenset(
    {"main_archetype", "core_strength", "emotional_conflict", "relationship_pattern", "financial_block"}
)


class MiniReportResultKind(StrEnum):
    COMPLETED_NEW = "completed_new"
    COMPLETED_REUSED = "completed_reused"
    IN_PROGRESS = "in_progress"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_NON_RETRYABLE = "failed_non_retryable"
    INVALID_INPUT = "invalid_input"


@dataclass(frozen=True)
class UserMiniReportSubject:
    user_id: uuid.UUID


@dataclass(frozen=True)
class GuestMiniReportSubject:
    guest_profile_id: uuid.UUID


MiniReportSubject = UserMiniReportSubject | GuestMiniReportSubject


@dataclass(frozen=True)
class MiniReportRequest:
    owner: MiniReportSubject
    name: str
    birth_date: str
    allow_retry: bool = False


@dataclass(frozen=True)
class MiniReportApplicationResult:
    kind: MiniReportResultKind
    generation_id: uuid.UUID | None = None
    report_id: uuid.UUID | None = None
    guest_profile_id: uuid.UUID | None = None
    content: dict[str, Any] | None = None
    matrix_data: dict[str, Any] | None = None
    error_code: str | None = None


class MiniReportApplicationService:
    """Coordinates validation, idempotency, generation and durable result storage."""

    def __init__(
        self,
        generation_service: MiniReportGenerationService,
        report_repository: ReportRepository,
        guest_repository: GuestProfileRepository,
    ) -> None:
        self._generation_service = generation_service
        self._report_repository = report_repository
        self._guest_repository = guest_repository

    async def generate(self, request: MiniReportRequest) -> MiniReportApplicationResult:
        try:
            name, birth_date = self._normalize_input(request.name, request.birth_date)
        except ValueError as error:
            return MiniReportApplicationResult(
                kind=MiniReportResultKind.INVALID_INPUT, error_code=str(error)
            )

        try:
            user_id, guest_profile_id = self._owner_ids(request.owner)
        except ValueError as error:
            return MiniReportApplicationResult(
                kind=MiniReportResultKind.INVALID_INPUT, error_code=str(error)
            )
        if guest_profile_id is not None and await self._guest_repository.get(guest_profile_id) is None:
            return MiniReportApplicationResult(
                kind=MiniReportResultKind.INVALID_INPUT, error_code="guest_profile_not_found"
            )

        fingerprint = build_mini_report_fingerprint(name=name, birth_date=birth_date)
        generation = await self._generation_service.get_or_create_generation(
            fingerprint=fingerprint, user_id=user_id, guest_profile_id=guest_profile_id
        )

        if generation.status == MiniReportGenerationState.COMPLETED:
            return await self._load_completed(
                generation.id, generation.report_id, user_id, guest_profile_id
            )
        if generation.status == MiniReportGenerationState.GENERATING:
            return self._in_progress(generation.id)
        if generation.status == MiniReportGenerationState.FAILED and not request.allow_retry:
            return MiniReportApplicationResult(
                kind=MiniReportResultKind.FAILED_RETRYABLE,
                generation_id=generation.id,
                error_code=generation.error_code or "generation_failed",
            )

        attempt_count = await self._generation_service.claim_generation(
            generation.id, allow_retry=request.allow_retry
        )
        if attempt_count is None:
            return self._in_progress(generation.id)

        try:
            matrix = MatrixService.calculate(birth_date)
            content = await AIService.generate_mini_analysis(birth_date, matrix)
            if content == FALLBACK_MINI:
                raise RuntimeError("mini_analysis_fallback")
            matrix_data = matrix.model_dump()
            report_id = await self._generation_service.finalize_result(
                generation.id,
                expected_attempt_count=attempt_count,
                matrix_data=matrix_data,
                content=content,
                report_token=ReportService.generate_token(),
            )
        except ValueError:
            await self._mark_failed(generation.id, attempt_count, "invalid_generation_data")
            return MiniReportApplicationResult(
                kind=MiniReportResultKind.FAILED_NON_RETRYABLE,
                generation_id=generation.id,
                error_code="invalid_generation_data",
            )
        except Exception:
            await self._mark_failed(generation.id, attempt_count, "generation_provider_failure")
            return MiniReportApplicationResult(
                kind=MiniReportResultKind.FAILED_RETRYABLE,
                generation_id=generation.id,
                error_code="generation_provider_failure",
            )

        return MiniReportApplicationResult(
            kind=MiniReportResultKind.COMPLETED_NEW,
            generation_id=generation.id,
            report_id=report_id,
            guest_profile_id=guest_profile_id,
            content=content,
            matrix_data=matrix_data,
        )

    async def _load_completed(
        self,
        generation_id: uuid.UUID,
        report_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        guest_profile_id: uuid.UUID | None,
    ) -> MiniReportApplicationResult:
        if user_id is not None:
            report = await self._report_repository.get(report_id) if report_id is not None else None
            if report is not None and self._is_valid_content(report.ai_analysis) and isinstance(report.matrix_data, dict):
                return MiniReportApplicationResult(
                    kind=MiniReportResultKind.COMPLETED_REUSED,
                    generation_id=generation_id,
                    report_id=report.id,
                    content=report.ai_analysis,
                    matrix_data=report.matrix_data,
                )
        elif guest_profile_id is not None:
            guest = await self._guest_repository.get(guest_profile_id)
            payload = guest.report_data if guest is not None else None
            if isinstance(payload, dict) and isinstance(payload.get("matrix_data"), dict):
                content = {key: value for key, value in payload.items() if key != "matrix_data"}
                if self._is_valid_content(content):
                    return MiniReportApplicationResult(
                        kind=MiniReportResultKind.COMPLETED_REUSED,
                        generation_id=generation_id,
                        guest_profile_id=guest_profile_id,
                        content=content,
                        matrix_data=payload["matrix_data"],
                    )
        return MiniReportApplicationResult(
            kind=MiniReportResultKind.FAILED_NON_RETRYABLE,
            generation_id=generation_id,
            error_code="completed_result_missing",
        )

    async def _mark_failed(self, generation_id: uuid.UUID, attempt_count: int, error_code: str) -> None:
        try:
            await self._generation_service.mark_failed(
                generation_id, expected_attempt_count=attempt_count, error_code=error_code
            )
        except ValueError:
            pass

    @staticmethod
    def _normalize_input(name: str, birth_date: str) -> tuple[str, str]:
        normalized_name = " ".join(unicodedata.normalize("NFC", name).strip().split())
        if not normalized_name or len(normalized_name) > 128 or any(ord(char) < 32 for char in normalized_name):
            raise ValueError("invalid_name")
        matched = re.fullmatch(r"\s*(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\s*", birth_date)
        if matched is None:
            raise ValueError("invalid_birth_date")
        try:
            parsed = datetime(*(int(part) for part in reversed(matched.groups()))).date()
        except ValueError as error:
            raise ValueError("invalid_birth_date") from error
        return normalized_name, parsed.strftime("%d.%m.%Y")

    @staticmethod
    def _owner_ids(owner: MiniReportSubject) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        if isinstance(owner, UserMiniReportSubject):
            return owner.user_id, None
        if isinstance(owner, GuestMiniReportSubject):
            return None, owner.guest_profile_id
        raise ValueError("invalid_owner")

    @staticmethod
    def _in_progress(generation_id: uuid.UUID) -> MiniReportApplicationResult:
        return MiniReportApplicationResult(
            kind=MiniReportResultKind.IN_PROGRESS, generation_id=generation_id
        )

    @staticmethod
    def _is_valid_content(content: object) -> bool:
        return isinstance(content, dict) and all(
            isinstance(content.get(field), str) and content[field] for field in _MINI_CONTENT_FIELDS
        )
