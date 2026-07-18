import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.models import (
    Base,
    Payment,
    Report,
    ReportGenerationJob,
    ReportGenerationJobState,
    ReportGenerationState,
    ReportPaymentState,
    ReportType,
    User,
)
from core.repositories.report_lifecycle import (
    ReportGenerationErrorCategory,
    ReportGenerationJobRepository,
)
from core.services.matrix_report_generator import (
    DefaultMatrixReportGenerator,
    MatrixReportGenerationError,
    MatrixReportGeneratorResult,
)
from core.services.matrix_report_worker import (
    MatrixReportGenerationWorker,
)
from core.services.report_lifecycle import ReportLifecycleService


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class FakeGenerator:
    def __init__(self, responses: list[MatrixReportGeneratorResult | Exception]):
        self._calls: list[tuple[str, str, str]] = []
        self._index = 0
        self._responses = responses
        self._call_count = 0
        self.transaction_check: Callable[[], None] | None = None

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def calls(self) -> list[tuple[str, str, str]]:
        return list(self._calls)

    async def generate(
        self, *, birth_date: str, user_name: str, report_token: str
    ) -> MatrixReportGeneratorResult:
        self._call_count += 1
        if self.transaction_check is not None:
            self.transaction_check()
        self._calls.append((birth_date, user_name, report_token))
        if self._index >= len(self._responses):
            raise MatrixReportGenerationError(ReportGenerationErrorCategory.UNKNOWN_INTERNAL)
        response = self._responses[self._index]
        self._index += 1
        if isinstance(response, Exception):
            raise response
        return response


def _sample_generator_result() -> MatrixReportGeneratorResult:
    return MatrixReportGeneratorResult(
        matrix_data={"center": 8, "birth_date": "01.01.2000"},
        ai_analysis={"archetype_key": "Justice", "analysis": "test analysis"},
        kitchen_analysis={"kitchen": "test kitchen"},
    )


async def _create_paid_queued_report(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    token: str,
    generation_state: str = ReportGenerationState.QUEUED,
    job_state: str = ReportGenerationJobState.QUEUED,
    report_type: str = ReportType.FULL.value,
    payment_state: str = ReportPaymentState.PAYMENT_CONFIRMED,
    generation_attempts: int = 0,
    generation_started_at: datetime | None = None,
    report_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
) -> tuple[Report, ReportGenerationJob, Payment]:
    payment = Payment(
        id=uuid.uuid4(),
        user_id=user_id,
        amount=890,
        payment_type="web_matrix",
        amount_kopecks=89000,
    )
    report = Report(
        id=report_id or uuid.uuid4(),
        user_id=user_id,
        report_type=report_type,
        token=token,
        payment_id=payment.id if payment_state == ReportPaymentState.PAYMENT_CONFIRMED else None,
        payment_state=payment_state,
        payment_confirmed_at=_now() if payment_state == ReportPaymentState.PAYMENT_CONFIRMED else None,
        generation_state=generation_state,
        generation_attempts=generation_attempts,
        generation_started_at=generation_started_at,
    )
    job = ReportGenerationJob(
        id=job_id or uuid.uuid4(),
        report_id=report.id,
        job_type="full_report",
        state=job_state,
    )
    session.add_all([payment, report, job])
    await session.commit()
    return report, job, payment


async def _snapshots(
    session_factory: async_sessionmaker, report_id: uuid.UUID, job_id: uuid.UUID
) -> tuple[Report, ReportGenerationJob]:
    async with session_factory() as session:
        report = await session.get(Report, report_id)
        job = await session.get(ReportGenerationJob, job_id)
        assert report is not None
        assert job is not None
        return report, job


class FailCommitAfterFlushSession(AsyncSession):
    fail_commit_count: int = 0
    commit_call_number: int = 0

    async def commit(self) -> None:
        type(self).commit_call_number += 1
        if type(self).commit_call_number == type(self).fail_commit_count:
            raise RuntimeError("controlled_commit_failure")
        await super().commit()


