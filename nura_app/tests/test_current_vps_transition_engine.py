"""Manifest-only preconditions, ordering, and honest compensation boundaries."""

import importlib.util
import inspect
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


def authorization(**overrides: object) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "schema_version": transition.AUTHORIZATION_SCHEMA,
        "authorization_base_commit_sha": "a" * 40,
        "authorization_manifest_path": "docs/operations/authorizations/current-vps-prelaunch-example.json",
        "source_application_sha": transition.SOURCE_APPLICATION_SHA,
        "source_static_sha": transition.SOURCE_APPLICATION_SHA,
        "target_application_sha": "a" * 40,
        "engine_commit_sha": "a" * 40,
        "engine_file_sha256": transition.hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        "current_db_revision": transition.CURRENT_REVISION,
        "target_db_revision": transition.TARGET_REVISION,
        "ordered_migration_revisions": [item.revision for item in transition.EXPECTED_MIGRATIONS],
        "migration_chain_digest": transition.MIGRATION_CHAIN_DIGEST,
        "required_secret_profile_version": transition.SECRET_PROFILE_VERSION,
        "backup_evidence_schema": 1,
        "backup_evidence_checksum": "b" * 64,
        "backup_evidence_sha256": "c" * 64,
        "application_layer_removal_evidence_schema": transition.REMOVAL_EVIDENCE_SCHEMA,
        "application_layer_removal_evidence_checksum": "f" * 64,
        "application_layer_removal_evidence_sha256": "1" * 64,
        "expected_database_counts": {
            "guest_profiles": 5,
            "payments": 0,
            "reports": 2,
            "users": 2,
        },
        "capacity_acknowledgement": {
            "allowed_modes": ["available_ram", "precreated_swap"],
            "minimum_available_ram_bytes": transition.MIN_AVAILABLE_RAM_BYTES,
            "minimum_active_swap_bytes": transition.MIN_ACTIVE_SWAP_BYTES,
        },
        "source_runtime_mode": transition.SOURCE_RUNTIME_MODE,
        "installation_mode": transition.INSTALLATION_MODE,
        "allow_source_fleet_start": False,
        "require_application_layer_removal_evidence": True,
        "post_migration_failure_mode": transition.POST_MIGRATION_FAILURE_MODE,
        "database_downgrade_acknowledgement": "not-supported",
        "owner_approval_identifiers": [transition.OWNER_APPROVAL],
        "valid_from": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=55)).isoformat().replace("+00:00", "Z"),
        "target_artifact_sha256": "d" * 64,
        "target_manifest_sha256": "e" * 64,
    }
    payload.update(overrides)
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
    def revalidate_removal_evidence(self) -> None: self._call("removal_revalidate")
    def verify_application_layer_absent(self) -> None: self._call("verify_absent")
    def apply_migrations(self, _target: str) -> None: self._call("migrate")
    def activate_target_with_polling_disabled(self, _target: str) -> None: self._call("activate_without_polling")
    def verify_target_without_polling(self, _target: str) -> None: self._call("verify_without_polling")
    def verify_owner_only_without_polling(self, _target: str) -> None: self._call("owner_safe_without_polling")
    def activate_bot_polling(self) -> None: self._call("bot_polling")
    def verify_bot_polling(self, _target: str) -> None: self._call("polling_smoke")
    def leave_application_stopped(self, _source: str, _target: str) -> None: self._call("leave_stopped")
    def verify_application_stopped(self, _source: str, _revision: str | None) -> None: self._call("verify_stopped")
    def record(self, phase: str, _payload: object) -> None: self.calls.append(f"record:{phase}")


