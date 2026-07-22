"""Managed, secret-safe P7B rollout tooling for the production host.

The command is deliberately dependency-free.  Its mutating operations are intended
for the approved production host only; tests inject a runner and never contact it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterator, Sequence

SHA = re.compile(r"[0-9a-f]{40}\Z")
OWNERSHIP_MARKER = "# Managed by NURA P7B rollout tooling; do not edit."
APP_SERVICES = ("api", "bot", "celery-worker", "celery-beat", "admin-bot")
STAGE1_SERVICES = ("redis", *APP_SERVICES)
OPERATIONS = (
    "status", "preflight", "plan-stage1", "stage1", "verify-stage1",
    "plan-stage2", "stage2", "verify-stage2", "rollback-stage1",
    "rollback-stage2", "cleanup",
)
@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""


Runner = Callable[[Sequence[str]], int | CommandResult]


def fail(message: str) -> None:
    raise SystemExit(f"p7b: {message}")


def require_sha(value: str) -> str:
    if not SHA.fullmatch(value):
        fail("exact_sha_required")
    return value


def atomic_write(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            os.chmod(path, mode)
        temporary = ""
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def edit_environment(path: Path, backup: Path, updates: dict[str, str]) -> None:
    """Back up and atomically change only whitelisted environment keys."""
    if set(updates) - {"APP_ENV", "TEST_MODE"}:
        fail("environment_update_not_permitted")
    source = path.read_bytes()
    seen: set[str] = set()
    output: list[bytes] = []
    for line in source.splitlines(keepends=True):
        raw_key = line.split(b"=", 1)[0]
        key = raw_key.decode("ascii", "ignore")
        if key in updates:
            if key in seen:
                fail(f"duplicate_environment_key:{key}")
            seen.add(key)
            output.append(f"{key}={updates[key]}\n".encode())
        else:
            output.append(line)
    # Duplicate keys are rejected above before creating a backup or replacing the source.
    atomic_write(backup, source)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}\n".encode())
    atomic_write(path, b"".join(output), stat.S_IMODE(path.stat().st_mode))


def environment_values(path: Path) -> dict[str, str]:
    """Read only the two permitted values; never expose the full environment."""
    values: dict[str, str] = {}
    for line in path.read_bytes().splitlines():
        key, separator, value = line.partition(b"=")
        decoded = key.decode("ascii", "ignore")
        if separator and decoded in {"APP_ENV", "TEST_MODE"}:
            if decoded in values:
                fail(f"duplicate_environment_key:{decoded}")
            values[decoded] = value.decode("ascii", "strict")
    return values


def require_environment(path: Path, expected: dict[str, str]) -> None:
    if environment_values(path) != expected:
        fail("environment_contract_failed")


@dataclass(frozen=True)
class ReleaseContext:
    sha: str
    project: str
    working_directory: str
    compose_files: tuple[str, ...]
    generated_file: str


@dataclass
class RolloutState:
    current: ReleaseContext | None = None
    previous: ReleaseContext | None = None
    stage1_verified: bool = False
    stage2_verified: bool = False

    @classmethod
    def load(cls, path: Path) -> "RolloutState":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        def context(key: str) -> ReleaseContext | None:
            value = data.get(key)
            return ReleaseContext(**{**value, "compose_files": tuple(value["compose_files"])}) if value else None
        return cls(context("current"), context("previous"), bool(data.get("stage1_verified")), bool(data.get("stage2_verified")))

    def save(self, path: Path) -> None:
        payload = {
            "current": asdict(self.current) if self.current else None,
            "previous": asdict(self.previous) if self.previous else None,
            "stage1_verified": self.stage1_verified,
            "stage2_verified": self.stage2_verified,
        }
        atomic_write(path, json.dumps(payload, sort_keys=True, indent=2).encode() + b"\n")


@dataclass(frozen=True)
class Settings:
    sha: str
    project: str
    working_directory: Path
    base_compose: Path
    state_directory: Path
    environment_file: Path

    @property
    def state_file(self) -> Path:
        return self.state_directory / "rollout-state.json"

    @property
    def lock_file(self) -> Path:
        return self.state_directory / "rollout.lock"

    @property
    def generated_directory(self) -> Path:
        return self.working_directory / ".p7b"

    def context(self, sha: str | None = None) -> ReleaseContext:
        release = require_sha(sha or self.sha)
        generated = self.generated_directory / f"compose.p7b.{release}.yml"
        return ReleaseContext(release, self.project, str(self.working_directory),
                              (str(self.base_compose), str(generated)), str(generated))


@contextmanager
def rollout_lock(path: Path) -> Iterator[None]:
    """Use an exclusive lock file; the operation is refused rather than waiting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        fail("rollout_locked")
    try:
        os.write(descriptor, str(os.getpid()).encode())
        yield
    finally:
        os.close(descriptor)
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def generated_compose(context: ReleaseContext) -> bytes:
    return (f"{OWNERSHIP_MARKER}\n# exact-release-sha: {context.sha}\n"
            "services:\n  api:\n    labels:\n      nura.release.sha: "
            f"{context.sha}\n").encode()


