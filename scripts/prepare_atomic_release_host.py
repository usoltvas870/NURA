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
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple

try:
    import fcntl
except ImportError:  # pragma: no cover - apply mode is Linux-host only
    fcntl = None  # type: ignore[assignment]

EXPECTED_LEGACY_SHA = "d0d39ae8717ceb0920d98f27dd9092f746755c6c"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ENABLED_CONFIG_ALLOWLIST = frozenset(
    {"nura-ai.ru", "nura-ai.ru.bak", "nura-ai.ru.conf"}
)
PREPARED_CONFIG_ALLOWLIST = frozenset({"nura-ai.ru.conf"})
APPLICATION_SERVICES = ("api", "bot", "celery-worker", "celery-beat", "admin-bot")
SENSITIVE_SUFFIXES = (".env", ".key", ".pem", ".p12", ".pfx")
PUBLIC_TIMEOUT_SECONDS = 10.0
PUBLIC_ALIASES = {
    "/": "public/index.html",
    "/VERSION": "public/VERSION",
    "/vk-callback.html": "public/vk-callback.html",
    "/mini": "public/mini.html",
    "/success": "public/success.html",
    "/admin/": "public/admin/index.html",
    "/app/": "public/app/index.html",
}
REDIRECT_CONTRACTS = {
    "https://www.nura-ai.ru/app/?release-check=1": "https://nura-ai.ru/app/?release-check=1",
    "http://www.nura-ai.ru/app/?release-check=1": "https://nura-ai.ru/app/?release-check=1",
    "http://nura-ai.ru/app/?release-check=1": "https://nura-ai.ru/app/?release-check=1",
}
LEGACY_PUBLIC_EXCLUDED_PREFIXES = (".well-known/acme-challenge/",)


class TransitionError(RuntimeError):
    """Raised when the host is not safe for the one-time transition."""


