#!/usr/bin/env python3
"""Deterministic forward-only migration contract for the owner prelaunch cutover."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


CURRENT_REVISION = "d1e2f3a4b5c6"
TARGET_REVISION = "d8e9f0a1b2c3"
SOURCE_APPLICATION_SHA = "9da6ad8cf0146b26bdd2b60ebf99b54a58ccd532"
MIGRATION_CHAIN_DIGEST = (
    "0277a4602fcc948e60450c80ec55121529f14443ee9616b38d3a4ead2549d0ad"
)


@dataclass(frozen=True)
class MigrationFileContract:
    revision: str
    down_revision: str
    file: str
    sha256: str


EXPECTED_MIGRATIONS = (
    MigrationFileContract("b1c2d3e4f5a6", CURRENT_REVISION, "a1b2c3d4e5f6_add_attribution_foundation.py", "4b125599e861517d2c3903d41dcfa73550f13b3847897c57215f4aa7cc8a9497"),
    MigrationFileContract("c1d2e3f4a5b6", "b1c2d3e4f5a6", "c1d2e3f4a5b6_add_mini_report_generation_foundation.py", "cbeb81a35ad20375498bdb376e536fb8a55b26a3b214d5b008f126eaf9286fe4"),
    MigrationFileContract("d2e3f4a5b6c7", "c1d2e3f4a5b6", "d2e3f4a5b6c7_add_telegram_mini_report_delivery.py", "dc0776d59b0ed132bea4416c0bfcb760ed04febe6813ee99aeff956f198263bf"),
    MigrationFileContract("d6e7f8a9b0c1", "d2e3f4a5b6c7", "d6e7f8a9b0c1_add_lifetime_chat_message_usage.py", "733508b6302099156b4db769f98fed0c328f9c5fe0a924354e34e76faa1476fc"),
    MigrationFileContract("d7e8f9a0b1c2", "d6e7f8a9b0c1", "d7e8f9a0b1c2_add_daily_tarot_draws.py", "fcdf0ee8c7fc24b6385338ae0ceb70e788275a79fe17090e5a080cafbe081227"),
    MigrationFileContract("e8f9a0b1c2d3", "d7e8f9a0b1c2", "e8f9a0b1c2d3_add_full_matrix_orders.py", "3a0542cc9c9dcc902e89492714717079aeb087b8a2f92ef65d3b79b1bc64fc2b"),
    MigrationFileContract("f9a0b1c2d3e4", "e8f9a0b1c2d3", "f9a0b1c2d3e4_add_full_report_telegram_delivery.py", "d6ce5a438913ed22f5608d67e1969afc4cddbaa5d62acdfaf90a48b91a235e37"),
    MigrationFileContract("b4c5d6e7f8a9", "f9a0b1c2d3e4", "b4c5d6e7f8a9_add_chat_delivery_progress.py", "63f3c4ad41edbe0cef53fc96592a07d172a9122fca89112dc794526590bda516"),
    MigrationFileContract("c5d6e7f8a9b0", "b4c5d6e7f8a9", "c5d6e7f8a9b0_add_full_report_text_delivery_progress.py", "0f90b5856658727dc60c8a79fc571064b7d57e753a9f3d78a0d92b12d87d6eb6"),
    MigrationFileContract("c6d7e8f9a0b1", "c5d6e7f8a9b0", "c6d7e8f9a0b1_add_broadcast_campaign_contour.py", "010701fc227751225c036dc016104331962fda31d0e726b2b1ac1406ad8c7c82"),
    MigrationFileContract(TARGET_REVISION, "c6d7e8f9a0b1", "d8e9f0a1b2c3_add_prompt_generation_metadata.py", "3384997950c348d7d40d508ca5637bf0521e2c2dac81c5fb11f0bc0e077835b3"),
)


class MigrationContractError(RuntimeError):
    """A bounded migration-contract failure without source or credential data."""


def _metadata(path: Path) -> tuple[str, str | None]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise MigrationContractError("migration_file_unreadable") from exc
    values: dict[str, Any] = {}
    for node in tree.body:
        name: str | None = None
        expression: ast.expr | None = None
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            name, expression = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, expression = node.target.id, node.value
        if name in {"revision", "down_revision"} and expression is not None:
            try:
                values[name] = ast.literal_eval(expression)
            except (ValueError, SyntaxError) as exc:
                raise MigrationContractError("migration_metadata_invalid") from exc
    revision = values.get("revision")
    down_revision = values.get("down_revision")
    if not isinstance(revision, str) or (
        down_revision is not None and not isinstance(down_revision, str)
    ):
        raise MigrationContractError("migration_metadata_invalid")
    return revision, down_revision


def canonical_chain_payload() -> bytes:
    payload = [asdict(item) for item in EXPECTED_MIGRATIONS]
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def validate_migration_contract(versions_dir: Path) -> dict[str, object]:
    actual: dict[str, tuple[str | None, Path]] = {}
    for path in sorted(versions_dir.glob("*.py")):
        revision, down_revision = _metadata(path)
        if revision in actual:
            raise MigrationContractError("migration_revision_duplicate")
        actual[revision] = (down_revision, path)
    parents = {
        down_revision
        for down_revision, _ in actual.values()
        if down_revision is not None
    }
    heads = sorted(set(actual) - parents)
    if heads != [TARGET_REVISION]:
        raise MigrationContractError("migration_head_mismatch")

    previous = CURRENT_REVISION
    for expected in EXPECTED_MIGRATIONS:
        record = actual.get(expected.revision)
        if record is None or record[0] != previous or record[1].name != expected.file:
            raise MigrationContractError("migration_chain_mismatch")
        digest = hashlib.sha256(record[1].read_bytes()).hexdigest()
        if digest != expected.sha256:
            raise MigrationContractError("migration_file_hash_mismatch")
        previous = expected.revision
    if previous != TARGET_REVISION:
        raise MigrationContractError("migration_target_mismatch")
    aggregate = hashlib.sha256(canonical_chain_payload()).hexdigest()
    if aggregate != MIGRATION_CHAIN_DIGEST:
        raise MigrationContractError("migration_chain_digest_mismatch")
    return {
        "current_revision": CURRENT_REVISION,
        "target_revision": TARGET_REVISION,
        "ordered_revisions": [item.revision for item in EXPECTED_MIGRATIONS],
        "migration_chain_digest": aggregate,
        "single_head": True,
        "backward_compatible_source_application": SOURCE_APPLICATION_SHA,
        "database_downgrade_supported": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--versions-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "alembic" / "versions",
    )
    args = parser.parse_args()
    try:
        result = validate_migration_contract(args.versions_dir)
        output = {"status": "PASS", "result": result}
        code = 0
    except MigrationContractError as exc:
        output = {"status": "FAIL", "error": str(exc)}
        code = 1
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
