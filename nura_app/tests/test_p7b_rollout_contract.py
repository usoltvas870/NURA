import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("p7b", ROOT / "scripts" / "p7b_rollout.py")
p7b = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = p7b
spec.loader.exec_module(p7b)
SHA = "a" * 40


def settings(tmp_path: Path) -> p7b.Settings:
    workdir = tmp_path / "work dir"
    environment = tmp_path / ".env"
    environment.write_text("APP_ENV=development\nTEST_MODE=true\n")
    return p7b.Settings(SHA, "nura_app", workdir, workdir / "docker-compose.yml", tmp_path / "state", environment)


def succeeding_runner(calls: list[list[str]]):
    def run(command: list[str]) -> int:
        calls.append(command)
        if "ps" in command:
            return p7b.CommandResult(0, "\n".join('{"Service": "%s", "State": "running", "Health": "healthy"}' % service for service in ("redis", "postgres", *p7b.APP_SERVICES)))
        return 0
    return run


def test_all_cli_operations_and_exact_sha_contract() -> None:
    assert set(p7b.OPERATIONS) == {"status", "preflight", "plan-stage1", "stage1", "verify-stage1", "plan-stage2", "stage2", "verify-stage2", "rollback-stage1", "rollback-stage2", "cleanup"}
    assert p7b.require_sha(SHA) == SHA
    with pytest.raises(SystemExit, match="exact_sha_required"):
        p7b.require_sha("not-a-sha")
    with pytest.raises(SystemExit):
        p7b.parser().parse_args(["unsupported", "--sha", SHA])


def test_compose_context_is_explicit_ordered_and_space_safe(tmp_path: Path) -> None:
    config = settings(tmp_path)
    context = config.context()
    command = p7b.compose_command(context, "up", "--detach", "api")
    assert command[:8] == ["docker", "compose", "--project-name", "nura_app", "--project-directory", str(config.working_directory), "--file", str(config.base_compose)]
    assert command[8:10] == ["--file", context.generated_file]
    assert str(config.working_directory) in command
    assert command[5] == str(config.working_directory)
    assert command[7] == str(config.base_compose)
    assert command[9] == context.generated_file


