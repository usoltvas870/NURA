"""Disposable PostgreSQL 16 proofs for full-report Telegram delivery.

The caller owns the disposable container. This harness refuses non-loopback or
non-disposable database URLs and never calls a real external provider.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

NURA_APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = NURA_APP_ROOT.parent
if str(NURA_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(NURA_APP_ROOT))
PARENT = "e8f9a0b1c2d3"
HEAD = "c5d6e7f8a9b0"
WORKERS = 8
_URL = os.environ.get("DATABASE_URL", "")
ALEMBIC_LAUNCHER = (
    "from pydantic_settings.sources import DotEnvSettingsSource;"
    "DotEnvSettingsSource.__call__=lambda self:{};"
    "from alembic.config import CommandLine;"
    "CommandLine(prog='alembic').main()"
)


def _check(label: str, condition: bool) -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        raise AssertionError(label)


def _validate_disposable_database_url(database_url: str) -> None:
    parsed = urlsplit(database_url)
    if parsed.scheme != "postgresql":
        raise ValueError("PostgreSQL URL required")
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Loopback PostgreSQL required")
    if "disposable" not in parsed.path.lower():
        raise ValueError("Disposable database name required")


def _child_env() -> dict[str, str]:
    parsed = urlsplit(_URL)
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "TELEGRAM_BOT_TOKEN",
            "YOOKASSA_SECRET_KEY",
            "DEEPSEEK_API_KEY",
        }
    }
    env.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": _URL,
            "POSTGRES_USER": parsed.username or "",
            "POSTGRES_PASSWORD": parsed.password or "",
            "POSTGRES_DB": parsed.path.lstrip("/"),
            "POSTGRES_HOST": parsed.hostname or "127.0.0.1",
            "POSTGRES_PORT": str(parsed.port or 5432),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return env


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", ALEMBIC_LAUNCHER, *args],
        cwd=NURA_APP_ROOT,
        env=_child_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _query(sql: str, params: tuple = ()) -> list[tuple]:
    with psycopg2.connect(_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall() if cursor.description else []


def _reset_schema() -> None:
    _query("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")


def _seed_parent_rows() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    user_id, full_report_id = uuid.uuid4(), uuid.uuid4()
    mini_report_id, generation_id = uuid.uuid4(), uuid.uuid4()
    order_id, delivery_id = uuid.uuid4(), uuid.uuid4()
    _query(
        """
        INSERT INTO users (id, telegram_id, username, first_name, birth_date, has_matrix)
        VALUES (%s, 991001, 'full-delivery-parent', 'Parent', '01.01.2000', true)
        """,
        (str(user_id),),
    )
    _query(
        """
        INSERT INTO reports
            (id, user_id, report_type, token, payment_state, generation_state,
             generated_at, matrix_data, ai_analysis)
        VALUES (%s, %s, 'full', 'parent-full-report', 'payment_confirmed',
                'completed', now(), '{}'::jsonb, '{}'::jsonb)
        """,
        (str(full_report_id), str(user_id)),
    )
    _query(
        """
        INSERT INTO orders
            (id, public_id, user_id, product_code, amount_kopecks, currency,
             status, report_id, idempotency_key, paid_at)
        VALUES (%s, 'parent-paid-order', %s, 'full_matrix', 89000, 'RUB',
                'paid', %s, 'parent-paid-order-key', now())
        """,
        (str(order_id), str(user_id), str(full_report_id)),
    )
    _query(
        "UPDATE reports SET order_id=%s WHERE id=%s",
        (str(order_id), str(full_report_id)),
    )
    _query(
        """
        INSERT INTO reports (id, user_id, report_type, token, matrix_data, ai_analysis)
        VALUES (%s, %s, 'mini', 'parent-mini-report', '{}'::jsonb, '{}'::jsonb)
        """,
        (str(mini_report_id), str(user_id)),
    )
    _query(
        """
        INSERT INTO mini_report_generations
            (id, user_id, fingerprint, generation_version, status, report_id)
        VALUES (%s, %s, %s, 'mini-v1', 'completed', %s)
        """,
        (str(generation_id), str(user_id), uuid.uuid4().hex * 2, str(mini_report_id)),
    )
    _query(
        """
        INSERT INTO telegram_report_deliveries
            (id, user_id, report_id, mini_report_generation_id)
        VALUES (%s, %s, %s, %s)
        """,
        (str(delivery_id), str(user_id), str(mini_report_id), str(generation_id)),
    )
    return full_report_id, order_id, generation_id, delivery_id


def _schema_proof() -> None:
    columns = {
        row[0]: (row[1], row[2], row[3])
        for row in _query(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema='public'
              AND table_name='full_report_telegram_deliveries'
            ORDER BY ordinal_position
            """
        )
    }
    expected = {
        "id", "report_id", "order_id", "user_id", "delivery_reason",
        "request_key", "status", "retryable", "attempt_count", "claimed_at",
        "queued_at", "sent_at", "failed_at", "telegram_chat_id_snapshot",
        "telegram_document_message_id", "telegram_caption_message_id",
        "telegram_file_id", "artifact_sha256", "artifact_size_bytes",
        "error_code", "error_detail", "created_at", "updated_at",
    }
    _check("delivery columns exact", set(columns) == expected)
    _check(
        "delivery stores no report text, PDF bytes, or PII",
        not {"artifact_bytes", "report_text", "name", "birth_date", "email"}
        & set(columns),
    )
    required = expected - {
        "order_id", "claimed_at", "sent_at", "failed_at",
        "telegram_chat_id_snapshot", "telegram_document_message_id",
        "telegram_caption_message_id", "telegram_file_id", "error_code",
        "error_detail",
    }
    _check("required columns are NOT NULL", all(columns[name][1] == "NO" for name in required))
    _check("queued status default", "queued" in (columns["status"][2] or ""))
    _check("retryable default true", "true" in (columns["retryable"][2] or ""))
    _check("attempt default zero", columns["attempt_count"][2] == "0")

    constraints = {
        row[0]: row[1]
        for row in _query(
            """
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid='full_report_telegram_deliveries'::regclass
            """
        )
    }
    for name in (
        "ck_full_report_delivery_reason", "ck_full_report_delivery_status",
        "ck_full_report_delivery_attempt_count", "ck_full_report_delivery_artifact_size",
        "ck_full_report_delivery_artifact_sha256", "ck_full_report_delivery_state",
        "uq_full_report_delivery_request",
    ):
        _check(f"constraint {name}", name in constraints)
    sha_definition = constraints[
        "ck_full_report_delivery_artifact_sha256"
    ].lower()
    _check(
        "SHA constraint definition is exact hexadecimal",
        "length(" in sha_definition
        and "artifact_sha256" in sha_definition
        and " = 64" in sha_definition
        and ", 1, 1)" in sha_definition
        and ", 64, 1)" in sha_definition
        and all(f"'{value}'" in sha_definition for value in "0123456789abcdef"),
    )
    state_definition = constraints["ck_full_report_delivery_state"].lower()
    _check(
        "state constraint definition covers every lifecycle state",
        all(f"'{status}'" in state_definition for status in (
            "queued", "sending", "completed", "failed", "canceled"
        ))
        and "telegram_document_message_id is not null" in state_definition
        and "attempt_count > 0" in state_definition
        and "error_code is not null" in state_definition,
    )
    for target, action in (("reports", "CASCADE"), ("users", "CASCADE"), ("orders", "SET NULL")):
        definition = next(value for value in constraints.values() if f"REFERENCES {target}(id)" in value)
        _check(f"{target} FK ON DELETE {action}", f"ON DELETE {action}" in definition)

    indexes = {
        row[0]: row[1]
        for row in _query(
            """
            SELECT indexname, indexdef FROM pg_indexes
            WHERE schemaname='public' AND tablename='full_report_telegram_deliveries'
            """
        )
    }
    for name in (
        "uq_full_report_delivery_automatic_report",
        "ix_full_report_delivery_report_id", "ix_full_report_delivery_order_id",
        "ix_full_report_delivery_user_id", "ix_full_report_delivery_status_claimed_at",
        "ix_full_report_delivery_queued_at", "ix_full_report_delivery_request_key",
    ):
        _check(f"index {name}", name in indexes)
    _check(
        "automatic uniqueness is partial",
        "UNIQUE" in indexes["uq_full_report_delivery_automatic_report"]
        and "delivery_reason" in indexes["uq_full_report_delivery_automatic_report"],
    )
    report_columns = {row[0] for row in _query(
        "SELECT column_name FROM information_schema.columns WHERE table_name='reports'"
    )}
    _check(
        "report artifact contract columns",
        {"artifact_bytes", "artifact_sha256", "artifact_size_bytes", "artifact_mime_type", "artifact_completed_at"}
        <= report_columns,
    )


