#!/usr/bin/env python3
"""Build and apply the tracked static deployment manifest for NURA."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MANIFEST_SCHEMA = 1
MIGRATION_DIRECTORY = "nura_app/alembic/versions"

EXPLICIT_MAPPINGS: tuple[tuple[str, str], ...] = (
    ("index.html", "index.html"),
    ("privacy.html", "privacy.html"),
    ("offer.html", "offer.html"),
    ("contacts.html", "contacts.html"),
    ("mini.html", "mini.html"),
    ("success.html", "success.html"),
    ("vk-callback.html", "vk-callback.html"),
    ("personal-data-consent.html", "personal-data-consent.html"),
    ("marketing-consent.html", "marketing-consent.html"),
    ("acceptable-use.html", "acceptable-use.html"),
    ("theme.css", "theme.css"),
    ("landing-v2.css", "landing-v2.css"),
    ("landing-v2.js", "landing-v2.js"),
    ("favicon.ico", "favicon.ico"),
    ("hero.png", "hero.png"),
    ("frontend/nura-hero-final.webp", "nura-hero-final.webp"),
    ("frontend/nura-hero-final-mobile.webp", "nura-hero-final-mobile.webp"),
    ("frontend/admin/index.html", "admin/index.html"),
    ("frontend/manifest.json", "manifest.json"),
    ("frontend/service-worker.js", "service-worker.js"),
    ("frontend/pwa-install.js", "pwa-install.js"),
    ("frontend/offline.html", "offline.html"),
    ("frontend/pwa/metrika.js", "metrika.js"),
    ("frontend/pwa/pwa-release.js", "pwa-release.js"),
    ("frontend/pwa/pwa-release.json", "pwa-release.json"),
)

DIRECTORY_MAPPINGS: tuple[tuple[str, str], ...] = (
    ("frontend/pwa/app", "app"),
    ("frontend/assets", "assets"),
    ("frontend/icons", "icons"),
    ("frontend/fonts", "fonts"),
    ("frontend/landing-v2", "landing-v2"),
)

EXCLUDED_TRACKED_SOURCES = frozenset({"frontend/pwa/app/AGENTS.md"})

LEGACY_D0_SHA = "d0d39ae8717ceb0920d98f27dd9092f746755c6c"
LEGACY_D0_EXPLICIT_MAPPINGS: tuple[tuple[str, str], ...] = (
    ("index.html", "index.html"),
    ("privacy.html", "privacy.html"),
    ("offer.html", "offer.html"),
    ("contacts.html", "contacts.html"),
    ("mini.html", "mini.html"),
    ("success.html", "success.html"),
    ("personal-data-consent.html", "personal-data-consent.html"),
    ("marketing-consent.html", "marketing-consent.html"),
    ("acceptable-use.html", "acceptable-use.html"),
    ("vk-callback.html", "vk-callback.html"),
    ("theme.css", "theme.css"),
    ("landing-v2.css", "landing-v2.css"),
    ("landing-v2.js", "landing-v2.js"),
    ("favicon.ico", "favicon.ico"),
    ("hero.png", "hero.png"),
    ("frontend/nura-hero-final.webp", "nura-hero-final.webp"),
    ("frontend/nura-hero-final-mobile.webp", "nura-hero-final-mobile.webp"),
    ("frontend/admin/index.html", "admin/index.html"),
    ("frontend/manifest.json", "manifest.json"),
    ("frontend/service-worker.js", "service-worker.js"),
    ("frontend/pwa-install.js", "pwa-install.js"),
    ("frontend/offline.html", "offline.html"),
    ("frontend/pwa/metrika.js", "metrika.js"),
)
LEGACY_D0_DIRECTORY_MAPPINGS: tuple[tuple[str, str], ...] = (
    ("frontend/pwa/app", "app"),
    ("frontend/icons", "icons"),
    ("frontend/fonts", "fonts"),
    ("frontend/landing-v2", "landing-v2"),
)


class DeploymentContractError(RuntimeError):
    """Raised when release inputs do not satisfy the deployment contract."""


def _run_git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise DeploymentContractError(detail)
    return result.stdout


def validate_sha(value: str, label: str = "SHA") -> str:
    if not SHA_PATTERN.fullmatch(value):
        raise DeploymentContractError(f"{label} must be exactly 40 lowercase hexadecimal characters")
    return value


def validate_relative_path(value: str, label: str) -> PurePosixPath:
    if not value or "\\" in value:
        raise DeploymentContractError(f"Invalid {label}: {value!r}")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise DeploymentContractError(f"Invalid {label}: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise DeploymentContractError(f"Invalid {label}: {value!r}")
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tracked_files(repo_root: Path) -> set[str]:
    output = _run_git(repo_root, "ls-files", "-z")
    return {item for item in output.split("\0") if item}


def _target_blob(repo_root: Path, target_sha: str, source: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "blob", f"{target_sha}:{source}"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "target blob is unavailable"
        raise DeploymentContractError(f"Cannot read target blob for {source}: {detail}")
    return result.stdout


def _assert_regular_source(repo_root: Path, source: str, tracked: set[str]) -> Path:
    validate_relative_path(source, "source path")
    if source not in tracked:
        raise DeploymentContractError(f"Required source is not tracked: {source}")

    source_path = repo_root.joinpath(*PurePosixPath(source).parts)
    current = repo_root
    for part in PurePosixPath(source).parts:
        current = current / part
        if current.is_symlink():
            raise DeploymentContractError(f"Unexpected source symlink: {source}")
    if not source_path.is_file():
        raise DeploymentContractError(f"Required source is missing or not a regular file: {source}")
    return source_path


def _expected_mappings(
    tracked: set[str],
    *,
    explicit_mappings: Sequence[tuple[str, str]] = EXPLICIT_MAPPINGS,
    directory_mappings: Sequence[tuple[str, str]] = DIRECTORY_MAPPINGS,
    excluded_sources: frozenset[str] = EXCLUDED_TRACKED_SOURCES,
) -> list[tuple[str, str]]:
    mappings = list(explicit_mappings)
    for source_prefix, destination_prefix in directory_mappings:
        prefix = f"{source_prefix}/"
        directory_sources = sorted(
            source
            for source in tracked
            if source.startswith(prefix) and source not in excluded_sources
        )
        if not directory_sources:
            raise DeploymentContractError(f"Tracked source directory is empty: {source_prefix}")
        for source in directory_sources:
            relative = source.removeprefix(prefix)
            mappings.append((source, f"{destination_prefix}/{relative}"))
    return mappings


def build_manifest(
    repo_root: Path,
    target_sha: str,
    *,
    source_profile: str = "current",
) -> dict[str, Any]:
    repo_root = repo_root.resolve(strict=True)
    validate_sha(target_sha, "target SHA")
    head = _run_git(repo_root, "rev-parse", "HEAD").strip()
    if head != target_sha:
        raise DeploymentContractError(f"HEAD/target mismatch: HEAD={head}, target={target_sha}")

    tracked = _tracked_files(repo_root)
    if source_profile == "current":
        mappings = _expected_mappings(tracked)
    elif source_profile == "legacy-d0":
        if target_sha != LEGACY_D0_SHA:
            raise DeploymentContractError(
                "legacy-d0 source profile requires the exact audited legacy SHA"
            )
        mappings = _expected_mappings(
            tracked,
            explicit_mappings=LEGACY_D0_EXPLICIT_MAPPINGS,
            directory_mappings=LEGACY_D0_DIRECTORY_MAPPINGS,
            excluded_sources=frozenset(),
        )
    else:
        raise DeploymentContractError(f"Unsupported source profile: {source_profile}")
    destinations: set[str] = set()
    entries: list[dict[str, Any]] = []
    for source, destination in mappings:
        source_path = _assert_regular_source(repo_root, source, tracked)
        target_content = _target_blob(repo_root, target_sha, source)
        target_digest = hashlib.sha256(target_content).hexdigest()
        if source_path.stat().st_size != len(target_content) or sha256_file(source_path) != target_digest:
            raise DeploymentContractError(f"Worktree source differs from target blob: {source}")
        validate_relative_path(destination, "destination path")
        if destination in destinations:
            raise DeploymentContractError(f"Duplicate destination: {destination}")
        destinations.add(destination)
        entries.append(
            {
                "source": source,
                "destination": destination,
                "size": len(target_content),
                "sha256": target_digest,
            }
        )

    entries.sort(key=lambda entry: entry["destination"])
    return {"schema": MANIFEST_SCHEMA, "target_sha": target_sha, "entries": entries}


def write_manifest(manifest: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentContractError(f"Cannot read deployment manifest: {exc}") from exc
    if not isinstance(raw, dict):
        raise DeploymentContractError("Deployment manifest must be a JSON object")
    return raw


def validate_manifest_structure(manifest: dict[str, Any]) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise DeploymentContractError("Unsupported deployment manifest schema")
    validate_sha(str(manifest.get("target_sha", "")), "manifest target SHA")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise DeploymentContractError("Deployment manifest entries must be a non-empty list")

    destinations: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise DeploymentContractError("Deployment manifest entry must be an object")
        source = str(entry.get("source", ""))
        destination = str(entry.get("destination", ""))
        validate_relative_path(source, "manifest source path")
        validate_relative_path(destination, "manifest destination path")
        if destination in destinations:
            raise DeploymentContractError(f"Duplicate destination: {destination}")
        destinations.add(destination)
        if not isinstance(entry.get("size"), int) or entry["size"] < 0:
            raise DeploymentContractError(f"Invalid source size for {source}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))):
            raise DeploymentContractError(f"Invalid SHA-256 for {source}")


def _safe_destination(web_root: Path, destination: str) -> Path:
    relative = validate_relative_path(destination, "destination path")
    web_root_resolved = web_root.resolve(strict=True)
    destination_path = web_root.joinpath(*relative.parts)

    current = web_root
    for part in relative.parts[:-1]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise DeploymentContractError(f"Unexpected destination symlink: {destination}")
    if destination_path.exists() and destination_path.is_symlink():
        raise DeploymentContractError(f"Unexpected destination symlink: {destination}")

    resolved = destination_path.resolve(strict=False)
    if resolved != web_root_resolved and web_root_resolved not in resolved.parents:
        raise DeploymentContractError(f"Destination escapes web root: {destination}")
    return destination_path


def copy_manifest(
    repo_root: Path,
    web_root: Path,
    manifest: dict[str, Any],
    *,
    copy_file: Callable[[Path, Path], None] | None = None,
) -> None:
    validate_manifest_structure(manifest)
    repo_root = repo_root.resolve(strict=True)
    web_root = web_root.resolve(strict=True)

    expected = build_manifest(repo_root, str(manifest["target_sha"]))
    if manifest != expected:
        raise DeploymentContractError("Deployment manifest does not match the exact tracked checkout")

    copier = copy_file or shutil.copyfile
    for entry in manifest["entries"]:
        source = repo_root.joinpath(*PurePosixPath(entry["source"]).parts)
        destination = _safe_destination(web_root, entry["destination"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.nura-deploy-{os.getpid()}.tmp")
        try:
            copier(source, temporary)
            temporary.chmod(0o644)
            if sha256_file(temporary) != entry["sha256"]:
                raise DeploymentContractError(
                    f"Copied file hash mismatch before activation: {entry['destination']}"
                )
            temporary.replace(destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        if sha256_file(destination) != entry["sha256"]:
            raise DeploymentContractError(
                f"Destination hash mismatch after copy: {entry['destination']}"
            )


def migration_delta(repo_root: Path, current_sha: str, target_sha: str) -> list[str]:
    validate_sha(current_sha, "current production SHA")
    validate_sha(target_sha, "target SHA")
    for sha in (current_sha, target_sha):
        _run_git(repo_root, "cat-file", "-e", f"{sha}^{{commit}}")
    result = _run_git(
        repo_root,
        "diff",
        "--name-only",
        current_sha,
        target_sha,
        "--",
        MIGRATION_DIRECTORY,
    )
    return sorted(line for line in result.splitlines() if line)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build-manifest")
    build.add_argument("--repo-root", type=Path, required=True)
    build.add_argument("--target-sha", required=True)
    build.add_argument("--output", type=Path, required=True)

    copy = subparsers.add_parser("copy-manifest")
    copy.add_argument("--repo-root", type=Path, required=True)
    copy.add_argument("--web-root", type=Path, required=True)
    copy.add_argument("--manifest", type=Path, required=True)

    migrations = subparsers.add_parser("migration-delta")
    migrations.add_argument("--repo-root", type=Path, required=True)
    migrations.add_argument("--current-sha", required=True)
    migrations.add_argument("--target-sha", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build-manifest":
            manifest = build_manifest(args.repo_root, args.target_sha)
            write_manifest(manifest, args.output)
            print(f"Manifest contains {len(manifest['entries'])} tracked files")
        elif args.command == "copy-manifest":
            copy_manifest(args.repo_root, args.web_root, load_manifest(args.manifest))
            print("All manifest source and destination hashes verified")
        elif args.command == "migration-delta":
            for path in migration_delta(args.repo_root, args.current_sha, args.target_sha):
                print(path)
        else:  # pragma: no cover - argparse enforces the command choices
            raise DeploymentContractError(f"Unknown command: {args.command}")
    except DeploymentContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
