import asyncio
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from core.models import DailyTarotDraw, DailyTarotDrawState
from core.services.daily_tarot_application import (
    DailyTarotApplicationService,
    DailyTarotRequest,
    DailyTarotResultKind,
)
from core.services.daily_tarot_timezone import local_date_for_timezone


class MemoryUsers:
    def __init__(self, user):
        self.user = user

    async def get(self, user_id):
        return self.user if self.user and self.user.id == user_id else None


class MemoryDraws:
    def __init__(self):
        self.draws = {}

    async def get_or_create(self, *, user_id, local_date, timezone_name):
        key = user_id, local_date
        if key not in self.draws:
            self.draws[key] = DailyTarotDraw(
                id=uuid.uuid4(), user_id=user_id, local_date=local_date,
                timezone_name=timezone_name, status=DailyTarotDrawState.PENDING,
                attempt_count=0,
            )
        return self.draws[key]

    async def get(self, draw_id):
        return next((draw for draw in self.draws.values() if draw.id == draw_id), None)

    async def claim(self, draw_id, *, allow_retry, arcana_number, now, stale_before):
        draw = await self.get(draw_id)
        assert draw is not None
        if draw.status not in {DailyTarotDrawState.PENDING, DailyTarotDrawState.FAILED}:
            return None
        if draw.status == DailyTarotDrawState.FAILED and not allow_retry:
            return None
        if draw.status == DailyTarotDrawState.FAILED and draw.error_code not in {
            "daily_tarot_cancelled", "daily_tarot_provider_failure"
        }:
            return None
        draw.status = DailyTarotDrawState.GENERATING
        draw.arcana_number = draw.arcana_number or arcana_number
        draw.attempt_count += 1
        draw.claimed_at = now
        return draw.attempt_count

    async def complete(self, draw_id, *, attempt, interpretation, now):
        draw = await self.get(draw_id)
        if draw is None or draw.status != DailyTarotDrawState.GENERATING or draw.attempt_count != attempt:
            return False
        draw.status = DailyTarotDrawState.COMPLETED
        draw.interpretation = interpretation
        return True

    async def fail(self, draw_id, *, attempt, error_code, now):
        draw = await self.get(draw_id)
        if draw is None or draw.status != DailyTarotDrawState.GENERATING or draw.attempt_count != attempt:
            return False
        draw.status = DailyTarotDrawState.FAILED
        draw.error_code = error_code
        return True


class StubAI:
    def __init__(self, response="interpretation"):
        self.response = response
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate_tarot_daily_card(self, **kwargs):
        self.calls += 1
        self.started.set()
        if self.response == "wait":
            await self.release.wait()
            return "interpretation"
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _user(*, birth_date="01.01.1990"):
    return SimpleNamespace(
        id=uuid.uuid4(), account_status="active", birth_date=birth_date,
        main_archetype_number=1, main_archetype="Маг", first_name="Тест",
        name=None, username=None,
    )


