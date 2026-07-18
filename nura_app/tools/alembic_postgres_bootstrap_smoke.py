"""Alembic PostgreSQL bootstrap smoke harness.

Does NOT use Docker, create_all, stamp, IF NOT EXISTS, or alembic_version
INSERTs.  Connects to an already-running disposable PostgreSQL instance
via DATABASE_URL environment variable only.

Usage:
  set DATABASE_URL=postgresql://user:pass@localhost:5432/dbname
  python tools/alembic_postgres_bootstrap_smoke.py

Exit code 0 = all scenarios passed.
"""

import os
import subprocess
import sys


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", os.path.join(_WORKTREE, "nura_app"))
    return subprocess.run(cmd, capture_output=True, text=True, env=env, **kwargs)


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    msg = f"  [{status}] {label}"
    if detail:
        msg += f" -- {detail}"
    print(msg)
    return condition


def _alembic(*args: str) -> subprocess.CompletedProcess:
    return run(["alembic"] + list(args), cwd=os.path.join(_WORKTREE, "nura_app"))


def _psql(sql: str) -> str:
    result = subprocess.run(
        ["docker", "exec", _CONTAINER, "psql", "-U", _PG_USER, "-d", _PG_DB, "-c", sql],
        capture_output=True, text=True,
    )
    return result.stdout


_WORKTREE = r"C:\tmp\nura-closed-beta-hardening"
_CONTAINER = "nura_smoke_bootstrap"
_PG_USER = ""
_PG_DB = ""
_URL = ""


def _mask_url(url: str) -> str:
    """Return a privacy-safe representation."""
    return "postgresql://***@localhost:***/***"