def test_environment_editor_changes_only_permitted_keys_and_rolls_back(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    original = b"# preserve\nSECRET_KEY=not-printed\nAPP_ENV=development\nTEST_MODE=true\n"
    env.write_bytes(original)
    backup = tmp_path / "backup"
    p7b.edit_environment(env, backup, {"APP_ENV": "production", "TEST_MODE": "false"})
    assert env.read_bytes() == b"# preserve\nSECRET_KEY=not-printed\nAPP_ENV=production\nTEST_MODE=false\n"
    assert backup.read_bytes() == original
    p7b.atomic_write(env, backup.read_bytes(), backup.stat().st_mode & 0o777)
    assert env.read_bytes() == original
    if os.name == "nt":
        with patch.object(p7b.os, "chmod") as chmod:
            p7b.atomic_write(tmp_path / "mode-check", b"x")
        chmod.assert_not_called()
    else:
        assert backup.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("key", ["APP_ENV", "TEST_MODE"])
def test_environment_editor_rejects_duplicates(tmp_path: Path, key: str) -> None:
    env = tmp_path / ".env"
    env.write_text(f"{key}=development\n{key}=test\n")
    with pytest.raises(SystemExit, match=f"duplicate_environment_key:{key}"):
        p7b.edit_environment(env, tmp_path / "backup", {key: "production"})


def test_environment_editor_adds_missing_keys_and_rejects_other_updates(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# keep\nOTHER=value\n")
    p7b.edit_environment(env, tmp_path / "backup", {"APP_ENV": "production", "TEST_MODE": "false"})
    assert env.read_text() == "# keep\nOTHER=value\nAPP_ENV=production\nTEST_MODE=false\n"
    with pytest.raises(SystemExit, match="environment_update_not_permitted"):
        p7b.edit_environment(env, tmp_path / "other", {"SECRET_KEY": "x"})


def test_environment_contract_is_categorical_and_rejects_wrong_values(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("APP_ENV=development\nTEST_MODE=true\n")
    p7b.require_environment(env, {"APP_ENV": "development", "TEST_MODE": "true"})
    with pytest.raises(SystemExit, match="environment_contract_failed"):
        p7b.require_environment(env, {"APP_ENV": "production", "TEST_MODE": "false"})


def test_stage1_persists_context_generates_owned_file_and_excludes_postgres(tmp_path: Path) -> None:
    config, calls = settings(tmp_path), []
    p7b.stage1(config, succeeding_runner(calls))
    state = p7b.RolloutState.load(config.state_file)
    generated = Path(state.current.generated_file)
    assert state.current.sha == SHA and state.stage1_verified
    assert p7b.OWNERSHIP_MARKER in generated.read_text()
    lifecycle = next(command for command in calls if "up" in command)
    joined = " ".join(" ".join(call) for call in calls)
    assert "postgres" not in lifecycle and "volume rm" not in joined and "down -v" not in joined
    assert set(p7b.STAGE1_SERVICES) == {"redis", "api", "bot", "celery-worker", "celery-beat", "admin-bot"}
    assert any(list(command[:5]) == ["git", "-C", str(config.working_directory), "diff", "--quiet"] for command in calls)


def test_stage2_requires_stage1_then_only_recreates_application_services(tmp_path: Path) -> None:
    config, calls = settings(tmp_path), []
    config.environment_file.write_text("APP_ENV=development\nTEST_MODE=true\n")
    with pytest.raises(SystemExit, match="stage1_verification_required"):
        p7b.stage2(config, succeeding_runner(calls))
    p7b.stage1(config, succeeding_runner(calls))
    p7b.stage2(config, succeeding_runner(calls))
    assert p7b.RolloutState.load(config.state_file).stage2_verified
    up_commands = [command for command in calls if "up" in command]
    assert set(up_commands[-1][-len(p7b.APP_SERVICES):]) == set(p7b.APP_SERVICES)
    assert "redis" not in up_commands[-1] and "postgres" not in up_commands[-1]


def test_stage2_preserves_original_backup_across_idempotent_retries(tmp_path: Path) -> None:
    config, calls = settings(tmp_path), []
    original = config.environment_file.read_bytes()
    p7b.stage1(config, succeeding_runner(calls))
    p7b.stage2(config, succeeding_runner(calls))
    p7b.stage2(config, succeeding_runner(calls))
    assert (config.state_directory / f"environment-{SHA}.backup").read_bytes() == original


def test_failed_verification_does_not_create_success_state(tmp_path: Path) -> None:
    config = settings(tmp_path)
    def fail_runner(_: list[str]) -> int:
        return 1
    with pytest.raises(SystemExit, match="verification_failed"):
        p7b.stage1(config, fail_runner)
    assert not p7b.RolloutState.load(config.state_file).stage1_verified


def test_unhealthy_compose_service_blocks_stage_completion(tmp_path: Path) -> None:
    config = settings(tmp_path)
    def unhealthy(command: list[str]) -> int | p7b.CommandResult:
        if "ps" in command:
            return p7b.CommandResult(0, '{"Service": "redis", "State": "running", "Health": "unhealthy"}')
        return 0
    with pytest.raises(SystemExit, match="service_unhealthy"):
        p7b.stage1(config, unhealthy)


def test_dirty_or_untracked_release_is_rejected(tmp_path: Path) -> None:
    config = settings(tmp_path)
    def dirty(command: list[str]) -> int | p7b.CommandResult:
        if "ls-files" in command:
            return p7b.CommandResult(0, "new-file.py\n")
        return 0
    with pytest.raises(SystemExit, match="untracked_worktree"):
        p7b.verify_release(config, dirty)


def test_rollback_uses_persistent_previous_context(tmp_path: Path) -> None:
    config, calls = settings(tmp_path), []
    p7b.stage1(config, succeeding_runner(calls))
    old = config.context("b" * 40)
    state = p7b.RolloutState.load(config.state_file)
    state.previous = old
    state.save(config.state_file)
    p7b.rollback_stage1(config, succeeding_runner(calls))
    assert p7b.RolloutState.load(config.state_file).current.sha == "b" * 40


def test_cleanup_is_idempotent_and_only_removes_owned_stale_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = settings(tmp_path)
    current, stale = config.context(), config.generated_directory / ("compose.p7b." + "c" * 40 + ".yml")
    p7b.ensure_generated(current)
    p7b.atomic_write(stale, (p7b.OWNERSHIP_MARKER + "\n").encode())
    foreign = config.generated_directory / ("compose.p7b." + "d" * 40 + ".yml")
    foreign.write_text("manual file\n")
    p7b.RolloutState(current=current).save(config.state_file)
    p7b.cleanup(config)
    p7b.cleanup(config)
    assert Path(current.generated_file).exists() and not stale.exists() and foreign.exists()
    assert "secrets=redacted" in capsys.readouterr().out


def test_rollout_lock_and_plan_do_not_mutate_state(tmp_path: Path) -> None:
    config = settings(tmp_path)
    p7b.plan(config, 1)
    assert not config.state_file.exists()
    config.lock_file.parent.mkdir(parents=True)
    config.lock_file.write_text("another process")
    with pytest.raises(SystemExit, match="rollout_locked"):
        p7b.stage1(config, succeeding_runner([]))
