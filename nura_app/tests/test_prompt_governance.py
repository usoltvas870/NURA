from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from core.config import settings
from core.services.ai import AIService
from core.services.prompt_governance import (
    DEFAULT_BUNDLE_LOCATIONS,
    PromptContractError,
    PromptRegistry,
    canonical_json_bytes,
    prompt_registry,
    resolve_active_bundle,
    validate_active_prompt_bundles,
)


RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "core" / "prompts" / "runtime"


def _copy_runtime(tmp_path: Path) -> Path:
    target = tmp_path / "runtime"
    shutil.copytree(RUNTIME_ROOT, target)
    return target


def _manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(path: Path, value: dict) -> None:
    path.write_bytes(canonical_json_bytes(value))


def test_checked_in_manifests_and_active_defaults_are_valid() -> None:
    bundles = prompt_registry.validate_all()
    assert {(item.bundle_id, item.bundle_version) for item in bundles} == {
        ("nura-report", "v1"),
        ("nura-chat", "v1"),
    }
    assert settings.report_prompt_bundle_version == "v1"
    assert settings.chat_prompt_bundle_version == "v1"
    validate_active_prompt_bundles()


def test_service_boot_validation_rejects_unknown_active_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "report_prompt_bundle_version", "v999")
    with pytest.raises(PromptContractError, match="prompt_bundle_unknown"):
        validate_active_prompt_bundles()


def test_report_and_chat_are_isolated() -> None:
    report = resolve_active_bundle("report.full")
    chat = resolve_active_bundle("chat.free")
    assert report.bundle_id != chat.bundle_id
    assert report.aggregate_hash != chat.aggregate_hash
    with pytest.raises(PromptContractError, match="prompt_consumer_not_allowed"):
        report.pin("chat.free")


def test_ai_cache_key_is_scoped_to_bundle_identity() -> None:
    messages = [{"role": "system", "content": "same content"}]
    params = {"temperature": 0.2}
    old_key = AIService._cache_key(
        messages, "deepseek-chat", params, "nura-report:v1:old-hash"
    )
    new_key = AIService._cache_key(
        messages, "deepseek-chat", params, "nura-report:v2:new-hash"
    )
    assert old_key != new_key


def test_unknown_version_consumer_and_path_traversal_fail_closed() -> None:
    registry = PromptRegistry()
    with pytest.raises(PromptContractError, match="prompt_bundle_unknown"):
        registry.resolve("report.full", "v999")
    with pytest.raises(PromptContractError, match="prompt_consumer_unknown"):
        registry.resolve("report.unknown", "v1")
    with pytest.raises(PromptContractError, match="prompt_version_invalid"):
        registry.resolve("report.full", "../v1")