class FakeSender:
    def __init__(self, *, invalid_file_id: bool = False, returned_file_id: str | None = "file-new"):
        self.invalid_file_id = invalid_file_id
        self.returned_file_id = returned_file_id
        self.file_id_calls = 0
        self.artifact_calls = 0

    async def send_document_by_file_id(self, chat_id: int, file_id: str, caption: str):
        from core.services.telegram_report_delivery import TelegramDeliveryError, TelegramDocument

        self.file_id_calls += 1
        if self.invalid_file_id:
            raise TelegramDeliveryError("invalid_file_id", retryable=False)
        return TelegramDocument(message_id=701, file_id=file_id, transport="file_id")

    async def send_document_from_artifact(self, chat_id: int, content: bytes, filename: str, caption: str):
        from core.services.telegram_report_delivery import TelegramDocument

        self.artifact_calls += 1
        return TelegramDocument(message_id=702, file_id=self.returned_file_id, transport="artifact_upload")


async def _seed_subject(factory, *, suffix: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    from core.models import Order, Report, User

    user_id, report_id, order_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    artifact = b"%PDF-" + suffix.encode() + b"x" * 2048
    now = datetime.now(timezone.utc)
    async with factory() as session:
        user = User(id=user_id, telegram_id=int(user_id.int % 2_000_000_000), has_matrix=True)
        report = Report(
            id=report_id, user_id=user_id, report_type="full", token=uuid.uuid4().hex,
            payment_state="payment_confirmed", generation_state="completed", generated_at=now,
            artifact_bytes=artifact, artifact_sha256=hashlib.sha256(artifact).hexdigest(),
            artifact_size_bytes=len(artifact), artifact_mime_type="application/pdf",
            artifact_completed_at=now,
        )
        order = Order(
            id=order_id, public_id=uuid.uuid4().hex, user_id=user_id,
            product_code="full_matrix", amount_kopecks=89_000, currency="RUB",
            status="paid", report_id=report_id, idempotency_key=uuid.uuid4().hex,
            paid_at=now,
        )
        session.add(user)
        await session.flush()
        session.add(report)
        await session.flush()
        session.add(order)
        await session.flush()
        report.order_id = order_id
        await session.commit()
    return user_id, report_id, order_id


async def _wave(call):
    ready = 0
    lock = asyncio.Lock()
    release = asyncio.Event()

    async def worker():
        nonlocal ready
        async with lock:
            ready += 1
            if ready == WORKERS:
                release.set()
        await release.wait()
        return await call()

    return await asyncio.gather(*(worker() for _ in range(WORKERS)))


async def _count(factory, model) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)))


