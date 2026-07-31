"""Disposable PostgreSQL proof for Telegram mini-report delivery.

The outer ``run_alembic_postgres_smoke.py`` owns the exact Docker container.
This harness accepts only its disposable ``DATABASE_URL`` child environment.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
NURA_APP_ROOT = Path(__file__).resolve().parents[1]
PARENT = "c1d2e3f4a5b6"
HEAD = "d2e3f4a5b6c7"
GRAPH_HEAD = "d8e9f0a1b2c3"
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


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", ALEMBIC_LAUNCHER, *args],
        cwd=NURA_APP_ROOT,
        env=os.environ.copy(),
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


def _schema_proof() -> None:
    columns = {
        row[0]: (row[1], row[2], row[3])
        for row in _query(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema='public'
              AND table_name='telegram_report_deliveries'
            ORDER BY ordinal_position
            """
        )
    }
    required = {
        "id",
        "user_id",
        "report_id",
        "mini_report_generation_id",
        "purpose",
        "status",
        "text_status",
        "document_status",
        "attempt_count",
        "retryable",
        "claimed_at",
        "text_message_ids",
        "document_message_id",
        "last_error_code",
        "created_at",
        "updated_at",
    }
    _check("delivery columns exact", set(columns) == required)
    _check(
        "no copied PII/content columns",
        not {"telegram_id", "name", "birth_date", "report_content"} & set(columns),
    )
    for column in (
        "user_id",
        "report_id",
        "mini_report_generation_id",
        "purpose",
        "status",
        "text_status",
        "document_status",
        "attempt_count",
        "retryable",
    ):
        _check(f"{column} is not nullable", columns[column][1] == "NO")
    _check("attempt_count default zero", columns["attempt_count"][2] == "0")
    _check("status default pending", "'pending'" in columns["status"][2])
    _check("text default pending", "'pending'" in columns["text_status"][2])
    _check("document default pending", "'pending'" in columns["document_status"][2])

    constraints = {
        row[0]: row[1]
        for row in _query(
            """
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid='telegram_report_deliveries'::regclass
            """
        )
    }
    _check(
        "unique delivery identity",
        "UNIQUE (mini_report_generation_id, user_id, purpose)"
        in constraints["uq_telegram_report_deliveries_generation_user_purpose"],
    )
    for target in ("users", "reports", "mini_report_generations"):
        definition = next(
            value
            for value in constraints.values()
            if f"REFERENCES {target}(id)" in value
        )
        _check(f"{target} FK cascades", "ON DELETE CASCADE" in definition)
    for check_name in (
        "ck_telegram_report_deliveries_status",
        "ck_telegram_report_deliveries_text_status",
        "ck_telegram_report_deliveries_document_status",
        "ck_telegram_report_deliveries_attempt_count",
    ):
        _check(f"{check_name} exists", check_name in constraints)

    indexes = {
        row[0]
        for row in _query(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname='public'
              AND tablename='telegram_report_deliveries'
            """
        )
    }
    _check(
        "status index exists",
        "ix_telegram_report_deliveries_status" in indexes,
    )
    _check(
        "stale lookup index exists",
        "ix_telegram_report_deliveries_status_claimed_at" in indexes,
    )


def _seed_subject() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    user_id, report_id, generation_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _query(
        """
        INSERT INTO users (id, telegram_id, username, first_name, birth_date)
        VALUES (%s, %s, 'delivery-smoke', 'Smoke', '01.01.2000')
        """,
        (str(user_id), int(user_id.int % 2_000_000_000)),
    )
    _query(
        """
        INSERT INTO reports
            (id, user_id, report_type, token, matrix_data, ai_analysis)
        VALUES (%s, %s, 'mini', %s, '{}'::jsonb, '{}'::jsonb)
        """,
        (str(report_id), str(user_id), uuid.uuid4().hex),
    )
    _query(
        """
        INSERT INTO mini_report_generations
            (id, user_id, fingerprint, generation_version, status, report_id)
        VALUES (%s, %s, %s, 'mini-v1', 'completed', %s)
        """,
        (str(generation_id), str(user_id), uuid.uuid4().hex * 2, str(report_id)),
    )
    return user_id, report_id, generation_id


async def _concurrency_proof() -> None:
    from core.config import settings
    from core.repositories.telegram_report_delivery import (
        TelegramReportDeliveryRepository,
    )

    async_url = _URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        user_id, report_id, generation_id = _seed_subject()
        first_repo = TelegramReportDeliveryRepository(factory)
        second_repo = TelegramReportDeliveryRepository(factory)
        first, second = await asyncio.gather(
            first_repo.get_or_create(
                generation_id=generation_id,
                user_id=user_id,
                report_id=report_id,
            ),
            second_repo.get_or_create(
                generation_id=generation_id,
                user_id=user_id,
                report_id=report_id,
            ),
        )
        _check("concurrent get-or-create returns one row", first.id == second.id)
        count = _query(
            "SELECT count(*) FROM telegram_report_deliveries WHERE user_id=%s",
            (str(user_id),),
        )
        _check("one durable delivery row", count == [(1,)])

        now = datetime.now(timezone.utc)
        attempt_a, attempt_loser = await asyncio.gather(
            first_repo.claim(first.id, now=now),
            second_repo.claim(first.id, now=now),
        )
        winners = [
            attempt
            for attempt in (attempt_a, attempt_loser)
            if attempt is not None
        ]
        _check("concurrent claim has one winner", winners == [1])
        _check(
            "attempt count increments once",
            _query(
                "SELECT attempt_count FROM telegram_report_deliveries WHERE id=%s",
                (str(first.id),),
            )
            == [(1,)],
        )

        _check(
            "attempt A saves text progress",
            await first_repo.save_text_progress(first.id, 1, [101]),
        )
        stale_now = now + timedelta(
            seconds=settings.telegram_delivery_claim_timeout_seconds + 1
        )
        attempt_b = await second_repo.claim(first.id, now=stale_now)
        _check("stale claim recovers to attempt B", attempt_b == 2)
        _check(
            "stale attempt A progress rejected",
            not await first_repo.save_text_progress(first.id, 1, [999]),
        )
        _check(
            "attempt B continues text progress",
            await second_repo.save_text_progress(first.id, 2, [101, 102]),
        )
        _check(
            "attempt B marks text sent",
            await second_repo.mark_text_sent(first.id, 2, [101, 102]),
        )
        _check(
            "retryable document failure preserves text",
            await second_repo.fail(
                first.id,
                2,
                "telegram_network_failure",
                retryable=True,
            ),
        )
        attempt_c = await first_repo.claim(
            first.id,
            now=stale_now + timedelta(seconds=1),
        )
        _check("partial delivery claims attempt C", attempt_c == 3)
        snapshot = await first_repo.get(first.id)
        _check(
            "text receipt survives document retry",
            snapshot is not None
            and snapshot.text_status == "sent"
            and snapshot.text_message_ids == [101, 102]
            and snapshot.document_status == "pending",
        )
        _check(
            "attempt C marks document sent",
            await first_repo.mark_document_sent(first.id, 3, 201),
        )
        _check(
            "attempt C completes delivery",
            await first_repo.complete(first.id, 3),
        )
        _check(
            "delivered row is terminal",
            await second_repo.claim(
                first.id,
                now=stale_now + timedelta(hours=2),
            )
            is None,
        )
        _check(
            "stale attempt cannot overwrite delivered row",
            not await second_repo.mark_document_sent(first.id, 2, 999),
        )

        user2, report2, generation2 = _seed_subject()
        cascade = await first_repo.get_or_create(
            generation_id=generation2,
            user_id=user2,
            report_id=report2,
        )
        _query("DELETE FROM reports WHERE id=%s", (str(report2),))
        _query(
            "DELETE FROM mini_report_generations WHERE id=%s",
            (str(generation2),),
        )
        _query("DELETE FROM users WHERE id=%s", (str(user2),))
        _check(
            "account deletion order is not blocked by delivery",
            await first_repo.get(cascade.id) is None,
        )

        user3, report3, generation3 = _seed_subject()
        report_cascade = await first_repo.get_or_create(
            generation_id=generation3,
            user_id=user3,
            report_id=report3,
        )
        _query("DELETE FROM reports WHERE id=%s", (str(report3),))
        _check(
            "report delete cascades delivery",
            await first_repo.get(report_cascade.id) is None,
        )

        user4, report4, generation4 = _seed_subject()
        generation_cascade = await first_repo.get_or_create(
            generation_id=generation4,
            user_id=user4,
            report_id=report4,
        )
        _query(
            "DELETE FROM mini_report_generations WHERE id=%s",
            (str(generation4),),
        )
        _check(
            "generation delete cascades delivery",
            await first_repo.get(generation_cascade.id) is None,
        )
    finally:
        await engine.dispose()


def main() -> int:
    if not _URL.startswith("postgresql://"):
        print("FATAL: disposable PostgreSQL DATABASE_URL is required")
        return 1
    try:
        print("--- TELEGRAM-DELIVERY-01: blank to head ---")
        _reset_schema()
        _check("blank upgrade succeeds", _alembic("upgrade", "head").returncode == 0)
        _check(
            "blank upgrade reaches head",
            _query("SELECT version_num FROM alembic_version") == [(GRAPH_HEAD,)],
        )

        print("--- TELEGRAM-DELIVERY-02: parent round trip ---")
        _reset_schema()
        _check("upgrade parent succeeds", _alembic("upgrade", PARENT).returncode == 0)
        _check(
            "delivery table absent at parent",
            _query("SELECT to_regclass('public.telegram_report_deliveries')")
            == [(None,)],
        )
        _check("parent to head succeeds", _alembic("upgrade", HEAD).returncode == 0)
        _schema_proof()
        _check("downgrade parent succeeds", _alembic("downgrade", PARENT).returncode == 0)
        _check(
            "downgrade removes only delivery table",
            _query(
                """
                SELECT to_regclass('public.telegram_report_deliveries'),
                       to_regclass('public.users'),
                       to_regclass('public.reports'),
                       to_regclass('public.mini_report_generations')
                """
            )
            == [(None, "users", "reports", "mini_report_generations")],
        )
        _check("re-upgrade head succeeds", _alembic("upgrade", HEAD).returncode == 0)
        _check(
            "alembic version is head",
            _query("SELECT version_num FROM alembic_version") == [(HEAD,)],
        )

        print("--- TELEGRAM-DELIVERY-03: PostgreSQL concurrency ---")
        asyncio.run(_concurrency_proof())
    except Exception as error:
        print(f"FAIL: {type(error).__name__}")
        return 1
    print("ALL TELEGRAM DELIVERY POSTGRESQL PROOFS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
