"""Channel-neutral use case for one durable daily Tarot card."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Callable

from core.arcana_data import ARCANA
from core.config import Settings, settings
from core.models import DailyTarotDraw, DailyTarotDrawState, User
from core.repositories.daily_tarot_draw import DailyTarotDrawRepository
from core.repositories.user import UserRepository
from core.services.ai import AIService
from core.services.daily_arcana import daily_arcana_number, personalize_arcana
from core.services.daily_tarot_timezone import (
    local_date_for_timezone,
    resolve_daily_tarot_timezone,
)


class DailyTarotResultKind(StrEnum):
    COMPLETED_NEW = "completed_new"
    COMPLETED_REUSED = "completed_reused"
    IN_PROGRESS = "in_progress"
    PROFILE_INCOMPLETE = "profile_incomplete"
    USER_UNAVAILABLE = "user_unavailable"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_NON_RETRYABLE = "failed_non_retryable"


@dataclass(frozen=True)
class DailyTarotRequest:
    user_id: uuid.UUID
    allow_retry: bool = False


@dataclass(frozen=True)
class DailyTarotApplicationResult:
    kind: DailyTarotResultKind
    draw_id: uuid.UUID | None = None
    local_date: str | None = None
    timezone_name: str | None = None
    arcana_number: int | None = None
    interpretation: str | None = None
    error_code: str | None = None


class DailyTarotApplicationService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        draw_repository: DailyTarotDrawRepository,
        ai_service: AIService,
        config: Settings = settings,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._users = user_repository
        self._draws = draw_repository
        self._ai = ai_service
        self._config = config
        self._now = now_provider or (lambda: datetime.now(timezone.utc))

    async def get_daily_card(self, request: DailyTarotRequest) -> DailyTarotApplicationResult:
        user = await self._users.get(request.user_id)
        if user is None or user.account_status != "active":
            return DailyTarotApplicationResult(kind=DailyTarotResultKind.USER_UNAVAILABLE)
        if not user.birth_date:
            return DailyTarotApplicationResult(kind=DailyTarotResultKind.PROFILE_INCOMPLETE)

        now = self._now()
        timezone_name = resolve_daily_tarot_timezone(user, self._config)
        local_date = local_date_for_timezone(now, timezone_name)
        draw = await self._draws.get_or_create(
            user_id=user.id, local_date=local_date, timezone_name=timezone_name
        )
        if draw.status == DailyTarotDrawState.COMPLETED:
            return self._completed(draw, DailyTarotResultKind.COMPLETED_REUSED)
        if draw.status == DailyTarotDrawState.FAILED:
            if draw.error_code in {"invalid_arcana", "invalid_daily_tarot_data"}:
                return self._failed(draw, DailyTarotResultKind.FAILED_NON_RETRYABLE)
            if not request.allow_retry:
                return self._failed(draw, DailyTarotResultKind.FAILED_RETRYABLE)

        arcana_number = draw.arcana_number or self._select_card(user, local_date)
        attempt = await self._draws.claim(
            draw.id,
            allow_retry=request.allow_retry,
            arcana_number=arcana_number,
            now=now,
            stale_before=now - timedelta(seconds=self._config.daily_tarot_claim_timeout_seconds),
        )
        if attempt is None:
            current = await self._draws.get(draw.id)
            if current is not None and current.status == DailyTarotDrawState.COMPLETED:
                return self._completed(current, DailyTarotResultKind.COMPLETED_REUSED)
            return self._in_progress(draw)

        try:
            arcana = ARCANA.get(arcana_number)
            if arcana is None:
                await self._draws.fail(draw.id, attempt=attempt, error_code="invalid_arcana", now=self._now())
                return DailyTarotApplicationResult(
                    kind=DailyTarotResultKind.FAILED_NON_RETRYABLE, draw_id=draw.id,
                    error_code="invalid_arcana",
                )
            interpretation = await self._ai.generate_tarot_daily_card(
                arcana_number=arcana_number,
                arcana_name=arcana["name"],
                date_str=local_date.strftime("%d.%m.%Y"),
                user_name=user.first_name or user.name or user.username or "друг",
                user_archetype_number=user.main_archetype_number or arcana_number,
                user_archetype_name=user.main_archetype or arcana["name"],
            )
            if not isinstance(interpretation, str) or not interpretation.strip():
                raise ValueError("empty_daily_tarot_interpretation")
            if not await self._draws.complete(
                draw.id, attempt=attempt, interpretation=interpretation, now=self._now()
            ):
                return self._in_progress(draw)
            completed = await self._draws.get(draw.id)
            return self._completed(completed or draw, DailyTarotResultKind.COMPLETED_NEW)
        except asyncio.CancelledError:
            await self._safe_fail(draw.id, attempt, "daily_tarot_cancelled")
            raise
        except ValueError as error:
            await self._safe_fail(draw.id, attempt, "invalid_daily_tarot_data")
            return DailyTarotApplicationResult(
                kind=DailyTarotResultKind.FAILED_NON_RETRYABLE, draw_id=draw.id,
                error_code=str(error),
            )
        except Exception:
            await self._safe_fail(draw.id, attempt, "daily_tarot_provider_failure")
            return DailyTarotApplicationResult(
                kind=DailyTarotResultKind.FAILED_RETRYABLE, draw_id=draw.id,
                error_code="daily_tarot_provider_failure",
            )

    @staticmethod
    def _select_card(user: User, local_date) -> int:
        if user.main_archetype_number:
            return personalize_arcana(local_date, user.main_archetype_number)
        return daily_arcana_number(local_date)

    @staticmethod
    def _completed(draw: DailyTarotDraw, kind: DailyTarotResultKind) -> DailyTarotApplicationResult:
        if draw.arcana_number is None or not draw.interpretation:
            return DailyTarotApplicationResult(
                kind=DailyTarotResultKind.FAILED_NON_RETRYABLE, draw_id=draw.id,
                error_code="completed_result_missing",
            )
        return DailyTarotApplicationResult(
            kind=kind, draw_id=draw.id, local_date=draw.local_date.isoformat(),
            timezone_name=draw.timezone_name, arcana_number=draw.arcana_number,
            interpretation=draw.interpretation,
        )

    @staticmethod
    def _in_progress(draw: DailyTarotDraw) -> DailyTarotApplicationResult:
        return DailyTarotApplicationResult(
            kind=DailyTarotResultKind.IN_PROGRESS, draw_id=draw.id,
            local_date=draw.local_date.isoformat(), timezone_name=draw.timezone_name,
            arcana_number=draw.arcana_number,
        )

    @staticmethod
    def _failed(draw: DailyTarotDraw, kind: DailyTarotResultKind) -> DailyTarotApplicationResult:
        return DailyTarotApplicationResult(
            kind=kind, draw_id=draw.id, local_date=draw.local_date.isoformat(),
            timezone_name=draw.timezone_name, arcana_number=draw.arcana_number,
            error_code=draw.error_code or "daily_tarot_failed",
        )

    async def _safe_fail(self, draw_id: uuid.UUID, attempt: int, error_code: str) -> None:
        try:
            await self._draws.fail(draw_id, attempt=attempt, error_code=error_code, now=self._now())
        except ValueError:
            pass
