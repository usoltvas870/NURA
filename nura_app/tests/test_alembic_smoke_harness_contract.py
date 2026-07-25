"""Static contracts for portable disposable PostgreSQL smoke tooling."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

NURA_APP_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = NURA_APP_ROOT.parent
TOOLS_ROOT = NURA_APP_ROOT / "tools"
BOOTSTRAP_PATH = TOOLS_ROOT / "alembic_postgres_bootstrap_smoke.py"
FK_PATH = TOOLS_ROOT / "alembic_fk_normalization_smoke.py"
RECONCILIATION_PATH = TOOLS_ROOT / "alembic_production_reconciliation_smoke.py"
DELIVERY_PATH = TOOLS_ROOT / "telegram_report_delivery_postgres_smoke.py"
RUNNER_PATH = TOOLS_ROOT / "run_alembic_postgres_smoke.py"
HARNESS_PATHS = (BOOTSTRAP_PATH, FK_PATH, RECONCILIATION_PATH, DELIVERY_PATH)
ALLOWLIST = {
    "STATE.md",
    "nura_app/bot/handlers/profile.py",
    "nura_app/bot/keyboards/main_menu.py",
    "nura_app/core/repositories/mini_report_generation.py",
    "nura_app/core/repositories/report.py",
    "nura_app/core/repositories/telegram_report_delivery.py",
    "nura_app/core/services/my_reports.py",
    "nura_app/core/services/telegram_report_delivery.py",
    "nura_app/core/tasks.py",
    "nura_app/tests/test_alembic_smoke_harness_contract.py",
    "nura_app/tests/test_celery_async_task_contract.py",
    "nura_app/tests/test_my_reports.py",
}


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bootstrap():
    return _load(BOOTSTRAP_PATH, "portable_bootstrap_smoke")


@pytest.fixture(scope="module")
def fk():
    return _load(FK_PATH, "portable_fk_smoke")


@pytest.fixture(scope="module")
def reconciliation():
    return _load(RECONCILIATION_PATH, "portable_reconciliation_smoke")


@pytest.fixture(scope="module")
def runner():
    return _load(RUNNER_PATH, "portable_smoke_runner")


def test_harnesses_have_no_stale_worktree_or_docker_sql() -> None:
    for path in HARNESS_PATHS:
        source = path.read_text(encoding="utf-8")
        assert r"C:\tmp\nura-closed-beta-hardening" not in source
        assert "docker exec" not in source.lower()
        assert "nura_smoke_bootstrap" not in source
        assert "nura_fk_smoke" not in source
        assert (
            "psycopg2.connect(_URL)" in source
            or "psycopg2.connect(database_url)" in source
        )


def test_roots_are_derived_from_resolved_file(bootstrap, fk, reconciliation) -> None:
    for module in (bootstrap, fk, reconciliation):
        assert module.REPO_ROOT == REPO_ROOT
        assert module.NURA_APP_ROOT == NURA_APP_ROOT
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "Path(__file__).resolve()" in source


def test_harness_import_is_independent_of_current_directory(tmp_path: Path) -> None:
    for path in HARNESS_PATHS:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib.util;"
                    f"p=r'{path}';"
                    "s=importlib.util.spec_from_file_location('portable',p);"
                    "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
                    "print(m.REPO_ROOT)"
                ),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert Path(result.stdout.strip()) == REPO_ROOT


def test_revision_constants(bootstrap, fk, reconciliation) -> None:
    assert bootstrap.EXPECTED_BASE == "0001a2b3c4d5e6"
    assert bootstrap.FK_NORMALIZATION_HEAD == "c0d1e2f3a4b5"
    assert bootstrap.PREVIOUS_HEAD == "d1e2f3a4b5c6"
    assert bootstrap.EXPECTED_HEAD == "d2e3f4a5b6c7"
    assert fk.PREVIOUS_HEAD == "b9c0d1e2f3a4"
    assert fk.NORMALIZATION_REVISION == "c0d1e2f3a4b5"
    assert fk.EXPECTED_HEAD == "d2e3f4a5b6c7"
    assert reconciliation.PRODUCTION_REVISION == "d5e6f7a8b9c0"
    assert reconciliation.FK_NORMALIZATION_HEAD == "c0d1e2f3a4b5"
    assert reconciliation.EXPECTED_HEAD == "d1e2f3a4b5c6"
    assert reconciliation.GRAPH_HEAD == "d2e3f4a5b6c7"


def test_structured_contract_helpers_reject_drift(bootstrap) -> None:
    rows = [("id", "uuid", "NO"), ("name", "character varying", "YES")]
    assert bootstrap._column_contract(rows) == {
        "id": ("uuid", "NO"),
        "name": ("character varying", "YES"),
    }
    assert bootstrap._column_contract(rows) != {
        "id": ("character varying", "NO"),
        "name": ("uuid", "YES"),
    }
    valid_backfill = [("legacy_unlinked", "completed", object(), None, 0)]
    assert bootstrap._legacy_backfill_matches(valid_backfill)
    assert not bootstrap._legacy_backfill_matches(
        [("legacy_unlinked", "completed", object(), "payment-id", 0)]
    )
    assert not bootstrap._legacy_backfill_matches(
        [("legacy_unlinked", "completed", object(), None, 10)]
    )


def test_bootstrap_does_not_describe_previous_revision_as_current_head() -> None:
    source = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    forbidden = (
        "Current is b9c0d1e2f3a4",
        "Single head b9c0d1e2f3a4",
        'stamp", "b9c0d1e2f3a4',
    )
    assert all(value not in source for value in forbidden)


def test_runner_contract(runner) -> None:
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert runner.IMAGE == "postgres:16-alpine"
    assert "127.0.0.1::5432" in source
    assert 'container_name = f"nura-alembic-smoke-{suffix}"' in source
    assert "secrets.token_hex" in source
    assert "secrets.token_urlsafe" in source
    assert '["docker", "rm", "-f", "-v", container_name]' in source
    assert "docker prune" not in source.lower()
    assert "system prune" not in source.lower()
    assert "alembic_postgres_bootstrap_smoke.py" in source
    assert "alembic_fk_normalization_smoke.py" in source
    assert "alembic_production_reconciliation_smoke.py" in source


def test_runner_masks_credentials(runner) -> None:
    url = "postgresql://user:secret@127.0.0.1:12345/database"
    masked = runner._sanitize(url, ("user", "secret", "database", url))
    assert url not in masked
    assert "secret" not in masked
    assert "postgresql://***/***" in masked


def test_reconciliation_harness_rejects_non_disposable_urls(reconciliation) -> None:
    reconciliation._validate_disposable_database_url(
        "postgresql://user:pass@127.0.0.1:5432/smoke_disposable"
    )
    for url in (
        "postgresql://user:pass@example.com:5432/smoke_disposable",
        "postgresql://user:pass@127.0.0.1:5432/nura_production",
        "sqlite:///tmp/smoke_disposable.sqlite",
    ):
        with pytest.raises(ValueError):
            reconciliation._validate_disposable_database_url(url)


def test_child_environments_exclude_production_values(
    bootstrap, fk, reconciliation, runner, monkeypatch
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("YOOKASSA_SECRET_KEY", "poison-secret")
    bootstrap._URL = "postgresql://user:pass@127.0.0.1/database"
    fk._URL = bootstrap._URL
    reconciliation._URL = bootstrap._URL
    for env in (
        bootstrap._child_env(),
        fk._child_env(),
        reconciliation._child_env(),
        runner._child_env(bootstrap._URL),
    ):
        assert env["APP_ENV"] == "test"
        assert env["DATABASE_URL"] == bootstrap._URL
        assert "YOOKASSA_SECRET_KEY" not in env


def test_shadow_search_path_is_scoped_to_reconciliation_upgrade(reconciliation) -> None:
    base_env = reconciliation._child_env()
    shadow_env = reconciliation._shadow_search_path_env()
    assert "PGOPTIONS" not in base_env
    assert shadow_env["PGOPTIONS"] == "-c search_path=p43d_shadow,public"


def test_dotenv_source_is_disabled(tmp_path: Path, bootstrap) -> None:
    poison = tmp_path / ".env"
    poison.write_text("SMOKE_SENTINEL=poison\n", encoding="utf-8")
    script = """