def good_preconditions(**overrides: object):
    values = {
        "current_application_sha": transition.SOURCE_APPLICATION_SHA,
        "current_static_sha": transition.SOURCE_APPLICATION_SHA,
        "current_db_revision": transition.CURRENT_REVISION,
        "current_database_counts": (2, 5, 2, 0),
        "database_other_sessions": 0,
        "current_release_successful": True,
        "active_transaction_present": False,
        "application_containers_present": False,
        "application_process_present": False,
        "data_services_healthy": True,
        "protected_volumes_present": True,
        "owner_allowlist_exact": True,
        "payments_disabled": True,
        "yookassa_absent": True,
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


def test_schema_v2_and_inexact_clean_install_fields_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "authorization.json"
    for override in (
        {"schema_version": 2},
        {"allow_source_fleet_start": True},
        {"installation_mode": "legacy-transition"},
        {"post_migration_failure_mode": "rollback-source"},
    ):
        path.write_bytes(transition.canonical_json(authorization(**override)))
        with pytest.raises(transition.TransitionError, match="schema_invalid|transition_mismatch"):
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

    git(
        "fetch",
        "--no-tags",
        "--depth=1",
        "origin",
        transition.SOURCE_APPLICATION_SHA,
    )
    git("cat-file", "-e", f"{transition.SOURCE_APPLICATION_SHA}^{{commit}}")
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


def test_target_source_is_clean_and_exact_before_offline_import(tmp_path: Path) -> None:
    repo = tmp_path / "target"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    tracked = repo / "tracked.txt"
    tracked.write_text("target\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=NURA Test",
            "-c",
            "user.email=nura-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "target",
        ],
        check=True,
    )
    target = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    manifest = {"target_application_sha": target}
    transition.validate_target_source_checkout(repo, manifest, engine_root=repo)

    tracked.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(transition.TransitionError, match="target_source_identity_mismatch"):
        transition.validate_target_source_checkout(repo, manifest, engine_root=repo)


