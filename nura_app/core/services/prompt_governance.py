"""Checked-in runtime prompt governance for NURA report and free-chat consumers."""

from __future__ import annotations

import hashlib
import json
import re
import string
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping


RUNTIME_PROMPTS_DIR = Path(__file__).parent.parent / "prompts" / "runtime"
APPROVED_STATUSES = frozenset({"active", "approved"})
CONSUMER_FAMILIES = MappingProxyType(
    {
        "report.mini": "report",
        "report.full": "report",
        "report.kitchen": "report",
        "chat.free": "chat",
    }
)
DEFAULT_BUNDLE_LOCATIONS = MappingProxyType(
    {
        "report": MappingProxyType({"v1": "report/v1"}),
        "chat": MappingProxyType({"v1": "chat/v1"}),
    }
)
PIN_FIELDS = (
    "prompt_consumer",
    "bundle_id",
    "bundle_version",
    "prompt_hash",
    "style_contract_version",
    "output_schema_version",
)


class PromptContractError(RuntimeError):
    """A bounded, content-free prompt contract failure."""


@dataclass(frozen=True)
class PromptFileContract:
    path: str
    sha256: str
    required_placeholders: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedPromptBundle:
    family: str
    bundle_id: str
    bundle_version: str
    style_contract_version: str
    output_schema_version: str
    status: str
    allowed_consumers: tuple[str, ...]
    aggregate_hash: str
    files: Mapping[str, str]

    def content(self, path: str) -> str:
        try:
            return self.files[path]
        except KeyError as exc:
            raise PromptContractError("prompt_file_not_declared") from exc

    def pin(self, consumer: str) -> dict[str, object]:
        if consumer not in self.allowed_consumers:
            raise PromptContractError("prompt_consumer_not_allowed")
        return {
            "prompt_consumer": consumer,
            "bundle_id": self.bundle_id,
            "bundle_version": self.bundle_version,
            "prompt_hash": self.aggregate_hash,
            "style_contract_version": self.style_contract_version,
            "output_schema_version": self.output_schema_version,
            "requested_provider": "deepseek",
            "requested_model": None,
            "provider": None,
            "model": None,
            "generation_source": None,
            "generated_at": None,
        }


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _safe_relative_path(raw: object) -> str:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise PromptContractError("prompt_path_invalid")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PromptContractError("prompt_path_invalid")
    return path.as_posix()


def _placeholders(content: str) -> tuple[str, ...]:
    names: set[str] = set()
    try:
        parsed = string.Formatter().parse(content)
        for _, field_name, _, _ in parsed:
            if field_name is None:
                continue
            if not re.fullmatch(r"[a-z][a-z0-9_]*", field_name):
                raise PromptContractError("prompt_placeholder_invalid")
            names.add(field_name)
    except ValueError as exc:
        raise PromptContractError("prompt_template_invalid") from exc
    return tuple(sorted(names))