@pytest_asyncio.fixture
async def sf(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'worker-lifecycle.db'}",
        poolclass=NullPool,
    )
    @event.listens_for(engine.sync_engine, "connect")
    def _configure(conn, rec):
        conn.execute("PRAGMA foreign_keys=ON")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def test_user(sf):
    user = User(id=uuid.uuid4(), name="WorkerTest", birth_date="01.01.2000")
    async with sf() as session:
        session.add(user)
        await session.commit()
    return user


class TestWorkerClaim:
    @pytest.mark.asyncio
    async def test_paid_queued_report_is_claimed(self, sf, test_user):
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s, user_id=test_user.id, token="worker-claim-success"
            )
        worker = MatrixReportGenerationWorker(
            sf, FakeGenerator([_sample_generator_result()])
        )

        result = await worker.process(job_id=job.id, report_id=report.id)

        assert result.disposition.value == "completed"
        stored_report, stored_job = await _snapshots(sf, report.id, job.id)
        assert stored_report.generation_state == ReportGenerationState.COMPLETED
        assert stored_report.matrix_data is not None
        assert stored_report.ai_analysis is not None
        assert stored_job.state == ReportGenerationJobState.COMPLETED

    @pytest.mark.asyncio
    async def test_unpaid_report_is_not_started(self, sf, test_user):
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s,
                user_id=test_user.id,
                token="worker-unpaid",
                payment_state=ReportPaymentState.AWAITING_PAYMENT,
            )
        worker = MatrixReportGenerationWorker(
            sf, FakeGenerator([_sample_generator_result()])
        )

        result = await worker.process(job_id=job.id, report_id=report.id)

        assert result.disposition.value == "terminal_failure"
        stored_report, _ = await _snapshots(sf, report.id, job.id)
        assert stored_report.generation_state == ReportGenerationState.QUEUED
        assert stored_report.matrix_data is None

    @pytest.mark.asyncio
    async def test_legacy_report_is_not_started(self, sf, test_user):
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s,
                user_id=test_user.id,
                token="worker-legacy",
                payment_state=ReportPaymentState.LEGACY_UNLINKED,
            )
        worker = MatrixReportGenerationWorker(
            sf, FakeGenerator([_sample_generator_result()])
        )

        result = await worker.process(job_id=job.id, report_id=report.id)

        assert result.disposition.value == "terminal_failure"

    @pytest.mark.asyncio
    async def test_wrong_report_type_is_not_started(self, sf, test_user):
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s,
                user_id=test_user.id,
                token="worker-wrong-type",
                report_type=ReportType.MINI.value,
            )
        worker = MatrixReportGenerationWorker(
            sf, FakeGenerator([_sample_generator_result()])
        )

        result = await worker.process(job_id=job.id, report_id=report.id)

        assert result.disposition.value == "terminal_failure"

    @pytest.mark.asyncio
    async def test_completed_report_is_idempotent(self, sf, test_user):
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s,
                user_id=test_user.id,
                token="worker-completed-already",
                generation_state=ReportGenerationState.COMPLETED,
            )
        generator = FakeGenerator([_sample_generator_result()])
        worker = MatrixReportGenerationWorker(sf, generator)

        result = await worker.process(job_id=job.id, report_id=report.id)

        assert result.disposition.value == "idempotent_completed"
        assert generator.call_count == 0

    @pytest.mark.asyncio
    async def test_terminal_report_is_not_started(self, sf, test_user):
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s,
                user_id=test_user.id,
                token="worker-terminal-already",
                generation_state=ReportGenerationState.FAILED_TERMINAL,
            )
        worker = MatrixReportGenerationWorker(
            sf, FakeGenerator([_sample_generator_result()])
        )

        result = await worker.process(job_id=job.id, report_id=report.id)

        assert result.disposition.value == "terminal_failure"

    @pytest.mark.asyncio
    async def test_job_report_mismatch_fails_closed(self, sf, test_user):
        async with sf() as s:
            report, _, _ = await _create_paid_queued_report(
                s, user_id=test_user.id, token="worker-mismatch"
            )
        fake_job_id = uuid.uuid4()
        worker = MatrixReportGenerationWorker(
            sf, FakeGenerator([_sample_generator_result()])
        )

        result = await worker.process(job_id=fake_job_id, report_id=report.id)

        assert result.disposition.value == "terminal_failure"


