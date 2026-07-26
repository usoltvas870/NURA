import logging
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

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
from core.services.report_generation_dispatcher import (
    PublishDisposition,
    PublishResult,
    ReportGenerationDispatcher,
    report_generation_task_id,
)
from core.services.celery_publisher import CeleryReportGenerationPublisher


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class FakeSendTask:
    def __init__(self, responses: list[None | Exception]):
        self._responses = deque(responses)
        self.calls: list[dict] = []

    def __call__(self, name, kwargs=None, task_id=None):
        self.calls.append({"name": name, "kwargs": kwargs or {}, "task_id": task_id})
        response = self._responses.popleft()
        if isinstance(response, Exception):
            raise response


def _fake_celery_app(*, has_task: bool = True):
    class _App:
        def send_task(self, name, kwargs=None, task_id=None):
            pass

    app = _App()
    if has_task:
        app.tasks = {"core.tasks.process_report_generation_job": object()}
    else:
        app.tasks = {}
    return app


async def _create_paid_pending_job(
    session: AsyncSession,
    user_id: uuid.UUID,
    token: str,
) -> tuple[Report, ReportGenerationJob]:
    payment = Payment(
        id=uuid.uuid4(), user_id=user_id, amount=890, payment_type="web_matrix",
        amount_kopecks=89000,
    )
    report = Report(
        id=uuid.uuid4(),
        user_id=user_id,
        report_type=ReportType.FULL.value,
        token=token,
        payment_id=payment.id,
        payment_state=ReportPaymentState.PAYMENT_CONFIRMED,
        payment_confirmed_at=_now(),
        generation_state=ReportGenerationState.PENDING_DISPATCH,
    )
    job = ReportGenerationJob(
        id=uuid.uuid4(),
        report_id=report.id,
        job_type="full_report",
        state=ReportGenerationJobState.PENDING_DISPATCH,
    )
    session.add_all([payment, report, job])
    await session.commit()
    return report, job


@pytest_asyncio.fixture
async def sf(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'celery-wiring.db'}",
        poolclass=NullPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _configure(conn, rec):
        conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _send_task_patcher(app):
    return patch("core.tasks.celery_app", app)


class TestPublisherRetryable:
    @pytest.mark.asyncio
    async def test_kombu_operational_error_is_retryable(self):
        job_id = uuid.uuid4()
        task_id = report_generation_task_id(job_id)

        try:
            from kombu.exceptions import OperationalError as KOE
        except ImportError:
            KOE = ConnectionError

        fake = FakeSendTask([KOE("connection refused")])
        app = _fake_celery_app()
        with _send_task_patcher(app), patch.object(app, "send_task", fake):
            publisher = CeleryReportGenerationPublisher()
            result = await publisher.publish(
                job_id=job_id, report_id=uuid.uuid4(), task_id=task_id,
            )

        assert result.disposition == PublishDisposition.RETRYABLE_FAILURE
        assert result.error_category == ReportGenerationErrorCategory.DISPATCH_FAILED

    @pytest.mark.asyncio
    async def test_timeout_error_is_retryable(self):
        job_id = uuid.uuid4()
        task_id = report_generation_task_id(job_id)

        fake = FakeSendTask([TimeoutError("timeout")])
        app = _fake_celery_app()
        with _send_task_patcher(app), patch.object(app, "send_task", fake):
            publisher = CeleryReportGenerationPublisher()
            result = await publisher.publish(
                job_id=job_id, report_id=uuid.uuid4(), task_id=task_id,
            )

        assert result.disposition == PublishDisposition.RETRYABLE_FAILURE

    @pytest.mark.asyncio
    async def test_connection_error_is_retryable(self):
        job_id = uuid.uuid4()
        task_id = report_generation_task_id(job_id)

        fake = FakeSendTask([ConnectionError("refused")])
        app = _fake_celery_app()
        with _send_task_patcher(app), patch.object(app, "send_task", fake):
            publisher = CeleryReportGenerationPublisher()
            result = await publisher.publish(
                job_id=job_id, report_id=uuid.uuid4(), task_id=task_id,
            )

        assert result.disposition == PublishDisposition.RETRYABLE_FAILURE

    @pytest.mark.asyncio
    async def test_os_error_is_retryable(self):
        job_id = uuid.uuid4()
        task_id = report_generation_task_id(job_id)

        fake = FakeSendTask([OSError("connection reset")])
        app = _fake_celery_app()
        with _send_task_patcher(app), patch.object(app, "send_task", fake):
            publisher = CeleryReportGenerationPublisher()
            result = await publisher.publish(
                job_id=job_id, report_id=uuid.uuid4(), task_id=task_id,
            )

        assert result.disposition == PublishDisposition.RETRYABLE_FAILURE

    @pytest.mark.asyncio
    async def test_unknown_runtime_error_is_retryable(self):
        job_id = uuid.uuid4()
        task_id = report_generation_task_id(job_id)

        fake = FakeSendTask([RuntimeError("unexpected transport error")])
        app = _fake_celery_app()
        with _send_task_patcher(app), patch.object(app, "send_task", fake):
            publisher = CeleryReportGenerationPublisher()
            result = await publisher.publish(
                job_id=job_id, report_id=uuid.uuid4(), task_id=task_id,
            )

        assert result.disposition == PublishDisposition.RETRYABLE_FAILURE
        assert result.error_category == ReportGenerationErrorCategory.DISPATCH_FAILED


