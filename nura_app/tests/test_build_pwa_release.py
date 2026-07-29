"""Regression tests for deterministic PWA release metadata generation.

These tests ensure that the release metadata are independent of platform checkout
line endings (CRLF vs LF) while still reflecting the actual working-tree content.
"""
from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = REPO_ROOT / "scripts" / "build_pwa_release.py"
GENERATOR_MODULE_NAME = "_nura_root_build_pwa_release"


def _load_generator_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(GENERATOR_MODULE_NAME, GENERATOR_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load PWA release generator from {GENERATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = _load_generator_module()
ASSETS = generator.ASSETS
_build_metadata = generator._build_metadata
canonical_asset_bytes = generator.canonical_asset_bytes


def test_generator_module_loaded_from_repository_root() -> None:
    assert generator.__name__ == GENERATOR_MODULE_NAME
    assert generator.__spec__ is not None
    assert Path(generator.__spec__.origin or "").resolve() == GENERATOR_PATH


def test_generator_cli_reports_current_metadata() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR_PATH), "--check"],
        cwd=Path(__file__).parent,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "PWA release metadata is current" in result.stdout


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"a\nb", b"a\nb"),
        (b"a\r\nb", b"a\nb"),
        (b"a\rb", b"a\nb"),
        (b"a\r\nb\rc", b"a\nb\nc"),
        (b"a\r\nb\nc", b"a\nb\nc"),
    ],
)
def test_canonical_asset_bytes_normalizes_line_endings(raw: bytes, expected: bytes) -> None:
    assert canonical_asset_bytes(raw) == expected


def test_canonical_asset_digest_same_for_lf_and_crlf() -> None:
    text = "line one\nline two\nline three\n"
    lf_digest = hashlib.sha256(canonical_asset_bytes(text.encode())).hexdigest()
    crlf_digest = hashlib.sha256(canonical_asset_bytes(text.replace("\n", "\r\n").encode())).hexdigest()
    assert lf_digest == crlf_digest


def test_canonical_asset_digest_same_for_lone_cr() -> None:
    text = "line one\nline two\nline three\n"
    lf_digest = hashlib.sha256(canonical_asset_bytes(text.encode())).hexdigest()
    cr_digest = hashlib.sha256(canonical_asset_bytes(text.replace("\n", "\r").encode())).hexdigest()
    assert lf_digest == cr_digest


def test_canonical_asset_digest_differs_for_different_content() -> None:
    a = hashlib.sha256(canonical_asset_bytes(b"alpha\n")).hexdigest()
    b = hashlib.sha256(canonical_asset_bytes(b"beta\n")).hexdigest()
    assert a != b


def test_build_metadata_uses_canonical_bytes_and_sees_working_tree_changes(
    tmp_path: Path,
) -> None:
    """Metadata must reflect the current working-tree content, not the git index.

    If a file on disk changes, its digest must change. If the only difference is
    line endings, the canonical digest must stay the same.
    """
    root = tmp_path / "repo"
    for asset in ASSETS:
        path = root / asset
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"asset content\n")

    meta = _build_metadata(root)
    chat_hash = meta["assets"]["/pwa/app/chat.html"]
    expected_chat_hash = hashlib.sha256(canonical_asset_bytes(b"asset content\n")).hexdigest()
    assert chat_hash == expected_chat_hash

    # LF and CRLF versions of the same content produce the same canonical digest.
    chat_path = root / "frontend/pwa/app/chat.html"
    chat_path.write_bytes(b"asset content\r\n")
    meta_lf = _build_metadata(root)
    assert meta_lf["assets"]["/pwa/app/chat.html"] == expected_chat_hash

    # A real content change produces a different digest and release ID.
    chat_path.write_bytes(b"changed chat content\n")
    meta_changed = _build_metadata(root)
    changed_chat_hash = hashlib.sha256(
        canonical_asset_bytes(b"changed chat content\n")
    ).hexdigest()
    assert meta_changed["assets"]["/pwa/app/chat.html"] == changed_chat_hash
    assert meta_changed["release_id"] != meta["release_id"]


def test_build_metadata_unaffected_by_line_endings_for_real_assets(
    tmp_path: Path,
) -> None:
    """Canonical line-ending normalization must not mask actual content changes."""
    root = tmp_path / "repo"
    for asset in ASSETS:
        path = root / asset
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"content\n")

    meta = _build_metadata(root)
    for asset in ASSETS:
        url = "/" + asset.removeprefix("frontend/")
        assert meta["assets"][url] == hashlib.sha256(
            canonical_asset_bytes(b"content\n")
        ).hexdigest()
