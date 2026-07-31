"""Disposable PostgreSQL proof for durable daily Tarot draws."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
NURA_APP_ROOT = REPO_ROOT / "nura_app"
if str(NURA_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(NURA_APP_ROOT))

from core.models import DailyTarotDraw, User  # noqa: E402
from core.repositories.daily_tarot_draw import DailyTarotDrawRepository  # noqa: E402

PARENT = "d6e7f8a9b0c1"
HEAD = "d8e9f0a1b2c3"
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
    check("PostgreSQL URL", parsed.scheme.startswith("postgresql"))
    check("loopback host", parsed.hostname in {"127.0.0.1", "localhost", "::1"})
    check("disposable database", parsed.path.removeprefix("/").startswith("smoke_"))


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


def _revision() -> str | None:
    with psycopg2.connect(_URL) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM alembic_version")
        row = cursor.fetchone()
        return None if row is None else str(row[0])


def _table_exists(name: str) -> bool:
    with psycopg2.connect(_URL) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", (f"public.{name}",))
        return cursor.fetchone()[0] is not None


def _insert_existing_user() -> uuid.UUID:
    user_id = uuid.uuid4()
    with psycopg2.connect(_URL) as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO users (id) VALUES (%s)", (str(user_id),))
    return user_id


def _assert_schema() -> None:
    expected_columns = {
        "id": ("uuid", "NO"),
        "user_id": ("uuid", "NO"),
        "local_date": ("date", "NO"),
        "timezone_name": ("character varying", "NO"),
        "status": ("character varying", "NO"),
        "arcana_number": ("integer", "YES"),
        "interpretation": ("text", "YES"),
        "attempt_count": ("integer", "NO"),
        "claimed_at": ("timestamp with time zone", "YES"),
        "completed_at": ("timestamp with time zone", "YES"),
        "failed_at": ("timestamp with time zone", "YES"),
        "error_code": ("character varying", "YES"),
        "error_detail": ("character varying", "YES"),
        "created_at": ("timestamp with time zone", "NO"),
        "updated_at": ("timestamp with time zone", "NO"),
    }
    with psycopg2.connect(_URL) as connection, connection.cursor() as cursor:
        fixture_user_id = uuid.uuid4()
        cursor.execute("INSERT INTO users (id) VALUES (%s)", (str(fixture_user_id),))
        cursor.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='daily_tarot_draws'
            ORDER BY ordinal_position
            """
        )
        actual = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
        check("exact daily draw columns", actual == expected_columns)
        cursor.execute(
            """
            SELECT column_name, character_maximum_length
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='daily_tarot_draws'
              AND column_name IN ('timezone_name', 'status', 'error_code', 'error_detail')
            """
        )
        lengths = dict(cursor.fetchall())
        check(
            "bounded timezone/status/error fields",
            lengths == {"timezone_name": 64, "status": 16, "error_code": 64, "error_detail": 256},
        )
        cursor.execute(
            """
            SELECT conname, contype, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid='daily_tarot_draws'::regclass
            """
        )
        constraints = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
        check("unique user and local date", constraints["uq_daily_tarot_draws_user_local_date"][0] == "u")
        check("state constraint exists", constraints["ck_daily_tarot_draws_state"][0] == "c")
        check(
            "arcana range constraint exists",
            constraints["ck_daily_tarot_draws_arcana_number"][0] == "c",
        )
        foreign_keys = [value[1] for value in constraints.values() if value[0] == "f"]
        check("user FK cascades", len(foreign_keys) == 1 and "ON DELETE CASCADE" in foreign_keys[0])
        cursor.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename='daily_tarot_draws'"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        check("user/date index", "ix_daily_tarot_draws_user_local_date" in indexes)
        check("stale claim index", "ix_daily_tarot_draws_status_claimed_at" in indexes)
        check(
            "no duplicated PII columns",
            not ({"telegram_id", "name", "birth_date", "prompt", "provider_response"} & set(actual)),
        )
        try:
            cursor.execute(
                """
                INSERT INTO daily_tarot_draws
                    (id, user_id, local_date, timezone_name, status, arcana_number,
                     attempt_count, claimed_at, completed_at)
                SELECT gen_random_uuid(), id, DATE '2026-07-26', 'Europe/Moscow',
                       'completed', 5, 1, now(), now()
                FROM users WHERE id = %s
                """,
                (str(fixture_user_id),),
            )
        except psycopg2.errors.CheckViolation:
            connection.rollback()
        else:
            raise AssertionError("completed without interpretation rejected")
        invalid_user_id = uuid.uuid4()
        cursor.execute("INSERT INTO users (id) VALUES (%s)", (str(invalid_user_id),))
        try:
            cursor.execute(
                """
                INSERT INTO daily_tarot_draws
                    (id, user_id, local_date, timezone_name, status, arcana_number,
                     attempt_count, claimed_at)
                VALUES (gen_random_uuid(), %s, DATE '2026-07-26', 'Europe/Moscow',
                        'generating', 23, 1, now())
                """,
                (str(invalid_user_id),),
            )
        except psycopg2.errors.CheckViolation:
            connection.rollback()
            check("out-of-range arcana rejected", True)
        else:
            raise AssertionError("out-of-range arcana rejected")


