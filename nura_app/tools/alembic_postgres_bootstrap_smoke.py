"""Alembic PostgreSQL bootstrap smoke harness.

Connects to an already-running disposable PostgreSQL instance through the
``DATABASE_URL`` environment variable only. Docker lifecycle belongs to the
external runner. Controlled ``create_all`` and ``stamp`` calls are used only
to construct disposable test fixtures; they are not production guidance.

Usage:
  set DATABASE_URL=postgresql://user:pass@localhost:5432/dbname
  python tools/alembic_postgres_bootstrap_smoke.py

Exit code 0 = all scenarios passed.
"""

import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import psycopg2
from sqlalchemy.ext.asyncio import create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
NURA_APP_ROOT = REPO_ROOT / "nura_app"

EXPECTED_BASE = "0001a2b3c4d5e6"
FK_NORMALIZATION_HEAD = "c0d1e2f3a4b5"
PREVIOUS_HEAD = "d1e2f3a4b5c6"
EXPECTED_HEAD = "d7e8f9a0b1c2"

_URL = ""

_EXECUTION_ENV_KEYS = (
    "COMSPEC",
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "WINDIR",
)
_ALEMBIC_LAUNCHER = (
    "from pydantic_settings.sources import DotEnvSettingsSource;"
    "DotEnvSettingsSource.__call__=lambda self:{};"
    "from alembic.config import CommandLine;"
    "CommandLine(prog='alembic').main()"
)


def _child_env() -> dict[str, str]:
    env = {key: os.environ[key] for key in _EXECUTION_ENV_KEYS if key in os.environ}
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


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, env=_child_env(), **kwargs
    )


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    msg = f"  [{status}] {label}"
    if detail:
        msg += f" -- {detail}"
    print(msg)
    return condition


def _alembic(*args: str) -> subprocess.CompletedProcess:
    return run(
        [sys.executable, "-c", _ALEMBIC_LAUNCHER, *args], cwd=NURA_APP_ROOT
    )


def _sanitize(text: str) -> str:
    """Remove connection credentials from diagnostics."""
    if not text:
        return text
    if _URL:
        text = text.replace(_URL, "postgresql://***/***")
        try:
            parsed = urlsplit(_URL)
            contextual_values = {
                "user": parsed.username,
                "database": parsed.path.lstrip("/"),
            }
            for label, value in contextual_values.items():
                if value:
                    decoded = unquote(value)
                    text = text.replace(f'{label} "{decoded}"', f'{label} "***"')
                    text = text.replace(f"{label}={decoded}", f"{label}=***")
        except ValueError:
            pass
    text = re.sub(
        r"postgresql(?:\+[^:/]+)?://[^\s@]+@[^/\s]+",
        "postgresql://***@localhost:***",
        text,
    )
    return re.sub(
        r"password=[^\s&\"']+", "password=***", text, flags=re.IGNORECASE
    )


def _query(sql: str) -> list[tuple]:
    """Execute SQL using DATABASE_URL and return typed result rows."""
    try:
        with psycopg2.connect(_URL) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(sql)
                return cursor.fetchall() if cursor.description else []
    except Exception as exc:
        raise RuntimeError(_sanitize(str(exc))) from None


def _sql(sql: str) -> str:
    """Execute SQL and format rows for human-readable diagnostics."""
    rows = _query(sql)
    return "".join(
        "\t".join("" if value is None else str(value) for value in row) + "\n"
        for row in rows
    )


def _normalize_to_asyncpg_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+asyncpg://"):
        return url
    raise ValueError("DATABASE_URL must use PostgreSQL")


def _create_all_schema(connection) -> None:
    from core.models import Base

    Base.metadata.create_all(connection)


def _create_current_model_schema() -> None:
    async def create_schema() -> None:
        engine = create_async_engine(_normalize_to_asyncpg_url(_URL))
        try:
            async with engine.begin() as connection:
                await connection.run_sync(_create_all_schema)
        finally:
            await engine.dispose()

    asyncio.run(create_schema())


def _column_contract(rows: list[tuple]) -> dict[str, tuple[str, str]]:
    return {name: (data_type, nullable) for name, data_type, nullable in rows}


def _legacy_backfill_matches(rows: list[tuple]) -> bool:
    return (
        len(rows) == 1
        and rows[0][0] == "legacy_unlinked"
        and rows[0][1] == "completed"
        and rows[0][2] is not None
        and rows[0][3] is None
        and rows[0][4] == 0
    )