class TestPublisherTerminal:
    @pytest.mark.asyncio
    async def test_missing_registered_task_is_terminal(self):
        job_id = uuid.uuid4()
        task_id = report_generation_task_id(job_id)

        fake = FakeSendTask([None])
        app = _fake_celery_app(has_task=False)
        with _send_task_patcher(app), patch.object(app, "send_task", fake):
            publisher = CeleryReportGenerationPublisher()
            result = await publisher.publish(
                job_id=job_id, report_id=uuid.uuid4(), task_id=task_id,
            )

        assert result.disposition == PublishDisposition.TERMINAL_FAILURE
        assert len(fake.calls) == 0

    @pytest.mark.asyncio
    async def test_encode_error_is_terminal(self):
        job_id = uuid.uuid4()
        task_id = report_generation_task_id(job_id)

        try:
            from kombu.exceptions import EncodeError
        except ImportError:
            EncodeError = TypeError

        fake = FakeSendTask([EncodeError("bad payload")])
        app = _fake_celery_app()
        with _send_task_patcher(app), patch.object(app, "send_task", fake):
            publisher = CeleryReportGenerationPublisher()
            result = await publisher.publish(
                job_id=job_id, report_id=uuid.uuid4(), task_id=task_id,
            )

        assert result.disposition == PublishDisposition.TERMINAL_FAILURE

    @pytest.mark.asyncio
    async def test_type_error_is_terminal(self):
        job_id = uuid.uuid4()
        task_id = report_generation_task_id(job_id)

        fake = FakeSendTask([TypeError("bad arg type")])
        app = _fake_celery_app()
        with _send_task_patcher(app), patch.object(app, "send_task", fake):
            publisher = CeleryReportGenerationPublisher()
            result = await publisher.publish(
                job_id=job_id, report_id=uuid.uuid4(), task_id=task_id,
            )

        assert result.disposition == PublishDisposition.TERMINAL_FAILURE


class TestPublisherRegistryPreflight:
    @pytest.mark.asyncio
    async def test_preflight_does_not_connect_to_broker(self):
        app = _fake_celery_app(has_task=False)
        with _send_task_patcher(app):
            publisher = CeleryReportGenerationPublisher()
            result = await publisher.publish(
                job_id=uuid.uuid4(), report_id=uuid.uuid4(),
                task_id="nura-report-v1-test",
            )

        assert result.disposition == PublishDisposition.TERMINAL_FAILURE


class TestPublisherContract:
    @pytest.mark.asyncio
    async def test_accepted_publish_unchanged(self):
        job_id = uuid.uuid4()
        report_id = uuid.uuid4()
        task_id = report_generation_task_id(job_id)

        fake = FakeSendTask([None])
        app = _fake_celery_app()
        with _send_task_patcher(app), patch.object(app, "send_task", fake):
            publisher = CeleryReportGenerationPublisher()
            result = await publisher.publish(
                job_id=job_id, report_id=report_id, task_id=task_id,
            )

        assert result.disposition == PublishDisposition.ACCEPTED
        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call["name"] == "core.tasks.process_report_generation_job"
        assert call["kwargs"] == {
            "job_id": str(job_id),
            "report_id": str(report_id),
        }
        assert call["task_id"] == task_id

    @pytest.mark.asyncio
    async def test_kwargs_only_job_id_and_report_id(self):
        job_id = uuid.uuid4()
        task_id = report_generation_task_id(job_id)

        fake = FakeSendTask([None])
        app = _fake_celery_app()
        with _send_task_patcher(app), patch.object(app, "send_task", fake):
            publisher = CeleryReportGenerationPublisher()
            await publisher.publish(
                job_id=job_id, report_id=uuid.uuid4(), task_id=task_id,
            )

        kw = fake.calls[0]["kwargs"]
        assert set(kw.keys()) == {"job_id", "report_id"}

    @pytest.mark.asyncio
    async def test_deterministic_task_id_passed_through(self):
        job_id = uuid.uuid4()
        task_id = report_generation_task_id(job_id)

        fake = FakeSendTask([None])
        app = _fake_celery_app()
        with _send_task_patcher(app), patch.object(app, "send_task", fake):
            publisher = CeleryReportGenerationPublisher()
            await publisher.publish(
                job_id=job_id, report_id=uuid.uuid4(), task_id=task_id,
            )

        assert fake.calls[0]["task_id"] == task_id
        assert task_id.startswith("nura-report-v1-")
        assert str(job_id) not in task_id