class TestWorkerIdempotency:
    @pytest.mark.asyncio
    async def test_repeat_after_completed_is_idempotent(self, sf, test_user):
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s, user_id=test_user.id, token="worker-repeat-after-complete"
            )
        generator = FakeGenerator([_sample_generator_result()])
        worker = MatrixReportGenerationWorker(sf, generator)

        first = await worker.process(job_id=job.id, report_id=report.id)
        assert first.disposition.value == "completed"
        assert generator.call_count == 1

        async with sf() as s:
            stored = await s.get(Report, report.id)
            completed_at = stored.generated_at
            completed_content = stored.ai_analysis

        generator2 = FakeGenerator([_sample_generator_result()])
        worker2 = MatrixReportGenerationWorker(sf, generator2)
        second = await worker2.process(job_id=job.id, report_id=report.id)

        assert second.disposition.value == "idempotent_completed"
        assert generator2.call_count == 0
        async with sf() as s:
            stored = await s.get(Report, report.id)
            assert stored.generated_at == completed_at
            assert stored.ai_analysis == completed_content


class TestWorkerConcurrency:
    @pytest.mark.asyncio
    async def test_two_concurrent_deliveries_call_generator_once(
        self, tmp_path
    ):
        database_path = tmp_path / "worker_concurrent.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{database_path.as_posix()}",
            poolclass=NullPool,
        )

        checked_out_connections: set[int] | None = None

        @event.listens_for(engine.sync_engine, "connect")
        def configure_sqlite(conn, rec):
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=300")

        @event.listens_for(engine.sync_engine, "checkout")
        def record_physical(conn, rec, proxy):
            if checked_out_connections is not None:
                checked_out_connections.add(id(conn))

        concurrent_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        try:
            async with engine.begin() as connection:
                await connection.execute(text("PRAGMA journal_mode=WAL"))
                await connection.run_sync(Base.metadata.create_all)

            results: list[tuple[int, int]] = []
            for cycle in range(10):
                cycle_user = User(
                    id=uuid.uuid4(),
                    name=f"Concurrent {cycle}",
                    birth_date="01.01.2000",
                )
                async with concurrent_factory() as s:
                    s.add(cycle_user)
                    await s.commit()
                    report, job, _ = await _create_paid_queued_report(
                        s, user_id=cycle_user.id, token=f"worker-race-{cycle}"
                    )

                generator = FakeGenerator([_sample_generator_result()])

                original_generate = generator.generate

                async def delayed_generate(**kwargs):
                    await asyncio.sleep(0)
                    return await original_generate(**kwargs)

                generator.generate = delayed_generate

                checked_out_connections = set()

                session_a = AsyncSession(bind=engine, expire_on_commit=False)
                session_b = AsyncSession(bind=engine, expire_on_commit=False)

                factory_maker_a = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                factory_maker_b = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )

                class _FixedSessionFactory:
                    def __init__(self, session):
                        self._session = session

                    def __call__(self):
                        factory = self

                        class _Ctx:
                            async def __aenter__(self):
                                return factory._session

                            async def __aexit__(self, *args):
                                pass

                        return _Ctx()

                worker_a = MatrixReportGenerationWorker(
                    _FixedSessionFactory(session_a),
                    generator,
                )
                worker_b = MatrixReportGenerationWorker(
                    _FixedSessionFactory(session_b),
                    generator,
                )

                try:
                    a_task = asyncio.create_task(
                        worker_a.process(job_id=job.id, report_id=report.id)
                    )
                    b_task = asyncio.create_task(
                        worker_b.process(job_id=job.id, report_id=report.id)
                    )
                    result_a, result_b = await asyncio.gather(a_task, b_task)

                    assert (
                        len(checked_out_connections) >= 2
                    ), f"Cycle {cycle}: expected >=2 physical connections"
                    completed_set = {
                        r.disposition.value
                        for r in (result_a, result_b)
                        if r.disposition.value == "completed"
                    }
                    assert len(completed_set) <= 1, (
                        f"Cycle {cycle}: at most 1 completed, "
                        f"got {result_a.disposition.value}/{result_b.disposition.value}"
                    )
                    assert generator.call_count == 1, (
                        f"Cycle {cycle}: generator called {generator.call_count} times"
                    )

                    async with concurrent_factory() as s:
                        stored = await s.get(Report, report.id)
                        assert stored.generation_state == ReportGenerationState.COMPLETED
                        assert stored.matrix_data is not None
                    results.append((1, 1))
                finally:
                    await session_a.close()
                    await session_b.close()
                    checked_out_connections = None

            assert len(results) == 10
            assert results == [(1, 1)] * 10
        finally:
            await engine.dispose()


