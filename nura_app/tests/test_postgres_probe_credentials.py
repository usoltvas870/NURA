"""Security contract for process-local PostgreSQL probe credentials."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "postgres_probe.py"
SPEC = importlib.util.spec_from_file_location("postgres_probe_contract", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)
FIXTURE_PASSWORD = "fixture-postgres-probe-password-2026"


def _secret(path: Path, value: str = FIXTURE_PASSWORD) -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def _compose(tmp_path: Path) -> Path:
    return _secret(tmp_path / "compose.yml", "services: {}")


def test_safe_file_password_is_child_environment_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = _secret(tmp_path / "postgres_password")
    compose = _compose(tmp_path)
    parent_before = os.environ.get("PGPASSWORD")
    captured: dict[str, object] = {}

    def run(command, environment, **kwargs):
        captured["command"] = list(command)
        captured["environment"] = dict(environment)
        return 0, b"d1e2f3a4b5c6\n", False

    monkeypatch.setattr(probe, "_run_bounded", run)
    assert probe.run_postgres_probe(compose, "revision", password_file=secret) == (
        "d1e2f3a4b5c6"
    )
    command = captured["command"]
    assert isinstance(command, list)
    assert command[command.index("-e") + 1] == "PGPASSWORD"
    assert "PGCONNECT_TIMEOUT" in command
    assert "PGOPTIONS" in command
    assert FIXTURE_PASSWORD not in repr(command)
    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert environment["PGPASSWORD"] == FIXTURE_PASSWORD
    assert "POSTGRES_PASSWORD" not in environment
    assert os.environ.get("PGPASSWORD") == parent_before


def test_snapshot_returns_exact_revision_and_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = _secret(tmp_path / "postgres_password")
    compose = _compose(tmp_path)
    output = "d1e2f3a4b5c6\n2\n5\n2\n0\n0\n"
    monkeypatch.setattr(
        probe,
        "_run_bounded",
        lambda command, environment: (0, output.encode(), False),
    )
    assert probe.run_postgres_probe(
        compose,
        "snapshot",
        password_file=secret,
    ).splitlines() == ["d1e2f3a4b5c6", "2", "5", "2", "0", "0"]


def test_wrong_password_failure_is_bounded_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = _secret(tmp_path / "postgres_password")
    compose = _compose(tmp_path)
    monkeypatch.setattr(
        probe,
        "_run_bounded",
        lambda command, environment: (2, b"", False),
    )
    with pytest.raises(probe.PostgresProbeError) as raised:
        probe.run_postgres_probe(compose, "revision", password_file=secret)
    assert str(raised.value) == "database_revision_probe_failed"
    assert FIXTURE_PASSWORD not in str(raised.value)
    assert "fixture.invalid" not in str(raised.value)


@pytest.mark.parametrize(
    "failure",
    [OSError("fixture-password-must-not-escape"), subprocess.TimeoutExpired([], 30)],
)
def test_process_launch_failure_is_bounded_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    secret = _secret(tmp_path / "postgres_password")
    compose = _compose(tmp_path)

    def fail(command, environment):
        raise failure

    monkeypatch.setattr(probe, "_run_bounded", fail)
    with pytest.raises(probe.PostgresProbeError) as raised:
        probe.run_postgres_probe(compose, "revision", password_file=secret)
    assert str(raised.value) == "database_revision_probe_failed"
    assert FIXTURE_PASSWORD not in str(raised.value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "line-one\nline-two",
        "line-one\rline-two",
        "nul\x00value",
        "x" * (16 * 1024 + 1),
    ],
)
def test_invalid_password_content_is_rejected(tmp_path: Path, value: str) -> None:
    secret = _secret(tmp_path / "postgres_password", value)
    with pytest.raises(probe.PostgresProbeError, match="postgres_probe_password"):
        probe.read_postgres_password(secret)


def test_unsafe_mode_is_rejected_without_environment_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = _secret(tmp_path / "postgres_password")
    secret.chmod(0o644)
    metadata = secret.stat()
    monkeypatch.setattr(probe, "_identity", lambda: (metadata.st_uid, metadata.st_gid))
    with pytest.raises(probe.PostgresProbeError, match="postgres_probe_password_unsafe"):
        probe.read_postgres_password(
            secret,
            allow_legacy_environment=True,
            environment={"POSTGRES_PASSWORD": "fallback-must-not-be-used"},
        )


def test_hardlinked_password_is_rejected(tmp_path: Path) -> None:
    secret = _secret(tmp_path / "postgres_password")
    os.link(secret, tmp_path / "second-link")
    with pytest.raises(probe.PostgresProbeError, match="postgres_probe_password_unsafe"):
        probe.read_postgres_password(secret)


def test_linked_password_path_is_rejected(tmp_path: Path) -> None:
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    _secret(real_directory / "postgres_password")
    linked_directory = tmp_path / "linked"
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(linked_directory), str(real_directory)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    else:
        linked_directory.symlink_to(real_directory, target_is_directory=True)
    with pytest.raises(probe.PostgresProbeError, match="postgres_probe_password_unsafe"):
        probe.read_postgres_password(linked_directory / "postgres_password")


def test_missing_file_uses_environment_only_when_explicitly_allowed(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(probe.PostgresProbeError, match="postgres_probe_password_missing"):
        probe.read_postgres_password(
            missing,
            environment={"POSTGRES_PASSWORD": FIXTURE_PASSWORD},
        )
    assert probe.read_postgres_password(
        missing,
        allow_legacy_environment=True,
        environment={"POSTGRES_PASSWORD": FIXTURE_PASSWORD},
    ) == FIXTURE_PASSWORD


@pytest.mark.parametrize(
    ("mode", "output"),
    [
        ("revision", "A\n"),
        ("revision", f"{'a' * 33}\n"),
        ("revision", f"{'a' * 1025}\n"),
        ("snapshot", "A\n2\n5\n2\n0\n0\n"),
    ],
)
def test_probe_rejects_invalid_or_unbounded_revision_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    output: str,
) -> None:
    secret = _secret(tmp_path / "postgres_password")
    compose = _compose(tmp_path)
    monkeypatch.setattr(
        probe,
        "_run_bounded",
        lambda command, environment: (0, output.encode(), False),
    )
    with pytest.raises(probe.PostgresProbeError, match="database_revision_probe_failed"):
        probe.run_postgres_probe(compose, mode, password_file=secret)


@pytest.mark.parametrize(
    "count",
    ["\u0662", "+2", "-1", "1" * 20],
)
def test_snapshot_rejects_non_ascii_or_unbounded_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    count: str,
) -> None:
    secret = _secret(tmp_path / "postgres_password")
    compose = _compose(tmp_path)
    output = f"d1e2f3a4b5c6\n{count}\n5\n2\n0\n0\n".encode()
    monkeypatch.setattr(
        probe,
        "_run_bounded",
        lambda command, environment: (0, output, False),
    )
    with pytest.raises(probe.PostgresProbeError, match="database_revision_probe_failed"):
        probe.run_postgres_probe(compose, "snapshot", password_file=secret)


def test_bounded_runner_stops_stdout_flood() -> None:
    returncode, output, overflow = probe._run_bounded(
        [sys.executable, "-c", "import sys; sys.stdout.write('x' * 1000000)"],
        os.environ,
        timeout=5,
    )
    assert returncode != 0
    assert overflow is True
    assert len(output) == probe.MAX_RESULT_BYTES + 1


@pytest.mark.parametrize(
    "taskkill_result",
    [subprocess.CompletedProcess([], 1), subprocess.TimeoutExpired([], 5)],
)
def test_windows_tree_termination_falls_back_to_bounded_leader_kill(
    monkeypatch: pytest.MonkeyPatch,
    taskkill_result: object,
) -> None:
    class Process:
        pid = 12345

        def __init__(self) -> None:
            self.killed = False
            self.waits: list[int] = []

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout: int) -> int:
            self.waits.append(timeout)
            return 0

    def taskkill(*args, **kwargs):
        if isinstance(taskkill_result, Exception):
            raise taskkill_result
        return taskkill_result

    process = Process()
    monkeypatch.setattr(probe.subprocess, "run", taskkill)
    probe._terminate_windows_process_tree(process)
    assert process.killed is True
    assert process.waits == [5]


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@pytest.mark.parametrize("failure_mode", ["timeout", "overflow"])
def test_bounded_runner_terminates_descendants(
    tmp_path: Path,
    failure_mode: str,
) -> None:
    pid_file = tmp_path / "descendant.pid"
    parent_code = (
        "import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c',"
        "'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)']);"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid));"
        + ("sys.stdout.write('x'*1000000);sys.stdout.flush();" if failure_mode == "overflow" else "")
        + "time.sleep(60)"
    )
    command = [sys.executable, "-c", parent_code, str(pid_file)]
    if failure_mode == "timeout":
        with pytest.raises(subprocess.TimeoutExpired):
            probe._run_bounded(command, os.environ, timeout=0.5)
    else:
        _, _, overflow = probe._run_bounded(command, os.environ, timeout=5)
        assert overflow is True
    descendant_pid = int(pid_file.read_text(encoding="utf-8"))
    for _ in range(50):
        if not _process_exists(descendant_pid):
            break
        time.sleep(0.02)
    assert not _process_exists(descendant_pid)


def test_all_production_psql_calls_use_the_exact_helper() -> None:
    repository = SCRIPT.parents[1]
    transition = (repository / "scripts" / "current_vps_prelaunch_transition.py").read_text(
        encoding="utf-8"
    )
    deploy = (repository / "deploy.sh").read_text(encoding="utf-8")
    bundle = (repository / "scripts" / "release_execution_bundle.py").read_text(
        encoding="utf-8"
    )
    assert "psql" not in transition
    assert "psql" not in deploy
    assert '"scripts/postgres_probe.py"' in bundle
    assert 'python3 "$POSTGRES_PROBE_HELPER" revision' in deploy
    assert 'str(REPO_ROOT / "scripts" / "postgres_probe.py")' in transition


def test_helper_never_creates_pgpass_or_inspects_container_secrets() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert ".pgpass" not in source
    assert "docker inspect" not in source
    assert "POSTGRES_PASSWORD=" not in source
    assert "set -x" not in source
