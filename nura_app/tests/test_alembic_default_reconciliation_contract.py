"""Static contracts for the legacy server-default reconciliation."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from core.models import Payment, Report, User

NURA_APP_ROOT = Path(__file__).resolve().parent.parent
MIGRATION_PATH = (
    NURA_APP_ROOT
    / "alembic"
    / "versions"
    / "d1e2f3a4b5c6_reconcile_legacy_server_defaults.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("default_reconciliation", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_contract() -> None:
    migration = _load_migration()
    assert migration.revision == "d1e2f3a4b5c6"
    assert migration.down_revision == "c0d1e2f3a4b5"
    assert migration._DEFAULTS == (
        ("users", "subscription_status", "free"),
        ("reports", "report_type", "mini"),
        ("payments", "status", "pending"),
    )


def test_default_expression_allowlist_is_exact() -> None:
    migration = _load_migration()
    for expression in ("'free'", "'free'::character varying", "'free'::varchar", "'free'::text"):
        assert migration._is_canonical_default(expression, "free")
    for expression in (
        None,
        "'paid'::character varying",
        "lower('free'::text)",
        "current_user",
        "'free '::text",
    ):
        assert not migration._is_canonical_default(expression, "free")


def test_migration_contains_no_dml_or_destructive_column_operations() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8").lower()
    for forbidden in (
        "insert into",
        "update ",
        "delete from",
        "drop_column",
        "create_table",
        "stamp",
        "if exists",
    ):
        assert forbidden not in source
    assert "set local lock_timeout = '2s'" in source
    assert "set local statement_timeout = '20s'" in source
    assert source.count("op.alter_column") == 1


def test_default_alter_is_explicitly_qualified_to_public_schema() -> None:
    tree = ast.parse(MIGRATION_PATH.read_text(encoding="utf-8"))
    alter_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "op"
        and node.func.attr == "alter_column"
    ]
    assert len(alter_calls) == 1
    schema_keywords = [
        keyword.value
        for keyword in alter_calls[0].keywords
        if keyword.arg == "schema"
    ]
    assert len(schema_keywords) == 1
    assert isinstance(schema_keywords[0], ast.Constant)
    assert schema_keywords[0].value == "public"


def test_model_metadata_has_canonical_server_defaults() -> None:
    expected = (
        (User.__table__.c.subscription_status, "free"),
        (Report.__table__.c.report_type, "mini"),
        (Payment.__table__.c.status, "pending"),
    )
    for column, value in expected:
        assert column.server_default is not None
        assert str(column.server_default.arg) == value
        assert column.nullable is False
