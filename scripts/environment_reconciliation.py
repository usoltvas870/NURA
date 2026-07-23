#!/usr/bin/env python3
"""Fail-closed, secret-free environment reconciliation for protected rollback."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")


def fail(message: str) -> None:
    raise SystemExit(f"environment_reconcile:{message}")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_file(path: Path, *, mode: int | None = None) -> os.stat_result:
    try:
        meta = path.lstat()
    except OSError:
        fail("missing_file")
    if path.is_symlink() or not stat.S_ISREG(meta.st_mode):
        fail("unsafe_file")
    if mode is not None and os.name == "posix" and stat.S_IMODE(meta.st_mode) != mode:
        fail("unsafe_mode")
    return meta


def atomic(path: Path, data: bytes, mode: int, owner: os.stat_result) -> None:
    fd, temp = tempfile.mkstemp(prefix=".environment.", dir=path.parent)
    temporary = Path(temp)
    try:
        if os.name == "posix":
            os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            os.chown(temporary, owner.st_uid, owner.st_gid)
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


def contract(data: bytes) -> dict[str, str]:
    values = {}
    for line in data.splitlines():
        key, sep, value = line.partition(b"=")
        if sep and key in {b"APP_ENV", b"TEST_MODE"}:
            text = key.decode()
            if text in values:
                fail("duplicate_contract_key")
            values[text] = value.decode("ascii", "strict")
    return values


def envelope(path: Path) -> dict:
    safe_file(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        payload = doc["payload"]
    except Exception:
        fail("invalid_p7b_provenance")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if (
        doc.get("schema") != 1
        or not isinstance(payload, dict)
        or doc.get("digest") != digest(canonical)
    ):
        fail("invalid_p7b_provenance")
    return payload


def load_record(record: Path, root: Path, target: str) -> dict:
    safe_file(record, mode=0o600)
    try:
        doc = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        fail("invalid_reconcile_record")
    expected = {"APP_ENV": "development", "TEST_MODE": "true"}
    if (
        doc.get("schema") != 1
        or doc.get("target_sha") != target
        or doc.get("phase") not in {"environment_reconcile_intent", "environment_reconcile_verified"}
        or doc.get("environment_contract") != expected
    ):
        fail("invalid_reconcile_record")
    for key, suffix in (("baseline_backup_path", ".baseline.backup"), ("pre_reconcile_backup_path", ".pre-reconcile.backup")):
        path = Path(str(doc.get(key, "")))
        if path.parent != root or path.name != target + suffix:
            fail("reconcile_backup_path_mismatch")
        data = path.read_bytes() if safe_file(path, mode=0o600) else b""
        if doc.get(key.replace("_path", "_sha256")) != digest(data):
            fail("reconcile_backup_digest_mismatch")
    return doc


def source_for(p7b: Path, target: str) -> tuple[str, Path]:
    candidates = []
    for baseline in (p7b / "baselines").glob("*.json"):
        payload = envelope(baseline)
        release = payload.get("target_sha")
        if (
            payload.get("previous_sha") != target
            or not isinstance(release, str)
            or not SHA.fullmatch(release)
        ):
            continue
        transaction = envelope(p7b / "transactions" / (release + ".json"))
        backup = p7b / "environment" / (release + ".backup")
        if transaction.get("phase") == "complete" and backup.exists():
            candidates.append((release, backup))
    if len(candidates) != 1:
        fail("baseline_backup_provenance_missing")
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("reconcile", "verify", "restore"))
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--p7b-root", type=Path, required=True)
    args = parser.parse_args()
    if not SHA.fullmatch(args.target_sha):
        fail("invalid_target_sha")
    env = args.environment
    env_meta = safe_file(env)
    root = args.state_root / "environment-reconcile"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (
        root.is_symlink()
        or not root.is_dir()
        or (os.name == "posix" and stat.S_IMODE(root.stat().st_mode) != 0o700)
    ):
        fail("unsafe_state_directory")
    record = root / (args.target_sha + ".json")
    if args.command == "reconcile":
        if record.exists():
            doc = load_record(record, root, args.target_sha)
            baseline = Path(str(doc["baseline_backup_path"])).read_bytes()
            current = env.read_bytes()
            if digest(current) not in {
                doc["pre_reconcile_backup_sha256"],
                doc["baseline_backup_sha256"],
            }:
                fail("reconcile_resume_environment_mismatch")
            if digest(current) == doc["pre_reconcile_backup_sha256"]:
                atomic(env, baseline, stat.S_IMODE(env_meta.st_mode), env_meta)
            if contract(env.read_bytes()) != doc["environment_contract"]:
                fail("reconcile_resume_verification_failed")
            return 0
        release, legacy = source_for(args.p7b_root, args.target_sha)
        safe_file(legacy)
        baseline = legacy.read_bytes()
        expected = {"APP_ENV": "development", "TEST_MODE": "true"}
        if contract(baseline) != expected:
            fail("baseline_environment_contract_mismatch")
        pre = env.read_bytes()
        backup = root / (args.target_sha + ".pre-reconcile.backup")
        protected = root / (args.target_sha + ".baseline.backup")
        atomic(backup, pre, 0o600, env_meta)
        atomic(protected, baseline, 0o600, env_meta)
        doc = {
            "schema": 1,
            "phase": "environment_reconcile_intent",
            "target_sha": args.target_sha,
            "source_release_sha": release,
            "baseline_backup_path": str(protected),
            "baseline_backup_sha256": digest(baseline),
            "pre_reconcile_backup_path": str(backup),
            "pre_reconcile_backup_sha256": digest(pre),
            "environment_contract": expected,
            "created_at": int(time.time()),
        }
        atomic(
            record,
            (json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n").encode(),
            0o600,
            env_meta,
        )
        atomic(env, baseline, stat.S_IMODE(env_meta.st_mode), env_meta)
        if contract(env.read_bytes()) != expected:
            fail("environment_restore_verification_failed")
    else:
        doc = load_record(record, root, args.target_sha)
        expected = doc.get("environment_contract")
        if not isinstance(expected, dict):
            fail("invalid_reconcile_record")
        if args.command == "restore":
            pre = Path(str(doc.get("pre_reconcile_backup_path", "")))
            safe_file(pre, mode=0o600)
            atomic(env, pre.read_bytes(), stat.S_IMODE(env_meta.st_mode), env_meta)
            doc["phase"] = "environment_reconcile_rolled_back"
        else:
            if contract(env.read_bytes()) != expected:
                fail("environment_contract_mismatch")
            doc["phase"] = "environment_reconcile_verified"
        atomic(
            record,
            (json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n").encode(),
            0o600,
            env_meta,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