async def _concurrency_proof() -> None:
    from core.config import settings
    from core.models import FullReportTelegramDelivery, Order, Report, ReportGenerationJob, User
    from core.repositories.full_report_telegram_delivery import FullReportTelegramDeliveryRepository
    from core.services.account_deletion import AccountDeletionService
    from core.services.full_report_telegram_delivery import (
        FullReportDeliveryReconciler,
        FullReportTelegramDeliveryService,
    )

    async_url = _URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(async_url, pool_size=20, max_overflow=20)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        user_id, report_id, _order_id = await _seed_subject(factory, suffix="race-a")
        created = await _wave(
            lambda: FullReportTelegramDeliveryService(factory).enqueue_automatic(report_id)
        )
        _check("A one automatic canonical ID", len(set(created)) == 1)
        _check("A one automatic row", await _count(factory, FullReportTelegramDelivery) == 1)
        delivery_id = created[0]
        now = datetime.now(timezone.utc)
        claims = await _wave(lambda: FullReportTelegramDeliveryRepository(factory).claim(delivery_id, now))
        _check("B one claim winner", [value for value in claims if value is not None] == [1])
        _check("B attempt_count=1", (await FullReportTelegramDeliveryRepository(factory).get(delivery_id)).attempt_count == 1)
        fresh = await _wave(lambda: FullReportTelegramDeliveryRepository(factory).claim(delivery_id, now))
        _check("C fresh sending has no winner", all(value is None for value in fresh))

        stale_now = now + timedelta(seconds=settings.telegram_delivery_claim_timeout_seconds + 1)
        stale = await _wave(lambda: FullReportTelegramDeliveryRepository(factory).claim(delivery_id, stale_now))
        _check("D stale recovery one winner", [value for value in stale if value is not None] == [2])
        repo = FullReportTelegramDeliveryRepository(factory)
        _check("D stale attempt fenced", not await repo.complete(delivery_id, 1, message_id=1, file_id="stale"))
        _check("E completion winner", await repo.complete(delivery_id, 2, message_id=202, file_id="file-canonical"))
        completed = await repo.get(delivery_id)
        _check("E receipts persisted", completed.telegram_document_message_id == 202 and completed.telegram_file_id == "file-canonical")
        _check("E completed terminal", await repo.claim(delivery_id, stale_now + timedelta(hours=1)) is None)

        retryable = await FullReportTelegramDeliveryService(factory).enqueue_manual(user_id, report_id, "retryable")
        attempt = await repo.claim(retryable, now)
        _check("F retryable failed", await repo.fail(retryable, attempt, "network", retryable=True))
        retry_wave = await _wave(lambda: FullReportTelegramDeliveryRepository(factory).claim(retryable, now + timedelta(seconds=1)))
        _check("F next wave one winner", [value for value in retry_wave if value is not None] == [2])
        terminal = await FullReportTelegramDeliveryService(factory).enqueue_manual(user_id, report_id, "terminal")
        terminal_attempt = await repo.claim(terminal, now)
        _check("G terminal failed", await repo.fail(terminal, terminal_attempt, "forbidden", retryable=False))
        terminal_wave = await _wave(lambda: FullReportTelegramDeliveryRepository(factory).claim(terminal, stale_now))
        _check("G non-retryable has no claim", all(value is None for value in terminal_wave))

        manuals = await _wave(lambda: FullReportTelegramDeliveryService(factory).enqueue_manual(user_id, report_id, "same-click"))
        _check("H manual double-click one ID", len(set(manuals)) == 1)
        manual_id = manuals[0]
        manual_attempt = await repo.claim(manual_id, now)
        _check("H one active manual", manual_attempt == 1)
        _check("H complete manual", await repo.complete(manual_id, 1, message_id=303, file_id="file-manual"))
        before_counts = (
            await _count(factory, Report), await _count(factory, ReportGenerationJob), await _count(factory, Order)
        )
        new_manual = await FullReportTelegramDeliveryService(factory).enqueue_manual(user_id, report_id, "next-click")
        _check("I new manual row", new_manual != manual_id)
        _check("I domain counts unchanged", before_counts == (
            await _count(factory, Report), await _count(factory, ReportGenerationJob), await _count(factory, Order)
        ))

        sender = FakeSender()
        await FullReportTelegramDeliveryService(factory, sender).deliver(new_manual)
        _check("J file_id reuse only", sender.file_id_calls == 1 and sender.artifact_calls == 0)
        invalid = await FullReportTelegramDeliveryService(factory).enqueue_manual(user_id, report_id, "invalid-file")
        fallback = FakeSender(invalid_file_id=True, returned_file_id="file-replaced")
        await FullReportTelegramDeliveryService(factory, fallback).deliver(invalid)
        _check("K invalid ID falls back once", fallback.file_id_calls == 1 and fallback.artifact_calls == 1)
        next_id = await FullReportTelegramDeliveryService(factory).enqueue_manual(user_id, report_id, "after-fallback")
        next_sender = FakeSender()
        await FullReportTelegramDeliveryService(factory, next_sender).deliver(next_id)
        _check("K replacement becomes canonical", next_sender.file_id_calls == 1 and next_sender.artifact_calls == 0)

        refund_user, refund_report, refund_order = await _seed_subject(factory, suffix="refund")
        refund_delivery = await FullReportTelegramDeliveryService(factory).enqueue_automatic(refund_report)
        async with factory() as session:
            order = await session.get(Order, refund_order)
            order.status = "refunded"
            order.refunded_at = datetime.now(timezone.utc)
            await session.commit()
        refund_sender = FakeSender()
        await FullReportTelegramDeliveryService(factory, refund_sender).deliver(refund_delivery)
        _check("L refund before claim sends nothing", refund_sender.file_id_calls + refund_sender.artifact_calls == 0)
        _check("L refunded delivery canceled", (await repo.get(refund_delivery)).status == "canceled")

        refund2_user, refund2_report, refund2_order = await _seed_subject(factory, suffix="refund-after-claim")
        refund2_delivery = await FullReportTelegramDeliveryService(factory).enqueue_automatic(refund2_report)
        refund2_attempt = await repo.claim(refund2_delivery, now)
        async with factory() as session:
            order = await session.get(Order, refund2_order)
            order.status = "refunded"
            order.refunded_at = datetime.now(timezone.utc)
            await session.commit()
        refund2_sender = FakeSender()
        await FullReportTelegramDeliveryService(factory, refund2_sender).deliver(
            refund2_delivery, claimed_attempt=refund2_attempt
        )
        _check("M refund after claim sends nothing", refund2_sender.file_id_calls + refund2_sender.artifact_calls == 0)
        _check("M claimed delivery canceled", (await repo.get(refund2_delivery)).status == "canceled")

        delete_user, delete_report, _delete_order = await _seed_subject(factory, suffix="delete")
        delete_delivery = await FullReportTelegramDeliveryService(factory).enqueue_automatic(delete_report)
        delete_attempt = await repo.claim(delete_delivery, now)
        await AccountDeletionService(factory).delete(delete_user)
        deleted_sender = FakeSender()
        await FullReportTelegramDeliveryService(factory, deleted_sender).deliver(delete_delivery, claimed_attempt=delete_attempt)
        _check("N deletion removes user/report/delivery", await repo.get(delete_delivery) is None)
        _check("N stale worker cannot send", deleted_sender.file_id_calls + deleted_sender.artifact_calls == 0)
        _check("N stale terminal update rejected", not await repo.complete(delete_delivery, delete_attempt, message_id=1, file_id="gone"))
        async with factory() as session:
            retained_order = await session.scalar(select(Order).where(Order.customer_reference_hash.is_not(None)))
        _check("N financial order retained anonymized", retained_order is not None)

        rec_user, rec_report, _rec_order = await _seed_subject(factory, suffix="reconcile")
        dispatches: list[tuple[uuid.UUID, int]] = []
        reconcilers = [
            FullReportDeliveryReconciler(
                factory,
                dispatch=lambda item, attempt: dispatches.append((item, attempt)),
            )
            for _ in range(WORKERS)
        ]
        rec_ready = 0
        rec_lock = asyncio.Lock()
        rec_release = asyncio.Event()

        async def reconcile_worker(reconciler):
            nonlocal rec_ready
            async with rec_lock:
                rec_ready += 1
                if rec_ready == WORKERS:
                    rec_release.set()
            await rec_release.wait()
            return await reconciler.reconcile_batch(now=now, limit=100)

        await asyncio.gather(*(reconcile_worker(item) for item in reconcilers))
        async with factory() as session:
            automatic_count = await session.scalar(
                select(func.count()).select_from(FullReportTelegramDelivery).where(
                    FullReportTelegramDelivery.report_id == rec_report,
                    FullReportTelegramDelivery.delivery_reason == "automatic",
                )
            )
        _check("O concurrent reconciliation one delivery", automatic_count == 1)
        _check("O concurrent reconciliation one dispatch", len(dispatches) == 1)
        _check("O subject preserved", await _count(factory, User) >= 1 and rec_user is not None)
    finally:
        await engine.dispose()