@pytest.mark.parametrize(
    ("override", "error"),
    [
        ({"current_application_sha": "f" * 40}, "current_application_mismatch"),
        ({"current_static_sha": "f" * 40}, "current_static_mismatch"),
        ({"current_db_revision": "wrong"}, "current_database_revision_mismatch"),
        ({"current_database_counts": (3, 5, 2, 0)}, "current_database_counts_mismatch"),
        ({"database_other_sessions": 1}, "application_database_session_present"),
        ({"active_transaction_present": True}, "active_transaction_present"),
        ({"application_containers_present": True}, "application_container_present"),
        ({"application_process_present": True}, "application_process_present"),
        ({"data_services_healthy": False}, "data_services_not_healthy"),
        ({"protected_volumes_present": False}, "protected_volume_missing"),
        ({"owner_allowlist_exact": False}, "owner_allowlist_invalid"),
        ({"payments_disabled": False}, "payments_not_disabled"),
        ({"yookassa_absent": False}, "yookassa_present"),
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
            removal_evidence={"result": "APPLICATION_LAYER_RESET_PASS"},
        )
    assert adapter.calls == []


def test_success_order_keeps_bot_last_and_never_cleans_up() -> None:
    adapter = FakeAdapter()
    transition.TransitionEngine(adapter).execute(
        authorization=authorization(),
        preconditions=good_preconditions(),
        backup_evidence={"schema_version": 1},
        removal_evidence={"result": "APPLICATION_LAYER_RESET_PASS"},
    )
    assert adapter.calls == [
        "record:all_preconditions_passed",
        "build",
        "backup_revalidate",
        "removal_revalidate",
        "verify_absent",
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


def test_backup_is_revalidated_after_build_and_before_absence_recheck() -> None:
    adapter = FakeAdapter("backup_revalidate")
    with pytest.raises(RuntimeError, match="backup_revalidate"):
        transition.TransitionEngine(adapter).execute(
            authorization=authorization(),
            preconditions=good_preconditions(),
            backup_evidence={"schema_version": 1},
            removal_evidence={"result": "APPLICATION_LAYER_RESET_PASS"},
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
            removal_evidence={"result": "APPLICATION_LAYER_RESET_PASS"},
        )
    assert adapter.calls == [
        "record:all_preconditions_passed",
        "build",
        "backup_revalidate",
        "removal_revalidate",
        "verify_absent",
        "migrate",
        "leave_stopped",
        "verify_stopped",
        "record:migration_failed",
    ]


def test_post_migration_activation_failure_rolls_back_only_application() -> None:
    adapter = FakeAdapter("verify_without_polling")
    with pytest.raises(RuntimeError, match="verify_without_polling"):
        transition.TransitionEngine(adapter).execute(
            authorization=authorization(),
            preconditions=good_preconditions(),
            backup_evidence={"schema_version": 1},
        removal_evidence={"result": "APPLICATION_LAYER_RESET_PASS"},
        )
    assert "leave_stopped" in adapter.calls
    assert "verify_stopped" in adapter.calls
    assert "bot_polling" not in adapter.calls
    assert adapter.calls[-1] == "record:application_stopped_verified"


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
    manifest = authorization(
        backup_evidence_checksum=payload["checksum"],
        backup_evidence_sha256=transition.hashlib.sha256(evidence.read_bytes()).hexdigest(),
    )

    transition.validate_evidence(
        evidence,
        kind="backup",
        schema=transition.BACKUP_EVIDENCE_SCHEMA,
        manifest=manifest,
        backup_root=backup_root,
    )
    (backup_root / "redis.backup").write_bytes(b"tampered")
    with pytest.raises(transition.TransitionError, match="artifact_mismatch"):
        transition.validate_evidence(
            evidence,
            kind="backup",
            schema=transition.BACKUP_EVIDENCE_SCHEMA,
            manifest=manifest,
            backup_root=backup_root,
        )


def test_removal_evidence_is_identity_bound_and_fail_closed(tmp_path: Path) -> None:
    payload: dict[str, object] = {
        "schema_version": transition.REMOVAL_EVIDENCE_SCHEMA,
        "kind": "legacy_application_layer_removal_evidence",
        "phase": "complete",
        "result": "APPLICATION_LAYER_RESET_PASS",
        "application_containers_after": [],
        "application_services_running": False,
        "active_transactions_after": [],
        "provider_calls": 0,
        "migrations_applied": 0,
        "deploy_performed": False,
        "volumes_deleted": 0,
        "images_deleted": 0,
        "releases_deleted": 0,
        "static_switched": False,
        "database_mutated_by_cleanup": False,
        "processes_after": {"application": 0, "controllers": 0, "provider_facing": 0},
        "protected_containers_after": [
            {"compose_service": service, "state": "running", "health": "healthy"}
            for service in transition.DATA_SERVICES
        ],
        "protected_volumes_after": [
            {"name": name} for name in transition.PROTECTED_VOLUMES
        ],
        "database_after": {
            "revision": transition.CURRENT_REVISION,
            "users": 2,
            "guest_profiles": 5,
            "reports": 2,
            "payments": 0,
            "other_sessions": 0,
        },
        "release_state_after": {
            "canonical_sha": transition.SOURCE_APPLICATION_SHA,
            "static_sha": transition.SOURCE_APPLICATION_SHA,
        },
    }
    payload["checksum"] = transition.compact_payload_checksum(payload)
    evidence = tmp_path / "removal.json"
    evidence.write_bytes(transition.canonical_json(payload))
    manifest = authorization(
        application_layer_removal_evidence_checksum=payload["checksum"],
        application_layer_removal_evidence_sha256=transition.hashlib.sha256(
            evidence.read_bytes()
        ).hexdigest(),
    )
    transition.validate_removal_evidence(evidence, manifest=manifest)

    payload["result"] = "FAILED"
    payload["checksum"] = transition.compact_payload_checksum(
        {key: value for key, value in payload.items() if key != "checksum"}
    )
    evidence.write_bytes(transition.canonical_json(payload))
    tampered_manifest = authorization(
        application_layer_removal_evidence_checksum=payload["checksum"],
        application_layer_removal_evidence_sha256=transition.hashlib.sha256(
            evidence.read_bytes()
        ).hexdigest(),
    )
    with pytest.raises(transition.TransitionError, match="removal_evidence_identity_invalid"):
        transition.validate_removal_evidence(evidence, manifest=tampered_manifest)


def test_concrete_activation_uses_exact_target_bundle(
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
        removal_evidence=tmp_path / "authorization.json",
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
    monkeypatch.setattr(
        transition,
        "_read_canonical_json",
        lambda *_args: {"sha": transition.SOURCE_APPLICATION_SHA},
    )
    adapter.activate_target_with_polling_disabled("a" * 40)

    assert calls[0][0][1] == str(bundle / "deploy.sh")
    assert calls[0][1]["NURA_RELEASE_EXECUTION_BUNDLE"] == str(bundle)
    assert calls[0][1]["NURA_TG_POLLING_ENABLED"] == "false"


def test_source_fleet_is_never_started_by_clean_install_engine() -> None:
    source = inspect.getsource(transition.TransitionEngine)
    assert "activate_from_state" not in source
    assert "compensate_application_only" not in source
    assert "verify_source_fleet" not in source
    assert "leave_application_stopped" in source


def test_application_container_probe_is_project_agnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        (
            subprocess.CompletedProcess([], 0, "container-1\n", ""),
            subprocess.CompletedProcess(
                [],
                0,
                f"bot|{transition.SOURCE_APPLICATION_SHA}|nura-release:{transition.SOURCE_APPLICATION_SHA}\n",
                "",
            ),
        )
    )
    monkeypatch.setattr(transition.subprocess, "run", lambda *_args, **_kwargs: next(responses))
    assert transition._application_containers_present() is True


def test_raw_nura_release_container_without_compose_labels_is_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        (
            subprocess.CompletedProcess([], 0, "raw-container\n", ""),
            subprocess.CompletedProcess(
                [],
                0,
                f"|{transition.SOURCE_APPLICATION_SHA}|nura-release:{transition.SOURCE_APPLICATION_SHA}\n",
                "",
            ),
        )
    )
    monkeypatch.setattr(transition.subprocess, "run", lambda *_args, **_kwargs: next(responses))
    assert transition._application_containers_present() is True


@pytest.mark.parametrize(
    "image",
    [
        "nura-release:" + "a" * 40,
        "nura-release-candidate:" + "a" * 40 + "-run",
        "nura-prelaunch-migration:" + "a" * 40,
    ],
)
def test_concrete_adapter_classifies_raw_nura_images(image: str) -> None:
    assert transition._is_application_container("", "", image) is True


@pytest.mark.parametrize(
    "command",
    [
        "python -m bot.main",
        "python3 -m admin_bot.main",
        "uvicorn api.main:app --host 0.0.0.0",
        "celery -A core.tasks worker --loglevel=info",
        "celery -A core.tasks beat --loglevel=info",
    ],
)
def test_application_process_probe_covers_real_compose_commands(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        transition.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, f"{command}\n", ""),
    )
    assert transition._application_process_present() is True


