from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


NURA_APP_ROOT = Path(__file__).resolve().parent.parent
MIGRATION_PATH = (
    NURA_APP_ROOT / "alembic" / "versions" / "c1d2e3f4a5b6_add_mini_report_generation_foundation.py"
)


def test_mini_report_generation_migration_has_expected_parent_and_single_head() -> None:
    script = ScriptDirectory.from_config(Config(str(NURA_APP_ROOT / "alembic.ini")))
    heads = script.get_heads()
    assert heads == ["d6e7f8a9b0c1"]
    revision = script.get_revision("c1d2e3f4a5b6")
    assert revision is not None and revision.down_revision == "b1c2d3e4f5a6"


def test_telegram_delivery_migration_has_expected_parent_and_contract() -> None:
    script = ScriptDirectory.from_config(Config(str(NURA_APP_ROOT / "alembic.ini")))
    revision = script.get_revision("d2e3f4a5b6c7")
    assert revision is not None and revision.down_revision == "c1d2e3f4a5b6"
    source = (NURA_APP_ROOT / "alembic" / "versions" / "d2e3f4a5b6c7_add_telegram_mini_report_delivery.py").read_text(encoding="utf-8")
    assert '"telegram_report_deliveries"' in source
    assert "uq_telegram_report_deliveries_generation_user_purpose" in source
    assert source.index("def downgrade") < source.index("op.drop_table")


def test_migration_defines_reversible_owner_and_idempotency_contract() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert '"mini_report_generations"' in source
    assert "ck_mini_report_generations_exactly_one_owner" in source
    assert source.count('ondelete="CASCADE"') == 2
    assert 'ondelete="SET NULL"' in source
    assert "uq_mini_report_generations_user_fingerprint_version" in source
    assert "uq_mini_report_generations_guest_fingerprint_version" in source
    assert "postgresql_where" in source
    assert source.index("def downgrade") < source.index("op.drop_table")