class TestWorkerGeneratorBoundary:
    @pytest.mark.asyncio
    async def test_generator_called_outside_db_transaction(
        self, sf, test_user
    ):
        session_count = 0

        class TrackingFactory:
            def __init__(self, inner):
                self._inner = inner

            def __call__(self):
                factory = self

                class _TrackedSessionCtx:
                    async def __aenter__(self):
                        nonlocal session_count
                        session_count += 1
                        ctx = factory._inner()
                        return await ctx.__aenter__()

                    async def __aexit__(self, *args):
                        nonlocal session_count
                        session_count -= 1
                        return True

                return _TrackedSessionCtx()

        tracking_factory = TrackingFactory(sf)

        record_active_sessions: list[int] = []

        def check_transaction():
            record_active_sessions.append(session_count)

        generator = FakeGenerator([_sample_generator_result()])
        generator.transaction_check = check_transaction

        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s, user_id=test_user.id, token="worker-boundary"
            )

        worker = MatrixReportGenerationWorker(tracking_factory, generator)
        result = await worker.process(job_id=job.id, report_id=report.id)

        assert result.disposition.value == "completed"
        assert len(record_active_sessions) == 1
        assert record_active_sessions[0] == 0


class TestWorkerPersistence:
    @pytest.mark.asyncio
    async def test_success_updates_existing_placeholder(
        self, sf, test_user
    ):
        original_report_id: uuid.UUID | None = None
        original_token: str | None = None
        original_payment_id: uuid.UUID | None = None
        original_payment_confirmed_at: datetime | None = None

        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s, user_id=test_user.id, token="worker-placeholder"
            )
            original_report_id = report.id
            original_token = report.token
            original_payment_id = report.payment_id
            original_payment_confirmed_at = report.payment_confirmed_at

        worker = MatrixReportGenerationWorker(
            sf, FakeGenerator([_sample_generator_result()])
        )
        result = await worker.process(job_id=job.id, report_id=report.id)

        assert result.disposition.value == "completed"
        async with sf() as s:
            stored = await s.get(Report, original_report_id)
            assert stored is not None
            assert stored.id == original_report_id
            assert stored.token == original_token
            assert stored.payment_id == original_payment_id
            assert stored.payment_confirmed_at is not None
            assert stored.payment_confirmed_at.replace(tzinfo=timezone.utc) == original_payment_confirmed_at
            assert stored.payment_state == ReportPaymentState.PAYMENT_CONFIRMED
            assert stored.generation_state == ReportGenerationState.COMPLETED
            assert stored.matrix_data == {"center": 8, "birth_date": "01.01.2000"}
            assert stored.ai_analysis == {
                "archetype_key": "Justice",
                "analysis": "test analysis",
            }
            assert stored.kitchen_analysis == {"kitchen": "test kitchen"}
            assert stored.generated_at is not None

    @pytest.mark.asyncio
    async def test_worker_does_not_delete_or_create_report(
        self, sf, test_user
    ):
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s, user_id=test_user.id, token="worker-no-delete"
            )

        all_reports_before: set[uuid.UUID] = set()
        async with sf() as s:
            result = await s.execute(select(Report.id))
            all_reports_before = {row[0] for row in result.all()}
        report_count_before = len(all_reports_before)

        worker = MatrixReportGenerationWorker(
            sf, FakeGenerator([_sample_generator_result()])
        )
        await worker.process(job_id=job.id, report_id=report.id)

        all_reports_after: set[uuid.UUID] = set()
        async with sf() as s:
            result = await s.execute(select(Report.id))
            all_reports_after = {row[0] for row in result.all()}

        assert report_count_before == len(all_reports_after)
        assert all_reports_before == all_reports_after