def _mask_url(url: str) -> str:
    """Return a privacy-safe representation."""
    return "postgresql://***@localhost:***/***"


def main():
    global _URL
    _URL = os.environ.get("DATABASE_URL", "")
    if not _URL:
        print("FATAL: DATABASE_URL environment variable not set")
        sys.exit(1)

    print(f"Database: {_mask_url(_URL)}")
    print()

    all_ok = True

    # ── ALEMBIC-BOOT-01: graph ──
    print("--- ALEMBIC-BOOT-01: graph ---")
    result = _alembic("heads")
    ok = check(f"Single head {EXPECTED_HEAD}", EXPECTED_HEAD in result.stdout and result.stdout.count("\n") <= 2,
               result.stdout.strip())
    all_ok &= ok

    result = _alembic("history")
    ok = check("History starts with base -> 0001a2b3c4d5e6",
               "base" in result.stdout and EXPECTED_BASE in result.stdout)
    all_ok &= ok

    ok = check("e475 parent is 0001a2b3c4d5e6",
               f"{EXPECTED_BASE} -> e47590a5c5c1" in result.stdout)
    all_ok &= ok

    result = _alembic("branches")
    ok = check("No branches", result.stdout.strip() == "", result.stdout.strip()[:80])
    all_ok &= ok

    # ── ALEMBIC-BOOT-02: blank upgrade ──
    print("\n--- ALEMBIC-BOOT-02: blank upgrade ---")
    _sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")

    result = _alembic("upgrade", "head")
    ok = check("Upgrade head succeeds", result.returncode == 0,
               f"rc={result.returncode}")
    all_ok &= ok

    result = _alembic("current")
    ok = check(f"Current is {EXPECTED_HEAD}", EXPECTED_HEAD in result.stdout,
               result.stdout.strip().split("\n")[-1])
    all_ok &= ok

    versions = _query("SELECT version_num FROM alembic_version;")
    ok = check("alembic_version single row",
               versions == [(EXPECTED_HEAD,)])
    all_ok &= ok

    # Second upgrade = no-op
    result = _alembic("upgrade", "head")
    ok = check("Second upgrade head is no-op",
               result.returncode == 0 and "Running upgrade" not in result.stdout)
    all_ok &= ok

    # ── ALEMBIC-BOOT-03: schema catalog ──
    print("\n--- ALEMBIC-BOOT-03: schema catalog ---")
    tables = {
        row[0]
        for row in _query(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname='public' ORDER BY tablename;"
        )
    }
    expected = ["alembic_version", "attribution_links", "attribution_touches",
                "guest_profiles", "payments", "promo_codes", "promo_reservations",
                "referral_rewards", "report_generation_jobs", "reports", "users",
                 "mini_report_generations", "telegram_report_deliveries", "daily_tarot_draws"]
    for t in expected:
        ok = check(f"Table {t} exists", t in tables)
        all_ok &= ok

    cols = {
        row[0]
        for row in _query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='reports' ORDER BY ordinal_position;"
        )
    }
    lifecycle_cols = ["payment_id", "payment_state", "payment_confirmed_at",
                      "generation_state", "generation_enqueued_at", "generation_started_at",
                      "generated_at", "generation_failed_at", "generation_attempts",
                      "generation_error_category"]
    for c in lifecycle_cols:
        ok = check(f"Report lifecycle column {c}", c in cols)
        all_ok &= ok

    # Constraints
    cons = {
        row[0]
        for row in _query(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid='reports'::regclass AND contype='u';"
        )
    }
    ok = check("uq_reports_payment_id", "uq_reports_payment_id" in cons)
    all_ok &= ok

    cons = {
        row[0]
        for row in _query(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid='report_generation_jobs'::regclass AND contype='u';"
        )
    }
    ok = check("uq_report_generation_jobs_report_job_type",
               "uq_report_generation_jobs_report_job_type" in cons)
    all_ok &= ok

    attribution_constraints = {
        row[0]: row[1]
        for row in _query(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='attribution_touches'::regclass;"
        )
    }
    ok = check(
        "attribution touch user/code uniqueness",
        "uq_attribution_touches_user_code" in attribution_constraints,
    )
    all_ok &= ok
    user_fk = next(
        (
            definition
            for name, definition in attribution_constraints.items()
            if name != "uq_attribution_touches_user_code"
            and "FOREIGN KEY (user_id)" in definition
        ),
        "",
    )
    ok = check(
        "attribution touch user FK cascades",
        "REFERENCES users(id) ON DELETE CASCADE" in user_fk,
        user_fk,
    )
    all_ok &= ok

    attribution_indexes = {
        row[0]
        for row in _query(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname='public' AND tablename IN "
            "('attribution_links', 'attribution_touches');"
        )
    }
    for index_name in (
        "ix_attribution_links_code",
        "ix_attribution_touches_user_id",
        "ix_attribution_touches_link_id",
        "ix_attribution_touches_first_seen_at",
    ):
        ok = check(f"Attribution index {index_name}", index_name in attribution_indexes)
        all_ok &= ok

    # ── ALEMBIC-BOOT-04: baseline fidelity ──
    print("\n--- ALEMBIC-BOOT-04: baseline fidelity ---")
    _sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    result = _alembic("upgrade", EXPECTED_BASE)
    ok = check("Upgrade to baseline", result.returncode == 0)
    all_ok &= ok

    user_rows = _query(
        "SELECT column_name, data_type, is_nullable "
        "FROM information_schema.columns WHERE table_name='users' "
        "ORDER BY ordinal_position;"
    )
    actual_users = _column_contract(user_rows)
    expected_users = {
        "id": ("uuid", "NO"),
        "telegram_id": ("bigint", "NO"),
        "username": ("character varying", "YES"),
        "first_name": ("character varying", "YES"),
        "birth_date": ("character varying", "YES"),
        "main_archetype": ("character varying", "YES"),
        "main_archetype_number": ("integer", "YES"),
        "subscription_status": ("character varying", "NO"),
        "subscription_until": ("timestamp with time zone", "YES"),
        "payment_method_id": ("character varying", "YES"),
        "has_tarot": ("boolean", "NO"),
        "created_at": ("timestamp with time zone", "NO"),
    }
    ok = check(
        "users baseline columns/types/nullability exact",
        actual_users == expected_users,
        f"actual={actual_users}",
    )
    all_ok &= ok

    report_columns = {
        row[0]
        for row in _query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='reports' ORDER BY ordinal_position;"
        )
    }
    expected_reports = {
        "id", "user_id", "report_type", "token", "matrix_data", "ai_analysis", "created_at"
    }
    ok = check("reports baseline columns exact", report_columns == expected_reports)
    all_ok &= ok

    payment_columns = {
        row[0]
        for row in _query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='payments' ORDER BY ordinal_position;"
        )
    }
    expected_payments = {"id", "user_id", "amount", "status", "yookassa_id", "created_at"}
    ok = check("payments baseline columns exact", payment_columns == expected_payments)
    all_ok &= ok

    # ── ALEMBIC-BOOT-05: baseline downgrade ──
    print("\n--- ALEMBIC-BOOT-05: baseline downgrade ---")
    result = _alembic("downgrade", "base")
    ok = check("Downgrade base succeeds", result.returncode == 0)
    all_ok &= ok

    tables = {
        row[0]
        for row in _query(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname='public' ORDER BY tablename;"
        )
    }
    for t in ["users", "reports", "payments"]:
        ok = check(f"Table {t} removed", t not in tables)
        all_ok &= ok

    ok = check("alembic_version table still exists", "alembic_version" in tables)
    all_ok &= ok

    result = _alembic("upgrade", "head")
    ok = check("Re-upgrade head succeeds", result.returncode == 0)
    all_ok &= ok

    # ── ALEMBIC-BOOT-06: intermediate upgrades ──
    print("\n--- ALEMBIC-BOOT-06: intermediate upgrades ---")
    for target in ["e47590a5c5c1", "f7a8b9c0d1e2", "a8b9c0d1e2f3", PREVIOUS_HEAD]:
        _sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        result = _alembic("upgrade", target)
        ok = check(f"Upgrade to {target}", result.returncode == 0)
        all_ok &= ok

        result = _alembic("upgrade", "head")
        ok = check(f"{target} -> head", result.returncode == 0)
        all_ok &= ok

        result = _alembic("current")
        ok = check(f"Current is head after {target} upgrade",
                   EXPECTED_HEAD in result.stdout)
        all_ok &= ok

    # ── ALEMBIC-BOOT-07: existing head no-op ──
    print("\n--- ALEMBIC-BOOT-07: existing head no-op ---")
    _sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    try:
        _create_current_model_schema()
        fixture_created = True
    except Exception as exc:
        fixture_created = False
        print(f"  [FAIL] Current-model fixture creation -- {_sanitize(str(exc))}")
    all_ok &= check("Current-model fixture creation succeeds", fixture_created)
    fixture_tables = {
        row[0]
        for row in _query(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        )
    }
    required_fixture_tables = {"users", "reports", "payments", "report_generation_jobs"}
    ok = check(
        "Current-model fixture tables exist",
        required_fixture_tables.issubset(fixture_tables),
        str(fixture_tables),
    )
    all_ok &= ok
    if fixture_created and ok:
        stamp_result = _alembic("stamp", EXPECTED_HEAD)
        stamp_succeeded = stamp_result.returncode == 0
    else:
        stamp_succeeded = False
    ok = check("Controlled disposable stamp succeeds", stamp_succeeded)
    all_ok &= ok
    result = _alembic("upgrade", "head")
    ok = check("Upgrade head no-op (baseline not executed)",
               result.returncode == 0 and "0001a2b3c4d5e6" not in result.stdout)
    all_ok &= ok

    versions = _query("SELECT version_num FROM alembic_version;")
    ok = check("Single alembic_version row", versions == [(EXPECTED_HEAD,)])
    all_ok &= ok

    # ── ALEMBIC-BOOT-08: partial schema fail closed ──
    print("\n--- ALEMBIC-BOOT-08: partial schema fail closed ---")
    _sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    # Create users with wrong schema
    _sql("""
        CREATE TABLE users (
            id UUID PRIMARY KEY,
            name VARCHAR(128)
        )
    """)
    result = _alembic("upgrade", "head")
    ok = check("Upgrade fails on partial schema", result.returncode != 0)
    all_ok &= ok

    # Check error is about duplicate table (users already exists)
    combined = result.stdout + result.stderr
    ok = check("Error mentions relation already exists",
               "already exists" in combined.lower() or "duplicate" in combined.lower())
    all_ok &= ok

    version_table = _sql("SELECT to_regclass('public.alembic_version');").strip()
    versions = _sql("SELECT version_num FROM alembic_version;") if version_table else ""
    ok = check("alembic_version NOT populated with head",
               EXPECTED_HEAD not in versions)
    all_ok &= ok

    # ── ALEMBIC-BOOT-09: legacy backfill ──
    print("\n--- ALEMBIC-BOOT-09: legacy backfill ---")
    _sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    _alembic("upgrade", "f7a8b9c0d1e2")
    # Create a user and legacy report
    _sql("""
        INSERT INTO users (id, telegram_id, username, first_name, birth_date)
        VALUES (gen_random_uuid(), 99999, 'legacy', 'Legacy', '01.01.1990')
    """)
    _sql("""
        INSERT INTO reports (id, user_id, report_type, token, created_at)
        VALUES (gen_random_uuid(),
                (SELECT id FROM users WHERE username='legacy'),
                'full', 'legacy-backfill-token',
                NOW() - INTERVAL '30 days')
    """)
    _alembic("upgrade", "head")

    rows = _query("""
        SELECT payment_state, generation_state, generated_at, payment_id, generation_attempts
        FROM reports WHERE token = 'legacy-backfill-token'
    """)
    backfill_exact = _legacy_backfill_matches(rows)
    ok = check("Legacy report backfill values exact", backfill_exact, str(rows))
    all_ok &= ok

    jobs = _query("""
        SELECT count(*) FROM report_generation_jobs
        WHERE report_id = (SELECT id FROM reports WHERE token = 'legacy-backfill-token')
    """)
    ok = check("No generation job created", jobs == [(0,)])
    all_ok &= ok

    # ── ALEMBIC-BOOT-10: downgrade/re-upgrade head ──
    print("\n--- ALEMBIC-BOOT-10: downgrade/re-upgrade head ---")
    result = _alembic("downgrade", "a8b9c0d1e2f3")
    ok = check("Downgrade to a8b9c0d1e2f3", result.returncode == 0)
    all_ok &= ok

    result = _alembic("downgrade", "f7a8b9c0d1e2")
    ok = check("Downgrade to f7a8b9c0d1e2", result.returncode == 0)
    all_ok &= ok

    result = _alembic("upgrade", "head")
    ok = check("Re-upgrade to head", result.returncode == 0)
    all_ok &= ok

    result = _alembic("current")
    ok = check(f"Current is {EXPECTED_HEAD}", EXPECTED_HEAD in result.stdout)
    all_ok &= ok

    # Summary
    print(f"\n{'='*60}")
    if all_ok:
        print("ALL SCENARIOS PASSED")
        print(f"{'='*60}")
        sys.exit(0)
    else:
        print("SOME SCENARIOS FAILED")
        print(f"{'='*60}")
        sys.exit(1)


if __name__ == "__main__":
    main()
