"""normalize report and payment FK constraint names

Semantically identifies and renames two foreign key constraints to their
migration-defined canonical names.  Only safe RENAME CONSTRAINT is used;
no DROP, ADD, or data modification is performed.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa

revision = "c0d1e2f3a4b5"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None

# Semantic FK definitions — matched via pg_constraint, not by name.
_FK_DEFINITIONS = (
    {
        "label": "reports.payment_id -> payments.id",
        "source_table": "reports",
        "source_columns": ("payment_id",),
        "referenced_table": "payments",
        "referenced_columns": ("id",),
        "legacy_name": "reports_payment_id_fkey",
        "target_name": "fk_reports_payment_id_payments",
    },
    {
        "label": "payments.promo_code_id -> promo_codes.id",
        "source_table": "payments",
        "source_columns": ("promo_code_id",),
        "referenced_table": "promo_codes",
        "referenced_columns": ("id",),
        "legacy_name": "payments_promo_code_id_fkey",
        "target_name": "fk_payments_promo_code_id_promo_codes",
    },
)


def _check_postgresql(connection) -> None:
    dialect_name = connection.dialect.name
    if dialect_name != "postgresql":
        raise RuntimeError(
            f"FK normalization requires PostgreSQL (detected: {dialect_name})"
        )


def _find_semantic_fk(connection, src_table, src_cols, ref_table, ref_cols):
    """Return (existing_name,) or empty tuple — exactly one FK by semantics."""
    rows = connection.execute(
        sa.text(
            "SELECT c.conname FROM pg_constraint c "
            "WHERE c.contype = 'f' "
            "AND c.conrelid = CAST(:src_table AS regclass) "
            "AND c.confrelid = CAST(:ref_table AS regclass) "
            "AND c.conkey = ("
            "  SELECT array_agg(a.attnum ORDER BY a.attnum) "
            "  FROM pg_attribute a "
            "  WHERE a.attrelid = CAST(:src_table AS regclass) "
            "  AND a.attname = ANY(:src_cols)"
            ") "
            "AND c.confkey = ("
            "  SELECT array_agg(a.attnum ORDER BY a.attnum) "
            "  FROM pg_attribute a "
            "  WHERE a.attrelid = CAST(:ref_table AS regclass) "
            "  AND a.attname = ANY(:ref_cols)"
            ")"
        ),
        {
            "src_table": src_table,
            "ref_table": ref_table,
            "src_cols": list(src_cols),
            "ref_cols": list(ref_cols),
        },
    ).fetchall()
    return tuple(r[0] for r in rows)


def _normalize_one_fk(connection, fk_def) -> None:
    label = fk_def["label"]
    legacy = fk_def["legacy_name"]
    target = fk_def["target_name"]
    src_table = fk_def["source_table"]

    existing = _find_semantic_fk(
        connection,
        fk_def["source_table"],
        fk_def["source_columns"],
        fk_def["referenced_table"],
        fk_def["referenced_columns"],
    )

    if len(existing) == 0:
        raise RuntimeError(
            f"FK normalization failed: no semantic FK found for {label}"
        )
    if len(existing) > 1:
        raise RuntimeError(
            f"FK normalization failed: multiple semantic FKs for {label}: {existing}"
        )

    current_name = existing[0]

    if current_name == target:
        # State 1: already target — no-op
        return

    if current_name == legacy:
        # State 2: legacy — rename to target
        connection.execute(
            sa.text(
                f'ALTER TABLE {src_table} RENAME CONSTRAINT {current_name} TO {target}'
            )
        )
        return

    # State 3: unexpected name
    raise RuntimeError(
        f"FK normalization failed: {label} has unexpected name "
        f"'{current_name}' (expected '{legacy}' or '{target}')"
    )


def upgrade() -> None:
    connection = op.get_bind()
    _check_postgresql(connection)

    for fk_def in _FK_DEFINITIONS:
        _normalize_one_fk(connection, fk_def)


def downgrade() -> None:
    # Forward-only no-op: constraint names after upgrade depend on the
    # original state (already-target vs renamed-from-legacy), which
    # cannot be recovered without storing pre-rename metadata.
    # Normalized target names are preserved.
    pass
