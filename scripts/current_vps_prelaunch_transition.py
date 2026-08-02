#!/usr/bin/env python3
"""Audited, manifest-only engine for the one-time owner-prelaunch transition.

The implementation milestone intentionally ships no authorization manifest.
Without a later tracked manifest binding an exact target commit this engine can
only validate its static contract and always refuses execution.
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
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Protocol, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "nura_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from tools.current_vps_migration_contract import (  # noqa: E402
    CURRENT_REVISION,
    EXPECTED_MIGRATIONS,
    MIGRATION_CHAIN_DIGEST,
    SOURCE_APPLICATION_SHA,
    TARGET_REVISION,
    validate_migration_contract,
)
from tools.current_vps_prelaunch_preflight import (  # noqa: E402
    SECRET_PROFILE_VERSION,
    run_preflight,
)


SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
APP_SERVICES = ("api", "bot", "celery-worker", "celery-beat", "admin-bot")
WRITER_SERVICES = ("bot", "celery-beat", "celery-worker", "api", "admin-bot")
AUTHORIZATION_SCHEMA = 2
BACKUP_EVIDENCE_SCHEMA = 1
RECOVERY_EVIDENCE_SCHEMA = 1
MIN_AVAILABLE_RAM_BYTES = 3 * 1024**3
MIN_ACTIVE_SWAP_BYTES = 2 * 1024**3
MIN_DISK_FREE_BYTES = 6 * 1024**3
MIN_FREE_INODES = 50_000


class TransitionError(RuntimeError):
    """A bounded transition failure that contains neither credentials nor PII."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def payload_checksum(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _read_canonical_json(path: Path, label: str) -> dict[str, object]:
    try:
        metadata = path.lstat()
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransitionError(f"{label}_unreadable") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or not isinstance(value, dict):
        raise TransitionError(f"{label}_unsafe")
    if canonical_json(value) != raw:
        raise TransitionError(f"{label}_not_canonical")
    return value


def _validate_checksum(value: dict[str, object], label: str) -> None:
    checksum = value.get("checksum")
    payload = {key: item for key, item in value.items() if key != "checksum"}
    if not isinstance(checksum, str) or not DIGEST_RE.fullmatch(checksum):
        raise TransitionError(f"{label}_checksum_invalid")
    if payload_checksum(payload) != checksum:
        raise TransitionError(f"{label}_checksum_mismatch")


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise TransitionError("authorization_git_identity_invalid")
    return result.stdout.strip()


def _git_bytes(repo: Path, *arguments: str) -> bytes:
    """Read a Git object byte-for-byte; canonical payloads must retain final LF."""
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise TransitionError("authorization_git_identity_invalid")
    return result.stdout


