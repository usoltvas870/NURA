"""Unit and static contracts for the synthetic-only P5B proof runner."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

NURA_APP_ROOT = Path(__file__).resolve().parent.parent
TOOLS_ROOT = NURA_APP_ROOT / "tools"
if str(NURA_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(NURA_APP_ROOT))

from tools import backup_restore_proof as proof  # noqa: E402


def test_disposable_identifiers_reject_production_like_values() -> None:
    with pytest.raises(proof.ProofError, match="non-disposable"):
        proof.validate_disposable_identifier("protected-production-target", "target_database")


def test_source_and_target_identity_collision_is_rejected() -> None:
    with pytest.raises(proof.ProofError, match="distinct"):
        proof.validate_distinct_resources(
            "nura-p5b-source-000000000000",
            "nura-p5b-source-000000000000",
            "p5b_source_000000000000",
            "p5b_source_000000000000",
        )


def test_remote_hostname_is_rejected() -> None:
    with pytest.raises(proof.ProofError, match="Remote"):
        proof.validate_loopback_hostname("protected-remote.invalid")


def test_missing_artifact_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(proof.ProofError, match="missing"):
        proof.validate_artifact(tmp_path / "missing.dump")


def test_zero_byte_artifact_is_rejected(tmp_path: Path) -> None:
    artifact = tmp_path / "empty.dump"
    artifact.touch()
    with pytest.raises(proof.ProofError, match="empty"):
        proof.validate_artifact(artifact)


def test_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    artifact = tmp_path / "synthetic.dump"
    artifact.write_bytes(b"synthetic archive")
    with pytest.raises(proof.ProofError, match="checksum mismatch"):
        proof.validate_artifact(artifact, "0" * 64)


def test_valid_artifact_returns_sha256(tmp_path: Path) -> None:
    artifact = tmp_path / "synthetic.dump"
    artifact.write_bytes(b"synthetic archive")
    assert proof.validate_artifact(artifact) == hashlib.sha256(
        b"synthetic archive"
    ).hexdigest()


def test_invalid_manifest_is_rejected() -> None:
    with pytest.raises(proof.ProofError, match="missing required keys"):
        proof.validate_manifest({"proof_status": "PASS"})
    with pytest.raises(proof.ProofError, match="JSON object"):
        proof.validate_manifest(json.loads("[]"))


def test_failed_manifest_is_a_valid_fail_closed_final_state() -> None:
    manifest = {key: "synthetic" for key in proof._MANIFEST_KEYS}
    manifest["proof_status"] = "FAILED"
    assert proof.validate_manifest(manifest)["proof_status"] == "FAILED"


def test_wrong_tool_major_is_rejected() -> None:
    with pytest.raises(proof.ProofError, match="major version"):
        proof.validate_client_versions(
            {
                "pg_dump": "pg_dump (PostgreSQL) 15.9",
                "pg_restore": "pg_restore (PostgreSQL) 16.13",
                "psql": "psql (PostgreSQL) 16.13",
            }
        )


def test_wrong_exact_tool_version_is_rejected() -> None:
    with pytest.raises(proof.ProofError, match="exact version"):
        proof.validate_client_versions(
            {
                "pg_dump": "pg_dump (PostgreSQL) 16.12",
                "pg_restore": "pg_restore (PostgreSQL) 16.13",
                "psql": "psql (PostgreSQL) 16.13",
            }
        )


def test_non_empty_target_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            ([], [(1,)]),
            ([], []),
        ]
    )
    monkeypatch.setattr(proof, "_query", lambda *_args, **_kwargs: next(responses))
    with pytest.raises(proof.ProofError, match="not empty"):
        proof._empty_target_gate("postgresql://***/***")


@pytest.mark.parametrize(
    ("actual_revision", "expected_revision", "actual_fingerprint", "expected_fingerprint", "fixture", "expected_fixture", "message"),
    [
        ("rev-a", "rev-b", "fingerprint", "fingerprint", "fixture", "fixture", "revision"),
        ("rev", "rev", "fingerprint-a", "fingerprint-b", "fixture", "fixture", "fingerprint"),
        ("rev", "rev", "fingerprint", "fingerprint", "fixture-a", "fixture-b", "Fixture"),
    ],
)
def test_expected_metadata_mismatches_fail_closed(
    actual_revision: str,
    expected_revision: str,
    actual_fingerprint: str,
    expected_fingerprint: str,
    fixture: str,
    expected_fixture: str,
    message: str,
) -> None:
    with pytest.raises(proof.ProofError, match=message):
        proof.verify_expected_metadata(
            actual_revision=actual_revision,
            expected_revision=expected_revision,
            actual_fingerprint=actual_fingerprint,
            expected_fingerprint=expected_fingerprint,
            fixture_checksum=fixture,
            expected_fixture_checksum=expected_fixture,
        )


def test_acknowledgement_flag_is_required(tmp_path: Path) -> None:
    assert proof.main(["--evidence-dir", str(tmp_path / "evidence")]) == 2


@pytest.mark.parametrize("status", [" M tracked.py\0", "?? untracked.txt\0"])
def test_repository_preflight_rejects_any_dirty_state(status: str) -> None:
    with pytest.raises(proof.ProofError, match="completely clean"):
        proof._validate_repository_state(
            status=status,
            head="a" * 40,
            branch="feature",
            remote="b" * 40,
            remote_is_ancestor=True,
        )


def test_repository_preflight_accepts_main_only_at_remote_head() -> None:
    state = proof._validate_repository_state(
        status="",
        head="a" * 40,
        branch="main",
        remote="a" * 40,
        remote_is_ancestor=True,
    )
    assert state.repository_clean is True
    with pytest.raises(proof.ProofError, match="exactly match"):
        proof._validate_repository_state(
            status="",
            head="a" * 40,
            branch="main",
            remote="b" * 40,
            remote_is_ancestor=True,
        )


def test_repository_preflight_accepts_clean_feature_descendant() -> None:
    state = proof._validate_repository_state(
        status="",
        head="a" * 40,
        branch="any-feature-name",
        remote="b" * 40,
        remote_is_ancestor=True,
    )
    assert state.current_branch == "any-feature-name"


def test_repository_preflight_rejects_detached_and_stale_feature() -> None:
    with pytest.raises(proof.ProofError, match="Detached"):
        proof._validate_repository_state(
            status="",
            head="a" * 40,
            branch="",
            remote="b" * 40,
            remote_is_ancestor=False,
        )


def test_repository_binding_rejects_post_preflight_drift() -> None:
    expected = proof.RepositoryState("a" * 40, "feature", "b" * 40, True)
    actual = proof.RepositoryState("c" * 40, "feature", "b" * 40, True)
    with pytest.raises(proof.ProofError, match="drifted"):
        proof._assert_repository_binding(expected, actual)
    with pytest.raises(proof.ProofError, match="contain"):
        proof._validate_repository_state(
            status="",
            head="a" * 40,
            branch="feature",
            remote="b" * 40,
            remote_is_ancestor=False,
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "unix:///var/run/docker.sock",
        "npipe:////./pipe/docker_engine",
        "tcp://127.0.0.1:2375",
        "tcp://localhost:2375",
        "tcp://[::1]:2375",
    ],
)
def test_local_docker_endpoints_are_accepted(endpoint: str) -> None:
    assert proof._validate_local_docker_endpoint("default", endpoint).endpoint == endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "ssh://host/docker",
        "tcp://remote-host:2375",
        "tcp://10.0.0.1:2375",
        "http://127.0.0.1:2375",
        "https://host:2376",
        "npipe:////remote-host/pipe/docker_engine",
        "npipe://remote-host/pipe/docker_engine",
        "not-an-endpoint",
    ],
)
def test_remote_or_unapproved_docker_endpoints_are_rejected(endpoint: str) -> None:
    with pytest.raises(proof.ProofError):
        proof._validate_local_docker_endpoint("default", endpoint)


def test_rejected_docker_endpoint_runs_no_mutating_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run(command: list[str], **_kwargs) -> proof.CommandResult:
        commands.append(tuple(command))
        output = "default\n" if command[-2:] == ["context", "show"] else '"ssh://remote/docker"\n'
        return proof.CommandResult(tuple(command), 0, output, "", 0.0)

    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(proof, "_run", fake_run)
    with pytest.raises(proof.ProofError):
        proof._docker_endpoint_preflight(tmp_path)
    assert all("create" not in command and "run" not in command for command in commands)


def test_docker_context_inspection_failure_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **_kwargs) -> proof.CommandResult:
        if command[-2:] == ["context", "show"]:
            return proof.CommandResult(tuple(command), 0, "default\n", "", 0.0)
        raise proof.ProofError("inspection failed")

    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(proof, "_run", fake_run)
    with pytest.raises(proof.ProofError, match="inspection failed"):
        proof._docker_endpoint_preflight(tmp_path)


def test_nested_actual_value_marker_is_rejected() -> None:
    hits = proof._actual_value_hits(
        "ai_analysis",
        {"safe": [{"nested": "protected_production_database_marker"}]},
    )
    assert hits["production_marker_or_domain"] == 1


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("web_session_id", "protected_session_value_0123456789"),
        ("ai_analysis", {"password": "protected_password_value"}),
        ("ai_analysis", {"nested": [{"client_secret": "protected_secret_value"}]}),
        ("ai_analysis", {"refresh_token": "protected_refresh_value"}),
        ("ai_analysis", {"secret_key": "protected_secret_key_value"}),
        ("ai_analysis", {"authorization": "Basic protected-value"}),
    ],
)
def test_actual_value_guard_rejects_credential_fields(
    column: str, value: object
) -> None:
    hits = proof._actual_value_hits(column, value)
    assert hits["credential_or_private_key"] > 0


def test_normal_nested_synthetic_value_passes() -> None:
    assert not any(
        proof._actual_value_hits(
            "ai_analysis", {"safe": ["synthetic_result", "user@example.invalid"]}
        ).values()
    )


def test_generated_evidence_scan_includes_artifacts_and_rejects_secret(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "synthetic.bin").write_bytes(b"prefix ephemeral-test-password suffix")
    with pytest.raises(proof.ProofError, match="known_ephemeral_secret"):
        proof._scan_generated_evidence(
            tmp_path, ephemeral_secrets=("ephemeral-test-password",)
        )


def test_command_result_never_retains_a_secret_in_argv() -> None:
    secret = "synthetic-ephemeral-secret"
    result = proof._run(
        [sys.executable, "-c", "print('ok')", secret],
        secrets_to_mask=(secret,),
    )
    assert secret not in " ".join(result.command)


def test_encryption_preflight_records_actual_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "synthetic.dump"
    archive.write_bytes(b"synthetic")
    monkeypatch.setattr(proof.shutil, "which", lambda _tool: None)
    result = proof._encryption_proof(archive, tmp_path)
    assert result["status"] == "NOT EXECUTED — PRODUCTION TOOLING DECISION PENDING"
    assert result["discovered_tools"] == {}


def test_gpg_round_trip_uses_disposable_home_and_persists_no_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "synthetic.dump"
    archive.write_bytes(b"synthetic archive")
    gpg_homes: list[Path] = []

    def fake_which(tool: str) -> str | None:
        return "gpg" if tool == "gpg" else None

    def fake_run(command: list[str], **kwargs) -> proof.CommandResult:
        if command[0] == "gpg" and "--version" in command:
            return proof.CommandResult(tuple(command), 0, "gpg 2.4.0\n", "", 0.0)
        if command[0] == "gpg":
            home = Path(command[command.index("--homedir") + 1])
            gpg_homes.append(home)
            assert kwargs["env"]["GNUPGHOME"] == str(home)
            assert kwargs["input_text"].strip() not in " ".join(command)
            output = Path(command[command.index("--output") + 1])
            if "--symmetric" in command:
                output.write_bytes(b"encrypted")
            else:
                output.write_bytes(archive.read_bytes())
            return proof.CommandResult(tuple(command), 0, "", "", 0.0)
        return proof.CommandResult(tuple(command), 0, "", "", 0.0)

    monkeypatch.setattr(proof.shutil, "which", fake_which)
    monkeypatch.setattr(proof, "_run", fake_run)
    result = proof._encryption_proof(archive, tmp_path)
    assert result["status"] == "PASS"
    assert result["integrity_protection"].startswith("OpenPGP MDC")
    assert gpg_homes and all(not home.exists() for home in gpg_homes)


def test_evidence_file_is_hardened(tmp_path: Path) -> None:
    artifact = tmp_path / "synthetic.dump"
    artifact.write_bytes(b"synthetic")
    proof._secure_path(artifact, directory=False)
    proof._verify_secure_path(artifact, directory=False)


def test_completed_interval_activity_fails_quiescence() -> None:
    snapshot = proof.DatabaseSnapshot(
        revision="rev",
        schema_fingerprint="fingerprint",
        catalog={},
        catalog_counts={},
        row_counts={},
        data_checksums={},
        sequence_states={},
        logical_size_bytes=0,
        pii_guard={"status": "PASS"},
    )
    before = {
        "database_activity_counters": {
            "tup_inserted": 1,
            "tup_updated": 0,
            "tup_deleted": 1,
            "conflicts": 0,
            "deadlocks": 0,
            "stats_reset": None,
        }
    }
    after = {
        "database_activity_counters": {
            **before["database_activity_counters"],
            "tup_inserted": 2,
        }
    }
    with pytest.raises(proof.ProofError, match="activity changed"):
        proof._validate_quiescence_interval(
            before, after, snapshot, snapshot, expected_dump_sessions=0
        )


def test_cleanup_continues_after_independent_inspection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run(command: list[str], **_kwargs) -> proof.CommandResult:
        commands.append(tuple(command))
        if command[:3] == ["docker", "container", "inspect"] and command[3] == "source":
            raise proof.ProofError("synthetic timeout")
        return proof.CommandResult(tuple(command), 1, "", "", 0.0)

    monkeypatch.setattr(proof, "_run", fake_run)
    endpoint = proof.DockerEndpoint("default", "npipe:////./pipe/docker_engine", "npipe:////./pipe/docker_engine", "npipe")
    result = proof._cleanup_resources(endpoint, "p5b_000000000000", ("source", "target"), "network")
    assert result["status"] == "FAIL"
    assert any("inspect" in command and "network" in command for command in commands)
    assert any("ls" in command and "network" in command for command in commands)


def test_cleanup_never_passes_when_docker_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str], **_kwargs) -> proof.CommandResult:
        return proof.CommandResult(tuple(command), 1, "", "daemon unavailable", 0.0)

    monkeypatch.setattr(proof, "_run", fake_run)
    endpoint = proof.DockerEndpoint("default", "npipe:////./pipe/docker_engine", "npipe:////./pipe/docker_engine", "npipe")
    result = proof._cleanup_resources(endpoint, "p5b_000000000000", ("source", "target"), "network")
    assert result["status"] == "FAIL"
    assert result["errors"]


def test_help_describes_synthetic_only_scope() -> None:
    result = subprocess.run(
        [sys.executable, str(TOOLS_ROOT / "backup_restore_proof.py"), "--help"],
        cwd=NURA_APP_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "synthetic-only" in result.stdout
    assert "not a production backup executor" in result.stdout
    assert "--synthetic-disposable-proof" in result.stdout


def test_runner_has_no_unsafe_production_or_cleanup_paths() -> None:
    source = (TOOLS_ROOT / "backup_restore_proof.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "shell=true" not in lowered
    assert "docker system prune" not in lowered
    assert "pg_terminate_backend" not in lowered
    assert "workflow_dispatch" not in lowered
    assert "alembic downgrade" not in lowered
    assert "--clean" not in source
    assert "--create" not in source
    assert "docker-compose" not in lowered
    assert "core.config" not in lowered
    assert "env_file" not in lowered
    assert "codex/p5b-backup-restore-proof" not in source
    assert "63b75c39faedd57f7882edf7e8e54bb678abb17e" not in source
