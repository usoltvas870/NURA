#!/usr/bin/env python3
"""Deterministic, file-sharded local pytest safe-suite for Telegram-first V1.

Artifacts are written under the operating system temporary directory, never into
the repository.  This runner deliberately accepts no dynamic exclusions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXCLUSIONS = (
    "tests/test_dialog_helper.py",
    "tests/test_e2e_harness.py",
    "tests/test_ios_install_dialogs_e2e.py",
    "tests/test_profile_dialogs_e2e.py",
    "tests/test_profile_telegram_link_e2e.py",
    "tests/test_pwa_personas_e2e.py",
    "tests/test_tarot_dialogs_e2e.py",
    "tests/test_admin_bot_deploy_contract.py",
    "tests/test_atomic_release_contract.py",
    "tests/test_build_pwa_release.py",
    "tests/test_deploy_release_contract.py",
    "tests/test_p7b_rollout_contract.py",
    "tests/test_backup_restore_proof_contract.py",
    "tests/test_backup_restore_proof_postgres.py",
)
DESELECTED_NODE = (
    "tests/test_tarot_asset_delivery.py::"
    "test_tarot_asset_builder_verifies_checked_in_derivatives"
)
PROCESS_ISOLATED_FILES = (
    "tests/test_telegram_first_service_boot.py",
    "tests/test_telegram_first_postgres_golden_path.py",
)
SCHEMA_VERSION = 1
OWNED_DOCKER_LABELS = (
    "nura.test=telegram-first-acceptance",
    "nura.test=telegram-first-standalone",
    "nura.test=telegram-first-failure-retry",
)


@dataclass(frozen=True)
class InventoryEntry:
    path: str
    tracked: bool
    excluded: bool
    sha256: str


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False,
    )
    if check and completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"command_failed:{' '.join(args)}:{detail[-1000:]}")
    return completed


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tracked_paths() -> set[str]:
    return set(_run("git", "ls-files", "--", "tests").stdout.splitlines())


def build_inventory() -> tuple[InventoryEntry, ...]:
    """Return the actual filesystem inventory, rejecting ambiguous paths."""
    tracked = _tracked_paths()
    paths = sorted(ROOT.glob("tests/**/test_*.py"), key=lambda item: item.as_posix().casefold())
    normalized: list[str] = []
    entries: list[InventoryEntry] = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"unsafe_test_path:{path}")
        relative = _relative(path)
        if ".." in Path(relative).parts:
            raise RuntimeError(f"path_traversal:{relative}")
        normalized.append(relative)
        entries.append(InventoryEntry(
            path=relative, tracked=relative in tracked,
            excluded=relative in EXCLUSIONS, sha256=_sha256_file(path),
        ))
    if len(normalized) != len(set(normalized)):
        raise RuntimeError("duplicate_normalized_test_path")
    folded = [path.casefold() for path in normalized]
    if len(folded) != len(set(folded)):
        raise RuntimeError("case_collision_test_path")
    expected = set(EXCLUSIONS)
    found = set(normalized)
    missing = sorted(expected - found)
    if missing:
        raise RuntimeError(f"missing_expected_exclusions:{','.join(missing)}")
    extra = sorted(entry.path for entry in entries if entry.excluded and entry.path not in expected)
    if extra:
        raise RuntimeError(f"extra_exclusions:{','.join(extra)}")
    if not entries:
        raise RuntimeError("empty_test_inventory")
    return tuple(entries)


def _node_exists() -> bool:
    path, node = DESELECTED_NODE.split("::", 1)
    source = (ROOT / path).read_text(encoding="utf-8")
    return f"def {node}(" in source or f"async def {node}(" in source


def _git_head() -> str:
    return _run("git", "rev-parse", "HEAD").stdout.strip()


def _alembic_head() -> str:
    output = _run(sys.executable, "-m", "alembic", "heads").stdout.strip()
    return output.split()[0] if output else ""


def _working_tree_snapshot() -> dict[str, Any]:
    status = _run("git", "status", "--short").stdout
    diff = _run("git", "diff", "--binary", "HEAD").stdout.encode("utf-8")
    modified = _run("git", "diff", "--name-only", "HEAD").stdout.splitlines()
    untracked = _run("git", "ls-files", "--others", "--exclude-standard").stdout.splitlines()
    hashes = {
        path: _sha256_file(ROOT / path)
        for path in sorted(set(modified + untracked))
        if (ROOT / path).is_file()
    }
    return {
        "status": status,
        "diff_sha256": hashlib.sha256(diff).hexdigest(),
        "untracked": sorted(untracked),
        "file_sha256": hashes,
    }


def _manifest_payload(inventory: tuple[InventoryEntry, ...]) -> dict[str, Any]:
    included = [entry for entry in inventory if not entry.excluded]
    shard_count = min(8, len(included))
    shards: list[list[InventoryEntry]] = [[] for _ in range(shard_count)]
    isolated = [entry for entry in included if entry.path in PROCESS_ISOLATED_FILES]
    regular = [entry for entry in included if entry.path not in PROCESS_ISOLATED_FILES]
    if len(isolated) >= shard_count:
        raise RuntimeError("process_isolation_requires_regular_shard")
    regular_shard_count = shard_count - len(isolated)
    for index, entry in enumerate(sorted(regular, key=lambda item: item.path.casefold())):
        shards[index % regular_shard_count].append(entry)
    for offset, entry in enumerate(sorted(isolated, key=lambda item: item.path.casefold())):
        shards[regular_shard_count + offset].append(entry)
    assignments = {entry.path: index + 1 for index, shard in enumerate(shards) for entry in shard}
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": uuid.uuid4().hex,
        "branch": _run("git", "branch", "--show-current").stdout.strip(),
        "head": _git_head(),
        "alembic_head": _alembic_head(),
        "inventory_timestamp": datetime.now(UTC).isoformat(),
        "working_tree_fingerprint": _working_tree_snapshot(),
        "total_files": len(inventory),
        "tracked_files": sum(entry.tracked for entry in inventory),
        "untracked_files": sum(not entry.tracked for entry in inventory),
        "included_files": len(included),
        "excluded_files": list(EXCLUSIONS),
        "deselected_node": DESELECTED_NODE,
        "shard_count": shard_count,
        "inventory": [
            {"path": entry.path, "tracked": entry.tracked, "excluded": entry.excluded,
             "shard": assignments.get(entry.path), "sha256": entry.sha256}
            for entry in inventory
        ],
        "shards": [
            {"number": number, "files": [entry.path for entry in shard]}
            for number, shard in enumerate(shards, start=1)
        ],
    }


def _with_hash(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["manifest_sha256"] = hashlib.sha256(encoded).hexdigest()
    return payload


def build_manifest() -> dict[str, Any]:
    if not _node_exists():
        raise RuntimeError(f"deselected_node_missing:{DESELECTED_NODE}")
    return _with_hash(_manifest_payload(build_inventory()))


def _pytest_command(files: list[str], collect_only: bool) -> list[str]:
    command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *files]
    if "tests/test_tarot_asset_delivery.py" in files:
        command.append(f"--deselect={DESELECTED_NODE}")
    if collect_only:
        command.extend(("--collect-only", "-q"))
    else:
        command.append("-q")
    return command


def _pytest_counts(output: str) -> dict[str, int]:
    counts = {key: 0 for key in ("passed", "failed", "skipped", "xfailed", "xpassed", "warnings", "deselected")}
    for key in counts:
        import re
        match = re.search(rf"(\d+) {key}", output)
        if match:
            counts[key] = int(match.group(1))
    return counts


def _collected_count(output: str) -> int:
    import re

    match = re.search(r"(\d+) tests? collected", output)
    return int(match.group(1)) if match else 0


def _confirmed_absent(
    completed: subprocess.CompletedProcess[str], kind: str
) -> bool:
    if completed.returncode == 0:
        return False
    detail = f"{completed.stdout}\n{completed.stderr}".casefold()
    markers = {
        "container": ("no such object", "no such container"),
        "volume": ("no such volume",),
    }
    return any(marker in detail for marker in markers[kind])


def _docker_inventory() -> dict[str, Any]:
    containers: set[str] = set()
    labelled_volumes: set[str] = set()
    mounted_volumes: set[str] = set()
    errors: list[str] = []
    for label in OWNED_DOCKER_LABELS:
        container_result = _run(
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label={label}",
            check=False,
        )
        volume_result = _run(
            "docker",
            "volume",
            "ls",
            "-q",
            "--filter",
            f"label={label}",
            check=False,
        )
        if container_result.returncode:
            errors.append(f"container_query_failed:{label}")
        else:
            containers.update(container_result.stdout.split())
        if volume_result.returncode:
            errors.append(f"volume_query_failed:{label}")
        else:
            labelled_volumes.update(volume_result.stdout.split())
    for container in tuple(containers):
        mounted = _run(
            "docker",
            "inspect",
            "--format",
            '{{range .Mounts}}{{if eq .Type "volume"}}{{println .Name}}{{end}}{{end}}',
            container,
            check=False,
        )
        if mounted.returncode:
            errors.append(f"container_volume_query_failed:{container}")
        else:
            mounted_volumes.update(mounted.stdout.split())
    return {
        "containers": sorted(containers),
        "labelled_volumes": sorted(labelled_volumes),
        "mounted_volumes": sorted(mounted_volumes),
        "errors": errors,
    }


def _cleanup_check() -> dict[str, Any]:
    try:
        before = _docker_inventory()
    except FileNotFoundError:
        return {
            "status": "FAIL",
            "labelled_containers": [],
            "labelled_volumes": [],
            "docker_available": False,
            "errors": ["docker_not_found"],
        }

    errors = list(before["errors"])
    owned_containers = tuple(before["containers"])
    owned_volumes = set(before["labelled_volumes"])
    mounted_volumes = set(before["mounted_volumes"])
    for container in owned_containers:
        removed = _run(
            "docker", "rm", "--force", "--volumes", container, check=False
        )
        inspected = _run("docker", "inspect", container, check=False)
        if removed.returncode and not _confirmed_absent(inspected, "container"):
            errors.append(f"container_remove_failed:{container}")
        if not _confirmed_absent(inspected, "container"):
            errors.append(f"container_remaining:{container}")

    for volume in sorted(owned_volumes):
        inspected = _run("docker", "volume", "inspect", volume, check=False)
        if _confirmed_absent(inspected, "volume"):
            continue
        removed = _run("docker", "volume", "rm", "--force", volume, check=False)
        inspected = _run("docker", "volume", "inspect", volume, check=False)
        if removed.returncode and not _confirmed_absent(inspected, "volume"):
            errors.append(f"volume_remove_failed:{volume}")
        if not _confirmed_absent(inspected, "volume"):
            errors.append(f"volume_remaining:{volume}")

    for volume in sorted(mounted_volumes - owned_volumes):
        inspected = _run("docker", "volume", "inspect", volume, check=False)
        if not _confirmed_absent(inspected, "volume"):
            errors.append(f"mounted_volume_remaining:{volume}")

    after = _docker_inventory()
    errors.extend(after["errors"])
    labelled_containers = after["containers"]
    labelled_volumes = after["labelled_volumes"]
    if labelled_containers:
        errors.append("labelled_containers_remaining")
    if labelled_volumes:
        errors.append("labelled_volumes_remaining")
    return {
        "status": "PASS" if not errors else "FAIL",
        "labelled_containers": labelled_containers,
        "labelled_volumes": labelled_volumes,
        "docker_available": True,
        "owned_labels": list(OWNED_DOCKER_LABELS),
        "removed_containers": list(owned_containers),
        "removed_volumes": sorted(owned_volumes),
        "errors": errors,
    }


def run_safe_suite() -> tuple[int, dict[str, Any]]:
    manifest = build_manifest()
    output_dir = Path(tempfile.mkdtemp(prefix="nura-telegram-first-safe-suite-"))
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    persisted_manifest_sha256 = _sha256_file(manifest_path)
    pre = _working_tree_snapshot()
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    env = os.environ.copy()
    env["APP_ENV"] = "test"
    env["NURA_DISABLE_DOTENV"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for shard in manifest["shards"]:
        files = shard["files"]
        collect_command = _pytest_command(files, collect_only=True)
        started = time.monotonic()
        collected = subprocess.run(collect_command, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, env=env)
        execution_command = _pytest_command(files, collect_only=False)
        executed = subprocess.run(execution_command, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, env=env) if collected.returncode == 0 else None
        log_path = output_dir / f"shard-{shard['number']}.log"
        log_path.write_text(
            "COLLECT\n" + collected.stdout + collected.stderr + "\nEXECUTE\n" + ("" if executed is None else executed.stdout + executed.stderr),
            encoding="utf-8",
        )
        execution_output = "" if executed is None else executed.stdout + executed.stderr
        cleanup = _cleanup_check()
        result = {
            "number": shard["number"], "files": files, "collect_command": collect_command,
            "collection_exit_code": collected.returncode,
            "collected_tests": _collected_count(collected.stdout + collected.stderr),
            "execution_command": execution_command, "execution_exit_code": None if executed is None else executed.returncode,
            "duration_seconds": round(time.monotonic() - started, 3), "log_path": str(log_path),
            "cleanup": cleanup, **_pytest_counts(execution_output),
        }
        results.append(result)
        if collected.returncode or executed is None or executed.returncode:
            failures.append(f"shard_{shard['number']}")
        if cleanup["status"] != "PASS":
            failures.append(f"cleanup_shard_{shard['number']}")
            break
    post = _working_tree_snapshot()
    immutable = pre == post and persisted_manifest_sha256 == _sha256_file(manifest_path)
    if not immutable:
        failures.append("working_tree_or_manifest_changed")
    assigned = [path for shard in manifest["shards"] for path in shard["files"]]
    included = [entry["path"] for entry in manifest["inventory"] if not entry["excluded"]]
    missing = sorted(set(included) - set(assigned))
    duplicates = sorted(path for path, count in Counter(assigned).items() if count != 1)
    if missing or duplicates:
        failures.append("assignment_integrity")
    summary = {
        "status": "PASS" if not failures else "PARTIAL", "manifest_path": str(manifest_path),
        "manifest_sha256": manifest["manifest_sha256"], "output_directory": str(output_dir),
        "results": results, "failures": failures, "missing_files": missing, "duplicate_files": duplicates,
        "pre_snapshot": pre, "post_snapshot": post, "immutability": immutable,
        "aggregate": {key: sum(item.get(key, 0) for item in results) for key in ("passed", "failed", "skipped", "xfailed", "xpassed", "warnings", "deselected")},
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return (0 if not failures else 1), summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory-only", action="store_true")
    args = parser.parse_args()
    if args.inventory_only:
        manifest = build_manifest()
        print(json.dumps({key: manifest[key] for key in ("total_files", "tracked_files", "untracked_files", "included_files", "excluded_files", "shard_count", "manifest_sha256")}, sort_keys=True))
        return 0
    exit_code, summary = run_safe_suite()
    print(json.dumps({"status": summary["status"], "summary": str(Path(summary["output_directory"]) / "summary.json")}, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
