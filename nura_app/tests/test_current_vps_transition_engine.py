"""Manifest-only preconditions, ordering, and honest compensation boundaries."""

import importlib.util
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "current_vps_prelaunch_transition.py"
SPEC = importlib.util.spec_from_file_location("current_vps_transition", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
transition = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = transition
SPEC.loader.exec_module(transition)


def authorization() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "schema_version": transition.AUTHORIZATION_SCHEMA,
        "authorization_base_commit_sha": "a" * 40,
        "authorization_manifest_path": "docs/operations/authorizations/current-vps-prelaunch-example.json",
        "source_application_sha": transition.SOURCE_APPLICATION_SHA,
        "target_application_sha": "a" * 40,
        "engine_commit_sha": "a" * 40,
        "engine_file_sha256": transition.hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        "current_db_revision": transition.CURRENT_REVISION,
        "target_db_revision": transition.TARGET_REVISION,
        "ordered_migration_revisions": [item.revision for item in transition.EXPECTED_MIGRATIONS],
        "migration_chain_digest": transition.MIGRATION_CHAIN_DIGEST,
        "required_secret_profile_version": transition.SECRET_PROFILE_VERSION,
        "backup_evidence_schema": 1,
        "capacity_acknowledgement": {
            "allowed_modes": ["available_ram", "precreated_swap"],
            "minimum_available_ram_bytes": transition.MIN_AVAILABLE_RAM_BYTES,
            "minimum_active_swap_bytes": transition.MIN_ACTIVE_SWAP_BYTES,
        },
        "backward_compatible_schema_acknowledgement": True,
        "database_downgrade_acknowledgement": "not-supported",
        "owner_approval_identifiers": ["approval-owner-20260731"],
        "valid_from": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=55)).isoformat().replace("+00:00", "Z"),
        "target_artifact_sha256": "d" * 64,
        "target_manifest_sha256": "e" * 64,
    }
    payload["checksum"] = transition.payload_checksum(payload)
    return payload


class FakeAdapter:
    def __init__(self, fail_at: str | None = None) -> None:
        self.calls: list[str] = []
        self.fail_at = fail_at

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_at == name:
            raise RuntimeError(name)

    def build_migration_candidate(self, _target: str) -> None: self._call("build")
    def revalidate_backup_evidence(self) -> None: self._call("backup_revalidate")
    def stop_writers(self) -> None: self._call("stop")
    def apply_migrations(self, _target: str) -> None: self._call("migrate")
    def activate_target_with_polling_disabled(self, _target: str) -> None: self._call("activate_without_polling")
    def verify_target_without_polling(self, _target: str) -> None: self._call("verify_without_polling")
    def verify_owner_only_without_polling(self, _target: str) -> None: self._call("owner_safe_without_polling")
    def activate_bot_polling(self) -> None: self._call("bot_polling")
    def verify_bot_polling(self, _target: str) -> None: self._call("polling_smoke")
    def compensate_application_only(self, _source: str) -> None: self._call("app_compensate")
    def verify_source_fleet_at_target_schema(self, _source: str) -> None: self._call("source_at_target_schema")
    def record(self, phase: str, _payload: object) -> None: self.calls.append(f"record:{phase}")


def good_preconditions(**overrides: object):
    values = {
        "current_application_sha": transition.SOURCE_APPLICATION_SHA,
        "current_db_revision": transition.CURRENT_REVISION,
        "current_release_successful": True,
        "staged_transaction_present": False,
        "duplicate_fleet_present": False,
        "source_fleet_identity_verified": True,
        "preflight_result": "READY_FOR_HOST_BACKUP_AND_RECOVERY",
        "artifact_sha256": "d" * 64,
        "manifest_sha256": "e" * 64,
        "capacity": transition.CapacitySnapshot(transition.MIN_AVAILABLE_RAM_BYTES, 0, transition.MIN_DISK_FREE_BYTES, transition.MIN_FREE_INODES),
    }
    values.update(overrides)
    return transition.Preconditions(**values)


def test_authorization_manifest_is_canonical_and_checksum_bound(tmp_path: Path) -> None:
    value = authorization()
    path = tmp_path / "authorization.json"
    path.write_bytes(transition.canonical_json(value))
    assert transition.validate_authorization_manifest(path, verify_git=False)["target_application_sha"] == "a" * 40
    value["target_application_sha"] = "f" * 40
    path.write_bytes(transition.canonical_json(value))
    with pytest.raises(transition.TransitionError, match="checksum_mismatch"):
        transition.validate_authorization_manifest(path, verify_git=False)


