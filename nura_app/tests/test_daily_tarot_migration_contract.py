from pathlib import Path

from core.models import DailyTarotDraw


MIGRATION = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "d7e8f9a0b1c2_add_daily_tarot_draws.py"


def test_daily_tarot_draw_model_has_user_local_date_identity_and_cascade() -> None:
    constraints = {constraint.name for constraint in DailyTarotDraw.__table__.constraints}
    assert "uq_daily_tarot_draws_user_local_date" in constraints
    assert "ck_daily_tarot_draws_state" in constraints
    assert "ck_daily_tarot_draws_arcana_number" in constraints
    foreign_keys = list(DailyTarotDraw.__table__.foreign_keys)
    assert len(foreign_keys) == 1
    assert foreign_keys[0].ondelete == "CASCADE"
    assert "retryable" not in DailyTarotDraw.__table__.columns


def test_daily_tarot_draw_migration_is_linear_and_has_state_guards() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "d7e8f9a0b1c2"' in source
    assert 'down_revision = "d6e7f8a9b0c1"' in source
    assert "uq_daily_tarot_draws_user_local_date" in source
    assert "ck_daily_tarot_draws_state" in source
    assert "ck_daily_tarot_draws_arcana_number" in source
    assert 'ondelete="CASCADE"' in source
