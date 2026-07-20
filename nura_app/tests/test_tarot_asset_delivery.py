"""Regression coverage for the deterministic Tarot asset pipeline."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILDER = REPO_ROOT / "scripts" / "build_tarot_assets.py"
ASSET_DIRECTORY = REPO_ROOT / "frontend" / "pwa" / "app" / "images" / "major-v1"


def test_tarot_asset_builder_verifies_checked_in_derivatives() -> None:
    result = subprocess.run(
        [sys.executable, str(BUILDER), "check"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_manifest_keeps_the_approved_22_card_source_contract() -> None:
    manifests = list(ASSET_DIRECTORY.glob("tarot-assets.*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    cards = manifest["cards"]
    assert len(cards) == 22
    assert sorted(card["arcana_id"] for card in cards) == list(range(1, 23))
    fool = next(card for card in cards if card["arcana_id"] == 22)
    assert fool["filename"] == "00-fool.png"
    assert all(set(card["derivatives"]) == {"480", "900"} for card in cards)
