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
LIFETIME_CHAT_PATH = TOOLS_ROOT / "lifetime_chat_postgres_smoke.py"
DAILY_TAROT_PATH = TOOLS_ROOT / "daily_tarot_postgres_smoke.py"
PAYMENT_EVENT_RACE_PATH = TOOLS_ROOT / "full_matrix_payment_event_postgres_race.py"
FULL_DELIVERY_RACE_PATH = TOOLS_ROOT / "full_report_telegram_delivery_postgres_race.py"
RUNNER_PATH = TOOLS_ROOT / "run_alembic_postgres_smoke.py"
SOURCE_BASELINE_HEAD = "61977175ef3b88fad618674fca2554db60aae379"
HARNESS_PATHS = (
    BOOTSTRAP_PATH,
    FK_PATH,
    RECONCILIATION_PATH,
    DELIVERY_PATH,
    LIFETIME_CHAT_PATH,
    DAILY_TAROT_PATH,
    PAYMENT_EVENT_RACE_PATH,
    FULL_DELIVERY_RACE_PATH,
)
PRODUCTION_BASELINE_PATHS = (
    "nura_app/api/logging.py",
    "nura_app/api/main.py",
    "nura_app/api/routes/payment.py",
    "nura_app/api/routes/reports.py",
    "nura_app/api/routes/web.py",
    "nura_app/bot/handlers/errors.py",
    "nura_app/bot/handlers/start.py",
    "nura_app/bot/main.py",
    "nura_app/core/config.py",
    "nura_app/core/models.py",
    "nura_app/core/repositories/report.py",
    "nura_app/core/repositories/report_lifecycle.py",
    "nura_app/core/services/account_deletion.py",
    "nura_app/core/services/full_matrix_checkout.py",
    "nura_app/core/services/full_report_telegram_delivery.py",
    "nura_app/core/services/matrix_report_worker.py",
    "nura_app/core/services/telegram_report_delivery.py",
)
TEST_BASELINE_PATHS = (
    "nura_app/tests/conftest.py",
    "nura_app/tests/test_alembic_smoke_harness_contract.py",
    "nura_app/tests/test_daily_tarot_migration_contract.py",
    "nura_app/tests/test_full_matrix_account_deletion.py",
    "nura_app/tests/test_full_matrix_checkout.py",
    "nura_app/tests/test_full_report_telegram_delivery.py",
    "nura_app/tests/test_matrix_report_worker_lifecycle.py",
    "nura_app/tests/test_mini_report_telegram_delivery.py",
    "nura_app/tests/test_report_generation_reconciliation.py",
    "nura_app/tests/test_sandbox_settings_isolation.py",
    "nura_app/tests/test_security_rendering_gate.py",
    "nura_app/tests/test_telegram_first_postgres_failure_retry.py",
    "nura_app/tests/test_telegram_first_postgres_golden_path.py",
    "nura_app/tests/test_telegram_first_safe_suite_contract.py",
    "nura_app/tests/test_telegram_first_security_acceptance.py",
    "nura_app/tests/test_telegram_first_service_boot.py",
)
TOOLING_BASELINE_PATHS = (
    "nura_app/tools/sitecustomize.py",
    "nura_app/tools/telegram_first_bot_boot_probe.py",
    "nura_app/tools/telegram_first_safe_suite.py",
    "nura_app/tools/telegram_first_sandbox_acceptance.py",
    "nura_app/tools/telegram_first_security_context.py",
    "nura_app/tools/telegram_first_security_guard.py",
    "nura_app/tools/telegram_first_sentry_probe.py",
    "nura_app/tools/telegram_first_service_boot.py",
)
CODE_BASELINE_PATHS = frozenset(
    (*PRODUCTION_BASELINE_PATHS, *TEST_BASELINE_PATHS, *TOOLING_BASELINE_PATHS)
)
CRITICAL_TELEGRAM_FIRST_ARTIFACTS = {
    "nura_app/api/logging.py",
    "nura_app/bot/main.py",
    "nura_app/tests/test_alembic_smoke_harness_contract.py",
    "nura_app/tests/test_telegram_first_postgres_failure_retry.py",
    "nura_app/tests/test_telegram_first_postgres_golden_path.py",
    "nura_app/tests/test_telegram_first_safe_suite_contract.py",
    "nura_app/tests/test_telegram_first_security_acceptance.py",
    "nura_app/tests/test_telegram_first_service_boot.py",
    "nura_app/tools/telegram_first_safe_suite.py",
    "nura_app/tools/telegram_first_sandbox_acceptance.py",
    "nura_app/tools/telegram_first_security_guard.py",
    "nura_app/tools/telegram_first_service_boot.py",
}
ROOT_DOCUMENTATION_PATHS = {
    "ADMIN_BOT_SPEC.md",
    "AGENTS.md",
    "AGENTS_TODO.md",
    "AUTH_REMAINING_TASKS.md",
    "DEPLOY.md",
    "NURA_SITE_QA_AUDIT_2026-07-06.md",
    "PLAN.md",
    "industry-standard-analysis.md",
    "pricing-vs-report-analysis.md",
}
NESTED_DOCUMENTATION_PATHS = {
    "frontend/pwa/app/AGENTS.md",
    "nura_app/templates/reports/AGENTS.md",
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


@pytest.fixture(scope="module")
def full_delivery_race():
    return _load(FULL_DELIVERY_RACE_PATH, "full_delivery_race")


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
    assert bootstrap.EXPECTED_HEAD == "e8f9a0b1c2d3"
    assert fk.PREVIOUS_HEAD == "b9c0d1e2f3a4"
    assert fk.NORMALIZATION_REVISION == "c0d1e2f3a4b5"
    assert fk.EXPECTED_HEAD == "e8f9a0b1c2d3"
    assert reconciliation.PRODUCTION_REVISION == "d5e6f7a8b9c0"
    assert reconciliation.FK_NORMALIZATION_HEAD == "c0d1e2f3a4b5"
    assert reconciliation.EXPECTED_HEAD == "d1e2f3a4b5c6"
    assert reconciliation.GRAPH_HEAD == "e8f9a0b1c2d3"


def test_full_delivery_race_contract(full_delivery_race) -> None:
    assert full_delivery_race.PARENT == "e8f9a0b1c2d3"
    assert full_delivery_race.HEAD == "c5d6e7f8a9b0"
    assert full_delivery_race.WORKERS == 8
    full_delivery_race._validate_disposable_database_url(
        "postgresql://user:pass@127.0.0.1:5432/nura_delivery_disposable"
    )
    for url in (
        "postgresql://user:pass@example.com/nura_delivery_disposable",
        "postgresql://user:pass@127.0.0.1/nura_production",
        "sqlite:///nura_delivery_disposable.db",
    ):
        with pytest.raises(ValueError):
            full_delivery_race._validate_disposable_database_url(url)


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
    assert "lifetime_chat_postgres_smoke.py" in source
    assert "daily_tarot_postgres_smoke.py" in source


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


def _normalize_repo_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _parse_porcelain_paths(output: str) -> set[str]:
    records = output.split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(records):
        record = records[index]
        if not record:
            break
        status = record[:2]
        paths.add(_normalize_repo_path(record[3:]))
        if "R" in status or "C" in status:
            index += 1
            paths.add(_normalize_repo_path(records[index]))
        index += 1
    return paths


def _parse_nul_path_list(output: str) -> set[str]:
    return {
        _normalize_repo_path(path)
        for path in output.split("\0")
        if path
    }


def _is_separate_documentation_or_state_path(path: str) -> bool:
    normalized = _normalize_repo_path(path)
    if normalized == "STATE.md":
        return True
    if normalized in ROOT_DOCUMENTATION_PATHS | NESTED_DOCUMENTATION_PATHS:
        return True
    return normalized.startswith("docs/") and Path(normalized).suffix.lower() in {
        ".md",
        ".txt",
    }


def _assert_code_baseline(paths: set[str]) -> None:
    normalized = {_normalize_repo_path(path) for path in paths}
    missing = sorted(CODE_BASELINE_PATHS - normalized)
    unexpected = sorted(normalized - CODE_BASELINE_PATHS)
    if missing or unexpected:
        raise AssertionError(
            "Telegram-first code baseline drift: "
            f"missing={missing}; unexpected={unexpected}"
        )


def _code_paths(paths: set[str]) -> set[str]:
    return {
        _normalize_repo_path(path)
        for path in paths
        if not _is_separate_documentation_or_state_path(path)
    }


def _assert_stage_code_scope(
    head: str,
    parent: str | None,
    *,
    committed_paths: set[str],
    staged_paths: set[str],
    worktree_paths: set[str],
) -> None:
    if head == SOURCE_BASELINE_HEAD:
        if staged_paths:
            _assert_code_baseline(staged_paths)
            unexpected_worktree_code = sorted(_code_paths(worktree_paths))
            if unexpected_worktree_code:
                raise AssertionError(
                    "Telegram-first unstaged code drift: "
                    f"unexpected={unexpected_worktree_code}"
                )
        else:
            _assert_code_baseline(_code_paths(worktree_paths))
        return
    if parent == SOURCE_BASELINE_HEAD:
        _assert_code_baseline(committed_paths)


def test_code_baseline_manifest_is_scoped_and_present() -> None:
    assert len(CODE_BASELINE_PATHS) == 41
    assert len(PRODUCTION_BASELINE_PATHS) == 17
    assert len(TEST_BASELINE_PATHS) == 16
    assert len(TOOLING_BASELINE_PATHS) == 8
    assert len(CODE_BASELINE_PATHS) == (
        len(PRODUCTION_BASELINE_PATHS)
        + len(TEST_BASELINE_PATHS)
        + len(TOOLING_BASELINE_PATHS)
    )
    assert all(path == _normalize_repo_path(path) for path in CODE_BASELINE_PATHS)
    assert all(
        path.startswith(("nura_app/api/", "nura_app/bot/", "nura_app/core/"))
        for path in PRODUCTION_BASELINE_PATHS
    )
    assert all(path.startswith("nura_app/tests/") for path in TEST_BASELINE_PATHS)
    assert all(path.startswith("nura_app/tools/") for path in TOOLING_BASELINE_PATHS)
    assert CRITICAL_TELEGRAM_FIRST_ARTIFACTS <= CODE_BASELINE_PATHS
    assert "STATE.md" not in CODE_BASELINE_PATHS
    assert not any(path.startswith("docs/") for path in CODE_BASELINE_PATHS)

    missing_files = sorted(
        path for path in CODE_BASELINE_PATHS if not (REPO_ROOT / path).is_file()
    )
    assert not missing_files, f"Missing Telegram-first baseline files: {missing_files}"


def test_source_baseline_and_direct_child_code_scope() -> None:
    revision = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    head = revision[0]
    parent = revision[1] if len(revision) > 1 else None
    if head != SOURCE_BASELINE_HEAD and parent != SOURCE_BASELINE_HEAD:
        return

    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--no-renames", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    unstaged = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    committed_paths: set[str] = set()
    if parent == SOURCE_BASELINE_HEAD:
        committed = subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                "--no-renames",
                "-z",
                f"{SOURCE_BASELINE_HEAD}..{head}",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        committed_paths = _parse_nul_path_list(committed.stdout)
    _assert_stage_code_scope(
        head,
        parent,
        committed_paths=committed_paths,
        staged_paths=_parse_nul_path_list(staged.stdout),
        worktree_paths=(
            _parse_nul_path_list(unstaged.stdout)
            | _parse_nul_path_list(untracked.stdout)
        ),
    )


def test_code_baseline_comparison_normalizes_order_and_windows_separators() -> None:
    windows_paths = {
        path.replace("/", "\\") for path in reversed(sorted(CODE_BASELINE_PATHS))
    }

    _assert_code_baseline(windows_paths)


def test_code_baseline_comparison_reports_missing_and_unexpected_paths() -> None:
    paths = set(CODE_BASELINE_PATHS)
    paths.remove("nura_app/tests/test_telegram_first_postgres_golden_path.py")
    paths.add("nura_app/alembic/versions/unauthorized_revision.py")

    with pytest.raises(AssertionError) as exc_info:
        _assert_code_baseline(paths)

    message = str(exc_info.value)
    assert (
        "missing=['nura_app/tests/test_telegram_first_postgres_golden_path.py']"
        in message
    )
    assert (
        "unexpected=['nura_app/alembic/versions/unauthorized_revision.py']"
        in message
    )


def test_direct_child_requires_exact_committed_code_scope() -> None:
    direct_child = "a" * 40
    _assert_stage_code_scope(
        direct_child,
        SOURCE_BASELINE_HEAD,
        committed_paths=set(CODE_BASELINE_PATHS),
        staged_paths=set(),
        worktree_paths=set(),
    )
    with pytest.raises(AssertionError, match="code baseline drift"):
        _assert_stage_code_scope(
            direct_child,
            SOURCE_BASELINE_HEAD,
            committed_paths=set(),
            staged_paths=set(),
            worktree_paths=set(),
        )

    _assert_stage_code_scope(
        "b" * 40,
        direct_child,
        committed_paths={"unrelated/future.py"},
        staged_paths=set(),
        worktree_paths=set(),
    )


@pytest.mark.parametrize("forbidden_path", ["docs/README.md", "STATE.md"])
def test_direct_child_rejects_mixed_code_commit(forbidden_path: str) -> None:
    with pytest.raises(AssertionError) as exc_info:
        _assert_stage_code_scope(
            "a" * 40,
            SOURCE_BASELINE_HEAD,
            committed_paths={*CODE_BASELINE_PATHS, forbidden_path},
            staged_paths=set(),
            worktree_paths=set(),
        )

    assert f"unexpected=['{forbidden_path}']" in str(exc_info.value)


@pytest.mark.parametrize("forbidden_path", ["docs/README.md", "STATE.md"])
def test_staged_scope_rejects_mixed_code_commit(forbidden_path: str) -> None:
    with pytest.raises(AssertionError) as exc_info:
        _assert_stage_code_scope(
            SOURCE_BASELINE_HEAD,
            None,
            committed_paths=set(),
            staged_paths={*CODE_BASELINE_PATHS, forbidden_path},
            worktree_paths=set(),
        )

    assert f"unexpected=['{forbidden_path}']" in str(exc_info.value)


def test_separate_scope_classification_normalizes_windows_paths() -> None:
    assert _is_separate_documentation_or_state_path(r".\STATE.md")
    assert _is_separate_documentation_or_state_path(r"docs\README.md")
    assert _is_separate_documentation_or_state_path(
        r"frontend\pwa\app\AGENTS.md"
    )
    assert not _is_separate_documentation_or_state_path(
        r"docs\acceptance\unauthorized.py"
    )
    assert not _is_separate_documentation_or_state_path(
        r"nura_app\alembic\versions\unauthorized_revision.py"
    )


def test_worktree_parser_keeps_both_sides_of_rename() -> None:
    output = (
        "R  nura_app/core/services/my_reports.py\0"
        "nura_app/alembic/versions/unauthorized_revision.py\0"
    )

    assert _parse_porcelain_paths(output) == {
        "nura_app/core/services/my_reports.py",
        "nura_app/alembic/versions/unauthorized_revision.py",
    }


def test_committed_diff_parser_normalizes_nul_separated_paths() -> None:
    output = (
        "nura_app/tests/test_telegram_first_postgres_golden_path.py\0"
        "docs\\NURA FORMS SYSTEM.txt\0"
        "nura_app/tools/telegram_first_safe_suite.py\0"
    )

    assert _parse_nul_path_list(output) == {
        "docs/NURA FORMS SYSTEM.txt",
        "nura_app/tests/test_telegram_first_postgres_golden_path.py",
        "nura_app/tools/telegram_first_safe_suite.py",
    }
