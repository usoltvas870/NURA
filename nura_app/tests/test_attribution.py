import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.handlers.start import cmd_start
from bot.states.onboarding_state import OnboardingStates
from core.models import AttributionLink, AttributionTouch
from core.repositories.attribution import AttributionRepository
from core.repositories.user import UserRepository
from core.services.attribution import (
    AttributionService,
    AttributionValidationError,
    normalize_code,
    normalize_metadata,
)


@pytest.fixture
def session_factory(db_engine):
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_active_link_creates_and_reuses_touch_with_snapshot(session_factory):
    service = AttributionService(session_factory)
    link = await service.create_link(
        code="Post_001", platform="telegram", source="channel", campaign="launch",
        content_id="post-42", topic="identity",
    )

    first = await service.process_telegram_start(
        telegram_id=1001, username="first", first_name="First", start_parameter="a_POST_001"
    )
    initial_seen = first.attribution_touch.first_seen_at
    second = await service.process_telegram_start(
        telegram_id=1001, username="renamed", first_name="Renamed", start_parameter="a_post_001"
    )

    touches = await AttributionRepository(session_factory).get_touches_for_user(first.user.id)
    assert link.code == "post_001"
    assert len(touches) == 1
    assert second.user.id == first.user.id
    assert second.user.username == "renamed"
    assert second.attribution_touch.first_seen_at == initial_seen
    assert second.attribution_touch.visit_count == 2
    assert second.attribution_touch.resolution_status == "resolved"
    assert second.attribution_touch.campaign == "launch"


@pytest.mark.asyncio
async def test_create_link_generates_valid_code_when_operator_omits_code(
    session_factory,
):
    link = await AttributionService(session_factory).create_link(
        platform="telegram",
        source="channel",
        campaign="launch",
        content_id="post-42",
        topic="identity",
    )

    assert normalize_code(link.code) == link.code
    assert 4 <= len(link.code) <= 24


@pytest.mark.asyncio
async def test_create_link_never_overwrites_duplicate_code(session_factory):
    service = AttributionService(session_factory)
    values = {
        "code": "unique_01",
        "platform": "telegram",
        "source": "channel",
        "campaign": "launch",
        "content_id": "post-42",
        "topic": "identity",
    }
    first = await service.create_link(**values)

    with pytest.raises(IntegrityError):
        await service.create_link(**values)

    assert first.code == "unique_01"


@pytest.mark.asyncio
async def test_unknown_inactive_and_invalid_codes_do_not_create_registry_links(session_factory):
    service = AttributionService(session_factory)
    inactive = await service.create_link(
        code="sleep_01", platform="telegram", source="channel", campaign="old",
        content_id="post-old", topic="identity",
    )
    async with session_factory() as session:
        inactive.is_active = False
        await session.merge(inactive)
        await session.commit()

    unknown = await service.process_telegram_start(
        telegram_id=1002, username=None, first_name=None, start_parameter="a_unknown_1"
    )
    inactive_result = await service.process_telegram_start(
        telegram_id=1003, username=None, first_name=None, start_parameter="a_sleep_01"
    )
    invalid = await service.process_telegram_start(
        telegram_id=1004, username=None, first_name=None, start_parameter="a_bad!"
    )

    assert unknown.attribution_touch.resolution_status == "unknown"
    assert inactive_result.attribution_touch.resolution_status == "inactive"
    assert inactive_result.attribution_touch.attribution_link_id == inactive.id
    assert inactive_result.attribution_touch.campaign is None
    assert invalid.start_kind == "invalid_attribution"
    async with session_factory() as session:
        assert len((await session.execute(AttributionLink.__table__.select())).all()) == 1


@pytest.mark.asyncio
async def test_unknown_touch_resolves_only_when_same_code_is_seen_again(session_factory):
    service = AttributionService(session_factory)
    unknown = await service.process_telegram_start(
        telegram_id=1010,
        username=None,
        first_name=None,
        start_parameter="a_later_01",
    )
    await service.create_link(
        code="later_01",
        platform="telegram",
        source="channel",
        campaign="later",
        content_id="post",
        topic="identity",
    )

    before_repeat = (
        await AttributionRepository(session_factory).get_touches_for_user(unknown.user.id)
    )[0]
    assert before_repeat.resolution_status == "unknown"
    assert before_repeat.campaign is None

    resolved = await service.process_telegram_start(
        telegram_id=1010,
        username=None,
        first_name=None,
        start_parameter="a_later_01",
    )

    assert resolved.attribution_touch.resolution_status == "resolved"
    assert resolved.attribution_touch.campaign == "later"
    assert resolved.attribution_touch.visit_count == 2


