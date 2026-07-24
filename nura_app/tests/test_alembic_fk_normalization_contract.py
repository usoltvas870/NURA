"""Static FK normalization migration contract tests.

Does NOT require PostgreSQL.  Validates migration file properties and
the Alembic graph after adding the new normalization revision.
"""

import importlib.util
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory


# Load the standalone harness as a module without requiring tools/__init__.py
HARNESS_PATH = Path(__file__).resolve().parent.parent / "tools" / "alembic_fk_normalization_smoke.py"


def _load_harness_module():
    spec = importlib.util.spec_from_file_location("fk_smoke_harness", str(HARNESS_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules["fk_smoke_harness"] = module
    spec.loader.exec_module(module)
    return module

ALEMBIC_DIR = Path(__file__).resolve().parent.parent / "alembic"
INI_PATH = Path(__file__).resolve().parent.parent / "alembic.ini"


@pytest.fixture(scope="module")
def script():
    cfg = Config(str(INI_PATH))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    return ScriptDirectory.from_config(cfg)


class TestGraphContract:
    def test_single_root(self, script):
        roots = [r for r in script.walk_revisions() if r.is_base]
        assert len(roots) == 1
        assert roots[0].revision == "0001a2b3c4d5e6"

    def test_single_head(self, script):
        heads = script.get_revisions("heads")
        assert len(heads) == 1
        assert heads[0].revision == "d2e3f4a5b6c7"

    def test_new_revision_exists(self, script):
        rev = script.get_revision("c0d1e2f3a4b5")
        assert rev is not None

    def test_down_revision_is_b9c0(self, script):
        rev = script.get_revision("c0d1e2f3a4b5")
        assert rev.down_revision == "b9c0d1e2f3a4"

    def test_no_branches(self, script):
        for rev in script.walk_revisions():
            assert not rev.branch_labels, (
                f"Revision {rev.revision} has branch_labels"
            )

    def test_linear_chain(self, script):
        revisions = list(script.iterate_revisions("head", "base"))
        ids = [r.revision for r in revisions]
        ids.reverse()
        assert ids[0] == "0001a2b3c4d5e6"
        assert ids[-1] == "d2e3f4a5b6c7"
        assert "b9c0d1e2f3a4" in ids
        assert ids.index("c0d1e2f3a4b5") == ids.index("d1e2f3a4b5c6") - 1
        assert ids.index("d1e2f3a4b5c6") == ids.index("b1c2d3e4f5a6") - 1
        assert ids.index("b1c2d3e4f5a6") == ids.index("c1d2e3f4a5b6") - 1
        assert ids.index("c1d2e3f4a5b6") == ids.index("d2e3f4a5b6c7") - 1
        assert ids.index("b9c0d1e2f3a4") == ids.index("c0d1e2f3a4b5") - 1


class TestMigrationFile:
    _PATH = ALEMBIC_DIR / "versions" / "c0d1e2f3a4b5_normalize_report_payment_fk_names.py"

    @property
    def content(self):
        return self._PATH.read_text(encoding="utf-8")

    def test_file_exists(self):
        assert self._PATH.is_file()

    def test_no_drop_constraint(self):
        assert "DROP CONSTRAINT" not in self.content
        assert "drop_constraint" not in self.content

    def test_no_add_constraint(self):
        assert "ADD CONSTRAINT" not in self.content.upper()
        # But RENAME is allowed
        assert "RENAME CONSTRAINT" in self.content

    def test_rename_only(self):
        # Only safe DDL: ALTER TABLE ... RENAME CONSTRAINT
        c = self.content
        assert "RENAME CONSTRAINT" in c
        assert "ADD FOREIGN KEY" not in c.upper()
        # Check in upgrade/downgrade body only (docstring may contain "Create")
        dg_start = c.find("def downgrade")
        body = c[:dg_start]  # upgrade body (before downgrade)
        assert "DROP CONSTRAINT" not in body
        assert "ADD CONSTRAINT" not in body.upper()

    def test_no_column_modification(self):
        c = self.content
        assert "ALTER COLUMN" not in c.upper()
        assert "DROP COLUMN" not in c.upper()
        assert "ADD COLUMN" not in c.upper()

    def test_no_index_modification(self):
        c = self.content
        assert "INDEX" not in c.upper()

    def test_semantic_inspection(self):
        c = self.content
        assert "pg_constraint" in c
        assert "pg_attribute" in c
        assert "contype = 'f'" in c

    def test_postgresql_check(self):
        c = self.content
        assert "postgresql" in c.lower()
        assert "dialect" in c.lower()

    def test_target_names(self):
        c = self.content
        assert "fk_reports_payment_id_payments" in c
        assert "fk_payments_promo_code_id_promo_codes" in c

    def test_legacy_names(self):
        c = self.content
        assert "reports_payment_id_fkey" in c
        assert "payments_promo_code_id_fkey" in c

    def test_fail_on_missing(self):
        c = self.content.lower()
        assert "no semantic fk" in c

    def test_fail_on_duplicate(self):
        c = self.content
        assert "ultiple" in c

    def test_fail_on_unexpected(self):
        c = self.content
        assert "nexpected" in c

    def test_downgrade_noop(self):
        c = self.content
        dg_start = c.find("def downgrade")
        dg_body = c[dg_start:]
        assert "no-op" in dg_body.lower() or "pass" in dg_body.lower()

    def test_no_if_not_exists(self):
        assert "IF NOT EXISTS" not in self.content

    def test_no_create_all(self):
        assert "create_all" not in self.content

    def test_no_stamp(self):
        assert "stamp" not in self.content.lower()

    def test_no_credentials(self):
        c = self.content
        assert "postgresql://" not in c
        assert "DATABASE_URL" not in c


class TestHarnessContract:
    """Contract tests for the standalone PostgreSQL smoke harness.

    These tests do NOT require Docker or a live database.
    """

    @pytest.fixture(scope="class")
    def harness(self):
        return _load_harness_module()

    def test_subprocess_nonzero_raises(self, harness):
        with pytest.raises(RuntimeError):
            harness._run_subprocess(
                "expected-failure",
                [sys.executable, "-c", "import sys; sys.exit(1)"],
            )

    def test_setup_failure_stops_scenario(self, harness, monkeypatch):
        calls = []

        def _explode():
            calls.append("explode")
            raise RuntimeError("fixture setup failed")

        harness._ALL_OK = True
        harness._SCENARIO_RESULTS.clear()
        harness._scenario("test-scenario", _explode)
        assert calls == ["explode"]
        assert not harness._ALL_OK
        assert harness._SCENARIO_RESULTS == [("test-scenario", False)]

    @pytest.mark.parametrize(
        "name",
        [
            "FK-NORM-01: properly migrated DB no-op",
            "FK-NORM-02: legacy names normalized",
            "FK-NORM-03: mixed schema",
            "FK-NORM-04: unexpected name fail-closed",
            "FK-NORM-05: missing FK fail-closed",
            "FK-NORM-06: duplicate semantic FK fail-closed",
            "FK-NORM-07: both-name conflict fail-closed",
            "FK-NORM-08: downgrade/re-upgrade",
            "FK-NORM-09: data and referential integrity",
            "FK-NORM-10: full blank upgrade",
        ],
    )
    def test_scenario_registry_contains_all(self, name):
        source = HARNESS_PATH.read_text(encoding="utf-8")
        assert name in source

    def test_main_returns_nonzero_on_failure(self, harness, monkeypatch):
        # Simulate DATABASE_URL set so main does not fail early.
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")

        # Force the first scenario to fail so we exercise the failure path.
        original = harness.scenario_01_properly_migrated_noop
        monkeypatch.setattr(
            harness,
            "scenario_01_properly_migrated_noop",
            lambda: (_ for _ in ()).throw(RuntimeError("forced failure")),
        )

        harness._ALL_OK = True
        harness._SCENARIO_RESULTS.clear()
        with pytest.raises(SystemExit) as exc_info:
            harness.main()
        assert exc_info.value.code != 0
        assert not harness._ALL_OK
        assert any(not ok for _, ok in harness._SCENARIO_RESULTS)

    @pytest.mark.parametrize(
        "raw,expected_masked",
        [
            (
                "postgresql://user:secret@db.example.com:5432/nura",
                "postgresql://***/nura",
            ),
            (
                "postgresql+psycopg2://admin:p%40ss@10.0.0.1:5432/db",
                "postgresql://***/db",
            ),
            (
                "connect to postgresql://user:pass@host/db now",
                "connect to postgresql://***/db now",
            ),
        ],
    )
    def test_credentials_masking(self, harness, raw, expected_masked):
        assert harness._sanitize(raw) == expected_masked

    def test_url_normalization_to_asyncpg(self, harness):
        assert harness._normalize_to_asyncpg_url(
            "postgresql://user:pass@localhost:5432/db"
        ) == "postgresql+asyncpg://user:pass@localhost:5432/db"

    def test_url_normalization_rejects_unsupported_scheme(self, harness):
        with pytest.raises(ValueError):
            harness._normalize_to_asyncpg_url("mysql://user:pass@localhost/db")


class TestBootstrapContractRegression:
    """Existing bootstrap tests must still pass."""
    pass  # Covered by running the separate test file