def ensure_generated(context: ReleaseContext) -> None:
    path = Path(context.generated_file)
    if not path.exists():
        atomic_write(path, generated_compose(context))
        return
    if OWNERSHIP_MARKER not in path.read_text(encoding="utf-8", errors="replace"):
        fail("generated_file_not_owned")


def compose_command(context: ReleaseContext, *arguments: str) -> list[str]:
    command = ["docker", "compose", "--project-name", context.project,
               "--project-directory", context.working_directory]
    for compose_file in context.compose_files:
        command.extend(("--file", compose_file))
    return [*command, *arguments]


def default_runner(command: Sequence[str]) -> CommandResult:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    return CommandResult(completed.returncode, completed.stdout)


def command_result(runner: Runner, command: Sequence[str]) -> CommandResult:
    result = runner(command)
    return result if isinstance(result, CommandResult) else CommandResult(result)


def run_or_fail(runner: Runner, command: Sequence[str], check: str) -> None:
    if command_result(runner, command).returncode != 0:
        fail(f"verification_failed:{check}")


def verify_release(settings: Settings, runner: Runner) -> None:
    """Fail closed unless the supplied checkout is exactly the approved commit."""
    run_or_fail(runner, ("git", "-C", str(settings.working_directory), "diff", "--quiet", settings.sha, "HEAD"), "exact_release_sha")
    run_or_fail(runner, ("git", "-C", str(settings.working_directory), "diff", "--quiet"), "dirty_worktree")
    run_or_fail(runner, ("git", "-C", str(settings.working_directory), "diff", "--cached", "--quiet"), "dirty_index")
    untracked = command_result(runner, ("git", "-C", str(settings.working_directory), "ls-files", "--others", "--exclude-standard"))
    if untracked.returncode != 0 or untracked.stdout.strip():
        fail("untracked_worktree")


def lifecycle(context: ReleaseContext, services: Sequence[str], runner: Runner) -> None:
    run_or_fail(runner, compose_command(context, "up", "--detach", "--force-recreate", *services), "compose_up")


def verification_commands(context: ReleaseContext, stage: int) -> list[list[str]]:
    # Commands carry no credential values; authentication is validated inside containers.
    commands = [
        compose_command(context, "ps", "--format", "json"),
        compose_command(context, "exec", "-T", "redis", "/usr/local/bin/nura-redis-healthcheck"),
        compose_command(context, "exec", "-T", "postgres", "pg_isready"),
        compose_command(context, "exec", "-T", "api", "python", "-c", "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200"),
        compose_command(context, "exec", "-T", "celery-worker", "celery", "inspect", "ping"),
    ]
    if stage == 2:
        commands.append(compose_command(context, "exec", "-T", "api", "python", "-c", "import sys; sys.exit(0)"))
    return commands


def parse_compose_status(output: str, services: Sequence[str]) -> None:
    """Require every expected service to be explicitly running and healthy."""
    try:
        records = json.loads(output) if output.lstrip().startswith("[") else [json.loads(line) for line in output.splitlines() if line]
    except json.JSONDecodeError:
        fail("compose_status_unparseable")
    status = {str(item.get("Service", item.get("Name", ""))): item for item in records}
    for service in services:
        item = status.get(service)
        if item is None or item.get("State") != "running" or item.get("Health") != "healthy":
            fail(f"service_unhealthy:{service}")


def verify(settings: Settings, stage: int, runner: Runner, acquire_lock: bool = True) -> None:
    if acquire_lock:
        with rollout_lock(settings.lock_file):
            verify(settings, stage, runner, acquire_lock=False)
        return
    state = RolloutState.load(settings.state_file)
    context = state.current
    if context is None:
        fail("release_context_missing")
    if stage == 2 and not state.stage1_verified:
        fail("stage1_verification_required")
    require_environment(settings.environment_file, {"APP_ENV": "development", "TEST_MODE": "true"} if stage == 1 else {"APP_ENV": "production", "TEST_MODE": "false"})
    commands = verification_commands(context, stage)
    status = command_result(runner, commands[0])
    if status.returncode != 0:
        fail(f"verification_failed:stage{stage}_compose_status")
    parse_compose_status(status.stdout, ("redis", "postgres", *APP_SERVICES))
    for command in commands[1:]:
        run_or_fail(runner, command, f"stage{stage}")
    if stage == 1:
        state.stage1_verified = True
        state.stage2_verified = False
    else:
        state.stage2_verified = True
    state.save(settings.state_file)
    print(f"p7b_verify_stage{stage} status=ok secrets=redacted")


def plan(settings: Settings, stage: int) -> None:
    context = settings.context()
    services = STAGE1_SERVICES if stage == 1 else APP_SERVICES
    print("p7b_plan " + json.dumps({"stage": stage, "sha": context.sha, "project": context.project,
                                     "working_directory": context.working_directory, "services": services,
                                     "secrets": "redacted"}, sort_keys=True))


