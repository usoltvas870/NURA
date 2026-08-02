"""Exact current-VPS forward migration graph and file-digest gates."""

import shutil
from pathlib import Path

import pytest

from tools.current_vps_migration_contract import (
    EXPECTED_MIGRATIONS,
    MIGRATION_CHAIN_DIGEST,
    MigrationContractError,
    validate_migration_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def copied_versions(tmp_path: Path) -> Path:
    destination = tmp_path / "versions"
    shutil.copytree(ROOT / "alembic" / "versions", destination)
    return destination


def test_exact_migration_chain_and_digest_pass() -> None:
    result = validate_migration_contract(ROOT / "alembic" / "versions")
    assert result["ordered_revisions"] == [item.revision for item in EXPECTED_MIGRATIONS]
    assert result["migration_chain_digest"] == MIGRATION_CHAIN_DIGEST
    assert result["database_downgrade_supported"] is False


def test_altered_migration_hash_is_rejected(tmp_path: Path) -> None:
    versions = copied_versions(tmp_path)
    target = versions / EXPECTED_MIGRATIONS[3].file
    target.write_text(target.read_text(encoding="utf-8") + "\n# altered\n", encoding="utf-8")
    with pytest.raises(MigrationContractError, match="migration_file_hash_mismatch"):
        validate_migration_contract(versions)


def test_unexpected_revision_or_second_head_is_rejected(tmp_path: Path) -> None:
    versions = copied_versions(tmp_path)
    (versions / "unexpected.py").write_text(
        'revision = "eeeeeeeeeeee"\ndown_revision = "d1e2f3a4b5c6"\n',
        encoding="utf-8",
    )
    with pytest.raises(MigrationContractError, match="migration_head_mismatch"):
        validate_migration_contract(versions)


def test_wrong_order_is_rejected(tmp_path: Path) -> None:
    versions = copied_versions(tmp_path)
    target = versions / EXPECTED_MIGRATIONS[1].file
    source = target.read_text(encoding="utf-8").replace(
        'down_revision = "b1c2d3e4f5a6"',
        'down_revision = "d1e2f3a4b5c6"',
    )
    target.write_text(source, encoding="utf-8")
    with pytest.raises(MigrationContractError, match="migration_(head|chain)_mismatch"):
        validate_migration_contract(versions)