def _migration_round_trip() -> None:
    print("Migration round-trip")
    _reset_schema()
    _migrate("upgrade", "head")
    check("blank to head", _revision() == HEAD)
    _assert_schema()

    _reset_schema()
    _migrate("upgrade", PARENT)
    existing_user = _insert_existing_user()
    _migrate("upgrade", HEAD)
    check("parent to head", _revision() == HEAD)
    with psycopg2.connect(_URL) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM daily_tarot_draws WHERE user_id=%s", (str(existing_user),))
        check("existing user gets no draw", cursor.fetchone()[0] == 0)
    _assert_schema()
    _migrate("downgrade", PARENT)
    check("head to parent", _revision() == PARENT)
    check("downgrade removes daily table", not _table_exists("daily_tarot_draws"))
    check("downgrade preserves users", _table_exists("users"))
    _migrate("upgrade", HEAD)
    check("re-upgrade returns head", _revision() == HEAD)


async def _new_user(session_factory: async_sessionmaker, label: str) -> uuid.UUID:
    async with session_factory() as session:
        user = User(id=uuid.uuid4(), name=f"daily-proof-{label}-{uuid.uuid4()}")
        session.add(user)
        await session.commit()
        return user.id


async def _row_count(session_factory: async_sessionmaker, user_id: uuid.UUID) -> int:
    async with session_factory() as session:
        result = await session.execute(
            select(DailyTarotDraw).where(DailyTarotDraw.user_id == user_id)
        )
        return len(result.scalars().all())


async def _postgres_concurrency_proofs() -> None:
    print("Concurrency and fencing")
    engine = create_async_engine(_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    repository = DailyTarotDrawRepository(session_factory)
    today = date(2026, 7, 26)
    now = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)
    try:
        owner = await _new_user(session_factory, "owner")
        created = await asyncio.gather(
            *(
                repository.get_or_create(
                    user_id=owner, local_date=today, timezone_name="Europe/Moscow"
                )
                for _ in range(8)
            )
        )
        check("same owner/date has one canonical row", len({item.id for item in created}) == 1)
        check("unique-race session remains usable", await _row_count(session_factory, owner) == 1)
        draw_id = created[0].id

        claims = await asyncio.gather(
            repository.claim(
                draw_id,
                allow_retry=True,
                arcana_number=5,
                now=now,
                stale_before=now - timedelta(minutes=15),
            ),
            repository.claim(
                draw_id,
                allow_retry=True,
                arcana_number=7,
                now=now,
                stale_before=now - timedelta(minutes=15),
            ),
        )
        check("concurrent claim has one winner", sum(item is not None for item in claims) == 1)
        row = await repository.get(draw_id)
        assert row is not None
        check("claim increments once", row.attempt_count == 1)
        check("one canonical card persists", row.arcana_number in {5, 7})

        other = await _new_user(session_factory, "other")
        other_draw = await repository.get_or_create(
            user_id=other, local_date=today, timezone_name="Europe/Moscow"
        )
        next_draw = await repository.get_or_create(
            user_id=owner, local_date=today + timedelta(days=1), timezone_name="Europe/Moscow"
        )
        check("different users get different rows", other_draw.id != draw_id)
        check("next local day gets a new row", next_draw.id != draw_id)

        winner_attempt = next(item for item in claims if item is not None)
        check(
            "failed winner transition",
            await repository.fail(
                draw_id,
                attempt=winner_attempt,
                error_code="daily_tarot_provider_failure",
                now=now + timedelta(minutes=1),
            ),
        )
        failed = await repository.get(draw_id)
        assert failed is not None
        preserved_card = failed.arcana_number
        retry_attempt = await repository.claim(
            draw_id,
            allow_retry=True,
            arcana_number=22,
            now=now + timedelta(minutes=2),
            stale_before=now - timedelta(minutes=15),
        )
        retried = await repository.get(draw_id)
        check("retry uses same row/card", retried is not None and retried.arcana_number == preserved_card)
        check("retry increments attempt", retry_attempt == 2)

        assert retry_attempt is not None
        async with session_factory() as session:
            await session.execute(
                update(DailyTarotDraw)
                .where(DailyTarotDraw.id == draw_id)
                .values(claimed_at=now - timedelta(hours=1))
            )
            await session.commit()
        recovered_attempt = await repository.claim(
            draw_id,
            allow_retry=True,
            arcana_number=22,
            now=now + timedelta(minutes=3),
            stale_before=now - timedelta(minutes=15),
        )
        check("stale claim recovered", recovered_attempt == 3)
        check(
            "stale completion fenced",
            not await repository.complete(
                draw_id, attempt=retry_attempt, interpretation="stale", now=now
            ),
        )
        assert recovered_attempt is not None
        check(
            "current completion succeeds",
            await repository.complete(
                draw_id,
                attempt=recovered_attempt,
                interpretation="durable interpretation",
                now=now + timedelta(minutes=4),
            ),
        )
        check(
            "completed row cannot be claimed",
            await repository.claim(
                draw_id,
                allow_retry=True,
                arcana_number=1,
                now=now + timedelta(hours=2),
                stale_before=now + timedelta(hours=1),
            )
            is None,
        )
        completed = await repository.get(draw_id)
        check(
            "completed interpretation is immutable",
            completed is not None and completed.interpretation == "durable interpretation",
        )

        async with session_factory() as session:
            await session.execute(delete(User).where(User.id == owner))
            await session.commit()
        check("account deletion cascades draws", await _row_count(session_factory, owner) == 0)
        async with session_factory() as session:
            check("session usable after proofs", await session.scalar(text("SELECT 1")) == 1)
    finally:
        await engine.dispose()


def main() -> int:
    global _URL
    _URL = os.environ.get("DATABASE_URL", "")
    try:
        _validate_disposable_url(_URL)
        _migration_round_trip()
        asyncio.run(_postgres_concurrency_proofs())
    except Exception as error:
        print(f"FATAL: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print("Daily Tarot PostgreSQL proof passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
