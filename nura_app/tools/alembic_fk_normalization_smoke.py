"""FK normalization PostgreSQL smoke harness.

Connects to an already-running disposable PostgreSQL instance through the
``DATABASE_URL`` environment variable only. Docker lifecycle belongs to the
external runner. Controlled ``create_all`` and ``stamp`` calls are used only
to construct disposable predecessor fixtures; they are not production guidance.

Usage:
    set DATABASE_URL=postgresql://user:pass@localhost:5432/dbname
    python tools/alembic_fk_normalization_smoke.py

Exit code 0 = all scenarios passed (FK-NORM-01 through FK-NORM-10).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import traceback
from pathlib import Path
from urllib.parse import unquote, urlsplit

import psycopg2

REPO_ROOT = Path(__file__).resolve().parents[2]
NURA_APP_ROOT = REPO_ROOT / "nura_app"

PREVIOUS_HEAD = "b9c0d1e2f3a4"
NORMALIZATION_REVISION = "c0d1e2f3a4b5"
EXPECTED_HEAD = "c6d7e8f9a0b1"

_URL = ""
_ALL_OK = True
_SCENARIO_RESULTS: list[tuple[str, bool]] = []

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

# Semantic target names used by the migration under test.
_TARGET_NAMES = {
    "fk_reports_payment_id_payments",
    "fk_payments_promo_code_id_promo_codes",
}
_LEGACY_NAMES = {
    "reports_payment_id_fkey",
    "payments_promo_code_id_fkey",
}


def _mask_url(url: str) -> str:
    return "postgresql://***@localhost:***/***"


def _sanitize(text: str) -> str:
    """Remove any connection credentials from diagnostic text."""
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
    # mask user:pass@host:port
    text = re.sub(r"postgresql(?:\+[^:/]+)?://[^\s@]+@[^/\s]+", "postgresql://***@localhost:***", text)
    text = re.sub(r"postgresql(?:\+[^:/]+)?://[^\s/]+/", "postgresql://***/", text)
    text = re.sub(r"password=[^\s&\"']+", "password=***", text, flags=re.IGNORECASE)
    return text


def _normalize_to_asyncpg_url(url: str) -> str:
    """Convert a disposable PostgreSQL URL to asyncpg SQLAlchemy URL."""
    if not url:
        raise ValueError("DATABASE_URL is empty")
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    raise ValueError(f"Unsupported DATABASE_URL scheme: {url.split('://')[0]}://")


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


def _run_subprocess(
    label: str,
    cmd: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and fail-fast on nonzero exit unless check=False."""
    env = env or _child_env()
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd)
    if check and result.returncode != 0:
        detail = f"{label} failed (exit={result.returncode})"
        sanitized = _sanitize(result.stdout + "\n" + result.stderr)
        raise RuntimeError(f"{detail}\n{_sanitize(sanitized)}")
    return result


def _alembic(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run_subprocess(
        f"alembic {' '.join(args)}",
        [sys.executable, "-c", _ALEMBIC_LAUNCHER, *args],
        env=_child_env(),
        cwd=str(NURA_APP_ROOT),
        check=check,
    )


def _psql(sql: str, check: bool = True) -> str:
    """Execute SQL through psycopg2 and return stable tab-separated rows."""
    try:
        with psycopg2.connect(_URL) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall() if cursor.description else []
    except Exception as exc:
        if check:
            raise RuntimeError(_sanitize(str(exc))) from None
        return ""
    return "".join(
        "\t".join("" if value is None else str(value) for value in row) + "\n"
        for row in rows
    )


def check(label: str, condition: bool, detail: str = "") -> bool:
    global _ALL_OK
    status = "PASS" if condition else "FAIL"
    msg = f"  [{status}] {label}"
    if detail:
        msg += f" -- {_sanitize(detail)}"
    print(msg)
    if not condition:
        _ALL_OK = False
    return condition


def _scenario(name: str, func) -> None:
    global _ALL_OK
    print(f"\n--- {name} ---")
    before = _ALL_OK
    scenario_ok = True
    try:
        func()
    except Exception as exc:
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        print(f"  [FAIL] {name} -- {_sanitize(detail)}")
        _ALL_OK = False
        scenario_ok = False
    else:
        # Mark this scenario failed only if checks inside it flipped _ALL_OK.
        if not _ALL_OK and before:
            scenario_ok = False
    _SCENARIO_RESULTS.append((name, scenario_ok))


def _table_exists(table_name: str) -> bool:
    out = _psql(
        f"SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        f"WHERE table_schema='public' AND table_name='{table_name}')"
    )
    return "t" in out.lower() or "true" in out.lower()


