"""Focused regression proofs for Telegram-first security acceptance.

The runner executes this module against its isolated PostgreSQL/Redis sandbox.
"""

import os
import json
import uuid
import logging
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.routes.reports import _render_report_by_type
from core.models import (
    MiniReportGeneration,
    MiniReportGenerationState,
    Order,
    OrderStatus,
    PaymentAttempt,
    Report,
    ReportGenerationJob,
    User,
)
from core.services.full_matrix_checkout import FullMatrixCheckoutService
from core.services.my_reports import MyReportsService


class SecuritySentinels:
    """Run-local values used only by security acceptance assertions."""

    receipt_email = "security-receipt-sentinel@example.test"
    report_marker = "security-report-content-sentinel"
    checkout_token = "security-checkout-capability-must-not-be-logged"
    telegram_token = "123456:security-telegram-token-must-not-be-logged"
    telegram_identity = "security-telegram-identity-must-not-be-logged"
    pdf_marker = "security-pdf-content-must-not-be-logged"
    webhook_marker = "security-webhook-event-must-not-be-logged"
    provider_marker = "security-provider-payment-must-not-be-logged"
    internal_support_marker = "security-support-marker-must-not-be-logged"

    @classmethod
    def from_context(cls) -> "SecuritySentinels":
        context = os.environ.get("NURA_SECURITY_RUN_CONTEXT")
        if not context:
            return cls()
        values = json.loads(open(os.path.join(context, "registry.json"), encoding="utf-8").read())
        instance = cls()
        instance.receipt_email = values["receipt_email"]
        instance.report_marker = values["report_content_marker"]
        instance.checkout_token = values["checkout_capability"]
        instance.telegram_token = values["telegram_token"]
        instance.telegram_identity = values["telegram_identity_marker"]
        instance.pdf_marker = values["pdf_content_marker"]
        instance.webhook_marker = values["webhook_event_marker"]
        instance.provider_marker = values["provider_payment_marker"]
        instance.internal_support_marker = values["internal_support_marker"]
        return instance


def _write_security_artifact(directory: str, name: str, content: str) -> None:
    context = os.environ.get("NURA_SECURITY_RUN_CONTEXT")
    if context is None:
        return
    target = Path(context) / directory / name
    target.write_text(content, encoding="utf-8")


def _telegram_id() -> int:
    return 8_000_000_000 + uuid.uuid4().int % 1_000_000_000


@pytest_asyncio.fixture
async def security_factory() -> async_sessionmaker[AsyncSession]:
    database_url = os.environ.get("NURA_SECURITY_DATABASE_URL")
    if not database_url:
        pytest.skip("security_acceptance_requires_isolated_postgresql_runner")
    engine = create_async_engine(database_url)
    try:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        await engine.dispose()


class _FakeYooKassa:
    def __init__(self) -> None:
        self.create_calls = 0
        self.get_calls = 0
        self.remote_by_id: dict[str, dict] = {}
        self.fail_ids: set[str] = set()
        self.provider_id = (
            SecuritySentinels.from_context().provider_marker
            + "-"
            + uuid.uuid4().hex[:8]
        )

    async def create_payment(self, *, idempotency_key: str, payload: dict) -> dict:
        self.create_calls += 1
        provider_id = self.provider_id
        remote = {
            "id": provider_id,
            "status": "pending",
            "paid": False,
            "amount": {"value": "890.00", "currency": "RUB"},
            "metadata": payload["metadata"],
            "confirmation": {"confirmation_url": "https://provider.test/checkout"},
        }
        self.remote_by_id[provider_id] = remote
        return remote

    async def get_payment(self, provider_payment_id: str) -> dict:
        from tools.telegram_first_security_context import emit_event

        self.get_calls += 1
        emit_event(
            "local_fake_call",
            destination_category="yookassa",
            host_category="loopback",
            allowed=True,
        )
        if provider_payment_id in self.fail_ids:
            raise TimeoutError("synthetic_provider_lookup_failure")
        return self.remote_by_id[provider_payment_id]