def _migration_round_trip() -> None:
    print("--- FULL-DELIVERY-PG-01 blank to head ---")
    _reset_schema()
    result = _alembic("upgrade", "head")
    _check("blank upgrade succeeds", result.returncode == 0)
    _check("blank reaches head", _query("SELECT version_num FROM alembic_version") == [(HEAD,)])
    _schema_proof()

    print("--- FULL-DELIVERY-PG-02 parent round-trip and preservation ---")
    _reset_schema()
    _check("upgrade parent succeeds", _alembic("upgrade", PARENT).returncode == 0)
    ids = _seed_parent_rows()
    _check("parent to head succeeds", _alembic("upgrade", HEAD).returncode == 0)
    _schema_proof()
    _check("existing full report preserved", _query("SELECT count(*) FROM reports WHERE id=%s", (str(ids[0]),)) == [(1,)])
    _check("existing paid order preserved", _query("SELECT count(*) FROM orders WHERE id=%s", (str(ids[1]),)) == [(1,)])
    _check("existing mini generation preserved", _query("SELECT count(*) FROM mini_report_generations WHERE id=%s", (str(ids[2]),)) == [(1,)])
    _check("existing mini delivery preserved", _query("SELECT count(*) FROM telegram_report_deliveries WHERE id=%s", (str(ids[3]),)) == [(1,)])
    _check("head to parent succeeds", _alembic("downgrade", PARENT).returncode == 0)
    _check("delivery table removed only", _query(
        "SELECT to_regclass('full_report_telegram_deliveries'), to_regclass('reports'), to_regclass('orders'), to_regclass('telegram_report_deliveries')"
    ) == [(None, "reports", "orders", "telegram_report_deliveries")])
    report_columns = {row[0] for row in _query("SELECT column_name FROM information_schema.columns WHERE table_name='reports'")}
    _check("downgrade removes artifact columns", not any(name.startswith("artifact_") for name in report_columns))
    _check("downgrade preserves seeded rows", _query("SELECT count(*) FROM reports WHERE id=%s", (str(ids[0]),)) == [(1,)])
    _check("repeat upgrade succeeds", _alembic("upgrade", HEAD).returncode == 0)
    _check("alembic_version is head", _query("SELECT version_num FROM alembic_version") == [(HEAD,)])


def main() -> int:
    try:
        _validate_disposable_database_url(_URL)
        _migration_round_trip()
        print("--- FULL-DELIVERY-PG-03 eight-worker delivery races ---")
        asyncio.run(_concurrency_proof())
    except Exception as error:
        print(f"FAIL: {type(error).__name__}: {error}")
        return 1
    print("ALL FULL REPORT TELEGRAM DELIVERY POSTGRESQL PROOFS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