class FetchResult(NamedTuple):
    status: int
    body: bytes
    location: str | None = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _fetch_public(url: str, timeout: float = PUBLIC_TIMEOUT_SECONDS) -> FetchResult:
    request = urllib.request.Request(
        url,
        headers={"Cache-Control": "no-cache, no-store", "Pragma": "no-cache"},
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            return FetchResult(response.status, response.read(), response.headers.get("Location"))
    except urllib.error.HTTPError as exc:
        return FetchResult(exc.code, exc.read(), exc.headers.get("Location"))


def verify_public_equivalence(
    release: Path,
    *,
    base_url: str = "https://nura-ai.ru",
    fetcher: Any = _fetch_public,
) -> dict[str, str]:
    """Prove exact public bytes, aliases, health and canonical redirects."""
    manifest_path = release / "public" / "release-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise TransitionError("legacy public release manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = {entry["destination"]: entry for entry in manifest.get("files", [])}
    if not files or "public/VERSION" not in files:
        raise TransitionError("legacy public release manifest inventory is incomplete")
    evidence: dict[str, str] = {}
    for destination, entry in sorted(files.items()):
        relative = destination.removeprefix("public/")
        source = release / destination
        if source.is_symlink() or not source.is_file():
            raise TransitionError(f"manifest public file is missing: {destination}")
        expected = source.read_bytes()
        if len(expected) != entry.get("size") or hashlib.sha256(expected).hexdigest() != entry.get("sha256"):
            raise TransitionError(f"manifest hash/size mismatch: {destination}")
        result = fetcher(f"{base_url.rstrip('/')}/{relative}")
        if result.status != 200 or result.body != expected:
            raise TransitionError(f"public byte equivalence failed: /{relative}")
        evidence[f"/{relative}"] = entry["sha256"]
    for endpoint, destination in PUBLIC_ALIASES.items():
        result = fetcher(f"{base_url.rstrip('/')}{endpoint}")
        expected = (release / destination).read_bytes()
        if result.status != 200 or result.body != expected:
            raise TransitionError(f"public alias equivalence failed: {endpoint}")
        evidence[endpoint] = hashlib.sha256(expected).hexdigest()
    health = fetcher(f"{base_url.rstrip('/')}/health")
    if health.status != 200:
        raise TransitionError("public health verification failed")
    for source, destination in REDIRECT_CONTRACTS.items():
        result = fetcher(source)
        if result.status not in {301, 302, 307, 308} or result.location != destination:
            raise TransitionError(f"canonical redirect verification failed: {source}")
        evidence[source] = destination
    return evidence


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _inventory_digest(entries: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical_json(entries)).hexdigest()


def _artifact_paths(artifact_dir: Path) -> tuple[Path, Path, Path]:
    return (
        artifact_dir / f"nura-static-{EXPECTED_LEGACY_SHA}.tar.gz",
        artifact_dir / f"nura-static-{EXPECTED_LEGACY_SHA}.tar.gz.sha256",
        artifact_dir / "release-manifest.json",
    )


def _build_legacy_artifact(repo_root: Path, artifact_dir: Path) -> tuple[Path, Path, Path]:
    checkout = Path(tempfile.mkdtemp(prefix="nura-legacy-checkout-"))
    try:
        shutil.rmtree(checkout)
        _run("git", "clone", "--quiet", "--no-checkout", "--shared", str(repo_root), str(checkout))
        _run("git", "-C", str(checkout), "checkout", "--quiet", "--detach", EXPECTED_LEGACY_SHA)
        _run(
            "python3",
            str(repo_root / "scripts" / "build_release_artifact.py"),
            "build",
            "--repo-root",
            str(checkout),
            "--target-sha",
            EXPECTED_LEGACY_SHA,
            "--output-dir",
            str(artifact_dir),
        )
        return _artifact_paths(artifact_dir)
    finally:
        shutil.rmtree(checkout, ignore_errors=True)


def _canonical_release_inventory(repo_root: Path) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="nura-legacy-artifact-") as temporary:
        _archive, _checksum, manifest_path = _build_legacy_artifact(
            repo_root, Path(temporary) / "artifact"
        )
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        entries = [
            {
                "path": entry["destination"].removeprefix("public/"),
                "size": entry["size"],
                "sha256": entry["sha256"],
            }
            for entry in manifest["files"]
        ]
        entries.append(
            {
                "path": "release-manifest.json",
                "size": len(manifest_bytes),
                "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            }
        )
        return sorted(entries, key=lambda entry: entry["path"])


def _legacy_extras(
    legacy_inventory: list[dict[str, Any]], canonical_inventory: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    canonical_paths = {entry["path"] for entry in canonical_inventory}
    return [
        entry
        for entry in legacy_inventory
        if entry["path"] not in canonical_paths
        and not entry["path"].startswith(LEGACY_PUBLIC_EXCLUDED_PREFIXES)
    ]


def _drop_candidate(inventory: dict[str, Any], *, status: str = "owner_review_required") -> dict[str, Any]:
    return {
        "schema": 1,
        "expected_production_sha": EXPECTED_LEGACY_SHA,
        "legacy_inventory_sha256": inventory["inventory_sha256"],
        "legacy_extra_files": [dict(entry) for entry in inventory["legacy_extra_files"]],
        "legacy_extra_inventory_sha256": inventory["legacy_extra_inventory_sha256"],
        "status": status,
    }


def _verify_approved_drop_manifest(
    path: Path | None, inventory: dict[str, Any]
) -> dict[str, Any] | None:
    extras = inventory["legacy_extra_files"]
    if not extras:
        if path is not None:
            raise TransitionError("approved drop manifest is unnecessary for zero legacy extras")
        return None
    if path is None:
        raise TransitionError("legacy extras require --approved-drop-manifest")
    if path.is_symlink() or not path.is_file():
        raise TransitionError("approved drop manifest must be a regular file")
    approved = json.loads(path.read_text(encoding="utf-8"))
    expected = _drop_candidate(inventory, status="approved")
    if approved != expected:
        raise TransitionError("approved drop manifest does not exactly match current legacy extras")
    return approved


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
    if names not in {ENABLED_CONFIG_ALLOWLIST, PREPARED_CONFIG_ALLOWLIST}:
        raise TransitionError(
            f"enabled Nginx filenames differ from audited strict sets: {sorted(names)}"
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


def _assert_legacy_inventory_unchanged(
    web_root: Path, expected: list[dict[str, Any]]
) -> None:
    if _public_inventory(web_root) != expected:
        raise TransitionError("legacy public inventory changed after approval/preflight")


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


def collect_inventory(
    args: argparse.Namespace,
    canonical_inventory: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    inventory = _public_inventory(args.legacy_web_root)
    encoded = _canonical_json(inventory)
    canonical = (
        canonical_inventory
        if canonical_inventory is not None
        else _canonical_release_inventory(args.repo_root)
    )
    extras = _legacy_extras(inventory, canonical)
    acme = [
        entry
        for entry in inventory
        if entry["path"].startswith(LEGACY_PUBLIC_EXCLUDED_PREFIXES)
    ]
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
        "canonical_release_file_count": len(canonical),
        "canonical_release_inventory": canonical,
        "acme_excluded_file_count": len(acme),
        "acme_excluded_inventory": acme,
        "legacy_extra_file_count": len(extras),
        "legacy_extra_total_bytes": sum(entry["size"] for entry in extras),
        "legacy_extra_inventory_sha256": _inventory_digest(extras),
        "legacy_extra_files": extras,
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


def _write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(_canonical_json(value) + b"\n")
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
        inspection = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
            check=False,
            capture_output=True,
            text=True,
        )
        if inspection.returncode == 0:
            if inspection.stdout.strip() != value["image_id"]:
                raise TransitionError(f"protected legacy image tag conflict: {service}")
            protected[service] = tag
            continue
        _run("docker", "image", "tag", value["image_id"], tag)
        inspected = _run("docker", "image", "inspect", "--format", "{{.Id}}", tag).strip()
        if inspected != value["image_id"]:
            raise TransitionError(f"protected legacy image tag mismatch: {service}")
        protected[service] = tag
    return protected


def _write_recovery_marker(transition_dir: Path, reason: str) -> Path:
    path = transition_dir / "transition-recovery-required.json"
    value = {
        "schema": 1,
        "status": "recovery_required",
        "reason": reason[:500],
        "recorded_at": datetime_utc(),
    }
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    except FileExistsError as exc:
        raise TransitionError("transition recovery evidence already exists; refusing overwrite") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
    return path


def _restore_and_verify_public(
    args: argparse.Namespace,
    transition_dir: Path,
    legacy_release: Path,
    original_error: BaseException,
) -> None:
    current = args.release_root / "current"
    if current.is_symlink() and current.resolve(strict=False) == legacy_release.resolve():
        current.unlink()
    _restore_enabled_configs(args, transition_dir)
    _restore_canonical_config(args, transition_dir)
    _run("nginx", "-t")
    _run("systemctl", "reload", "nginx")
    try:
        verify_public_equivalence(legacy_release, base_url=args.base_url)
    except Exception as restore_error:
        reason = f"activation failed: {original_error}; restored baseline verification failed: {restore_error}"
        _write_recovery_marker(transition_dir, reason)
        raise TransitionError(reason) from restore_error


class PreparedLegacyRelease(NamedTuple):
    verification_path: Path
    final_path: Path
    staging_path: Path | None
    archive: Path
    manifest: Path


def _prepare_legacy_release(
    args: argparse.Namespace, transition_dir: Path
) -> PreparedLegacyRelease:
    artifact_dir = transition_dir / "legacy-artifact"
    archive, checksum, manifest = _build_legacy_artifact(args.repo_root, artifact_dir)
    final = args.release_root / "releases" / EXPECTED_LEGACY_SHA
    if final.exists() or final.is_symlink():
        if final.is_symlink() or not final.is_dir():
            raise TransitionError("existing legacy final release is not a real directory")
        _run(
            "python3",
            "-c",
            "import importlib.util,json,pathlib,sys;"
            "s=importlib.util.spec_from_file_location('artifact',sys.argv[1]);"
            "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
            "m.verify_release_directory(pathlib.Path(sys.argv[2]),json.load(open(sys.argv[3],encoding='utf-8')))",
            str(args.repo_root / "scripts" / "build_release_artifact.py"),
            str(final),
            str(manifest),
        )
        return PreparedLegacyRelease(final, final, None, archive, manifest)
    staging = (
        args.release_root
        / "staging"
        / f"{EXPECTED_LEGACY_SHA}-transition-{os.getpid()}-{time.time_ns()}"
    )
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
    return PreparedLegacyRelease(staging, final, staging, archive, manifest)


def _finalize_prepared_release(args: argparse.Namespace, prepared: PreparedLegacyRelease) -> Path:
    if prepared.staging_path is None:
        return prepared.final_path
    output = _run(
        "python3",
        str(args.repo_root / "scripts" / "build_release_artifact.py"),
        "finalize",
        "--staging",
        str(prepared.staging_path),
        "--releases-root",
        str(args.release_root / "releases"),
        "--target-sha",
        EXPECTED_LEGACY_SHA,
    ).strip()
    if Path(output) != prepared.final_path:
        raise TransitionError("legacy release finalization returned an unexpected path")
    return prepared.final_path


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


def _copy_approved_drop_evidence(
    args: argparse.Namespace, inventory: dict[str, Any], transition_dir: Path
) -> None:
    approved = _verify_approved_drop_manifest(
        getattr(args, "approved_drop_manifest", None), inventory
    )
    if approved is None:
        return
    destination = transition_dir / "approved-drop-manifest.json"
    shutil.copy2(args.approved_drop_manifest, destination, follow_symlinks=False)
    if json.loads(destination.read_text(encoding="utf-8")) != approved:
        raise TransitionError("approved drop manifest evidence copy mismatch")


def validate_activation_history(value: dict[str, Any]) -> list[str]:
    if not isinstance(value.get("sha"), str) or SHA_PATTERN.fullmatch(value["sha"]) is None:
        raise TransitionError("legacy state SHA is invalid")
    history = value.get("activation_history", [])
    if not isinstance(history, list) or len(history) > 2:
        raise TransitionError("legacy state activation_history is invalid")
    if any(not isinstance(item, str) or SHA_PATTERN.fullmatch(item) is None for item in history):
        raise TransitionError("legacy state activation_history contains an invalid SHA")
    if len(history) != len(set(history)) or value.get("sha") in history:
        raise TransitionError("legacy state activation_history contains duplicate or self SHA")
    return history


def next_activation_history(current: dict[str, Any], target_sha: str) -> list[str]:
    if SHA_PATTERN.fullmatch(target_sha) is None:
        raise TransitionError("activation history target SHA is invalid")
    validate_activation_history(current)
    history: list[str] = []
    for item in [current["sha"], *current.get("activation_history", [])]:
        if item != target_sha and item not in history:
            history.append(item)
    return history[:2]


def _existing_transition_status(
    args: argparse.Namespace,
    prepared: PreparedLegacyRelease,
    protected_tags: dict[str, str],
    inventory: dict[str, Any],
    reviewed_nginx: bytes,
) -> str:
    current = args.release_root / "current"
    record = args.state_root / "releases" / f"{EXPECTED_LEGACY_SHA}.json"
    current_state = args.state_root / "current.json"
    present = [current.exists() or current.is_symlink(), record.exists(), current_state.exists()]
    if not any(present):
        return "not_prepared"
    if not all(present):
        raise TransitionError("partial legacy current/state disagreement requires recovery")
    if not current.is_symlink() or current.resolve(strict=True) != prepared.final_path.resolve(strict=True):
        raise TransitionError("prepared legacy current pointer mismatch requires recovery")
    if record.is_symlink() or current_state.is_symlink() or not record.is_file() or not current_state.is_file():
        raise TransitionError("prepared legacy state paths are invalid")
    record_value = json.loads(record.read_text(encoding="utf-8"))
    current_value = json.loads(current_state.read_text(encoding="utf-8"))
    if record_value != current_value:
        raise TransitionError("prepared legacy current/state records disagree")
    history = validate_activation_history(record_value)
    previous = args.state_root / "previous.json"
    if history:
        if previous.is_symlink() or not previous.is_file():
            raise TransitionError("prepared previous state pointer is missing")
        if json.loads(previous.read_text(encoding="utf-8")).get("sha") != history[0]:
            raise TransitionError("prepared previous state pointer mismatch")
    expected = {
        "sha": EXPECTED_LEGACY_SHA,
        "status": "successful",
        "legacy": True,
        "rollback_eligibility": True,
        "static_release_path": str(prepared.final_path),
        "artifact_sha256": _sha256(prepared.archive),
        "public_manifest_sha256": _sha256(prepared.final_path / "public/release-manifest.json"),
        "per_service_image_mapping": protected_tags,
        "per_service_image_ids": {
            service: value["image_id"] for service, value in inventory["services"].items()
        },
        "migration_delta": False,
    }
    for key, expected_value in expected.items():
        if record_value.get(key) != expected_value:
            raise TransitionError(f"prepared legacy immutable state mismatch: {key}")
    canonical = args.sites_available / "nura-ai.ru.conf"
    enabled = args.sites_enabled / "nura-ai.ru.conf"
    if canonical.read_bytes() != reviewed_nginx or not enabled.is_symlink():
        raise TransitionError("prepared legacy Nginx state mismatch")
    if set(path.name for path in _enabled_configs(args.sites_enabled)) != PREPARED_CONFIG_ALLOWLIST:
        raise TransitionError("prepared legacy enabled config set mismatch")
    return "already_prepared"


def _remove_staging(prepared: PreparedLegacyRelease | None, args: argparse.Namespace) -> None:
    if prepared is None or prepared.staging_path is None or not prepared.staging_path.exists():
        return
    staging_root = (args.release_root / "staging").resolve(strict=True)
    staging = prepared.staging_path.resolve(strict=True)
    if staging.parent != staging_root or prepared.staging_path.is_symlink():
        raise TransitionError("unsafe legacy transition staging cleanup target")
    shutil.rmtree(staging)


def apply_transition(args: argparse.Namespace, inventory: dict[str, Any]) -> str:
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
        locked_inventory = collect_inventory(args)
        if _canonical_json(locked_inventory) != _canonical_json(inventory):
            raise TransitionError("transition inventory changed before the common lock")
        inventory = locked_inventory
        transition_dir = args.backup_root / (
            f"{time.time_ns()}-{inventory['inventory_sha256'][:16]}"
        )
        transition_dir.mkdir(parents=True, mode=0o750)
        _snapshot(args, inventory, transition_dir)
        _assert_legacy_inventory_unchanged(args.legacy_web_root, inventory["files"])
        for directory in (
            args.release_root / "releases",
            args.release_root / "staging",
            args.state_root / "releases",
            args.state_root / "logs",
        ):
            directory.mkdir(parents=True, exist_ok=True)
        prepared: PreparedLegacyRelease | None = None
        try:
            prepared = _prepare_legacy_release(args, transition_dir)
            verify_public_equivalence(prepared.verification_path, base_url=args.base_url)
            _copy_approved_drop_evidence(args, inventory, transition_dir)
            protected_tags = _protect_legacy_images(inventory["services"])
            status = _existing_transition_status(
                args, prepared, protected_tags, inventory, reviewed_nginx
            )
            if status == "already_prepared":
                return status
            legacy_release = _finalize_prepared_release(args, prepared)
        except Exception as exc:
            _remove_staging(prepared, args)
            _write_recovery_marker(transition_dir, f"transition precheck failed: {exc}")
            raise
        current = args.release_root / "current"
        temporary = args.release_root / f".current.transition.{os.getpid()}"
        canonical = args.sites_available / "nura-ai.ru.conf"
        if not canonical.is_file() or canonical.is_symlink():
            raise TransitionError("canonical reviewed Nginx config is missing")
        try:
            _assert_legacy_inventory_unchanged(args.legacy_web_root, inventory["files"])
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
            verify_public_equivalence(legacy_release, base_url=args.base_url)
        except Exception as exc:
            if temporary.exists() or temporary.is_symlink():
                temporary.unlink()
            _restore_and_verify_public(args, transition_dir, legacy_release, exc)
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
            "activation_history": [],
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
        except Exception as exc:
            for state_path in (record_path, current_state_path):
                if state_path.is_file() and not state_path.is_symlink():
                    state_path.unlink()
            _restore_and_verify_public(args, transition_dir, legacy_release, exc)
            raise
        return "prepared"


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
    parser.add_argument("--base-url", default="https://nura-ai.ru")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--drop-candidate-output", type=Path)
    parser.add_argument("--approved-drop-manifest", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.apply and args.drop_candidate_output:
            raise TransitionError("--drop-candidate-output is dry-run only")
        if not args.apply and args.approved_drop_manifest:
            raise TransitionError("--approved-drop-manifest is apply-only")
        if args.drop_candidate_output:
            candidate = args.drop_candidate_output.resolve(strict=False)
            repository = args.repo_root.resolve(strict=True)
            if candidate == repository or repository in candidate.parents:
                raise TransitionError("drop candidate must not be written inside repository")
        inventory = collect_inventory(args)
        if args.output:
            if args.apply:
                raise TransitionError("--output is dry-run only")
            args.output.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        else:
            print(json.dumps(inventory, indent=2, sort_keys=True))
        if args.drop_candidate_output:
            _write_canonical_json(args.drop_candidate_output, _drop_candidate(inventory))
        if args.apply:
            status = apply_transition(args, inventory)
            print(json.dumps({"transition_status": status}, sort_keys=True))
    except (OSError, TransitionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
