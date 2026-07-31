"""Validate server-default reconciliation on disposable PostgreSQL.

The harness connects only through ``DATABASE_URL``. Docker lifecycle belongs
to ``run_alembic_postgres_smoke.py``; no production data or identifiers are
used here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import psycopg2

REPO_ROOT = Path(__file__).resolve().parents[2]
NURA_APP_ROOT = REPO_ROOT / "nura_app"
PRODUCTION_REVISION = "d5e6f7a8b9c0"
FK_NORMALIZATION_HEAD = "c0d1e2f3a4b5"
EXPECTED_HEAD = "d1e2f3a4b5c6"
GRAPH_HEAD = "d8e9f0a1b2c3"
SHADOW_SCHEMA = "p43d_shadow"
PRODUCTION_SCHEMA_FINGERPRINT = (
    "6b4d42974f1b0d4538e22d90f310c42fb2ffaa417ccbe7dd2e1d16802c41ab87"
)

# SHA-256 of compact JSON arrays built from the sanitized P4.3C CSV rows.
_PRODUCTION_COMPONENT_HASHES = {
    "alembic": "e3711ce92a229f8ff25c50e143f47cce704212fac37ee32880c04fe214851d2b",
    "tables": "51d64a24701f337b776314344ca747ca26734fda5e9b9ebd405556ab267005fe",
    # Column semantics exclude ordinal_position. A fresh migration chain keeps
    # a dropped-column attnum tombstone that the legacy production table lacks.
    "columns": "d2bcc927d898664fd36bedc68fc7e16093e9995d0ba1ecfff45b80a249ac00e5",
    "constraints": "cc909e2efb5bafb9cba851a046855577ed84e41d2a4b7b56cd4b2aeb63c3c409",
    "indexes": "999a54706a29a95adf11f329cad1baa413a701a0285bb21cbfc5e25df86f2aaf",
}
_TARGET_DEFAULTS = {
    ("users", "subscription_status"): "free",
    ("reports", "report_type"): "mini",
    ("payments", "status"): "pending",
}
_URL = ""
_ALL_OK = True
_NEGATIVE_RESULTS: list[dict[str, object]] = []
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


def _validate_disposable_database_url(url: str) -> None:
    """Reject every target except the runner-created loopback smoke database."""
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        database_name = unquote(parsed.path.lstrip("/"))
    except ValueError as exc:
        raise ValueError("DATABASE_URL must be a disposable loopback PostgreSQL URL") from exc
    if parsed.scheme not in {"postgresql", "postgresql+psycopg2"}:
        raise ValueError("DATABASE_URL must use PostgreSQL")
    if hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Reconciliation smoke requires a loopback DATABASE_URL")
    if not database_name.startswith("smoke_"):
        raise ValueError(
            "Reconciliation smoke requires a runner-created smoke_ database"
        )


def _sanitize(text: str) -> str:
    if _URL:
        text = text.replace(_URL, "postgresql://***/***")
        try:
            parsed = urlsplit(_URL)
            for value in (parsed.username, parsed.path.lstrip("/")):
                if value:
                    text = text.replace(unquote(value), "***")
        except ValueError:
            pass
    text = re.sub(
        r"postgresql(?:\+[^:/]+)?://[^\s@]+@[^/\s]+/[^\s]+",
        "postgresql://***/***",
        text,
    )
    return re.sub(r"password=[^\s&\"']+", "password=***", text, flags=re.I)


def _alembic(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _ALEMBIC_LAUNCHER, *args],
        cwd=NURA_APP_ROOT,
        env=env or _child_env(),
        capture_output=True,
        text=True,
    )


def _query(sql: str, params: tuple[object, ...] = ()) -> tuple[list[str], list[tuple]]:
    try:
        with psycopg2.connect(_URL) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                headers = [column.name for column in cursor.description] if cursor.description else []
                rows = cursor.fetchall() if cursor.description else []
                return headers, rows
    except Exception as exc:
        raise RuntimeError(_sanitize(str(exc))) from None


def _execute(sql: str) -> None:
    _query(sql)


def _check(label: str, condition: bool, detail: str = "") -> bool:
    global _ALL_OK
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" -- {detail}" if detail else ""))
    _ALL_OK &= condition
    return condition


def _reset_schema() -> None:
    _execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")


def _current_revision() -> str:
    _, rows = _query("SELECT version_num FROM alembic_version ORDER BY version_num")
    return rows[0][0] if len(rows) == 1 else ""


def _default_expressions() -> dict[str, str | None]:
    _, rows = _query(
        "SELECT c.relname, a.attname, pg_get_expr(d.adbin, d.adrelid) "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid=c.oid "
        "LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum "
        "WHERE n.nspname='public' AND (c.relname, a.attname) IN "
        "(('users','subscription_status'),('reports','report_type'),('payments','status')) "
        "AND a.attnum > 0 AND NOT a.attisdropped ORDER BY c.relname, a.attname"
    )
    return {f"{table}.{column}": expression for table, column, expression in rows}


def _defaults_are_canonical(defaults: dict[str, str | None]) -> bool:
    if len(defaults) != 3:
        return False
    for (table, column), value in _TARGET_DEFAULTS.items():
        expression = defaults.get(f"{table}.{column}")
        if expression not in {
            f"'{value}'::character varying",
            f"'{value}'::varchar",
            f"'{value}'::text",
            f"'{value}'",
        }:
            return False
    return True


def _shadow_defaults() -> dict[str, str | None]:
    _, rows = _query(
        "SELECT c.relname, a.attname, pg_get_expr(d.adbin, d.adrelid) "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid=c.oid "
        "LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum "
        "WHERE n.nspname=%s AND (c.relname, a.attname) IN "
        "(('users','subscription_status'),('reports','report_type'),('payments','status')) "
        "AND a.attnum > 0 AND NOT a.attisdropped ORDER BY c.relname, a.attname",
        (SHADOW_SCHEMA,),
    )
    return {f"{table}.{column}": expression for table, column, expression in rows}


def _shadow_column_contract() -> list[tuple[str, str, str, str]]:
    _, rows = _query(
        "SELECT table_name, column_name, data_type, is_nullable "
        "FROM information_schema.columns WHERE table_schema=%s "
        "AND (table_name, column_name) IN "
        "(('users','subscription_status'),('reports','report_type'),('payments','status')) "
        "ORDER BY table_name, column_name",
        (SHADOW_SCHEMA,),
    )
    return rows


def _shadow_objects() -> list[tuple[str, str]]:
    _, rows = _query(
        "SELECT relkind, relname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=%s ORDER BY relkind, relname",
        (SHADOW_SCHEMA,),
    )
    return rows


def _shadow_search_path_env() -> dict[str, str]:
    env = _child_env()
    env["PGOPTIONS"] = f"-c search_path={SHADOW_SCHEMA},public"
    return env


def _csv_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "t" if value else "f"
    return str(value)


def _catalog_rows(sql: str) -> list[dict[str, str]]:
    headers, rows = _query(sql)
    return [
        {header: _csv_value(value) for header, value in zip(headers, row, strict=True)}
        for row in rows
    ]


def _component_hash(rows: list[dict[str, str]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _production_catalog_hashes() -> dict[str, str]:
    queries = {
        "alembic": (
            "SELECT count(*) AS revision_count, min(version_num) AS revision_min, "
            "max(version_num) AS revision_max FROM public.alembic_version"
        ),
        "tables": (
            "SELECT tablename AS table_name, CASE WHEN tableowner=current_user "
            "THEN '[current_user]' ELSE '[other]' END AS owner_class "
            "FROM pg_catalog.pg_tables WHERE schemaname='public' ORDER BY tablename"
        ),
        "columns": (
            "SELECT table_name, ordinal_position, column_name, data_type, udt_name, "
            "is_nullable, column_default, is_identity, identity_generation, "
            "is_generated, generation_expression FROM information_schema.columns "
            "WHERE table_schema='public' ORDER BY table_name, ordinal_position"
        ),
        "constraints": (
            "SELECT c.conrelid::regclass::text AS table_name, c.conname, c.contype, "
            "c.condeferrable, c.condeferred, c.convalidated, "
            "CASE c.confupdtype WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT' "
            "WHEN 'c' THEN 'CASCADE' WHEN 'n' THEN 'SET NULL' WHEN 'd' THEN 'SET DEFAULT' END AS fk_on_update, "
            "CASE c.confdeltype WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT' "
            "WHEN 'c' THEN 'CASCADE' WHEN 'n' THEN 'SET NULL' WHEN 'd' THEN 'SET DEFAULT' END AS fk_on_delete, "
            "pg_get_constraintdef(c.oid) AS definition FROM pg_catalog.pg_constraint c "
            "WHERE c.connamespace='public'::regnamespace ORDER BY 1, 2"
        ),
        "indexes": (
            "SELECT schemaname, tablename, indexname, indexdef FROM pg_catalog.pg_indexes "
            "WHERE schemaname='public' ORDER BY tablename, indexname"
        ),
    }
    hashes: dict[str, str] = {}
    for name, sql in queries.items():
        rows = _catalog_rows(sql)
        if name == "columns":
            rows = [
                {key: value for key, value in row.items() if key != "ordinal_position"}
                for row in rows
            ]
        hashes[name] = _component_hash(rows)
    return hashes


def _insert_synthetic_rows() -> None:
    _execute(
        "INSERT INTO users (id, telegram_id, username, subscription_status) VALUES "
        "('00000000-0000-0000-0000-00000000d301', 930001, 'p43d_synthetic_1', 'free'), "
        "('00000000-0000-0000-0000-00000000d302', 930002, 'p43d_synthetic_2', 'free')"
    )
    _execute(
        "INSERT INTO reports (id, user_id, report_type, token, created_at) VALUES "
        "('00000000-0000-0000-0000-00000000d303', "
        "'00000000-0000-0000-0000-00000000d301', 'full', "
        "'p43d-synthetic-report', NOW() - INTERVAL '7 days')"
    )


def _scenario_production_d5() -> tuple[dict[str, object], dict[str, object]]:
    print("\n--- RECONCILE-01: exact production-like d5 drift ---")
    _reset_schema()
    result = _alembic("upgrade", PRODUCTION_REVISION)
    _check("Blank database upgrades to production d5", result.returncode == 0)
    _check("Single revision is d5", _current_revision() == PRODUCTION_REVISION)
    _execute("ALTER TABLE users ALTER COLUMN subscription_status DROP DEFAULT")
    _execute("ALTER TABLE reports ALTER COLUMN report_type DROP DEFAULT")
    _execute("ALTER TABLE payments ALTER COLUMN status DROP DEFAULT")
    hashes = _production_catalog_hashes()
    for component, expected in _PRODUCTION_COMPONENT_HASHES.items():
        _check(
            (
                "P4.3C sanitized semantic columns hash exact"
                if component == "columns"
                else f"P4.3C {component} catalog hash exact"
            ),
            hashes[component] == expected,
            hashes[component],
        )
    before = {
        "authoritative_fingerprint": PRODUCTION_SCHEMA_FINGERPRINT,
        "component_hashes": hashes,
        "component_hash_scope": (
            "alembic/tables/constraints/indexes exact; columns exact after "
            "excluding ordinal_position tombstone differences"
        ),
        "defaults": _default_expressions(),
        "revision": _current_revision(),
    }
    _insert_synthetic_rows()
    result = _alembic("upgrade", "head")
    _check("Production-like d5 upgrades to new head", result.returncode == 0)
    _check("Single revision is graph head", _current_revision() == GRAPH_HEAD)
    defaults = _default_expressions()
    _check("Three canonical defaults restored", _defaults_are_canonical(defaults), str(defaults))
    _, counts = _query(
        "SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM reports), "
        "(SELECT count(*) FROM payments), (SELECT count(*) FROM promo_codes)"
    )
    _check("Synthetic row counts preserved", counts == [(2, 1, 0, 0)], str(counts))
    _, lifecycle = _query(
        "SELECT payment_state, generation_state, generated_at IS NOT NULL, payment_id, "
        "generation_attempts FROM reports WHERE token='p43d-synthetic-report'"
    )
    _check(
        "Report lifecycle backfill exact",
        lifecycle == [("legacy_unlinked", "completed", True, None, 0)],
        str(lifecycle),
    )
    _, integrity = _query(
        "SELECT "
        "(SELECT count(*) FROM reports r LEFT JOIN users u ON u.id=r.user_id WHERE u.id IS NULL), "
        "(SELECT count(*) FROM payments p LEFT JOIN users u ON u.id=p.user_id WHERE u.id IS NULL), "
        "(SELECT count(*) FROM (SELECT yookassa_id FROM payments WHERE yookassa_id IS NOT NULL "
        "GROUP BY yookassa_id HAVING count(*) > 1) d), "
        "(SELECT count(*) FROM promo_codes WHERE used_count < 0 OR reserved_count < 0)"
    )
    _check("Orphan/duplicate/negative checks are zero", integrity == [(0, 0, 0, 0)], str(integrity))
    _, target_tables = _query(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN "
        "('promo_reservations','report_generation_jobs') ORDER BY tablename"
    )
    _check("Target tables exist", len(target_tables) == 2, str(target_tables))
    after = {
        "defaults": defaults,
        "integrity_counts": integrity[0],
        "revision": _current_revision(),
        "row_counts": counts[0],
        "target_tables": [row[0] for row in target_tables],
    }
    return before, after


def _scenario_canonical_and_downgrade() -> None:
    print("\n--- RECONCILE-02: canonical c0, d1, attribution round-trip ---")
    _reset_schema()
    _check("Canonical c0 setup succeeds", _alembic("upgrade", FK_NORMALIZATION_HEAD).returncode == 0)
    before = _default_expressions()
    _check("Canonical c0 defaults present", _defaults_are_canonical(before), str(before))
    _check("c0 to d1 succeeds", _alembic("upgrade", EXPECTED_HEAD).returncode == 0)
    _check("Canonical defaults unchanged", _default_expressions() == before)
    _, d1_rows = _query(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    )
    d1_tables = {row[0] for row in d1_rows}
    foundation_tables = {
        "attribution_links",
        "attribution_touches",
        "mini_report_generations",
        "telegram_report_deliveries",
        "chat_message_usages",
        "daily_tarot_draws",
        "orders",
        "payment_attempts",
        "payment_events",
        "full_report_telegram_deliveries",
        "broadcast_campaigns",
        "broadcast_deliveries",
        "broadcast_cta_clicks",
        "broadcast_cta_click_events",
        "telegram_suppressions",
        "broadcast_audit_entries",
    }
    _check("Post-d1 foundation tables absent at d1", foundation_tables.isdisjoint(d1_tables))

    _check("d1 to graph head succeeds", _alembic("upgrade", GRAPH_HEAD).returncode == 0)
    _check("Revision is graph head", _current_revision() == GRAPH_HEAD)
    _, graph_head_rows = _query(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    )
    graph_head_tables = {row[0] for row in graph_head_rows}
    _check(
        "Graph head adds only post-d1 foundation tables",
        graph_head_tables == d1_tables | foundation_tables,
        str(graph_head_tables - d1_tables),
    )

    _check("Downgrade graph head to d1 succeeds", _alembic("downgrade", EXPECTED_HEAD).returncode == 0)
    _check("Revision is d1 after downgrade", _current_revision() == EXPECTED_HEAD)
    _, downgraded_rows = _query(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    )
    downgraded_tables = {row[0] for row in downgraded_rows}
    _check("Downgrade removes only post-d1 foundation tables", downgraded_tables == d1_tables)
    _check("Foundation downgrade preserves defaults", _default_expressions() == before)

    _check("Re-upgrade d1 to graph head succeeds", _alembic("upgrade", GRAPH_HEAD).returncode == 0)
    _check("Revision returns to graph head", _current_revision() == GRAPH_HEAD)
    _, reupgraded_rows = _query(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    )
    reupgraded_tables = {row[0] for row in reupgraded_rows}
    _check(
        "Re-upgrade restores only post-d1 foundation tables",
        reupgraded_tables == d1_tables | foundation_tables,
    )


def _scenario_shadow_search_path() -> dict[str, object]:
    print("\n--- RECONCILE-SHADOW-SEARCH-PATH: schema-qualified ALTER ---")
    _reset_schema()
    _check(
        "Shadow scenario canonical c0 setup succeeds",
        _alembic("upgrade", FK_NORMALIZATION_HEAD).returncode == 0,
    )
    _execute("ALTER TABLE public.users ALTER COLUMN subscription_status DROP DEFAULT")
    _execute("ALTER TABLE public.reports ALTER COLUMN report_type DROP DEFAULT")
    _execute("ALTER TABLE public.payments ALTER COLUMN status DROP DEFAULT")
    _execute(f"CREATE SCHEMA {SHADOW_SCHEMA}")
    for table_name, column_name, sentinel in (
        ("users", "subscription_status", "shadow_free"),
        ("reports", "report_type", "shadow_mini"),
        ("payments", "status", "shadow_pending"),
    ):
        _execute(
            f"CREATE TABLE {SHADOW_SCHEMA}.{table_name} "
            f"({column_name} VARCHAR(20) NOT NULL DEFAULT '{sentinel}')"
        )

    public_before = _default_expressions()
    shadow_before = _shadow_defaults()
    shadow_contract_before = _shadow_column_contract()
    shadow_objects_before = _shadow_objects()
    result = _alembic("upgrade", EXPECTED_HEAD, env=_shadow_search_path_env())
    public_after = _default_expressions()
    shadow_after = _shadow_defaults()
    shadow_contract_after = _shadow_column_contract()
    shadow_objects_after = _shadow_objects()

    expected_shadow = {
        "users.subscription_status": "'shadow_free'::character varying",
        "reports.report_type": "'shadow_mini'::character varying",
        "payments.status": "'shadow_pending'::character varying",
    }
    expected_contract = [
        ("payments", "status", "character varying", "NO"),
        ("reports", "report_type", "character varying", "NO"),
        ("users", "subscription_status", "character varying", "NO"),
    ]
    expected_objects = [("r", "payments"), ("r", "reports"), ("r", "users")]
    _check("Shadow search_path c0 to d1 succeeds", result.returncode == 0)
    _check("Shadow search_path records d1", _current_revision() == EXPECTED_HEAD)
    _check("Shadow search_path restores public defaults", _defaults_are_canonical(public_after), str(public_after))
    _check("Shadow sentinel defaults unchanged", shadow_before == expected_shadow and shadow_after == expected_shadow, str(shadow_after))
    _check("Shadow column contracts unchanged", shadow_contract_before == expected_contract and shadow_contract_after == expected_contract, str(shadow_contract_after))
    _check("No additional shadow objects created", shadow_objects_before == expected_objects and shadow_objects_after == expected_objects, str(shadow_objects_after))
    return {
        "scenario": "RECONCILE-SHADOW-SEARCH-PATH",
        "search_path": f"{SHADOW_SCHEMA},public",
        "revision": _current_revision(),
        "public_defaults_before": public_before,
        "public_defaults_after": public_after,
        "shadow_defaults_before": shadow_before,
        "shadow_defaults_after": shadow_after,
        "shadow_column_contract_before": shadow_contract_before,
        "shadow_column_contract_after": shadow_contract_after,
        "shadow_objects_before": shadow_objects_before,
        "shadow_objects_after": shadow_objects_after,
    }


def _negative(name: str, mutation_sql: str) -> None:
    print(f"\n--- {name} ---")
    _reset_schema()
    setup = _alembic("upgrade", FK_NORMALIZATION_HEAD)
    _check(f"{name}: canonical c0 setup", setup.returncode == 0)
    _execute(mutation_sql)
    before = _default_expressions()
    result = _alembic("upgrade", EXPECTED_HEAD)
    after = _default_expressions()
    outcome = {
        "name": name,
        "failed": result.returncode != 0,
        "revision": _current_revision(),
        "defaults_unchanged": before == after,
    }
    _NEGATIVE_RESULTS.append(outcome)
    _check(f"{name}: upgrade fails closed", outcome["failed"] is True)
    _check(f"{name}: revision remains c0", outcome["revision"] == FK_NORMALIZATION_HEAD)
    _check(f"{name}: no partial default changes", outcome["defaults_unchanged"] is True)


def _write_evidence(
    before: dict[str, object], after: dict[str, object], shadow: dict[str, object]
) -> None:
    raw_dir = os.environ.get("RECONCILIATION_EVIDENCE_DIR", "").strip()
    if not raw_dir:
        return
    evidence_dir = Path(raw_dir).resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (
        ("schema-before.json", before),
        ("schema-after.json", after),
        ("negative-scenarios.json", _NEGATIVE_RESULTS),
        ("shadow-schema-scenario.json", shadow),
    ):
        (evidence_dir / name).write_text(
            json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )


def main() -> int:
    global _URL
    _URL = os.environ.get("DATABASE_URL", "").strip()
    if not _URL:
        print("FATAL: DATABASE_URL not set")
        return 1
    try:
        _validate_disposable_database_url(_URL)
    except ValueError as exc:
        print(f"FATAL: {_sanitize(str(exc))}", file=sys.stderr)
        return 1
    print("Database: postgresql://***@localhost:***/***")

    try:
        before, after = _scenario_production_d5()
        _scenario_canonical_and_downgrade()
        shadow = _scenario_shadow_search_path()
        negative_scenarios = (
            ("RECONCILE-NEG-01 unexpected users default", "ALTER TABLE users ALTER COLUMN subscription_status SET DEFAULT 'paid'"),
            ("RECONCILE-NEG-02 unexpected reports default", "ALTER TABLE reports ALTER COLUMN report_type SET DEFAULT 'full'"),
            (
                "RECONCILE-NEG-03 expression default and atomic rollback",
                "ALTER TABLE users ALTER COLUMN subscription_status DROP DEFAULT; "
                "ALTER TABLE reports ALTER COLUMN report_type DROP DEFAULT; "
                "ALTER TABLE payments ALTER COLUMN status SET DEFAULT lower('pending'::text)",
            ),
            ("RECONCILE-NEG-04 missing column", "ALTER TABLE payments DROP COLUMN status"),
            ("RECONCILE-NEG-05 unexpected type", "ALTER TABLE users ALTER COLUMN subscription_status TYPE VARCHAR(21)"),
            ("RECONCILE-NEG-06 nullable column", "ALTER TABLE reports ALTER COLUMN report_type DROP NOT NULL"),
        )
        for name, mutation in negative_scenarios:
            _negative(name, mutation)
        _write_evidence(before, after, shadow)
    except Exception as exc:
        print(f"FATAL: {_sanitize(str(exc))}", file=sys.stderr)
        return 1

    print("\nALL RECONCILIATION SCENARIOS PASSED" if _ALL_OK else "\nRECONCILIATION SCENARIOS FAILED")
    return 0 if _ALL_OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