class PromptRegistry:
    """Resolve only code-allowlisted bundle family/version pairs."""

    def __init__(
        self,
        root: Path = RUNTIME_PROMPTS_DIR,
        locations: Mapping[str, Mapping[str, str]] = DEFAULT_BUNDLE_LOCATIONS,
    ) -> None:
        self._root = root.resolve()
        self._locations = locations

    def resolve(self, consumer: str, version: str) -> ResolvedPromptBundle:
        family = CONSUMER_FAMILIES.get(consumer)
        if family is None:
            raise PromptContractError("prompt_consumer_unknown")
        if not isinstance(version, str) or not re.fullmatch(r"v[1-9][0-9]*", version):
            raise PromptContractError("prompt_version_invalid")
        location = self._locations.get(family, {}).get(version)
        if location is None:
            raise PromptContractError("prompt_bundle_unknown")
        bundle_dir = (self._root / _safe_relative_path(location)).resolve()
        if self._root not in bundle_dir.parents:
            raise PromptContractError("prompt_path_invalid")
        return self._load_bundle(bundle_dir, family, consumer, version)

    def validate_all(self) -> tuple[ResolvedPromptBundle, ...]:
        resolved: list[ResolvedPromptBundle] = []
        identities: set[tuple[str, str]] = set()
        for family, versions in sorted(self._locations.items()):
            consumers = sorted(
                consumer
                for consumer, consumer_family in CONSUMER_FAMILIES.items()
                if consumer_family == family
            )
            if not consumers:
                raise PromptContractError("prompt_family_without_consumer")
            for version in sorted(versions):
                bundle = self.resolve(consumers[0], version)
                identity = (bundle.bundle_id, bundle.bundle_version)
                if identity in identities:
                    raise PromptContractError("prompt_bundle_duplicate")
                identities.add(identity)
                resolved.append(bundle)
        return tuple(resolved)

    def _load_bundle(
        self,
        bundle_dir: Path,
        family: str,
        consumer: str,
        expected_version: str,
    ) -> ResolvedPromptBundle:
        manifest_path = bundle_dir / "manifest.json"
        try:
            manifest_bytes = manifest_path.read_bytes()
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PromptContractError("prompt_manifest_unreadable") from exc
        if canonical_json_bytes(manifest) != manifest_bytes:
            raise PromptContractError("prompt_manifest_not_canonical")
        required_keys = {
            "bundle_id",
            "bundle_version",
            "style_contract_version",
            "output_schema_version",
            "status",
            "allowed_consumers",
            "files",
        }
        if set(manifest) not in (required_keys, required_keys | {"migration_note"}):
            raise PromptContractError("prompt_manifest_schema_invalid")
        for key in (
            "bundle_id",
            "bundle_version",
            "style_contract_version",
            "output_schema_version",
            "status",
        ):
            if not isinstance(manifest[key], str) or not manifest[key]:
                raise PromptContractError("prompt_manifest_schema_invalid")
        if manifest["bundle_version"] != expected_version:
            raise PromptContractError("prompt_bundle_version_mismatch")
        if manifest["status"] not in APPROVED_STATUSES:
            raise PromptContractError("prompt_bundle_unapproved")
        allowed = manifest["allowed_consumers"]
        if (
            not isinstance(allowed, list)
            or allowed != sorted(set(allowed))
            or any(CONSUMER_FAMILIES.get(item) != family for item in allowed)
            or consumer not in allowed
        ):
            raise PromptContractError("prompt_consumer_not_allowed")
        raw_files = manifest["files"]
        if not isinstance(raw_files, list) or not raw_files:
            raise PromptContractError("prompt_manifest_schema_invalid")

        contracts: list[PromptFileContract] = []
        seen: set[str] = set()
        contents: dict[str, str] = {}
        for raw_file in raw_files:
            if not isinstance(raw_file, dict) or set(raw_file) != {
                "path",
                "sha256",
                "required_placeholders",
            }:
                raise PromptContractError("prompt_manifest_schema_invalid")
            path = _safe_relative_path(raw_file["path"])
            digest = raw_file["sha256"]
            placeholders = raw_file["required_placeholders"]
            if path in seen:
                raise PromptContractError("prompt_file_duplicate")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise PromptContractError("prompt_file_hash_invalid")
            if (
                not isinstance(placeholders, list)
                or placeholders != sorted(set(placeholders))
                or any(not isinstance(item, str) for item in placeholders)
            ):
                raise PromptContractError("prompt_placeholder_contract_invalid")
            file_path = (bundle_dir / path).resolve()
            if bundle_dir not in file_path.parents:
                raise PromptContractError("prompt_path_invalid")
            try:
                content_bytes = file_path.read_bytes()
                content = content_bytes.decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise PromptContractError("prompt_file_unreadable") from exc
            if not content.strip():
                raise PromptContractError("prompt_file_empty")
            if hashlib.sha256(content_bytes).hexdigest() != digest:
                raise PromptContractError("prompt_file_hash_mismatch")
            if _placeholders(content) != tuple(placeholders):
                raise PromptContractError("prompt_placeholder_mismatch")
            seen.add(path)
            contents[path] = content
            contracts.append(PromptFileContract(path, digest, tuple(placeholders)))

        actual_inventory = {
            path.relative_to(bundle_dir).as_posix()
            for path in bundle_dir.rglob("*")
            if path.is_file()
        }
        if actual_inventory != {"manifest.json", *seen}:
            raise PromptContractError("prompt_file_inventory_mismatch")
        if "system.txt" not in seen:
            raise PromptContractError("prompt_system_missing")

        aggregate = hashlib.sha256()
        aggregate.update(manifest_bytes)
        for contract in sorted(contracts, key=lambda item: item.path):
            aggregate.update(contract.path.encode("utf-8"))
            aggregate.update(b"\x00")
            aggregate.update(contents[contract.path].encode("utf-8"))
        return ResolvedPromptBundle(
            family=family,
            bundle_id=manifest["bundle_id"],
            bundle_version=manifest["bundle_version"],
            style_contract_version=manifest["style_contract_version"],
            output_schema_version=manifest["output_schema_version"],
            status=manifest["status"],
            allowed_consumers=tuple(allowed),
            aggregate_hash=aggregate.hexdigest(),
            files=MappingProxyType(contents),
        )


prompt_registry = PromptRegistry()


def resolve_active_bundle(consumer: str) -> ResolvedPromptBundle:
    from core.config import settings

    family = CONSUMER_FAMILIES.get(consumer)
    if family == "report":
        version = settings.report_prompt_bundle_version
    elif family == "chat":
        version = settings.chat_prompt_bundle_version
    else:
        raise PromptContractError("prompt_consumer_unknown")
    return prompt_registry.resolve(consumer, version)


def resolve_pinned_bundle(consumer: str, metadata: Mapping[str, object]) -> ResolvedPromptBundle:
    version = metadata.get("bundle_version")
    if not isinstance(version, str):
        raise PromptContractError("prompt_pin_invalid")
    bundle = prompt_registry.resolve(consumer, version)
    expected = bundle.pin(consumer)
    if any(metadata.get(field) != expected[field] for field in PIN_FIELDS):
        raise PromptContractError("prompt_pin_mismatch")
    return bundle


def validate_active_prompt_bundles() -> None:
    resolve_active_bundle("report.full")
    resolve_active_bundle("chat.free")


def input_hash(value: object) -> str:
    return canonical_hash(value)


def finalize_generation_metadata(
    pin: Mapping[str, object],
    *,
    provider: str | None,
    model: str | None,
    generation_source: str,
    structured_input_hash: str | None = None,
    context_input_hash: str | None = None,
    components: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if generation_source not in {"provider", "fallback"}:
        raise ValueError("generation_source_invalid")
    metadata = dict(pin)
    metadata.update(
        {
            "provider": provider,
            "model": model,
            "generation_source": generation_source,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    if structured_input_hash is not None:
        metadata["structured_input_hash"] = structured_input_hash
    if context_input_hash is not None:
        metadata["context_input_hash"] = context_input_hash
    if components is not None:
        metadata["components"] = dict(components)
    return metadata