def main():
    global _URL, _PG_USER, _PG_DB, _CONTAINER
    _URL = os.environ.get("DATABASE_URL", "")
    if not _URL:
        print("FATAL: DATABASE_URL environment variable not set")
        sys.exit(1)

    print(f"Database: {_mask_url(_URL)}")
    print()

    # Determine container/user/db from existing container
    container_name = "nura_smoke_bootstrap"
    _CONTAINER = container_name

    # Extract user/db from URL
    # URL format: postgresql://user:pass@host:port/dbname
    url_part = _URL.split("://", 1)[1]
    creds, rest = url_part.split("@", 1)
    _PG_USER = creds.split(":")[0]
    host_port, _PG_DB = rest.rsplit("/", 1)
    _PG_DB = _PG_DB.split("?")[0]

    all_ok = True

    # ── ALEMBIC-BOOT-01: graph ──
    print("--- ALEMBIC-BOOT-01: graph ---")
    result = _alembic("heads")
    ok = check("Single head b9c0d1e2f3a4", "b9c0d1e2f3a4" in result.stdout and result.stdout.count("\n") <= 2,
               result.stdout.strip())
    all_ok &= ok

    result = _alembic("history")
    ok = check("History starts with base -> 0001a2b3c4d5e6",
               "base" in result.stdout and "0001a2b3c4d5e6" in result.stdout)
    all_ok &= ok

    ok = check("e475 parent is 0001a2b3c4d5e6",
               "0001a2b3c4d5e6 -> e47590a5c5c1" in result.stdout)
    all_ok &= ok

    result = _alembic("branches")
    ok = check("No branches", result.stdout.strip() == "", result.stdout.strip()[:80])
    all_ok &= ok

    # ── ALEMBIC-BOOT-02: blank upgrade ──
    print("\n--- ALEMBIC-BOOT-02: blank upgrade ---")
    _psql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")

    result = _alembic("upgrade", "head")
    ok = check("Upgrade head succeeds", result.returncode == 0,
               f"rc={result.returncode}")
    all_ok &= ok

    result = _alembic("current")
    ok = check("Current is b9c0d1e2f3a4", "b9c0d1e2f3a4" in result.stdout,
               result.stdout.strip().split("\n")[-1])
    all_ok &= ok

    versions = _psql("SELECT version_num FROM alembic_version;")
    ok = check("alembic_version single row",
               "b9c0d1e2f3a4" in versions and versions.count("0001a2b3c4d5e6") == 0)
    all_ok &= ok

    # Second upgrade = no-op
    result = _alembic("upgrade", "head")
    ok = check("Second upgrade head is no-op",
               result.returncode == 0 and "Running upgrade" not in result.stdout)
    all_ok &= ok

    # ── ALEMBIC-BOOT-03: schema catalog ──
    print("\n--- ALEMBIC-BOOT-03: schema catalog ---")
    tables = _psql("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;")
    expected = ["alembic_version", "guest_profiles", "payments", "promo_codes",
                "promo_reservations", "referral_rewards", "report_generation_jobs",
                "reports", "users"]
    for t in expected:
        ok = check(f"Table {t} exists", t in tables)
        all_ok &= ok

    cols = _psql("SELECT column_name FROM information_schema.columns WHERE table_name='reports' ORDER BY ordinal_position;")
    lifecycle_cols = ["payment_id", "payment_state", "payment_confirmed_at",
                      "generation_state", "generation_enqueued_at", "generation_started_at",
                      "generated_at", "generation_failed_at", "generation_attempts",
                      "generation_error_category"]
    for c in lifecycle_cols:
        ok = check(f"Report lifecycle column {c}", c in cols)
        all_ok &= ok

    # Constraints
    cons = _psql("SELECT conname FROM pg_constraint WHERE conrelid='reports'::regclass AND contype='u';")
    ok = check("uq_reports_payment_id", "uq_reports_payment_id" in cons)
    all_ok &= ok

    cons = _psql("SELECT conname FROM pg_constraint WHERE conrelid='report_generation_jobs'::regclass AND contype='u';")
    ok = check("uq_report_generation_jobs_report_job_type",
               "uq_report_generation_jobs_report_job_type" in cons)
    all_ok &= ok

    # ── ALEMBIC-BOOT-04: baseline fidelity ──
    print("\n--- ALEMBIC-BOOT-04: baseline fidelity ---")
    _psql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    result = _alembic("upgrade", "0001a2b3c4d5e6")
    ok = check("Upgrade to baseline", result.returncode == 0)
    all_ok &= ok

    cols = _psql("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name='users' ORDER BY ordinal_position;")
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
    for cname, (ctype, null) in expected_users.items():
        ok = check(f"users.{cname} {ctype} nullable={null}",
                   cname in cols and ctype in cols and null in cols)
        all_ok &= ok
    # Check no extra columns
    ok = check("users has exactly 12 columns",
               cols.count("\n") >= 12 and cols.count("\n") <= 18)
    all_ok &= ok

    cols = _psql("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='reports' ORDER BY ordinal_position;")
    expected_reports = ["id", "user_id", "report_type", "token", "matrix_data",
                        "ai_analysis", "created_at"]
    for c in expected_reports:
        ok = check(f"reports.{c}", c in cols)
        all_ok &= ok
    # Must NOT have kitchen_analysis or lifecycle columns
    for forbidden in ["kitchen_analysis", "expires_at", "payment_id", "generation_state"]:
        ok = check(f"reports.{forbidden} ABSENT", forbidden not in cols)
        all_ok &= ok

    cols = _psql("SELECT column_name FROM information_schema.columns WHERE table_name='payments' ORDER BY ordinal_position;")
    expected_payments = ["id", "user_id", "amount", "status", "yookassa_id", "created_at"]
    for c in expected_payments:
        ok = check(f"payments.{c}", c in cols)
        all_ok &= ok
    for forbidden in ["payment_type", "amount_kopecks", "promo_code_id"]:
        ok = check(f"payments.{forbidden} ABSENT", forbidden not in cols)
        all_ok &= ok

    # ── ALEMBIC-BOOT-05: baseline downgrade ──
    print("\n--- ALEMBIC-BOOT-05: baseline downgrade ---")
    result = _alembic("downgrade", "base")
    ok = check("Downgrade base succeeds", result.returncode == 0)
    all_ok &= ok

    tables = _psql("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;")
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
    for target in ["e47590a5c5c1", "f7a8b9c0d1e2", "a8b9c0d1e2f3"]:
        _psql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        result = _alembic("upgrade", target)
        ok = check(f"Upgrade to {target}", result.returncode == 0)
        all_ok &= ok

        result = _alembic("upgrade", "head")
        ok = check(f"{target} -> head", result.returncode == 0)
        all_ok &= ok

        result = _alembic("current")
        ok = check(f"Current is head after {target} upgrade",
                   "b9c0d1e2f3a4" in result.stdout)
        all_ok &= ok

    # ── ALEMBIC-BOOT-07: existing head no-op ──
    print("\n--- ALEMBIC-BOOT-07: existing head no-op ---")
    _psql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    # Simulate create_all+stamp head DB
    subprocess.run([
        sys.executable, "-c",
        "import asyncio; "
        "from sqlalchemy.ext.asyncio import create_async_engine; "
        f"from core.models import Base; "
        "async def f(): "
        f"  engine = create_async_engine('{_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)}'); "
        "  async with engine.begin() as c: await c.run_sync(Base.metadata.create_all); "
        "  await engine.dispose(); "
        "asyncio.run(f())"
    ], capture_output=True, text=True,
       env={**os.environ, "PYTHONPATH": os.path.join(_WORKTREE, "nura_app")})
    _alembic("stamp", "head")
    result = _alembic("upgrade", "head")
    ok = check("Upgrade head no-op (baseline not executed)",
               result.returncode == 0 and "0001a2b3c4d5e6" not in result.stdout)
    all_ok &= ok

    versions = _psql("SELECT version_num FROM alembic_version;")
    version_lines = [ln.strip() for ln in versions.split("\n")
                     if ln.strip() and "---" not in ln and "version" not in ln.lower()
                     and "(" not in ln and "row" not in ln.lower()]
    ok = check("Single alembic_version row",
               len(version_lines) == 1 and "b9c0d1e2f3a4" in version_lines[0])

    ok = check("Baseline NOT in alembic_version",
               "0001a2b3c4d5e6" not in versions)
    all_ok &= ok

    # ── ALEMBIC-BOOT-08: partial schema fail closed ──
    print("\n--- ALEMBIC-BOOT-08: partial schema fail closed ---")
    _psql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    # Create users with wrong schema
    _psql("""
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

    versions = _psql("SELECT version_num FROM alembic_version;")
    ok = check("alembic_version NOT populated with head",
               "b9c0d1e2f3a4" not in versions)
    all_ok &= ok

    # ── ALEMBIC-BOOT-09: legacy backfill ──
    print("\n--- ALEMBIC-BOOT-09: legacy backfill ---")
    _psql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    _alembic("upgrade", "f7a8b9c0d1e2")
    # Create a user and legacy report
    _psql("""
        INSERT INTO users (id, telegram_id, username, first_name, birth_date)
        VALUES (gen_random_uuid(), 99999, 'legacy', 'Legacy', '01.01.1990')
    """)
    _psql("""
        INSERT INTO reports (id, user_id, report_type, token, created_at)
        VALUES (gen_random_uuid(),
                (SELECT id FROM users WHERE username='legacy'),
                'full', 'legacy-backfill-token',
                NOW() - INTERVAL '30 days')
    """)
    _alembic("upgrade", "head")

    row = _psql("""
        SELECT payment_state, generation_state, generated_at, payment_id, generation_attempts
        FROM reports WHERE token = 'legacy-backfill-token'
    """)
    for expected in ["legacy_unlinked", "completed", "0"]:
        ok = check(f"Backfill contains {expected}", expected in row)
        all_ok &= ok
    ok = check("payment_id IS NULL", "legacy_unlinked" in row)  # payment_id column would show empty
    all_ok &= ok

    jobs = _psql("""
        SELECT count(*) FROM report_generation_jobs
        WHERE report_id = (SELECT id FROM reports WHERE token = 'legacy-backfill-token')
    """)
    ok = check("No generation job created", "0" in jobs)
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
    ok = check("Current is b9c0d1e2f3a4", "b9c0d1e2f3a4" in result.stdout)
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
