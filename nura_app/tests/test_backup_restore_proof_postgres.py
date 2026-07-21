"""PostgreSQL 16 integration proof for disposable backup and restore."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

NURA_APP_ROOT = Path(__file__).resolve().parent.parent
if str(NURA_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(NURA_APP_ROOT))

from tools import backup_restore_proof as proof  # noqa: E402


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    return result.returncode == 0


def test_disposable_postgres_backup_restore_and_fail_closed_matrix(tmp_path: Path) -> None:
    if not _docker_available():
        if os.environ.get("NURA_ALLOW_DOCKER_SKIP") == "1":
            pytest.skip("Docker skip explicitly acknowledged for local execution")
        pytest.fail("Docker is mandatory for the P5B PostgreSQL integration contract")
    evidence_dir = tmp_path / "p5b-integration-evidence"
    result = proof.run_disposable_proof(
        evidence_dir,
        pull_image_if_missing=True,
        verify_repository=False,
        run_fail_closed_checks=True,
    )

    assert result.source_revision == result.restored_revision
    assert result.source_fingerprint == result.restored_fingerprint
    assert result.archive_size_bytes > 0
    assert len(result.archive_sha256) == 64
    assert result.cleanup["status"] == "PASS"
    manifest = json.loads(
        (evidence_dir / "12_backup_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["proof_status"] == "PASS"
    assert manifest["cleanup_status"] == "PASS"
    assert "PENDING CLEANUP" not in (evidence_dir / "33_final_report.md").read_text(
        encoding="utf-8"
    )
    assert result.fail_closed_matrix == {
        "clean_source_backup_restore": "PASS",
        "completed_read_only_session_during_gate": "PASS (detected)",
        "completed_transaction_during_gate": "PASS (detected)",
        "corrupted_archive": "PASS (rejected)",
        "non_empty_target": "PASS (rejected)",
        "restored_data_checksum_mismatch": "PASS (detected)",
        "restored_actual_value_guard": "PASS (rejected nested marker)",
        "restored_credential_guard": "PASS (rejected credential field)",
        "restored_nested_credential_guard": "PASS (rejected nested credential)",
        "restored_row_count_mismatch": "PASS (detected)",
        "sequence_mismatch": "PASS (detected)",
        "source_actual_value_guard": "PASS (rejected nested marker)",
        "source_credential_guard": "PASS (rejected credential field)",
        "source_nested_credential_guard": "PASS (rejected nested credential)",
        "target_source_identity_collision": "PASS (rejected)",
        "unexpected_application_transaction": "PASS (rejected)",
    }

    required_evidence = {
        *(f"{index:02d}_{name}" for index, name in enumerate((
            "preflight.txt",
            "owner_decisions.md",
            "worktree_and_branch.txt",
            "repository_baseline.txt",
            "environment_versions.txt",
            "postgres_images_and_digests.txt",
            "source_creation.txt",
            "alembic_upgrade.txt",
            "fixture_manifest.json",
            "source_verification.json",
            "quiescence_gate.json",
            "backup_command_redacted.txt",
            "backup_manifest.json",
            "archive_catalog.txt",
            "archive_checksum.txt",
            "encryption_proof.md",
            "target_empty_gate.json",
            "restore_command_redacted.txt",
            "restore_verification.json",
            "catalog_comparison.json",
            "row_counts.json",
            "data_checksums.json",
            "sequences.json",
            "constraints_indexes_objects.json",
            "pii_guard.json",
            "timings_and_throughput.json",
            "fail_closed_matrix.md",
            "test_results.txt",
            "cleanup.txt",
            "git_diff_and_allowlist.txt",
            "commit.txt",
            "draft_pr.txt",
            "remote_ci.txt",
            "final_report.md",
        ))),
        "SHA256SUMS.txt",
    }
    assert required_evidence <= {path.name for path in evidence_dir.iterdir()}
    assert not subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label=nura.run_id={result.run_id}",
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