class TestWorkerFailure:
    @pytest.mark.asyncio
    async def test_retryable_failure_saves_safe_category(
        self, sf, test_user
    ):
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s, user_id=test_user.id, token="worker-retryable"
            )

        exc = MatrixReportGenerationError(ReportGenerationErrorCategory.AI_TIMEOUT)
        worker = MatrixReportGenerationWorker(sf, FakeGenerator([exc]))
        result = await worker.process(job_id=job.id, report_id=report.id)

        assert result.disposition.value == "retryable_failure"
        assert result.error_category == ReportGenerationErrorCategory.AI_TIMEOUT
        async with sf() as s:
            stored_report = await s.get(Report, report.id)
            stored_job = await s.get(ReportGenerationJob, job.id)
        assert stored_report is not None
        assert (
            stored_report.generation_state == ReportGenerationState.FAILED_RETRYABLE
        )
        assert (
            stored_report.generation_error_category
            == ReportGenerationErrorCategory.AI_TIMEOUT
        )
        assert stored_report.matrix_data is None
        assert stored_job is not None
        assert stored_job.state == ReportGenerationJobState.FAILED_RETRYABLE
        assert (
            stored_job.last_error_category
            == ReportGenerationErrorCategory.AI_TIMEOUT
        )

    @pytest.mark.asyncio
    async def test_terminal_failure_saves_safe_category(
        self, sf, test_user
    ):
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s, user_id=test_user.id, token="worker-terminal"
            )

        exc = MatrixReportGenerationError(
            ReportGenerationErrorCategory.PDF_GENERATION_FAILED
        )
        worker = MatrixReportGenerationWorker(sf, FakeGenerator([exc]))
        result = await worker.process(job_id=job.id, report_id=report.id)

        assert result.disposition.value == "terminal_failure"
        assert result.error_category == ReportGenerationErrorCategory.PDF_GENERATION_FAILED
        async with sf() as s:
            stored_report = await s.get(Report, report.id)
            stored_job = await s.get(ReportGenerationJob, job.id)
        assert stored_report is not None
        assert (
            stored_report.generation_state == ReportGenerationState.FAILED_TERMINAL
        )
        assert (
            stored_report.generation_error_category
            == ReportGenerationErrorCategory.PDF_GENERATION_FAILED
        )
        assert stored_job is not None
        assert stored_job.state == ReportGenerationJobState.FAILED_TERMINAL

    @pytest.mark.asyncio
    async def test_raw_exception_not_saved(self, sf, test_user):
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s, user_id=test_user.id, token="worker-raw-exc"
            )

        exc = MatrixReportGenerationError(
            f"SELECT {uuid.uuid4()} report-token traceback"
        )
        worker = MatrixReportGenerationWorker(sf, FakeGenerator([exc]))
        result = await worker.process(job_id=job.id, report_id=report.id)

        assert result.disposition.value == "terminal_failure"
        assert "SELECT" not in (result.error_category or "")
        async with sf() as s:
            stored_report = await s.get(Report, report.id)
            stored_job = await s.get(ReportGenerationJob, job.id)
        assert stored_report is not None
        assert "SELECT" not in (stored_report.generation_error_category or "")
        assert "traceback" not in (stored_report.generation_error_category or "")
        assert stored_job is not None
        assert "SELECT" not in (stored_job.last_error_category or "")