def _service(user, draws, ai, *, now=None, default_timezone="Europe/Moscow"):
    return DailyTarotApplicationService(
        user_repository=MemoryUsers(user), draw_repository=draws, ai_service=ai,
        config=SimpleNamespace(
            default_daily_tarot_timezone=default_timezone,
            daily_tarot_claim_timeout_seconds=300,
        ),
        now_provider=lambda: now or datetime(2026, 7, 26, 20, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_same_day_reuses_persisted_card_and_interpretation_without_ai() -> None:
    user, draws, ai = _user(), MemoryDraws(), StubAI()
    service = _service(user, draws, ai)

    first = await service.get_daily_card(DailyTarotRequest(user_id=user.id, allow_retry=True))
    replay = await service.get_daily_card(DailyTarotRequest(user_id=user.id, allow_retry=True))

    assert first.kind == DailyTarotResultKind.COMPLETED_NEW
    assert replay.kind == DailyTarotResultKind.COMPLETED_REUSED
    assert replay.arcana_number == first.arcana_number
    assert replay.interpretation == first.interpretation
    assert ai.calls == 1
    assert len(draws.draws) == 1


@pytest.mark.asyncio
async def test_concurrent_request_returns_in_progress_and_only_one_ai_call() -> None:
    user, draws, ai = _user(), MemoryDraws(), StubAI("wait")
    service = _service(user, draws, ai)
    winner = asyncio.create_task(service.get_daily_card(DailyTarotRequest(user_id=user.id, allow_retry=True)))
    await ai.started.wait()

    loser = await service.get_daily_card(DailyTarotRequest(user_id=user.id, allow_retry=True))
    ai.release.set()
    completed = await winner

    assert loser.kind == DailyTarotResultKind.IN_PROGRESS
    assert completed.kind == DailyTarotResultKind.COMPLETED_NEW
    assert ai.calls == 1


@pytest.mark.asyncio
async def test_retry_keeps_selected_card_after_ai_failure() -> None:
    user, draws, ai = _user(), MemoryDraws(), StubAI(RuntimeError("unavailable"))
    service = _service(user, draws, ai)

    failed = await service.get_daily_card(DailyTarotRequest(user_id=user.id, allow_retry=True))
    draw = next(iter(draws.draws.values()))
    selected = draw.arcana_number
    ai.response = "recovered"
    retried = await service.get_daily_card(DailyTarotRequest(user_id=user.id, allow_retry=True))

    assert failed.kind == DailyTarotResultKind.FAILED_RETRYABLE
    assert retried.kind == DailyTarotResultKind.COMPLETED_NEW
    assert retried.arcana_number == selected
    assert ai.calls == 2


@pytest.mark.asyncio
async def test_incomplete_profile_creates_no_draw_and_calls_no_ai() -> None:
    user, draws, ai = _user(birth_date=None), MemoryDraws(), StubAI()

    result = await _service(user, draws, ai).get_daily_card(DailyTarotRequest(user_id=user.id))

    assert result.kind == DailyTarotResultKind.PROFILE_INCOMPLETE
    assert not draws.draws
    assert ai.calls == 0


def test_local_date_is_resolved_from_aware_utc_time() -> None:
    now = datetime(2026, 7, 26, 21, 30, tzinfo=timezone.utc)
    assert local_date_for_timezone(now, "Europe/Moscow") == date(2026, 7, 27)
    with pytest.raises(ValueError, match="timezone_aware"):
        local_date_for_timezone(datetime(2026, 7, 26, 21, 30), "Europe/Moscow")


@pytest.mark.asyncio
async def test_next_local_day_creates_a_new_draw() -> None:
    user, draws, ai = _user(), MemoryDraws(), StubAI()

    first = await _service(
        user, draws, ai, now=datetime(2026, 7, 26, 20, tzinfo=timezone.utc)
    ).get_daily_card(DailyTarotRequest(user_id=user.id, allow_retry=True))
    second = await _service(
        user, draws, ai, now=datetime(2026, 7, 26, 22, tzinfo=timezone.utc)
    ).get_daily_card(DailyTarotRequest(user_id=user.id, allow_retry=True))

    assert first.local_date == "2026-07-26"
    assert second.local_date == "2026-07-27"
    assert len(draws.draws) == 2
    assert ai.calls == 2


@pytest.mark.asyncio
async def test_empty_ai_result_is_non_retryable_and_never_completed() -> None:
    user, draws, ai = _user(), MemoryDraws(), StubAI("   ")

    result = await _service(user, draws, ai).get_daily_card(
        DailyTarotRequest(user_id=user.id, allow_retry=True)
    )
    draw = next(iter(draws.draws.values()))

    assert result.kind == DailyTarotResultKind.FAILED_NON_RETRYABLE
    assert draw.status == DailyTarotDrawState.FAILED
    assert draw.interpretation is None

    replay = await _service(user, draws, ai).get_daily_card(
        DailyTarotRequest(user_id=user.id, allow_retry=True)
    )
    assert replay.kind == DailyTarotResultKind.FAILED_NON_RETRYABLE
    assert ai.calls == 1


@pytest.mark.asyncio
async def test_persistence_rejection_does_not_report_false_success() -> None:
    class RejectingCompletionDraws(MemoryDraws):
        async def complete(self, *args, **kwargs):
            return False

    user, draws, ai = _user(), RejectingCompletionDraws(), StubAI()

    result = await _service(user, draws, ai).get_daily_card(
        DailyTarotRequest(user_id=user.id, allow_retry=True)
    )

    assert result.kind == DailyTarotResultKind.IN_PROGRESS
    assert result.interpretation is None


@pytest.mark.asyncio
async def test_completed_row_without_interpretation_is_consistency_failure() -> None:
    user, draws, ai = _user(), MemoryDraws(), StubAI()
    local_day = date(2026, 7, 26)
    draws.draws[(user.id, local_day)] = DailyTarotDraw(
        id=uuid.uuid4(), user_id=user.id, local_date=local_day,
        timezone_name="Europe/Moscow", status=DailyTarotDrawState.COMPLETED,
        arcana_number=1, interpretation=None, attempt_count=1,
    )

    result = await _service(user, draws, ai).get_daily_card(
        DailyTarotRequest(user_id=user.id)
    )

    assert result.kind == DailyTarotResultKind.FAILED_NON_RETRYABLE
    assert result.error_code == "completed_result_missing"
    assert ai.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("subscription_status", "has_tarot", "chat_quota_exhausted"),
    [("free", False, True), ("premium", False, True), ("free", True, True)],
)
async def test_access_is_independent_of_entitlements_and_chat_quota(
    subscription_status, has_tarot, chat_quota_exhausted
) -> None:
    user, draws, ai = _user(), MemoryDraws(), StubAI()
    user.subscription_status = subscription_status
    user.has_tarot = has_tarot
    user.chat_quota_exhausted = chat_quota_exhausted

    result = await _service(user, draws, ai).get_daily_card(
        DailyTarotRequest(user_id=user.id, allow_retry=True)
    )

    assert result.kind == DailyTarotResultKind.COMPLETED_NEW
    assert ai.calls == 1


@pytest.mark.asyncio
async def test_result_is_framework_neutral_dataclass() -> None:
    user, draws, ai = _user(), MemoryDraws(), StubAI()

    result = await _service(user, draws, ai).get_daily_card(
        DailyTarotRequest(user_id=user.id, allow_retry=True)
    )

    assert is_dataclass(result)
    assert set(asdict(result)) == {
        "kind", "draw_id", "local_date", "timezone_name", "arcana_number",
        "interpretation", "error_code",
    }


def test_timezone_resolution_valid_invalid_and_default() -> None:
    from core.services.daily_tarot_timezone import resolve_daily_tarot_timezone

    config = SimpleNamespace(default_daily_tarot_timezone="Europe/Moscow")
    user = _user()
    assert resolve_daily_tarot_timezone(user, config) == "Europe/Moscow"
    user.timezone = "Asia/Tokyo"
    assert resolve_daily_tarot_timezone(user, config) == "Asia/Tokyo"
    user.timezone = "not/a-zone"
    assert resolve_daily_tarot_timezone(user, config) == "Europe/Moscow"


def test_same_utc_instant_can_have_different_local_dates() -> None:
    now = datetime(2026, 7, 26, 23, 30, tzinfo=timezone.utc)
    assert local_date_for_timezone(now, "Pacific/Honolulu") == date(2026, 7, 26)
    assert local_date_for_timezone(now, "Asia/Tokyo") == date(2026, 7, 27)


def test_dst_fallback_does_not_duplicate_local_date() -> None:
    before = datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)
    after = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
    assert local_date_for_timezone(before, "America/New_York") == date(2026, 11, 1)
    assert local_date_for_timezone(after, "America/New_York") == date(2026, 11, 1)


@pytest.mark.asyncio
async def test_existing_draw_keeps_timezone_snapshot_after_default_changes() -> None:
    user, draws, ai = _user(), MemoryDraws(), StubAI()
    now = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)

    first = await _service(
        user, draws, ai, now=now, default_timezone="Europe/Moscow"
    ).get_daily_card(DailyTarotRequest(user_id=user.id, allow_retry=True))
    replay = await _service(
        user, draws, ai, now=now, default_timezone="UTC"
    ).get_daily_card(DailyTarotRequest(user_id=user.id, allow_retry=True))

    assert first.timezone_name == "Europe/Moscow"
    assert replay.timezone_name == "Europe/Moscow"
    assert len(draws.draws) == 1