def _legacy_fk_preflight() -> None:
    """Ensure legacy fixture is complete before any scenario continues."""
    required_tables = ["users", "reports", "payments", "promo_codes"]
    for table in required_tables:
        if not _table_exists(table):
            raise RuntimeError(f"Legacy fixture incomplete: table '{table}' missing")
    fks = get_fk_names()
    if not _LEGACY_NAMES.issubset(fks):
        raise RuntimeError(
            f"Legacy fixture incomplete: expected legacy FKs {_LEGACY_NAMES}, got {fks}"
        )


def drop_schema():
    _psql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")


def get_fk_names():
    """Return set of FK constraint names on reports and payments."""
    out = _psql(
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid IN ('reports'::regclass, 'payments'::regclass) AND contype='f'"
    )
    names = set()
    for line in out.split("\n"):
        line = line.strip()
        if line and "---" not in line and "conname" not in line and "(" not in line and "row" not in line.lower():
            names.add(line)
    return names


def get_table_counts():
    """Return bounded row counts for integrity checks."""
    out = _psql(
        "SELECT (SELECT count(*) FROM reports) AS rc, "
        "(SELECT count(*) FROM payments) AS pc, "
        "(SELECT count(*) FROM promo_codes) AS prc, "
        "(SELECT count(*) FROM users) AS uc"
    )
    return out.strip()


def rename_fk(old_name, new_name, table="reports"):
    _psql(f"ALTER TABLE {table} RENAME CONSTRAINT {old_name} TO {new_name}")


def create_legacy_fk_names():
    """Rename target FK names to legacy create_all-style names."""
    fks = get_fk_names()
    if "fk_reports_payment_id_payments" in fks:
        rename_fk("fk_reports_payment_id_payments", "reports_payment_id_fkey")
    if "fk_payments_promo_code_id_promo_codes" in fks:
        rename_fk("fk_payments_promo_code_id_promo_codes", "payments_promo_code_id_fkey", "payments")


def setup_legacy_db():
    """Create a b9 schema and give the two target FKs their legacy names."""
    drop_schema()
    result = _alembic("upgrade", PREVIOUS_HEAD, check=False)
    if result.returncode != 0:
        raise RuntimeError("Could not create the canonical b9 fixture")
    create_legacy_fk_names()

    # Prove the fixture is usable before any scenario continues.
    _legacy_fk_preflight()


def setup_properly_migrated_db():
    """Create properly migrated DB up to b9c0d1e2f3a4."""
    drop_schema()
    r = _alembic("upgrade", PREVIOUS_HEAD, check=False)
    return r.returncode == 0


def _current_version() -> str:
    result = _alembic("current")
    for line in result.stdout.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _assert_current(expected: str, label: str) -> bool:
    current = _current_version()
    return check(label, expected in current, current)


def _assert_fk_integrity() -> bool:
    ref_ok = _psql(
        "SELECT count(*) FROM reports WHERE payment_id NOT IN "
        "(SELECT id FROM payments) AND payment_id IS NOT NULL"
    )
    return check("Reports FK references valid", "0" in ref_ok)