class TestWorkerDbFailure:
    @pytest.mark.asyncio
    async def test_db_failure_after_generation_rolls_back(
        self, tmp_path
    ):
        database_path = tmp_path / "worker_db_failure.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{database_path.as_posix()}",
            poolclass=NullPool,
        )

        @event.listens_for(engine.sync_engine, "connect")
        def configure(conn, rec):
            conn.execute("PRAGMA foreign_keys=ON")

        test_user = User(id=uuid.uuid4(), name="DBFail", birth_date="01.01.2000")

        normal_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        FailCommitAfterFlushSession.fail_commit_count = 2
        FailCommitAfterFlushSession.commit_call_number = 0
        fail_factory = async_sessionmaker(
            engine, class_=FailCommitAfterFlushSession, expire_on_commit=False
        )
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with normal_factory() as s:
                s.add(test_user)
                await s.commit()
                report, job, _ = await _create_paid_queued_report(
                    s, user_id=test_user.id, token="worker-db-fail"
                )

            worker = MatrixReportGenerationWorker(
                fail_factory, FakeGenerator([_sample_generator_result()])
            )
            result = await worker.process(job_id=job.id, report_id=report.id)

            assert result.disposition.value == "retryable_failure"

            async with normal_factory() as s:
                stored = await s.get(Report, report.id)
                assert stored is not None
                assert stored.generation_state == ReportGenerationState.RUNNING
                assert stored.matrix_data is None
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_session_usable_after_rollback_and_retry_possible(
        self, sf, test_user
    ):
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s, user_id=test_user.id, token="worker-retry-after-fail"
            )

        class _FailOnceGen:
            def __init__(self):
                self.call_count = 0

            async def generate(self, **kwargs):
                self.call_count += 1
                raise MatrixReportGenerationError(ReportGenerationErrorCategory.AI_TIMEOUT)

        fail_gen = _FailOnceGen()
        worker = MatrixReportGenerationWorker(sf, fail_gen)
        result = await worker.process(job_id=job.id, report_id=report.id)

        assert result.disposition.value == "retryable_failure"
        assert fail_gen.call_count == 1

        async with sf() as s:
            row = (await s.execute(select(Report).where(Report.id == report.id))).scalar_one()
            assert row is not None
            assert row.generation_state == ReportGenerationState.FAILED_RETRYABLE

        async with sf() as s:
            lifecycle = ReportLifecycleService(s)
            await lifecycle.retry_generation(report.id)
            await s.commit()

        async with sf() as s:
            job_repo = ReportGenerationJobRepository(s)
            job_to_retry = await job_repo.get_by_report_and_type(report.id)
            assert job_to_retry is not None
            now = _now()
            assert await job_repo.claim_job_for_dispatch(job_to_retry.id, now) == "claimed"
            await s.commit()
        async with sf() as s:
            lifecycle2 = ReportLifecycleService(s)
            await lifecycle2.mark_generation_queued(report.id, "retry-task-id")
            await s.commit()

        generator2 = FakeGenerator([_sample_generator_result()])
        worker2 = MatrixReportGenerationWorker(sf, generator2)
        result2 = await worker2.process(job_id=job.id, report_id=report.id)
        assert result2.disposition.value == "completed"