def test_unapproved_bundle_is_rejected(tmp_path: Path) -> None:
    root = _copy_runtime(tmp_path)
    path = root / "report" / "v1" / "manifest.json"
    manifest = _manifest(path)
    manifest["status"] = "deprecated"
    _write_manifest(path, manifest)
    with pytest.raises(PromptContractError, match="prompt_bundle_unapproved"):
        PromptRegistry(root).resolve("report.full", "v1")


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_file_inventory_is_strict(tmp_path: Path, mutation: str) -> None:
    root = _copy_runtime(tmp_path)
    bundle = root / "report" / "v1"
    if mutation == "missing":
        (bundle / "mini_analysis.txt").unlink()
    else:
        (bundle / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(
        PromptContractError,
        match="prompt_file_(unreadable|inventory_mismatch)",
    ):
        PromptRegistry(root).resolve("report.full", "v1")


def test_file_change_without_manifest_hash_update_is_rejected(tmp_path: Path) -> None:
    root = _copy_runtime(tmp_path)
    path = root / "chat" / "v1" / "system.txt"
    path.write_text(path.read_text(encoding="utf-8") + "\nchange", encoding="utf-8")
    with pytest.raises(PromptContractError, match="prompt_file_hash_mismatch"):
        PromptRegistry(root).resolve("chat.free", "v1")


@pytest.mark.parametrize("replacement", ["", "{unexpected}"])
def test_placeholder_contract_is_exact(tmp_path: Path, replacement: str) -> None:
    root = _copy_runtime(tmp_path)
    bundle = root / "chat" / "v1"
    prompt_path = bundle / "system.txt"
    content = prompt_path.read_text(encoding="utf-8").replace(
        "{matrix_context}", replacement
    )
    prompt_path.write_text(content, encoding="utf-8")
    manifest_path = bundle / "manifest.json"
    manifest = _manifest(manifest_path)
    manifest["files"][0]["sha256"] = hashlib.sha256(
        prompt_path.read_bytes()
    ).hexdigest()
    _write_manifest(manifest_path, manifest)
    with pytest.raises(PromptContractError, match="prompt_placeholder_mismatch"):
        PromptRegistry(root).resolve("chat.free", "v1")


def test_manifest_must_be_canonical_json(tmp_path: Path) -> None:
    root = _copy_runtime(tmp_path)
    path = root / "chat" / "v1" / "manifest.json"
    path.write_text(json.dumps(_manifest(path), ensure_ascii=False, indent=2), encoding="utf-8")
    with pytest.raises(PromptContractError, match="prompt_manifest_not_canonical"):
        PromptRegistry(root).resolve("chat.free", "v1")


def test_empty_system_prompt_is_rejected_without_leaking_content(tmp_path: Path) -> None:
    root = _copy_runtime(tmp_path)
    bundle = root / "chat" / "v1"
    prompt_path = bundle / "system.txt"
    prompt_path.write_text("   \n", encoding="utf-8")
    manifest_path = bundle / "manifest.json"
    manifest = _manifest(manifest_path)
    manifest["files"][0]["sha256"] = hashlib.sha256(
        prompt_path.read_bytes()
    ).hexdigest()
    _write_manifest(manifest_path, manifest)
    with pytest.raises(PromptContractError) as error:
        PromptRegistry(root).resolve("chat.free", "v1")
    assert str(error.value) == "prompt_file_empty"
    assert "Ты — NURA" not in str(error.value)


def test_duplicate_bundle_identity_is_rejected(tmp_path: Path) -> None:
    root = _copy_runtime(tmp_path)
    report_manifest_path = root / "report" / "v1" / "manifest.json"
    chat_manifest_path = root / "chat" / "v1" / "manifest.json"
    report_manifest = _manifest(report_manifest_path)
    chat_manifest = _manifest(chat_manifest_path)
    report_manifest["bundle_id"] = "duplicate"
    chat_manifest["bundle_id"] = "duplicate"
    _write_manifest(report_manifest_path, report_manifest)
    _write_manifest(chat_manifest_path, chat_manifest)
    with pytest.raises(PromptContractError, match="prompt_bundle_duplicate"):
        PromptRegistry(root, DEFAULT_BUNDLE_LOCATIONS).validate_all()


def test_active_report_contract_preserves_schema_with_safe_semantics(sample_matrix) -> None:
    bundle = resolve_active_bundle("report.full")
    system = AIService._governed_report_system(bundle)
    part_b = bundle.content("full_report_part_b.txt").format(
        name="Тест",
        matrix_text="center=1",
    )
    assert "chain of thought" in system.lower()
    assert "не выводи chain of thought" in system.lower()
    assert "без органов, заболеваний, чакр" in part_b
    assert "без дат, возрастов и предсказаний" in part_b
    assert "life_forecast" in part_b and "health_analysis" in part_b


@pytest.mark.parametrize(
    "scenario",
    [
        "ordinary",
        "matrix",
        "future",
        "other_person",
        "new_birth_date",
        "prompt_injection",
        "medical_legal_financial",
        "crisis",
        "limited_history",
        "missing_matrix",
        "fallback",
    ],
)
def test_chat_scenarios_share_one_safe_composed_contract(scenario: str) -> None:
    bundle = resolve_active_bundle("chat.free")
    prompt = AIService._governed_chat_system(bundle, {}, "Тест")
    assert scenario
    assert "не пересчитывай Матрицу" in prompt
    assert "не предсказывай будущее" in prompt
    assert "не упоминай матрицу механически" in prompt.lower()
    assert "Не заканчивай каждый ответ вопросом" in prompt
    assert "честно оставайся AI" in prompt
