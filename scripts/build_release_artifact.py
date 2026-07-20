#!/usr/bin/env python3
"""Build, verify, and stage immutable NURA static release artifacts."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import deploy_static_release as static_contract

SCHEMA_VERSION = 2
ARTIFACT_FORMAT = "nura-static-tar-gzip"
ARTIFACT_FORMAT_VERSION = 1
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_MEMBER = "public/release-manifest.json"
VERSION_MEMBER = "public/VERSION"
REQUIRED_PUBLIC_FILES = frozenset(
    {
        "public/index.html",
        "public/vk-callback.html",
        "public/service-worker.js",
        "public/pwa-release.js",
        "public/pwa-release.json",
        "public/manifest.json",
        "public/offline.html",
        "public/app/index.html",
        VERSION_MEMBER,
    }
)


class ArtifactContractError(RuntimeError):
    """Raised when an artifact or release directory violates the contract."""


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise ArtifactContractError(detail)
    return result.stdout


def validate_sha(value: str, label: str = "SHA") -> str:
    if not SHA_PATTERN.fullmatch(value):
        raise ArtifactContractError(f"{label} must be exactly 40 lowercase hexadecimal characters")
    return value


def _validate_member_name(value: str) -> PurePosixPath:
    if not value or value.startswith("/") or "\\" in value or "\0" in value:
        raise ArtifactContractError(f"unsafe artifact member path: {value!r}")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ArtifactContractError(f"unsafe artifact member path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ArtifactContractError(f"unsafe artifact member path: {value!r}")
    return path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _commit_timestamp(repo_root: Path, target_sha: str) -> tuple[int, str]:
    raw = _git(repo_root, "show", "-s", "--format=%ct", target_sha).strip()
    try:
        epoch = int(raw)
    except ValueError as exc:
        raise ArtifactContractError("target commit timestamp is invalid") from exc
    stamp = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return epoch, stamp


def _payload(repo_root: Path, target_sha: str) -> tuple[dict[str, bytes], dict[str, Any], int]:
    repo_root = repo_root.resolve(strict=True)
    validate_sha(target_sha, "target SHA")
    _git(repo_root, "cat-file", "-e", f"{target_sha}^{{commit}}")
    head = _git(repo_root, "rev-parse", "HEAD").strip()
    if head != target_sha:
        raise ArtifactContractError(f"HEAD/target mismatch: HEAD={head}, target={target_sha}")

    epoch, commit_timestamp = _commit_timestamp(repo_root, target_sha)
    source_manifest = static_contract.build_manifest(repo_root, target_sha)
    files: dict[str, bytes] = {}
    source_by_destination: dict[str, str] = {}
    for entry in source_manifest["entries"]:
        destination = f"public/{entry['destination']}"
        _validate_member_name(destination)
        folded = destination.casefold()
        if any(existing.casefold() == folded for existing in files):
            raise ArtifactContractError(f"duplicate or case-colliding destination: {destination}")
        data = subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "blob", f"{target_sha}:{entry['source']}"],
            check=True,
            capture_output=True,
        ).stdout
        files[destination] = data
        source_by_destination[destination] = entry["source"]

    version = f"{target_sha} {commit_timestamp}\n".encode()
    if VERSION_MEMBER in files:
        raise ArtifactContractError("VERSION destination collides with tracked content")
    files[VERSION_MEMBER] = version
    source_by_destination[VERSION_MEMBER] = "generated:commit-metadata"

    missing = REQUIRED_PUBLIC_FILES - files.keys()
    if missing:
        raise ArtifactContractError(f"required release files are missing: {', '.join(sorted(missing))}")

    inventory = [
        {
            "destination": name,
            "source": source_by_destination[name],
            "size": len(files[name]),
            "sha256": sha256_bytes(files[name]),
        }
        for name in sorted(files)
    ]
    aggregate = sha256_bytes(_canonical_json(inventory))
    manifest: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "target_sha": target_sha,
        "release_id": target_sha,
        "commit_timestamp": commit_timestamp,
        "artifact": {"format": ARTIFACT_FORMAT, "version": ARTIFACT_FORMAT_VERSION},
        "file_count": len(inventory),
        "files": inventory,
        "aggregate_manifest_sha256": aggregate,
    }
    files[MANIFEST_MEMBER] = _canonical_json(manifest)
    return files, manifest, epoch


def _directory_names(file_names: Sequence[str]) -> list[str]:
    directories: set[str] = set()
    for name in file_names:
        path = PurePosixPath(name)
        for parent in path.parents:
            if str(parent) != ".":
                directories.add(str(parent))
    return sorted(directories)


def _tar_bytes(files: dict[str, bytes], epoch: int) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for directory in _directory_names(list(files)):
            info = tarfile.TarInfo(f"{directory}/")
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = epoch
            info.pax_headers = {}
            archive.addfile(info)
        for name in sorted(files):
            data = files[name]
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = epoch
            info.pax_headers = {}
            archive.addfile(info, io.BytesIO(data))
    compressed = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=epoch, compresslevel=9) as stream:
        stream.write(raw.getvalue())
    return compressed.getvalue()


def build_artifact(repo_root: Path, target_sha: str, output_dir: Path) -> tuple[Path, Path, Path]:
    files, manifest, epoch = _payload(repo_root, target_sha)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"nura-static-{target_sha}.tar.gz"
    checksum_path = output_dir / f"nura-static-{target_sha}.tar.gz.sha256"
    manifest_path = output_dir / "release-manifest.json"
    archive_bytes = _tar_bytes(files, epoch)
    archive_path.write_bytes(archive_bytes)
    digest = sha256_bytes(archive_bytes)
    checksum_path.write_text(f"{digest}  {archive_path.name}\n", encoding="ascii")
    manifest_path.write_bytes(_canonical_json(manifest))
    return archive_path, checksum_path, manifest_path


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactContractError(f"cannot read release manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise ArtifactContractError("release manifest must be an object")
    return value


def validate_manifest(manifest: dict[str, Any], target_sha: str | None = None) -> dict[str, dict[str, Any]]:
    if manifest.get("schema") != SCHEMA_VERSION:
        raise ArtifactContractError("unsupported release manifest schema")
    actual_sha = validate_sha(str(manifest.get("target_sha", "")), "manifest target SHA")
    if target_sha is not None and actual_sha != validate_sha(target_sha, "target SHA"):
        raise ArtifactContractError("manifest target SHA mismatch")
    if manifest.get("release_id") != actual_sha:
        raise ArtifactContractError("release ID mismatch")
    artifact = manifest.get("artifact")
    if artifact != {"format": ARTIFACT_FORMAT, "version": ARTIFACT_FORMAT_VERSION}:
        raise ArtifactContractError("artifact format/version mismatch")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ArtifactContractError("release inventory must be a non-empty list")
    if manifest.get("file_count") != len(entries):
        raise ArtifactContractError("release manifest file count mismatch")
    if entries != sorted(entries, key=lambda item: str(item.get("destination", ""))):
        raise ArtifactContractError("release inventory is not ordered")
    indexed: dict[str, dict[str, Any]] = {}
    folded: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ArtifactContractError("release inventory entry must be an object")
        destination = str(entry.get("destination", ""))
        _validate_member_name(destination)
        if destination in indexed or destination.casefold() in folded:
            raise ArtifactContractError(f"duplicate or case-colliding destination: {destination}")
        if not isinstance(entry.get("size"), int) or entry["size"] < 0:
            raise ArtifactContractError(f"invalid size for {destination}")
        if not HASH_PATTERN.fullmatch(str(entry.get("sha256", ""))):
            raise ArtifactContractError(f"invalid SHA-256 for {destination}")
        indexed[destination] = entry
        folded.add(destination.casefold())
    missing = REQUIRED_PUBLIC_FILES - indexed.keys()
    if missing:
        raise ArtifactContractError(f"required release files are missing: {', '.join(sorted(missing))}")
    expected_aggregate = sha256_bytes(_canonical_json(entries))
    if manifest.get("aggregate_manifest_sha256") != expected_aggregate:
        raise ArtifactContractError("aggregate manifest SHA-256 mismatch")
    return indexed


def _expected_checksum(checksum_path: Path, archive_path: Path) -> str:
    fields = checksum_path.read_text(encoding="ascii").strip().split()
    if len(fields) != 2 or not HASH_PATTERN.fullmatch(fields[0]) or fields[1] != archive_path.name:
        raise ArtifactContractError("archive checksum sidecar is invalid")
    return fields[0]


def inspect_artifact(
    archive_path: Path,
    checksum_path: Path,
    manifest_path: Path,
    target_sha: str | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    expected_checksum = _expected_checksum(checksum_path, archive_path)
    if sha256_file(archive_path) != expected_checksum:
        raise ArtifactContractError("archive checksum mismatch")
    manifest = load_manifest(manifest_path)
    indexed = validate_manifest(manifest, target_sha)
    expected_files = set(indexed) | {MANIFEST_MEMBER}
    expected_directories = set(_directory_names(sorted(expected_files)))
    payload: dict[str, bytes] = {}
    seen: set[str] = set()
    folded: set[str] = set()
    actual_directories: set[str] = set()
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            name = member.name.rstrip("/") if member.isdir() else member.name
            _validate_member_name(name)
            if name in seen:
                raise ArtifactContractError(f"duplicate archive member: {name}")
            if name.casefold() in folded:
                raise ArtifactContractError(f"case-colliding archive member: {name}")
            seen.add(name)
            folded.add(name.casefold())
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise ArtifactContractError(f"unsafe archive member type: {member.name}")
            if not (member.isdir() or member.isfile()):
                raise ArtifactContractError(f"unsupported archive member type: {member.name}")
            if member.isfile():
                if member.name not in expected_files:
                    raise ArtifactContractError(f"unexpected artifact member: {member.name}")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ArtifactContractError(f"cannot read artifact member: {member.name}")
                payload[member.name] = stream.read()
            else:
                actual_directories.add(name)
    if actual_directories != expected_directories:
        raise ArtifactContractError("artifact directory inventory mismatch")
    if set(payload) != expected_files:
        missing = expected_files - payload.keys()
        extra = payload.keys() - expected_files
        raise ArtifactContractError(f"artifact inventory mismatch; missing={sorted(missing)}, extra={sorted(extra)}")
    if payload[MANIFEST_MEMBER] != _canonical_json(manifest):
        raise ArtifactContractError("embedded release manifest mismatch")
    for name, entry in indexed.items():
        data = payload[name]
        if len(data) != entry["size"] or sha256_bytes(data) != entry["sha256"]:
            raise ArtifactContractError(f"artifact member hash/size mismatch: {name}")
    return manifest, payload


def extract_artifact(
    archive_path: Path,
    checksum_path: Path,
    manifest_path: Path,
    staging_path: Path,
    target_sha: str | None = None,
) -> dict[str, Any]:
    manifest, payload = inspect_artifact(archive_path, checksum_path, manifest_path, target_sha)
    if staging_path.exists() or staging_path.is_symlink():
        raise ArtifactContractError(f"staging path already exists: {staging_path}")
    staging_path.mkdir(parents=True, mode=0o755)
    try:
        for name in sorted(payload):
            destination = staging_path.joinpath(*PurePosixPath(name).parts)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            destination.write_bytes(payload[name])
            destination.chmod(0o644)
        verify_release_directory(staging_path, manifest)
    except Exception:
        shutil.rmtree(staging_path, ignore_errors=True)
        raise
    return manifest


def verify_release_directory(release_path: Path, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    if release_path.is_symlink() or not release_path.is_dir():
        raise ArtifactContractError("release path must be a real directory")
    embedded_path = release_path / MANIFEST_MEMBER
    embedded = load_manifest(embedded_path)
    if manifest is not None and embedded != manifest:
        raise ArtifactContractError("release directory manifest mismatch")
    indexed = validate_manifest(embedded)
    actual: set[str] = set()
    for path in release_path.rglob("*"):
        relative = path.relative_to(release_path).as_posix()
        if path.is_symlink():
            raise ArtifactContractError(f"release directory contains symlink: {relative}")
        if path.is_file():
            actual.add(relative)
        elif not path.is_dir():
            raise ArtifactContractError(f"release directory contains special file: {relative}")
    expected = set(indexed) | {MANIFEST_MEMBER}
    if actual != expected:
        raise ArtifactContractError("release directory inventory mismatch")
    if embedded_path.read_bytes() != _canonical_json(embedded):
        raise ArtifactContractError("embedded manifest is not canonical")
    for name, entry in indexed.items():
        path = release_path.joinpath(*PurePosixPath(name).parts)
        if path.stat().st_size != entry["size"] or sha256_file(path) != entry["sha256"]:
            raise ArtifactContractError(f"release directory hash/size mismatch: {name}")
    return embedded


def finalize_release(staging_path: Path, releases_root: Path, target_sha: str) -> Path:
    validate_sha(target_sha, "target SHA")
    releases_root.mkdir(parents=True, exist_ok=True, mode=0o755)
    if staging_path.stat().st_dev != releases_root.stat().st_dev:
        raise ArtifactContractError("staging and releases directories must be on the same filesystem")
    manifest = verify_release_directory(staging_path)
    if manifest["target_sha"] != target_sha:
        raise ArtifactContractError("staging release SHA mismatch")
    final_path = releases_root / target_sha
    if final_path.exists() or final_path.is_symlink():
        existing = verify_release_directory(final_path)
        if existing != manifest:
            raise ArtifactContractError("existing final release does not match incoming release")
        shutil.rmtree(staging_path)
        return final_path
    os.replace(staging_path, final_path)
    return final_path


def atomic_switch(current_path: Path, target_path: Path) -> None:
    target_path = target_path.resolve(strict=True)
    if not target_path.is_dir():
        raise ArtifactContractError("current target must be a release directory")
    current_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = current_path.with_name(f".{current_path.name}.{uuid.uuid4().hex}.tmp")
    relative_target = os.path.relpath(target_path, current_path.parent)
    try:
        os.symlink(relative_target, temporary, target_is_directory=True)
        if temporary.resolve(strict=True) != target_path:
            raise ArtifactContractError("temporary current symlink target mismatch")
        os.replace(temporary, current_path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
    if not current_path.is_symlink() or current_path.resolve(strict=True) != target_path:
        raise ArtifactContractError("current symlink verification failed")


def validate_current(current_path: Path, expected_sha: str) -> Path:
    validate_sha(expected_sha, "expected SHA")
    if not current_path.is_symlink():
        raise ArtifactContractError("current must be a symlink")
    target = current_path.resolve(strict=True)
    if target.name != expected_sha:
        raise ArtifactContractError("current symlink target SHA mismatch")
    manifest = verify_release_directory(target)
    if manifest["target_sha"] != expected_sha:
        raise ArtifactContractError("current release manifest SHA mismatch")
    return target


def disk_inode_gate(
    path: Path,
    archive_size: int,
    extracted_size: int,
    docker_headroom: int,
    reserve_bytes: int,
    required_inodes: int,
) -> None:
    usage = shutil.disk_usage(path)
    required = archive_size + (extracted_size * 2) + docker_headroom + reserve_bytes
    if usage.free < required:
        raise ArtifactContractError(f"insufficient disk reserve: free={usage.free}, required={required}")
    stats = os.statvfs(path)
    if stats.f_favail < required_inodes:
        raise ArtifactContractError(
            f"insufficient inode reserve: free={stats.f_favail}, required={required_inodes}"
        )


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(_canonical_json(value))
    temporary.chmod(0o640)
    os.replace(temporary, path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--repo-root", type=Path, required=True)
    build.add_argument("--target-sha", required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    for command in (verify,):
        command.add_argument("--archive", type=Path, required=True)
        command.add_argument("--checksum", type=Path, required=True)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--target-sha")
    extract = subparsers.add_parser("extract")
    extract.add_argument("--archive", type=Path, required=True)
    extract.add_argument("--checksum", type=Path, required=True)
    extract.add_argument("--manifest", type=Path, required=True)
    extract.add_argument("--staging", type=Path, required=True)
    extract.add_argument("--target-sha")
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--staging", type=Path, required=True)
    finalize.add_argument("--releases-root", type=Path, required=True)
    finalize.add_argument("--target-sha", required=True)
    switch = subparsers.add_parser("switch-current")
    switch.add_argument("--current", type=Path, required=True)
    switch.add_argument("--target", type=Path, required=True)
    current = subparsers.add_parser("validate-current")
    current.add_argument("--current", type=Path, required=True)
    current.add_argument("--expected-sha", required=True)
    gate = subparsers.add_parser("disk-gate")
    gate.add_argument("--path", type=Path, required=True)
    gate.add_argument("--archive-size", type=int, required=True)
    gate.add_argument("--extracted-size", type=int, required=True)
    gate.add_argument("--docker-headroom", type=int, required=True)
    gate.add_argument("--reserve-bytes", type=int, required=True)
    gate.add_argument("--required-inodes", type=int, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            paths = build_artifact(args.repo_root, args.target_sha, args.output_dir)
            print("\n".join(str(path) for path in paths))
        elif args.command == "verify":
            manifest, _ = inspect_artifact(
                args.archive, args.checksum, args.manifest, args.target_sha
            )
            print(f"verified {manifest['file_count']} release files")
        elif args.command == "extract":
            manifest = extract_artifact(
                args.archive,
                args.checksum,
                args.manifest,
                args.staging,
                args.target_sha,
            )
            print(f"extracted {manifest['file_count']} release files")
        elif args.command == "finalize":
            print(finalize_release(args.staging, args.releases_root, args.target_sha))
        elif args.command == "switch-current":
            atomic_switch(args.current, args.target)
        elif args.command == "validate-current":
            print(validate_current(args.current, args.expected_sha))
        elif args.command == "disk-gate":
            disk_inode_gate(
                args.path,
                args.archive_size,
                args.extracted_size,
                args.docker_headroom,
                args.reserve_bytes,
                args.required_inodes,
            )
        else:  # pragma: no cover
            raise ArtifactContractError(f"unknown command: {args.command}")
    except (ArtifactContractError, OSError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