class TestWorkerStaleRunningRecovery:
    @pytest.mark.asyncio
    async def test_stale_running_recovery_is_transitioned_to_retryable(
        self, sf, test_user
    ):
        now = _now()
        stale_started_at = now - timedelta(minutes=30)
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s,
                user_id=test_user.id,
                token="worker-stale-running",
                generation_state=ReportGenerationState.RUNNING,
                generation_started_at=stale_started_at,
            )

        async with sf() as s:
            repo = ReportGenerationJobRepository(s)
            next_attempt_at = now + timedelta(minutes=2)
            recovered = await repo.mark_stale_running_generation_retryable(
                report.id,
                stale_started_at + timedelta(seconds=1),
                now,
                next_attempt_at,
            )
            await s.commit()
            assert recovered

        async with sf() as s:
            stored_report = await s.get(Report, report.id)
            stored_job = await s.get(ReportGenerationJob, job.id)
        assert stored_report is not None
        assert (
            stored_report.generation_state == ReportGenerationState.FAILED_RETRYABLE
        )
        assert (
            stored_report.generation_error_category
            == ReportGenerationErrorCategory.DISPATCH_CLAIM_EXPIRED
        )
        assert stored_job is not None
        assert stored_job.state == ReportGenerationJobState.FAILED_RETRYABLE
        assert stored_job.next_attempt_at is not None

    @pytest.mark.asyncio
    async def test_fresh_running_is_not_recovered(self, sf, test_user):
        now = _now()
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s,
                user_id=test_user.id,
                token="worker-fresh-running",
                generation_state=ReportGenerationState.RUNNING,
                generation_started_at=now,
            )

        async with sf() as s:
            repo = ReportGenerationJobRepository(s)
            recovered = await repo.mark_stale_running_generation_retryable(
                report.id,
                now - timedelta(minutes=5),
                now,
                now + timedelta(minutes=1),
            )
            await s.commit()
            assert not recovered

    @pytest.mark.asyncio
    async def test_completed_is_not_recovered(self, sf, test_user):
        now = _now()
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s,
                user_id=test_user.id,
                token="worker-completed-no-recover",
                generation_state=ReportGenerationState.COMPLETED,
            )

        async with sf() as s:
            repo = ReportGenerationJobRepository(s)
            recovered = await repo.mark_stale_running_generation_retryable(
                report.id,
                now - timedelta(minutes=30),
                now,
                now + timedelta(minutes=1),
            )
            await s.commit()
            assert not recovered

    @pytest.mark.asyncio
    async def test_terminal_is_not_recovered(self, sf, test_user):
        now = _now()
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s,
                user_id=test_user.id,
                token="worker-terminal-no-recover",
                generation_state=ReportGenerationState.FAILED_TERMINAL,
            )

        async with sf() as s:
            repo = ReportGenerationJobRepository(s)
            recovered = await repo.mark_stale_running_generation_retryable(
                report.id,
                now - timedelta(minutes=30),
                now,
                now + timedelta(minutes=1),
            )
            await s.commit()
            assert not recovered


class TestWorkerAttempts:
    @pytest.mark.asyncio
    async def test_generation_attempts_incremented_once_per_claim(
        self, sf, test_user
    ):
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s,
                user_id=test_user.id,
                token="worker-attempts",
                generation_attempts=2,
            )

        worker = MatrixReportGenerationWorker(
            sf, FakeGenerator([_sample_generator_result()])
        )
        result = await worker.process(job_id=job.id, report_id=report.id)

        assert result.disposition.value == "completed"
        async with sf() as s:
            stored = await s.get(Report, report.id)
        assert stored is not None
        assert stored.generation_attempts == 3


class TestWorkerCrossUser:
    @pytest.mark.asyncio
    async def test_cross_user_isolation(self, sf, test_user):
        other_user = User(id=uuid.uuid4(), name="Other", birth_date="02.02.1990")
        async with sf() as s:
            s.add(other_user)
            await s.commit()
            report, job, _ = await _create_paid_queued_report(
                s, user_id=test_user.id, token="worker-cross-user"
            )

        generator = FakeGenerator([_sample_generator_result()])
        worker = MatrixReportGenerationWorker(sf, generator)
        result = await worker.process(job_id=job.id, report_id=report.id)
        assert result.disposition.value == "completed"

        async with sf() as s:
            stored = await s.get(Report, report.id)
            other_stored = await s.get(User, other_user.id)
        assert stored is not None
        assert stored.user_id == test_user.id
        assert stored.user_id != other_user.id
        assert other_stored is not None
        assert other_stored.has_matrix is False


