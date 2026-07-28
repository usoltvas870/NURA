from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import telegram_first_safe_suite as safe_suite  # noqa: E402
from telegram_first_safe_suite import (  # noqa: E402
    DESELECTED_NODE,
    EXCLUSIONS,
    OWNED_DOCKER_LABELS,
    build_manifest,
)


def test_safe_suite_manifest_covers_actual_inventory_exactly_once() -> None:
    manifest = build_manifest()

    assert manifest["excluded_files"] == list(EXCLUSIONS)
    assert manifest["deselected_node"] == DESELECTED_NODE
    assert manifest["shard_count"] == min(8, manifest["included_files"])
    assigned = [path for shard in manifest["shards"] for path in shard["files"]]
    included = [item["path"] for item in manifest["inventory"] if not item["excluded"]]
    assert sorted(assigned) == sorted(included)
    assert len(assigned) == len(set(assigned))
    assert all(path not in assigned for path in EXCLUSIONS)
    assert all(item["sha256"] for item in manifest["inventory"])
    assert manifest["manifest_sha256"]


def _completed(
    args: tuple[str, ...], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


def test_cleanup_gate_covers_every_harness_label() -> None:
    assert set(OWNED_DOCKER_LABELS) == {
        "nura.test=telegram-first-acceptance",
        "nura.test=telegram-first-standalone",
        "nura.test=telegram-first-failure-retry",
    }


def test_cleanup_gate_removes_only_discovered_owned_resources(monkeypatch) -> None:
    state = {"container": True, "volume": True}
    removals: list[tuple[str, ...]] = []

    def fake_run(*args: str, check: bool = True):
        command = tuple(args)
        if command[1:3] == ("ps", "-aq"):
            selected = command[-1].endswith("telegram-first-standalone")
            return _completed(command, stdout="owned-container\n" if selected and state["container"] else "")
        if command[1:4] == ("volume", "ls", "-q"):
            return _completed(command)
        if command[1:3] == ("inspect", "--format"):
            return _completed(command, stdout="owned-volume\n")
        if command[1:3] == ("rm", "--force"):
            assert command[-1] == "owned-container"
            removals.append(command)
            state["container"] = False
            state["volume"] = False
            return _completed(command)
        if command[1] == "inspect":
            if state["container"]:
                return _completed(command, stdout="{}")
            return _completed(command, 1, stderr="No such container")
        if command[1:3] == ("volume", "inspect"):
            if state["volume"]:
                return _completed(command, stdout="[]")
            return _completed(command, 1, stderr="No such volume")
        pytest.fail(f"unexpected docker command: {command}")

    monkeypatch.setattr(safe_suite, "_run", fake_run)

    cleanup = safe_suite._cleanup_check()

    assert cleanup["status"] == "PASS"
    assert cleanup["removed_containers"] == ["owned-container"]
    assert cleanup["removed_volumes"] == []
    assert removals == [
        ("docker", "rm", "--force", "--volumes", "owned-container")
    ]
    assert all("foreign" not in part for command in removals for part in command)


def test_cleanup_gate_fails_closed_when_owned_container_remains(monkeypatch) -> None:
    def fake_run(*args: str, check: bool = True):
        command = tuple(args)
        if command[1:3] == ("ps", "-aq"):
            selected = command[-1].endswith("telegram-first-standalone")
            return _completed(command, stdout="stuck-container\n" if selected else "")
        if command[1:4] == ("volume", "ls", "-q"):
            return _completed(command)
        if command[1:3] == ("inspect", "--format"):
            return _completed(command)
        if command[1:3] == ("rm", "--force"):
            return _completed(command, 1, stderr="remove failed")
        if command[1] == "inspect":
            return _completed(command, stdout="{}")
        pytest.fail(f"unexpected docker command: {command}")

    monkeypatch.setattr(safe_suite, "_run", fake_run)

    cleanup = safe_suite._cleanup_check()

    assert cleanup["status"] == "FAIL"
    assert "container_remove_failed:stuck-container" in cleanup["errors"]
    assert "container_remaining:stuck-container" in cleanup["errors"]
    assert cleanup["labelled_containers"] == ["stuck-container"]


def test_cleanup_gate_never_deletes_unlabelled_named_volume(monkeypatch) -> None:
    state = {"container": True}
    removals: list[tuple[str, ...]] = []

    def fake_run(*args: str, check: bool = True):
        command = tuple(args)
        if command[1:3] == ("ps", "-aq"):
            selected = command[-1].endswith("telegram-first-standalone")
            return _completed(command, stdout="owned-container\n" if selected and state["container"] else "")
        if command[1:4] == ("volume", "ls", "-q"):
            return _completed(command)
        if command[1:3] == ("inspect", "--format"):
            return _completed(command, stdout="foreign-named-volume\n")
        if command[1:3] == ("rm", "--force"):
            removals.append(command)
            state["container"] = False
            return _completed(command)
        if command[1] == "inspect":
            if state["container"]:
                return _completed(command, stdout="{}")
            return _completed(command, 1, stderr="No such container")
        if command[1:3] == ("volume", "inspect"):
            return _completed(command, stdout="[]")
        if command[1:3] == ("volume", "rm"):
            pytest.fail("unlabelled named volume must never be removed")
        pytest.fail(f"unexpected docker command: {command}")

    monkeypatch.setattr(safe_suite, "_run", fake_run)

    cleanup = safe_suite._cleanup_check()

    assert cleanup["status"] == "FAIL"
    assert "mounted_volume_remaining:foreign-named-volume" in cleanup["errors"]
    assert removals == [
        ("docker", "rm", "--force", "--volumes", "owned-container")
    ]