def test_uvicorn_access_log_redacts_checkout_capability(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Uvicorn must keep method/status while removing bearer capabilities."""
    import api.main  # noqa: F401 - production ASGI import must install the filter

    capability = SecuritySentinels.from_context().checkout_token
    access_logger = logging.getLogger("uvicorn.access")
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        access_logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:1",
            "GET",
            f"/api/v1/payment/full-matrix/checkout/{capability}",
            "1.1",
            200,
        )

    assert capability not in caplog.text
    assert "GET" in caplog.text and "200" in caplog.text


@pytest.mark.asyncio
async def test_unknown_report_type_log_redacts_report_capability(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A report token is an access capability and must never reach application logs."""
    sentinels = SecuritySentinels.from_context()
    report = SimpleNamespace(
        report_type="unknown",
        token=sentinels.checkout_token,
        ai_analysis={"content": sentinels.report_marker},
        artifact_bytes=sentinels.pdf_marker.encode(),
    )
    monkeypatch.setattr(
        "api.routes.reports.ReportService.render_report_html", AsyncMock(return_value="ok")
    )

    with caplog.at_level(logging.WARNING, logger="api.routes.reports"):
        assert await _render_report_by_type(report, object()) == "ok"

    assert "unknown_report_type_fallback" in caplog.text
    for marker in (
        sentinels.checkout_token,
        sentinels.report_marker,
        sentinels.pdf_marker,
    ):
        assert marker not in caplog.text
    _write_security_artifact(
        "logs", "fallback-rendering-warning.log", caplog.text
    )


@pytest.mark.asyncio
async def test_security_database_is_postgresql_and_idor_is_enforced(
    security_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The attacker cannot enumerate, fetch, or resend the owner's mini report."""
    owner = User(id=uuid.uuid4(), telegram_id=_telegram_id(), username="security-owner")
    attacker = User(id=uuid.uuid4(), telegram_id=_telegram_id(), username="security-attacker")
    report = Report(
        id=uuid.uuid4(), user_id=owner.id, report_type="mini",
        token=SecuritySentinels.from_context().report_marker + uuid.uuid4().hex[:8],
        matrix_data={}, ai_analysis={},
    )
    generation = MiniReportGeneration(
        id=uuid.uuid4(), user_id=owner.id, fingerprint=uuid.uuid4().hex * 2,
        generation_version="security-v1", status=MiniReportGenerationState.COMPLETED,
        report_id=report.id,
    )
    async with security_factory() as session:
        version = (await session.execute(text("SHOW server_version"))).scalar_one()
        assert str(version).startswith("16.")
        session.add_all((owner, attacker))
        await session.flush()
        session.add(report)
        await session.flush()
        session.add(generation)
        await session.commit()

    reports = MyReportsService(security_factory)
    assert (await reports.list_user_reports(attacker.id, 0)).items == ()
    assert await reports.get_user_report(attacker.id, report.id) is None
    assert await reports.prepare_repeated_delivery(attacker.id, report.id, "attacker") is None
    assert (await reports.get_user_report(owner.id, report.id)).report_id == report.id


@pytest.mark.asyncio
async def test_forged_report_callbacks_fail_closed(
    security_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Raw, sequential, and cross-owner callback IDs never dispatch delivery."""
    from bot.handlers import profile

    sentinels = SecuritySentinels.from_context()
    owner = User(id=uuid.uuid4(), telegram_id=_telegram_id(), username="callback-owner")
    attacker = User(id=uuid.uuid4(), telegram_id=_telegram_id(), username="callback-attacker")
    report = Report(
        id=uuid.uuid4(),
        user_id=owner.id,
        report_type="mini",
        token=sentinels.report_marker + uuid.uuid4().hex[:8],
        matrix_data={},
        ai_analysis={},
    )
    generation = MiniReportGeneration(
        id=uuid.uuid4(),
        user_id=owner.id,
        fingerprint=uuid.uuid4().hex * 2,
        generation_version="security-callback-v1",
        status=MiniReportGenerationState.COMPLETED,
        report_id=report.id,
    )
    async with security_factory() as session:
        session.add_all((owner, attacker))
        await session.flush()
        session.add(report)
        await session.flush()
        session.add(generation)
        await session.commit()
    monkeypatch.setattr(profile, "get_async_sessionmaker", lambda: security_factory)
    full_delay = MagicMock()
    mini_delay = MagicMock()
    monkeypatch.setattr(profile.deliver_full_report, "delay", full_delay)
    monkeypatch.setattr(profile.deliver_repeated_mini_report, "delay", mini_delay)

    message = SimpleNamespace(edit_text=AsyncMock())

    def callback(data: str) -> SimpleNamespace:
        return SimpleNamespace(
            id="forged-callback",
            data=data,
            from_user=SimpleNamespace(id=attacker.telegram_id),
            message=message,
            answer=AsyncMock(),
        )

    with caplog.at_level(logging.INFO):
        await profile.my_report_detail(callback(f"reports:view:{report.id.hex}"))
        await profile.my_report_send_again(callback(f"reports:send:{report.id.hex}"))
        await profile.my_report_detail(callback("reports:view:1"))
        await profile.my_report_send_again(callback("reports:send:1"))

    full_delay.assert_not_called()
    mini_delay.assert_not_called()
    rendered = "\n".join(
        str(call.args[0]) for call in message.edit_text.await_args_list
    )
    assert "недоступен" in rendered.casefold()
    for value in (str(report.id), report.id.hex, report.token):
        assert value not in rendered
        assert value not in caplog.text
    _write_security_artifact("responses", "forged-report-callbacks.log", rendered)


@pytest.mark.asyncio
async def test_invalid_checkout_never_calls_provider(
    security_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed capabilities fail before a payment attempt or external boundary."""
    monkeypatch.setattr("core.services.full_matrix_checkout.settings.yookassa_receipt_enabled", True)
    monkeypatch.setattr("core.services.full_matrix_checkout.settings.yookassa_receipt_vat_code", "test_vat")
    monkeypatch.setattr("core.services.full_matrix_checkout.settings.yookassa_receipt_payment_mode", "test_mode")
    monkeypatch.setattr("core.services.full_matrix_checkout.settings.yookassa_receipt_payment_subject", "test_subject")
    provider = _FakeYooKassa()
    service = FullMatrixCheckoutService(security_factory, provider)

    with pytest.raises(ValueError, match="checkout_not_available"):
        await service.start_checkout("not-a-real-opaque-capability", SecuritySentinels.from_context().receipt_email)

    assert provider.create_calls == 0


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_service_start_failure_closes_process_and_capture_handles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-return launch failure must not retain a child or log handle."""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "tools"))
    from tools import telegram_first_service_boot as service_boot

    context = tmp_path / "security-context"
    (context / "logs").mkdir(parents=True)
    environment = os.environ.copy()
    environment["NURA_SECURITY_RUN_CONTEXT"] = str(context)

    def fail_popen(*args, **kwargs):
        raise OSError("controlled_popen_failure")

    monkeypatch.setattr(service_boot.subprocess, "Popen", fail_popen)
    with pytest.raises(OSError, match="controlled_popen_failure"):
        service_boot._start("telegram", [sys.executable, "-c", "pass"], environment)
    for artifact in (context / "logs").iterdir():
        artifact.unlink()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job cleanup contract")
def test_service_job_assignment_failure_terminates_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "tools"))
    from tools import telegram_first_service_boot as service_boot

    context = tmp_path / "security-context"
    (context / "logs").mkdir(parents=True)
    environment = os.environ.copy()
    environment["NURA_SECURITY_RUN_CONTEXT"] = str(context)
    original_popen = subprocess.Popen
    children: list[subprocess.Popen[str]] = []

    def tracked_popen(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        children.append(child)
        return child

    def fail_job_assignment(process):
        raise OSError("controlled_job_assignment_failure")

    monkeypatch.setattr(service_boot.subprocess, "Popen", tracked_popen)
    monkeypatch.setattr(service_boot, "_create_windows_job", fail_job_assignment)
    with pytest.raises(OSError, match="controlled_job_assignment_failure"):
        service_boot._start(
            "telegram", [sys.executable, "-c", "pass"], environment
        )
    assert len(children) == 1 and children[0].poll() is not None
    for artifact in (context / "logs").iterdir():
        artifact.unlink()


@pytest.mark.asyncio
async def test_real_uvicorn_access_log_redacts_checkout_capability(
    security_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Canonical Uvicorn covers invalid and terminal capabilities without disclosure."""
    sentinels = SecuritySentinels.from_context()
    user = User(id=uuid.uuid4(), telegram_id=_telegram_id(), username="security-http")
    paid_user = User(id=uuid.uuid4(), telegram_id=_telegram_id(), username="security-paid")
    refunded_user = User(id=uuid.uuid4(), telegram_id=_telegram_id(), username="security-refunded")
    async with security_factory() as session:
        session.add_all((user, paid_user, refunded_user))
        await session.commit()
    checkout_service = FullMatrixCheckoutService(security_factory)
    order = await checkout_service.create_or_get_order(user_id=user.id)
    paid_order = await checkout_service.create_or_get_order(user_id=paid_user.id)
    refunded_order = await checkout_service.create_or_get_order(user_id=refunded_user.id)
    assert order.checkout_token is not None
    assert paid_order.checkout_token is not None
    assert refunded_order.checkout_token is not None
    async with security_factory() as session:
        live_order = (
            await session.execute(
                select(Order).where(Order.checkout_token == order.checkout_token)
            )
        ).scalar_one()
        paid_row = (
            await session.execute(
                select(Order).where(Order.checkout_token == paid_order.checkout_token)
            )
        ).scalar_one()
        refunded_row = (
            await session.execute(
                select(Order).where(Order.checkout_token == refunded_order.checkout_token)
            )
        ).scalar_one()
        live_order_id = live_order.id
        terminal_at = datetime.now(timezone.utc)
        paid_row.status = OrderStatus.PAID
        paid_row.paid_at = terminal_at
        refunded_row.status = OrderStatus.REFUNDED
        refunded_row.paid_at = terminal_at
        refunded_row.refunded_at = terminal_at
        await session.commit()

    port = _free_loopback_port()
    environment = os.environ.copy()
    security_database = environment["NURA_SECURITY_DATABASE_URL"].rsplit("/", 1)[1]
    environment.update({
        "APP_ENV": "test",
        "NURA_DISABLE_DOTENV": "1",
        "DATABASE_URL": environment["NURA_SECURITY_DATABASE_URL"],
        "POSTGRES_DB": security_database,
        "DEEPSEEK_API_KEY": "security-ai-disabled-probe",
        "NURA_SECURITY_PROCESS_ROLE": "uvicorn-error-path",
        "PYTHONUNBUFFERED": "1",
    })
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=os.path.dirname(os.path.dirname(__file__)), env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    log = ""
    responses: list[dict[str, object]] = []
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1):
                    break
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        else:
            pytest.fail("uvicorn_security_probe_not_ready")
        base = f"http://127.0.0.1:{port}/api/v1/payment/full-matrix"
        with urllib.request.urlopen(f"{base}/checkout/{order.checkout_token}", timeout=2) as response:
            assert response.status == 200
            responses.append({"case": "available", "status": response.status})
        negative_targets = (
            ("malformed", f"{base}/checkout/malformed"),
            ("unknown", f"{base}/checkout/{'x' * 43}"),
            ("paid", f"{base}/checkout/{paid_order.checkout_token}"),
            ("refunded", f"{base}/checkout/{refunded_order.checkout_token}"),
        )
        for case, target in negative_targets:
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(target, timeout=2)
            assert error.value.code == 404
            responses.append(
                {
                    "case": case,
                    "status": error.value.code,
                    "body": error.value.read().decode("utf-8"),
                }
            )
        request = urllib.request.Request(
            f"{base}/checkout/{order.checkout_token}",
            data=f"email={sentinels.receipt_email}\ninvalid".encode(),
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=2)
        assert error.value.code == 404
        responses.append(
            {"case": "invalid-email", "status": error.value.code, "body": error.value.read().decode("utf-8")}
        )
        oversized = urllib.request.Request(
            f"{base}/checkout/{order.checkout_token}",
            data=("email=" + sentinels.report_marker * 300).encode(),
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(oversized, timeout=2)
        assert error.value.code == 404
        responses.append(
            {"case": "oversized", "status": error.value.code, "body": error.value.read().decode("utf-8")}
        )
        with urllib.request.urlopen(f"{base}/return/{order.checkout_token}", timeout=2) as response:
            assert response.status == 200
            responses.append(
                {"case": "return", "status": response.status, "body": response.read().decode("utf-8")}
            )
    finally:
        process.terminate()
        try:
            stdout, _ = process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, _ = process.communicate(timeout=20)
        log += stdout
    assert process.poll() is not None
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))

    for value in (
        order.checkout_token,
        paid_order.checkout_token,
        refunded_order.checkout_token,
        sentinels.receipt_email,
        sentinels.report_marker,
    ):
        assert value not in log
    assert "GET /api/v1/payment/full-matrix/checkout/<redacted>" in log
    assert "POST /api/v1/payment/full-matrix/checkout/<redacted>" in log
    assert "GET /api/v1/payment/full-matrix/return/<redacted>" in log
    assert " 200" in log and " 404" in log
    async with security_factory() as session:
        assert not (
            await session.execute(
                select(PaymentAttempt).where(PaymentAttempt.order_id == live_order_id)
            )
        ).scalars().all()
        stored_user = await session.get(User, user.id)
        assert stored_user is not None and stored_user.has_matrix is False
    _write_security_artifact("logs", "uvicorn-checkout-access.log", log)
    _write_security_artifact(
        "responses", "checkout-error-paths.json", json.dumps(responses, sort_keys=True)
    )


@pytest.mark.asyncio
async def test_full_matrix_webhook_rejections_never_activate(
    security_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forged and inconsistent webhook data cannot create entitlement or work."""
    sentinels = SecuritySentinels.from_context()
    monkeypatch.setattr(
        "core.services.full_matrix_checkout.settings.yookassa_receipt_enabled", True
    )
    monkeypatch.setattr(
        "core.services.full_matrix_checkout.settings.yookassa_receipt_vat_code", "test_vat"
    )
    monkeypatch.setattr(
        "core.services.full_matrix_checkout.settings.yookassa_receipt_payment_mode", "test_mode"
    )
    monkeypatch.setattr(
        "core.services.full_matrix_checkout.settings.yookassa_receipt_payment_subject", "test_subject"
    )
    user = User(id=uuid.uuid4(), telegram_id=_telegram_id(), username="security-webhook")
    async with security_factory() as session:
        session.add(user)
        await session.commit()
    provider = _FakeYooKassa()
    provider_id = provider.provider_id
    service = FullMatrixCheckoutService(security_factory, provider)
    created = await service.create_or_get_order(user_id=user.id)
    await service.start_checkout(created.checkout_token, sentinels.receipt_email)
    async with security_factory() as session:
        order = (
            await session.execute(select(Order).where(Order.user_id == user.id))
        ).scalar_one()
        order_id = order.id
        public_id = order.public_id

    with pytest.raises(ValueError, match="invalid_webhook_payload"):
        await service.process_webhook({"event": "payment.succeeded", "object": {}})

    results: dict[str, str] = {}
    provider.remote_by_id[provider_id].update(
        {"status": "succeeded", "paid": True}
    )
    results["unsupported"] = str(
        (
            await service.process_webhook(
                {
                    "event": sentinels.webhook_marker,
                    "object": {"id": provider_id},
                }
            )
        )["result"]
    )
    provider.remote_by_id[provider_id].update(
        {"status": "pending", "paid": False}
    )
    results["forged-success"] = str(
        (
            await service.process_webhook(
                {
                    "event": "payment.succeeded",
                    "object": {
                        "id": provider_id,
                        "status": "succeeded",
                        "paid": True,
                        "metadata": {"internal": sentinels.internal_support_marker},
                    },
                }
            )
        )["result"]
    )

    def valid_remote(provider_id: str) -> dict:
        return {
            "id": provider_id,
            "status": "succeeded",
            "paid": True,
            "amount": {"value": "890.00", "currency": "RUB"},
            "metadata": {"product_code": "full_matrix", "order_id": public_id},
        }

    for case in (
        "unknown-payment",
        "provider-mismatch",
        "amount-mismatch",
        "currency-mismatch",
    ):
        case_provider_id = provider_id + "-" + case
        remote = valid_remote(case_provider_id)
        if case == "provider-mismatch":
            remote["id"] = provider_id + "-other"
        elif case == "amount-mismatch":
            remote["amount"] = {"value": "1.00", "currency": "RUB"}
        elif case == "currency-mismatch":
            remote["amount"] = {"value": "890.00", "currency": "USD"}
        provider.remote_by_id[case_provider_id] = remote
        result = await service.process_webhook(
            {"event": "payment.succeeded", "object": {"id": case_provider_id}}
        )
        results[case] = str(result["result"])

    temporary_id = provider_id + "-temporary"
    provider.fail_ids.add(temporary_id)
    result = await service.process_webhook(
        {"event": "payment.succeeded", "object": {"id": temporary_id}}
    )
    results["temporary-provider-error"] = str(result["result"])

    assert results == {
        "unsupported": "unsupported_event",
        "forged-success": "pending",
        "unknown-payment": "verification_failed",
        "provider-mismatch": "verification_failed",
        "amount-mismatch": "verification_failed",
        "currency-mismatch": "verification_failed",
        "temporary-provider-error": "retryable_failure",
    }
    async with security_factory() as session:
        stored_order = await session.get(Order, order_id)
        stored_user = await session.get(User, user.id)
        assert stored_order is not None and stored_order.status == OrderStatus.PENDING
        assert stored_order.report_id is None
        assert stored_user is not None and stored_user.has_matrix is False
        assert not (
            await session.execute(select(Report).where(Report.order_id == order_id))
        ).scalars().all()
        assert not (
            await session.execute(
                select(ReportGenerationJob).join(
                    Report, ReportGenerationJob.report_id == Report.id
                ).where(Report.order_id == order_id)
            )
        ).scalars().all()
    _write_security_artifact(
        "responses", "webhook-rejections.json", json.dumps(results, sort_keys=True)
    )


def test_security_guard_blocks_public_destination_only_with_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """The bootstrap guard is opt-in and its blocked record has no endpoint text."""
    from tools.telegram_first_security_context import SecurityContext
    from tools import telegram_first_security_guard as guard

    context = SecurityContext.create({"DATABASE_URL": "postgresql://u:p@127.0.0.1:5432/db", "REDIS_URL": "redis://127.0.0.1:6379/0"})
    try:
        monkeypatch.setenv("NURA_SECURITY_RUN_CONTEXT", str(context.path))
        monkeypatch.setenv("NURA_SECURITY_PROCESS_ROLE", "guard-test")
        guard.install()
        with pytest.raises(OSError, match="security_guard_blocked_destination"):
            socket.create_connection(("203.0.113.1", 443), timeout=0.01)
        artifacts = list((context.path / "events").glob("*.jsonl"))
        assert artifacts
        assert "203.0.113.1" not in artifacts[0].read_text(encoding="utf-8")
    finally:
        context.cleanup()


def test_sentry_scrubber_removes_sensitive_fields_and_keeps_exception_shape() -> None:
    """Production Sentry filtering must retain diagnostics without payload values."""
    from api.logging import scrub_sentry_event

    event = {
        "environment": "test",
        "release": "acceptance",
        "request": {"method": "POST", "url": "sensitive", "headers": {"Authorization": "sensitive"}, "data": "sensitive"},
        "user": {"id": "sensitive", "email": "sensitive"},
        "extra": {
            "receipt_email": "sensitive",
            "error_category": "bounded",
            "correlation_id": "safe-correlation",
        },
        "contexts": {"provider": {"object": "sensitive"}},
        "breadcrumbs": {"values": [{"message": "sensitive"}]},
        "tags": {
            "service": "api",
            "correlation_id": "safe-correlation",
            "unsafe": "sensitive",
        },
        "exception": {"values": [{"type": "RuntimeError", "value": "sensitive", "stacktrace": {"frames": [{"filename": "safe.py", "lineno": 1, "vars": {"secret": "sensitive"}}]}}]},
    }
    scrubbed = scrub_sentry_event(event, {})
    assert scrubbed["exception"]["values"][0]["type"] == "RuntimeError"
    assert scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]["filename"] == "safe.py"
    assert "vars" not in scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert scrubbed["request"] == {"method": "POST"}
    assert "user" not in scrubbed and "breadcrumbs" not in scrubbed
    assert scrubbed["environment"] == "test" and scrubbed["release"] == "acceptance"
    assert scrubbed["extra"] == {
        "error_category": "bounded",
        "correlation_id": "safe-correlation",
    }
    assert scrubbed["tags"] == {
        "service": "api",
        "correlation_id": "safe-correlation",
    }


@pytest.mark.asyncio
async def test_global_bot_error_log_does_not_expose_exception_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The aiogram error boundary must retain a category, not exception text."""
    from bot.handlers.errors import global_error_handler

    marker = SecuritySentinels.from_context().telegram_token
    event = SimpleNamespace(
        exception=RuntimeError(marker),
        update=SimpleNamespace(message=None, callback_query=None),
    )

    with caplog.at_level(logging.ERROR, logger="bot.handlers.errors"):
        assert await global_error_handler(event) is True

    assert marker not in caplog.text
    assert "telegram_update_failed" in caplog.text


def test_security_scanner_negative_control_does_not_disclose_value() -> None:
    """A deliberate isolated leak is reported with safe metadata only."""
    from tools.telegram_first_security_context import scan_artifacts

    sentinel = "negative-control-sensitive-value"
    fixture_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="nura-security-negative-") as directory:
        fixture_path = Path(directory)
        artifact = fixture_path / "sentry" / "envelope-negative.bin"
        artifact.parent.mkdir()
        artifact.write_text(sentinel, encoding="utf-8")
        with pytest.raises(RuntimeError) as error:
            scan_artifacts(fixture_path, {"checkout_capability": sentinel})
        detail = str(error.value)
        assert sentinel not in detail
        assert "alias=checkout_capability" in detail
        assert "path=sentry" in detail
        assert "sink=sentry_envelope" in detail
        assert "count=1" in detail
    assert fixture_path is not None and not fixture_path.exists()


def test_security_scanner_pairwise_control_is_safe() -> None:
    """Pairwise identity context is rejected without disclosing either value."""
    from tools.telegram_first_security_context import scan_artifacts

    birth = "pairwise-birth-sensitive-value"
    identity = "pairwise-identity-sensitive-value"
    fixture_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix="nura-security-pairwise-") as directory:
        fixture_path = Path(directory)
        artifact = fixture_path / "logs" / "pairwise.log"
        artifact.parent.mkdir()
        artifact.write_text(f"{birth} bounded {identity}", encoding="utf-8")
        with pytest.raises(RuntimeError) as error:
            scan_artifacts(
                fixture_path,
                {
                    "birth_date_marker": birth,
                    "telegram_identity_marker": identity,
                },
            )
        detail = str(error.value)
        assert birth not in detail and identity not in detail
        assert "birth_date_marker+telegram_identity_marker" in detail
        assert "sink=subprocess_log" in detail
    assert fixture_path is not None and not fixture_path.exists()
