"""Persistent State B handoff and managed P7B activation.

The module is dependency-free so the reviewed target revision can run it on the
production host.  Manifests never contain environment contents or command-line
credentials.  Every mutating command is serialized by the same persistent lock.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover - production hosts are Linux
    fcntl = None  # type: ignore[assignment]
try:
    import msvcrt
except ImportError:  # pragma: no cover - Windows-only test fallback
    msvcrt = None  # type: ignore[assignment]

SHA = re.compile(r"[0-9a-f]{40}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()
APP_SERVICES = ("api", "bot", "celery-worker", "celery-beat", "admin-bot")
STAGE1_SERVICES = ("redis", *APP_SERVICES)
DATA_SERVICES = ("postgres", "redis")
HEALTH_SERVICES = ("postgres", "redis", "api")
REDIS_HEALTHCHECK_ATTEMPTS = 6
REDIS_HEALTHCHECK_DELAY_SECONDS = 5
REDIS_HEALTHCHECK_TIMEOUT_SECONDS = 5
CELERY_PING_ATTEMPTS = 6
CELERY_PING_DELAY_SECONDS = 5
CELERY_PING_TIMEOUT_SECONDS = 5
CELERY_PING_OUTER_TIMEOUT_SECONDS = 45
SCHEMA = 1
KINDS = {"handoff", "baseline", "transaction", "receipt"}
PHASES = {
    "prepared",
    "baseline_ready",
    "stage1_intent",
    "stage1_verified",
    "stage1_compensated",
    "stage2_intent",
    "stage2_verified",
    "stage2_compensated",
    "smoke_verified",
    "finalizing",
    "complete",
}
OPERATIONS = (
    "status",
    "prepare-handoff",
    "bootstrap",
    "preflight",
    "plan-stage1",
    "stage1",
    "verify-stage1",
    "plan-stage2",
    "stage2",
    "verify-stage2",
    "readiness",
    "activate",
    "finalize",
    "recover",
)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[Sequence[str]], int | CommandResult]


def fail(message: str) -> None:
    raise SystemExit(f"p7b: {message}")


def require_sha(value: str) -> str:
    if not SHA.fullmatch(value):
        fail("exact_sha_required")
    return value


def require_digest(value: str, label: str = "digest") -> str:
    if not DIGEST.fullmatch(value):
        fail(f"invalid_{label}")
    return value


def require_image_id(value: str) -> str:
    if not IMAGE_ID.fullmatch(value):
        fail("immutable_image_id_required")
    return value


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def payload_digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def atomic_write(
    path: Path,
    content: bytes,
    mode: int = 0o600,
    owner_from: Path | None = None,
) -> None:
    if path.exists() and path.is_symlink():
        fail("unsafe_output_path")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink():
        fail("unsafe_output_directory")
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, mode)
        if owner_from is not None and os.name != "nt":
            source_stat = owner_from.stat()
            os.fchown(descriptor, source_stat.st_uid, source_stat.st_gid)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            os.chmod(path, mode)
            directory = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        temporary = ""
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def write_record(path: Path, kind: str, payload: Mapping[str, object]) -> str:
    if kind not in KINDS:
        fail("unknown_record_kind")
    digest = payload_digest(payload)
    envelope = {"schema": SCHEMA, "kind": kind, "digest": digest, "payload": payload}
    atomic_write(path, canonical_json(envelope) + b"\n")
    return digest


def read_record(path: Path, kind: str) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        fail(f"{kind}_missing_or_unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        fail(f"{kind}_unreadable")
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "kind", "digest", "payload"}
        or value.get("schema") != SCHEMA
        or value.get("kind") != kind
        or not isinstance(value.get("payload"), dict)
        or not isinstance(value.get("digest"), str)
    ):
        fail(f"{kind}_schema_invalid")
    payload = value["payload"]
    assert isinstance(payload, dict)
    if payload_digest(payload) != value["digest"]:
        fail(f"{kind}_integrity_failed")
    return payload


def safe_existing_file(path: Path, root: Path, label: str) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        fail(f"unsafe_{label}_path")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        fail(f"unsafe_{label}_path")
    return resolved


def compose_digest(path: Path, root: Path, label: str) -> str:
    resolved = safe_existing_file(path, root, label)
    content = resolved.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if not content.strip() or digest == EMPTY_DIGEST:
        fail(f"{label}_empty")
    return digest


def preflight_managed_compose(
    path: Path,
    content: bytes,
    state_directory: Path,
    *,
    allow_empty_recovery: bool,
) -> bool:
    expected_parent = state_directory / "compose"
    expected_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (
        expected_parent.is_symlink()
        or path.parent != expected_parent
        or path.is_symlink()
        or not content.strip()
    ):
        fail("unsafe_compose_materialization")
    if not path.exists():
        return True
    if not path.is_file():
        fail("unsafe_compose_materialization")
    metadata = path.stat()
    state_owner = state_directory.stat().st_uid if os.name != "nt" else None
    if os.name != "nt" and metadata.st_uid != state_owner:
        fail("unsafe_compose_materialization")
    existing = path.read_bytes()
    if existing:
        if existing != content:
            fail("existing_compose_material_conflict")
        return False
    if not allow_empty_recovery:
        fail("unexpected_empty_compose_material")
    return True


def materialize_managed_compose(
    path: Path,
    content: bytes,
    state_directory: Path,
    *,
    replace: bool,
) -> str:
    if replace:
        atomic_write(path, content, owner_from=state_directory)
    return compose_digest(path, state_directory, "compose_material")


def safe_existing_directory(path: Path, label: str) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        fail(f"unsafe_{label}_path")
    return path.resolve(strict=True)


def exact_release_path(settings: "Settings", path: Path, sha: str) -> Path:
    root = safe_existing_directory(settings.releases_directory, "releases_root")
    expected = root / require_sha(sha)
    resolved = safe_existing_directory(path, "release")
    if path.parent.is_symlink() or resolved != expected.resolve(strict=True):
        fail("release_path_outside_root")
    return resolved


@dataclass(frozen=True)
class Settings:
    sha: str
    project: str
    working_directory: Path
    base_compose: Path
    state_directory: Path
    environment_file: Path
    canonical_state: Path = Path("/var/lib/nura-release-state/current.json")
    previous_state: Path = Path("/var/lib/nura-release-state/previous.json")
    current_link: Path = Path("/var/www/nura-releases/current")
    releases_directory: Path = Path("/var/www/nura-releases/releases")
    common_lock_file: Path = Path("/run/lock/nura-deploy.lock")

    @property
    def lock_file(self) -> Path:
        return self.state_directory / "rollout.lock"

    @property
    def handoff_file(self) -> Path:
        return self.state_directory / "handoffs" / f"{self.sha}.json"

    @property
    def baseline_file(self) -> Path:
        return self.state_directory / "baselines" / f"{self.sha}.json"

    @property
    def transaction_file(self) -> Path:
        return self.state_directory / "transactions" / f"{self.sha}.json"

    @property
    def receipt_file(self) -> Path:
        return self.state_directory / "receipts" / f"{self.sha}.json"

    @property
    def target_compose(self) -> Path:
        return self.state_directory / "compose" / f"target-{self.sha}.yml"

    @property
    def target_override(self) -> Path:
        return self.state_directory / "compose" / f"target-images-{self.sha}.yml"

    def baseline_compose(self, sha: str) -> Path:
        return self.state_directory / "compose" / f"baseline-{require_sha(sha)}.yml"

    def baseline_override(self, sha: str) -> Path:
        return self.state_directory / "compose" / f"baseline-images-{require_sha(sha)}.yml"

    @property
    def environment_backup(self) -> Path:
        return self.state_directory / "environment" / f"{self.sha}.backup"

    @property
    def release_state_file(self) -> Path:
        return self.canonical_state.parent / "releases" / f"{self.sha}.json"


def secure_lock_directory(path: Path) -> None:
    """Create or validate the private P7B lock directory without relaxing path checks."""
    if not path.is_absolute() or path.is_symlink():
        fail("unsafe_lock_directory")
    if path == Path("/run/lock"):
        metadata = path.stat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o1777
        ):
            fail("unsafe_lock_directory")
        return
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        fail("unsafe_lock_parent")
    parent_metadata = parent.stat()
    if not stat.S_ISDIR(parent_metadata.st_mode):
        fail("unsafe_lock_parent")
    if os.name != "nt" and (
        (stat.S_IMODE(parent_metadata.st_mode) & 0o022)
        or parent_metadata.st_uid != os.geteuid()
    ):
        fail("unsafe_lock_parent")
    if not path.exists():
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    if path.is_symlink() or not path.is_dir():
        fail("unsafe_lock_directory")
    metadata = path.stat()
    if not stat.S_ISDIR(metadata.st_mode):
        fail("unsafe_lock_directory")
    if os.name != "nt" and (
        stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.geteuid()
    ):
        fail("unsafe_lock_directory")


@contextmanager
def rollout_lock(path: Path) -> Iterator[None]:
    secure_lock_directory(path.parent)
    if path.is_symlink():
        fail("unsafe_lock_file")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        fail("unsafe_lock_file")
    acquired = False
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            fail("unsafe_lock_file")
        if os.name != "nt" and (
            (stat.S_IMODE(metadata.st_mode) & 0o022)
            or metadata.st_uid != os.geteuid()
        ):
            fail("unsafe_lock_file")
        if fcntl is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fail("rollout_locked")
            acquired = True
        elif msvcrt is not None:  # pragma: no cover
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError:
                fail("rollout_locked")
            acquired = True
        else:  # pragma: no cover
            fail("advisory_lock_unavailable")
        yield
    finally:
        if acquired and fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        elif acquired and msvcrt is not None:  # pragma: no cover
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        os.close(descriptor)


def default_runner(command: Sequence[str]) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired):
        return CommandResult(124, stderr="command_timeout")
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def command_result(runner: Runner, command: Sequence[str]) -> CommandResult:
    result = runner(command)
    return result if isinstance(result, CommandResult) else CommandResult(result)


def run_or_fail(runner: Runner, command: Sequence[str], check: str) -> str:
    result = command_result(runner, command)
    if result.returncode != 0:
        fail(f"verification_failed:{check}")
    return result.stdout


def require_environment(path: Path, expected: Mapping[str, str]) -> None:
    if path.is_symlink() or not path.is_file():
        fail("unsafe_environment_path")
    values: dict[str, str] = {}
    for line in path.read_bytes().splitlines():
        key, separator, value = line.partition(b"=")
        decoded = key.decode("ascii", "ignore")
        if separator and decoded in expected:
            if decoded in values:
                fail(f"duplicate_environment_key:{decoded}")
            values[decoded] = value.decode("ascii", "strict")
    if values != dict(expected):
        fail("environment_contract_failed")


def edit_environment(path: Path, backup: Path, updates: Mapping[str, str]) -> None:
    if set(updates) != {"APP_ENV", "TEST_MODE"}:
        fail("environment_update_not_permitted")
    if path.is_symlink() or not path.is_file() or backup.is_symlink():
        fail("unsafe_environment_path")
    source = path.read_bytes()
    source_mode = stat.S_IMODE(path.stat().st_mode)
    lines = source.splitlines(keepends=True)
    seen: set[str] = set()
    output: list[bytes] = []
    for line in lines:
        key = line.partition(b"=")[0].decode("ascii", "ignore")
        if key in updates:
            if key in seen:
                fail(f"duplicate_environment_key:{key}")
            seen.add(key)
            newline = b"\r\n" if line.endswith(b"\r\n") else b"\n"
            output.append(f"{key}={updates[key]}".encode() + newline)
        else:
            output.append(line)
    if not backup.exists():
        atomic_write(backup, source, source_mode, owner_from=path)
    elif backup.read_bytes() != source:
        fail("environment_backup_conflict")
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}\n".encode())
    atomic_write(path, b"".join(output), source_mode, owner_from=path)


def restore_environment(settings: Settings) -> None:
    backup = settings.environment_backup
    if not backup.is_file() or backup.is_symlink():
        fail("environment_backup_missing")
    atomic_write(
        settings.environment_file,
        backup.read_bytes(),
        stat.S_IMODE(backup.stat().st_mode),
        owner_from=backup,
    )


def compose_command(
    project: str,
    working_directory: str,
    compose_files: Sequence[str],
    *arguments: str,
) -> list[str]:
    command = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--project-directory",
        working_directory,
    ]
    for compose_file in compose_files:
        command.extend(("--file", compose_file))
    return [*command, *arguments]


def parse_compose_status(
    output: str,
    services: Sequence[str],
    health_services: Sequence[str],
) -> None:
    try:
        records = (
            json.loads(output)
            if output.lstrip().startswith("[")
            else [json.loads(line) for line in output.splitlines() if line]
        )
    except json.JSONDecodeError:
        fail("compose_status_unparseable")
    if not isinstance(records, list):
        fail("compose_status_unparseable")
    status: dict[str, dict[str, object]] = {}
    for item in records:
        if not isinstance(item, dict):
            fail("compose_status_unparseable")
        service = str(item.get("Service", item.get("Name", "")))
        if not service or service in status:
            fail("compose_status_unparseable")
        status[service] = item
    for service in services:
        item = status.get(service)
        if item is None or item.get("State") != "running":
            fail(f"service_unhealthy:{service}")
        if service in health_services and item.get("Health") != "healthy":
            fail(f"service_unhealthy:{service}")


def materialized_override(image_mapping: Mapping[str, str]) -> bytes:
    if set(image_mapping) != set(APP_SERVICES):
        fail("image_mapping_invalid")
    lines = ["# Managed by NURA P7B; persistent rollback material.", "services:"]
    for service in APP_SERVICES:
        image = image_mapping[service]
        if not IMAGE_ID.fullmatch(image) and not re.fullmatch(
            r"nura-release:[0-9a-f]{40}", image
        ):
            fail("mutable_image_reference")
        lines.extend(
            (
                f"  {service}:",
                f"    image: {image}",
                "    secrets:",
                "      - source: redis_password",
                "        target: redis_password",
                "        mode: 0444",
                "    environment:",
                '      REDIS_PASSWORD: ""',
                "      REDIS_PASSWORD_FILE: /run/secrets/redis_password",
                "      REDIS_URL: redis://redis:6379/0",
                '      CELERY_BROKER_URL: ""',
                '      CELERY_RESULT_BACKEND: ""',
                "      NURA_CELERY_BROKER_URL: redis://redis:6379/1",
                "      NURA_CELERY_RESULT_BACKEND: redis://redis:6379/2",
            )
        )
        if service == "api":
            lines.append('      RUN_MIGRATIONS: "0"')
    return ("\n".join(lines) + "\n").encode()


def verify_secret_file_compose_contract(handoff: Mapping[str, object]) -> None:
    """Reject incomplete application secret transport before Stage 1 mutation."""

    files = handoff.get("compose_files")
    if not isinstance(files, list) or not files:
        fail("application_secret_mount_missing")
    content = "\n".join(Path(str(item)).read_text(encoding="utf-8") for item in files)
    required = (
        "secrets:",
        "redis_password:",
        "source: redis_password",
        "target: redis_password",
        "REDIS_PASSWORD_FILE: /run/secrets/redis_password",
        'REDIS_PASSWORD: ""',
        'CELERY_BROKER_URL: ""',
        'CELERY_RESULT_BACKEND: ""',
    )
    if any(item not in content for item in required):
        fail("application_secret_mount_missing")
    for service in APP_SERVICES:
        if f"  {service}:" not in content:
            fail("application_secret_mount_missing")


def transaction(settings: Settings, phase: str, **updates: object) -> dict[str, object]:
    if phase not in PHASES:
        fail("invalid_transaction_phase")
    existing: dict[str, object] = {}
    if settings.transaction_file.exists():
        existing = read_record(settings.transaction_file, "transaction")
        if existing.get("target_sha") != settings.sha:
            fail("transaction_target_mismatch")
    existing.update(
        {
            "target_sha": settings.sha,
            "phase": phase,
            "compensation_owner": "p7b",
            "updated_at": int(time.time()),
            **updates,
        }
    )
    write_record(settings.transaction_file, "transaction", existing)
    return existing


def load_release_state(path: Path, label: str) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        fail(f"{label}_state_missing_or_unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        fail(f"{label}_state_unreadable")
    if not isinstance(value, dict):
        fail(f"{label}_state_invalid")
    sha = value.get("sha")
    if not isinstance(sha, str):
        fail(f"{label}_state_invalid")
    require_sha(sha)
    if value.get("status") != "successful":
        fail(f"{label}_state_not_successful")
    return value


def load_staged_release_state(
    settings: Settings,
    release: Path,
    expected_baseline: str,
    artifact_digest: str,
    manifest_digest: str,
    image_id: str,
) -> dict[str, object]:
    path = settings.release_state_file
    root = settings.canonical_state.parent / "releases"
    if path.parent != root or root.is_symlink() or not root.is_dir():
        fail("prepared_release_state_path_invalid")
    resolved = safe_existing_file(path, root, "prepared_release_state")
    metadata = resolved.stat()
    if os.name != "nt" and metadata.st_uid != root.stat().st_uid:
        fail("prepared_release_state_owner_invalid")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        fail("prepared_release_state_invalid")
    services = set(APP_SERVICES)
    image_tag = f"nura-release:{settings.sha}"
    immutable: dict[str, object] = {
        "schema": 2,
        "sha": settings.sha,
        "status": "staged",
        "static_release_path": str(release),
        "artifact_sha256": artifact_digest,
        "public_manifest_sha256": manifest_digest,
        "application_image_tag": image_tag,
        "application_image_id": image_id,
        "oci_revision": settings.sha,
        "oci_source": "https://github.com/usoltvas870/NURA",
        "migration_delta": False,
        "previous_successful_sha": expected_baseline,
        "rollback_eligibility": False,
        "compensation_verified": False,
        "failure_stage": None,
        "failure_reason": None,
    }
    if not isinstance(value, dict) or any(
        value.get(key) != expected for key, expected in immutable.items()
    ):
        fail("prepared_release_state_mismatch")
    created = value.get("oci_created")
    history = value.get("activation_history")
    mappings = value.get("per_service_image_mapping")
    ids = value.get("per_service_image_ids")
    if (
        not isinstance(created, str)
        or not created
        or not isinstance(history, list)
        or not history
        or len(history) > 2
        or len(history) != len(set(history))
        or history[0] != expected_baseline
        or any(
            not isinstance(item, str)
            or SHA.fullmatch(item) is None
            or item == settings.sha
            for item in history
        )
        or not isinstance(mappings, dict)
        or set(mappings) != services
        or any(value != image_tag for value in mappings.values())
        or not isinstance(ids, dict)
        or set(ids) != services
        or any(value != image_id for value in ids.values())
    ):
        fail("prepared_release_state_mismatch")
    return value


def load_canonical(settings: Settings) -> dict[str, object]:
    return load_release_state(settings.canonical_state, "canonical")


def verify_release_checkout(settings: Settings, runner: Runner) -> None:
    working = safe_existing_directory(settings.working_directory, "working_directory")
    revision = run_or_fail(
        runner,
        ("git", "-C", str(working.parent), "rev-parse", "--verify", "HEAD"),
        "exact_release_sha",
    )
    if revision.strip() != settings.sha:
        fail("verification_failed:exact_release_sha")
    run_or_fail(
        runner,
        ("git", "-C", str(working.parent), "diff", "--quiet"),
        "dirty_worktree",
    )
    run_or_fail(
        runner,
        ("git", "-C", str(working.parent), "diff", "--cached", "--quiet"),
        "dirty_index",
    )
    untracked = run_or_fail(
        runner,
        (
            "git",
            "-C",
            str(working.parent),
            "ls-files",
            "--others",
            "--exclude-standard",
        ),
        "untracked_worktree",
    )
    if untracked.strip():
        fail("untracked_worktree")


def validate_handoff(settings: Settings, runner: Runner) -> dict[str, object]:
    handoff = read_record(settings.handoff_file, "handoff")
    required = {
        "target_sha",
        "expected_baseline_sha",
        "release_path",
        "artifact_sha256",
        "manifest_sha256",
        "image_mapping",
        "image_ids",
        "compose_project",
        "working_directory",
        "compose_files",
        "compose_digests",
        "volumes",
    }
    if set(handoff) != required or handoff.get("target_sha") != settings.sha:
        fail("handoff_schema_invalid")
    expected = handoff.get("expected_baseline_sha")
    if not isinstance(expected, str):
        fail("handoff_schema_invalid")
    require_sha(expected)
    for key in ("artifact_sha256", "manifest_sha256"):
        value = handoff.get(key)
        if not isinstance(value, str):
            fail("handoff_schema_invalid")
        require_digest(value, key)
    mapping = handoff.get("image_mapping")
    ids = handoff.get("image_ids")
    if not isinstance(mapping, dict) or not isinstance(ids, dict):
        fail("handoff_schema_invalid")
    if set(mapping) != set(APP_SERVICES) or set(ids) != set(APP_SERVICES):
        fail("handoff_schema_invalid")
    for service in APP_SERVICES:
        image_ref = mapping.get(service)
        image_id = ids.get(service)
        if image_ref != f"nura-release:{settings.sha}" or not isinstance(image_id, str):
            fail("mutable_image_reference")
        require_image_id(image_id)
        actual_id = run_or_fail(
            runner,
            ("docker", "image", "inspect", "--format", "{{.Id}}", image_ref),
            f"target_image:{service}",
        ).strip()
        if actual_id != image_id:
            fail(f"target_image_mismatch:{service}")
    release_path = handoff.get("release_path")
    if not isinstance(release_path, str):
        fail("handoff_schema_invalid")
    exact_release_path(settings, Path(release_path), settings.sha)
    compose_files = handoff.get("compose_files")
    if not isinstance(compose_files, list) or len(compose_files) != 2:
        fail("handoff_schema_invalid")
    compose_digests = handoff.get("compose_digests")
    if not isinstance(compose_digests, list) or len(compose_digests) != len(compose_files):
        fail("handoff_schema_invalid")
    for item, expected_digest in zip(compose_files, compose_digests, strict=True):
        if not isinstance(item, str):
            fail("handoff_schema_invalid")
        if not isinstance(expected_digest, str):
            fail("handoff_schema_invalid")
        require_digest(expected_digest, "compose_digest")
        if expected_digest == EMPTY_DIGEST:
            fail("compose_digest_empty")
        if compose_digest(Path(item), settings.state_directory, "compose") != expected_digest:
            fail("compose_digest_mismatch")
    project = str(handoff["compose_project"])
    working_directory = str(handoff["working_directory"])
    compose_context = [str(item) for item in compose_files]
    run_or_fail(
        runner,
        compose_command(
            project,
            working_directory,
            compose_context,
            "config",
            "--quiet",
        ),
        "handoff_compose",
    )
    volumes = handoff.get("volumes")
    if not isinstance(volumes, dict):
        fail("handoff_schema_invalid")
    config_output = run_or_fail(
        runner,
        compose_command(
            project,
            working_directory,
            compose_context,
            "config",
            "--format",
            "json",
        ),
        "handoff_compose_volumes",
    )
    validate_compose_volume_contract(config_output, project, volumes)
    return handoff


def prepare_handoff(settings: Settings, args: argparse.Namespace) -> None:
    with rollout_lock(settings.lock_file):
        canonical = load_canonical(settings)
        expected = require_sha(args.expected_baseline_sha)
        if canonical.get("sha") != expected or expected == settings.sha:
            fail("canonical_baseline_mismatch")
        release = exact_release_path(settings, args.release_path, settings.sha)
        base_source = safe_existing_file(
            settings.base_compose, settings.working_directory, "base_compose"
        ).read_bytes()
        if not base_source.strip():
            fail("base_compose_empty")
        image_id = require_image_id(args.image_id)
        image_ref = f"nura-release:{settings.sha}"
        actual = run_or_fail(
            args.runner,
            ("docker", "image", "inspect", "--format", "{{.Id}}", image_ref),
            "target_image",
        ).strip()
        if actual != image_id:
            fail("target_image_mismatch")
        mapping = {service: image_ref for service in APP_SERVICES}
        ids = {service: image_id for service in APP_SERVICES}
        override_source = materialized_override(mapping)
        legacy_handoff = {
            "target_sha": settings.sha,
            "expected_baseline_sha": expected,
            "release_path": str(release),
            "artifact_sha256": require_digest(args.artifact_sha256, "artifact_sha256"),
            "manifest_sha256": require_digest(args.manifest_sha256, "manifest_sha256"),
            "image_mapping": mapping,
            "image_ids": ids,
            "compose_project": settings.project,
            "working_directory": str(settings.working_directory.resolve(strict=True)),
            "compose_files": [str(settings.target_compose), str(settings.target_override)],
            "volumes": {
                "redis": args.redis_volume,
                "postgres": args.postgres_volume,
            },
        }
        existing_handoff: dict[str, object] | None = None
        if settings.handoff_file.exists():
            existing_handoff = read_record(settings.handoff_file, "handoff")
            comparable = dict(existing_handoff)
            comparable.pop("compose_digests", None)
            if comparable != legacy_handoff:
                fail("existing_handoff_conflict")
            if not settings.transaction_file.exists():
                fail("handoff_transaction_missing")
            state = read_record(settings.transaction_file, "transaction")
            if state.get("target_sha") != settings.sha or state.get("phase") not in {
                "prepared",
                "baseline_ready",
            }:
                fail("compose_recovery_phase_invalid")
            current_target = settings.current_link.resolve(strict=True)
            canonical_release = canonical.get("static_release_path")
            if (
                not isinstance(canonical_release, str)
                or current_target != Path(canonical_release).resolve(strict=True)
                or current_target == release
            ):
                fail("compose_recovery_active_reference")
            if settings.previous_state.exists():
                previous = load_release_state(settings.previous_state, "previous")
                if previous.get("sha") == settings.sha:
                    fail("compose_recovery_rollback_reference")
            load_staged_release_state(
                settings,
                release,
                expected,
                args.artifact_sha256,
                args.manifest_sha256,
                image_id,
            )
        elif settings.transaction_file.exists():
            fail("transaction_without_handoff")
        expected_compose_digests = [
            hashlib.sha256(base_source).hexdigest(),
            hashlib.sha256(override_source).hexdigest(),
        ]
        if (
            existing_handoff is not None
            and "compose_digests" in existing_handoff
            and existing_handoff["compose_digests"] != expected_compose_digests
        ):
            fail("existing_compose_digest_conflict")
        allow_empty_recovery = existing_handoff is not None
        replace_base = preflight_managed_compose(
            settings.target_compose,
            base_source,
            settings.state_directory,
            allow_empty_recovery=allow_empty_recovery,
        )
        replace_override = preflight_managed_compose(
            settings.target_override,
            override_source,
            settings.state_directory,
            allow_empty_recovery=allow_empty_recovery,
        )
        base_digest = materialize_managed_compose(
            settings.target_compose,
            base_source,
            settings.state_directory,
            replace=replace_base,
        )
        override_digest = materialize_managed_compose(
            settings.target_override,
            override_source,
            settings.state_directory,
            replace=replace_override,
        )
        handoff = {
            **legacy_handoff,
            "compose_digests": [base_digest, override_digest],
        }
        compose_context = [str(settings.target_compose), str(settings.target_override)]
        run_or_fail(
            args.runner,
            compose_command(
                settings.project,
                str(settings.working_directory.resolve(strict=True)),
                compose_context,
                "config",
                "--quiet",
            ),
            "prepared_compose",
        )
        config_output = run_or_fail(
            args.runner,
            compose_command(
                settings.project,
                str(settings.working_directory.resolve(strict=True)),
                compose_context,
                "config",
                "--format",
                "json",
            ),
            "prepared_compose_volumes",
        )
        validate_compose_volume_contract(
            config_output,
            settings.project,
            handoff["volumes"],  # type: ignore[arg-type]
        )
        write_record(settings.handoff_file, "handoff", handoff)
        if existing_handoff is not None:
            print(f"p7b_prepare sha={settings.sha} status=recovered secrets=redacted")
            return
        transaction(settings, "prepared")
        print(f"p7b_prepare sha={settings.sha} status=prepared secrets=redacted")


def service_container(
    runner: Runner,
    project: str,
    working_directory: str,
    compose_files: Sequence[str],
    service: str,
) -> str:
    container = run_or_fail(
        runner,
        compose_command(
            project, working_directory, compose_files, "ps", "-q", "--all", service
        ),
        f"container:{service}",
    ).strip()
    if not container or "\n" in container:
        fail(f"service_missing_or_ambiguous:{service}")
    return container


def inspect_service(
    runner: Runner,
    project: str,
    working_directory: str,
    compose_files: Sequence[str],
    service: str,
) -> dict[str, str]:
    container = service_container(
        runner,
        project,
        working_directory,
        compose_files,
        service,
    )
    inspection = run_or_fail(
        runner,
        (
            "docker",
            "inspect",
            "--format",
            '{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none'
            "{{end}}|{{.Config.Image}}|{{.Image}}|"
            '{{index .Config.Labels "org.opencontainers.image.revision"}}',
            container,
        ),
        f"inspect:{service}",
    ).strip()
    fields = inspection.split("|")
    if len(fields) != 5:
        fail(f"service_inspection_invalid:{service}")
    running, health, image_ref, image_id, revision = fields
    if running != "true" or health == "unhealthy":
        fail(f"service_unhealthy:{service}")
    require_image_id(image_id)
    return {
        "container": container,
        "image_ref": image_ref,
        "image_id": image_id,
        "revision": revision,
    }


def validate_compose_volume_contract(
    output: str,
    project: str,
    expected: Mapping[str, object],
) -> None:
    try:
        config = json.loads(output)
    except json.JSONDecodeError:
        fail("compose_volume_contract_unparseable")
    if not isinstance(config, dict) or not isinstance(config.get("services"), dict):
        fail("compose_volume_contract_unparseable")
    definitions = config.get("volumes", {})
    if not isinstance(definitions, dict):
        fail("compose_volume_contract_unparseable")
    destinations = {"postgres": "/var/lib/postgresql/data", "redis": "/data"}
    for service, destination in destinations.items():
        expected_name = expected.get(service)
        service_config = config["services"].get(service)
        if not isinstance(expected_name, str) or not isinstance(service_config, dict):
            fail("compose_volume_contract_invalid")
        mounts = service_config.get("volumes")
        if not isinstance(mounts, list):
            fail("compose_volume_contract_invalid")
        matches = [
            item
            for item in mounts
            if isinstance(item, dict)
            and item.get("type") == "volume"
            and item.get("target") == destination
        ]
        if len(matches) != 1 or not isinstance(matches[0].get("source"), str):
            fail("compose_volume_contract_invalid")
        source = str(matches[0]["source"])
        definition = definitions.get(source, {})
        if not isinstance(definition, dict):
            fail("compose_volume_contract_invalid")
        actual_name = definition.get("name") or f"{project}_{source}"
        if actual_name != expected_name:
            fail("compose_volume_identity_mismatch")


def verify_live_volumes(
    runner: Runner,
    project: str,
    working_directory: str,
    compose_files: Sequence[str],
    expected: Mapping[str, object],
) -> None:
    destinations = {"postgres": "/var/lib/postgresql/data", "redis": "/data"}
    for service, destination in destinations.items():
        volume = expected.get(service)
        if not isinstance(volume, str):
            fail("volume_identity_invalid")
        actual = run_or_fail(
            runner,
            ("docker", "volume", "inspect", "--format", "{{.Name}}", volume),
            f"volume:{service}",
        ).strip()
        if actual != volume:
            fail("volume_identity_changed")
        container = run_or_fail(
            runner,
            compose_command(
                project,
                working_directory,
                compose_files,
                "ps",
                "-q",
                "--all",
                service,
            ),
            f"volume_container:{service}",
        ).strip()
        if not container or "\n" in container:
            fail(f"service_missing_or_ambiguous:{service}")
        mounts_output = run_or_fail(
            runner,
            ("docker", "inspect", "--format", "{{json .Mounts}}", container),
            f"volume_mounts:{service}",
        )
        try:
            mounts = json.loads(mounts_output)
        except json.JSONDecodeError:
            fail("volume_mounts_unparseable")
        matches = [
            item
            for item in mounts
            if isinstance(item, dict)
            and item.get("Type") == "volume"
            and item.get("Destination") == destination
        ] if isinstance(mounts, list) else []
        if len(matches) != 1 or matches[0].get("Name") != volume:
            fail(f"live_volume_identity_mismatch:{service}")


def bootstrap(settings: Settings, runner: Runner) -> None:
    with rollout_lock(settings.lock_file):
        handoff = read_record(settings.handoff_file, "handoff")
        canonical = load_canonical(settings)
        baseline_sha = handoff.get("expected_baseline_sha")
        if canonical.get("sha") != baseline_sha or not isinstance(baseline_sha, str):
            fail("canonical_runtime_mismatch")
        require_environment(
            settings.environment_file,
            {"APP_ENV": "development", "TEST_MODE": "true"},
        )
        base_source = run_or_fail(
            runner,
            (
                "git",
                "-C",
                str(settings.working_directory.parent),
                "show",
                f"{baseline_sha}:nura_app/docker-compose.yml",
            ),
            "baseline_compose_materialization",
        ).encode()
        baseline_compose = settings.baseline_compose(baseline_sha)
        atomic_write(baseline_compose, base_source)
        compose_files = [str(baseline_compose)]
        status = run_or_fail(
            runner,
            compose_command(
                settings.project,
                str(settings.working_directory),
                compose_files,
                "ps",
                "--format",
                "json",
            ),
            "baseline_compose_status",
        )
        parse_compose_status(
            status,
            (*DATA_SERVICES, *APP_SERVICES),
            HEALTH_SERVICES,
        )
        mapping: dict[str, str] = {}
        ids: dict[str, str] = {}
        for service in APP_SERVICES:
            inspected = inspect_service(
                runner,
                settings.project,
                str(settings.working_directory),
                compose_files,
                service,
            )
            revision = inspected["revision"]
            if revision and revision != baseline_sha:
                fail("mixed_application_fleet")
            mapping[service] = inspected["image_ref"]
            ids[service] = inspected["image_id"]
        if len(set(ids.values())) != 1:
            fail("mixed_application_fleet")
        atomic_write(settings.baseline_override(baseline_sha), materialized_override(ids))
        volumes = handoff.get("volumes")
        if not isinstance(volumes, dict) or set(volumes) != set(DATA_SERVICES):
            fail("handoff_schema_invalid")
        verify_live_volumes(
            runner,
            settings.project,
            str(settings.working_directory),
            compose_files,
            volumes,
        )
        volume_ids = {service: str(volumes[service]) for service in DATA_SERVICES}
        release_path = canonical.get("static_release_path")
        if not isinstance(release_path, str):
            fail("canonical_state_invalid")
        exact_release_path(settings, Path(release_path), baseline_sha)
        current_target = settings.current_link.resolve(strict=True)
        if current_target != Path(release_path).resolve(strict=True):
            fail("canonical_public_mismatch")
        baseline = {
            "target_sha": settings.sha,
            "previous_sha": baseline_sha,
            "release_path": release_path,
            "image_mapping": mapping,
            "image_ids": ids,
            "compose_project": settings.project,
            "working_directory": str(settings.working_directory.resolve(strict=True)),
            "compose_files": [
                str(baseline_compose),
                str(settings.baseline_override(baseline_sha)),
            ],
            "volumes": volume_ids,
            "canonical_digest": hashlib.sha256(
                settings.canonical_state.read_bytes()
            ).hexdigest(),
            "public_target": str(current_target),
        }
        write_record(settings.baseline_file, "baseline", baseline)
        transaction(settings, "baseline_ready")
        print(
            f"p7b_bootstrap sha={settings.sha} baseline={baseline_sha} "
            "status=ready secrets=redacted"
        )


def verify_volumes(
    runner: Runner,
    payload: Mapping[str, object],
    expected: Mapping[str, object],
) -> None:
    compose_files = payload.get("compose_files")
    if not isinstance(compose_files, list) or not all(
        isinstance(item, str) for item in compose_files
    ):
        fail("compose_context_invalid")
    verify_live_volumes(
        runner,
        str(payload["compose_project"]),
        str(payload["working_directory"]),
        [str(item) for item in compose_files],
        expected,
    )


def lifecycle(
    payload: Mapping[str, object],
    services: Sequence[str],
    runner: Runner,
) -> None:
    compose_files = payload.get("compose_files")
    if not isinstance(compose_files, list) or not all(
        isinstance(item, str) for item in compose_files
    ):
        fail("compose_context_invalid")
    run_or_fail(
        runner,
        compose_command(
            str(payload["compose_project"]),
            str(payload["working_directory"]),
            [str(item) for item in compose_files],
            "up",
            "--detach",
            "--force-recreate",
            "--no-build",
            "--no-deps",
            "--wait",
            "--wait-timeout",
            "180",
            *services,
        ),
        "compose_up",
    )


def verification_commands(
    payload: Mapping[str, object], stage: int
) -> list[tuple[str, list[str]]]:
    compose_files = [str(item) for item in payload["compose_files"]]  # type: ignore[index]
    project = str(payload["compose_project"])
    working = str(payload["working_directory"])
    commands = [
        (
            "compose_status",
            compose_command(project, working, compose_files, "ps", "--format", "json"),
        ),
        (
            "postgres_readiness",
            compose_command(
                project, working, compose_files, "exec", "-T", "postgres", "pg_isready"
            ),
        ),
        (
            "api_health",
            compose_command(
                project,
                working,
                compose_files,
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                "import urllib.request; assert "
                "urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200",
            ),
        ),
    ]
    if stage == 2:
        commands.append(
            (
                "production_settings",
                compose_command(
                    project,
                    working,
                    compose_files,
                    "exec",
                    "-T",
                    "api",
                    "python",
                    "-c",
                    "from core.config import settings; assert settings.is_production "
                    "and not settings.test_mode and settings.session_cookie_secure "
                    "and settings.yookassa_verify_on_webhook "
                    "and not settings.production_readiness_errors",
                ),
            ),
        )
    return commands


def verify_application_identity(
    settings: Settings,
    handoff: Mapping[str, object],
    runner: Runner,
) -> dict[str, dict[str, str]]:
    mappings = handoff.get("image_mapping")
    ids = handoff.get("image_ids")
    compose_files = handoff.get("compose_files")
    if (
        not isinstance(mappings, dict)
        or set(mappings) != set(APP_SERVICES)
        or not isinstance(ids, dict)
        or set(ids) != set(APP_SERVICES)
        or not isinstance(compose_files, list)
        or not all(isinstance(item, str) for item in compose_files)
    ):
        fail("handoff_schema_invalid")
    inspected_services: dict[str, dict[str, str]] = {}
    for service in APP_SERVICES:
        inspected = inspect_service(
            runner,
            str(handoff["compose_project"]),
            str(handoff["working_directory"]),
            [str(item) for item in compose_files],
            service,
        )
        if (
            inspected["image_ref"] != mappings[service]
            or inspected["image_id"] != ids[service]
            or inspected["revision"] != settings.sha
        ):
            fail(f"target_identity_mismatch:{service}")
        inspected_services[service] = inspected
    return inspected_services


def verify_redis_target_identity(
    handoff: Mapping[str, object],
    state: Mapping[str, object],
    runner: Runner,
) -> str:
    expected = state.get("stage1_redis_container")
    if not isinstance(expected, str) or not expected:
        fail("target_redis_identity_missing")
    compose_files = handoff.get("compose_files")
    if not isinstance(compose_files, list) or not all(
        isinstance(item, str) for item in compose_files
    ):
        fail("handoff_schema_invalid")
    actual = service_container(
        runner,
        str(handoff["compose_project"]),
        str(handoff["working_directory"]),
        [str(item) for item in compose_files],
        "redis",
    )
    if actual != expected:
        fail("target_redis_identity_mismatch")
    return expected


def redis_authenticated_healthcheck_command(container: str) -> tuple[str, ...]:
    return (
        "docker",
        "exec",
        container,
        "timeout",
        str(REDIS_HEALTHCHECK_TIMEOUT_SECONDS),
        "/bin/sh",
        "/usr/local/bin/nura-redis-healthcheck",
    )


def celery_worker_ping_command(container: str) -> tuple[str, ...]:
    return (
        "timeout",
        str(CELERY_PING_OUTER_TIMEOUT_SECONDS),
        "docker",
        "exec",
        container,
        "celery",
        "-A",
        "core.tasks",
        "inspect",
        "ping",
        "--timeout",
        str(CELERY_PING_TIMEOUT_SECONDS),
    )


def verify_redis_authenticated_healthcheck(
    runner: Runner,
    command: Sequence[str],
    check: str,
) -> None:
    for attempt in range(REDIS_HEALTHCHECK_ATTEMPTS):
        result = command_result(runner, command)
        if result.returncode == 0 and result.stdout.strip() == "PONG":
            return
        if attempt + 1 < REDIS_HEALTHCHECK_ATTEMPTS:
            time.sleep(REDIS_HEALTHCHECK_DELAY_SECONDS)
    fail(f"verification_failed:{check}")


def celery_output_category(output: str, *, stderr: bool) -> str:
    lowered = output.lower()
    if not output.strip():
        return "empty"
    if "authentication required" in lowered or "noauth" in lowered:
        return "authentication_required"
    if "wrongpass" in lowered or "invalid username-password pair" in lowered:
        return "wrong_password"
    if "connection refused" in lowered:
        return "connection_refused"
    if (
        "name or service not known" in lowered
        or "temporary failure in name resolution" in lowered
    ):
        return "dns_failure"
    if "no nodes replied" in lowered or "no workers replied" in lowered:
        return "no_worker_reply"
    if "unable to load celery application" in lowered or "module not found" in lowered:
        return "invalid_app_module"
    if "timed out" in lowered or "command_timeout" in lowered:
        return "timeout"
    if not stderr and any(
        line.strip().lower() == "pong" for line in output.splitlines()
    ):
        return "standalone_pong"
    return "other"


def celery_attempt_container_state(
    runner: Runner,
    container: str,
    current_service_command: Sequence[str],
) -> dict[str, object]:
    current_service = command_result(runner, current_service_command)
    current_container = current_service.stdout.strip()
    if (
        current_service.returncode != 0
        or not current_container
        or "\n" in current_container
    ):
        return {
            "container_identity": "service_missing",
            "container_running": False,
            "restart_count": None,
        }
    result = command_result(
        runner,
        (
            "docker",
            "inspect",
            "--format",
            "{{.Id}}|{{.State.Running}}|{{.RestartCount}}",
            container,
        ),
    )
    if result.returncode != 0:
        return {
            "container_identity": "missing",
            "container_running": False,
            "restart_count": None,
        }
    fields = result.stdout.strip().split("|")
    if len(fields) != 3:
        return {
            "container_identity": "unparseable",
            "container_running": False,
            "restart_count": None,
        }
    actual, running, restarts = fields
    try:
        restart_count: int | None = int(restarts)
    except ValueError:
        restart_count = None
    return {
        "container_identity": (
            "exact_target"
            if actual == container and current_container == container
            else "service_rebound"
            if actual == container
            else "stale"
        ),
        "container_running": running == "true",
        "restart_count": restart_count,
    }


def verify_celery_worker_ping(
    settings: Settings,
    runner: Runner,
    command: Sequence[str],
    check: str,
    worker_container: str,
    current_service_command: Sequence[str],
    stage: int,
    *,
    persist: bool,
) -> None:
    attempts: list[dict[str, object]] = []
    for attempt in range(CELERY_PING_ATTEMPTS):
        container_state = celery_attempt_container_state(
            runner,
            worker_container,
            current_service_command,
        )
        result = command_result(runner, command)
        pong = any(line.strip().lower() == "pong" for line in result.stdout.splitlines())
        stdout_category = celery_output_category(result.stdout, stderr=False)
        stderr_category = celery_output_category(result.stderr, stderr=True)
        diagnostic = {
            "attempt": attempt + 1,
            **container_state,
            "command_path": "docker_exec",
            "celery_app": "core.tasks",
            "outer_timeout_seconds": CELERY_PING_OUTER_TIMEOUT_SECONDS,
            "internal_timeout_seconds": CELERY_PING_TIMEOUT_SECONDS,
            "exit_code": result.returncode,
            "stdout_category": stdout_category,
            "stderr_category": stderr_category,
            "pong_found": pong,
            "broker_connection_error_class": (
                stderr_category
                if stderr_category
                in {
                    "authentication_required",
                    "wrong_password",
                    "connection_refused",
                    "dns_failure",
                    "timeout",
                }
                else "none"
            ),
            "worker_node_visible": "celery@" in result.stdout and ": OK" in result.stdout,
        }
        attempts.append(diagnostic)
        if persist:
            current_phase = read_record(
                settings.transaction_file,
                "transaction",
            ).get("phase")
            if not isinstance(current_phase, str) or current_phase not in PHASES:
                fail("invalid_transaction_phase")
            transaction(
                settings,
                current_phase,
                **{
                    f"stage{stage}_celery_ping_attempts": attempts,
                },
            )
        if (
            result.returncode == 0
            and pong
            and container_state["container_identity"] == "exact_target"
            and container_state["container_running"] is True
        ):
            return
        if attempt + 1 < CELERY_PING_ATTEMPTS:
            time.sleep(CELERY_PING_DELAY_SECONDS)
    fail(f"verification_failed:{check}")


def verify_stage(
    settings: Settings,
    stage: int,
    runner: Runner,
    *,
    acquire_lock: bool = True,
    persist: bool = True,
) -> None:
    if acquire_lock:
        with rollout_lock(settings.lock_file):
            verify_stage(
                settings,
                stage,
                runner,
                acquire_lock=False,
                persist=persist,
            )
        return
    handoff = read_record(settings.handoff_file, "handoff")
    baseline = read_record(settings.baseline_file, "baseline")
    state = read_record(settings.transaction_file, "transaction")
    allowed = (
        {"stage1_intent", "stage1_verified"}
        if stage == 1
        else {"stage2_intent", "stage2_verified", "smoke_verified", "finalizing"}
    )
    if state.get("phase") not in allowed:
        fail(f"stage{stage}_intent_required")
    require_environment(
        settings.environment_file,
        {"APP_ENV": "development", "TEST_MODE": "true"}
        if stage == 1
        else {"APP_ENV": "production", "TEST_MODE": "false"},
    )
    commands = verification_commands(handoff, stage)
    status = run_or_fail(
        runner,
        commands[0][1],
        f"stage{stage}:{commands[0][0]}",
    )
    parse_compose_status(
        status,
        (*DATA_SERVICES, *APP_SERVICES),
        HEALTH_SERVICES,
    )
    redis_container = verify_redis_target_identity(handoff, state, runner)
    inspected_services = verify_application_identity(settings, handoff, runner)
    worker_container = state.get(f"stage{stage}_worker_container")
    if not isinstance(worker_container, str) or not worker_container:
        fail(f"stage{stage}_worker_identity_missing")
    if inspected_services["celery-worker"]["container"] != worker_container:
        fail("target_identity_mismatch:celery-worker")
    verify_redis_authenticated_healthcheck(
        runner,
        redis_authenticated_healthcheck_command(redis_container),
        f"stage{stage}:redis_authenticated_healthcheck",
    )
    for check, command in commands[1:]:
        run_or_fail(runner, command, f"stage{stage}:{check}")
    verify_celery_worker_ping(
        settings,
        runner,
        celery_worker_ping_command(worker_container),
        f"stage{stage}:celery_worker_ping",
        worker_container,
        compose_command(
            str(handoff["compose_project"]),
            str(handoff["working_directory"]),
            [str(item) for item in handoff["compose_files"]],  # type: ignore[index]
            "ps",
            "-q",
            "--all",
            "celery-worker",
        ),
        stage,
        persist=persist,
    )
    verify_volumes(runner, handoff, baseline["volumes"])  # type: ignore[arg-type]
    phase = f"stage{stage}_verified"
    if persist:
        transaction(settings, phase)
    if stage == 2 and persist:
        receipt = {
            "target_sha": settings.sha,
            "previous_sha": baseline["previous_sha"],
            "handoff_digest": payload_digest(handoff),
            "baseline_digest": payload_digest(baseline),
            "transaction_phase": phase,
            "verified_at": int(time.time()),
        }
        write_record(settings.receipt_file, "receipt", receipt)
    print(f"p7b_verify_stage{stage} status=ok secrets=redacted")


def compensate(settings: Settings, runner: Runner, failed_stage: int) -> None:
    baseline = read_record(settings.baseline_file, "baseline")
    if failed_stage == 2 and settings.environment_backup.exists():
        restore_environment(settings)
    lifecycle(baseline, STAGE1_SERVICES, runner)
    require_environment(
        settings.environment_file,
        {"APP_ENV": "development", "TEST_MODE": "true"},
    )
    verify_volumes(runner, baseline, baseline["volumes"])  # type: ignore[arg-type]
    transaction(
        settings,
        f"stage{failed_stage}_compensated",
        compensated_to=baseline["previous_sha"],
    )


def verify_baseline_canonical(
    settings: Settings,
    baseline: Mapping[str, object],
) -> None:
    canonical = load_canonical(settings)
    expected_sha = baseline.get("previous_sha")
    expected_digest = baseline.get("canonical_digest")
    actual_digest = hashlib.sha256(settings.canonical_state.read_bytes()).hexdigest()
    if (
        canonical.get("sha") != expected_sha
        or not isinstance(expected_digest, str)
        or actual_digest != expected_digest
    ):
        fail("canonical_baseline_changed")


def stage1(settings: Settings, runner: Runner) -> None:
    with rollout_lock(settings.lock_file):
        handoff = validate_handoff(settings, runner)
        baseline = read_record(settings.baseline_file, "baseline")
        state = read_record(settings.transaction_file, "transaction")
        if state.get("phase") == "stage1_verified":
            verify_stage(settings, 1, runner, acquire_lock=False)
            return
        if state.get("phase") not in {
            "baseline_ready",
            "stage1_compensated",
            "stage2_compensated",
        }:
            fail("baseline_ready_required")
        transaction(settings, "stage1_intent")
        try:
            verify_baseline_canonical(settings, baseline)
            verify_volumes(
                runner,
                baseline,
                baseline["volumes"],  # type: ignore[arg-type]
            )
            lifecycle(handoff, STAGE1_SERVICES, runner)
            compose_files = handoff.get("compose_files")
            if not isinstance(compose_files, list) or not all(
                isinstance(item, str) for item in compose_files
            ):
                fail("handoff_schema_invalid")
            redis_container = service_container(
                runner,
                str(handoff["compose_project"]),
                str(handoff["working_directory"]),
                [str(item) for item in compose_files],
                "redis",
            )
            worker_container = service_container(
                runner,
                str(handoff["compose_project"]),
                str(handoff["working_directory"]),
                [str(item) for item in compose_files],
                "celery-worker",
            )
            transaction(
                settings,
                "stage1_intent",
                stage1_redis_container=redis_container,
                stage1_worker_container=worker_container,
            )
            verify_stage(settings, 1, runner, acquire_lock=False)
        except BaseException:
            compensate(settings, runner, 1)
            raise


def stage2(settings: Settings, runner: Runner) -> None:
    with rollout_lock(settings.lock_file):
        handoff = validate_handoff(settings, runner)
        state = read_record(settings.transaction_file, "transaction")
        if state.get("phase") == "stage2_verified":
            verify_stage(settings, 2, runner, acquire_lock=False)
            return
        if state.get("phase") != "stage1_verified":
            fail("stage1_verification_required")
        baseline = read_record(settings.baseline_file, "baseline")
        verify_baseline_canonical(settings, baseline)
        transaction(settings, "stage2_intent")
        try:
            if settings.environment_backup.exists():
                require_environment(
                    settings.environment_file,
                    {"APP_ENV": "production", "TEST_MODE": "false"},
                )
            else:
                edit_environment(
                    settings.environment_file,
                    settings.environment_backup,
                    {"APP_ENV": "production", "TEST_MODE": "false"},
                )
            lifecycle(handoff, APP_SERVICES, runner)
            compose_files = handoff.get("compose_files")
            if not isinstance(compose_files, list) or not all(
                isinstance(item, str) for item in compose_files
            ):
                fail("handoff_schema_invalid")
            worker_container = service_container(
                runner,
                str(handoff["compose_project"]),
                str(handoff["working_directory"]),
                [str(item) for item in compose_files],
                "celery-worker",
            )
            transaction(
                settings,
                "stage2_intent",
                stage2_worker_container=worker_container,
            )
            verify_stage(settings, 2, runner, acquire_lock=False)
        except BaseException:
            compensate(settings, runner, 2)
            raise


def preflight(settings: Settings, runner: Runner) -> None:
    verify_release_checkout(settings, runner)
    handoff = validate_handoff(settings, runner)
    baseline = read_record(settings.baseline_file, "baseline")
    verify_baseline_canonical(settings, baseline)
    if handoff.get("expected_baseline_sha") != baseline.get("previous_sha"):
        fail("baseline_contract_mismatch")
    verify_secret_file_compose_contract(handoff)
    verify_volumes(runner, baseline, baseline["volumes"])  # type: ignore[arg-type]
    print(f"p7b_preflight sha={settings.sha} status=ok secrets=redacted")


def readiness(settings: Settings, runner: Runner) -> None:
    state = read_record(settings.transaction_file, "transaction")
    if state.get("phase") != "stage1_verified":
        fail("stage1_verification_required")
    handoff = read_record(settings.handoff_file, "handoff")
    status = run_or_fail(
        runner,
        verification_commands(handoff, 1)[0][1],
        "readiness_compose_status",
    )
    parse_compose_status(status, (*DATA_SERVICES, *APP_SERVICES), HEALTH_SERVICES)
    print(f"p7b_readiness sha={settings.sha} status=ready secrets=redacted")


def smoke_webhook(
    settings: Settings,
    runner: Runner,
    webhook_url: str,
) -> None:
    if webhook_url != "http://127.0.0.1:8000/api/v1/payment/webhook":
        fail("unsafe_webhook_smoke_url")
    state = read_record(settings.transaction_file, "transaction")
    if state.get("phase") != "stage2_verified":
        fail("stage2_verification_required")
    for payload in ("{", "[]", '"invalid"', "null"):
        status = run_or_fail(
            runner,
            (
                "curl",
                "--silent",
                "--show-error",
                "--output",
                "/dev/null",
                "--write-out",
                "%{http_code}",
                "--header",
                "Content-Type: application/json",
                "--data-binary",
                payload,
                webhook_url,
            ),
            "malformed_webhook_smoke",
        ).strip()
        if status != "400":
            fail("malformed_webhook_smoke_failed")
    transaction(settings, "smoke_verified")
    print(f"p7b_webhook_smoke sha={settings.sha} status=ok mutations=none")


def activate(settings: Settings, runner: Runner, webhook_url: str) -> None:
    """Own the full managed chain under the host-wide common release lock."""
    with rollout_lock(settings.common_lock_file):
        state = read_record(settings.transaction_file, "transaction")
        phase = state.get("phase")
        if phase == "prepared":
            bootstrap(settings, runner)
            phase = "baseline_ready"
        if phase in {"stage1_intent", "stage2_intent", "stage2_verified"}:
            recover(settings, runner)
            phase = read_record(settings.transaction_file, "transaction").get("phase")
        if phase in {
            "baseline_ready",
            "stage1_compensated",
            "stage2_compensated",
        }:
            preflight(settings, runner)
            stage1(settings, runner)
            phase = "stage1_verified"
        if phase == "stage1_verified":
            try:
                readiness(settings, runner)
            except BaseException:
                with rollout_lock(settings.lock_file):
                    compensate(settings, runner, 1)
                raise
            stage2(settings, runner)
            phase = "stage2_verified"
        if phase == "stage2_verified":
            try:
                with rollout_lock(settings.lock_file):
                    smoke_webhook(settings, runner, webhook_url)
            except BaseException:
                with rollout_lock(settings.lock_file):
                    compensate(settings, runner, 2)
                raise
            phase = "smoke_verified"
        if phase in {"smoke_verified", "finalizing", "complete"}:
            finalize(settings, runner)
            return
        fail("activation_phase_invalid")


def atomic_symlink(link: Path, target: Path) -> None:
    if link.is_symlink():
        parent = link.parent
    elif link.exists():
        fail("current_marker_not_symlink")
    else:
        parent = link.parent
    if parent.is_symlink() or not parent.is_dir():
        fail("unsafe_current_marker_parent")
    temporary = parent / f".{link.name}.{os.getpid()}.tmp"
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    os.symlink(str(target), temporary, target_is_directory=True)
    os.replace(temporary, link)


def retention_cleanup(
    settings: Settings,
    current: Mapping[str, object],
    runner: Runner,
) -> None:
    """Best-effort retention after durable completion, under the common lock."""
    root = safe_existing_directory(settings.releases_directory, "releases_root")
    history = current.get("activation_history", [])
    if (
        not isinstance(history, list)
        or len(history) > 2
        or not all(isinstance(item, str) and SHA.fullmatch(item) for item in history)
    ):
        fail("retention_history_invalid")
    protected = {settings.sha, *history}
    cleanup_failed = False
    for candidate in root.iterdir():
        if (
            candidate.name in protected
            or not SHA.fullmatch(candidate.name)
            or candidate.is_symlink()
            or not candidate.is_dir()
        ):
            continue
        record = settings.canonical_state.parent / "releases" / f"{candidate.name}.json"
        if record.is_file() and not record.is_symlink():
            try:
                if json.loads(record.read_text(encoding="utf-8")).get("legacy"):
                    continue
            except (OSError, json.JSONDecodeError):
                cleanup_failed = True
                continue
        shutil.rmtree(candidate)
        result = command_result(
            runner,
            ("docker", "image", "rm", f"nura-release:{candidate.name}"),
        )
        if result.returncode != 0:
            cleanup_failed = True
    if cleanup_failed:
        print("p7b_retention status=warning secrets=redacted")
    else:
        print("p7b_retention status=ok secrets=redacted")


def finalize(
    settings: Settings,
    runner: Runner,
    *,
    acquire_lock: bool = True,
) -> None:
    if acquire_lock:
        with rollout_lock(settings.lock_file):
            finalize(settings, runner, acquire_lock=False)
        return
    else:
        state = read_record(settings.transaction_file, "transaction")
        if state.get("phase") == "complete":
            canonical = load_canonical(settings)
            if canonical.get("sha") != settings.sha:
                fail("complete_canonical_mismatch")
            retention_cleanup(settings, canonical, runner)
            print(f"p7b_finalize sha={settings.sha} status=complete secrets=redacted")
            return
        if state.get("phase") not in {"smoke_verified", "finalizing"}:
            fail("stage2_completion_proof_required")
        receipt = read_record(settings.receipt_file, "receipt")
        handoff = validate_handoff(settings, runner)
        baseline = read_record(settings.baseline_file, "baseline")
        if (
            receipt.get("target_sha") != settings.sha
            or receipt.get("transaction_phase") != "stage2_verified"
            or receipt.get("handoff_digest") != payload_digest(handoff)
            or receipt.get("baseline_digest") != payload_digest(baseline)
        ):
            fail("completion_proof_invalid")
        verify_stage(settings, 2, runner, acquire_lock=False, persist=False)
        if state.get("phase") == "smoke_verified":
            previous_snapshot = canonical_json(load_canonical(settings)) + b"\n"
            atomic_write(settings.previous_state, previous_snapshot, mode=0o640)
            transaction(settings, "finalizing", previous_saved=True)
        else:
            previous = load_release_state(settings.previous_state, "previous")
            if previous.get("sha") != baseline.get("previous_sha"):
                fail("previous_marker_mismatch")
        target_release = Path(str(handoff["release_path"]))
        target_release = exact_release_path(settings, target_release, settings.sha)
        version = target_release / "public" / "VERSION"
        if not version.is_file() or version.is_symlink():
            fail("active_version_missing")
        if version.read_text(encoding="utf-8").split()[0] != settings.sha:
            fail("active_version_mismatch")
        if not settings.release_state_file.is_file() or settings.release_state_file.is_symlink():
            fail("prepared_release_state_missing")
        try:
            current = json.loads(settings.release_state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            fail("prepared_release_state_invalid")
        if not isinstance(current, dict):
            fail("prepared_release_state_invalid")
        immutable = {
            "sha": settings.sha,
            "static_release_path": str(target_release),
            "artifact_sha256": handoff["artifact_sha256"],
            "public_manifest_sha256": handoff["manifest_sha256"],
            "application_image_tag": f"nura-release:{settings.sha}",
            "per_service_image_mapping": handoff["image_mapping"],
            "per_service_image_ids": handoff["image_ids"],
        }
        for key, expected in immutable.items():
            if current.get(key) != expected:
                fail(f"prepared_release_state_mismatch:{key}")
        image_ids = handoff["image_ids"]
        if not isinstance(image_ids, dict):
            fail("handoff_schema_invalid")
        target_image_id = next(iter(image_ids.values()))
        if current.get("application_image_id") != target_image_id:
            fail("prepared_release_state_mismatch:application_image_id")
        previous = load_release_state(settings.previous_state, "previous")
        history = previous.get("activation_history", [])
        if not isinstance(history, list):
            fail("previous_activation_history_invalid")
        next_history = [baseline["previous_sha"], *history][:2]
        current.update(
            {
                "schema": 2,
                "status": "successful",
                "previous_successful_sha": baseline["previous_sha"],
                "activation_history": next_history,
                "activation_timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                ),
                "rollback_eligibility": True,
                "compensation_verified": False,
                "failure_stage": None,
                "failure_reason": None,
                "p7b_completion_receipt": str(settings.receipt_file),
            }
        )
        atomic_symlink(settings.current_link, target_release)
        atomic_write(
            settings.release_state_file,
            canonical_json(current) + b"\n",
            mode=0o640,
        )
        atomic_write(settings.canonical_state, canonical_json(current) + b"\n", mode=0o640)
        transaction(settings, "complete")
        retention_cleanup(settings, current, runner)
        print(f"p7b_finalize sha={settings.sha} status=complete secrets=redacted")


def recover(settings: Settings, runner: Runner) -> None:
    with rollout_lock(settings.lock_file):
        state = read_record(settings.transaction_file, "transaction")
        phase = state.get("phase")
        if phase in {"prepared", "baseline_ready", "stage1_compensated", "stage2_compensated"}:
            print(f"p7b_recover sha={settings.sha} phase={phase} action=none")
        elif phase == "stage1_intent":
            compensate(settings, runner, 1)
        elif phase == "stage1_verified":
            verify_stage(settings, 1, runner, acquire_lock=False)
        elif phase == "stage2_intent":
            compensate(settings, runner, 2)
        elif phase == "stage2_verified":
            compensate(settings, runner, 2)
        elif phase == "smoke_verified":
            finalize(settings, runner, acquire_lock=False)
        elif phase == "finalizing":
            finalize(settings, runner, acquire_lock=False)
        elif phase == "complete":
            finalize(settings, runner, acquire_lock=False)
        else:
            fail("recovery_phase_invalid")


def recover_under_common_lock(settings: Settings, runner: Runner) -> None:
    with rollout_lock(settings.common_lock_file):
        recover(settings, runner)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("operation", choices=OPERATIONS)
    result.add_argument("--sha", required=True, type=require_sha)
    result.add_argument("--project", default="nura_app")
    result.add_argument(
        "--working-directory", type=Path, default=Path("/opt/nura/nura_app")
    )
    result.add_argument(
        "--base-compose", type=Path, default=Path("/opt/nura/nura_app/docker-compose.yml")
    )
    result.add_argument("--env-file", type=Path, default=Path("/opt/nura/nura_app/.env"))
    result.add_argument(
        "--state-dir", type=Path, default=Path("/var/lib/nura-release-state/p7b")
    )
    result.add_argument(
        "--canonical-state",
        type=Path,
        default=Path("/var/lib/nura-release-state/current.json"),
    )
    result.add_argument(
        "--previous-state",
        type=Path,
        default=Path("/var/lib/nura-release-state/previous.json"),
    )
    result.add_argument(
        "--current-link", type=Path, default=Path("/var/www/nura-releases/current")
    )
    result.add_argument(
        "--releases-directory",
        type=Path,
        default=Path("/var/www/nura-releases/releases"),
    )
    result.add_argument(
        "--common-lock-file",
        type=Path,
        default=Path("/run/lock/nura-deploy.lock"),
    )
    result.add_argument(
        "--webhook-url",
        default="http://127.0.0.1:8000/api/v1/payment/webhook",
    )
    result.add_argument("--release-path", type=Path)
    result.add_argument("--image-id")
    result.add_argument("--artifact-sha256")
    result.add_argument("--manifest-sha256")
    result.add_argument("--expected-baseline-sha")
    result.add_argument("--redis-volume", default="nura_app_redis_data")
    result.add_argument("--postgres-volume", default="nura_app_postgres_data")
    return result


def main(argv: Sequence[str] | None = None, runner: Runner = default_runner) -> None:
    args = parser().parse_args(argv)
    args.runner = runner
    settings = Settings(
        args.sha,
        args.project,
        args.working_directory,
        args.base_compose,
        args.state_dir,
        args.env_file,
        args.canonical_state,
        args.previous_state,
        args.current_link,
        args.releases_directory,
        args.common_lock_file,
    )
    direct_managed = {
        "bootstrap",
        "stage1",
        "verify-stage1",
        "readiness",
        "stage2",
        "verify-stage2",
        "finalize",
    }
    if args.operation in direct_managed:
        fail("managed_activation_use_activate")
    if args.operation == "status":
        payload = (
            read_record(settings.transaction_file, "transaction")
            if settings.transaction_file.exists()
            else {"target_sha": settings.sha, "phase": "absent"}
        )
        print("p7b_status " + json.dumps(payload, sort_keys=True))
    elif args.operation == "prepare-handoff":
        required = (
            args.release_path,
            args.image_id,
            args.artifact_sha256,
            args.manifest_sha256,
            args.expected_baseline_sha,
        )
        if any(value is None for value in required):
            fail("prepare_handoff_arguments_required")
        prepare_handoff(settings, args)
    elif args.operation == "preflight":
        preflight(settings, runner)
    elif args.operation == "plan-stage1":
        print(
            json.dumps(
                {"stage": 1, "services": STAGE1_SERVICES, "compensation_owner": "p7b"}
            )
        )
    elif args.operation == "plan-stage2":
        print(
            json.dumps(
                {"stage": 2, "services": APP_SERVICES, "compensation_owner": "p7b"}
            )
        )
    elif args.operation == "activate":
        activate(settings, runner, args.webhook_url)
    else:
        recover_under_common_lock(settings, runner)


if __name__ == "__main__":
    main()