@pytest.mark.asyncio
async def test_persistence_failure_is_logged_and_returns_existing_user(
    session_factory, monkeypatch, caplog
):
    service = AttributionService(session_factory)
    user = await UserRepository(session_factory).get_or_create_by_telegram_id(
        1011, username="safe", first_name="Safe"
    )

    async def fail_record_touch(**_values):
        raise RuntimeError("temporary database error")

    monkeypatch.setattr(service._attribution, "record_touch", fail_record_touch)

    with caplog.at_level(logging.ERROR):
        result = await service.process_telegram_start(
            telegram_id=1011,
            username="safe",
            first_name="Safe",
            start_parameter="a_unknown_2",
        )

    assert result.user.id == user.id
    assert result.start_kind == "attribution_persistence_failed"
    assert "attribution_touch_persistence_failed" in caplog.text


@pytest.mark.asyncio
async def test_start_handler_records_unknown_attribution_and_continues_onboarding(
    session_factory,
):
    message = AsyncMock()
    message.from_user.id = 1012
    message.from_user.username = "new_user"
    message.from_user.first_name = "New"
    state = AsyncMock()
    command = MagicMock(args="a_unknown_3")

    with patch(
        "bot.handlers.start.get_async_sessionmaker",
        return_value=session_factory,
    ):
        await cmd_start(message, state, command)

    user = await UserRepository(session_factory).get_by_telegram_id(1012)
    touches = await AttributionRepository(session_factory).get_touches_for_user(user.id)

    assert len(touches) == 1
    assert touches[0].resolution_status == "unknown"
    assert touches[0].normalized_code == "unknown_3"
    message.answer.assert_awaited_once()
    state.set_state.assert_awaited_once_with(
        OnboardingStates.waiting_for_pd_consent
    )


@pytest.mark.asyncio
async def test_different_codes_and_users_have_distinct_touches(session_factory):
    service = AttributionService(session_factory)
    for code in ("code_one", "code_two"):
        await service.create_link(
            code=code, platform="telegram", source="channel", campaign=code,
            content_id="post", topic="identity",
        )
    first = await service.process_telegram_start(
        telegram_id=1005, username=None, first_name=None, start_parameter="a_code_one"
    )
    await service.process_telegram_start(
        telegram_id=1005, username=None, first_name=None, start_parameter="a_code_two"
    )
    other = await service.process_telegram_start(
        telegram_id=1006, username=None, first_name=None, start_parameter="a_code_one"
    )

    assert len(await AttributionRepository(session_factory).get_touches_for_user(first.user.id)) == 2
    assert len(await AttributionRepository(session_factory).get_touches_for_user(other.user.id)) == 1


@pytest.mark.parametrize("value", ["abc", "a" * 25, "bad!"])
def test_code_validation_rejects_invalid_values(value):
    with pytest.raises(AttributionValidationError):
        normalize_code(value)


def test_code_validation_normalizes_lowercase():
    assert normalize_code("  POST_001  ") == "post_001"


def test_platform_validation_matches_database_length():
    assert normalize_metadata("p" * 64, "platform", max_length=64) == "p" * 64
    with pytest.raises(AttributionValidationError):
        normalize_metadata("p" * 65, "platform", max_length=64)


def test_touch_user_foreign_key_cascades_on_account_deletion():
    foreign_key = next(iter(AttributionTouch.__table__.c.user_id.foreign_keys))
    assert foreign_key.ondelete == "CASCADE"


@pytest.mark.asyncio
async def test_existing_profile_values_are_not_cleared_by_missing_telegram_fields(session_factory):
    users = UserRepository(session_factory)
    created = await users.get_or_create_by_telegram_id(1007, username="known", first_name="Known")
    updated = await users.get_or_create_by_telegram_id(1007, username=None, first_name=None)

    assert updated.id == created.id
    assert updated.username == "known"
    assert updated.first_name == "Known"


@pytest.mark.asyncio
async def test_repeated_concurrent_touches_increment_visit_count(session_factory):
    service = AttributionService(session_factory)
    await service.create_link(
        code="race_code", platform="telegram", source="channel", campaign="race",
        content_id="post", topic="identity",
    )
    first = await service.process_telegram_start(
        telegram_id=1008, username=None, first_name=None, start_parameter="a_race_code"
    )
    await asyncio.gather(*[
        service.process_telegram_start(
            telegram_id=1008, username=None, first_name=None, start_parameter="a_race_code"
        )
        for _ in range(4)
    ])

    touches = await AttributionRepository(session_factory).get_touches_for_user(first.user.id)
    assert touches[0].visit_count == 5
