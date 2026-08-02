#!/usr/bin/env python3
"""Materialize and verify a trusted exact-commit release execution bundle."""

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
from pathlib import Path, PurePosixPath

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
PROVENANCE_NAME = "provenance.json"
BUNDLE_FILES = (
    "deploy.sh",
    "scripts/release_execution_bundle.py",
    "scripts/release_lock.py",
    "scripts/build_release_artifact.py",
    "scripts/deploy_static_release.py",
    "scripts/prepare_atomic_release_host.py",
    "scripts/environment_reconciliation.py",
    "scripts/p7b_rollout.py",
    "scripts/p7_telegram_pilot_controller.py",
    "scripts/current_vps_prelaunch_transition.py",
)
BUNDLE_SCHEMA = 3


class BundleError(RuntimeError):
    """Raised when trusted bundle provenance or filesystem safety fails."""


def _fail(message: str) -> None:
    raise BundleError(message)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _effective_uid() -> int | None:
    getter = getattr(os, "geteuid", None)
    return getter() if getter is not None else None


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        _fail("unsafe bundle path")
    return path


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=False
    )
    if result.returncode:
        _fail("exact workflow Git object is unavailable")
    return result.stdout


def _source_is_regular_file(repo: Path, workflow_sha: str, source: str) -> None:
    """Reject a missing, symlinked, or otherwise non-regular Git member."""

    listing = _git(repo, "ls-tree", "-z", workflow_sha, "--", source)
    records = listing.split(b"\0")
    if len(records) != 2 or not records[0] or records[1]:
        _fail("exact bundle member is missing or unsafe")
    try:
        metadata, tracked_path = records[0].split(b"\t", maxsplit=1)
        mode, kind, _object = metadata.split(maxsplit=2)
    except ValueError:
        _fail("exact bundle member is missing or unsafe")
    if tracked_path.decode("utf-8", "strict") != source or kind != b"blob":
        _fail("exact bundle member is missing or unsafe")
    expected_mode = b"100755" if source == "deploy.sh" else b"100644"
    if mode != expected_mode:
        _fail("exact bundle member has an unsafe executable contract")


def _lstat_regular(path: Path, *, mode: int | None = None) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise BundleError("bundle member is missing or unreadable") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        _fail("bundle member is not a regular non-symlink file")
    if mode is not None and os.name == "posix" and stat.S_IMODE(metadata.st_mode) != mode:
        _fail("bundle member mode is unsafe")
    return metadata


def _atomic_write(path: Path, content: bytes, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".bundle.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        if os.name == "posix":
            os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _lstat_regular(temporary, mode=mode)
        os.replace(temporary, path)
        if os.name == "posix":
            directory = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def _validate_root(path: Path, *, require_manifest: bool) -> dict[str, object] | None:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or (os.name == "posix" and stat.S_IMODE(metadata.st_mode) != 0o700)
    ):
        _fail("bundle root is unsafe")
    owner = _effective_uid()
    if owner is not None and metadata.st_uid != owner:
        _fail("bundle root owner mismatch")
    manifest_path = path / PROVENANCE_NAME
    if not require_manifest:
        return None
    _lstat_regular(manifest_path, mode=0o600)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError("bundle provenance is invalid") from exc
    if not isinstance(manifest, dict):
        _fail("bundle provenance is invalid")
    return manifest


