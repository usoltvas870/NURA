from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from core.models import ChatMessageUsage, MiniReportGeneration, Report


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "d8e9f0a1b2c3_add_prompt_generation_metadata.py"


def test_prompt_metadata_migration_is_additive_nullable_and_reversible() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["d8e9f0a1b2c3"]
    revision = script.get_revision("d8e9f0a1b2c3")
    assert revision is not None and revision.down_revision == "c6d7e8f9a0b1"
    source = MIGRATION.read_text(encoding="utf-8")
    assert source.count('"generation_metadata"') == 6
    assert source.count('op.drop_column(') == 3
    assert "UPDATE" not in source and "legacy-unknown" not in source


def test_models_expose_nullable_json_metadata_without_legacy_attribution() -> None:
    for model in (Report, MiniReportGeneration, ChatMessageUsage):
        column = model.__table__.c.generation_metadata
        assert column.nullable is True
        assert column.server_default is None