def scenario_01_properly_migrated_noop():
    ok = setup_properly_migrated_db()
    check("Upgrade to b9c0d1e2f3a4", ok)
    fks_before = get_fk_names()
    check(
        "Migration-defined names present",
        _TARGET_NAMES.issubset(fks_before),
        str(fks_before),
    )

    r = _alembic("upgrade", NORMALIZATION_REVISION, check=False)
    check("Upgrade b9 to c0 normalization succeeds", r.returncode == 0)
    # For a no-op, alembic still logs the revision; verify the DB state is unchanged.
    fks_after = get_fk_names()
    check("FK names unchanged", fks_after == fks_before, str(fks_after))
    _assert_current(NORMALIZATION_REVISION, f"Current is {NORMALIZATION_REVISION}")
    r = _alembic("upgrade", "head", check=False)
    check("Upgrade c0 to current head succeeds", r.returncode == 0)
    _assert_current(EXPECTED_HEAD, f"Current is {EXPECTED_HEAD}")


def scenario_02_legacy_normalized():
    setup_legacy_db()
    create_legacy_fk_names()
    fks_before = get_fk_names()
    check(
        "Legacy names present",
        _LEGACY_NAMES.issubset(fks_before),
        str(fks_before),
    )

    r = _alembic("upgrade", NORMALIZATION_REVISION, check=False)
    check("Upgrade to c0 normalization succeeds", r.returncode == 0)

    fks_after = get_fk_names()
    check(
        "Both FKs renamed to target",
        _TARGET_NAMES.issubset(fks_after),
        str(fks_after),
    )
    check(
        "Legacy names absent",
        _LEGACY_NAMES.isdisjoint(fks_after),
    )
    _assert_current(NORMALIZATION_REVISION, f"Current is {NORMALIZATION_REVISION}")
    r = _alembic("upgrade", "head", check=False)
    check("Upgrade c0 to current head succeeds", r.returncode == 0)
    _assert_current(EXPECTED_HEAD, f"Current is {EXPECTED_HEAD}")

    versions = _psql("SELECT version_num FROM alembic_version;")
    check(
        "Single alembic_version row at current head",
        versions.strip() == EXPECTED_HEAD,
        versions,
    )


def scenario_03_mixed_schema():
    setup_legacy_db()
    # Rename reports FK to legacy, ensure payments FK is target
    fks = get_fk_names()
    if "fk_reports_payment_id_payments" in fks:
        rename_fk("fk_reports_payment_id_payments", "reports_payment_id_fkey")
    if "payments_promo_code_id_fkey" in fks:
        rename_fk("payments_promo_code_id_fkey", "fk_payments_promo_code_id_promo_codes", "payments")

    r = _alembic("upgrade", "head", check=False)
    check("Upgrade to head succeeds", r.returncode == 0)
    fks_after = get_fk_names()
    check("Reports FK renamed to target", "fk_reports_payment_id_payments" in fks_after)
    check("Payments FK unchanged", "fk_payments_promo_code_id_promo_codes" in fks_after)


def scenario_04_unexpected_name():
    drop_schema()
    if not setup_properly_migrated_db():
        check("Setup failed", False)
        return
    fks = get_fk_names()
    if "fk_reports_payment_id_payments" in fks:
        rename_fk("fk_reports_payment_id_payments", "bogus_unknown_name_xyz")
    r = _alembic("upgrade", "head", check=False)
    combined = _sanitize(r.stdout + r.stderr)
    check("Upgrade fails", r.returncode != 0)
    check(
        "Error mentions unexpected name",
        "unexpected" in combined.lower() and "bogus" in combined,
    )
    _assert_current(PREVIOUS_HEAD, f"Current remains {PREVIOUS_HEAD}")


def scenario_05_missing_fk():
    drop_schema()
    if not setup_properly_migrated_db():
        check("Setup failed", False)
        return
    _psql("ALTER TABLE reports DROP CONSTRAINT fk_reports_payment_id_payments")
    r = _alembic("upgrade", "head", check=False)
    combined = _sanitize(r.stdout + r.stderr)
    check("Upgrade fails", r.returncode != 0)
    check(
        "Error mentions missing semantic FK for payments.promo_code_id",
        "no semantic fk" in combined.lower() or "not found" in combined.lower(),
        combined,
    )
    _assert_current(PREVIOUS_HEAD, f"Current remains {PREVIOUS_HEAD}")

    # Atomic rollback: prove the second FK was never touched.
    fks = get_fk_names()
    check("Second FK still present", "fk_payments_promo_code_id_promo_codes" in fks, str(fks))