def validate_authorization_manifest(
    path: Path,
    *,
    repo: Path = REPO_ROOT,
    engine_path: Path | None = None,
    now: datetime | None = None,
    verify_git: bool = True,
) -> dict[str, object]:
    manifest = _read_canonical_json(path, "authorization_manifest")
    _validate_checksum(manifest, "authorization_manifest")
    required = {
        "schema_version",
        "authorization_base_commit_sha",
        "authorization_manifest_path",
        "source_application_sha",
        "target_application_sha",
        "engine_commit_sha",
        "engine_file_sha256",
        "current_db_revision",
        "target_db_revision",
        "ordered_migration_revisions",
        "migration_chain_digest",
        "required_secret_profile_version",
        "backup_evidence_schema",
        "capacity_acknowledgement",
        "backward_compatible_schema_acknowledgement",
        "database_downgrade_acknowledgement",
        "owner_approval_identifiers",
        "valid_from",
        "expires_at",
        "target_artifact_sha256",
        "target_manifest_sha256",
        "checksum",
    }
    if set(manifest) != required or manifest.get("schema_version") != AUTHORIZATION_SCHEMA:
        raise TransitionError("authorization_manifest_schema_invalid")
    for key in (
        "authorization_base_commit_sha",
        "source_application_sha",
        "target_application_sha",
        "engine_commit_sha",
    ):
        if not isinstance(manifest.get(key), str) or not SHA_RE.fullmatch(manifest[key]):
            raise TransitionError("authorization_manifest_sha_invalid")
    for key in (
        "engine_file_sha256",
        "migration_chain_digest",
        "target_artifact_sha256",
        "target_manifest_sha256",
    ):
        if not isinstance(manifest.get(key), str) or not DIGEST_RE.fullmatch(manifest[key]):
            raise TransitionError("authorization_manifest_digest_invalid")
    expected_revisions = [item.revision for item in EXPECTED_MIGRATIONS]
    if (
        manifest["source_application_sha"] != SOURCE_APPLICATION_SHA
        or manifest["target_application_sha"] == SOURCE_APPLICATION_SHA
        or manifest["engine_commit_sha"] != manifest["target_application_sha"]
        or manifest["authorization_base_commit_sha"] != manifest["target_application_sha"]
        or manifest["current_db_revision"] != CURRENT_REVISION
        or manifest["target_db_revision"] != TARGET_REVISION
        or manifest["ordered_migration_revisions"] != expected_revisions
        or manifest["migration_chain_digest"] != MIGRATION_CHAIN_DIGEST
        or manifest["required_secret_profile_version"] != SECRET_PROFILE_VERSION
        or manifest["backup_evidence_schema"] != BACKUP_EVIDENCE_SCHEMA
        or manifest["backward_compatible_schema_acknowledgement"] is not True
        or manifest["database_downgrade_acknowledgement"] != "not-supported"
    ):
        raise TransitionError("authorization_manifest_transition_mismatch")
    capacity = manifest["capacity_acknowledgement"]
    if capacity != {
        "allowed_modes": ["available_ram", "precreated_swap"],
        "minimum_available_ram_bytes": MIN_AVAILABLE_RAM_BYTES,
        "minimum_active_swap_bytes": MIN_ACTIVE_SWAP_BYTES,
    }:
        raise TransitionError("authorization_manifest_capacity_invalid")
    approvals = manifest["owner_approval_identifiers"]
    if (
        not isinstance(approvals, list)
        or not approvals
        or approvals != sorted(set(approvals))
        or any(not isinstance(item, str) or not re.fullmatch(r"approval-[a-z0-9-]{8,64}", item) for item in approvals)
    ):
        raise TransitionError("authorization_manifest_approvals_invalid")
    try:
        valid_from = datetime.fromisoformat(str(manifest["valid_from"]).replace("Z", "+00:00"))
        expires_at = datetime.fromisoformat(str(manifest["expires_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise TransitionError("authorization_manifest_window_invalid") from exc
    current_time = now or datetime.now(timezone.utc)
    if (
        valid_from.tzinfo is None
        or expires_at.tzinfo is None
        or not valid_from <= current_time <= expires_at
        or (expires_at - valid_from).total_seconds() > 24 * 60 * 60
    ):
        raise TransitionError("authorization_manifest_window_invalid")

    actual_engine = engine_path or Path(__file__)
    if hashlib.sha256(actual_engine.read_bytes()).hexdigest() != manifest["engine_file_sha256"]:
        raise TransitionError("authorization_engine_hash_mismatch")
    if verify_git:
        repo = repo.resolve(strict=True)
        relative = manifest.get("authorization_manifest_path")
        if (
            not isinstance(relative, str)
            or not re.fullmatch(
                r"docs/operations/authorizations/current-vps-prelaunch-[a-z0-9-]+\.json",
                relative,
            )
        ):
            raise TransitionError("authorization_manifest_path_invalid")
        authorization_sha = _git(repo, "rev-parse", "origin/main")
        authorization_parent = _git(repo, "rev-parse", f"{authorization_sha}^")
        if authorization_parent != manifest["authorization_base_commit_sha"]:
            raise TransitionError("authorization_commit_parent_mismatch")
        changed = [
            item.decode("utf-8", "strict")
            for item in _git_bytes(
                repo,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "-z",
                authorization_sha,
            ).split(b"\0")
            if item
        ]
        if changed != [relative]:
            raise TransitionError("authorization_commit_scope_invalid")
        tracked = _git_bytes(repo, "show", f"{authorization_sha}:{relative}")
        if tracked != path.read_bytes():
            raise TransitionError("authorization_manifest_not_tracked")
        engine_relative = "scripts/current_vps_prelaunch_transition.py"
        engine_blob = _git_bytes(repo, "show", f"{manifest['engine_commit_sha']}:{engine_relative}")
        if hashlib.sha256(engine_blob).hexdigest() != manifest["engine_file_sha256"]:
            raise TransitionError("authorization_engine_provenance_mismatch")
        _git(
            repo,
            "merge-base",
            "--is-ancestor",
            str(manifest["source_application_sha"]),
            str(manifest["target_application_sha"]),
        )
    return manifest


def validate_execution_checkout(repo: Path, manifest: Mapping[str, object]) -> None:
    """Prove the canonical checkout can fast-forward before any host mutation."""
    if _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD") != "main":
        raise TransitionError("execution_checkout_branch_invalid")
    if _git(repo, "status", "--porcelain", "--untracked-files=normal"):
        raise TransitionError("execution_checkout_dirty")
    head = _git(repo, "rev-parse", "HEAD")
    target = str(manifest["target_application_sha"])
    if _git(repo, "rev-parse", f"{target}^{{commit}}") != target:
        raise TransitionError("execution_target_object_invalid")
    _git(repo, "merge-base", "--is-ancestor", head, target)


def validate_evidence(
    path: Path,
    *,
    kind: str,
    schema: int,
    manifest: Mapping[str, object],
    backup_root: Path | None = None,
) -> dict[str, object]:
    value = _read_canonical_json(path, f"{kind}_evidence")
    _validate_checksum(value, f"{kind}_evidence")
    if value.get("schema_version") != schema:
        raise TransitionError(f"{kind}_evidence_schema_invalid")
    if value.get("source_application_sha") != manifest["source_application_sha"]:
        raise TransitionError(f"{kind}_evidence_source_mismatch")
    if value.get("current_db_revision") != CURRENT_REVISION:
        raise TransitionError(f"{kind}_evidence_revision_mismatch")
    if kind == "backup":
        if backup_root is None:
            raise TransitionError("backup_root_required")
        try:
            unresolved_root = backup_root
            backup_root = unresolved_root.resolve(strict=True)
            root_metadata = unresolved_root.lstat()
        except OSError as exc:
            raise TransitionError("backup_root_unsafe") from exc
        root_owner = getattr(os, "geteuid", lambda: None)()
        if (
            not unresolved_root.is_absolute()
            or unresolved_root.is_symlink()
            or unresolved_root != backup_root
            or not stat.S_ISDIR(root_metadata.st_mode)
            or (root_owner is not None and root_metadata.st_uid != root_owner)
            or (os.name == "posix" and root_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
        ):
            raise TransitionError("backup_root_unsafe")
        artifacts = value.get("artifacts")
        required = {"postgresql", "redis", "configuration", "release_state"}
        if not isinstance(artifacts, dict) or set(artifacts) != required:
            raise TransitionError("backup_evidence_artifacts_invalid")
        for record in artifacts.values():
            if (
                not isinstance(record, dict)
                or set(record) != {"path", "sha256", "size_bytes", "verified"}
                or record.get("verified") is not True
                or not isinstance(record.get("path"), str)
                or not isinstance(record.get("sha256"), str)
                or not DIGEST_RE.fullmatch(record["sha256"])
                or not isinstance(record.get("size_bytes"), int)
                or record["size_bytes"] <= 0
            ):
                raise TransitionError("backup_evidence_artifacts_invalid")
            _verify_backup_artifact(Path(record["path"]), record, backup_root)
    elif (
        value.get("status") != "canonical_recovery_verified"
        or value.get("canonical_application_sha") != SOURCE_APPLICATION_SHA
        or value.get("staged_transaction_present") is not False
    ):
        raise TransitionError("recovery_evidence_invalid")
    return value


@dataclass(frozen=True)
class CapacitySnapshot:
    available_ram_bytes: int
    active_swap_bytes: int
    disk_free_bytes: int
    free_inodes: int

    def validate(self) -> str:
        if self.disk_free_bytes < MIN_DISK_FREE_BYTES or self.free_inodes < MIN_FREE_INODES:
            raise TransitionError("capacity_disk_or_inode_insufficient")
        if self.available_ram_bytes >= MIN_AVAILABLE_RAM_BYTES:
            return "available_ram"
        if self.active_swap_bytes >= MIN_ACTIVE_SWAP_BYTES:
            return "precreated_swap"
        raise TransitionError("capacity_memory_insufficient")


def read_capacity(path: Path = Path("/proc/meminfo"), filesystem: Path = Path("/opt/nura")) -> CapacitySnapshot:
    try:
        values: dict[str, int] = {}
        for line in path.read_text(encoding="ascii").splitlines():
            name, raw = line.split(":", 1)
            values[name] = int(raw.strip().split()[0]) * 1024
        disk = shutil.disk_usage(filesystem)
        vfs = os.statvfs(filesystem)
    except (OSError, ValueError, KeyError) as exc:
        raise TransitionError("capacity_probe_failed") from exc
    return CapacitySnapshot(
        available_ram_bytes=values["MemAvailable"],
        active_swap_bytes=values.get("SwapTotal", 0),
        disk_free_bytes=disk.free,
        free_inodes=vfs.f_favail,
    )


class MutationAdapter(Protocol):
    def build_migration_candidate(self, target_sha: str) -> None: ...
    def revalidate_backup_evidence(self) -> None: ...
    def stop_writers(self) -> None: ...
    def apply_migrations(self, target_revision: str) -> None: ...
    def activate_target_with_polling_disabled(self, target_sha: str) -> None: ...
    def verify_target_without_polling(self, target_sha: str) -> None: ...
    def verify_owner_only_without_polling(self, target_sha: str) -> None: ...
    def activate_bot_polling(self) -> None: ...
    def verify_bot_polling(self, target_sha: str) -> None: ...
    def compensate_application_only(self, source_sha: str) -> None: ...
    def verify_source_fleet_at_target_schema(self, source_sha: str) -> None: ...
    def record(self, phase: str, payload: Mapping[str, object]) -> None: ...


@dataclass(frozen=True)
class Preconditions:
    current_application_sha: str
    current_db_revision: str
    current_release_successful: bool
    staged_transaction_present: bool
    duplicate_fleet_present: bool
    source_fleet_identity_verified: bool
    preflight_result: str
    artifact_sha256: str
    manifest_sha256: str
    capacity: CapacitySnapshot


class TransitionEngine:
    """Evaluate every gate before build, stop, migration, or activation."""

    def __init__(self, adapter: MutationAdapter) -> None:
        self.adapter = adapter

    def execute(
        self,
        *,
        authorization: Mapping[str, object],
        preconditions: Preconditions,
        backup_evidence: Mapping[str, object],
        recovery_evidence: Mapping[str, object],
    ) -> None:
        if preconditions.current_application_sha != authorization["source_application_sha"]:
            raise TransitionError("current_application_mismatch")
        if preconditions.current_db_revision != authorization["current_db_revision"]:
            raise TransitionError("current_database_revision_mismatch")
        if not preconditions.current_release_successful:
            raise TransitionError("current_release_not_successful")
        if preconditions.staged_transaction_present:
            raise TransitionError("stale_transaction_not_recovered")
        if preconditions.duplicate_fleet_present:
            raise TransitionError("duplicate_fleet_detected")
        if not preconditions.source_fleet_identity_verified:
            raise TransitionError("source_fleet_identity_mismatch")
        if preconditions.preflight_result != "READY_FOR_HOST_BACKUP_AND_RECOVERY":
            raise TransitionError("offline_preflight_failed")
        if preconditions.artifact_sha256 != authorization["target_artifact_sha256"] or preconditions.manifest_sha256 != authorization["target_manifest_sha256"]:
            raise TransitionError("target_artifact_identity_mismatch")
        if backup_evidence.get("schema_version") != BACKUP_EVIDENCE_SCHEMA:
            raise TransitionError("backup_evidence_missing")
        if recovery_evidence.get("status") != "canonical_recovery_verified":
            raise TransitionError("stale_recovery_evidence_missing")
        capacity_mode = preconditions.capacity.validate()

        target_sha = str(authorization["target_application_sha"])
        self.adapter.record("all_preconditions_passed", {"capacity_mode": capacity_mode})
        self.adapter.build_migration_candidate(target_sha)
        self.adapter.revalidate_backup_evidence()
        self.adapter.stop_writers()
        try:
            self.adapter.apply_migrations(TARGET_REVISION)
        except Exception:
            self.adapter.record("migration_failed", {"database_rollback": False})
            raise
        try:
            self.adapter.activate_target_with_polling_disabled(target_sha)
            self.adapter.verify_target_without_polling(target_sha)
            self.adapter.verify_owner_only_without_polling(target_sha)
            self.adapter.activate_bot_polling()
            self.adapter.verify_bot_polling(target_sha)
        except Exception:
            self.adapter.compensate_application_only(SOURCE_APPLICATION_SHA)
            self.adapter.verify_source_fleet_at_target_schema(SOURCE_APPLICATION_SHA)
            self.adapter.record(
                "application_rollback_verified",
                {"database_revision": TARGET_REVISION, "database_rollback": False},
            )
            raise
        self.adapter.record(
            "transition_succeeded",
            {"application_sha": target_sha, "database_revision": TARGET_REVISION, "cleanup": False},
        )


class HostMutationAdapter:
    """Concrete host adapter; every command is fixed by the audited contract."""

    def __init__(
        self,
        *,
        target_source: Path,
        authorization_manifest: Path,
        archive: Path,
        checksum: Path,
        public_manifest: Path,
        evidence_directory: Path,
        backup_evidence: Path,
        backup_root: Path,
        authorization: Mapping[str, object],
    ) -> None:
        self.target_source = target_source.resolve(strict=True)
        self.target_app = self.target_source / "nura_app"
        self.authorization_manifest = authorization_manifest.resolve(strict=True)
        self.archive = archive.resolve(strict=True)
        self.checksum = checksum.resolve(strict=True)
        self.public_manifest = public_manifest.resolve(strict=True)
        self.evidence_directory = evidence_directory.resolve(strict=True)
        self.backup_evidence = backup_evidence.resolve(strict=True)
        self.backup_root = backup_root.resolve(strict=True)
        self.authorization = dict(authorization)
        self.current_app = Path("/opt/nura/nura_app")
        self.candidate_tag = ""
        self.override = self.evidence_directory / "migration-image.override.yml"
        self.execution_bundle: Path | None = None

    @staticmethod
    def _run(command: Sequence[str], *, cwd: Path | None = None, environment: Mapping[str, str] | None = None) -> str:
        inherited_fds: tuple[int, ...] = ()
        if os.name == "posix" and os.environ.get("NURA_COMMON_LOCK_FD") == "9":
            inherited_fds = (9,)
        result = subprocess.run(
            command,
            cwd=cwd,
            env=dict(environment) if environment is not None else None,
            capture_output=True,
            text=True,
            check=False,
            pass_fds=inherited_fds,
        )
        if result.returncode:
            raise TransitionError("transition_command_failed")
        return result.stdout.strip()

    def _compose(self, app: Path, *arguments: str, polling: str | None = None) -> str:
        environment = os.environ.copy()
        if polling is not None:
            environment["NURA_TG_POLLING_ENABLED"] = polling
        return self._run(
            ["docker", "compose", "--project-directory", str(app), "-f", str(app / "docker-compose.yml"), *arguments],
            cwd=app,
            environment=environment,
        )

    def _verify_fleet_revision(self, expected_sha: str, *, polling: str) -> None:
        for service in APP_SERVICES:
            container = self._compose(
                self.current_app,
                "ps",
                "--status",
                "running",
                "-q",
                service,
                polling=polling,
            )
            if not container or "\n" in container:
                raise TransitionError("fleet_identity_invalid")
            revision = self._run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    '{{index .Config.Labels "org.opencontainers.image.revision"}}',
                    container,
                ]
            )
            if revision != expected_sha:
                raise TransitionError("fleet_identity_invalid")

    def build_migration_candidate(self, target_sha: str) -> None:
        if _git(self.target_source, "rev-parse", "HEAD") != target_sha or _git(self.target_source, "status", "--porcelain"):
            raise TransitionError("target_source_identity_mismatch")
        self.candidate_tag = f"nura-prelaunch-migration:{target_sha}"
        self._run(
            [
                "docker",
                "build",
                "--label",
                f"org.opencontainers.image.revision={target_sha}",
                "--tag",
                self.candidate_tag,
                str(self.target_app),
            ]
        )
        content = (
            "services:\n"
            "  api:\n"
            f"    image: {self.candidate_tag}\n"
            "    build: null\n"
            "    environment:\n"
            "      RUN_MIGRATIONS: \"0\"\n"
        ).encode()
        descriptor = os.open(self.override, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        bundle_output = self._run(
            [
                sys.executable,
                str(self.target_source / "scripts" / "release_execution_bundle.py"),
                "materialize",
                "--repo",
                str(self.target_source),
                "--workflow-sha",
                target_sha,
                "--parent",
                str(self.evidence_directory),
            ]
        )
        bundle = Path(bundle_output)
        try:
            resolved_bundle = bundle.resolve(strict=True)
            resolved_bundle.relative_to(self.evidence_directory)
        except (OSError, ValueError) as exc:
            raise TransitionError("execution_bundle_identity_invalid") from exc
        if resolved_bundle.parent != self.evidence_directory or resolved_bundle.is_symlink():
            raise TransitionError("execution_bundle_identity_invalid")
        self.execution_bundle = resolved_bundle

    def revalidate_backup_evidence(self) -> None:
        validate_evidence(
            self.backup_evidence,
            kind="backup",
            schema=BACKUP_EVIDENCE_SCHEMA,
            manifest=self.authorization,
            backup_root=self.backup_root,
        )

    def stop_writers(self) -> None:
        self._compose(self.current_app, "stop", *WRITER_SERVICES)

    def apply_migrations(self, target_revision: str) -> None:
        self._run(
            [
                "docker",
                "compose",
                "--project-directory",
                str(self.target_app),
                "--env-file",
                str(self.current_app / ".env"),
                "-f",
                str(self.target_app / "docker-compose.yml"),
                "-f",
                str(self.override),
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "python",
                "api",
                "-m",
                "alembic",
                "upgrade",
                target_revision,
            ],
            cwd=self.target_app,
        )

    def activate_target_with_polling_disabled(self, target_sha: str) -> None:
        if self.execution_bundle is None:
            raise TransitionError("execution_bundle_missing")
        environment = os.environ.copy()
        environment.update(
            {
                "NURA_PRELAUNCH_TRANSITION_AUTHORIZATION": str(self.authorization_manifest),
                "NURA_RELEASE_EXECUTION_BUNDLE": str(self.execution_bundle),
                "NURA_WORKFLOW_SHA": target_sha,
                "NURA_TG_POLLING_ENABLED": "false",
            }
        )
        self._run(
            [
                "bash",
                str(self.execution_bundle / "deploy.sh"),
                "deploy",
                target_sha,
                str(self.archive),
                str(self.checksum),
                str(self.public_manifest),
            ],
            environment=environment,
        )

    def verify_target_without_polling(self, target_sha: str) -> None:
        self._verify_fleet_revision(target_sha, polling="false")
        raw_readiness = self._run(["curl", "--fail", "--silent", "http://127.0.0.1:8000/ready"])
        try:
            readiness = json.loads(raw_readiness)
        except json.JSONDecodeError as exc:
            raise TransitionError("target_readiness_invalid") from exc
        dependencies = readiness.get("dependencies") if isinstance(readiness, dict) else None
        if (
            not isinstance(readiness, dict)
            or readiness.get("status") != "ready"
            or not isinstance(dependencies, dict)
            or dependencies.get("database") != "ok"
            or dependencies.get("redis") != "ok"
            or dependencies.get("ai_configuration") != "ok"
            or dependencies.get("payment_configuration") != "disabled"
        ):
            raise TransitionError("target_readiness_invalid")
        worker_ping = self._compose(
            self.current_app,
            "exec",
            "-T",
            "celery-worker",
            "celery",
            "-A",
            "core.tasks",
            "inspect",
            "ping",
            "--timeout",
            "10",
            polling="false",
        )
        if "pong" not in worker_ping.lower() or "no nodes replied" in worker_ping.lower():
            raise TransitionError("worker_ping_failed")
        beat_container = self._compose(
            self.current_app,
            "ps",
            "--status",
            "running",
            "-q",
            "celery-beat",
            polling="false",
        )
        if not beat_container:
            raise TransitionError("beat_process_not_running")
        source = self._compose(
            self.current_app,
            "exec",
            "-T",
            "celery-beat",
            "python",
            "-c",
            "from core.tasks import celery_app; print(','.join(sorted(celery_app.conf.beat_schedule)))",
            polling="false",
        )
        if any(item in source for item in ("charge-recurring", "expiring-subscriptions", "downgrade-expired")):
            raise TransitionError("payment_schedule_not_contained")
        polling = self._compose(
            self.current_app,
            "exec",
            "-T",
            "bot",
            "python",
            "-c",
            "from core.config import settings; print(str(settings.telegram_polling_enabled).lower())",
            polling="false",
        )
        if polling != "false":
            raise TransitionError("bot_polling_started_early")

    def verify_owner_only_without_polling(self, target_sha: str) -> None:
        del target_sha
        identity = self._compose(
            self.current_app,
            "exec",
            "-T",
            "bot",
            "python",
            "-c",
            "from core.config import settings; allowed=settings.telegram_restricted_allowed_ids; safe=(settings.is_owner_prelaunch and len(allowed)==1 and settings.admin_telegram_id==allowed[0] and not settings.payments_enabled and not any((settings.yookassa_shop_id,settings.yookassa_secret_key,settings.yookassa_secret_key_file)) and not settings.telegram_polling_enabled); raise SystemExit(0 if safe else 1)",
            polling="false",
        )
        if identity:
            raise TransitionError("owner_only_runtime_output_invalid")

    def activate_bot_polling(self) -> None:
        self._compose(self.current_app, "up", "-d", "--no-deps", "--force-recreate", "bot", polling="true")

    def verify_bot_polling(self, target_sha: str) -> None:
        del target_sha
        polling = self._compose(
            self.current_app,
            "exec",
            "-T",
            "bot",
            "python",
            "-c",
            "from core.config import settings; print(str(settings.telegram_polling_enabled).lower())",
            polling="true",
        )
        if polling != "true":
            raise TransitionError("bot_polling_verification_failed")

    def compensate_application_only(self, source_sha: str) -> None:
        if self.execution_bundle is None:
            raise TransitionError("execution_bundle_missing")
        environment = os.environ.copy()
        environment.update(
            {
                "NURA_PRELAUNCH_TRANSITION_AUTHORIZATION": str(self.authorization_manifest),
                "NURA_RELEASE_EXECUTION_BUNDLE": str(self.execution_bundle),
                "NURA_WORKFLOW_SHA": _git(self.target_source, "rev-parse", "HEAD"),
                "NURA_TG_POLLING_ENABLED": "false",
            }
        )
        self._run(["bash", str(self.execution_bundle / "deploy.sh"), "rollback", source_sha], environment=environment)

    def verify_source_fleet_at_target_schema(self, source_sha: str) -> None:
        self._verify_fleet_revision(source_sha, polling="false")
        self._run(["curl", "--fail", "--silent", "http://127.0.0.1:8000/ready"])
        revision = self._compose(
            self.current_app,
            "exec",
            "-T",
            "postgres",
            "sh",
            "-lc",
            'exec psql -X -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM alembic_version"',
        )
        if revision != TARGET_REVISION:
            raise TransitionError("application_compensation_schema_identity_mismatch")

    def record(self, phase: str, payload: Mapping[str, object]) -> None:
        record = {
            "schema_version": 1,
            "phase": phase,
            "payload": dict(payload),
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        record["checksum"] = payload_checksum(record)
        destination = self.evidence_directory / f"{len(tuple(self.evidence_directory.glob('*.json'))):03d}-{phase}.json"
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json(record))


def verify_deploy_authorization(
    manifest: Mapping[str, object],
    *,
    source_sha: str,
    target_sha: str,
    database_revision: str,
) -> None:
    if (
        source_sha != manifest["source_application_sha"]
        or target_sha != manifest["target_application_sha"]
        or database_revision != manifest["target_db_revision"]
    ):
        raise TransitionError("deploy_authorization_mismatch")


def _sha256(path: Path) -> str:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise TransitionError("artifact_path_unsafe")
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise TransitionError("artifact_path_unreadable") from exc


def _verify_backup_artifact(
    artifact: Path,
    record: Mapping[str, object],
    backup_root: Path,
) -> None:
    """Hash one direct-child backup through the same checked descriptor."""
    if not artifact.is_absolute() or artifact.parent != backup_root or not artifact.name:
        raise TransitionError("backup_evidence_artifact_unsafe")
    root_descriptor: int | None = None
    descriptor: int | None = None
    try:
        owner = getattr(os, "geteuid", lambda: None)()
        if os.name == "posix":
            root_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
            root_descriptor = os.open(backup_root, root_flags)
            root_info = os.fstat(root_descriptor)
            if (
                not stat.S_ISDIR(root_info.st_mode)
                or (owner is not None and root_info.st_uid != owner)
                or root_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            ):
                raise TransitionError("backup_root_unsafe")
            descriptor = os.open(
                artifact.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_descriptor,
            )
        else:
            if artifact.is_symlink():
                raise TransitionError("backup_evidence_artifact_unsafe")
            descriptor = os.open(artifact, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or (owner is not None and before.st_uid != owner)
            or (os.name == "posix" and stat.S_IMODE(before.st_mode) not in {0o400, 0o600})
            or before.st_size != record["size_bytes"]
        ):
            raise TransitionError("backup_evidence_artifact_mismatch")
        digest = hashlib.sha256()
        for chunk in iter(lambda: os.read(descriptor, 1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(descriptor)
        if root_descriptor is not None:
            path_after = os.stat(
                artifact.name,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
        else:
            path_after = artifact.lstat()
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_nlink,
            before.st_uid,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_nlink,
            after.st_uid,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if (
            identity_after != identity_before
            or (path_after.st_dev, path_after.st_ino) != (before.st_dev, before.st_ino)
            or not stat.S_ISREG(path_after.st_mode)
            or digest.hexdigest() != record["sha256"]
        ):
            raise TransitionError("backup_evidence_artifact_mismatch")
    except TransitionError:
        raise
    except OSError as exc:
        raise TransitionError("backup_evidence_artifact_unreadable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if root_descriptor is not None:
            os.close(root_descriptor)


def _current_database_revision(compose_file: Path) -> str:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(compose_file.parent),
            "-f",
            str(compose_file),
            "exec",
            "-T",
            "postgres",
            "sh",
            "-lc",
            'exec psql -X -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM alembic_version"',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode or not re.fullmatch(r"[0-9a-z]{12,32}", result.stdout.strip()):
        raise TransitionError("database_revision_probe_failed")
    return result.stdout.strip()


def _duplicate_fleet_present() -> bool:
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Label \"com.docker.compose.service\"}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise TransitionError("fleet_probe_failed")
    names = result.stdout.splitlines()
    return any(names.count(service) > 1 for service in APP_SERVICES)


def _source_fleet_identity_verified(
    compose_file: Path,
    current_state: Mapping[str, object],
    expected_sha: str,
) -> bool:
    mappings = current_state.get("per_service_image_mapping")
    image_ids = current_state.get("per_service_image_ids")
    if not isinstance(mappings, dict) or not isinstance(image_ids, dict):
        return False
    for service in APP_SERVICES:
        expected_image = mappings.get(service)
        expected_image_id = image_ids.get(service)
        if (
            not isinstance(expected_image, str)
            or not expected_image
            or not isinstance(expected_image_id, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", expected_image_id) is None
        ):
            return False
        containers = subprocess.run(
            [
                "docker",
                "compose",
                "--project-directory",
                str(compose_file.parent),
                "-f",
                str(compose_file),
                "ps",
                "--status",
                "running",
                "-q",
                service,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        container_ids = containers.stdout.splitlines()
        if containers.returncode or len(container_ids) != 1:
            return False
        inspection = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                '{{.State.Running}}|{{.Config.Image}}|{{.Image}}|{{index .Config.Labels "org.opencontainers.image.revision"}}',
                container_ids[0],
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if inspection.returncode:
            return False
        fields = inspection.stdout.strip().split("|")
        if fields != ["true", expected_image, expected_image_id, expected_sha]:
            return False
    return True


def execute_from_cli(args: argparse.Namespace) -> None:
    repo = args.repo.resolve(strict=True)
    manifest = validate_authorization_manifest(args.manifest, repo=repo)
    validate_execution_checkout(repo, manifest)
    validate_migration_contract(args.target_source / "nura_app" / "alembic" / "versions")
    backup = validate_evidence(
        args.backup_evidence,
        kind="backup",
        schema=BACKUP_EVIDENCE_SCHEMA,
        manifest=manifest,
        backup_root=args.backup_root,
    )
    recovery = validate_evidence(
        args.recovery_evidence,
        kind="recovery",
        schema=RECOVERY_EVIDENCE_SCHEMA,
        manifest=manifest,
    )
    if not args.evidence_directory.is_absolute():
        raise TransitionError("evidence_directory_unsafe")
    evidence_metadata = args.evidence_directory.lstat()
    if (
        args.evidence_directory.is_symlink()
        or not stat.S_ISDIR(evidence_metadata.st_mode)
        or (os.name != "nt" and stat.S_IMODE(evidence_metadata.st_mode) != 0o700)
    ):
        raise TransitionError("evidence_directory_unsafe")
    preflight = run_preflight(
        env_file=args.env_file,
        compose_file=args.target_source / "nura_app" / "docker-compose.yml",
        secrets_dir=args.secrets_dir,
        versions_dir=args.target_source / "nura_app" / "alembic" / "versions",
        allowed_owner_ids=frozenset({0}),
        execution=True,
        authorization_manifest=args.manifest,
    )
    current = _read_canonical_json(args.current_release_state, "current_release_state")
    if (
        not args.p7b_transaction_directory.is_dir()
        or args.p7b_transaction_directory.is_symlink()
    ):
        raise TransitionError("p7b_transaction_directory_unsafe")
    staged = any(args.p7b_transaction_directory.glob("*.json"))
    archive_digest = _sha256(args.archive)
    try:
        checksum_tokens = args.checksum.read_text(encoding="ascii").strip().split()
    except (OSError, UnicodeDecodeError) as exc:
        raise TransitionError("artifact_checksum_unreadable") from exc
    if checksum_tokens not in ([archive_digest], [archive_digest, args.archive.name]):
        raise TransitionError("artifact_checksum_mismatch")
    preconditions = Preconditions(
        current_application_sha=str(current.get("sha", "")),
        current_db_revision=_current_database_revision(args.current_compose),
        current_release_successful=current.get("status") == "successful",
        staged_transaction_present=staged,
        duplicate_fleet_present=_duplicate_fleet_present(),
        source_fleet_identity_verified=_source_fleet_identity_verified(
            args.current_compose,
            current,
            str(manifest["source_application_sha"]),
        ),
        preflight_result=str(preflight["result"]),
        artifact_sha256=archive_digest,
        manifest_sha256=_sha256(args.public_manifest),
        capacity=read_capacity(filesystem=repo),
    )
    adapter = HostMutationAdapter(
        target_source=args.target_source,
        authorization_manifest=args.manifest,
        archive=args.archive,
        checksum=args.checksum,
        public_manifest=args.public_manifest,
        evidence_directory=args.evidence_directory,
        backup_evidence=args.backup_evidence,
        backup_root=args.backup_root,
        authorization=manifest,
    )
    TransitionEngine(adapter).execute(
        authorization=manifest,
        preconditions=preconditions,
        backup_evidence=backup,
        recovery_evidence=recovery,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate-authorization")
    validate_parser.add_argument("--manifest", type=Path, required=True)
    validate_parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    deploy_parser = subparsers.add_parser("verify-deploy-authorization")
    deploy_parser.add_argument("--manifest", type=Path, required=True)
    deploy_parser.add_argument("--source-sha", required=True)
    deploy_parser.add_argument("--target-sha", required=True)
    deploy_parser.add_argument("--database-revision", required=True)
    deploy_parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    execute_parser = subparsers.add_parser("execute")
    execute_parser.add_argument("--manifest", type=Path, required=True)
    execute_parser.add_argument("--backup-evidence", type=Path, required=True)
    execute_parser.add_argument(
        "--backup-root",
        type=Path,
        default=Path("/var/backups/nura-release-transition"),
    )
    execute_parser.add_argument("--recovery-evidence", type=Path, required=True)
    execute_parser.add_argument("--target-source", type=Path, required=True)
    execute_parser.add_argument("--archive", type=Path, required=True)
    execute_parser.add_argument("--checksum", type=Path, required=True)
    execute_parser.add_argument("--public-manifest", type=Path, required=True)
    execute_parser.add_argument("--evidence-directory", type=Path, required=True)
    execute_parser.add_argument("--repo", type=Path, default=Path("/opt/nura"))
    execute_parser.add_argument("--env-file", type=Path, default=Path("/opt/nura/nura_app/.env"))
    execute_parser.add_argument("--secrets-dir", type=Path, default=Path("/opt/nura/secrets/production"))
    execute_parser.add_argument("--current-compose", type=Path, default=Path("/opt/nura/nura_app/docker-compose.yml"))
    execute_parser.add_argument("--current-release-state", type=Path, default=Path("/var/lib/nura-release-state/current.json"))
    execute_parser.add_argument("--p7b-transaction-directory", type=Path, default=Path("/var/lib/nura-release-state/p7b/transactions"))
    args = parser.parse_args(argv)
    if args.command == "execute" and os.environ.get("NURA_COMMON_LOCK_FD") != "9":
        lock_helper = Path(__file__).with_name("release_lock.py")
        os.execv(
            sys.executable,
            [
                sys.executable,
                str(lock_helper),
                "--lock-file",
                "/run/lock/nura-deploy.lock",
                "--",
                sys.executable,
                str(Path(__file__).resolve()),
                *sys.argv[1:],
            ],
        )
    try:
        if args.command == "execute":
            execute_from_cli(args)
            output = {"status": "PASS", "result": "transition_succeeded"}
        else:
            manifest = validate_authorization_manifest(args.manifest, repo=args.repo)
            if args.command == "verify-deploy-authorization":
                verify_deploy_authorization(
                    manifest,
                    source_sha=args.source_sha,
                    target_sha=args.target_sha,
                    database_revision=args.database_revision,
                )
            output = {"status": "PASS", "target": manifest["target_application_sha"]}
        code = 0
    except TransitionError as exc:
        output = {"status": "FAIL", "error": str(exc)}
        code = 1
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