@pytest.mark.parametrize(
    "phase",
    sorted(
        {
            "stage1_intent",
            "stage1_verified",
            "stage2_intent",
            "stage2_verified",
            "smoke_verified",
            "finalizing",
            "stale_recovery_intent",
            "unknown_future_phase",
        }
    ),
)
def test_unresolved_or_unknown_p7b_phases_fail_closed(tmp_path: Path, phase: str) -> None:
    transaction = tmp_path / "transaction.json"
    transaction.write_bytes(transition.canonical_json({"payload": {"phase": phase}}))
    assert transition._active_transaction_present(tmp_path) is True


@pytest.mark.parametrize("phase", sorted(transition.P7B_QUIESCENT_PHASES))
def test_quiescent_p7b_phases_are_not_active(tmp_path: Path, phase: str) -> None:
    transaction = tmp_path / "transaction.json"
    transaction.write_bytes(transition.canonical_json({"payload": {"phase": phase}}))
    assert transition._active_transaction_present(tmp_path) is False


def test_static_current_rejects_same_basename_outside_release_root(tmp_path: Path) -> None:
    release_root = tmp_path / "canonical" / "releases"
    release_root.mkdir(parents=True)
    outside = tmp_path / "untrusted" / transition.SOURCE_APPLICATION_SHA
    outside.mkdir(parents=True)
    current = release_root.parent / "current"
    try:
        current.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(transition.TransitionError, match="current_static_link_invalid"):
        transition._validate_static_current(
            current,
            transition.SOURCE_APPLICATION_SHA,
            tmp_path / "helper.py",
        )


def test_compensation_removes_target_source_and_unlabelled_revision_containers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    evidence = tmp_path / "evidence"
    (target / "nura_app").mkdir(parents=True)
    evidence.mkdir()
    fixture = tmp_path / "fixture"
    fixture.write_text("fixture", encoding="utf-8")
    adapter = transition.HostMutationAdapter(
        target_source=target,
        authorization_manifest=fixture,
        archive=fixture,
        checksum=fixture,
        public_manifest=fixture,
        evidence_directory=evidence,
        backup_evidence=fixture,
        removal_evidence=fixture,
        backup_root=tmp_path,
        authorization=authorization(),
    )
    rows = [
        ("target", "running", "a" * 40),
        ("source", "running", transition.SOURCE_APPLICATION_SHA),
        ("missing-revision", "running", ""),
    ]
    monkeypatch.setattr(adapter, "_application_containers", lambda: rows)
    commands: list[list[str]] = []
    monkeypatch.setattr(
        adapter,
        "_run",
        lambda command, **_kwargs: commands.append(list(command)) or "",
    )
    adapter._stop_and_remove_application_containers()
    assert commands == [
        ["docker", "stop", "target"],
        ["docker", "stop", "source"],
        ["docker", "stop", "missing-revision"],
        ["docker", "rm", "target"],
        ["docker", "rm", "source"],
        ["docker", "rm", "missing-revision"],
    ]