def scenario_06_duplicate_fk():
    drop_schema()
    if not setup_properly_migrated_db():
        check("Setup failed", False)
        return
    _psql(
        "ALTER TABLE reports ADD CONSTRAINT dup_fk_test "
        "FOREIGN KEY (payment_id) REFERENCES payments(id)"
    )
    r = _alembic("upgrade", "head", check=False)
    combined = _sanitize(r.stdout + r.stderr)
    check("Upgrade fails", r.returncode != 0)
    check("Error mentions multiple semantic FKs", "multiple" in combined.lower(), combined)
    _assert_current(PREVIOUS_HEAD, f"Current remains {PREVIOUS_HEAD}")


def scenario_07_both_names_conflict():
    drop_schema()
    if not setup_properly_migrated_db():
        check("Setup failed", False)
        return
    fks = get_fk_names()
    if "fk_reports_payment_id_payments" in fks:
        rename_fk("fk_reports_payment_id_payments", "reports_payment_id_fkey")
    _psql(
        "ALTER TABLE reports ADD CONSTRAINT fk_reports_payment_id_payments "
        "FOREIGN KEY (payment_id) REFERENCES payments(id)"
    )
    r = _alembic("upgrade", "head", check=False)
    combined = _sanitize(r.stdout + r.stderr)
    check("Upgrade fails (both names present)", r.returncode != 0)
    check("Error mentions multiple semantic FKs", "multiple" in combined.lower(), combined)
    _assert_current(PREVIOUS_HEAD, f"Current remains {PREVIOUS_HEAD}")


def scenario_08_downgrade_reupgrade():
    setup_legacy_db()
    create_legacy_fk_names()
    _alembic("upgrade", "head")
    fks = get_fk_names()
    check(
        "Target names present after upgrade",
        _TARGET_NAMES.issubset(fks),
        str(fks),
    )

    r = _alembic("downgrade", NORMALIZATION_REVISION, check=False)
    check("Downgrade d1 to c0 succeeds", r.returncode == 0)

    fks_after_d1_downgrade = get_fk_names()
    check(
        "FK names remain target after d1 downgrade",
        _TARGET_NAMES.issubset(fks_after_d1_downgrade),
        str(fks_after_d1_downgrade),
    )
    _assert_current(NORMALIZATION_REVISION, f"Current is {NORMALIZATION_REVISION}")

    r = _alembic("downgrade", PREVIOUS_HEAD, check=False)
    check("Downgrade c0 to b9 succeeds", r.returncode == 0)

    fks_after_downgrade = get_fk_names()
    check(
        "FK names remain target after downgrade",
        _TARGET_NAMES.issubset(fks_after_downgrade),
        str(fks_after_downgrade),
    )
    _assert_current(PREVIOUS_HEAD, f"Current is {PREVIOUS_HEAD}")

    r = _alembic("upgrade", "head", check=False)
    check("Re-upgrade idempotent", r.returncode == 0)
    _assert_current(EXPECTED_HEAD, f"Current is {EXPECTED_HEAD} after re-upgrade")


