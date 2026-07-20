#!/usr/bin/env python3
"""Inventory or explicitly prepare the one-time NURA atomic-release host layout.

The default mode is read-only. Apply mode is intentionally separate from normal
deployment and requires the production SHA plus an explicit acknowledgement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - apply mode is Linux-host only
    fcntl = None  # type: ignore[assignment]

EXPECTED_LEGACY_SHA = "d0d39ae8717ceb0920d98f27dd9092f746755c6c"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ENABLED_CONFIG_ALLOWLIST = frozenset(
    {"nura-ai.ru", "nura-ai.ru.bak", "nura-ai.ru.conf"}
)
APPLICATION_SERVICES = ("api", "bot", "celery-worker", "celery-beat", "admin-bot")
SENSITIVE_SUFFIXES = (".env", ".key", ".pem", ".p12", ".pfx")


class TransitionError(RuntimeError):
    """Raised when the host is not safe for the one-time transition."""


def _run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise TransitionError(f"{' '.join(args)}: {detail}")
    return result.stdout


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_version(web_root: Path) -> str:
    version = web_root / "VERSION"
    if version.is_symlink() or not version.is_file():
        raise TransitionError("legacy VERSION is missing, non-regular, or a symlink")
    fields = version.read_text(encoding="utf-8").split()
    if not fields:
        raise TransitionError("legacy VERSION is empty")
    return fields[0]


def _enabled_configs(sites_enabled: Path) -> list[Path]:
    if sites_enabled.is_symlink() or not sites_enabled.is_dir():
        raise TransitionError("sites-enabled must be a real directory")
    entries = sorted(path for path in sites_enabled.iterdir() if path.is_file() or path.is_symlink())
    names = {path.name for path in entries}
    if names != ENABLED_CONFIG_ALLOWLIST:
        raise TransitionError(
            f"enabled Nginx filenames differ from audited strict allowlist: {sorted(names)}"
        )
    return entries


def _public_inventory(web_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(web_root.rglob("*")):
        relative = path.relative_to(web_root).as_posix()
        if path.is_symlink():
            raise TransitionError(f"legacy web root contains a symlink: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise TransitionError(f"legacy web root contains a special file: {relative}")
        lowered = relative.lower()
        if lowered.startswith(".env") or lowered.endswith(SENSITIVE_SUFFIXES):
            raise TransitionError(f"possible secret in public root; refusing snapshot: {relative}")
        info = path.stat()
        entries.append(
            {
                "path": relative,
                "size": info.st_size,
                "sha256": _sha256(path),
                "mode": oct(info.st_mode & 0o777),
                "uid": info.st_uid,
                "gid": info.st_gid,
            }
        )
    return entries


def _service_map(repo_root: Path) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for service in APPLICATION_SERVICES:
        container_ids = _run(
            "docker",
            "compose",
            "-f",
            str(repo_root / "nura_app" / "docker-compose.yml"),
            "ps",
            "-q",
            "--all",
            service,
        ).splitlines()
        if len(container_ids) != 1:
            raise TransitionError(f"legacy service is missing or ambiguous: {service}")
        image_id = _run("docker", "inspect", "--format", "{{.Image}}", container_ids[0]).strip()
        if not image_id.startswith("sha256:"):
            raise TransitionError(f"legacy service image ID is invalid: {service}")
        mapping[service] = {"container_id": container_ids[0], "image_id": image_id}
    return mapping


def collect_inventory(args: argparse.Namespace) -> dict[str, Any]:
    inventory = _public_inventory(args.legacy_web_root)
    encoded = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
    configs = _enabled_configs(args.sites_enabled)
    return {
        "schema": 1,
        "mode": "apply" if args.apply else "dry-run",
        "production_version": _read_version(args.legacy_web_root),
        "legacy_web_root": str(args.legacy_web_root),
        "file_count": len(inventory),
        "total_bytes": sum(entry["size"] for entry in inventory),
        "inventory_sha256": hashlib.sha256(encoded).hexdigest(),
        "files": inventory,
        "enabled_nginx_configs": [str(path) for path in configs],
        "services": _service_map(args.repo_root),
        "proposed": {
            "release_root": str(args.release_root),
            "state_root": str(args.state_root),
            "backup_root": str(args.backup_root),
            "legacy_release_sha": EXPECTED_LEGACY_SHA,
        },
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o640)
    os.replace(temporary, path)


def _snapshot(args: argparse.Namespace, inventory: dict[str, Any], transition_dir: Path) -> None:
    _write_json(transition_dir / "legacy-inventory.json", inventory)
    archive_path = transition_dir / "legacy-web-root.tar.gz"
    with tarfile.open(archive_path, "w:gz", dereference=False) as archive:
        archive.add(args.legacy_web_root, arcname="nura-ai.ru", recursive=True)
    (transition_dir / "legacy-web-root.tar.gz.sha256").write_text(
        f"{_sha256(archive_path)}  {archive_path.name}\n", encoding="ascii"
    )
    config_backup = transition_dir / "sites-enabled"
    config_backup.mkdir(mode=0o750)
    for source in _enabled_configs(args.sites_enabled):
        if source.is_symlink():
            (config_backup / f"{source.name}.symlink-target").write_text(
                os.readlink(source), encoding="utf-8"
            )
        else:
            shutil.copy2(source, config_backup / source.name, follow_symlinks=False)
    canonical = args.sites_available / "nura-ai.ru.conf"
    if canonical.is_file() and not canonical.is_symlink():
        shutil.copy2(canonical, transition_dir / "sites-available-nura-ai.ru.conf")


def _reviewed_nginx_bytes(args: argparse.Namespace) -> bytes:
    if not args.target_sha or SHA_PATTERN.fullmatch(args.target_sha) is None:
        raise TransitionError("--target-sha must be an exact reviewed 40-character SHA")
    if _run("git", "-C", str(args.repo_root), "rev-parse", "HEAD").strip() != args.target_sha:
        raise TransitionError("transition checkout HEAD does not equal --target-sha")
    if _run("git", "-C", str(args.repo_root), "status", "--porcelain"):
        raise TransitionError("transition checkout must be clean")
    relative = "nura_app/nginx/nura-ai.ru.conf"
    _run("git", "-C", str(args.repo_root), "ls-files", "--error-unmatch", "--", relative)
    source = args.repo_root / relative
    if source.is_symlink() or not source.is_file():
        raise TransitionError("reviewed tracked Nginx source is not a regular file")
    result = subprocess.run(
        ["git", "-C", str(args.repo_root), "cat-file", "blob", f"{args.target_sha}:{relative}"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise TransitionError("cannot read reviewed Nginx config from the exact target blob")
    reviewed = bytes(result.stdout)
    if b"root /var/www/nura-releases/current/public;" not in reviewed:
        raise TransitionError("reviewed Nginx source does not use the atomic release root")
    return reviewed


def _protect_legacy_images(service_map: dict[str, dict[str, str]]) -> dict[str, str]:
    protected: dict[str, str] = {}
    for service, value in service_map.items():
        tag = f"nura-legacy:{service}-{EXPECTED_LEGACY_SHA[:12]}"
        _run("docker", "image", "tag", value["image_id"], tag)
        inspected = _run("docker", "image", "inspect", "--format", "{{.Id}}", tag).strip()
        if inspected != value["image_id"]:
            raise TransitionError(f"protected legacy image tag mismatch: {service}")
        protected[service] = tag
    return protected


def _build_legacy_release(args: argparse.Namespace, transition_dir: Path) -> Path:
    worktree = Path(tempfile.mkdtemp(prefix="nura-legacy-worktree-"))
    artifact_dir = transition_dir / "legacy-artifact"
    try:
        shutil.rmtree(worktree)
        _run("git", "-C", str(args.repo_root), "worktree", "add", "--detach", str(worktree), EXPECTED_LEGACY_SHA)
        _run(
            "python3",
            str(args.repo_root / "scripts" / "build_release_artifact.py"),
            "build",
            "--repo-root",
            str(worktree),
            "--target-sha",
            EXPECTED_LEGACY_SHA,
            "--output-dir",
            str(artifact_dir),
        )
        archive = artifact_dir / f"nura-static-{EXPECTED_LEGACY_SHA}.tar.gz"
        checksum = artifact_dir / f"nura-static-{EXPECTED_LEGACY_SHA}.tar.gz.sha256"
        manifest = artifact_dir / "release-manifest.json"
        staging = args.release_root / "staging" / f"{EXPECTED_LEGACY_SHA}-transition-{os.getpid()}"
        _run(
            "python3",
            str(args.repo_root / "scripts" / "build_release_artifact.py"),
            "extract",
            "--archive",
            str(archive),
            "--checksum",
            str(checksum),
            "--manifest",
            str(manifest),
            "--target-sha",
            EXPECTED_LEGACY_SHA,
            "--staging",
            str(staging),
        )
        final = args.release_root / "releases" / EXPECTED_LEGACY_SHA
        if final.exists():
            raise TransitionError("legacy final release already exists; refusing to overwrite")
        os.replace(staging, final)
        return final
    finally:
        subprocess.run(
            ["git", "-C", str(args.repo_root), "worktree", "remove", "--force", str(worktree)],
            check=False,
            capture_output=True,
        )


def _restore_enabled_configs(args: argparse.Namespace, transition_dir: Path) -> None:
    for name in ENABLED_CONFIG_ALLOWLIST:
        target = args.sites_enabled / name
        if target.exists() or target.is_symlink():
            target.unlink()
        backup = transition_dir / "sites-enabled" / name
        link_record = transition_dir / "sites-enabled" / f"{name}.symlink-target"
        if backup.exists():
            shutil.copy2(backup, target)
        elif link_record.exists():
            target.symlink_to(link_record.read_text(encoding="utf-8"))


def _restore_canonical_config(args: argparse.Namespace, transition_dir: Path) -> None:
    canonical = args.sites_available / "nura-ai.ru.conf"
    backup = transition_dir / "sites-available-nura-ai.ru.conf"
    if backup.is_file():
        temporary = canonical.with_name(f".{canonical.name}.restore.{os.getpid()}")
        shutil.copy2(backup, temporary)
        os.replace(temporary, canonical)


def apply_transition(args: argparse.Namespace, inventory: dict[str, Any]) -> None:
    if args.expected_production_sha != EXPECTED_LEGACY_SHA:
        raise TransitionError("--expected-production-sha must equal the audited legacy SHA")
    if not args.acknowledge_production_change:
        raise TransitionError("--acknowledge-production-change is required with --apply")
    if inventory["production_version"] != EXPECTED_LEGACY_SHA:
        raise TransitionError("production VERSION does not equal the expected legacy SHA")
    reviewed_nginx = _reviewed_nginx_bytes(args)
    for root, expected in (
        (args.release_root, Path("/var/www/nura-releases")),
        (args.state_root, Path("/var/lib/nura-release-state")),
        (args.backup_root, Path("/var/backups/nura-release-transition")),
    ):
        if root != expected:
            raise TransitionError(f"apply root must use exact canonical path: {expected}")

    args.lock_file.parent.mkdir(parents=True, exist_ok=True)
    with args.lock_file.open("a+") as lock:
        if fcntl is None:
            raise TransitionError("apply mode requires POSIX flock support")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        transition_dir = args.backup_root / f"{int(time.time())}-{inventory['inventory_sha256'][:16]}"
        transition_dir.mkdir(parents=True, mode=0o750)
        _snapshot(args, inventory, transition_dir)
        protected_tags = _protect_legacy_images(inventory["services"])
        for directory in (
            args.release_root / "releases",
            args.release_root / "staging",
            args.state_root / "releases",
            args.state_root / "logs",
        ):
            directory.mkdir(parents=True, exist_ok=True)
        legacy_release = _build_legacy_release(args, transition_dir)
        current = args.release_root / "current"
        if current.exists() or current.is_symlink():
            raise TransitionError("current already exists; refusing to overwrite transition state")
        temporary = args.release_root / f".current.transition.{os.getpid()}"
        canonical = args.sites_available / "nura-ai.ru.conf"
        if not canonical.is_file() or canonical.is_symlink():
            raise TransitionError("canonical reviewed Nginx config is missing")
        try:
            candidate = canonical.with_name(f".{canonical.name}.candidate.{os.getpid()}")
            candidate.write_bytes(reviewed_nginx)
            candidate.chmod(0o644)
            os.replace(candidate, canonical)
            if canonical.read_bytes() != reviewed_nginx:
                raise TransitionError("installed canonical Nginx config does not match target bytes")
            for name in ENABLED_CONFIG_ALLOWLIST:
                target = args.sites_enabled / name
                if target.exists() or target.is_symlink():
                    target.unlink()
            (args.sites_enabled / "nura-ai.ru.conf").symlink_to(canonical)
            _run("nginx", "-t")
            temporary.symlink_to(
                os.path.relpath(legacy_release, args.release_root), target_is_directory=True
            )
            if temporary.resolve(strict=True) != legacy_release.resolve(strict=True):
                raise TransitionError("temporary legacy current symlink is invalid")
            os.replace(temporary, current)
            _run("systemctl", "reload", "nginx")
        except Exception:
            if temporary.exists() or temporary.is_symlink():
                temporary.unlink()
            if current.is_symlink() and current.resolve(strict=False) == legacy_release.resolve():
                current.unlink()
            _restore_enabled_configs(args, transition_dir)
            _restore_canonical_config(args, transition_dir)
            _run("nginx", "-t")
            _run("systemctl", "reload", "nginx")
            raise
        state = {
            "schema": 1,
            "sha": EXPECTED_LEGACY_SHA,
            "status": "successful",
            "legacy": True,
            "rollback_eligibility": True,
            "static_release_path": str(legacy_release),
            "artifact_sha256": _sha256(
                transition_dir / "legacy-artifact" / f"nura-static-{EXPECTED_LEGACY_SHA}.tar.gz"
            ),
            "public_manifest_sha256": _sha256(legacy_release / "public/release-manifest.json"),
            "application_image_tag": "service-specific-legacy-map",
            "application_image_id": "",
            "oci_revision": None,
            "per_service_image_mapping": protected_tags,
            "per_service_image_ids": {
                service: value["image_id"] for service, value in inventory["services"].items()
            },
            "previous_successful_sha": None,
            "migration_delta": False,
            "activation_timestamp": datetime_utc(),
            "workflow_run_id": None,
            "failure_stage": None,
            "failure_reason": None,
        }
        record_path = args.state_root / "releases" / f"{EXPECTED_LEGACY_SHA}.json"
        current_state_path = args.state_root / "current.json"
        try:
            _write_json(record_path, state)
            _write_json(current_state_path, state)
        except Exception:
            if current.is_symlink():
                current.unlink()
            for state_path in (record_path, current_state_path):
                if state_path.is_file() and not state_path.is_symlink():
                    state_path.unlink()
            _restore_enabled_configs(args, transition_dir)
            _restore_canonical_config(args, transition_dir)
            _run("nginx", "-t")
            _run("systemctl", "reload", "nginx")
            raise


def datetime_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-production-sha")
    parser.add_argument("--target-sha")
    parser.add_argument("--acknowledge-production-change", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path("/opt/nura"))
    parser.add_argument("--legacy-web-root", type=Path, default=Path("/var/www/nura-ai.ru"))
    parser.add_argument("--release-root", type=Path, default=Path("/var/www/nura-releases"))
    parser.add_argument("--state-root", type=Path, default=Path("/var/lib/nura-release-state"))
    parser.add_argument("--backup-root", type=Path, default=Path("/var/backups/nura-release-transition"))
    parser.add_argument("--sites-enabled", type=Path, default=Path("/etc/nginx/sites-enabled"))
    parser.add_argument("--sites-available", type=Path, default=Path("/etc/nginx/sites-available"))
    parser.add_argument("--lock-file", type=Path, default=Path("/var/lock/nura-deploy.lock"))
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        inventory = collect_inventory(args)
        if args.output:
            if args.apply:
                raise TransitionError("--output is dry-run only")
            args.output.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        else:
            print(json.dumps(inventory, indent=2, sort_keys=True))
        if args.apply:
            apply_transition(args, inventory)
    except (OSError, TransitionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
