"""Static Alembic bootstrap contract tests.

Does NOT require PostgreSQL.  Validates the migration graph and baseline
migration properties using the Alembic ScriptDirectory API.
"""

import os
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

ALEMBIC_DIR = Path(__file__).resolve().parent.parent / "alembic"
INI_PATH = Path(__file__).resolve().parent.parent / "alembic.ini"


@pytest.fixture(scope="module")
def script():
    cfg = Config(str(INI_PATH))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    return ScriptDirectory.from_config(cfg)


class TestGraphContract:
    def test_single_root(self, script):
        # Roots have down_revision is None
        roots = [r for r in script.walk_revisions() if r.is_base]
        assert len(roots) == 1, f"Expected 1 root, got {len(roots)}: {[r.revision for r in roots]}"
        root = roots[0]
        assert root.revision == "0001a2b3c4d5e6", f"Root is {root.revision}"

    def test_single_head(self, script):
        heads = script.get_revisions("heads")
        assert len(heads) == 1, f"Expected 1 head, got {len(heads)}: {[h.revision for h in heads]}"
        head = heads[0]
        assert head.revision == "c5d6e7f8a9b0", f"Head is {head.revision}"

    def test_e475_parent_is_baseline(self, script):
        rev = script.get_revision("e47590a5c5c1")
        assert rev.down_revision is not None, "e475 down_revision should not be None"
        assert rev.down_revision == "0001a2b3c4d5e6", (
            f"e475 parent is {rev.down_revision}"
        )

    def test_no_branch_labels(self, script):
        # Verify no revision has branch_labels set
        for rev in script.walk_revisions():
            assert not rev.branch_labels, (
                f"Revision {rev.revision} has branch_labels={rev.branch_labels}"
            )

    def test_linear_history(self, script):
        expected_chain = [
            "0001a2b3c4d5e6",
            "e47590a5c5c1",
            "add_tarot_and_payment_type",
            "b3c1d2e4f5a6",
            "5a8cac04bf5e",
            "a1b2c3d4e5f6",
            "b2c3d4e5f6a7",
            "c3d4e5f6a7b8",
            "d4e5f6a7b8c9",
            "e5f6a7b8c9d0",
            "f1a2b3c4d5e6",
            "a2b3c4d5e6f7",
            "b3c4d5e6f7a8",
            "c4d5e6f7a8b9",
            "d5e6f7a8b9c0",
            "e6f7a8b9c0d1",
            "f7a8b9c0d1e2",
            "a8b9c0d1e2f3",
            "b9c0d1e2f3a4",
            "c0d1e2f3a4b5",
            "d1e2f3a4b5c6",
            "b1c2d3e4f5a6",
            "c1d2e3f4a5b6",
            "d2e3f4a5b6c7",
            "d6e7f8a9b0c1",
            "d7e8f9a0b1c2",
            "e8f9a0b1c2d3",
            "f9a0b1c2d3e4",
            "b4c5d6e7f8a9",
            "c5d6e7f8a9b0",
        ]
        # iterate_revisions goes head→base, reverse for base→head
        revisions = list(script.iterate_revisions("head", "base"))
        ids = [r.revision for r in revisions]
        ids.reverse()
        assert ids == expected_chain, (
            f"Chain mismatch. Expected {len(expected_chain)}, got {len(ids)}"
        )


class TestBaselineFile:
    def test_file_exists(self):
        path = ALEMBIC_DIR / "versions" / "0001a2b3c4d5e6_create_initial_tables.py"
        assert path.is_file(), f"Baseline file not found at {path}"

    def test_no_if_not_exists(self):
        path = ALEMBIC_DIR / "versions" / "0001a2b3c4d5e6_create_initial_tables.py"
        content = path.read_text(encoding="utf-8")
        assert "IF NOT EXISTS" not in content, (
            "Baseline must NOT use IF NOT EXISTS"
        )

    def test_no_create_all(self):
        path = ALEMBIC_DIR / "versions" / "0001a2b3c4d5e6_create_initial_tables.py"
        content = path.read_text(encoding="utf-8")
        assert "create_all" not in content, (
            "Baseline must NOT call Base.metadata.create_all()"
        )

    def test_no_stamp(self):
        path = ALEMBIC_DIR / "versions" / "0001a2b3c4d5e6_create_initial_tables.py"
        content = path.read_text(encoding="utf-8")
        assert "stamp" not in content.lower(), (
            "Baseline must NOT contain stamp logic"
        )

    def test_creates_three_tables(self):
        path = ALEMBIC_DIR / "versions" / "0001a2b3c4d5e6_create_initial_tables.py"
        content = path.read_text(encoding="utf-8")
        # op.create_table is a function call — check for the pattern
        assert content.count("create_table") == 3, (
            f"Baseline must create exactly 3 tables, "
            f"found {content.count('create_table')} create_table calls"
        )
        assert '"users"' in content or "'users'" in content
        assert '"reports"' in content or "'reports'" in content
        assert '"payments"' in content or "'payments'" in content

    def test_downgrade_order(self):
        path = ALEMBIC_DIR / "versions" / "0001a2b3c4d5e6_create_initial_tables.py"
        content = path.read_text(encoding="utf-8")
        # FK-safe order: payments first (depends on users), then reports, then users
        downgrade_start = content.index("def downgrade")
        downgrade_body = content[downgrade_start:]
        p_idx = downgrade_body.find("payments")
        r_idx = downgrade_body.find("reports")
        u_idx = downgrade_body.find("users")
        assert p_idx < r_idx < u_idx, (
            "Downgrade must drop in FK-safe order: payments, reports, users"
        )

    def test_down_revision_none(self, script):
        rev = script.get_revision("0001a2b3c4d5e6")
        assert rev.down_revision is None, (
            f"Baseline down_revision must be None, got {rev.down_revision}"
        )


class TestE475Diff:
    def test_down_revision_changed_only(self):
        """Verify e47590a5c5c1 change is limited to down_revision line."""
        path = ALEMBIC_DIR / "versions" / "e47590a5c5c1_add_kitchen_analysis_to_reports.py"
        content = path.read_text(encoding="utf-8")
        lines = content.split("\n")
        down_rev_lines = [ln for ln in lines if "down_revision" in ln]
        assert len(down_rev_lines) == 1
        assert 'down_revision: Union[str, None] = "0001a2b3c4d5e6"' in down_rev_lines[0]

    def test_revision_unchanged(self, script):
        rev = script.get_revision("e47590a5c5c1")
        assert rev.revision == "e47590a5c5c1"

    def test_upgrade_body_unchanged(self):
        path = ALEMBIC_DIR / "versions" / "e47590a5c5c1_add_kitchen_analysis_to_reports.py"
        content = path.read_text(encoding="utf-8")
        assert "add_column" in content
        assert '"reports"' in content or "'reports'" in content
        assert "kitchen_analysis" in content
        assert "JSONB" in content or "jsonb" in content.lower()