def scenario_09_data_integrity():
    setup_legacy_db()
    create_legacy_fk_names()
    # Capture bounded pre-migration state.
    _psql(
        "INSERT INTO users (id, telegram_id, username, first_name, birth_date, "
        "subscription_status, tarot_subscription) "
        "VALUES (gen_random_uuid(), 1, 'fktest', 'FK', '01.01.2000', 'free', false)"
    )
    _psql(
        "INSERT INTO promo_codes (id, code, discount_percent, used_count, reserved_count, is_active) "
        "VALUES (gen_random_uuid(), 'FKPROMO', 10, 0, 0, true)"
    )
    _psql(
        "INSERT INTO payments (id, user_id, amount, status, payment_type, promo_code_id) "
        "VALUES (gen_random_uuid(), (SELECT id FROM users WHERE username='fktest'), 890, "
        "'paid', 'subscription', (SELECT id FROM promo_codes WHERE code='FKPROMO'))"
    )
    _psql(
        "INSERT INTO reports (id, user_id, report_type, token, payment_id) "
        "VALUES (gen_random_uuid(), (SELECT id FROM users WHERE username='fktest'), 'full', "
        "'fktest-token', (SELECT id FROM payments WHERE amount=890 LIMIT 1))"
    )
    counts_with_data = get_table_counts()

    r = _alembic("upgrade", "head", check=False)
    check("Upgrade succeeds", r.returncode == 0)
    counts_after = get_table_counts()
    check(
        "Row counts unchanged by RENAME",
        counts_with_data == counts_after,
        f"before={counts_with_data} after={counts_after}",
    )
    _assert_fk_integrity()
    fks = get_fk_names()
    check(
        "Target names after data-preserving normalization",
        _TARGET_NAMES.issubset(fks),
        str(fks),
    )


def scenario_10_blank_upgrade():
    drop_schema()
    r = _alembic("upgrade", "head", check=False)
    check("Blank DB to head succeeds", r.returncode == 0)
    _assert_current(EXPECTED_HEAD, f"Current is {EXPECTED_HEAD}")
    r = _alembic("heads")
    check("Single head", EXPECTED_HEAD in r.stdout and r.stdout.count("\n") <= 2)
    r = _alembic("branches")
    check("No branches", r.stdout.strip() == "")
    fks = get_fk_names()
    check("Target names on blank DB", _TARGET_NAMES.issubset(fks), str(fks))


def main():
    global _URL
    _URL = os.environ.get("DATABASE_URL", "").strip()
    if not _URL:
        print("FATAL: DATABASE_URL not set")
        sys.exit(1)
    print(f"Database: {_mask_url(_URL)}")

    # Validate that we can build an async URL before any scenario runs.
    try:
        _normalize_to_asyncpg_url(_URL)
    except ValueError as exc:
        print(f"FATAL: {_sanitize(str(exc))}")
        sys.exit(1)

    scenarios = [
        ("FK-NORM-01: properly migrated DB no-op", scenario_01_properly_migrated_noop),
        ("FK-NORM-02: legacy names normalized", scenario_02_legacy_normalized),
        ("FK-NORM-03: mixed schema", scenario_03_mixed_schema),
        ("FK-NORM-04: unexpected name fail-closed", scenario_04_unexpected_name),
        ("FK-NORM-05: missing FK fail-closed", scenario_05_missing_fk),
        ("FK-NORM-06: duplicate semantic FK fail-closed", scenario_06_duplicate_fk),
        ("FK-NORM-07: both-name conflict fail-closed", scenario_07_both_names_conflict),
        ("FK-NORM-08: downgrade/re-upgrade", scenario_08_downgrade_reupgrade),
        ("FK-NORM-09: data and referential integrity", scenario_09_data_integrity),
        ("FK-NORM-10: full blank upgrade", scenario_10_blank_upgrade),
    ]

    for name, func in scenarios:
        _scenario(name, func)

    print(f"\n{'='*60}")
    total = len(_SCENARIO_RESULTS)
    passed = sum(1 for _, ok in _SCENARIO_RESULTS if ok)
    failed = total - passed
    print(f"SCENARIOS: executed={total} passed={passed} failed={failed}")
    for name, ok in _SCENARIO_RESULTS:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
    if _ALL_OK:
        print(f"ALL SCENARIOS PASSED ({passed}/{total})")
    else:
        print("SOME SCENARIOS FAILED")
    print(f"{'='*60}")
    sys.exit(0 if _ALL_OK else 1)


if __name__ == "__main__":
    main()
