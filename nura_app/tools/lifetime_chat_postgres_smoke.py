"""Disposable PostgreSQL proof for the lifetime free-chat ledger."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
NURA_APP_ROOT = REPO_ROOT / "nura_app"
if str(NURA_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(NURA_APP_ROOT))

from core.models import ChatMessageUsage, User  # noqa: E402
from core.services.chat_quota import (  # noqa: E402
    ChatChannel,
    ChatQuotaService,
    ChatUsageStatus,
    QuotaReservationKind,
)


PARENT = "d2e3f4a5b6c7"
HEAD = "d7e8f9a0b1c2"
_URL = ""
_ALEMBIC_LAUNCHER = (
    "from pydantic_settings.sources import DotEnvSettingsSource;"
    "DotEnvSettingsSource.__call__=lambda self:{};"
    "from alembic.config import CommandLine;"
    "CommandLine(prog='alembic').main()"
)


def check(label: str, condition: bool) -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        raise AssertionError(label)


def _validate_disposable_url(value: str) -> None:
    parsed = urlsplit(value)
    check("loopback PostgreSQL URL", parsed.scheme.startswith("postgresql"))
    check("loopback host", parsed.hostname in {"127.0.0.1", "localhost", "::1"})
    check("disposable database name", parsed.path.removeprefix("/").startswith("smoke_"))


def _child_env() -> dict[str, str]:
    allowed = ("COMSPEC", "PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP", "WINDIR")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": _URL,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(NURA_APP_ROOT),
        }
    )
    return env


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _ALEMBIC_LAUNCHER, *args],
        cwd=NURA_APP_ROOT,
        env=_child_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _migrate(*args: str) -> None:
    result = _alembic(*args)
    check(f"alembic {' '.join(args)}", result.returncode == 0)


def _reset_schema() -> None:
    with psycopg2.connect(_URL) as connection, connection.cursor() as cursor:
        cursor.execute("DROP SCHEMA public CASCADE")
        cursor.execute("CREATE SCHEMA public")


def _current_revision() -> str | None:
    with psycopg2.connect(_URL) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        row = cursor.fetchone()
        return None if row is None else str(row[0])


def _table_exists(table_name: str) -> bool:
    with psycopg2.connect(_URL) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
        return cursor.fetchone()[0] is not None


def _insert_existing_user() -> uuid.UUID:
    user_id = uuid.uuid4()
    with psycopg2.connect(_URL) as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO users (id) VALUES (%s)", (str(user_id),))
    return user_id


def _assert_schema() -> None:
    expected = {
        "id": ("uuid", "NO"),
        "user_id": ("uuid", "NO"),
        "request_key": ("character varying", "NO"),
        "channel": ("character varying", "NO"),
        "status": ("character varying", "NO"),
        "billable": ("boolean", "NO"),
        "created_at": ("timestamp with time zone", "NO"),
        "reserved_at": ("timestamp with time zone", "NO"),
        "consumed_at": ("timestamp with time zone", "YES"),
        "released_at": ("timestamp with time zone", "YES"),
        "release_reason": ("character varying", "YES"),
        "response_text": ("text", "YES"),
        "error_code": ("character varying", "YES"),
        "result_ready_at": ("timestamp with time zone", "YES"),
        "updated_at": ("timestamp with time zone", "NO"),
    }
    with psycopg2.connect(_URL) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'chat_message_usages'
            ORDER BY ordinal_position
            """
        )
        rows = cursor.fetchall()
        actual = {name: (data_type, nullable) for name, data_type, nullable, _ in rows}
        defaults = {name: default for name, _, _, default in rows}
        check("exact columns, types, and nullability", actual == expected)
        check("billable default true", defaults["billable"] in ("true", "true::boolean"))
        check("reserved default", "reserved" in str(defaults["status"]))
        check("no raw message or Telegram identifiers", not ({"message", "user_message", "telegram_id"} & actual.keys()))

        cursor.execute(
            """
            SELECT conname, contype, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'public.chat_message_usages'::regclass
            """
        )
        constraints = {name: (kind, definition.lower()) for name, kind, definition in cursor.fetchall()}
        check("unique user/request", constraints["uq_chat_message_usages_user_request"][0] == "u")
        check("channel check", all(value in constraints["ck_chat_message_usages_channel"][1] for value in ("telegram", "web")))
        check("status check", all(value in constraints["ck_chat_message_usages_status"][1] for value in ("reserved", "result_ready", "consumed", "released")))
        check("response state check", "response_text" in constraints["ck_chat_message_usages_response_state"][1])
        timestamp_check = constraints["ck_chat_message_usages_timestamps_state"][1]
        check("state-dependent timestamp check", all(value in timestamp_check for value in ("result_ready_at", "consumed_at", "released_at")))
        fk = constraints[next(name for name, value in constraints.items() if value[0] == "f")][1]
        check("user FK cascade", "users(id) on delete cascade" in fk)

        cursor.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = 'chat_message_usages'
            """
        )
        indexes = {name: definition.lower() for name, definition in cursor.fetchall()}
        check("user/status index", "(user_id, status)" in indexes["ix_chat_message_usages_user_status"])
        check("stale lookup index", "(status, reserved_at)" in indexes["ix_chat_message_usages_stale_reserved"])


def _migration_round_trip() -> None:
    print("Migration round-trip")
    _reset_schema()
    _migrate("upgrade", "head")
    check("blank to head revision", _current_revision() == HEAD)
    _assert_schema()
    blank_user = _insert_existing_user()
    with psycopg2.connect(_URL) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM chat_message_usages WHERE user_id = %s", (str(blank_user),))
        check("blank-to-head existing user has zero rows", cursor.fetchone()[0] == 0)
    _migrate("downgrade", PARENT)
    check("downgrade removes lifetime table", not _table_exists("chat_message_usages"))
    check("downgrade preserves users", _table_exists("users"))
    _migrate("upgrade", HEAD)
    check("re-upgrade records head", _current_revision() == HEAD)
    _assert_schema()

    _reset_schema()
    _migrate("upgrade", PARENT)
    parent_user = _insert_existing_user()
    check("parent has no lifetime table", not _table_exists("chat_message_usages"))
    _migrate("upgrade", HEAD)
    check("parent to head revision", _current_revision() == HEAD)
    with psycopg2.connect(_URL) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM chat_message_usages WHERE user_id = %s", (str(parent_user),))
        check("parent fixture has zero usage rows", cursor.fetchone()[0] == 0)
    _assert_schema()
    _migrate("downgrade", PARENT)
    check("round-trip removes only lifetime table", not _table_exists("chat_message_usages") and _table_exists("users"))
    _migrate("upgrade", HEAD)
    check("final revision is head", _current_revision() == HEAD)


async def _new_user(session_factory, label: str) -> uuid.UUID:
    async with session_factory() as session:
        user = User(name=f"proof-{label}-{uuid.uuid4()}", tarot_subscription=False)
        session.add(user)
        await session.commit()
        return user.id


async def _seed_consumed(session_factory, user_id: uuid.UUID, count: int) -> None:
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        for index in range(count):
            session.add(
                ChatMessageUsage(
                    user_id=user_id,
                    request_key=f"seed-{index}-{uuid.uuid4()}",
                    channel=ChatChannel.WEB.value,
                    status=ChatUsageStatus.CONSUMED.value,
                    response_text="seed",
                    result_ready_at=now,
                    consumed_at=now,
                )
            )
        await session.commit()


async def _count_rows(session_factory, user_id: uuid.UUID) -> int:
    async with session_factory() as session:
        return int(await session.scalar(select(func.count()).select_from(ChatMessageUsage).where(ChatMessageUsage.user_id == user_id)))


async def _postgres_service_proofs() -> None:
    async_url = _URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(async_url, pool_size=10, max_overflow=10)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    service = ChatQuotaService(session_factory)
    try:
        print("Concurrency proofs")
        one_left = await _new_user(session_factory, "one-left")
        await _seed_consumed(session_factory, one_left, 4)
        race = await asyncio.gather(
            service.reserve(one_left, "race-a", ChatChannel.WEB, subscriber=False),
            service.reserve(one_left, "race-b", ChatChannel.WEB, subscriber=False),
        )
        check("one remaining has one winner", [item.kind for item in race].count(QuotaReservationKind.RESERVED_NEW) == 1)
        check("one remaining has one exhausted", [item.kind for item in race].count(QuotaReservationKind.EXHAUSTED) == 1)
        check("consumed plus active is five", await _count_rows(session_factory, one_left) == 5)

        same_key = await _new_user(session_factory, "same-key")
        duplicates = await asyncio.gather(
            service.reserve(same_key, "same", ChatChannel.WEB, subscriber=False),
            service.reserve(same_key, "same", ChatChannel.WEB, subscriber=False),
        )
        check("same key creates one row", await _count_rows(session_factory, same_key) == 1)
        check("same key has one execution winner", [item.kind for item in duplicates].count(QuotaReservationKind.RESERVED_NEW) == 1)
        check("same key returns duplicate state", [item.kind for item in duplicates].count(QuotaReservationKind.DUPLICATE_RESERVED) == 1)
        async with session_factory() as session:
            check("session remains usable", await session.scalar(select(1)) == 1)

        cross = await _new_user(session_factory, "cross")
        await _seed_consumed(session_factory, cross, 4)
        cross_race = await asyncio.gather(
            service.reserve(cross, "telegram", ChatChannel.TELEGRAM, subscriber=False),
            service.reserve(cross, "web", ChatChannel.WEB, subscriber=False),
        )
        check("cross-channel has one shared winner", [item.kind for item in cross_race].count(QuotaReservationKind.RESERVED_NEW) == 1)
        check("cross-channel has one exhausted", [item.kind for item in cross_race].count(QuotaReservationKind.EXHAUSTED) == 1)

        multiple = await _new_user(session_factory, "multiple")
        multiple_race = await asyncio.gather(
            service.reserve(multiple, "a", ChatChannel.WEB, subscriber=False),
            service.reserve(multiple, "b", ChatChannel.TELEGRAM, subscriber=False),
        )
        check("multiple available reserves both", all(item.kind == QuotaReservationKind.RESERVED_NEW for item in multiple_race))

        premium = await _new_user(session_factory, "premium")
        premium_race = await asyncio.gather(
            service.reserve(premium, "premium", ChatChannel.WEB, subscriber=True),
            service.reserve(premium, "premium", ChatChannel.WEB, subscriber=True),
        )
        check("premium same key creates one row", await _count_rows(session_factory, premium) == 1)
        check("premium has one winner", [item.kind for item in premium_race].count(QuotaReservationKind.RESERVED_NEW) == 1)
        async with session_factory() as session:
            premium_row = await session.scalar(select(ChatMessageUsage).where(ChatMessageUsage.user_id == premium))
            check("premium request is non-billable", premium_row is not None and not premium_row.billable)
        check("premium does not reduce free allowance", (await service.state(premium, subscriber=False)).messages_left == 5)

        deleted = await _new_user(session_factory, "cascade")
        await service.reserve(deleted, "delete", ChatChannel.WEB, subscriber=False)
        async with session_factory() as session:
            await session.execute(delete(User).where(User.id == deleted))
            await session.commit()
        check("account deletion cascades usage", await _count_rows(session_factory, deleted) == 0)

        print("State and durable replay proofs")
        state_user = await _new_user(session_factory, "state")
        reservation = await service.reserve(state_user, "state", ChatChannel.WEB, subscriber=False)
        assert reservation.usage_id is not None
        await service.store_result(reservation.usage_id, "durable response")
        ready_state = await service.state(state_user, subscriber=False)
        check("result_ready occupies quota slot", ready_state.messages_left == 4 and ready_state.used == 0)
        async with session_factory() as session:
            ready = await session.get(ChatMessageUsage, reservation.usage_id)
            check("result_ready is durable in a new session", ready is not None and ready.status == "result_ready" and ready.response_text == "durable response")
        replay = await service.reserve(state_user, "state", ChatChannel.WEB, subscriber=False)
        check("duplicate result_ready replays durable response", replay.kind == QuotaReservationKind.DUPLICATE_RESULT and replay.response_text == "durable response")
        consumed = await service.consume(reservation.usage_id)
        consumed_again = await service.consume(reservation.usage_id)
        check("consume is idempotent", consumed.used == consumed_again.used == 1)
        replay_consumed = await service.reserve(state_user, "state", ChatChannel.WEB, subscriber=False)
        check("duplicate consumed replays response", replay_consumed.response_text == "durable response")
        try:
            await service.release(reservation.usage_id, reason="forbidden")
        except RuntimeError as exc:
            check("consumed cannot release", str(exc) == "quota_reservation_not_releasable")
        else:
            raise AssertionError("consumed cannot release")
        check("rejected transition keeps service usable", (await service.state(state_user, subscriber=False)).used == 1)

        release_user = await _new_user(session_factory, "release")
        released = await service.reserve(release_user, "released", ChatChannel.WEB, subscriber=False)
        assert released.usage_id is not None
        release_state = await service.release(released.usage_id, reason="provider_failure")
        release_again = await service.release(released.usage_id, reason="provider_failure")
        check("release is idempotent and returns slot", release_state.messages_left == release_again.messages_left == 5)
        duplicate_released = await service.reserve(release_user, "released", ChatChannel.WEB, subscriber=False)
        check("released duplicate does not create a row", duplicate_released.kind == QuotaReservationKind.DUPLICATE_RELEASED and await _count_rows(session_factory, release_user) == 1)
        try:
            await service.consume(released.usage_id)
        except RuntimeError as exc:
            check("released cannot consume", str(exc) == "quota_result_not_ready")
        else:
            raise AssertionError("released cannot consume")

        stale_user = await _new_user(session_factory, "stale")
        stale = await service.reserve(stale_user, "stale", ChatChannel.WEB, subscriber=False)
        fresh = await service.reserve(stale_user, "fresh", ChatChannel.WEB, subscriber=False)
        assert stale.usage_id is not None and fresh.usage_id is not None
        async with session_factory() as session:
            await session.execute(update(ChatMessageUsage).where(ChatMessageUsage.id == stale.usage_id).values(reserved_at=datetime.now(timezone.utc) - timedelta(minutes=6)))
            await session.commit()
        stale_state = await service.state(stale_user, subscriber=False)
        async with session_factory() as session:
            stale_row = await session.get(ChatMessageUsage, stale.usage_id)
            fresh_row = await session.get(ChatMessageUsage, fresh.usage_id)
            check("stale reserved is released", stale_row is not None and stale_row.status == "released")
            check("fresh reserved is not recovered", fresh_row is not None and fresh_row.status == "reserved")
        check("stale recovery returns only stale slot", stale_state.messages_left == 4)

        ready_old = await service.reserve(stale_user, "ready-old", ChatChannel.WEB, subscriber=False)
        assert ready_old.usage_id is not None
        await service.store_result(ready_old.usage_id, "ready")
        async with session_factory() as session:
            await session.execute(update(ChatMessageUsage).where(ChatMessageUsage.id == ready_old.usage_id).values(reserved_at=datetime.now(timezone.utc) - timedelta(days=1)))
            await session.commit()
        await service.state(stale_user, subscriber=False)
        async with session_factory() as session:
            row = await session.get(ChatMessageUsage, ready_old.usage_id)
            check("result_ready is never stale-released", row is not None and row.status == "result_ready")

        over_user = await _new_user(session_factory, "nonnegative")
        await _seed_consumed(session_factory, over_user, 6)
        check("remaining never becomes negative", (await service.state(over_user, subscriber=False)).messages_left == 0)
    finally:
        await engine.dispose()


def main() -> int:
    global _URL
    _URL = os.environ.get("DATABASE_URL", "")
    try:
        _validate_disposable_url(_URL)
        _migration_round_trip()
        asyncio.run(_postgres_service_proofs())
    except Exception as exc:
        print(f"FATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("Lifetime chat PostgreSQL proof passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