class TestWorkerPrivacy:
    @pytest.mark.asyncio
    async def test_logs_do_not_contain_identifiers(self, sf, test_user, caplog):
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s, user_id=test_user.id, token="worker-privacy"
            )

        caplog.set_level(logging.WARNING)

        worker = MatrixReportGenerationWorker(
            sf, FakeGenerator([_sample_generator_result()])
        )
        await worker.process(job_id=job.id, report_id=report.id)

        for record in caplog.records:
            msg_text = record.getMessage()
            assert str(report.id) not in msg_text
            assert str(job.id) not in msg_text
            assert str(test_user.id) not in msg_text
            assert report.token not in msg_text
            assert "01.01.2000" not in msg_text

    @pytest.mark.asyncio
    async def test_retryable_failure_logs_no_raw_exception(
        self, sf, test_user, caplog
    ):
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s, user_id=test_user.id, token="worker-privacy-retry"
            )

        caplog.set_level(logging.WARNING)
        exc = MatrixReportGenerationError(ReportGenerationErrorCategory.AI_TIMEOUT)
        worker = MatrixReportGenerationWorker(sf, FakeGenerator([exc]))
        await worker.process(job_id=job.id, report_id=report.id)

        for record in caplog.records:
            msg_text = record.getMessage()
            assert str(report.id) not in msg_text
            assert str(job.id) not in msg_text

    @pytest.mark.asyncio
    async def test_terminal_failure_logs_no_raw_exception(
        self, sf, test_user, caplog
    ):
        async with sf() as s:
            report, job, _ = await _create_paid_queued_report(
                s, user_id=test_user.id, token="worker-privacy-term"
            )

        caplog.set_level(logging.WARNING)
        exc = MatrixReportGenerationError(
            ReportGenerationErrorCategory.PDF_GENERATION_FAILED
        )
        worker = MatrixReportGenerationWorker(sf, FakeGenerator([exc]))
        await worker.process(job_id=job.id, report_id=report.id)

        for record in caplog.records:
            msg_text = record.getMessage()
            assert str(report.id) not in msg_text
            assert str(job.id) not in msg_text

    @pytest.mark.asyncio
    async def test_db_failure_logs_no_sensitive_identifiers(
        self, tmp_path, caplog
    ):
        database_path = tmp_path / "worker_privacy_db_fail.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{database_path.as_posix()}",
            poolclass=NullPool,
        )

        @event.listens_for(engine.sync_engine, "connect")
        def configure(conn, rec):
            conn.execute("PRAGMA foreign_keys=ON")

        test_user = User(id=uuid.uuid4(), name="PrivacyDB", birth_date="01.01.2000")

        normal_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        FailCommitAfterFlushSession.fail_commit_count = 2
        FailCommitAfterFlushSession.commit_call_number = 0
        fail_factory = async_sessionmaker(
            engine, class_=FailCommitAfterFlushSession, expire_on_commit=False
        )
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with normal_factory() as s:
                s.add(test_user)
                await s.commit()
                report, job, _ = await _create_paid_queued_report(
                    s, user_id=test_user.id, token="worker-privacy-db-fail"
                )

            caplog.set_level(logging.WARNING)
            worker = MatrixReportGenerationWorker(
                fail_factory, FakeGenerator([_sample_generator_result()])
            )
            await worker.process(job_id=job.id, report_id=report.id)

            for record in caplog.records:
                msg_text = record.getMessage()
                assert str(report.id) not in msg_text
                assert str(job.id) not in msg_text
                assert str(test_user.id) not in msg_text
                assert report.token not in msg_text
        finally:
            await engine.dispose()


class TestDefaultGenerator:
    @pytest.mark.asyncio
    async def test_default_generator_is_importable(self):
        gen = DefaultMatrixReportGenerator()
        assert gen is not None
        result = MatrixReportGeneratorResult(
            matrix_data={"center": 8},
            ai_analysis={"key": "val"},
            kitchen_analysis=None,
        )
        assert result.matrix_data == {"center": 8}
