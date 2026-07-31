"""Audited owner-only full-report generation and resend without purchase."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api import main as api_main
from core.config import settings
from core.models import (
    FullReportTelegramDelivery,
    Order,
    Payment,
    PaymentAttempt,
    Report,
    ReportGenerationState,
    ReportPaymentState,
    User,
)
from core.repositories.full_report_telegram_delivery import (
    PRELAUNCH_FULL_REPORT_DELIVERY_FORMAT,
)
from core.repositories.report import PRELAUNCH_FULL_REPORT_AUDIT_KEY
from core.services.full_report_telegram_delivery import (
    FullReportTelegramDeliveryService,
)
from core.services.prelaunch_full_report import PrelaunchFullReportService
from core.services.telegram_report_delivery import TelegramDocument


FULL_ANALYSIS = {
    key: f"Тестовый текст раздела {key}."
    for _title, key in FullReportTelegramDeliveryService._TEXT_SECTIONS
}


class FakeSender:
    def __init__(self) -> None:
        self.text_calls: list[tuple[int, str]] = []
        self.document_calls: list[int] = []

    async def send_message(self, chat_id: int, text: str) -> int:
        self.text_calls.append((chat_id, text))
        return 1_000 + len(self.text_calls)

    async def send_document_from_artifact(
        self,
        chat_id: int,
        content: bytes,
        filename: str,
        caption: str,
    ) -> TelegramDocument:
        self.document_calls.append(chat_id)
        return TelegramDocument(
            message_id=2_000 + len(self.document_calls),
            file_id="prelaunch-file-id",
        )

    async def send_document_by_file_id(
        self,
        chat_id: int,
        file_id: str,
        caption: str,
    ) -> TelegramDocument:
        self.document_calls.append(chat_id)
        return TelegramDocument(
            message_id=2_000 + len(self.document_calls),
            file_id=file_id,
        )


@pytest.fixture(autouse=True)
def owner_prelaunch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "prelaunch_owner_only", True)
    monkeypatch.setattr(settings, "prelaunch_telegram_allowed_user_ids", "101")
    monkeypatch.setattr(settings, "payments_enabled", False)
    monkeypatch.setattr(settings, "test_mode", False)
    monkeypatch.setattr(settings, "enable_internal_payment_shortcut", False)


@pytest.mark.asyncio
async def test_operator_flow_generates_once_delivers_and_resends_without_entitlement(
    db_engine,
) -> None:
    factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                telegram_id=101,
                first_name="Owner",
                birth_date="01.01.1990",
                has_matrix=False,
            )
        )
        await session.commit()

    generation_dispatches: list[uuid.UUID] = []
    delivery_dispatches: list[uuid.UUID] = []
    service = PrelaunchFullReportService(
        factory,
        dispatch_generation=generation_dispatches.append,
        dispatch_delivery=delivery_dispatches.append,
    )

    first = await service.request(
        user_id=user_id,
        actor="owner.operator",
        reason="Проверка полного отчёта перед запуском",
        request_key="owner-report-001",
    )
    repeated = await service.request(
        user_id=user_id,
        actor="owner.operator",
        reason="Повтор того же запроса до генерации",
        request_key="owner-report-001",
    )

    assert first.status == "generation_queued"
    assert repeated.status == "generation_in_progress"
    assert generation_dispatches == [first.report_id]

    claim = await service.claim_generation(first.report_id)
    assert claim is not None
    report, user, should_generate = claim
    assert user.id == user_id
    assert should_generate is True

    artifact = b"%PDF-" + b"x" * 2048
    await service.complete_generation(
        report.id,
        matrix_data={"center": 1},
        ai_analysis=FULL_ANALYSIS,
        kitchen_analysis={"main_archetype": {"logic": "fixture"}},
        generation_metadata={
            "bundle_id": "nura-report",
            "bundle_version": "v1",
            "bundle_hash": "a" * 64,
            "consumer": "report.full",
            "requested_model": "blocked-provider",
            "provider": "blocked",
            "model": "blocked-provider",
            "generation_source": "fallback",
            "structured_input_hash": "b" * 64,
        },
        artifact=artifact,
    )

    assert len(delivery_dispatches) == 1
    delivery_id = delivery_dispatches[0]
    sender = FakeSender()
    await FullReportTelegramDeliveryService(
        factory, adapter=sender
    ).deliver(delivery_id)

    assert sender.text_calls
    assert sender.document_calls == [101]

    resend = await service.request(
        user_id=user_id,
        actor="owner.operator",
        reason="Проверка повторной доставки сохранённого отчёта",
        request_key="owner-report-002",
    )
    replay = await service.request(
        user_id=user_id,
        actor="owner.operator",
        reason="Replay повторной доставки",
        request_key="owner-report-002",
    )

    assert resend.status == "delivery_queued"
    assert replay.status == "delivery_queued"
    assert replay.delivery_dispatched is False
    assert generation_dispatches == [first.report_id]
    assert len(delivery_dispatches) == 2

    async with factory() as session:
        stored_report = await session.get(Report, first.report_id)
        stored_user = await session.get(User, user_id)
        deliveries = (
            await session.execute(
                select(FullReportTelegramDelivery)
                .where(FullReportTelegramDelivery.report_id == first.report_id)
                .order_by(FullReportTelegramDelivery.created_at)
            )
        ).scalars().all()
        assert stored_report is not None
        assert stored_report.payment_state == ReportPaymentState.AWAITING_PAYMENT
        assert stored_report.generation_state == ReportGenerationState.COMPLETED
        assert stored_report.order_id is None
        assert stored_report.artifact_bytes == artifact
        audit = stored_report.generation_metadata[
            PRELAUNCH_FULL_REPORT_AUDIT_KEY
        ]
        assert audit["actor"] == "owner.operator"
        assert audit["reason"] == "Проверка полного отчёта перед запуском"
        assert datetime.fromisoformat(audit["requested_at"]).tzinfo is not None
        assert len(audit["operations"]) == 2
        assert [item["reason"] for item in audit["operations"]] == [
            "Проверка полного отчёта перед запуском",
            "Проверка повторной доставки сохранённого отчёта",
        ]
        assert [item["action"] for item in audit["operations"]] == [
            "generate",
            "resend",
        ]
        assert stored_user is not None and stored_user.has_matrix is False
        assert len(deliveries) == 2
        assert all(
            item.order_id is None
            and item.delivery_format_version
            == PRELAUNCH_FULL_REPORT_DELIVERY_FORMAT
            for item in deliveries
        )
        assert await session.scalar(select(func.count()).select_from(Order)) == 0
        assert await session.scalar(select(func.count()).select_from(Payment)) == 0
        assert (
            await session.scalar(select(func.count()).select_from(PaymentAttempt))
            == 0
        )


@pytest.mark.asyncio
async def test_dispatch_failure_is_durable_and_same_key_retry_is_idempotent(
    db_engine,
) -> None:
    factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                telegram_id=101,
                birth_date="01.01.1990",
            )
        )
        await session.commit()

    def fail_dispatch(_: uuid.UUID) -> None:
        raise RuntimeError("bounded broker failure")

    failing = PrelaunchFullReportService(
        factory,
        dispatch_generation=fail_dispatch,
    )
    with pytest.raises(RuntimeError, match="bounded broker failure"):
        await failing.request(
            user_id=user_id,
            actor="owner.operator",
            reason="Проверка восстановления после ошибки broker",
            request_key="owner-report-broker",
        )

    dispatches: list[uuid.UUID] = []
    recovered = PrelaunchFullReportService(
        factory,
        dispatch_generation=dispatches.append,
    )
    retry = await recovered.request(
        user_id=user_id,
        actor="owner.operator",
        reason="Повтор после ошибки broker",
        request_key="owner-report-broker",
    )
    replay = await recovered.request(
        user_id=user_id,
        actor="owner.operator",
        reason="Replay того же idempotency key",
        request_key="owner-report-broker",
    )

    assert retry.status == "generation_queued"
    assert replay.status == "generation_in_progress"
    assert dispatches == [retry.report_id]


@pytest.mark.asyncio
async def test_stale_running_prelaunch_generation_is_reconciled(
    db_engine,
) -> None:
    factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                telegram_id=101,
                birth_date="01.01.1990",
            )
        )
        await session.commit()

    initial_dispatches: list[uuid.UUID] = []
    service = PrelaunchFullReportService(
        factory,
        dispatch_generation=initial_dispatches.append,
    )
    requested = await service.request(
        user_id=user_id,
        actor="owner.operator",
        reason="Проверка восстановления потерянного worker",
        request_key="owner-report-worker",
    )
    claim = await service.claim_generation(requested.report_id)
    assert claim is not None

    stale_now = datetime.now(timezone.utc) + timedelta(minutes=31)
    recovery_dispatches: list[uuid.UUID] = []
    reconciler = PrelaunchFullReportService(
        factory,
        dispatch_generation=recovery_dispatches.append,
    )
    result = await reconciler.reconcile_stalled_generations(
        now=stale_now,
        limit=10,
    )

    assert result == {"selected": 1, "dispatched": 1, "errors": 0}
    assert recovery_dispatches == [requested.report_id]
    async with factory() as session:
        report = await session.get(Report, requested.report_id)
        assert report is not None
        assert report.generation_state == ReportGenerationState.PENDING_DISPATCH


@pytest.mark.asyncio
async def test_outsider_cannot_request_prelaunch_full_report(
    db_engine,
) -> None:
    factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                telegram_id=999,
                birth_date="01.01.1990",
            )
        )
        await session.commit()

    with pytest.raises(ValueError, match="prelaunch_owner_not_allowed"):
        await PrelaunchFullReportService(
            factory,
            dispatch_generation=lambda _: None,
        ).request(
            user_id=user_id,
            actor="owner.operator",
            reason="Попытка для пользователя вне allowlist",
            request_key="owner-report-003",
        )

    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Report)) == 0


def test_prelaunch_full_report_route_requires_admin_auth_and_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    monkeypatch.setattr(settings, "admin_token", "owner-admin-token")
    service = AsyncMock()
    service.request.return_value = SimpleNamespace(
        report_id=uuid.uuid4(),
        status="generation_queued",
        generation_dispatched=True,
        delivery_dispatched=False,
    )

    with TestClient(api_main.app) as client, patch(
        "api.routes.admin_api.PrelaunchFullReportService",
        return_value=service,
    ):
        unauthenticated = client.post(
            f"/api/v1/admin/users/{user_id}/prelaunch-full-report",
            json={
                "reason": "Проверка полного отчёта",
                "request_key": "owner-report-004",
            },
        )
        missing_actor = client.post(
            f"/api/v1/admin/users/{user_id}/prelaunch-full-report",
            headers={"X-Admin-Token": "owner-admin-token"},
            json={
                "reason": "Проверка полного отчёта",
                "request_key": "owner-report-004",
            },
        )
        authorized = client.post(
            f"/api/v1/admin/users/{user_id}/prelaunch-full-report",
            headers={
                "X-Admin-Token": "owner-admin-token",
                "X-Admin-Actor": "owner.operator",
            },
            json={
                "reason": "Проверка полного отчёта",
                "request_key": "owner-report-004",
            },
        )

    assert unauthenticated.status_code == 422
    assert missing_actor.status_code == 422
    assert authorized.status_code == 200
    service.request.assert_awaited_once_with(
        user_id=user_id,
        actor="owner.operator",
        reason="Проверка полного отчёта",
        request_key="owner-report-004",
    )
