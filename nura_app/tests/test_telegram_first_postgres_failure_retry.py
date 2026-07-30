"""PostgreSQL failure/retry proof for the Telegram-first paid full report path.

The test intentionally creates only the persona.  Orders, attempts, events, report
and delivery rows are always produced by their production services/tasks.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

if not os.environ.get("NURA_FAILURE_RETRY_DATABASE_URL"):
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("NURA_DISABLE_DOTENV", "1")

import core.database as database_module
from core import tasks
from core.celery_async import _reset_runtime_for_tests
from core.config import settings
from core.fallbacks import FALLBACK_FULL, FALLBACK_KITCHEN
from core.models import (
    FullReportTelegramDelivery, Order, PaymentAttempt, PaymentEvent, Report,
    ReportGenerationJob, ReportGenerationJobState, ReportGenerationState,
    ReportType, User,
)
from core.services.ai import AIService
from core.services.account_deletion import AccountDeletionService
from core.services.full_matrix_checkout import FullMatrixCheckoutService
from core.services.matrix import MatrixService
from core.services.matrix_report_generator import DefaultMatrixReportGenerator, MatrixReportGenerationError, MatrixReportGeneratorResult
from core.services.matrix_report_worker import MatrixReportGenerationWorker
from core.services.report import ReportService
from core.services.report_generation_dispatcher import PublishResult, ReportGenerationDispatcher
from core.services.report_generation_reconciliation import ReportGenerationReconciler
from core.services.telegram_report_delivery import TelegramDeliveryError, TelegramDocument
import core.loop_specs.report_loop as report_loop
import core.services.full_report_telegram_delivery as delivery_module


ROOT = Path(__file__).resolve().parents[1]
_LABEL = "nura.test=telegram-first-failure-retry"
TELEGRAM_ID = 7_778_002
FULL_AI_JSON = __import__("json").dumps({key: "Failure retry sandbox insight. " * 8 for key in FALLBACK_FULL})


def _docker(*args: str) -> str:
    result = subprocess.run(("docker", *args), text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"docker_failed:{args[0]}")
    return result.stdout.strip()


def _wait(container: str, command: tuple[str, ...], port: str) -> int:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if subprocess.run(("docker", "exec", container, *command), capture_output=True, check=False).returncode == 0:
            return int(_docker("port", container, port).rsplit(":", 1)[1])
        time.sleep(0.25)
    raise RuntimeError(f"container_not_ready:{container}")


def _confirmed_absent(completed: subprocess.CompletedProcess[str], kind: str) -> bool:
    if completed.returncode == 0:
        return False
    detail = f"{completed.stdout}\n{completed.stderr}".casefold()
    expected = {
        "container": ("no such object", "no such container"),
        "volume": ("no such volume",),
    }
    return any(marker in detail for marker in expected[kind])


def _owned_volume_names(container: str) -> tuple[str, ...]:
    inspected = subprocess.run(
        (
            "docker",
            "inspect",
            "--format",
            "{{range .Mounts}}{{if eq .Type \"volume\"}}{{println .Name}}{{end}}{{end}}",
            container,
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    if inspected.returncode:
        return ()
    return tuple(line.strip() for line in inspected.stdout.splitlines() if line.strip())


def _remove_owned_container(container: str) -> bool:
    """Remove one exact standalone container and prove that it is absent."""
    for _attempt in range(3):
        subprocess.run(
            ("docker", "rm", "--force", "--volumes", container),
            text=True,
            capture_output=True,
            check=False,
        )
        inspected = subprocess.run(
            ("docker", "inspect", container),
            text=True,
            capture_output=True,
            check=False,
        )
        if _confirmed_absent(inspected, "container"):
            return True
        time.sleep(0.25)
    return False


@pytest.fixture(scope="session", autouse=True)
def standalone_failure_retry_sandbox() -> Any:
    """Supply a disposable, migrated PostgreSQL 16/Redis pair for direct pytest."""
    if os.environ.get("NURA_FAILURE_RETRY_DATABASE_URL"):
        yield
        return
    if shutil.which("docker") is None:
        pytest.fail("failure_retry_standalone_requires_docker")
    suffix = uuid.uuid4().hex[:12]
    pg, redis = f"nura-failure-pg-{suffix}", f"nura-failure-redis-{suffix}"
    created_containers: list[str] = []
    user, database, password = f"nura_{suffix}", f"nura_{suffix}", secrets.token_urlsafe(24)
    prior = {key: os.environ.get(key) for key in (
        "APP_ENV", "NURA_DISABLE_DOTENV", "DATABASE_URL", "NURA_FAILURE_RETRY_DATABASE_URL",
        "REDIS_URL", "NURA_CELERY_BROKER_URL", "NURA_CELERY_RESULT_BACKEND",
    )}
    try:
        _docker("run", "--detach", "--name", pg, "--label", _LABEL, "--env", f"POSTGRES_USER={user}", "--env", f"POSTGRES_PASSWORD={password}", "--env", f"POSTGRES_DB={database}", "--publish", "127.0.0.1::5432", "postgres:16-alpine")
        created_containers.append(pg)
        pg_port = _wait(pg, ("pg_isready", "--username", user, "--dbname", database), "5432/tcp")
        _docker("run", "--detach", "--name", redis, "--label", _LABEL, "--publish", "127.0.0.1::6379", "redis:7-alpine")
        created_containers.append(redis)
        redis_port = _wait(redis, ("redis-cli", "ping"), "6379/tcp")
        url = f"postgresql+asyncpg://{user}:{password}@127.0.0.1:{pg_port}/{database}"
        os.environ.update({"APP_ENV": "test", "NURA_DISABLE_DOTENV": "1", "DATABASE_URL": url, "NURA_FAILURE_RETRY_DATABASE_URL": url, "REDIS_URL": f"redis://127.0.0.1:{redis_port}/0", "NURA_CELERY_BROKER_URL": f"redis://127.0.0.1:{redis_port}/1", "NURA_CELERY_RESULT_BACKEND": f"redis://127.0.0.1:{redis_port}/2"})
        assert subprocess.run((sys.executable, "-m", "alembic", "upgrade", "head"), cwd=ROOT, env=os.environ.copy(), check=False).returncode == 0
        yield
    finally:
        cleanup_errors: list[str] = []
        volumes = {
            volume
                for container in created_containers
            for volume in _owned_volume_names(container)
        }
        try:
            for container in reversed(created_containers):
                if not _remove_owned_container(container):
                    cleanup_errors.append(
                        f"standalone_cleanup_container_unverified:{container}"
                    )
            for volume in volumes:
                inspected = subprocess.run(
                    ("docker", "volume", "inspect", volume),
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if not _confirmed_absent(inspected, "volume"):
                    cleanup_errors.append(
                        f"standalone_cleanup_volume_unverified:{volume}"
                    )
        finally:
            for key, value in prior.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        if cleanup_errors:
            pytest.fail(";".join(cleanup_errors))


@pytest_asyncio.fixture
async def postgres_factory() -> Any:
    url = os.environ.get("NURA_FAILURE_RETRY_DATABASE_URL")
    assert url and url != os.environ.get("NURA_GOLDEN_PATH_DATABASE_URL")
    engine = create_async_engine(url, poolclass=NullPool)
    assert engine.dialect.name == "postgresql"
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            assert str((await session.execute(text("SHOW server_version"))).scalar_one()).startswith("16.")
        yield factory
    finally:
        await engine.dispose()


async def _count(session: AsyncSession, model: type[Any]) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def _run(executor: ThreadPoolExecutor, task: Any, *args: str) -> Any:
    return await asyncio.get_running_loop().run_in_executor(executor, partial(task.run, *args))


class Provider:
    def __init__(self) -> None:
        self.create_calls = 0
        self.lookup_calls = 0
        self.fail_lookup = True
        self.order_id = ""

    async def create_payment(self, *, idempotency_key: str, payload: dict) -> dict:
        self.create_calls += 1
        self.order_id = payload["metadata"]["order_id"]
        return {"id": "failure-retry-payment", "status": "pending", "paid": False, "amount": {"value": "890.00", "currency": "RUB"}, "metadata": payload["metadata"], "confirmation": {"confirmation_url": "https://sandbox.test/pay"}}

    async def get_payment(self, provider_payment_id: str) -> dict:
        self.lookup_calls += 1
        if self.fail_lookup:
            raise ConnectionError("temporary_provider_unavailable")
        return {"id": provider_payment_id, "status": "succeeded", "paid": True, "amount": {"value": "890.00", "currency": "RUB"}, "metadata": {"product_code": "full_matrix", "order_id": self.order_id}, "test": False}


class Publisher:
    async def publish(self, *, job_id: uuid.UUID, report_id: uuid.UUID, task_id: str) -> PublishResult:
        return PublishResult.accepted()


class Telegram:
    calls = 0
    message_calls = 0
    fail = True

    async def send_message(self, chat_id: int, text: str) -> int:
        type(self).message_calls += 1
        return 900 + type(self).message_calls

    async def send_document_from_artifact(self, chat_id: int, content: bytes, filename: str, caption: str) -> TelegramDocument:
        type(self).calls += 1
        if type(self).fail:
            raise TelegramDeliveryError("telegram_network", retryable=True)
        return TelegramDocument(message_id=901, file_id="failure-retry-file")

    async def send_document_by_file_id(self, chat_id: int, file_id: str, caption: str) -> TelegramDocument:
        pytest.fail("first automatic delivery must use the canonical artifact")


class ForbiddenProvider:
    async def create_payment(self, **_: Any) -> dict:
        pytest.fail("fresh replay must not create a provider payment")

    async def get_payment(self, provider_payment_id: str) -> dict:
        pytest.fail(f"fresh replay must not look up provider payment {provider_payment_id}")


class ForbiddenTelegram:
    async def send_document_from_artifact(self, *_: Any, **__: Any) -> TelegramDocument:
        pytest.fail("fresh replay must not upload the completed report")

    async def send_document_by_file_id(self, *_: Any, **__: Any) -> TelegramDocument:
        pytest.fail("fresh replay must not resend the completed report")


@pytest.mark.asyncio
async def test_postgres_webhook_generation_delivery_failure_retry(
    postgres_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One fresh persona proves durable retries and no-op replays across all three boundaries."""
    monkeypatch.setattr(settings, "test_mode", False)
    monkeypatch.setattr(settings, "report_base_url", "https://sandbox.test")
    monkeypatch.setattr(settings, "yookassa_receipt_enabled", True)
    monkeypatch.setattr(settings, "yookassa_receipt_vat_code", "sandbox_vat")
    monkeypatch.setattr(settings, "yookassa_receipt_payment_mode", "full_prepayment")
    monkeypatch.setattr(settings, "yookassa_receipt_payment_subject", "service")
    async with postgres_factory() as session:
        user = User(id=uuid.uuid4(), telegram_id=TELEGRAM_ID, first_name="Failure", birth_date="02.01.2000", pd_consent_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
        session.add(user)
        await session.commit()
    provider = Provider()
    checkout = FullMatrixCheckoutService(postgres_factory, provider)
    token = (await checkout.create_or_get_order(user_id=user.id)).checkout_token
    assert token and await checkout.start_checkout(token, "failure.retry@example.test") == "https://sandbox.test/pay"
    assert provider.create_calls == 1
    payload = {"event": "payment.succeeded", "object": {"id": "failure-retry-payment"}}
    assert await checkout.process_webhook(payload) == {"status": "ok", "result": "retryable_failure"}
    async with postgres_factory() as session:
        event = (await session.execute(select(PaymentEvent))).scalar_one()
        assert event.processing_status == "failed" and event.retryable and event.attempt_count == 1
        assert await _count(session, ReportGenerationJob) == 0
    provider.fail_lookup = False
    assert (await FullMatrixCheckoutService(postgres_factory, provider).process_webhook(payload))["result"] == "activated"
    assert provider.lookup_calls == 2
    assert (await FullMatrixCheckoutService(postgres_factory, provider).process_webhook(payload))["result"] == "already_processed"
    assert provider.lookup_calls == 2
    async with postgres_factory() as session:
        order, attempt = (await session.execute(select(Order))).scalar_one(), (await session.execute(select(PaymentAttempt))).scalar_one()
        report = (await session.execute(select(Report).where(Report.report_type == ReportType.FULL.value))).scalar_one()
        job = (await session.execute(select(ReportGenerationJob))).scalar_one()
        assert order.status == "paid" and attempt.status == "succeeded" and report.generation_state == "pending_dispatch" and job.state == "pending_dispatch"
        report_id, job_id = report.id, job.id
    await ReportGenerationDispatcher(postgres_factory, Publisher()).dispatch_batch(now=__import__("datetime").datetime.now(__import__("datetime").timezone.utc), limit=1)
    ai_calls: list[str] = []
    pdf_calls: list[bytes] = []
    real_pdf = ReportService.generate_pdf.__func__
    generation_attempts = 0
    async def fail_first_generation(self: Any, **kwargs: Any) -> Any:
        nonlocal generation_attempts
        generation_attempts += 1
        if generation_attempts == 1:
            raise MatrixReportGenerationError("ai_provider_unavailable")
        return MatrixReportGeneratorResult(
            matrix_data={"birth_date": kwargs["birth_date"], "source": "production-shaped-fake-ai-boundary"},
            ai_analysis={key: "Failure retry sandbox insight. " * 8 for key in FALLBACK_FULL},
            kitchen_analysis=FALLBACK_KITCHEN,
        )
    async def fake_ai(*_: Any, **kwargs: Any) -> str:
        ai_calls.append(str(kwargs["method_name"]))
        return FULL_AI_JSON
    async def kitchen(*_: Any, **__: Any) -> dict:
        return FALLBACK_KITCHEN
    async def pdf(cls: type[ReportService], html_content: str) -> bytes:
        value = await real_pdf(cls, html_content)
        pdf_calls.append(value)
        return value
    monkeypatch.setattr(database_module, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(AIService, "chat", fake_ai)
    monkeypatch.setattr(AIService, "generate_kitchen_report", kitchen)
    monkeypatch.setattr(DefaultMatrixReportGenerator, "generate", fail_first_generation)
    monkeypatch.setattr(ReportService, "generate_pdf", classmethod(pdf))
    dispatched: list[str] = []
    monkeypatch.setattr(tasks.deliver_full_report, "delay", lambda delivery_id: dispatched.append(delivery_id))
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            first = await _run(executor, tasks.process_report_generation_job, str(job_id), str(report_id))
            assert first["retryable"] is True
            async with postgres_factory() as session:
                report, job = await session.get(Report, report_id), await session.get(ReportGenerationJob, job_id)
                assert report.generation_state == "failed_retryable" and job.state == "failed_retryable" and report.artifact_bytes is None
            retry_now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc) + __import__("datetime").timedelta(minutes=10)
            repaired = await ReportGenerationReconciler(postgres_factory, delivery_dispatch=lambda *_: None).reconcile_batch(now=retry_now, limit=1)
            assert repaired.retries_promoted == 1
            await ReportGenerationDispatcher(postgres_factory, Publisher()).dispatch_batch(now=retry_now, limit=1)
            second = await _run(executor, tasks.process_report_generation_job, str(job_id), str(report_id))
            assert second.get("ok") is True, second
        finally:
            await asyncio.get_running_loop().run_in_executor(executor, _reset_runtime_for_tests)
    assert len(pdf_calls) == 1 and len(dispatched) == 1
    async with postgres_factory() as session:
        report, job = await session.get(Report, report_id), await session.get(ReportGenerationJob, job_id)
        delivery = (await session.execute(select(FullReportTelegramDelivery))).scalar_one()
        assert report.generation_state == "completed" and job.state == "completed" and report.artifact_sha256 == hashlib.sha256(report.artifact_bytes).hexdigest()
        delivery_id, artifact = delivery.id, report.artifact_bytes
    Telegram.calls, Telegram.message_calls, Telegram.fail = 0, 0, True
    monkeypatch.setattr(delivery_module, "TelegramDocumentAdapter", Telegram)
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            with pytest.raises(Exception):
                await _run(executor, tasks.deliver_full_report, str(delivery_id))
            Telegram.fail = False
            await _run(executor, tasks.deliver_full_report, str(delivery_id))
            await _run(executor, tasks.deliver_full_report, str(delivery_id))
        finally:
            await asyncio.get_running_loop().run_in_executor(executor, _reset_runtime_for_tests)
    async with postgres_factory() as session:
        delivery = await session.get(FullReportTelegramDelivery, delivery_id)
        assert delivery.status == "completed" and delivery.telegram_file_id == "failure-retry-file" and Telegram.calls == 2
        assert Telegram.message_calls == delivery.total_text_chunks
        assert (await session.get(Report, report_id)).artifact_bytes == artifact
        assert await _count(session, PaymentEvent) == 1 and await _count(session, ReportGenerationJob) == 1 and await _count(session, FullReportTelegramDelivery) == 1


@pytest.mark.asyncio
async def test_postgres_failure_retry_fresh_process_replay(
    postgres_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new interpreter replays every terminal identity without side effects."""
    if os.environ.get("NURA_FAILURE_RETRY_REPLAY_CHILD") != "1":
        child_env = os.environ.copy()
        child_env["NURA_FAILURE_RETRY_REPLAY_CHILD"] = "1"
        completed = subprocess.run(
            (
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                f"{Path(__file__).name}::test_postgres_failure_retry_fresh_process_replay",
                "-q",
            ),
            cwd=Path(__file__).parent,
            env=child_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, (
            "fresh_process_failure_retry_replay_failed:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
        return

    async with postgres_factory() as session:
        order = (await session.execute(select(Order))).scalar_one()
        event = (await session.execute(select(PaymentEvent))).scalar_one()
        report = (
            await session.execute(
                select(Report).where(Report.report_type == ReportType.FULL.value)
            )
        ).scalar_one()
        job = (await session.execute(select(ReportGenerationJob))).scalar_one()
        delivery = (
            await session.execute(select(FullReportTelegramDelivery))
        ).scalar_one()
        before = (
            await _count(session, PaymentEvent),
            await _count(session, Report),
            await _count(session, ReportGenerationJob),
            await _count(session, FullReportTelegramDelivery),
            report.artifact_sha256,
            delivery.telegram_document_message_id,
            delivery.telegram_file_id,
        )

    payload = {
        "event": "payment.succeeded",
        "object": {"id": event.provider_payment_id},
    }
    replay = await FullMatrixCheckoutService(
        postgres_factory, ForbiddenProvider()
    ).process_webhook(payload)
    assert replay == {"status": "ok", "result": "already_processed"}

    async def forbidden(*_: Any, **__: Any) -> Any:
        pytest.fail("fresh generation replay must not call computation or rendering")

    monkeypatch.setattr(database_module, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(DefaultMatrixReportGenerator, "generate", forbidden)
    monkeypatch.setattr(ReportService, "generate_pdf", classmethod(forbidden))
    monkeypatch.setattr(delivery_module, "TelegramDocumentAdapter", ForbiddenTelegram)
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            generation = await _run(
                executor,
                tasks.process_report_generation_job,
                str(job.id),
                str(report.id),
            )
            assert generation == {
                "ok": True,
                "idempotent": True,
                "disposition": "idempotent_completed",
            }
            assert await _run(
                executor, tasks.deliver_full_report, str(delivery.id)
            ) is None
        finally:
            await asyncio.get_running_loop().run_in_executor(
                executor, _reset_runtime_for_tests
            )

    async with postgres_factory() as session:
        final_report = await session.get(Report, report.id)
        final_delivery = await session.get(FullReportTelegramDelivery, delivery.id)
        after = (
            await _count(session, PaymentEvent),
            await _count(session, Report),
            await _count(session, ReportGenerationJob),
            await _count(session, FullReportTelegramDelivery),
            final_report.artifact_sha256,
            final_delivery.telegram_document_message_id,
            final_delivery.telegram_file_id,
        )
        assert order.status == "paid"
        assert after == before


@pytest.mark.asyncio
async def test_postgres_refund_race_fences_worker_persist_and_retry(
    postgres_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A committed refund immediately before persist wins the paid-order fence."""
    monkeypatch.setattr(settings, "test_mode", False)
    monkeypatch.setattr(settings, "report_base_url", "https://sandbox.test")
    monkeypatch.setattr(settings, "yookassa_receipt_enabled", True)
    monkeypatch.setattr(settings, "yookassa_receipt_vat_code", "sandbox_vat")
    monkeypatch.setattr(settings, "yookassa_receipt_payment_mode", "full_prepayment")
    monkeypatch.setattr(settings, "yookassa_receipt_payment_subject", "service")

    payment_id = f"refund-race-payment-{uuid.uuid4().hex}"
    refund_id = f"refund-race-{uuid.uuid4().hex}"

    class RefundRaceProvider:
        def __init__(self) -> None:
            self.order_id = ""
            self.refund_calls = 0

        async def create_payment(
            self, *, idempotency_key: str, payload: dict
        ) -> dict:
            self.order_id = payload["metadata"]["order_id"]
            return {
                "id": payment_id,
                "status": "pending",
                "paid": False,
                "amount": {"value": "890.00", "currency": "RUB"},
                "metadata": payload["metadata"],
                "confirmation": {"confirmation_url": "https://sandbox.test/pay"},
            }

        async def get_payment(self, provider_payment_id: str) -> dict:
            assert provider_payment_id == payment_id
            return {
                "id": payment_id,
                "status": "succeeded",
                "paid": True,
                "amount": {"value": "890.00", "currency": "RUB"},
                "metadata": {
                    "product_code": "full_matrix",
                    "order_id": self.order_id,
                },
                "test": False,
            }

        async def get_refund(self, provider_refund_id: str) -> dict:
            self.refund_calls += 1
            assert provider_refund_id == refund_id
            return {
                "id": refund_id,
                "payment_id": payment_id,
                "status": "succeeded",
                "amount": {"value": "890.00", "currency": "RUB"},
            }

    async with postgres_factory() as session:
        user = User(
            id=uuid.uuid4(),
            telegram_id=7_778_003,
            first_name="Refund race",
            birth_date="02.01.2000",
            pd_consent_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        )
        session.add(user)
        await session.commit()

    provider = RefundRaceProvider()
    checkout = FullMatrixCheckoutService(postgres_factory, provider)
    token = (await checkout.create_or_get_order(user_id=user.id)).checkout_token
    assert token
    await checkout.start_checkout(token, "refund.race@example.test")
    payment_payload = {"event": "payment.succeeded", "object": {"id": payment_id}}
    assert (await checkout.process_webhook(payment_payload))["result"] == "activated"

    async with postgres_factory() as session:
        report = (
            await session.execute(
                select(Report).where(Report.user_id == user.id)
            )
        ).scalar_one()
        job = (
            await session.execute(
                select(ReportGenerationJob).where(
                    ReportGenerationJob.report_id == report.id
                )
            )
        ).scalar_one()
        report_id, job_id = report.id, job.id

    dispatched = await ReportGenerationDispatcher(
        postgres_factory, Publisher()
    ).dispatch_batch(
        now=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        limit=10,
    )
    assert dispatched.published == 1

    persist_ready = asyncio.Event()
    persist_release = asyncio.Event()

    class RefundRaceGenerator:
        async def generate(self, **_: Any) -> MatrixReportGeneratorResult:
            return MatrixReportGeneratorResult(
                matrix_data={"source": "refund-race"},
                ai_analysis={"status": "must-not-persist"},
                kitchen_analysis=None,
            )

    class RefundRaceWorker(MatrixReportGenerationWorker):
        async def _persist_success(
            self,
            report_id: uuid.UUID,
            generator_result: MatrixReportGeneratorResult,
            artifact: bytes,
        ) -> str:
            persist_ready.set()
            await persist_release.wait()
            return await super()._persist_success(
                report_id, generator_result, artifact
            )

    async def fake_pdf(cls: type[ReportService], html_content: str) -> bytes:
        assert html_content
        return b"%PDF-" + b"r" * 2048

    monkeypatch.setattr(ReportService, "generate_pdf", classmethod(fake_pdf))
    worker_task = asyncio.create_task(
        RefundRaceWorker(postgres_factory, RefundRaceGenerator()).process(
            job_id=job_id, report_id=report_id
        )
    )
    await asyncio.wait_for(persist_ready.wait(), timeout=30)
    refund_payload = {
        "event": "refund.succeeded",
        "object": {"id": refund_id, "payment_id": payment_id},
    }
    assert (await checkout.process_webhook(refund_payload))["result"] == "refunded"
    assert (await checkout.process_webhook(refund_payload))["result"] == "already_processed"
    persist_release.set()
    worker_result = await asyncio.wait_for(worker_task, timeout=30)

    assert worker_result.disposition.value == "terminal_failure"
    assert worker_result.error_category == "entitlement_revoked"
    assert provider.refund_calls == 1
    reconciled = await ReportGenerationReconciler(
        postgres_factory, delivery_dispatch=lambda *_: None
    ).reconcile_batch(
        now=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        + __import__("datetime").timedelta(minutes=10),
        limit=10,
    )
    assert reconciled.retries_promoted == 0

    async with postgres_factory() as session:
        report = await session.get(Report, report_id)
        job = await session.get(ReportGenerationJob, job_id)
        order = (
            await session.execute(select(Order).where(Order.report_id == report_id))
        ).scalar_one()
        refund_event = (
            await session.execute(
                select(PaymentEvent).where(
                    PaymentEvent.provider_object_id == refund_id
                )
            )
        ).scalar_one()
        deliveries = (
            await session.execute(
                select(FullReportTelegramDelivery).where(
                    FullReportTelegramDelivery.report_id == report_id
                )
            )
        ).scalars().all()
        assert order.status == "refunded"
        assert report.generation_state == "failed_terminal"
        assert report.artifact_bytes is None and report.ai_analysis is None
        assert job.state == "failed_terminal"
        assert refund_event.provider_status == "refunded"
        assert deliveries == []


@pytest.mark.asyncio
async def test_postgres_delivery_and_refund_share_order_linearization_point(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A refund cannot commit between the paid check and Telegram completion."""
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    artifact = b"%PDF-" + b"d" * 2048
    async with postgres_factory() as session:
        user = User(
            id=uuid.uuid4(),
            telegram_id=7_778_004,
            first_name="Delivery refund race",
            birth_date="02.01.2000",
            has_matrix=True,
            pd_consent_at=now,
        )
        report = Report(
            id=uuid.uuid4(),
            user_id=user.id,
            report_type=ReportType.FULL.value,
            token=f"delivery-refund-race-{uuid.uuid4().hex}",
            generation_state=ReportGenerationState.COMPLETED,
            artifact_bytes=artifact,
            artifact_sha256=hashlib.sha256(artifact).hexdigest(),
            artifact_size_bytes=len(artifact),
            artifact_mime_type="application/pdf",
            artifact_completed_at=now,
            ai_analysis={key: "Delivery refund race insight." for key in FALLBACK_FULL},
        )
        session.add(user)
        await session.flush()
        session.add(report)
        await session.flush()
        order = Order(
            id=uuid.uuid4(),
            public_id=f"delivery-refund-race-{uuid.uuid4().hex}",
            user_id=user.id,
            telegram_id_snapshot=user.telegram_id,
            product_code="full_matrix",
            amount_kopecks=89_000,
            currency="RUB",
            status="paid",
            report_id=report.id,
            idempotency_key=f"delivery-refund-race-{uuid.uuid4().hex}",
            paid_at=now,
        )
        session.add(order)
        await session.flush()
        report.order_id = order.id
        await session.commit()
        order_id = order.id

    send_started = asyncio.Event()
    release_send = asyncio.Event()

    class BlockingTelegram:
        calls = 0

        async def send_message(self, chat_id: int, text: str) -> int:
            return 800

        async def send_document_from_artifact(
            self, chat_id: int, content: bytes, filename: str, caption: str
        ) -> TelegramDocument:
            type(self).calls += 1
            send_started.set()
            await release_send.wait()
            return TelegramDocument(message_id=902, file_id="delivery-race-file")

        async def send_document_by_file_id(
            self, chat_id: int, file_id: str, caption: str
        ) -> TelegramDocument:
            pytest.fail("the first delivery must upload the canonical artifact")

    service = delivery_module.FullReportTelegramDeliveryService(
        postgres_factory, BlockingTelegram()
    )
    delivery_id = await service.enqueue_automatic(report.id)
    assert delivery_id is not None
    delivery_task = asyncio.create_task(service.deliver(delivery_id))
    await asyncio.wait_for(send_started.wait(), timeout=30)

    refund_committed = asyncio.Event()

    async def commit_refund() -> None:
        async with postgres_factory() as session:
            locked_order = (
                await session.execute(
                    select(Order).where(Order.id == order_id).with_for_update()
                )
            ).scalar_one()
            locked_order.status = "refunded"
            locked_order.refunded_at = now
            await session.commit()
        refund_committed.set()

    refund_task = asyncio.create_task(commit_refund())
    await asyncio.sleep(0.1)
    assert not refund_committed.is_set()
    release_send.set()
    await asyncio.wait_for(delivery_task, timeout=30)
    await asyncio.wait_for(refund_task, timeout=30)

    async with postgres_factory() as session:
        stored_order = await session.get(Order, order_id)
        stored_delivery = await session.get(
            FullReportTelegramDelivery, delivery_id
        )
        assert stored_order.status == "refunded"
        assert stored_delivery.status == "canceled"
        assert stored_delivery.telegram_file_id == "delivery-race-file"
        assert BlockingTelegram.calls == 1

    assert await service.enqueue_manual(
        user.id, report.id, "after-refund"
    ) is None


@pytest.mark.asyncio
async def test_postgres_refund_and_account_deletion_complete_without_deadlock(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production refund and deletion share the User -> Order lock hierarchy."""
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    payment_id = f"delete-race-payment-{uuid.uuid4().hex}"
    refund_id = f"delete-race-refund-{uuid.uuid4().hex}"
    public_id = f"delete-race-order-{uuid.uuid4().hex}"

    async with postgres_factory() as session:
        user = User(
            id=uuid.uuid4(),
            telegram_id=7_778_005,
            first_name="Delete refund race",
            birth_date="02.01.2000",
            has_matrix=True,
            pd_consent_at=now,
        )
        session.add(user)
        await session.flush()
        report = Report(
            id=uuid.uuid4(),
            user_id=user.id,
            report_type=ReportType.FULL.value,
            token=f"delete-refund-race-{uuid.uuid4().hex}",
            generation_state=ReportGenerationState.PENDING_DISPATCH,
        )
        session.add(report)
        await session.flush()
        order = Order(
            id=uuid.uuid4(),
            public_id=public_id,
            user_id=user.id,
            telegram_id_snapshot=user.telegram_id,
            product_code="full_matrix",
            amount_kopecks=89_000,
            currency="RUB",
            status="paid",
            report_id=report.id,
            idempotency_key=f"delete-race-{uuid.uuid4().hex}",
            paid_at=now,
            retain_until=now
            + __import__("datetime").timedelta(days=365 * 5),
        )
        session.add(order)
        await session.flush()
        report.order_id = order.id
        attempt = PaymentAttempt(
            id=uuid.uuid4(),
            order_id=order.id,
            provider="yookassa",
            provider_payment_id=payment_id,
            idempotency_key=f"delete-race-attempt-{uuid.uuid4().hex}",
            status="succeeded",
            amount_kopecks=89_000,
            currency="RUB",
            provider_metadata={
                "product_code": "full_matrix",
                "order_id": public_id,
            },
            paid_at=now,
            retain_until=order.retain_until,
        )
        session.add(attempt)
        await session.flush()
        order.active_payment_id = attempt.id
        session.add(ReportGenerationJob(id=uuid.uuid4(), report_id=report.id))
        await session.commit()
        user_id, order_id, attempt_id = user.id, order.id, attempt.id

    class DeleteRaceProvider:
        async def get_payment(self, provider_payment_id: str) -> dict:
            assert provider_payment_id == payment_id
            await asyncio.sleep(0)
            return {
                "id": payment_id,
                "status": "succeeded",
                "paid": True,
                "amount": {"value": "890.00", "currency": "RUB"},
                "metadata": {
                    "product_code": "full_matrix",
                    "order_id": public_id,
                },
                "test": False,
            }

        async def get_refund(self, provider_refund_id: str) -> dict:
            assert provider_refund_id == refund_id
            await asyncio.sleep(0)
            return {
                "id": refund_id,
                "payment_id": payment_id,
                "status": "succeeded",
                "amount": {"value": "890.00", "currency": "RUB"},
            }

    refund_payload = {
        "event": "refund.succeeded",
        "object": {"id": refund_id, "payment_id": payment_id},
    }
    deletion_has_user_lock = asyncio.Event()
    release_deletion = asyncio.Event()
    refund_waiting_for_user = asyncio.Event()
    refund_reached_order_lock = asyncio.Event()
    original_get = AsyncSession.get

    async def coordinated_get(self, entity, ident, *args, **kwargs):
        task = asyncio.current_task()
        task_name = task.get_name() if task is not None else ""
        is_target_user_lock = bool(
            entity is User
            and ident == user_id
            and kwargs.get("with_for_update") is True
        )
        if is_target_user_lock and task_name == "refund-race":
            refund_waiting_for_user.set()
        result = await original_get(self, entity, ident, *args, **kwargs)
        if is_target_user_lock and task_name == "deletion-race":
            deletion_has_user_lock.set()
            await release_deletion.wait()
        return result

    monkeypatch.setattr(AsyncSession, "get", coordinated_get)

    class ObservedCheckout(FullMatrixCheckoutService):
        @staticmethod
        async def _get_order(
            session: AsyncSession, current_public_id: str, lock: bool
        ) -> Order | None:
            task = asyncio.current_task()
            if lock and task is not None and task.get_name() == "refund-race":
                refund_reached_order_lock.set()
            return await FullMatrixCheckoutService._get_order(
                session, current_public_id, lock
            )

    deletion_task = asyncio.create_task(
        AccountDeletionService(postgres_factory).delete(user_id),
        name="deletion-race",
    )
    await asyncio.wait_for(deletion_has_user_lock.wait(), timeout=30)
    refund_task = asyncio.create_task(
        ObservedCheckout(
            postgres_factory, DeleteRaceProvider()
        ).process_webhook(refund_payload),
        name="refund-race",
    )
    await asyncio.wait_for(refund_waiting_for_user.wait(), timeout=30)
    await asyncio.sleep(0.1)
    assert not refund_reached_order_lock.is_set()
    release_deletion.set()
    refund_result, deletion_result = await asyncio.wait_for(
        asyncio.gather(refund_task, deletion_task), timeout=30
    )
    assert refund_result == {"status": "ok", "result": "refunded"}
    assert deletion_result is None

    async with postgres_factory() as session:
        stored_order = await session.get(Order, order_id)
        stored_attempt = await session.get(PaymentAttempt, attempt_id)
        refund_event = (
            await session.execute(
                select(PaymentEvent).where(
                    PaymentEvent.provider_object_id == refund_id
                )
            )
        ).scalar_one()
        assert await session.get(User, user_id) is None
        assert stored_order.status == "refunded"
        assert stored_order.user_id is None and stored_order.report_id is None
        assert stored_attempt.status == "refunded"
        assert refund_event.processing_status == "processed"
        assert refund_event.provider_status == "refunded"
        assert refund_event.anonymized_at == stored_order.anonymized_at
        assert refund_event.anonymization_reason == "account_deleted"