class TestPublisherPrivacy:
    @pytest.mark.asyncio
    async def test_retryable_error_logs_no_raw_elements(self, caplog):
        job_id = uuid.uuid4()
        task_id = report_generation_task_id(job_id)

        fake = FakeSendTask([RuntimeError("broker://redis:6379?secret_key=xyz")])
        app = _fake_celery_app()
        caplog.set_level(logging.WARNING)
        with _send_task_patcher(app), patch.object(app, "send_task", fake):
            publisher = CeleryReportGenerationPublisher()
            await publisher.publish(
                job_id=job_id, report_id=uuid.uuid4(), task_id=task_id,
            )

        for record in caplog.records:
            msg = record.getMessage()
            assert "broker://" not in msg
            assert "redis://" not in msg
            assert "secret_key" not in msg
            assert str(job_id) not in msg
            assert task_id not in msg

    @pytest.mark.asyncio
    async def test_publish_result_excludes_raw_error(self, caplog):
        job_id = uuid.uuid4()
        task_id = report_generation_task_id(job_id)
        marker = f"MARKER-{uuid.uuid4().hex[:8]}"

        fake = FakeSendTask([RuntimeError(marker)])
        app = _fake_celery_app()
        caplog.set_level(logging.WARNING)
        with _send_task_patcher(app), patch.object(app, "send_task", fake):
            publisher = CeleryReportGenerationPublisher()
            result = await publisher.publish(
                job_id=job_id, report_id=uuid.uuid4(), task_id=task_id,
            )

        error_cat = result.error_category or ""
        assert marker not in error_cat
        assert "RuntimeError" not in error_cat
        for record in caplog.records:
            assert marker not in record.getMessage()

    @pytest.mark.asyncio
    async def test_publisher_no_db_session(self):
        publisher = CeleryReportGenerationPublisher()
        assert not hasattr(publisher, "_session_factory")
        assert not hasattr(publisher, "_session")


class TestUnknownErrorIntegration:
    @pytest.mark.asyncio
    async def test_runtime_error_does_not_transition_to_terminal(self, sf):
        async with sf() as session:
            user = User(id=uuid.uuid4(), name="Test", birth_date="01.01.2000")
            session.add(user)
            await session.commit()
            report, job = await _create_paid_pending_job(
                session, user.id, "wiring-unknown-retryable"
            )

        class _RuntimeErrorPublisher:
            async def publish(self, *, job_id, report_id, task_id):
                raise RuntimeError("simulated unknown transport crash")

        now = _now()
        dispatcher = ReportGenerationDispatcher(sf, _RuntimeErrorPublisher())
        result = await dispatcher.dispatch_batch(now=now, limit=10)

        assert result.retryable_failed == 1
        assert result.terminal_failed == 0
        assert result.published == 0

        async with sf() as session:
            stored_report = await session.get(Report, report.id)
            stored_job = await session.get(ReportGenerationJob, job.id)
        assert stored_report.generation_state == ReportGenerationState.PENDING_DISPATCH
        assert stored_job.state == ReportGenerationJobState.FAILED_RETRYABLE
        assert stored_job.next_attempt_at is not None

    @pytest.mark.asyncio
    async def test_batch_continues_after_runtime_error(self, sf):
        async with sf() as session:
            user = User(id=uuid.uuid4(), name="Test", birth_date="01.01.2000")
            session.add(user)
            await session.commit()
            _, job1 = await _create_paid_pending_job(
                session, user.id, "wiring-batch-continue-1"
            )
            _, job2 = await _create_paid_pending_job(
                session, user.id, "wiring-batch-continue-2"
            )

        class _CrashThenAcceptPublisher:
            def __init__(self):
                self._idx = 0

            async def publish(self, *, job_id, report_id, task_id):
                self._idx += 1
                if self._idx == 1:
                    raise RuntimeError("crash")
                return PublishResult.accepted()

        now = _now()
        dispatcher = ReportGenerationDispatcher(sf, _CrashThenAcceptPublisher())
        result = await dispatcher.dispatch_batch(now=now, limit=10)

        assert result.retryable_failed == 1
        assert result.published == 1


class TestTaskRegistration:
    def test_worker_task_registered(self):
        from core.tasks import process_report_generation_job

        assert process_report_generation_job.name == "core.tasks.process_report_generation_job"

    def test_dispatcher_task_registered(self):
        from core.tasks import dispatch_report_generation_jobs

        assert dispatch_report_generation_jobs.name == "core.tasks.dispatch_report_generation_jobs"

    def test_no_circular_import(self):
        from core.tasks import celery_app, dispatch_report_generation_jobs

        assert celery_app is not None
        assert dispatch_report_generation_jobs.name.endswith("dispatch_report_generation_jobs")


class TestBeatScheduleUnchanged:
    def test_existing_entries_preserved(self):
        from core.tasks import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "dispatch-report-generation-jobs" in schedule
        assert "reconcile-report-generation-jobs" in schedule
        assert "send-weekly-tarot-spread" in schedule
        assert "send-monthly-tarot-portal" in schedule
        assert "send-daily-card" not in schedule
        assert "send-daily-tarot-card" not in schedule
