from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "c6d7e8f9a0b1_add_broadcast_campaign_contour.py"


def test_broadcast_migration_is_single_additive_head() -> None:
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == ["c6d7e8f9a0b1"]
    revision = script.get_revision("c6d7e8f9a0b1")
    assert revision is not None and revision.down_revision == "c5d6e7f8a9b0"


def test_broadcast_migration_contains_required_privacy_and_integrity_contracts() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for table in (
        "broadcast_campaigns",
        "broadcast_deliveries",
        "broadcast_cta_clicks",
        "broadcast_cta_click_events",
        "telegram_suppressions",
        "broadcast_audit_entries",
    ):
        assert f'"{table}"' in source
    assert "uq_broadcast_deliveries_campaign_user" in source
    assert "editorial_messages_enabled" in source
    assert "notification_prefs ->> 'news'" in source
    assert '"attribution_expires_at"' in source
    assert "uq_broadcast_cta_clicks_delivery_key" in source
    assert "ondelete=\"CASCADE\"" in source
    assert "def downgrade()" in source
    for forbidden in ("telegram_bot_token", "admin_token", "provider_exception"):
        assert forbidden not in source