from pydantic_settings import BaseSettings
from pydantic_settings.sources import DotEnvSettingsSource
DotEnvSettingsSource.__call__ = lambda self: {}
class SmokeSettings(BaseSettings):
    smoke_sentinel: str = "safe"
    model_config = {"env_file": ".env"}
print(SmokeSettings().smoke_sentinel)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=bootstrap._child_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "safe"


def test_no_production_stamp_guidance() -> None:
    for path in (*HARNESS_PATHS, RUNNER_PATH):
        source = path.read_text(encoding="utf-8").lower()
        assert "stamp production" not in source
        assert "production stamp" not in source


def _paths_outside_allowlist(paths: set[str]) -> set[str]:
    return paths - ALLOWLIST


def _parse_porcelain_paths(output: str) -> set[str]:
    records = output.split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(records):
        record = records[index]
        if not record:
            break
        status = record[:2]
        paths.add(record[3:].replace("\\", "/"))
        if "R" in status or "C" in status:
            index += 1
            paths.add(records[index].replace("\\", "/"))
        index += 1
    return paths


def test_worktree_diff_stays_inside_allowlist() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert _parse_porcelain_paths(result.stdout) == ALLOWLIST


def test_worktree_allowlist_rejects_unrelated_sensitive_scopes() -> None:
    unrelated_paths = {
        "README.md",
        "nura_app/alembic/versions/d2e3f4a5b6c7_add_telegram_mini_report_delivery.py",
        "nura_app/alembic/versions/unauthorized_revision.py",
        "nura_app/core/config.py",
        "nura_app/requirements.txt",
        "nura_app/api/routes/web.py",
        "frontend/pwa/app/app.js",
        "nura_app/deploy/deploy.sh",
        "graphify-out/graph.json",
        "nura_app/tests/shard-result.log",
    }

    assert _paths_outside_allowlist(unrelated_paths) == unrelated_paths


def test_worktree_parser_keeps_both_sides_of_rename() -> None:
    output = (
        "R  nura_app/core/services/my_reports.py\0"
        "nura_app/alembic/versions/unauthorized_revision.py\0"
    )

    assert _parse_porcelain_paths(output) == {
        "nura_app/core/services/my_reports.py",
        "nura_app/alembic/versions/unauthorized_revision.py",
    }