def test_authorization_manifest_preserves_tracked_blob_bytes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "clone", "--quiet", "--no-checkout", str(SCRIPT.parents[1]), str(repo)],
        check=True,
    )

    def git(*arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    git("checkout", "-B", "main", transition.SOURCE_APPLICATION_SHA)
    git("config", "user.name", "NURA Test")
    git("config", "user.email", "nura-test@example.invalid")
    engine = repo / "scripts" / "current_vps_prelaunch_transition.py"
    engine.parent.mkdir(exist_ok=True)
    engine.write_bytes(SCRIPT.read_bytes())
    git("add", "scripts/current_vps_prelaunch_transition.py")
    git("commit", "-m", "target")
    target = git("rev-parse", "HEAD")

    value = authorization()
    value["authorization_base_commit_sha"] = target
    value["target_application_sha"] = target
    value["engine_commit_sha"] = target
    value["checksum"] = transition.payload_checksum(
        {key: item for key, item in value.items() if key != "checksum"}
    )
    relative = str(value["authorization_manifest_path"])
    manifest = repo / relative
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(transition.canonical_json(value))
    git("add", relative)
    git("commit", "-m", "authorize target")
    git("update-ref", "refs/remotes/origin/main", git("rev-parse", "HEAD"))

    validated = transition.validate_authorization_manifest(
        manifest,
        repo=repo,
        engine_path=SCRIPT,
        verify_git=True,
    )
    assert validated["target_application_sha"] == target
    with pytest.raises(transition.TransitionError, match="authorization_git_identity_invalid"):
        transition.validate_execution_checkout(repo, validated)
    git("checkout", "-B", "main", transition.SOURCE_APPLICATION_SHA)
    transition.validate_execution_checkout(repo, validated)

    git("checkout", "--detach", git("rev-parse", "refs/remotes/origin/main"))
    manifest.write_bytes(transition.canonical_json(value))
    extra = repo / "unexpected.txt"
    extra.write_text("unexpected", encoding="utf-8")
    git("add", "unexpected.txt")
    git("commit", "--amend", "--no-edit")
    git("update-ref", "refs/remotes/origin/main", git("rev-parse", "HEAD"))
    with pytest.raises(transition.TransitionError, match="authorization_commit_scope_invalid"):
        transition.validate_authorization_manifest(
            manifest,
            repo=repo,
            engine_path=SCRIPT,
            verify_git=True,
        )


@pytest.mark.parametrize(
    ("override", "error"),
    [
        ({"current_application_sha": "f" * 40}, "current_application_mismatch"),
        ({"current_db_revision": "wrong"}, "current_database_revision_mismatch"),
        ({"staged_transaction_present": True}, "stale_transaction_not_recovered"),
        ({"duplicate_fleet_present": True}, "duplicate_fleet_detected"),
        ({"source_fleet_identity_verified": False}, "source_fleet_identity_mismatch"),
        ({"preflight_result": "BLOCKED"}, "offline_preflight_failed"),
        ({"artifact_sha256": "0" * 64}, "target_artifact_identity_mismatch"),
        ({"capacity": transition.CapacitySnapshot(1, 0, transition.MIN_DISK_FREE_BYTES, transition.MIN_FREE_INODES)}, "capacity_memory_insufficient"),
    ],
)
def test_every_failed_gate_prevents_all_mutations(override: dict[str, object], error: str) -> None:
    adapter = FakeAdapter()
    with pytest.raises(transition.TransitionError, match=error):
        transition.TransitionEngine(adapter).execute(
            authorization=authorization(),
            preconditions=good_preconditions(**override),
            backup_evidence={"schema_version": 1},
            recovery_evidence={"status": "canonical_recovery_verified"},
        )
    assert adapter.calls == []


def test_success_order_keeps_bot_last_and_never_cleans_up() -> None:
    adapter = FakeAdapter()
    transition.TransitionEngine(adapter).execute(
        authorization=authorization(),
        preconditions=good_preconditions(),
        backup_evidence={"schema_version": 1},
        recovery_evidence={"status": "canonical_recovery_verified"},
    )
    assert adapter.calls == [
        "record:all_preconditions_passed",
        "build",
        "backup_revalidate",
        "stop",
        "migrate",
        "activate_without_polling",
        "verify_without_polling",
        "owner_safe_without_polling",
        "bot_polling",
        "polling_smoke",
        "record:transition_succeeded",
    ]
    assert "cleanup" not in adapter.calls


def test_execution_entrypoint_reuses_the_common_release_lock() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "NURA_COMMON_LOCK_FD" in source
    assert "/run/lock/nura-deploy.lock" in source
    assert "release_lock.py" in source
    assert "pass_fds=inherited_fds" in source


def test_backup_is_revalidated_after_build_and_before_writer_stop() -> None:
    adapter = FakeAdapter("backup_revalidate")
    with pytest.raises(RuntimeError, match="backup_revalidate"):
        transition.TransitionEngine(adapter).execute(
            authorization=authorization(),
            preconditions=good_preconditions(),
            backup_evidence={"schema_version": 1},
            recovery_evidence={"status": "canonical_recovery_verified"},
        )
    assert adapter.calls == [
        "record:all_preconditions_passed",
        "build",
        "backup_revalidate",
    ]


def test_migration_failure_never_downgrades_or_activates() -> None:
    adapter = FakeAdapter("migrate")
    with pytest.raises(RuntimeError, match="migrate"):
        transition.TransitionEngine(adapter).execute(
            authorization=authorization(),
            preconditions=good_preconditions(),
            backup_evidence={"schema_version": 1},
            recovery_evidence={"status": "canonical_recovery_verified"},
        )
    assert adapter.calls == [
        "record:all_preconditions_passed",
        "build",
        "backup_revalidate",
        "stop",
        "migrate",
        "record:migration_failed",
    ]


def test_post_migration_activation_failure_rolls_back_only_application() -> None:
    adapter = FakeAdapter("verify_without_polling")
    with pytest.raises(RuntimeError, match="verify_without_polling"):
        transition.TransitionEngine(adapter).execute(
            authorization=authorization(),
            preconditions=good_preconditions(),
            backup_evidence={"schema_version": 1},
            recovery_evidence={"status": "canonical_recovery_verified"},
        )
    assert "app_compensate" in adapter.calls
    assert "source_at_target_schema" in adapter.calls
    assert "bot_polling" not in adapter.calls
    assert adapter.calls[-1] == "record:application_rollback_verified"


def test_backup_evidence_rehashes_each_real_artifact(tmp_path: Path) -> None:
    backup_root = tmp_path.resolve()
    artifacts: dict[str, object] = {}
    for name in ("postgresql", "redis", "configuration", "release_state"):
        path = backup_root / f"{name}.backup"
        path.write_bytes(f"verified-{name}".encode())
        if os.name != "nt":
            path.chmod(0o600)
        artifacts[name] = {
            "path": str(path),
            "sha256": transition.hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
            "verified": True,
        }
    payload: dict[str, object] = {
        "schema_version": transition.BACKUP_EVIDENCE_SCHEMA,
        "source_application_sha": transition.SOURCE_APPLICATION_SHA,
        "current_db_revision": transition.CURRENT_REVISION,
        "artifacts": artifacts,
    }
    payload["checksum"] = transition.payload_checksum(payload)
    evidence = backup_root / "backup-evidence.json"
    evidence.write_bytes(transition.canonical_json(payload))

    transition.validate_evidence(
        evidence,
        kind="backup",
        schema=transition.BACKUP_EVIDENCE_SCHEMA,
        manifest=authorization(),
        backup_root=backup_root,
    )
    (backup_root / "redis.backup").write_bytes(b"tampered")
    with pytest.raises(transition.TransitionError, match="artifact_mismatch"):
        transition.validate_evidence(
            evidence,
            kind="backup",
            schema=transition.BACKUP_EVIDENCE_SCHEMA,
            manifest=authorization(),
            backup_root=backup_root,
        )


def test_concrete_activation_and_compensation_use_exact_target_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    evidence = tmp_path / "evidence"
    bundle = evidence / "nura-release-bundle.fixture"
    for directory in (target / "nura_app", evidence, bundle):
        directory.mkdir(parents=True, exist_ok=True)
    for name in ("authorization.json", "archive.tar.gz", "archive.sha256", "manifest.json"):
        (tmp_path / name).write_text("fixture", encoding="utf-8")
    (bundle / "deploy.sh").write_text("fixture", encoding="utf-8")
    adapter = transition.HostMutationAdapter(
        target_source=target,
        authorization_manifest=tmp_path / "authorization.json",
        archive=tmp_path / "archive.tar.gz",
        checksum=tmp_path / "archive.sha256",
        public_manifest=tmp_path / "manifest.json",
        evidence_directory=evidence,
        backup_evidence=tmp_path / "authorization.json",
        backup_root=tmp_path,
        authorization=authorization(),
    )
    adapter.execution_bundle = bundle
    calls: list[tuple[list[str], dict[str, str]]] = []

    def capture(
        command: list[str],
        *,
        cwd: Path | None = None,
        environment: dict[str, str] | None = None,
    ) -> str:
        del cwd
        calls.append((command, environment or {}))
        return ""

    monkeypatch.setattr(adapter, "_run", capture)
    monkeypatch.setattr(transition, "_git", lambda *_args: "a" * 40)
    adapter.activate_target_with_polling_disabled("a" * 40)
    adapter.compensate_application_only(transition.SOURCE_APPLICATION_SHA)

    assert all(call[0][1] == str(bundle / "deploy.sh") for call in calls)
    assert all(call[1]["NURA_RELEASE_EXECUTION_BUNDLE"] == str(bundle) for call in calls)
    assert calls[0][1]["NURA_TG_POLLING_ENABLED"] == "false"
    assert calls[1][1]["NURA_TG_POLLING_ENABLED"] == "false"