def stage1(settings: Settings, runner: Runner) -> None:
    with rollout_lock(settings.lock_file):
        verify_release(settings, runner)
        state = RolloutState.load(settings.state_file)
        context = settings.context()
        ensure_generated(context)
        state.previous = state.current
        state.current = context
        state.stage1_verified = False
        state.stage2_verified = False
        state.save(settings.state_file)
        lifecycle(context, STAGE1_SERVICES, runner)
        verify(settings, 1, runner, acquire_lock=False)


def stage2(settings: Settings, runner: Runner) -> None:
    with rollout_lock(settings.lock_file):
        state = RolloutState.load(settings.state_file)
        if not state.stage1_verified:
            fail("stage1_verification_required")
        backup = settings.state_directory / f"environment-{state.current.sha}.backup" if state.current else None
        if backup is None:
            fail("release_context_missing")
        if not backup.exists():
            edit_environment(settings.environment_file, backup, {"APP_ENV": "production", "TEST_MODE": "false"})
        else:
            require_environment(settings.environment_file, {"APP_ENV": "production", "TEST_MODE": "false"})
        lifecycle(state.current, APP_SERVICES, runner)
        verify(settings, 2, runner, acquire_lock=False)


def rollback_stage1(settings: Settings, runner: Runner) -> None:
    with rollout_lock(settings.lock_file):
        state = RolloutState.load(settings.state_file)
        if state.previous is None:
            fail("previous_release_context_missing")
        ensure_generated(state.previous)
        state.current, state.previous = state.previous, state.current
        state.stage1_verified = False
        state.stage2_verified = False
        state.save(settings.state_file)
        lifecycle(state.current, STAGE1_SERVICES, runner)


def rollback_stage2(settings: Settings, runner: Runner) -> None:
    with rollout_lock(settings.lock_file):
        state = RolloutState.load(settings.state_file)
        if state.current is None:
            fail("release_context_missing")
        backup = settings.state_directory / f"environment-{state.current.sha}.backup"
        if not backup.is_file():
            fail("environment_backup_missing")
        atomic_write(settings.environment_file, backup.read_bytes(), stat.S_IMODE(backup.stat().st_mode))
        lifecycle(state.current, APP_SERVICES, runner)


def cleanup(settings: Settings) -> None:
    state = RolloutState.load(settings.state_file)
    protected = {value.generated_file for value in (state.current, state.previous) if value}
    if not settings.generated_directory.exists():
        print("p7b_cleanup removed=0 secrets=redacted")
        return
    removed = 0
    for candidate in settings.generated_directory.glob("compose.p7b.*.yml"):
        if str(candidate) in protected:
            continue
        if OWNERSHIP_MARKER in candidate.read_text(encoding="utf-8", errors="replace"):
            candidate.unlink()
            removed += 1
    print(f"p7b_cleanup removed={removed} secrets=redacted")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("operation", choices=OPERATIONS)
    result.add_argument("--sha", required=True, type=require_sha)
    result.add_argument("--project", default="nura_app")
    result.add_argument("--working-directory", type=Path, default=Path("/opt/nura/nura_app"))
    result.add_argument("--base-compose", type=Path, default=Path("/opt/nura/nura_app/docker-compose.yml"))
    result.add_argument("--env-file", type=Path, default=Path("/opt/nura/nura_app/.env"))
    result.add_argument("--state-dir", type=Path, default=Path("/var/lib/nura-release-state/p7b"))
    return result


def main(argv: Sequence[str] | None = None, runner: Runner = default_runner) -> None:
    args = parser().parse_args(argv)
    settings = Settings(args.sha, args.project, args.working_directory, args.base_compose, args.state_dir, args.env_file)
    if args.operation == "status":
        state = RolloutState.load(settings.state_file)
        print("p7b_status " + json.dumps({"current": state.current.sha if state.current else None,
                                            "stage1_verified": state.stage1_verified,
                                            "stage2_verified": state.stage2_verified, "secrets": "redacted"}, sort_keys=True))
    elif args.operation == "preflight":
        verify_release(settings, runner)
        run_or_fail(runner, compose_command(settings.context(), "config", "--quiet"), "compose_config")
        print(f"p7b_preflight sha={settings.sha} project={settings.project} status=ok secrets=redacted")
    elif args.operation.startswith("plan-"):
        plan(settings, 1 if args.operation.endswith("stage1") else 2)
    elif args.operation == "stage1":
        stage1(settings, runner)
    elif args.operation == "verify-stage1":
        verify(settings, 1, runner)
    elif args.operation == "stage2":
        stage2(settings, runner)
    elif args.operation == "verify-stage2":
        verify(settings, 2, runner)
    elif args.operation == "rollback-stage1":
        rollback_stage1(settings, runner)
    elif args.operation == "rollback-stage2":
        rollback_stage2(settings, runner)
    else:
        cleanup(settings)


if __name__ == "__main__":
    main()
