import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import AttributionLink, AttributionTouch


class AttributionRepository:
    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    async def get_link_by_code(self, code: str) -> AttributionLink | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(AttributionLink).where(AttributionLink.code == code)
            )
            return result.scalar_one_or_none()

    async def create_link(self, **values: str | bool | None) -> AttributionLink:
        async with self._session_factory() as session:
            link = AttributionLink(id=uuid.uuid4(), **values)
            session.add(link)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                raise
            await session.refresh(link)
            return link

    async def get_touches_for_user(self, user_id: uuid.UUID) -> list[AttributionTouch]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(AttributionTouch)
                .where(AttributionTouch.user_id == user_id)
                .order_by(AttributionTouch.first_seen_at)
            )
            return list(result.scalars())

    async def record_touch(
        self,
        *,
        user_id: uuid.UUID,
        raw_start_parameter: str,
        normalized_code: str,
        resolution_status: str,
        link: AttributionLink | None,
    ) -> AttributionTouch:
        """Create one touch per user/code or atomically increment an existing one."""
        now = datetime.now(timezone.utc)
        async with self._session_factory() as session:
            updated = await session.execute(
                update(AttributionTouch)
                .where(
                    AttributionTouch.user_id == user_id,
                    AttributionTouch.normalized_code == normalized_code,
                )
                .values(last_seen_at=now, visit_count=AttributionTouch.visit_count + 1)
            )
            if updated.rowcount:
                result = await session.execute(
                    select(AttributionTouch).where(
                        AttributionTouch.user_id == user_id,
                        AttributionTouch.normalized_code == normalized_code,
                    )
                )
                touch = result.scalar_one()
                if touch.resolution_status == "unknown" and link is not None and link.is_active:
                    self._resolve_touch(touch, link)
                await session.commit()
                await session.refresh(touch)
                return touch

            touch = self._new_touch(
                user_id, raw_start_parameter, normalized_code, resolution_status, link, now
            )
            session.add(touch)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                updated = await session.execute(
                    update(AttributionTouch)
                    .where(
                        AttributionTouch.user_id == user_id,
                        AttributionTouch.normalized_code == normalized_code,
                    )
                    .values(last_seen_at=now, visit_count=AttributionTouch.visit_count + 1)
                )
                if not updated.rowcount:
                    raise
                result = await session.execute(
                    select(AttributionTouch).where(
                        AttributionTouch.user_id == user_id,
                        AttributionTouch.normalized_code == normalized_code,
                    )
                )
                touch = result.scalar_one()
                await session.commit()
            await session.refresh(touch)
            return touch

    @staticmethod
    def _new_touch(
        user_id: uuid.UUID,
        raw_start_parameter: str,
        normalized_code: str,
        resolution_status: str,
        link: AttributionLink | None,
        now: datetime,
    ) -> AttributionTouch:
        touch = AttributionTouch(
            id=uuid.uuid4(), user_id=user_id, raw_start_parameter=raw_start_parameter,
            normalized_code=normalized_code, resolution_status=resolution_status,
            first_seen_at=now, last_seen_at=now, visit_count=1,
        )
        if link is not None:
            touch.attribution_link_id = link.id
            if link.is_active:
                AttributionRepository._resolve_touch(touch, link)
        return touch

    @staticmethod
    def _resolve_touch(touch: AttributionTouch, link: AttributionLink) -> None:
        touch.attribution_link_id = link.id
        touch.resolution_status = "resolved"
        touch.platform = link.platform
        touch.source = link.source
        touch.campaign = link.campaign
        touch.content_id = link.content_id
        touch.topic = link.topic
