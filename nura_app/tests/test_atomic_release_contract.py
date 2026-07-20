from __future__ import annotations

import argparse
import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
BUILDER_PATH = SCRIPTS / "build_release_artifact.py"
TRANSITION_PATH = SCRIPTS / "prepare_atomic_release_host.py"
DEPLOY_SCRIPT = REPO_ROOT / "deploy.sh"


def _load_module(name: str, path: Path) -> ModuleType:
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


builder = _load_module("build_release_artifact", BUILDER_PATH)
transition = _load_module("prepare_atomic_release_host", TRANSITION_PATH)
static_contract = sys.modules["deploy_static_release"]


def _run(*args: str, cwd: Path) -> str:
    result = subprocess.run(args, cwd=cwd, check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _write(path: Path, content: str = "fixture\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _create_repo(path: Path) -> str:
    _run("git", "init", "--initial-branch=main", str(path), cwd=path.parent)
    _run("git", "config", "core.autocrlf", "false", cwd=path)
    _run("git", "config", "user.email", "fixture@example.invalid", cwd=path)
    _run("git", "config", "user.name", "Fixture", cwd=path)
    for source, _destination in static_contract.EXPLICIT_MAPPINGS:
        _write(path / source, f"{source}\n")
    for source_prefix, _destination_prefix in static_contract.DIRECTORY_MAPPINGS:
        suffix = "index.html" if source_prefix.endswith("/app") else "fixture.dat"
        _write(path / source_prefix / suffix, f"{source_prefix}\n")
    _run("git", "add", "--all", cwd=path)
    _run("git", "commit", "-m", "fixture", cwd=path)
    return _run("git", "rev-parse", "HEAD", cwd=path)


@pytest.fixture
def artifact_fixture(tmp_path: Path) -> tuple[Path, str, Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = _create_repo(repo)
    output = tmp_path / "artifact"
    archive, checksum, manifest = builder.build_artifact(repo, target, output)
    return repo, target, archive, checksum, manifest


def test_deterministic_build_twice_is_byte_identical(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = _create_repo(repo)
    first = builder.build_artifact(repo, target, tmp_path / "a")
    second = builder.build_artifact(repo, target, tmp_path / "b")
    assert [path.read_bytes() for path in first] == [path.read_bytes() for path in second]


def test_artifact_includes_vk_version_and_ordered_manifest(
    artifact_fixture: tuple[Path, str, Path, Path, Path],
) -> None:
    _repo, target, archive, checksum, manifest_path = artifact_fixture
    manifest, payload = builder.inspect_artifact(archive, checksum, manifest_path, target)
    assert "public/vk-callback.html" in payload
    assert payload["public/VERSION"].decode().split()[0] == target
    assert manifest["files"] == sorted(manifest["files"], key=lambda item: item["destination"])
    assert manifest["aggregate_manifest_sha256"] == builder.sha256_bytes(
        builder._canonical_json(manifest["files"])
    )


def _rewrite_archive(
    archive: Path,
    checksum: Path,
    mutate: object,
) -> None:
    with tarfile.open(archive, "r:gz") as source:
        members: list[tuple[tarfile.TarInfo, bytes | None]] = []
        for member in source.getmembers():
            stream = source.extractfile(member) if member.isfile() else None
            members.append((copy.copy(member), stream.read() if stream else None))
    mutate(members)  # type: ignore[operator]
    with tarfile.open(archive, "w:gz") as destination:
        for member, data in members:
            destination.addfile(member, io.BytesIO(data) if data is not None else None)
    checksum.write_text(f"{builder.sha256_file(archive)}  {archive.name}\n", encoding="ascii")


@pytest.mark.parametrize(
    ("name", "member_type"),
    [
        ("../escape", tarfile.REGTYPE),
        ("public/link", tarfile.SYMTYPE),
        ("public/hard", tarfile.LNKTYPE),
        ("public/device", tarfile.CHRTYPE),
        ("public/fifo", tarfile.FIFOTYPE),
    ],
)
def test_artifact_rejects_traversal_links_and_special_members(
    artifact_fixture: tuple[Path, str, Path, Path, Path], name: str, member_type: bytes
) -> None:
    _repo, target, archive, checksum, manifest = artifact_fixture

    def mutate(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> None:
        info = tarfile.TarInfo(name)
        info.type = member_type
        info.size = 0
        info.linkname = "public/index.html"
        members.append((info, b"" if member_type == tarfile.REGTYPE else None))

    _rewrite_archive(archive, checksum, mutate)
    with pytest.raises(builder.ArtifactContractError, match="unsafe|unexpected"):
        builder.inspect_artifact(archive, checksum, manifest, target)


def test_archive_checksum_mismatch_fails(
    artifact_fixture: tuple[Path, str, Path, Path, Path],
) -> None:
    _repo, target, archive, checksum, manifest = artifact_fixture
    archive.write_bytes(archive.read_bytes() + b"corrupt")
    with pytest.raises(builder.ArtifactContractError, match="checksum mismatch"):
        builder.inspect_artifact(archive, checksum, manifest, target)


@pytest.mark.parametrize("mutation", ["count", "aggregate", "target", "embedded"])
def test_manifest_mismatch_variants_fail(
    artifact_fixture: tuple[Path, str, Path, Path, Path], mutation: str
) -> None:
    _repo, target, archive, checksum, manifest_path = artifact_fixture
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation == "count":
        manifest["file_count"] += 1
    elif mutation == "aggregate":
        manifest["aggregate_manifest_sha256"] = "0" * 64
    elif mutation == "target":
        manifest["target_sha"] = "0" * 40
    else:
        manifest["commit_timestamp"] = "1970-01-01T00:00:00Z"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(builder.ArtifactContractError):
        builder.inspect_artifact(archive, checksum, manifest_path, target)


@pytest.mark.parametrize("mode", ["missing", "unexpected", "hash"])
def test_artifact_inventory_and_hash_failures_are_rejected(
    artifact_fixture: tuple[Path, str, Path, Path, Path], mode: str
) -> None:
    _repo, target, archive, checksum, manifest = artifact_fixture

    def mutate(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> None:
        if mode == "missing":
            members[:] = [item for item in members if item[0].name != "public/index.html"]
        elif mode == "unexpected":
            info = tarfile.TarInfo("public/stale.txt")
            info.size = 5
            members.append((info, b"stale"))
        else:
            for index, (info, data) in enumerate(members):
                if info.name == "public/index.html":
                    info.size = 7
                    members[index] = (info, b"changed")
                    break

    _rewrite_archive(archive, checksum, mutate)
    with pytest.raises(builder.ArtifactContractError, match="inventory|unexpected|hash/size"):
        builder.inspect_artifact(archive, checksum, manifest, target)


def test_extract_uses_unique_path_and_exact_hashes(
    artifact_fixture: tuple[Path, str, Path, Path, Path], tmp_path: Path
) -> None:
    _repo, target, archive, checksum, manifest_path = artifact_fixture
    staging = tmp_path / "staging" / f"{target}-run-1"
    manifest = builder.extract_artifact(archive, checksum, manifest_path, staging, target)
    builder.verify_release_directory(staging, manifest)
    with pytest.raises(builder.ArtifactContractError, match="already exists"):
        builder.extract_artifact(archive, checksum, manifest_path, staging, target)


def test_finalize_renames_staging_and_reuses_only_exact_release(
    artifact_fixture: tuple[Path, str, Path, Path, Path], tmp_path: Path
) -> None:
    _repo, target, archive, checksum, manifest_path = artifact_fixture
    releases = tmp_path / "release-root" / "releases"
    staging = tmp_path / "release-root" / "staging" / "one"
    builder.extract_artifact(archive, checksum, manifest_path, staging, target)
    final = builder.finalize_release(staging, releases, target)
    assert final == releases / target and final.is_dir() and not staging.exists()
    second = tmp_path / "release-root" / "staging" / "two"
    builder.extract_artifact(archive, checksum, manifest_path, second, target)
    assert builder.finalize_release(second, releases, target) == final
    assert not second.exists()


def test_existing_mismatched_release_fails(
    artifact_fixture: tuple[Path, str, Path, Path, Path], tmp_path: Path
) -> None:
    _repo, target, archive, checksum, manifest_path = artifact_fixture
    releases = tmp_path / "release-root" / "releases"
    first = tmp_path / "release-root" / "staging" / "one"
    builder.extract_artifact(archive, checksum, manifest_path, first, target)
    final = builder.finalize_release(first, releases, target)
    (final / "public" / "index.html").write_text("changed", encoding="utf-8")
    second = tmp_path / "release-root" / "staging" / "two"
    builder.extract_artifact(archive, checksum, manifest_path, second, target)
    with pytest.raises(builder.ArtifactContractError, match="hash/size|does not match"):
        builder.finalize_release(second, releases, target)


def test_same_filesystem_gate_rejects_cross_device(
    artifact_fixture: tuple[Path, str, Path, Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo, target, archive, checksum, manifest_path = artifact_fixture
    releases = tmp_path / "release-root" / "releases"
    staging = tmp_path / "release-root" / "staging" / "one"
    builder.extract_artifact(archive, checksum, manifest_path, staging, target)
    original = Path.stat

    def fake_stat(path: Path, *args: object, **kwargs: object) -> os.stat_result:
        value = original(path, *args, **kwargs)
        if path == staging:
            fields = list(value)
            fields[2] += 1
            return os.stat_result(fields)
        return value

    monkeypatch.setattr(Path, "stat", fake_stat)
    with pytest.raises(builder.ArtifactContractError, match="same filesystem"):
        builder.finalize_release(staging, releases, target)


def test_atomic_current_switch_and_target_validation(
    artifact_fixture: tuple[Path, str, Path, Path, Path], tmp_path: Path
) -> None:
    _repo, target, archive, checksum, manifest_path = artifact_fixture
    release_root = tmp_path / "root"
    staging = release_root / "staging" / "one"
    builder.extract_artifact(archive, checksum, manifest_path, staging, target)
    final = builder.finalize_release(staging, release_root / "releases", target)
    current = release_root / "current"
    try:
        builder.atomic_switch(current, final)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    assert current.is_symlink()
    assert builder.validate_current(current, target) == final.resolve()
    with pytest.raises(builder.ArtifactContractError, match="SHA mismatch"):
        builder.validate_current(current, "0" * 40)
    assert not list(release_root.glob(".current.*.tmp"))


@pytest.mark.parametrize(("free", "inodes", "message"), [(10, 10000, "disk"), (10**12, 1, "inode")])
def test_disk_and_inode_gates_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    free: int,
    inodes: int,
    message: str,
) -> None:
    monkeypatch.setattr(builder.shutil, "disk_usage", lambda _path: SimpleNamespace(free=free))
    monkeypatch.setattr(
        builder.os,
        "statvfs",
        lambda _path: SimpleNamespace(f_favail=inodes),
        raising=False,
    )
    with pytest.raises(builder.ArtifactContractError, match=message):
        builder.disk_inode_gate(tmp_path, 100, 100, 100, 100, 100)


def test_state_write_is_atomic_and_private(tmp_path: Path) -> None:
    path = tmp_path / "state" / "current.json"
    builder.atomic_write_json(path, {"sha": "0" * 40, "status": "successful"})
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "successful"
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize(
    "required_text",
    [
        "current release state is missing",
        "rollback target is not a protected successful release",
        "rollback target is not one of two protected predecessors",
        "schema-incompatible release cannot be rolled back automatically",
        "rollback tag no longer identifies the recorded immutable image",
        "release directory inventory mismatch",
    ],
)
def test_rollback_failure_contracts_are_explicit(required_text: str) -> None:
    contract = DEPLOY_SCRIPT.read_text(encoding="utf-8") + BUILDER_PATH.read_text(encoding="utf-8")
    assert required_text in contract


def test_static_failure_compensation_precedes_application_rollback() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    cleanup = script[script.index("cleanup()") : script.index("trap cleanup EXIT")]
    assert cleanup.index("STATIC_SWITCHED") < cleanup.index("APP_MUTATED")
    assert "write_state failed" in cleanup
    assert "SUCCESS -ne 1" in cleanup


def _transition_args(tmp_path: Path) -> argparse.Namespace:
    web = tmp_path / "web"
    enabled = tmp_path / "sites-enabled"
    available = tmp_path / "sites-available"
    repo = tmp_path / "repo"
    for path in (web, enabled, available, repo):
        path.mkdir()
    _write(web / "VERSION", f"{transition.EXPECTED_LEGACY_SHA} legacy\n")
    _write(web / "index.html", "legacy\n")
    for name in transition.ENABLED_CONFIG_ALLOWLIST:
        _write(enabled / name, f"# {name}\n")
    return argparse.Namespace(
        apply=False,
        expected_production_sha=None,
        target_sha=None,
        acknowledge_production_change=False,
        repo_root=repo,
        legacy_web_root=web,
        release_root=tmp_path / "release",
        state_root=tmp_path / "state",
        backup_root=tmp_path / "backup",
        sites_enabled=enabled,
        sites_available=available,
        lock_file=tmp_path / "lock" / "deploy.lock",
        output=None,
    )


def test_transition_dry_run_is_mutation_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    args = _transition_args(tmp_path)
    monkeypatch.setattr(
        transition,
        "_service_map",
        lambda _repo: {
            service: {"container_id": f"container-{service}", "image_id": f"sha256:{'0' * 64}"}
            for service in transition.APPLICATION_SERVICES
        },
    )
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    inventory = transition.collect_inventory(args)
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert before == after
    assert inventory["file_count"] == 2
    assert len(inventory["services"]) == 5
    assert not args.release_root.exists() and not args.backup_root.exists()


@pytest.mark.parametrize(
    ("sha", "ack", "message"),
    [("0" * 40, True, "audited legacy SHA"), (transition.EXPECTED_LEGACY_SHA, False, "acknowledge")],
)
def test_transition_apply_requires_exact_acknowledgements(
    tmp_path: Path, sha: str, ack: bool, message: str
) -> None:
    args = _transition_args(tmp_path)
    args.apply = True
    args.expected_production_sha = sha
    args.acknowledge_production_change = ack
    inventory = {"production_version": transition.EXPECTED_LEGACY_SHA}
    with pytest.raises(transition.TransitionError, match=message):
        transition.apply_transition(args, inventory)
    assert not args.release_root.exists()


def test_transition_rejects_wrong_legacy_version(tmp_path: Path) -> None:
    args = _transition_args(tmp_path)
    _write(args.legacy_web_root / "VERSION", f"{'0' * 40} wrong\n")
    assert transition._read_version(args.legacy_web_root) == "0" * 40
    args.apply = True
    args.expected_production_sha = transition.EXPECTED_LEGACY_SHA
    args.acknowledge_production_change = True
    with pytest.raises(transition.TransitionError, match="production VERSION"):
        transition.apply_transition(args, {"production_version": "0" * 40})


def test_transition_enabled_config_names_are_strict_allowlist(tmp_path: Path) -> None:
    args = _transition_args(tmp_path)
    _write(args.sites_enabled / "unexpected.conf", "server {}\n")
    with pytest.raises(transition.TransitionError, match="strict allowlist"):
        transition._enabled_configs(args.sites_enabled)


def test_transition_requires_exact_tracked_nginx_target(tmp_path: Path) -> None:
    args = _transition_args(tmp_path)
    _run("git", "init", "--initial-branch=main", str(args.repo_root), cwd=tmp_path)
    _run("git", "config", "core.autocrlf", "false", cwd=args.repo_root)
    _run("git", "config", "user.email", "fixture@example.invalid", cwd=args.repo_root)
    _run("git", "config", "user.name", "Fixture", cwd=args.repo_root)
    source = args.repo_root / "nura_app/nginx/nura-ai.ru.conf"
    _write(source, "server { root /var/www/nura-releases/current/public; }\n")
    _run("git", "add", "nura_app/nginx/nura-ai.ru.conf", cwd=args.repo_root)
    _run("git", "commit", "-m", "nginx", cwd=args.repo_root)
    args.target_sha = _run("git", "rev-parse", "HEAD", cwd=args.repo_root)
    reviewed = transition._reviewed_nginx_bytes(args)
    assert reviewed == source.read_bytes()
    _write(source, "server { root /var/www/nura-ai.ru; }\n")
    assert b"/var/www/nura-releases/current/public" in reviewed
    with pytest.raises(transition.TransitionError, match="checkout must be clean"):
        transition._reviewed_nginx_bytes(args)


def test_forensic_snapshot_records_inventory_and_three_configs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = _transition_args(tmp_path)
    monkeypatch.setattr(transition, "_service_map", lambda _repo: {})
    inventory = transition.collect_inventory(args)
    destination = tmp_path / "snapshot"
    destination.mkdir()
    transition._snapshot(args, inventory, destination)
    assert (destination / "legacy-web-root.tar.gz").is_file()
    assert (destination / "legacy-web-root.tar.gz.sha256").is_file()
    assert json.loads((destination / "legacy-inventory.json").read_text(encoding="utf-8"))[
        "inventory_sha256"
    ]
    assert {path.name for path in (destination / "sites-enabled").iterdir()} == set(
        transition.ENABLED_CONFIG_ALLOWLIST
    )


def test_transition_has_five_legacy_mappings_vk_and_no_wildcard_deletion() -> None:
    source = TRANSITION_PATH.read_text(encoding="utf-8")
    assert 'APPLICATION_SERVICES = ("api", "bot", "celery-worker", "celery-beat", "admin-bot")' in source
    assert "vk-callback" in (REPO_ROOT / "scripts" / "deploy_static_release.py").read_text(
        encoding="utf-8"
    )
    assert "sites_enabled.glob(" not in source
    assert "rmtree(args.legacy_web_root" not in source
    assert "ENABLED_CONFIG_ALLOWLIST" in source
    assert "_restore_enabled_configs" in source
    assert "_restore_canonical_config" in source
    assert "installed canonical Nginx config does not match target bytes" in source
    assert source.index('_run("nginx", "-t")') < source.index('_run("systemctl", "reload", "nginx")')


def test_retention_protects_current_two_previous_and_legacy_records() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    retention = script[script.index("retention cleanup is best-effort") :]
    assert "for _ in range(2)" in retention
    assert 'path.name in protected' in retention
    assert 'value.get("legacy")' in retention
    assert "7*86400" in retention
    assert "failed[2:]" in retention
    assert "30*86400" in retention
    assert "docker system prune" not in script
    assert "docker image prune" not in script
    assert "WARNING: retention cleanup failed" in script


def test_same_sha_cycles_mutable_tags_and_incomplete_compensation_fail_closed() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "refusing to create a self-referential release lineage" in script
    assert script.count("release state lineage contains a cycle") == 2
    assert "per_service_image_ids" in script
    assert "rollback tag no longer identifies the recorded immutable image" in script
    assert "current rollback tag does not match its recorded immutable image ID" in script
    cleanup = script[script.index("cleanup()") : script.index("trap cleanup EXIT")]
    assert 'validate-current --current "$CURRENT_LINK" --expected-sha "$CURRENT_SHA"' in cleanup
    assert 'public_smoke "$CURRENT_SHA"' in cleanup
    assert "write_recovery_required" in cleanup
    assert "operator recovery is required" in cleanup


def test_incoming_cleanup_is_bounded_and_checks_separate_filesystem() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "archive is outside a direct unique incoming directory" in script
    assert "checksum is outside the validated incoming directory" in script
    assert "manifest is outside the validated incoming directory" in script
    assert 'incoming.resolve(strict=True).parent != root' in script
    assert 'sys.argv[3]=="1"' in script
    assert "failed[2:]" in script
    assert 'stat -c %d "$INCOMING_ROOT"' in script