def materialize(repo: Path, workflow_sha: str, parent: Path) -> Path:
    if SHA_PATTERN.fullmatch(workflow_sha) is None:
        _fail("workflow SHA is invalid")
    repo = repo.resolve(strict=True)
    parent = parent.resolve(strict=True)
    parent_meta = parent.lstat()
    owner = _effective_uid()
    if (
        parent.is_symlink()
        or not stat.S_ISDIR(parent_meta.st_mode)
        or (owner is not None and parent_meta.st_uid != owner)
    ):
        _fail("bundle parent is unsafe")
    _git(repo, "cat-file", "-e", f"{workflow_sha}^{{commit}}")
    bundle = Path(tempfile.mkdtemp(prefix="nura-release-bundle.", dir=parent))
    os.chmod(bundle, 0o700)
    try:
        _validate_root(bundle, require_manifest=False)
        members: list[dict[str, str | bool]] = []
        for source in BUNDLE_FILES:
            relative = _safe_relative(source)
            _source_is_regular_file(repo, workflow_sha, source)
            destination = bundle.joinpath(*relative.parts)
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            for ancestor in (destination.parent, *destination.parent.parents):
                if ancestor == bundle.parent:
                    break
                metadata = ancestor.lstat()
                if ancestor.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
                    _fail("bundle directory is unsafe")
            content = _git(repo, "show", f"{workflow_sha}:{source}")
            if not content:
                _fail("exact bundle member is empty")
            executable = source == "deploy.sh"
            _atomic_write(destination, content, 0o700 if executable else 0o600)
            members.append(
                {"path": source, "sha256": _sha256(content), "executable": executable}
            )
        provenance = {
            "schema": BUNDLE_SCHEMA,
            "workflow_sha": workflow_sha,
            "members": members,
        }
        _atomic_write(
            bundle / PROVENANCE_NAME,
            (json.dumps(provenance, sort_keys=True, separators=(",", ":")) + "\n").encode(),
            0o600,
        )
        verify(bundle, workflow_sha)
        return bundle
    except Exception:
        shutil.rmtree(bundle, ignore_errors=True)
        raise


def verify(bundle: Path, workflow_sha: str) -> None:
    if SHA_PATTERN.fullmatch(workflow_sha) is None:
        _fail("workflow SHA is invalid")
    bundle = bundle.absolute()
    manifest = _validate_root(bundle, require_manifest=True)
    assert manifest is not None
    if manifest.get("schema") != BUNDLE_SCHEMA or manifest.get("workflow_sha") != workflow_sha:
        _fail("bundle provenance mismatch")
    members = manifest.get("members")
    if not isinstance(members, list) or len(members) != len(BUNDLE_FILES):
        _fail("bundle member manifest is invalid")
    expected: dict[str, str] = {}
    for member in members:
        if not isinstance(member, dict):
            _fail("bundle member manifest is invalid")
        path = member.get("path")
        digest = member.get("sha256")
        executable = member.get("executable")
        if (
            not isinstance(path, str)
            or not isinstance(digest, str)
            or not isinstance(executable, bool)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            _fail("bundle member manifest is invalid")
        if path in expected:
            _fail("bundle member manifest is invalid")
        expected[path] = digest
        if executable != (path == "deploy.sh"):
            _fail("bundle member executable contract is invalid")
    if set(expected) != set(BUNDLE_FILES):
        _fail("bundle member manifest is incomplete")
    for source in BUNDLE_FILES:
        destination = bundle.joinpath(*_safe_relative(source).parts)
        _lstat_regular(destination, mode=0o700 if source == "deploy.sh" else 0o600)
        if _sha256(destination.read_bytes()) != expected[source]:
            _fail("bundle member checksum mismatch")


def cleanup(bundle: Path, workflow_sha: str) -> None:
    verify(bundle, workflow_sha)
    shutil.rmtree(bundle)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize_parser = subparsers.add_parser("materialize")
    materialize_parser.add_argument("--repo", type=Path, required=True)
    materialize_parser.add_argument("--workflow-sha", required=True)
    materialize_parser.add_argument("--parent", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--bundle", type=Path, required=True)
    verify_parser.add_argument("--workflow-sha", required=True)
    cleanup_parser = subparsers.add_parser("cleanup")
    cleanup_parser.add_argument("--bundle", type=Path, required=True)
    cleanup_parser.add_argument("--workflow-sha", required=True)
    args = parser.parse_args()
    try:
        if args.command == "materialize":
            print(materialize(args.repo, args.workflow_sha, args.parent))
        elif args.command == "verify":
            verify(args.bundle, args.workflow_sha)
        else:
            cleanup(args.bundle, args.workflow_sha)
    except BundleError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
