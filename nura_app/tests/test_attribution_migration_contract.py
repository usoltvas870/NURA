from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


NURA_APP_ROOT = Path(__file__).resolve().parent.parent
MIGRATION_PATH = (
    NURA_APP_ROOT
    / "alembic"
    / "versions"
    / "a1b2c3d4e5f6_add_attribution_foundation.py"
)


def test_attribution_revision_is_the_single_linear_head():
    config = Config(str(NURA_APP_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(NURA_APP_ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)

    heads = script.get_heads()
    revision = script.get_revision("b1c2d3e4f5a6")

    assert heads == ["b4c5d6e7f8a9"]
    assert revision is not None
    assert revision.down_revision == "d1e2f3a4b5c6"


def test_attribution_migration_has_scoped_schema_contract():
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'revision = "b1c2d3e4f5a6"' in source
    assert 'down_revision = "d1e2f3a4b5c6"' in source
    assert 'op.create_table(\n        "attribution_links"' in source
    assert 'op.create_table(\n        "attribution_touches"' in source
    assert 'sa.UniqueConstraint("user_id", "normalized_code"' in source
    assert 'sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE")' in source
    assert '"ix_attribution_links_code"' in source
    assert '"ix_attribution_touches_user_id"' in source
    assert '"ix_attribution_touches_link_id"' in source
    assert '"ix_attribution_touches_first_seen_at"' in source
    assert source.index('op.drop_table("attribution_touches")') < source.index(
        'op.drop_table("attribution_links")'
    )
    assert "op.execute" not in source
    assert "DROP TABLE users" not in source
