import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import GuestProfile, MiniReportGeneration, MiniReportGenerationState, Report, ReportType, User
from core.repositories.mini_report_generation import MiniReportGenerationRepository
from core.services.mini_report_generation import (
    MINI_REPORT_GENERATION_VERSION,
    MiniReportGenerationService,
    build_mini_report_fingerprint,
)


def test_fingerprint_is_canonical_unicode_safe_and_does_not_expose_pii() -> None:
    canonical = build_mini_report_fingerprint(name="  Йван   Петров ", birth_date="1/2/2000")
    assert canonical == build_mini_report_fingerprint(name="Йван Петров", birth_date="01.02.2000")
    assert canonical != build_mini_report_fingerprint(name="Йван Петров", birth_date="02.02.2000")
    assert canonical != build_mini_report_fingerprint(name="Другая", birth_date="01.02.2000")
    assert canonical != build_mini_report_fingerprint(
        name="Йван Петров", birth_date="01.02.2000", generation_version="mini-v2"
    )
    assert len(canonical) == 64
    assert "Петров" not in canonical and "2000" not in canonical


@pytest.fixture
async def guest_profile(db_session: AsyncSession) -> GuestProfile:
    guest = GuestProfile(
        id=uuid.uuid4(),
        guest_token="guest-mini-generation",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db_session.add(guest)
    await db_session.commit()
    return guest


@pytest.fixture
async def generation_service(db_engine) -> MiniReportGenerationService:
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    return MiniReportGenerationService(MiniReportGenerationRepository(factory))


@pytest.mark.asyncio
async def test_owner_xor_and_owner_scoped_idempotency(
    db_session: AsyncSession, test_user: User, guest_profile: GuestProfile, generation_service: MiniReportGenerationService
) -> None:
    fingerprint = build_mini_report_fingerprint(name="Иван", birth_date="01.02.2000")
    user_generation = await generation_service.get_or_create_generation(
        fingerprint=fingerprint, user_id=test_user.id
    )
    assert user_generation.user_id == test_user.id and user_generation.guest_profile_id is None
    guest_generation = await generation_service.get_or_create_generation(
        fingerprint=fingerprint, guest_profile_id=guest_profile.id
    )
    assert guest_generation.guest_profile_id == guest_profile.id
    assert guest_generation.id != user_generation.id
    with pytest.raises(ValueError, match="exactly_one_owner_required"):
        await generation_service.get_or_create_generation(fingerprint=fingerprint)
    with pytest.raises(ValueError, match="exactly_one_owner_required"):
        await generation_service.get_or_create_generation(
            fingerprint=fingerprint, user_id=test_user.id, guest_profile_id=guest_profile.id
        )
    with pytest.raises(IntegrityError):
        db_session.add(
            MiniReportGeneration(
                id=uuid.uuid4(), fingerprint=fingerprint, generation_version=MINI_REPORT_GENERATION_VERSION
            )
        )
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_get_or_create_reuses_completed_and_failed_rows(
    test_user: User, generation_service: MiniReportGenerationService
) -> None:
    fingerprint = build_mini_report_fingerprint(name="Иван", birth_date="01.02.2000")
    generation = await generation_service.get_or_create_generation(fingerprint=fingerprint, user_id=test_user.id)
    assert (await generation_service.get_or_create_generation(fingerprint=fingerprint, user_id=test_user.id)).id == generation.id
    attempt = await generation_service.claim_generation(generation.id)
    assert attempt == 1
    completed = await generation_service.mark_completed(
        generation.id, expected_attempt_count=attempt
    )
    assert completed.status == MiniReportGenerationState.COMPLETED
    assert (await generation_service.get_or_create_generation(fingerprint=fingerprint, user_id=test_user.id)).id == generation.id
    failed_fingerprint = build_mini_report_fingerprint(name="Иван", birth_date="02.02.2000")
    failed = await generation_service.get_or_create_generation(fingerprint=failed_fingerprint, user_id=test_user.id)
    failed_attempt = await generation_service.claim_generation(failed.id)
    assert failed_attempt == 1
    failed = await generation_service.mark_failed(
        failed.id,
        expected_attempt_count=failed_attempt,
        error_code="provider_unavailable",
    )
    assert failed.status == MiniReportGenerationState.FAILED
    assert (await generation_service.get_or_create_generation(fingerprint=failed_fingerprint, user_id=test_user.id)).id == failed.id


@pytest.mark.asyncio
async def test_claim_complete_fail_and_retry_contract(
    test_user: User, generation_service: MiniReportGenerationService
) -> None:
    generation = await generation_service.get_or_create_generation(
        fingerprint=build_mini_report_fingerprint(name="Иван", birth_date="01.02.2000"), user_id=test_user.id
    )
    with pytest.raises(ValueError, match="invalid_mini_report_generation_transition"):
        await generation_service.mark_completed(generation.id, expected_attempt_count=1)
    first_attempt = await generation_service.claim_generation(generation.id)
    assert first_attempt == 1
    assert await generation_service.claim_generation(generation.id) is None
    assert not await generation_service.recover_stale_generation(
        generation.id, stale_before=datetime.now(timezone.utc) - timedelta(minutes=1)
    )
    assert await generation_service.recover_stale_generation(
        generation.id, stale_before=datetime.now(timezone.utc) + timedelta(minutes=1)
    )
    second_attempt = await generation_service.claim_generation(
        generation.id, allow_retry=True
    )
    assert second_attempt == 2
    failed = await generation_service.mark_failed(
        generation.id,
        expected_attempt_count=second_attempt,
        error_code="provider_unavailable",
    )
    assert failed.attempt_count == 2 and failed.error_detail is None
    assert await generation_service.claim_generation(generation.id) is None
    assert await generation_service.claim_generation(generation.id, allow_retry=True) == 3
    retried = await generation_service.get_or_create_generation(
        fingerprint=generation.fingerprint, user_id=test_user.id
    )
    assert retried.attempt_count == 3 and retried.started_at is not None


@pytest.mark.asyncio
async def test_completed_report_cannot_be_silently_replaced(
    db_session: AsyncSession, test_user: User, generation_service: MiniReportGenerationService
) -> None:
    report = Report(id=uuid.uuid4(), user_id=test_user.id, report_type=ReportType.MINI.value, token="mini-generation-report")
    db_session.add(report)
    await db_session.commit()
    generation = await generation_service.get_or_create_generation(
        fingerprint=build_mini_report_fingerprint(name="Иван", birth_date="01.02.2000"), user_id=test_user.id
    )
    attempt = await generation_service.claim_generation(generation.id)
    assert attempt == 1
    completed = await generation_service.mark_completed(
        generation.id, expected_attempt_count=attempt, report_id=report.id
    )
    assert (
        await generation_service.mark_completed(
            generation.id, expected_attempt_count=attempt, report_id=report.id
        )
    ).id == completed.id
    with pytest.raises(ValueError, match="invalid_mini_report_generation_transition"):
        await generation_service.mark_completed(
            generation.id,
            expected_attempt_count=attempt,
            report_id=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_sqlite_concurrent_claim_has_one_winner(
    test_user: User, generation_service: MiniReportGenerationService
) -> None:
    generation = await generation_service.get_or_create_generation(
        fingerprint=build_mini_report_fingerprint(name="Иван", birth_date="01.02.2000"), user_id=test_user.id
    )
    claims = await asyncio.gather(
        generation_service.claim_generation(generation.id), generation_service.claim_generation(generation.id)
    )
    assert sorted(claim for claim in claims if claim is not None) == [1]
    assert claims.count(None) == 1


@pytest.mark.asyncio
async def test_stale_worker_cannot_finish_a_retried_attempt(
    test_user: User, generation_service: MiniReportGenerationService
) -> None:
    generation = await generation_service.get_or_create_generation(
        fingerprint=build_mini_report_fingerprint(
            name="Иван", birth_date="01.02.2000"
        ),
        user_id=test_user.id,
    )
    stale_attempt = await generation_service.claim_generation(generation.id)
    assert stale_attempt == 1
    assert await generation_service.recover_stale_generation(
        generation.id, stale_before=datetime.now(timezone.utc) + timedelta(minutes=1)
    )
    active_attempt = await generation_service.claim_generation(
        generation.id, allow_retry=True
    )
    assert active_attempt == 2

    with pytest.raises(ValueError, match="invalid_mini_report_generation_transition"):
        await generation_service.mark_completed(
            generation.id, expected_attempt_count=stale_attempt
        )
    with pytest.raises(ValueError, match="invalid_mini_report_generation_transition"):
        await generation_service.mark_failed(
            generation.id,
            expected_attempt_count=stale_attempt,
            error_code="late_worker",
        )

    active = await generation_service.get_generation(generation.id)
    assert active is not None
    assert active.status == MiniReportGenerationState.GENERATING
    assert active.attempt_count == active_attempt
    assert (
        await generation_service.mark_completed(
            generation.id, expected_attempt_count=active_attempt
        )
    ).status == MiniReportGenerationState.COMPLETED
