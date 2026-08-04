#!/usr/bin/env python3
"""Audited, manifest-only engine for the owner-only clean installation.

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
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
APP_SERVICES = ("api", "bot", "celery-worker", "celery-beat", "admin-bot")
DATA_SERVICES = ("postgres", "redis")
APPLICATION_PROCESS_RE = re.compile(
    r"(?:^|\s)(?:"
    r"uvicorn\s+api\.main:app|"
    r"python(?:3)?\s+-m\s+(?:bot|admin_bot)\.main|"
    r"celery\s+-A\s+core\.tasks\s+(?:worker|beat)"
    r")(?:\s|$)"
)
PROTECTED_VOLUMES = (
    "nura_app_postgres_data",
    "nura_app_redis_data",
    "nura_app_reports_output",
)
AUTHORIZATION_SCHEMA = 4
BACKUP_EVIDENCE_SCHEMA = 1
MIGRATION_EVIDENCE_SCHEMA = 1
POST_MIGRATION_BACKUP_EVIDENCE_SCHEMA = 1
TARGET_COMPOSE_HANDOFF_SCHEMA = 1
REMOVAL_EVIDENCE_SCHEMA = "1.0"
SOURCE_RUNTIME_MODE = "application-layer-absent"
INSTALLATION_MODE = "clean-install-resume-post-migration"
ACTIVATION_COMPOSE_MODE = "exact-target-only"
MIGRATION_STATUS = "preapplied-and-verified"
POST_ACTIVATION_FAILURE_MODE = "leave-application-stopped"
OWNER_APPROVAL = "approval-owner-prelaunch-activation-resume-v4"
SECRET_PROFILE_VERSION = "production-files-v1"
MIN_AVAILABLE_RAM_BYTES = 3 * 1024**3
MIN_ACTIVE_SWAP_BYTES = 2 * 1024**3
MIN_DISK_FREE_BYTES = 6 * 1024**3
MIN_FREE_INODES = 50_000
P7B_QUIESCENT_PHASES = {
    "prepared",
    "baseline_ready",
    "complete",
    "stage1_compensated",
    "stage2_compensated",
    "stale_stage2_recovered",
}
CURRENT_RELEASE_STATE = Path("/var/lib/nura-release-state/current.json")
CURRENT_STATIC_LINK = Path("/var/www/nura-releases/current")
P7B_TRANSACTION_DIRECTORY = Path("/var/lib/nura-release-state/p7b/transactions")
PRODUCTION_SECRETS_DIRECTORY = Path("/opt/nura/secrets/production")


def _is_application_container(
    project: str,
    service: str,
    revision: str,
    image: str,
) -> bool:
    if service in DATA_SERVICES:
        return False
    if project == "nura_app" and service in APP_SERVICES:
        return True
    if project:
        return False
    known_nura_image = (
        image == "nura-release"
        or image.startswith("nura-release:")
        or image.startswith("nura-release-candidate:")
        or image.startswith("nura-prelaunch-migration:")
        or image.startswith("nura-legacy:")
    )
    return known_nura_image or (service in APP_SERVICES and SHA_RE.fullmatch(revision) is not None)


class TransitionError(RuntimeError):
    """A bounded transition failure that contains neither credentials nor PII."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def payload_checksum(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def compact_payload_checksum(value: Mapping[str, object]) -> str:
    """Checksum canonical JSON without LF for the existing cleanup evidence."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


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


def _validate_checksum(
    value: dict[str, object],
    label: str,
    *,
    compact: bool = False,
) -> None:
    checksum = value.get("checksum")
    payload = {key: item for key, item in value.items() if key != "checksum"}
    if not isinstance(checksum, str) or not DIGEST_RE.fullmatch(checksum):
        raise TransitionError(f"{label}_checksum_invalid")
    expected = compact_payload_checksum(payload) if compact else payload_checksum(payload)
    if expected != checksum:
        raise TransitionError(f"{label}_checksum_mismatch")


def _validate_root_owned_private_directory(path: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        metadata = path.lstat()
    except OSError as exc:
        raise TransitionError(f"{label}_unsafe") from exc
    effective_uid = getattr(os, "geteuid", lambda: None)()
    if (
        not path.is_absolute()
        or path.is_symlink()
        or path != resolved
        or not stat.S_ISDIR(metadata.st_mode)
        or (
            os.name == "posix"
            and (
                effective_uid != 0
                or metadata.st_uid != effective_uid
                or stat.S_IMODE(metadata.st_mode) != 0o700
            )
        )
    ):
        raise TransitionError(f"{label}_unsafe")
    return resolved


def _validate_resume_cli_paths(args: argparse.Namespace, repo: Path) -> None:
    """Reject alternate runtime/state inputs before any preflight or DB probe."""

    expected = {
        "target_source": repo,
        "env_file": repo / "nura_app" / ".env",
        "current_compose": repo / "nura_app" / "docker-compose.yml",
        "current_release_state": CURRENT_RELEASE_STATE,
        "current_static_link": CURRENT_STATIC_LINK,
        "p7b_transaction_directory": P7B_TRANSACTION_DIRECTORY,
        "secrets_dir": PRODUCTION_SECRETS_DIRECTORY,
    }
    if os.name == "posix" and repo != Path("/opt/nura"):
        raise TransitionError("resume_runtime_path_invalid")
    for name, exact in expected.items():
        value = getattr(args, name)
        if not isinstance(value, Path) or not value.is_absolute() or value != exact:
            raise TransitionError("resume_runtime_path_invalid")
    evidence = _validate_root_owned_private_directory(
        args.evidence_directory,
        "evidence_directory",
    )
    try:
        evidence.relative_to(Path("/var/lib/nura-release-state/prelaunch-evidence"))
    except ValueError as exc:
        raise TransitionError("evidence_directory_unsafe") from exc


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
        "source_static_sha",
        "target_application_sha",
        "engine_commit_sha",
        "engine_file_sha256",
        "current_db_revision",
        "target_db_revision",
        "original_db_revision",
        "ordered_migration_revisions",
        "migration_chain_digest",
        "migration_status",
        "allow_migration_execution",
        "required_secret_profile_version",
        "original_backup_evidence_schema",
        "original_backup_evidence_checksum",
        "original_backup_evidence_sha256",
        "migration_evidence_schema",
        "migration_evidence_checksum",
        "migration_evidence_sha256",
        "post_migration_backup_evidence_schema",
        "post_migration_backup_evidence_checksum",
        "post_migration_backup_evidence_sha256",
        "application_layer_removal_evidence_schema",
        "application_layer_removal_evidence_checksum",
        "application_layer_removal_evidence_sha256",
        "expected_database_counts",
        "capacity_acknowledgement",
        "source_runtime_mode",
        "installation_mode",
        "activation_compose_mode",
        "allow_source_fleet_start",
        "require_application_layer_removal_evidence",
        "post_activation_failure_mode",
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
        "original_backup_evidence_checksum",
        "original_backup_evidence_sha256",
        "migration_evidence_checksum",
        "migration_evidence_sha256",
        "post_migration_backup_evidence_checksum",
        "post_migration_backup_evidence_sha256",
        "application_layer_removal_evidence_checksum",
        "application_layer_removal_evidence_sha256",
    ):
        if not isinstance(manifest.get(key), str) or not DIGEST_RE.fullmatch(manifest[key]):
            raise TransitionError("authorization_manifest_digest_invalid")
    expected_revisions = [item.revision for item in EXPECTED_MIGRATIONS]
    if (
        manifest["source_application_sha"] != SOURCE_APPLICATION_SHA
        or manifest["source_static_sha"] != SOURCE_APPLICATION_SHA
        or manifest["target_application_sha"] == SOURCE_APPLICATION_SHA
        or manifest["engine_commit_sha"] != manifest["target_application_sha"]
        or manifest["authorization_base_commit_sha"] != manifest["target_application_sha"]
        or manifest["current_db_revision"] != TARGET_REVISION
        or manifest["target_db_revision"] != TARGET_REVISION
        or manifest["original_db_revision"] != CURRENT_REVISION
        or manifest["ordered_migration_revisions"] != expected_revisions
        or manifest["migration_chain_digest"] != MIGRATION_CHAIN_DIGEST
        or manifest["migration_status"] != MIGRATION_STATUS
        or manifest["allow_migration_execution"] is not False
        or manifest["required_secret_profile_version"] != SECRET_PROFILE_VERSION
        or manifest["original_backup_evidence_schema"] != BACKUP_EVIDENCE_SCHEMA
        or manifest["migration_evidence_schema"] != MIGRATION_EVIDENCE_SCHEMA
        or manifest["post_migration_backup_evidence_schema"]
        != POST_MIGRATION_BACKUP_EVIDENCE_SCHEMA
        or manifest["application_layer_removal_evidence_schema"] != REMOVAL_EVIDENCE_SCHEMA
        or manifest["expected_database_counts"]
        != {"guest_profiles": 5, "payments": 0, "reports": 2, "users": 2}
        or manifest["source_runtime_mode"] != SOURCE_RUNTIME_MODE
        or manifest["installation_mode"] != INSTALLATION_MODE
        or manifest["activation_compose_mode"] != ACTIVATION_COMPOSE_MODE
        or manifest["allow_source_fleet_start"] is not False
        or manifest["require_application_layer_removal_evidence"] is not True
        or manifest["post_activation_failure_mode"] != POST_ACTIVATION_FAILURE_MODE
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
        approvals != [OWNER_APPROVAL]
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


def validate_target_source_checkout(
    target_source: Path,
    manifest: Mapping[str, object],
    *,
    engine_root: Path = REPO_ROOT,
) -> None:
    """Prove offline modules come from the exact clean target checkout."""

    try:
        source = target_source.resolve(strict=True)
        root = engine_root.resolve(strict=True)
    except OSError as exc:
        raise TransitionError("target_source_identity_mismatch") from exc
    if target_source.is_symlink() or source != root:
        raise TransitionError("target_source_identity_mismatch")
    try:
        git_root = Path(_git(source, "rev-parse", "--show-toplevel")).resolve(
            strict=True
        )
    except OSError as exc:
        raise TransitionError("target_source_identity_mismatch") from exc
    if git_root != source:
        raise TransitionError("target_source_identity_mismatch")
    if _git(source, "rev-parse", "HEAD") != manifest["target_application_sha"]:
        raise TransitionError("target_source_identity_mismatch")
    if _git(source, "status", "--porcelain", "--untracked-files=normal"):
        raise TransitionError("target_source_identity_mismatch")


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
    if kind == "original_backup":
        if (
            value.get("checksum") != manifest["original_backup_evidence_checksum"]
            or hashlib.sha256(path.read_bytes()).hexdigest()
            != manifest["original_backup_evidence_sha256"]
        ):
            raise TransitionError("original_backup_evidence_identity_mismatch")
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
    else:
        raise TransitionError("evidence_kind_invalid")
    return value


def validate_migration_evidence(
    path: Path,
    *,
    manifest: Mapping[str, object],
) -> dict[str, object]:
    """Validate the exact prior migration completion and contained incident."""

    value = _read_canonical_json(path, "migration_evidence")
    _validate_checksum(value, "migration_evidence")
    required = {
        "schema_version",
        "kind",
        "original_db_revision",
        "current_db_revision",
        "target_db_revision",
        "ordered_migration_revisions",
        "migration_chain_digest",
        "migration_completed_at",
        "database_counts",
        "application_containers",
        "application_processes",
        "automatic_downgrade",
        "source_fleet_started",
        "legacy_bot_incident",
        "provider_call_certainty",
        "current_safe_state",
        "checksum",
    }
    expected_counts = manifest["expected_database_counts"]
    if (
        set(value) != required
        or value.get("schema_version") != MIGRATION_EVIDENCE_SCHEMA
        or value.get("kind") != "post_migration_completion_evidence"
        or value.get("original_db_revision") != CURRENT_REVISION
        or value.get("current_db_revision") != TARGET_REVISION
        or value.get("target_db_revision") != TARGET_REVISION
        or value.get("ordered_migration_revisions")
        != [item.revision for item in EXPECTED_MIGRATIONS]
        or value.get("migration_chain_digest") != MIGRATION_CHAIN_DIGEST
        or value.get("database_counts") != expected_counts
        or value.get("application_containers") != 0
        or value.get("application_processes") != 0
        or value.get("automatic_downgrade") is not False
        or value.get("source_fleet_started") is not False
        or value.get("provider_call_certainty")
        != "unknown-for-contained-legacy-polling-interval"
        or value.get("current_safe_state") != "application-layer-absent"
        or value.get("checksum") != manifest["migration_evidence_checksum"]
        or hashlib.sha256(path.read_bytes()).hexdigest()
        != manifest["migration_evidence_sha256"]
    ):
        raise TransitionError("migration_evidence_identity_invalid")
    try:
        completed = datetime.fromisoformat(
            str(value["migration_completed_at"]).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise TransitionError("migration_evidence_timestamp_invalid") from exc
    if completed.tzinfo is None:
        raise TransitionError("migration_evidence_timestamp_invalid")
    incident = value.get("legacy_bot_incident")
    if (
        not isinstance(incident, dict)
        or set(incident) != {"contained", "evidence_path", "evidence_sha256"}
        or incident.get("contained") is not True
        or not isinstance(incident.get("evidence_path"), str)
        or not isinstance(incident.get("evidence_sha256"), str)
        or DIGEST_RE.fullmatch(str(incident["evidence_sha256"])) is None
    ):
        raise TransitionError("migration_evidence_incident_invalid")
    incident_path = Path(str(incident["evidence_path"]))
    if (
        not incident_path.is_absolute()
        or _sha256(incident_path) != incident["evidence_sha256"]
    ):
        raise TransitionError("migration_evidence_incident_invalid")
    return value


def validate_post_migration_backup_evidence(
    path: Path,
    *,
    manifest: Mapping[str, object],
    backup_root: Path,
) -> dict[str, object]:
    """Validate the private PostgreSQL 16 checkpoint made after migration."""

    value = _read_canonical_json(path, "post_migration_backup_evidence")
    _validate_checksum(value, "post_migration_backup_evidence")
    required = {
        "schema_version",
        "kind",
        "source_application_sha",
        "target_application_sha",
        "current_db_revision",
        "database_counts",
        "postgresql",
        "created_at",
        "checksum",
    }
    if (
        set(value) != required
        or value.get("schema_version") != POST_MIGRATION_BACKUP_EVIDENCE_SCHEMA
        or value.get("kind") != "post_migration_postgresql_checkpoint"
        or value.get("source_application_sha") != manifest["source_application_sha"]
        or value.get("target_application_sha") != manifest["target_application_sha"]
        or value.get("current_db_revision") != TARGET_REVISION
        or value.get("database_counts") != manifest["expected_database_counts"]
        or value.get("checksum")
        != manifest["post_migration_backup_evidence_checksum"]
        or hashlib.sha256(path.read_bytes()).hexdigest()
        != manifest["post_migration_backup_evidence_sha256"]
    ):
        raise TransitionError("post_migration_backup_evidence_identity_invalid")
    record = value.get("postgresql")
    if (
        not isinstance(record, dict)
        or set(record)
        != {
            "format",
            "major_version",
            "no_owner_acl",
            "path",
            "restore_list_verified",
            "sha256",
            "size_bytes",
        }
        or record.get("format") != "custom"
        or record.get("major_version") != 16
        or record.get("no_owner_acl") is not True
        or record.get("restore_list_verified") is not True
        or not isinstance(record.get("path"), str)
        or not isinstance(record.get("sha256"), str)
        or DIGEST_RE.fullmatch(str(record["sha256"])) is None
        or not isinstance(record.get("size_bytes"), int)
        or int(record["size_bytes"]) <= 0
    ):
        raise TransitionError("post_migration_backup_artifact_invalid")
    try:
        resolved_root = backup_root.resolve(strict=True)
        root_metadata = backup_root.lstat()
    except OSError as exc:
        raise TransitionError("post_migration_backup_root_unsafe") from exc
    if (
        not backup_root.is_absolute()
        or backup_root.is_symlink()
        or backup_root != resolved_root
        or not stat.S_ISDIR(root_metadata.st_mode)
        or (os.name == "posix" and stat.S_IMODE(root_metadata.st_mode) != 0o700)
    ):
        raise TransitionError("post_migration_backup_root_unsafe")
    _verify_backup_artifact(Path(str(record["path"])), record, resolved_root)
    try:
        created = datetime.fromisoformat(str(value["created_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise TransitionError("post_migration_backup_timestamp_invalid") from exc
    if created.tzinfo is None:
        raise TransitionError("post_migration_backup_timestamp_invalid")
    return value


def validate_resume_evidence_timeline(
    migration_evidence: Mapping[str, object],
    post_migration_backup_evidence: Mapping[str, object],
    authorization: Mapping[str, object],
) -> None:
    """Prove migration preceded its checkpoint and both preceded authorization."""

    try:
        migration_completed = datetime.fromisoformat(
            str(migration_evidence["migration_completed_at"]).replace("Z", "+00:00")
        )
        checkpoint_created = datetime.fromisoformat(
            str(post_migration_backup_evidence["created_at"]).replace("Z", "+00:00")
        )
        authorization_created = datetime.fromisoformat(
            str(authorization["valid_from"]).replace("Z", "+00:00")
        )
    except (KeyError, ValueError) as exc:
        raise TransitionError("resume_evidence_timeline_invalid") from exc
    if (
        migration_completed.tzinfo is None
        or checkpoint_created.tzinfo is None
        or authorization_created.tzinfo is None
        or not migration_completed <= checkpoint_created <= authorization_created
    ):
        raise TransitionError("resume_evidence_timeline_invalid")


def validate_removal_evidence(
    path: Path,
    *,
    manifest: Mapping[str, object],
) -> dict[str, object]:
    """Validate the exact completed legacy-application removal proof."""
    value = _read_canonical_json(path, "removal_evidence")
    _validate_checksum(value, "removal_evidence", compact=True)
    if (
        value.get("schema_version") != REMOVAL_EVIDENCE_SCHEMA
        or value.get("kind") != "legacy_application_layer_removal_evidence"
        or value.get("phase") != "complete"
        or value.get("result") != "APPLICATION_LAYER_RESET_PASS"
        or value.get("checksum")
        != manifest["application_layer_removal_evidence_checksum"]
        or hashlib.sha256(path.read_bytes()).hexdigest()
        != manifest["application_layer_removal_evidence_sha256"]
    ):
        raise TransitionError("removal_evidence_identity_invalid")
    if (
        value.get("application_containers_after") != []
        or value.get("application_services_running") is not False
        or value.get("active_transactions_after") != []
        or value.get("provider_calls") != 0
        or value.get("migrations_applied") != 0
        or value.get("deploy_performed") is not False
        or value.get("volumes_deleted") != 0
        or value.get("images_deleted") != 0
        or value.get("releases_deleted") != 0
        or value.get("static_switched") is not False
        or value.get("database_mutated_by_cleanup") is not False
    ):
        raise TransitionError("removal_evidence_result_invalid")
    processes = value.get("processes_after")
    if not isinstance(processes, dict) or any(processes.get(key) != 0 for key in ("application", "controllers", "provider_facing")):
        raise TransitionError("removal_evidence_processes_invalid")
    protected = value.get("protected_containers_after")
    if (
        not isinstance(protected, list)
        or {item.get("compose_service") for item in protected if isinstance(item, dict)}
        != set(DATA_SERVICES)
        or any(
            not isinstance(item, dict)
            or item.get("state") != "running"
            or item.get("health") != "healthy"
            for item in protected
        )
    ):
        raise TransitionError("removal_evidence_data_services_invalid")
    volumes = value.get("protected_volumes_after")
    if (
        not isinstance(volumes, list)
        or {item.get("name") for item in volumes if isinstance(item, dict)}
        != set(PROTECTED_VOLUMES)
    ):
        raise TransitionError("removal_evidence_volumes_invalid")
    database = value.get("database_after")
    expected_counts = manifest["expected_database_counts"]
    if (
        not isinstance(database, dict)
        or database.get("revision") != CURRENT_REVISION
        or any(database.get(key) != expected_counts[key] for key in expected_counts)
        or database.get("other_sessions") != 0
    ):
        raise TransitionError("removal_evidence_database_invalid")
    release = value.get("release_state_after")
    if (
        not isinstance(release, dict)
        or release.get("canonical_sha") != manifest["source_application_sha"]
        or release.get("static_sha") != manifest["source_static_sha"]
    ):
        raise TransitionError("removal_evidence_release_state_invalid")
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
    def prepare_target_execution(self, target_sha: str) -> None: ...
    def revalidate_original_backup_evidence(self) -> None: ...
    def revalidate_removal_evidence(self) -> None: ...
    def revalidate_migration_evidence(self) -> None: ...
    def revalidate_post_migration_backup_evidence(self) -> None: ...
    def verify_application_layer_absent(self) -> None: ...
    def activate_target_with_polling_disabled(self, target_sha: str) -> None: ...
    def verify_target_without_polling(self, target_sha: str) -> None: ...
    def verify_owner_only_without_polling(self, target_sha: str) -> None: ...
    def activate_bot_polling(self) -> None: ...
    def verify_bot_polling(self, target_sha: str) -> None: ...
    def leave_application_stopped(self, source_sha: str, target_sha: str) -> None: ...
    def verify_application_stopped(
        self,
        source_sha: str,
        expected_db_revision: str | None,
    ) -> None: ...
    def record(self, phase: str, payload: Mapping[str, object]) -> None: ...


@dataclass(frozen=True)
class Preconditions:
    current_application_sha: str
    current_static_sha: str
    current_db_revision: str
    current_database_counts: tuple[int, int, int, int]
    database_other_sessions: int
    current_release_successful: bool
    active_transaction_present: bool
    application_containers_present: bool
    application_process_present: bool
    data_services_healthy: bool
    protected_volumes_present: bool
    owner_allowlist_exact: bool
    payments_disabled: bool
    yookassa_absent: bool
    preflight_result: str
    artifact_sha256: str
    manifest_sha256: str
    capacity: CapacitySnapshot


class TransitionEngine:
    """Evaluate every gate before build, stop, migration, or activation."""

    def __init__(self, adapter: MutationAdapter) -> None:
        self.adapter = adapter

    def execute_resume_post_migration(
        self,
        *,
        authorization: Mapping[str, object],
        preconditions: Preconditions,
        original_backup_evidence: Mapping[str, object],
        removal_evidence: Mapping[str, object],
        migration_evidence: Mapping[str, object],
        post_migration_backup_evidence: Mapping[str, object],
    ) -> None:
        if preconditions.current_application_sha != authorization["source_application_sha"]:
            raise TransitionError("current_application_mismatch")
        if preconditions.current_static_sha != authorization["source_static_sha"]:
            raise TransitionError("current_static_mismatch")
        if preconditions.current_db_revision != authorization["current_db_revision"]:
            raise TransitionError("current_database_revision_mismatch")
        expected_counts = authorization["expected_database_counts"]
        if preconditions.current_database_counts != (
            expected_counts["users"],
            expected_counts["guest_profiles"],
            expected_counts["reports"],
            expected_counts["payments"],
        ):
            raise TransitionError("current_database_counts_mismatch")
        if preconditions.database_other_sessions != 0:
            raise TransitionError("application_database_session_present")
        if not preconditions.current_release_successful:
            raise TransitionError("current_release_not_successful")
        if preconditions.active_transaction_present:
            raise TransitionError("active_transaction_present")
        if preconditions.application_containers_present:
            raise TransitionError("application_container_present")
        if preconditions.application_process_present:
            raise TransitionError("application_process_present")
        if not preconditions.data_services_healthy:
            raise TransitionError("data_services_not_healthy")
        if not preconditions.protected_volumes_present:
            raise TransitionError("protected_volume_missing")
        if not preconditions.owner_allowlist_exact:
            raise TransitionError("owner_allowlist_invalid")
        if not preconditions.payments_disabled:
            raise TransitionError("payments_not_disabled")
        if not preconditions.yookassa_absent:
            raise TransitionError("yookassa_present")
        if preconditions.preflight_result != "READY_FOR_HOST_BACKUP_AND_RECOVERY":
            raise TransitionError("offline_preflight_failed")
        if preconditions.artifact_sha256 != authorization["target_artifact_sha256"] or preconditions.manifest_sha256 != authorization["target_manifest_sha256"]:
            raise TransitionError("target_artifact_identity_mismatch")
        if original_backup_evidence.get("schema_version") != BACKUP_EVIDENCE_SCHEMA:
            raise TransitionError("original_backup_evidence_missing")
        if removal_evidence.get("result") != "APPLICATION_LAYER_RESET_PASS":
            raise TransitionError("removal_evidence_missing")
        if migration_evidence.get("kind") != "post_migration_completion_evidence":
            raise TransitionError("migration_evidence_missing")
        if (
            post_migration_backup_evidence.get("kind")
            != "post_migration_postgresql_checkpoint"
        ):
            raise TransitionError("post_migration_backup_evidence_missing")
        if authorization.get("allow_migration_execution") is not False:
            raise TransitionError("migration_execution_not_disabled")
        capacity_mode = preconditions.capacity.validate()

        target_sha = str(authorization["target_application_sha"])
        self.adapter.record("all_preconditions_passed", {"capacity_mode": capacity_mode})
        self.adapter.prepare_target_execution(target_sha)
        self.adapter.revalidate_original_backup_evidence()
        self.adapter.revalidate_removal_evidence()
        self.adapter.revalidate_migration_evidence()
        self.adapter.revalidate_post_migration_backup_evidence()
        self.adapter.verify_application_layer_absent()
        try:
            self.adapter.activate_target_with_polling_disabled(target_sha)
            self.adapter.verify_target_without_polling(target_sha)
            self.adapter.verify_owner_only_without_polling(target_sha)
            self.adapter.activate_bot_polling()
            self.adapter.verify_bot_polling(target_sha)
        except Exception as activation_error:
            compensation_failed = False
            try:
                self.adapter.leave_application_stopped(SOURCE_APPLICATION_SHA, target_sha)
            except Exception:
                compensation_failed = True
            try:
                self.adapter.verify_application_stopped(
                    SOURCE_APPLICATION_SHA,
                    TARGET_REVISION,
                )
            except Exception:
                compensation_failed = True
            phase = (
                "application_compensation_failed"
                if compensation_failed
                else "application_stopped_verified"
            )
            try:
                self.adapter.record(
                    phase,
                    {
                        "database_revision": TARGET_REVISION,
                        "database_rollback": False,
                        "source_fleet_started": False,
                    },
                )
            except Exception:
                compensation_failed = True
            if compensation_failed:
                raise TransitionError("application_compensation_incomplete") from activation_error
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
        original_backup_evidence: Path,
        removal_evidence: Path,
        migration_evidence: Path,
        post_migration_backup_evidence: Path,
        original_backup_root: Path,
        post_migration_backup_root: Path,
        authorization: Mapping[str, object],
    ) -> None:
        self.target_source = target_source.resolve(strict=True)
        self.target_app = self.target_source / "nura_app"
        self.authorization_manifest = authorization_manifest.resolve(strict=True)
        self.archive = archive.resolve(strict=True)
        self.checksum = checksum.resolve(strict=True)
        self.public_manifest = public_manifest.resolve(strict=True)
        self.evidence_directory = evidence_directory.resolve(strict=True)
        self.original_backup_evidence = original_backup_evidence.resolve(strict=True)
        self.removal_evidence = removal_evidence.resolve(strict=True)
        self.migration_evidence = migration_evidence.resolve(strict=True)
        self.post_migration_backup_evidence = post_migration_backup_evidence.resolve(
            strict=True
        )
        self.original_backup_root = original_backup_root.resolve(strict=True)
        self.post_migration_backup_root = post_migration_backup_root.resolve(strict=True)
        self.authorization = dict(authorization)
        self.current_app = Path("/opt/nura/nura_app")
        self.execution_bundle: Path | None = None
        self.target_compose_handoff = (
            self.evidence_directory / "target-compose-handoff.json"
        )
        self.target_image_override = (
            self.evidence_directory / "target-image.override.yml"
        )
        self.polling_bot_identity: tuple[str, str, str] | None = None
        self.source_current_snapshot = (
            self.evidence_directory / "source-current-before-activation.json"
        )
        self.source_previous_snapshot = (
            self.evidence_directory / "source-previous-before-activation.json"
        )
        self.clean_install_handoff = (
            self.evidence_directory / "clean-install-deploy-handoff.json"
        )

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

    def _target_compose(self, *arguments: str, polling: str | None = None) -> str:
        context = validate_target_compose_handoff(
            self.target_compose_handoff,
            manifest=self.authorization,
            target_source=self.target_source,
            env_file=self.current_app / ".env",
        )
        environment = os.environ.copy()
        if polling is not None:
            environment["NURA_TG_POLLING_ENABLED"] = polling
        return self._run(
            [
                "docker",
                "compose",
                "--project-name",
                "nura_app",
                "--project-directory",
                str(context.project_directory),
                "--env-file",
                str(context.env_file),
                "-f",
                str(context.compose_file),
                "-f",
                str(context.image_override),
                *arguments,
            ],
            cwd=context.project_directory,
            environment=environment,
        )

    def _application_containers(self) -> list[tuple[str, str, str]]:
        result = self._run(["docker", "ps", "-aq"])
        rows: list[tuple[str, str, str]] = []
        for container in result.splitlines():
            inspection = self._run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    '{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{.State.Status}}|{{index .Config.Labels "org.opencontainers.image.revision"}}|{{.Config.Image}}',
                    container,
                ]
            )
            project, service, state, revision, image = inspection.split("|", 4)
            if _is_application_container(project, service, revision, image):
                rows.append((container, state, revision))
        return rows

    def _application_process_present(self) -> bool:
        result = self._run(["ps", "-eo", "args="])
        return any(
            APPLICATION_PROCESS_RE.search(line) and "docker" not in line
            for line in result.splitlines()
        )

    def _verify_fleet_revision(self, expected_sha: str, *, polling: str) -> None:
        for service in APP_SERVICES:
            container = self._target_compose(
                "ps",
                "--status",
                "running",
                "-q",
                service,
                polling=polling,
            )
            if not container or "\n" in container:
                raise TransitionError("fleet_identity_invalid")
            identity = self._run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    '{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{.Config.Image}}|{{.Image}}|{{index .Config.Labels "org.opencontainers.image.revision"}}',
                    container,
                ]
            )
            project, actual_service, image, image_id, revision = identity.split("|", 4)
            context = validate_target_compose_handoff(
                self.target_compose_handoff,
                manifest=self.authorization,
                target_source=self.target_source,
                env_file=self.current_app / ".env",
            )
            if (
                project != "nura_app"
                or actual_service != service
                or image != context.image_tag
                or image_id != context.image_id
                or revision != expected_sha
            ):
                raise TransitionError("fleet_identity_invalid")

    def prepare_target_execution(self, target_sha: str) -> None:
        if _git(self.target_source, "rev-parse", "HEAD") != target_sha or _git(self.target_source, "status", "--porcelain"):
            raise TransitionError("target_source_identity_mismatch")
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

    def revalidate_original_backup_evidence(self) -> None:
        validate_evidence(
            self.original_backup_evidence,
            kind="original_backup",
            schema=BACKUP_EVIDENCE_SCHEMA,
            manifest=self.authorization,
            backup_root=self.original_backup_root,
        )

    def revalidate_removal_evidence(self) -> None:
        validate_removal_evidence(
            self.removal_evidence,
            manifest=self.authorization,
        )

    def revalidate_migration_evidence(self) -> None:
        validate_migration_evidence(
            self.migration_evidence,
            manifest=self.authorization,
        )

    def revalidate_post_migration_backup_evidence(self) -> None:
        validate_post_migration_backup_evidence(
            self.post_migration_backup_evidence,
            manifest=self.authorization,
            backup_root=self.post_migration_backup_root,
        )

    def verify_application_layer_absent(self) -> None:
        if self._application_containers():
            raise TransitionError("application_container_present")
        if self._application_process_present():
            raise TransitionError("application_process_present")

    def activate_target_with_polling_disabled(self, target_sha: str) -> None:
        if self.execution_bundle is None:
            raise TransitionError("execution_bundle_missing")
        for source, destination, label in (
            (
                Path("/var/lib/nura-release-state/current.json"),
                self.source_current_snapshot,
                "current_release_state",
            ),
            (
                Path("/var/lib/nura-release-state/previous.json"),
                self.source_previous_snapshot,
                "previous_release_state",
            ),
        ):
            value = _read_canonical_json(source, label)
            if destination.exists() or destination.is_symlink():
                raise TransitionError("source_state_snapshot_exists")
            descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(canonical_json(value))
                stream.flush()
                os.fsync(stream.fileno())
        if self.clean_install_handoff.exists() or self.clean_install_handoff.is_symlink():
            raise TransitionError("clean_install_handoff_exists")
        handoff_payload: dict[str, object] = {
            "schema_version": 1,
            "kind": "clean_install_deploy_handoff",
            "source_application_sha": self.authorization["source_application_sha"],
            "source_static_sha": self.authorization["source_static_sha"],
            "target_application_sha": target_sha,
            "target_db_revision": self.authorization["target_db_revision"],
            "authorization_sha256": _sha256(self.authorization_manifest),
            "original_backup_evidence_checksum": self.authorization[
                "original_backup_evidence_checksum"
            ],
            "original_backup_evidence_sha256": _sha256(
                self.original_backup_evidence
            ),
            "migration_evidence_checksum": self.authorization[
                "migration_evidence_checksum"
            ],
            "migration_evidence_sha256": _sha256(self.migration_evidence),
            "post_migration_backup_evidence_checksum": self.authorization[
                "post_migration_backup_evidence_checksum"
            ],
            "post_migration_backup_evidence_sha256": _sha256(
                self.post_migration_backup_evidence
            ),
            "removal_evidence_checksum": self.authorization[
                "application_layer_removal_evidence_checksum"
            ],
            "application_layer_removal_evidence_sha256": _sha256(self.removal_evidence),
            "precondition_result": "PASS",
            "application_layer_absent": True,
            "protected_data_services_healthy": True,
            "protected_volumes_present": True,
            "owner_allowlist_exact": True,
            "payments_disabled": True,
            "yookassa_absent": True,
            "database_rollback_allowed": False,
            "source_fleet_start_allowed": False,
        }
        handoff = dict(handoff_payload)
        handoff["checksum"] = payload_checksum(handoff_payload)
        descriptor = os.open(
            self.clean_install_handoff,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json(handoff))
            stream.flush()
            os.fsync(stream.fileno())
        environment = os.environ.copy()
        environment.update(
            {
                "NURA_PRELAUNCH_TRANSITION_AUTHORIZATION": str(self.authorization_manifest),
                "NURA_CLEAN_INSTALL_HANDOFF": str(self.clean_install_handoff),
                "NURA_TARGET_COMPOSE_HANDOFF": str(self.target_compose_handoff),
                "NURA_TARGET_IMAGE_OVERRIDE": str(self.target_image_override),
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
        worker_ping = self._target_compose(
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
        beat_container = self._target_compose(
            "ps",
            "--status",
            "running",
            "-q",
            "celery-beat",
            polling="false",
        )
        if not beat_container:
            raise TransitionError("beat_process_not_running")
        source = self._target_compose(
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
        polling = self._target_compose(
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
        identity = self._target_compose(
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
        context = validate_target_compose_handoff(
            self.target_compose_handoff,
            manifest=self.authorization,
            target_source=self.target_source,
            env_file=self.current_app / ".env",
        )
        current = self._target_compose(
            "ps", "--status", "running", "-q", "bot", polling="false"
        )
        if not current or "\n" in current:
            raise TransitionError("bot_polling_precondition_invalid")
        before = self._run(
            [
                "docker",
                "inspect",
                "--format",
                '{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{.Config.Image}}|{{.Image}}|{{index .Config.Labels "org.opencontainers.image.revision"}}',
                current,
            ]
        )
        if before != f"nura_app|bot|{context.image_tag}|{context.image_id}|{context.target_sha}":
            raise TransitionError("bot_polling_precondition_invalid")
        polling = self._target_compose(
            "exec",
            "-T",
            "bot",
            "python",
            "-c",
            "from core.config import settings; print(str(settings.telegram_polling_enabled).lower())",
            polling="false",
        )
        if polling != "false":
            raise TransitionError("bot_polling_precondition_invalid")
        self._target_compose(
            "up", "-d", "--no-deps", "--force-recreate", "bot", polling="true"
        )
        container = self._target_compose(
            "ps", "--status", "running", "-q", "bot", polling="true"
        )
        if not container or "\n" in container or container == current:
            raise TransitionError("bot_polling_identity_invalid")
        identity = self._run(
            [
                "docker",
                "inspect",
                "--format",
                '{{.Config.Image}}|{{.Image}}|{{index .Config.Labels "org.opencontainers.image.revision"}}',
                container,
            ]
        )
        image, image_id, revision = identity.split("|", 2)
        if (image, image_id, revision) != (
            context.image_tag,
            context.image_id,
            context.target_sha,
        ):
            raise TransitionError("bot_polling_identity_invalid")
        self.polling_bot_identity = (container, image_id, revision)

    def verify_bot_polling(self, target_sha: str) -> None:
        polling = self._target_compose(
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
        container = self._target_compose(
            "ps", "--status", "running", "-q", "bot", polling="true"
        )
        context = validate_target_compose_handoff(
            self.target_compose_handoff,
            manifest=self.authorization,
            target_source=self.target_source,
            env_file=self.current_app / ".env",
        )
        identity = self._run(
            [
                "docker",
                "inspect",
                "--format",
                '{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{.Config.Image}}|{{.Image}}|{{index .Config.Labels "org.opencontainers.image.revision"}}',
                container,
            ]
        )
        if (
            self.polling_bot_identity != (container, context.image_id, target_sha)
            or identity
            != f"nura_app|bot|{context.image_tag}|{context.image_id}|{target_sha}"
        ):
            raise TransitionError("bot_polling_identity_invalid")

    def leave_application_stopped(self, source_sha: str, target_sha: str) -> None:
        compensation_failed = False
        for action in (
            self._stop_and_remove_application_containers,
            lambda: self._restore_source_static(source_sha),
            lambda: self._restore_source_release_state(source_sha, target_sha),
        ):
            try:
                action()
            except Exception:
                compensation_failed = True
        if compensation_failed:
            raise TransitionError("application_compensation_incomplete")

    def _restore_source_static(self, source_sha: str) -> None:
        current_link = CURRENT_STATIC_LINK
        source_release = current_link.parent / "releases" / source_sha
        helper = (
            self.execution_bundle / "scripts" / "build_release_artifact.py"
            if self.execution_bundle is not None
            else self.target_source / "scripts" / "build_release_artifact.py"
        )
        self._run(
            [
                sys.executable,
                str(helper),
                "switch-current",
                "--current",
                str(current_link),
                "--target",
                str(source_release),
            ]
        )
        _validate_static_current(current_link, source_sha, helper)

    def _restore_source_release_state(self, source_sha: str, target_sha: str) -> None:
        current_state = CURRENT_RELEASE_STATE
        previous_state = Path("/var/lib/nura-release-state/previous.json")
        current = _read_canonical_json(current_state, "current_release_state")
        if current.get("sha") == target_sha:
            source_current = _read_canonical_json(
                self.source_current_snapshot,
                "source_current_snapshot",
            )
            source_previous = _read_canonical_json(
                self.source_previous_snapshot,
                "source_previous_snapshot",
            )
            if source_current.get("sha") != source_sha:
                raise TransitionError("state_compensation_source_mismatch")
            for _snapshot, destination, value in (
                (self.source_current_snapshot, current_state, source_current),
                (self.source_previous_snapshot, previous_state, source_previous),
            ):
                temporary = destination.with_name(
                    f".{destination.name}.{os.getpid()}.tmp"
                )
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o640,
                )
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(canonical_json(value))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, destination)
                directory = os.open(
                    destination.parent,
                    os.O_RDONLY | os.O_DIRECTORY,
                )
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        elif current.get("sha") != source_sha:
            raise TransitionError("current_state_compensation_source_mismatch")

    def _stop_and_remove_application_containers(self) -> None:
        rows = self._application_containers()
        running = [container for container, state, _ in rows if state == "running"]
        cleanup_failed = False
        if running:
            for container in running:
                try:
                    self._run(["docker", "stop", container])
                except TransitionError:
                    cleanup_failed = True
        stopped = [container for container, _, _ in self._application_containers()]
        if stopped:
            for container in stopped:
                try:
                    self._run(["docker", "rm", container])
                except TransitionError:
                    cleanup_failed = True
        if cleanup_failed:
            raise TransitionError("application_container_cleanup_failed")

    def verify_application_stopped(
        self,
        source_sha: str,
        expected_db_revision: str | None,
    ) -> None:
        self.verify_application_layer_absent()
        current = _read_canonical_json(
            Path("/var/lib/nura-release-state/current.json"),
            "current_release_state",
        )
        helper = (
            self.execution_bundle / "scripts" / "build_release_artifact.py"
            if self.execution_bundle is not None
            else self.target_source / "scripts" / "build_release_artifact.py"
        )
        _validate_static_current(
            Path("/var/www/nura-releases/current"),
            source_sha,
            helper,
        )
        if current.get("sha") != source_sha:
            raise TransitionError("application_stopped_source_state_invalid")
        history = current.get("activation_history")
        previous = _read_canonical_json(
            Path("/var/lib/nura-release-state/previous.json"),
            "previous_release_state",
        )
        if (
            not isinstance(history, list)
            or not history
            or previous.get("sha") != history[0]
        ):
            raise TransitionError("application_stopped_previous_state_invalid")
        if expected_db_revision is not None:
            revision = _current_database_snapshot(self.current_app / "docker-compose.yml")[
                "revision"
            ]
            if revision != expected_db_revision:
                raise TransitionError("application_stopped_database_revision_invalid")

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


@dataclass(frozen=True)
class TargetComposeContext:
    target_sha: str
    project_directory: Path
    compose_file: Path
    image_override: Path
    env_file: Path
    image_tag: str
    image_id: str


def _target_image_override_bytes(target_sha: str) -> bytes:
    image_tag = f"nura-release:{target_sha}"
    lines = ["services:"]
    for service in APP_SERVICES:
        lines.extend(
            (
                f"  {service}:",
                f"    image: {image_tag}",
                "    build: null",
            )
        )
        if service == "api":
            lines.extend(("    environment:", '      RUN_MIGRATIONS: "0"'))
    return ("\n".join(lines) + "\n").encode()


def create_target_compose_handoff(
    path: Path,
    *,
    image_override: Path,
    repo: Path,
    env_file: Path,
    target_sha: str,
    image_tag: str,
    image_id: str,
    oci_revision: str,
) -> None:
    """Persist the one exact, secret-free Compose context used after target build."""

    try:
        repository = repo.resolve(strict=True)
        environment_file = env_file.resolve(strict=True)
    except OSError as exc:
        raise TransitionError("target_compose_handoff_path_invalid") from exc
    evidence_directory = _validate_root_owned_private_directory(
        path.parent,
        "target_compose_evidence_directory",
    )
    if (
        not path.is_absolute()
        or not image_override.is_absolute()
        or path.name != "target-compose-handoff.json"
        or image_override.name != "target-image.override.yml"
        or image_override.parent.resolve(strict=True) != evidence_directory
        or path.exists()
        or path.is_symlink()
        or image_override.exists()
        or image_override.is_symlink()
        or not SHA_RE.fullmatch(target_sha)
        or _git(repository, "rev-parse", "HEAD") != target_sha
        or image_tag != f"nura-release:{target_sha}"
        or not image_id.startswith("sha256:")
        or oci_revision != target_sha
    ):
        raise TransitionError("target_compose_handoff_identity_invalid")
    project_directory = repository / "nura_app"
    compose_file = project_directory / "docker-compose.yml"
    expected_env = project_directory / ".env"
    if (
        environment_file != expected_env
        or env_file.is_symlink()
        or not env_file.is_file()
        or compose_file.is_symlink()
        or not compose_file.is_file()
    ):
        raise TransitionError("target_compose_handoff_identity_invalid")
    compose_blob = _git_bytes(repository, "show", f"{target_sha}:nura_app/docker-compose.yml")
    if compose_file.read_bytes() != compose_blob:
        raise TransitionError("target_compose_git_blob_mismatch")
    override_bytes = _target_image_override_bytes(target_sha)
    descriptor = os.open(image_override, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(override_bytes)
        stream.flush()
        os.fsync(stream.fileno())
    payload: dict[str, object] = {
        "schema_version": TARGET_COMPOSE_HANDOFF_SCHEMA,
        "kind": "exact_target_compose_handoff",
        "target_sha": target_sha,
        "project_name": "nura_app",
        "project_directory": str(project_directory),
        "compose_path": str(compose_file),
        "compose_sha256": hashlib.sha256(compose_blob).hexdigest(),
        "image_override_path": str(image_override),
        "image_override_sha256": hashlib.sha256(override_bytes).hexdigest(),
        "image_tag": image_tag,
        "image_id": image_id,
        "oci_revision": oci_revision,
        "environment": {
            "classification": "non-secret-production",
            "path": str(environment_file),
            "sha256": _sha256(environment_file),
        },
        "polling_initial_state": False,
    }
    handoff = dict(payload)
    handoff["checksum"] = payload_checksum(payload)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_json(handoff))
        stream.flush()
        os.fsync(stream.fileno())


def validate_target_compose_handoff(
    path: Path,
    *,
    manifest: Mapping[str, object],
    target_source: Path,
    env_file: Path,
) -> TargetComposeContext:
    """Revalidate every immutable input before any target Compose operation."""

    value = _read_canonical_json(path, "target_compose_handoff")
    _validate_checksum(value, "target_compose_handoff")
    evidence_directory = _validate_root_owned_private_directory(
        path.parent,
        "target_compose_evidence_directory",
    )
    required = {
        "schema_version",
        "kind",
        "target_sha",
        "project_name",
        "project_directory",
        "compose_path",
        "compose_sha256",
        "image_override_path",
        "image_override_sha256",
        "image_tag",
        "image_id",
        "oci_revision",
        "environment",
        "polling_initial_state",
        "checksum",
    }
    try:
        source = target_source.resolve(strict=True)
        expected_env = env_file.resolve(strict=True)
        compose_file = Path(str(value["compose_path"])).resolve(strict=True)
        image_override = Path(str(value["image_override_path"])).resolve(strict=True)
        project_directory = Path(str(value["project_directory"])).resolve(strict=True)
        recorded_env = Path(str(value["environment"]["path"])).resolve(strict=True)  # type: ignore[index]
        handoff_metadata = path.lstat()
        override_metadata = image_override.lstat()
    except (KeyError, OSError, TypeError) as exc:
        raise TransitionError("target_compose_handoff_identity_invalid") from exc
    target_sha = str(manifest["target_application_sha"])
    environment = value.get("environment")
    effective_uid = getattr(os, "geteuid", lambda: None)()
    if (
        not path.is_absolute()
        or path.name != "target-compose-handoff.json"
        or path.is_symlink()
        or not stat.S_ISREG(handoff_metadata.st_mode)
        or handoff_metadata.st_nlink != 1
        or image_override.is_symlink()
        or not stat.S_ISREG(override_metadata.st_mode)
        or override_metadata.st_nlink != 1
        or compose_file.is_symlink()
        or env_file.is_symlink()
        or (
            os.name == "posix"
            and (
                stat.S_IMODE(handoff_metadata.st_mode) != 0o600
                or stat.S_IMODE(override_metadata.st_mode) != 0o600
                or handoff_metadata.st_uid != effective_uid
                or override_metadata.st_uid != effective_uid
            )
        )
        or set(value) != required
        or value.get("schema_version") != TARGET_COMPOSE_HANDOFF_SCHEMA
        or value.get("kind") != "exact_target_compose_handoff"
        or value.get("target_sha") != target_sha
        or value.get("project_name") != "nura_app"
        or project_directory != source / "nura_app"
        or compose_file != project_directory / "docker-compose.yml"
        or image_override.parent != evidence_directory
        or image_override.name != "target-image.override.yml"
        or value.get("image_tag") != f"nura-release:{target_sha}"
        or not str(value.get("image_id", "")).startswith("sha256:")
        or value.get("oci_revision") != target_sha
        or value.get("polling_initial_state") is not False
        or not isinstance(environment, dict)
        or environment.get("classification") != "non-secret-production"
        or recorded_env != expected_env
        or environment.get("sha256") != _sha256(expected_env)
    ):
        raise TransitionError("target_compose_handoff_identity_invalid")
    compose_blob = _git_bytes(source, "show", f"{target_sha}:nura_app/docker-compose.yml")
    if (
        _git(source, "rev-parse", "HEAD") != target_sha
        or compose_file.read_bytes() != compose_blob
        or value.get("compose_sha256") != hashlib.sha256(compose_blob).hexdigest()
    ):
        raise TransitionError("target_compose_git_blob_mismatch")
    expected_override = _target_image_override_bytes(target_sha)
    if (
        image_override.is_symlink()
        or image_override.read_bytes() != expected_override
        or value.get("image_override_sha256")
        != hashlib.sha256(expected_override).hexdigest()
    ):
        raise TransitionError("target_compose_override_mismatch")
    return TargetComposeContext(
        target_sha=target_sha,
        project_directory=project_directory,
        compose_file=compose_file,
        image_override=image_override,
        env_file=expected_env,
        image_tag=str(value["image_tag"]),
        image_id=str(value["image_id"]),
    )


def verify_clean_install_handoff(
    path: Path,
    *,
    manifest_path: Path,
    repo: Path,
    source_sha: str,
    target_sha: str,
    consume: bool,
) -> None:
    manifest = validate_authorization_manifest(manifest_path, repo=repo)
    value = _read_canonical_json(path, "clean_install_handoff")
    _validate_checksum(value, "clean_install_handoff")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise TransitionError("clean_install_handoff_unreadable") from exc
    owner = getattr(os, "geteuid", lambda: None)()
    if (
        metadata.st_nlink != 1
        or (os.name == "posix" and stat.S_IMODE(metadata.st_mode) != 0o600)
        or (owner is not None and metadata.st_uid != owner)
    ):
        raise TransitionError("clean_install_handoff_unsafe")
    expected: dict[str, object] = {
        "schema_version": 1,
        "kind": "clean_install_deploy_handoff",
        "source_application_sha": source_sha,
        "source_static_sha": manifest["source_static_sha"],
        "target_application_sha": target_sha,
        "target_db_revision": manifest["target_db_revision"],
        "authorization_sha256": _sha256(manifest_path),
        "original_backup_evidence_checksum": manifest[
            "original_backup_evidence_checksum"
        ],
        "original_backup_evidence_sha256": manifest[
            "original_backup_evidence_sha256"
        ],
        "migration_evidence_checksum": manifest["migration_evidence_checksum"],
        "migration_evidence_sha256": manifest["migration_evidence_sha256"],
        "post_migration_backup_evidence_checksum": manifest[
            "post_migration_backup_evidence_checksum"
        ],
        "post_migration_backup_evidence_sha256": manifest[
            "post_migration_backup_evidence_sha256"
        ],
        "removal_evidence_checksum": manifest["application_layer_removal_evidence_checksum"],
        "application_layer_removal_evidence_sha256": manifest["application_layer_removal_evidence_sha256"],
        "precondition_result": "PASS",
        "application_layer_absent": True,
        "protected_data_services_healthy": True,
        "protected_volumes_present": True,
        "owner_allowlist_exact": True,
        "payments_disabled": True,
        "yookassa_absent": True,
        "database_rollback_allowed": False,
        "source_fleet_start_allowed": False,
    }
    payload = {key: item for key, item in value.items() if key != "checksum"}
    if payload != expected:
        raise TransitionError("clean_install_handoff_identity_invalid")
    if source_sha != manifest["source_application_sha"] or target_sha != manifest["target_application_sha"]:
        raise TransitionError("clean_install_handoff_target_invalid")
    if consume:
        try:
            path.unlink()
            if os.name == "posix":
                directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        except OSError as exc:
            raise TransitionError("clean_install_handoff_consume_failed") from exc


def _validate_static_current(current_link: Path, expected_sha: str, helper: Path) -> None:
    """Pin current to the exact immutable release root and verify its contents."""
    expected_release = current_link.parent / "releases" / expected_sha
    try:
        link_info = current_link.lstat()
        releases_root_info = expected_release.parent.lstat()
        release_info = expected_release.lstat()
        resolved_current = current_link.resolve(strict=True)
        resolved_expected = expected_release.resolve(strict=True)
    except OSError as exc:
        raise TransitionError("current_static_link_invalid") from exc
    owner = getattr(os, "geteuid", lambda: None)()
    if (
        not stat.S_ISLNK(link_info.st_mode)
        or not stat.S_ISDIR(releases_root_info.st_mode)
        or stat.S_ISLNK(releases_root_info.st_mode)
        or not stat.S_ISDIR(release_info.st_mode)
        or stat.S_ISLNK(release_info.st_mode)
        or resolved_current != resolved_expected
        or (owner is not None and any(info.st_uid != owner for info in (link_info, releases_root_info, release_info)))
        or releases_root_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or release_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise TransitionError("current_static_link_invalid")
    result = subprocess.run(
        [
            sys.executable,
            str(helper),
            "validate-current",
            "--current",
            str(current_link),
            "--expected-sha",
            expected_sha,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode:
        raise TransitionError("current_static_integrity_invalid")


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


def _current_database_snapshot(compose_file: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "postgres_probe.py"),
            "snapshot",
            "--compose-file",
            str(compose_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    values = result.stdout.splitlines()
    if (
        result.returncode
        or len(values) != 6
        or not re.fullmatch(r"[0-9a-z]{12,32}", values[0])
        or any(not item.isdigit() for item in values[1:])
    ):
        raise TransitionError("database_revision_probe_failed")
    return {
        "revision": values[0],
        "users": int(values[1]),
        "guest_profiles": int(values[2]),
        "reports": int(values[3]),
        "payments": int(values[4]),
        "other_sessions": int(values[5]),
    }


def _application_containers_present() -> bool:
    result = subprocess.run(
        [
            "docker",
            "ps",
            "-aq",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise TransitionError("fleet_probe_failed")
    for container in result.stdout.splitlines():
        inspection = subprocess.run(
            [
                "docker",
                "inspect",
            "--format",
                '{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{index .Config.Labels "org.opencontainers.image.revision"}}|{{.Config.Image}}',
                container,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if inspection.returncode:
            raise TransitionError("fleet_probe_failed")
        try:
            project, service, revision, image = inspection.stdout.strip().split("|", 3)
        except ValueError as exc:
            raise TransitionError("fleet_probe_invalid") from exc
        if _is_application_container(project, service, revision, image):
            return True
    return False


def _application_process_present() -> bool:
    result = subprocess.run(
        ["ps", "-eo", "args="],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise TransitionError("application_process_probe_failed")
    return any(
        APPLICATION_PROCESS_RE.search(line) and "docker" not in line
        for line in result.stdout.splitlines()
    )


def _data_services_healthy(compose_file: Path) -> bool:
    for service in DATA_SERVICES:
        result = subprocess.run(
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
        containers = result.stdout.splitlines()
        if result.returncode or len(containers) != 1:
            return False
        inspection = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
                containers[0],
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if inspection.returncode or inspection.stdout.strip() != "healthy":
            return False
    return True


def _protected_volumes_present() -> bool:
    for volume in PROTECTED_VOLUMES:
        result = subprocess.run(
            ["docker", "volume", "inspect", volume],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode:
            return False
    return True


def _active_transaction_present(directory: Path) -> bool:
    if not directory.is_dir() or directory.is_symlink():
        raise TransitionError("p7b_transaction_directory_unsafe")
    try:
        for path in directory.glob("*.json"):
            value = _read_canonical_json(path, "p7b_transaction")
            phase = value.get("payload", value).get("phase")
            if not isinstance(phase, str) or phase not in P7B_QUIESCENT_PHASES:
                return True
    except AttributeError as exc:
        raise TransitionError("p7b_transaction_schema_invalid") from exc
    return False


def execute_from_cli(args: argparse.Namespace) -> None:
    repo = args.repo.resolve(strict=True)
    _validate_resume_cli_paths(args, repo)
    manifest = validate_authorization_manifest(args.manifest, repo=repo)
    validate_execution_checkout(repo, manifest)
    validate_target_source_checkout(args.target_source, manifest)

    from tools.current_vps_prelaunch_preflight import run_preflight

    validate_migration_contract(args.target_source / "nura_app" / "alembic" / "versions")
    original_backup = validate_evidence(
        args.original_backup_evidence,
        kind="original_backup",
        schema=BACKUP_EVIDENCE_SCHEMA,
        manifest=manifest,
        backup_root=args.original_backup_root,
    )
    removal = validate_removal_evidence(
        args.removal_evidence,
        manifest=manifest,
    )
    migration = validate_migration_evidence(
        args.migration_evidence,
        manifest=manifest,
    )
    post_migration_backup = validate_post_migration_backup_evidence(
        args.post_migration_backup_evidence,
        manifest=manifest,
        backup_root=args.post_migration_backup_root,
    )
    validate_resume_evidence_timeline(migration, post_migration_backup, manifest)
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
    _validate_static_current(
        args.current_static_link,
        str(manifest["source_static_sha"]),
        args.target_source / "scripts" / "build_release_artifact.py",
    )
    current_static_sha = str(manifest["source_static_sha"])
    archive_digest = _sha256(args.archive)
    try:
        checksum_tokens = args.checksum.read_text(encoding="ascii").strip().split()
    except (OSError, UnicodeDecodeError) as exc:
        raise TransitionError("artifact_checksum_unreadable") from exc
    if checksum_tokens not in ([archive_digest], [archive_digest, args.archive.name]):
        raise TransitionError("artifact_checksum_mismatch")
    database = _current_database_snapshot(args.current_compose)
    gates = preflight.get("gates")
    if not isinstance(gates, dict):
        raise TransitionError("offline_preflight_invalid")
    preconditions = Preconditions(
        current_application_sha=str(current.get("sha", "")),
        current_static_sha=current_static_sha,
        current_db_revision=str(database["revision"]),
        current_database_counts=(
            int(database["users"]),
            int(database["guest_profiles"]),
            int(database["reports"]),
            int(database["payments"]),
        ),
        database_other_sessions=int(database["other_sessions"]),
        current_release_successful=current.get("status") == "successful",
        active_transaction_present=_active_transaction_present(
            args.p7b_transaction_directory
        ),
        application_containers_present=_application_containers_present(),
        application_process_present=_application_process_present(),
        data_services_healthy=_data_services_healthy(args.current_compose),
        protected_volumes_present=_protected_volumes_present(),
        owner_allowlist_exact=gates.get("owner_allowlist") is True,
        payments_disabled=gates.get("payments_disabled") is True,
        yookassa_absent=gates.get("yookassa_absent") is True,
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
        original_backup_evidence=args.original_backup_evidence,
        removal_evidence=args.removal_evidence,
        migration_evidence=args.migration_evidence,
        post_migration_backup_evidence=args.post_migration_backup_evidence,
        original_backup_root=args.original_backup_root,
        post_migration_backup_root=args.post_migration_backup_root,
        authorization=manifest,
    )
    TransitionEngine(adapter).execute_resume_post_migration(
        authorization=manifest,
        preconditions=preconditions,
        original_backup_evidence=original_backup,
        removal_evidence=removal,
        migration_evidence=migration,
        post_migration_backup_evidence=post_migration_backup,
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
    handoff_parser = subparsers.add_parser("verify-clean-install-handoff")
    handoff_parser.add_argument("--handoff", type=Path, required=True)
    handoff_parser.add_argument("--manifest", type=Path, required=True)
    handoff_parser.add_argument("--source-sha", required=True)
    handoff_parser.add_argument("--target-sha", required=True)
    handoff_parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    handoff_parser.add_argument("--consume", action="store_true")
    target_handoff_parser = subparsers.add_parser("create-target-compose-handoff")
    target_handoff_parser.add_argument("--handoff", type=Path, required=True)
    target_handoff_parser.add_argument("--image-override", type=Path, required=True)
    target_handoff_parser.add_argument("--repo", type=Path, required=True)
    target_handoff_parser.add_argument("--env-file", type=Path, required=True)
    target_handoff_parser.add_argument("--target-sha", required=True)
    target_handoff_parser.add_argument("--image-tag", required=True)
    target_handoff_parser.add_argument("--image-id", required=True)
    target_handoff_parser.add_argument("--oci-revision", required=True)
    target_validate_parser = subparsers.add_parser("validate-target-compose-handoff")
    target_validate_parser.add_argument("--handoff", type=Path, required=True)
    target_validate_parser.add_argument("--manifest", type=Path, required=True)
    target_validate_parser.add_argument("--target-source", type=Path, required=True)
    target_validate_parser.add_argument("--env-file", type=Path, required=True)
    target_validate_parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    execute_parser = subparsers.add_parser("clean-install-resume-post-migration")
    execute_parser.add_argument("--manifest", type=Path, required=True)
    execute_parser.add_argument("--original-backup-evidence", type=Path, required=True)
    execute_parser.add_argument(
        "--original-backup-root",
        type=Path,
        default=Path("/var/backups/nura-release-transition"),
    )
    execute_parser.add_argument("--removal-evidence", type=Path, required=True)
    execute_parser.add_argument("--migration-evidence", type=Path, required=True)
    execute_parser.add_argument(
        "--post-migration-backup-evidence", type=Path, required=True
    )
    execute_parser.add_argument(
        "--post-migration-backup-root", type=Path, required=True
    )
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
    execute_parser.add_argument(
        "--current-static-link",
        type=Path,
        default=Path("/var/www/nura-releases/current"),
    )
    execute_parser.add_argument("--p7b-transaction-directory", type=Path, default=Path("/var/lib/nura-release-state/p7b/transactions"))
    args = parser.parse_args(argv)
    if (
        args.command == "clean-install-resume-post-migration"
        and os.environ.get("NURA_COMMON_LOCK_FD") != "9"
    ):
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
        if args.command == "clean-install-resume-post-migration":
            execute_from_cli(args)
            output = {"status": "PASS", "result": "transition_succeeded"}
        elif args.command == "create-target-compose-handoff":
            create_target_compose_handoff(
                args.handoff,
                image_override=args.image_override,
                repo=args.repo,
                env_file=args.env_file,
                target_sha=args.target_sha,
                image_tag=args.image_tag,
                image_id=args.image_id,
                oci_revision=args.oci_revision,
            )
            output = {"status": "PASS", "result": "target_compose_handoff_created"}
        elif args.command == "validate-target-compose-handoff":
            manifest = validate_authorization_manifest(args.manifest, repo=args.repo)
            context = validate_target_compose_handoff(
                args.handoff,
                manifest=manifest,
                target_source=args.target_source,
                env_file=args.env_file,
            )
            output = {
                "status": "PASS",
                "result": "target_compose_handoff_verified",
                "target": context.target_sha,
            }
        elif args.command == "verify-clean-install-handoff":
            verify_clean_install_handoff(
                args.handoff,
                manifest_path=args.manifest,
                repo=args.repo,
                source_sha=args.source_sha,
                target_sha=args.target_sha,
                consume=args.consume,
            )
            output = {"status": "PASS", "result": "clean_install_handoff_verified"}
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
