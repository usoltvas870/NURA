"""reconcile legacy server defaults

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-07-21

Production at d5 was found to have three missing defaults that are part of
the canonical root schema.  This forward reconciliation accepts only that
exact legacy drift or an already-canonical default and changes no row data.
"""

import re

from alembic import op
import sqlalchemy as sa

revision = "d1e2f3a4b5c6"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None

_DEFAULTS = (
    ("users", "subscription_status", "free"),
    ("reports", "report_type", "mini"),
    ("payments", "status", "pending"),
)


def _is_canonical_default(expression: str | None, expected: str) -> bool:
    if expression is None:
        return False
    escaped = re.escape(expected).replace(r"\'", "''")
    return bool(
        re.fullmatch(
            rf"'{escaped}'(?:::(?:character varying|varchar|text))?",
            expression.strip(),
            flags=re.IGNORECASE,
        )
    )


def _inspect_column(connection, table_name: str, column_name: str) -> tuple[str, bool, str | None]:
    rows = connection.execute(
        sa.text(
            "SELECT pg_catalog.format_type(a.atttypid, a.atttypmod), "
            "a.attnotnull, pg_catalog.pg_get_expr(d.adbin, d.adrelid) "
            "FROM pg_catalog.pg_namespace n "
            "JOIN pg_catalog.pg_class c ON c.relnamespace = n.oid "
            "JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid "
            "LEFT JOIN pg_catalog.pg_attrdef d "
            "ON d.adrelid = c.oid AND d.adnum = a.attnum "
            "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
            "AND c.relname = :table_name AND a.attname = :column_name "
            "AND a.attnum > 0 AND NOT a.attisdropped"
        ),
        {"table_name": table_name, "column_name": column_name},
    ).fetchall()
    if len(rows) != 1:
        raise RuntimeError(
            "Server-default reconciliation failed: expected exactly one "
            f"public.{table_name}.{column_name} column, found {len(rows)}"
        )
    return rows[0][0], rows[0][1], rows[0][2]


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        raise RuntimeError(
            "Server-default reconciliation requires PostgreSQL "
            f"(detected: {connection.dialect.name})"
        )

    connection.execute(sa.text("SET LOCAL lock_timeout = '2s'"))
    connection.execute(sa.text("SET LOCAL statement_timeout = '20s'"))

    missing_defaults: list[tuple[str, str, str]] = []
    for table_name, column_name, expected in _DEFAULTS:
        data_type, not_null, current_default = _inspect_column(
            connection, table_name, column_name
        )
        label = f"public.{table_name}.{column_name}"
        if data_type != "character varying(20)":
            raise RuntimeError(
                f"Server-default reconciliation failed: {label} has type "
                f"{data_type!r}, expected 'character varying(20)'"
            )
        if not not_null:
            raise RuntimeError(
                f"Server-default reconciliation failed: {label} must be NOT NULL"
            )
        if current_default is None:
            missing_defaults.append((table_name, column_name, expected))
        elif not _is_canonical_default(current_default, expected):
            raise RuntimeError(
                f"Server-default reconciliation failed: {label} has unexpected "
                f"default {current_default!r}"
            )

    for table_name, column_name, expected in missing_defaults:
        op.alter_column(
            table_name,
            column_name,
            schema="public",
            server_default=sa.text(f"'{expected}'"),
        )


def downgrade() -> None:
    # Intentional no-op. The canonical c0 schema already inherits these
    # defaults from the root migration, so removing them would recreate the
    # production-only drift instead of restoring the previous contract.
    pass
