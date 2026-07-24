import re
import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.models import GuestProfile, MiniReportGeneration, MiniReportGenerationState, Report, ReportType


class MiniReportGenerationRepository:
    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    @staticmethod
    def _validate_owner(
        user_id: uuid.UUID | None, guest_profile_id: uuid.UUID | None
    ) -> None:
        if (user_id is None) == (guest_profile_id is None):
            raise ValueError("exactly_one_owner_required")

    async def get(self, generation_id: uuid.UUID) -> MiniReportGeneration | None:
        async with self._session_factory() as session:
            return await session.get(MiniReportGeneration, generation_id)

    async def get_or_create(
        self,
        *,
        fingerprint: str,
        generation_version: str,
        user_id: uuid.UUID | None = None,
        guest_profile_id: uuid.UUID | None = None,
    ) -> MiniReportGeneration:
        self._validate_owner(user_id, guest_profile_id)
        for _ in range(3):
            async with self._session_factory() as session:
                generation = MiniReportGeneration(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    guest_profile_id=guest_profile_id,
                    fingerprint=fingerprint,
                    generation_version=generation_version,
                )
                session.add(generation)
                try:
                    await session.commit()
                    await session.refresh(generation)
                    return generation
                except IntegrityError:
                    await session.rollback()
                    existing = await self._get_by_owner_key(
                        session, user_id, guest_profile_id, fingerprint, generation_version
                    )
                    if existing is not None:
                        return existing
        raise RuntimeError("mini_report_generation_conflict_unresolved")

    async def claim(
        self, generation_id: uuid.UUID, *, allow_retry: bool, now: datetime
    ) -> int | None:
        eligible_states = [MiniReportGenerationState.PENDING]
        if allow_retry:
            eligible_states.append(MiniReportGenerationState.FAILED)
        async with self._session_factory() as session:
            result = await session.execute(
                update(MiniReportGeneration)
                .where(
                    MiniReportGeneration.id == generation_id,
                    MiniReportGeneration.status.in_(eligible_states),
                )
                .values(
                    status=MiniReportGenerationState.GENERATING,
                    attempt_count=MiniReportGeneration.attempt_count + 1,
                    started_at=now,
                    failed_at=None,
                    error_code=None,
                    error_detail=None,
                )
                .returning(MiniReportGeneration.attempt_count)
            )
            attempt_count = result.scalar_one_or_none()
            await session.commit()
            return attempt_count

    async def mark_completed(
        self,
        generation_id: uuid.UUID,
        *,
        expected_attempt_count: int,
        report_id: uuid.UUID | None,
        now: datetime,
    ) -> MiniReportGeneration:
        async with self._session_factory() as session:
            result = await session.execute(
                update(MiniReportGeneration)
                .where(
                    MiniReportGeneration.id == generation_id,
                    MiniReportGeneration.status == MiniReportGenerationState.GENERATING,
                    MiniReportGeneration.attempt_count == expected_attempt_count,
                )
                .values(
                    status=MiniReportGenerationState.COMPLETED,
                    report_id=report_id,
                    completed_at=now,
                    failed_at=None,
                    error_code=None,
                    error_detail=None,
                )
            )
            if result.rowcount == 1:
                await session.commit()
                completed = await session.get(MiniReportGeneration, generation_id)
                assert completed is not None
                return completed
            existing = (
                await session.execute(
                    select(
                        MiniReportGeneration.status,
                        MiniReportGeneration.report_id,
                        MiniReportGeneration.attempt_count,
                    ).where(MiniReportGeneration.id == generation_id)
                )
            ).one_or_none()
            await session.rollback()
            if existing is None:
                raise ValueError("mini_report_generation_not_found")
            if (
                existing.status == MiniReportGenerationState.COMPLETED
                and existing.report_id == report_id
                and existing.attempt_count == expected_attempt_count
            ):
                completed = await self.get(generation_id)
                assert completed is not None
                return completed
            raise ValueError("invalid_mini_report_generation_transition")

    async def mark_failed(
        self,
        generation_id: uuid.UUID,
        *,
        expected_attempt_count: int,
        error_code: str,
        now: datetime,
    ) -> MiniReportGeneration:
        if not re.fullmatch(r"[a-z0-9_]{1,64}", error_code):
            raise ValueError("invalid_mini_report_error_code")
        async with self._session_factory() as session:
            result = await session.execute(
                update(MiniReportGeneration)
                .where(
                    MiniReportGeneration.id == generation_id,
                    MiniReportGeneration.status == MiniReportGenerationState.GENERATING,
                    MiniReportGeneration.attempt_count == expected_attempt_count,
                )
                .values(
                    status=MiniReportGenerationState.FAILED,
                    failed_at=now,
                    error_code=error_code,
                    error_detail=None,
                )
            )
            if result.rowcount != 1:
                await session.rollback()
                raise ValueError("invalid_mini_report_generation_transition")
            await session.commit()
            failed = await session.get(MiniReportGeneration, generation_id)
            assert failed is not None
            return failed

    async def finalize_result(
        self,
        generation_id: uuid.UUID,
        *,
        expected_attempt_count: int,
        matrix_data: dict,
        content: dict,
        report_token: str,
        now: datetime,
    ) -> uuid.UUID | None:
        """Persist the owner result and complete its claimed attempt atomically."""
        async with self._session_factory() as session:
            generation = (
                await session.execute(
                    select(MiniReportGeneration)
                    .where(MiniReportGeneration.id == generation_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if (
                generation is None
                or generation.status != MiniReportGenerationState.GENERATING
                or generation.attempt_count != expected_attempt_count
            ):
                raise ValueError("invalid_mini_report_generation_transition")
            report_id = None
            if generation.user_id is not None:
                report = Report(
                    id=uuid.uuid4(),
                    user_id=generation.user_id,
                    report_type=ReportType.MINI.value,
                    token=report_token,
                    matrix_data=matrix_data,
                    ai_analysis=content,
                )
                session.add(report)
                await session.flush()
                report_id = report.id
                generation.report_id = report_id
            else:
                guest = await session.get(GuestProfile, generation.guest_profile_id)
                if guest is None:
                    raise ValueError("guest_profile_not_found")
                guest.report_data = {**content, "matrix_data": matrix_data}
            generation.status = MiniReportGenerationState.COMPLETED
            generation.completed_at = now
            generation.failed_at = None
            generation.error_code = None
            generation.error_detail = None
            await session.commit()
            return report_id

    async def mark_stale_failed(
        self, generation_id: uuid.UUID, *, stale_before: datetime, now: datetime
    ) -> bool:
        """Makes an abandoned generation retryable without reclaiming a live worker."""
        async with self._session_factory() as session:
            result = await session.execute(
                update(MiniReportGeneration)
                .where(
                    MiniReportGeneration.id == generation_id,
                    MiniReportGeneration.status == MiniReportGenerationState.GENERATING,
                    MiniReportGeneration.started_at <= stale_before,
                )
                .values(
                    status=MiniReportGenerationState.FAILED,
                    failed_at=now,
                    error_code="generation_lease_expired",
                    error_detail=None,
                )
            )
            await session.commit()
            return result.rowcount == 1

    @staticmethod
    async def _get_by_owner_key(
        session,
        user_id: uuid.UUID | None,
        guest_profile_id: uuid.UUID | None,
        fingerprint: str,
        generation_version: str,
    ) -> MiniReportGeneration | None:
        filters = [
            MiniReportGeneration.fingerprint == fingerprint,
            MiniReportGeneration.generation_version == generation_version,
        ]
        if user_id is not None:
            filters.append(MiniReportGeneration.user_id == user_id)
        else:
            filters.append(MiniReportGeneration.guest_profile_id == guest_profile_id)
        return (await session.execute(select(MiniReportGeneration).where(*filters))).scalar_one_or_none()
