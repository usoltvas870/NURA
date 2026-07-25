import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import MiniReportGeneration, Report, ReportType, User
from core.services.my_reports import MyReportsService


@pytest.fixture
def db_factory(db_engine) -> async_sessionmaker:
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_completed_mini(
    factory: async_sessionmaker, user_id: uuid.UUID, *, created_at: datetime | None = None
) -> uuid.UUID:
    report_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            Report(
                id=report_id,
                user_id=user_id,
                report_type=ReportType.MINI.value,
                token=uuid.uuid4().hex,
                matrix_data={"center": 8},
                ai_analysis={"main_archetype": "Сила"},
                created_at=created_at or datetime.now(timezone.utc),
            )
        )
        session.add(
            MiniReportGeneration(
                id=uuid.uuid4(),
                user_id=user_id,
                fingerprint=uuid.uuid4().hex + uuid.uuid4().hex,
                generation_version="mini-v1",
                status="completed",
                report_id=report_id,
            )
        )
        await session.commit()
    return report_id


@pytest.mark.asyncio
async def test_my_reports_lists_only_owned_completed_mini_reports(db_factory) -> None:
    owner_id, other_id = uuid.uuid4(), uuid.uuid4()
    async with db_factory() as session:
        session.add_all([User(id=owner_id), User(id=other_id)])
        await session.commit()
    newest = await _seed_completed_mini(
        db_factory, owner_id, created_at=datetime(2026, 1, 2, tzinfo=timezone.utc)
    )
    await _seed_completed_mini(
        db_factory, owner_id, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    await _seed_completed_mini(db_factory, other_id)
    async with db_factory() as session:
        session.add(
            Report(
                id=uuid.uuid4(), user_id=owner_id, report_type=ReportType.FULL.value,
                token=uuid.uuid4().hex,
            )
        )
        await session.commit()

    page = await MyReportsService(db_factory).list_user_reports(owner_id, 0)

    assert page.total == 2
    assert page.items[0].report_id == newest
    assert all(item.report_type == "mini" for item in page.items)
    assert all("token" not in item.display_label.lower() for item in page.items)


@pytest.mark.asyncio
async def test_my_reports_idor_returns_same_neutral_absence(db_factory) -> None:
    owner_id, other_id = uuid.uuid4(), uuid.uuid4()
    async with db_factory() as session:
        session.add_all([User(id=owner_id), User(id=other_id)])
        await session.commit()
    report_id = await _seed_completed_mini(db_factory, owner_id)
    service = MyReportsService(db_factory)

    assert await service.get_user_report(other_id, report_id) is None
    assert await service.get_user_report(other_id, uuid.uuid4()) is None
    assert await service.prepare_repeated_delivery(other_id, report_id, "callback-1") is None


@pytest.mark.asyncio
async def test_my_reports_paginates_at_eight_items(db_factory) -> None:
    user_id = uuid.uuid4()
    async with db_factory() as session:
        session.add(User(id=user_id))
        await session.commit()
    for day in range(9):
        await _seed_completed_mini(
            db_factory,
            user_id,
            created_at=datetime(2026, 1, day + 1, tzinfo=timezone.utc),
        )

    first = await MyReportsService(db_factory).list_user_reports(user_id, 0)
    second = await MyReportsService(db_factory).list_user_reports(user_id, 1)

    assert first.total == 9
    assert first.total_pages == 2
    assert len(first.items) == 8
    assert len(second.items) == 1
    assert first.items[0].created_at > first.items[-1].created_at


@pytest.mark.asyncio
async def test_repeated_delivery_request_is_idempotent_per_callback(db_factory) -> None:
    user_id = uuid.uuid4()
    async with db_factory() as session:
        session.add(User(id=user_id))
        await session.commit()
    report_id = await _seed_completed_mini(db_factory, user_id)
    service = MyReportsService(db_factory)

    first = await service.prepare_repeated_delivery(user_id, report_id, "callback-1")
    duplicate = await service.prepare_repeated_delivery(user_id, report_id, "callback-1")
    new_callback = await service.prepare_repeated_delivery(user_id, report_id, "callback-2")

    assert first is not None and duplicate is not None and new_callback is not None
    assert duplicate.delivery_id == first.delivery_id
    assert new_callback.delivery_id != first.delivery_id
