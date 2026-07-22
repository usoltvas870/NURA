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


def test_transition_builds_real_audited_legacy_artifact(tmp_path: Path) -> None:
    archive, checksum, manifest_path = transition._build_legacy_artifact(
        REPO_ROOT,
        tmp_path / "legacy-artifact",
    )

    manifest, payload = builder.inspect_artifact(
        archive,
        checksum,
        manifest_path,
        transition.EXPECTED_LEGACY_SHA,
    )

    assert manifest["target_sha"] == transition.EXPECTED_LEGACY_SHA
    assert "public/index.html" in payload
    assert "public/vk-callback.html" in payload
    assert "public/success.html" in payload
    assert "public/app/index.html" in payload
    assert "public/app/AGENTS.md" in payload
    assert "public/pwa-release.json" not in payload
    assert set(transition.PUBLIC_ALIASES.values()) <= set(payload)
    assert all(not name.startswith("public/assets/") for name in payload)


def test_legacy_source_profile_rejects_every_other_sha(
    artifact_fixture: tuple[Path, str, Path, Path, Path],
) -> None:
    repo, target, _archive, _checksum, _manifest = artifact_fixture

    with pytest.raises(
        static_contract.DeploymentContractError,
        match="exact audited legacy SHA",
    ):
        static_contract.build_manifest(repo, target, source_profile="legacy-d0")


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
        "rollback target is outside current activation_history",
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
    (web / "VERSION").write_bytes(
        f"{transition.EXPECTED_LEGACY_SHA} - 2026-07-18T09:06:46Z\n".encode("ascii")
    )
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
        base_url="https://nura-ai.ru",
        output=None,
        drop_candidate_output=None,
        approved_drop_manifest=None,
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
    canonical = [
        {"path": "index.html", "size": 7, "sha256": transition._sha256(web_file)}
        for web_file in [args.legacy_web_root / "index.html"]
    ]
    canonical.append(
        {
            "path": "VERSION",
            "size": (args.legacy_web_root / "VERSION").stat().st_size,
            "sha256": transition._sha256(args.legacy_web_root / "VERSION"),
        }
    )
    inventory = transition.collect_inventory(args, canonical)
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
    with pytest.raises(transition.TransitionError, match="strict legacy contract"):
        transition._read_version(args.legacy_web_root)
    args.apply = True
    args.expected_production_sha = transition.EXPECTED_LEGACY_SHA
    args.acknowledge_production_change = True
    with pytest.raises(transition.TransitionError, match="production VERSION"):
        transition.apply_transition(args, {"production_version": "0" * 40})


def test_transition_enabled_config_names_are_strict_allowlist(tmp_path: Path) -> None:
    args = _transition_args(tmp_path)
    _write(args.sites_enabled / "unexpected.conf", "server {}\n")
    with pytest.raises(transition.TransitionError, match="strict"):
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
    canonical = [
        {
            "path": path.name,
            "size": path.stat().st_size,
            "sha256": transition._sha256(path),
        }
        for path in (args.legacy_web_root / "index.html", args.legacy_web_root / "VERSION")
    ]
    inventory = transition.collect_inventory(args, canonical)
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


def _public_release_fixture(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    release = tmp_path / "release"
    payloads = {
        "public/index.html": b"index\n",
        "public/VERSION": f"{transition.EXPECTED_LEGACY_SHA} 2026-07-18T09:05:39Z\n".encode(),
        "public/vk-callback.html": b"vk\n",
        "public/mini.html": b"mini\n",
        "public/success.html": b"success\n",
        "public/admin/index.html": b"admin\n",
        "public/app/index.html": b"app\n",
    }
    files = []
    for destination, body in payloads.items():
        path = release / destination
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        files.append(
            {
                "destination": destination,
                "size": len(body),
                "sha256": __import__("hashlib").sha256(body).hexdigest(),
            }
        )
    manifest = {"files": sorted(files, key=lambda item: item["destination"])}
    (release / "public/release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return release, payloads


def _public_fetcher(payloads: dict[str, bytes], *, corrupt: str | None = None, redirect_ok: bool = True):
    aliases = {endpoint: payloads[destination] for endpoint, destination in transition.PUBLIC_ALIASES.items()}
    direct = {f"/{name.removeprefix('public/')}": body for name, body in payloads.items()}
    direct.pop("/success.html")

    def fetch(url: str) -> transition.FetchResult:
        if url in transition.REDIRECT_CONTRACTS:
            location = transition.REDIRECT_CONTRACTS[url] if redirect_ok else "https://wrong.invalid/"
            return transition.FetchResult(301, b"", location)
        endpoint = url.removeprefix("https://nura-ai.ru")
        if endpoint == "/health":
            return transition.FetchResult(200, b"ok")
        body = aliases.get(endpoint, direct.get(endpoint, b""))
        if endpoint == corrupt:
            body += b"corrupt"
        return transition.FetchResult(200 if body else 404, body)

    return fetch


def test_transition_public_equivalence_accepts_exact_manifest_aliases_and_redirects(
    tmp_path: Path,
) -> None:
    release, payloads = _public_release_fixture(tmp_path)
    evidence = transition.verify_public_equivalence(release, fetcher=_public_fetcher(payloads))
    assert evidence["/VERSION"]
    assert set(transition.REDIRECT_CONTRACTS) <= set(evidence)


@pytest.mark.parametrize("endpoint", ["/index.html", "/VERSION", "/vk-callback.html", "/app/"])
def test_transition_public_equivalence_rejects_wrong_bytes(tmp_path: Path, endpoint: str) -> None:
    release, payloads = _public_release_fixture(tmp_path)
    with pytest.raises(transition.TransitionError, match="equivalence"):
        transition.verify_public_equivalence(
            release,
            fetcher=_public_fetcher(payloads, corrupt=endpoint),
        )


def test_transition_public_equivalence_rejects_redirect_drift(tmp_path: Path) -> None:
    release, payloads = _public_release_fixture(tmp_path)
    with pytest.raises(transition.TransitionError, match="canonical redirect"):
        transition.verify_public_equivalence(
            release,
            fetcher=_public_fetcher(payloads, redirect_ok=False),
        )


@pytest.mark.parametrize(
    "version_bytes",
    [
        f"{transition.EXPECTED_LEGACY_SHA} 2026-07-18T09:05:39Z\n".encode(),
        f"{'0' * 40} - 2026-07-18T09:06:46Z\n".encode(),
        f"{transition.EXPECTED_LEGACY_SHA}-2026-07-18T09:06:46Z\n".encode(),
        f"{transition.EXPECTED_LEGACY_SHA} - 2026-02-30T09:06:46Z\n".encode(),
        f"{transition.EXPECTED_LEGACY_SHA} - 2026-07-18T09:06:46Z\nextra\n".encode(),
    ],
)
def test_legacy_version_contract_rejects_non_legacy_or_malformed_bytes(version_bytes: bytes) -> None:
    with pytest.raises(transition.TransitionError):
        transition._legacy_version_evidence_from_bytes(version_bytes)


def test_legacy_version_contract_records_exact_old_format() -> None:
    version_bytes = f"{transition.EXPECTED_LEGACY_SHA} - 2026-07-18T09:06:46Z\n".encode()
    evidence = transition._legacy_version_evidence_from_bytes(version_bytes)
    assert evidence == {
        "size": len(version_bytes),
        "sha256": __import__("hashlib").sha256(version_bytes).hexdigest(),
        "parsed_sha": transition.EXPECTED_LEGACY_SHA,
        "deployment_timestamp": "2026-07-18T09:06:46Z",
    }


def test_legacy_public_baseline_accepts_old_version_but_post_switch_requires_deterministic_version(
    tmp_path: Path,
) -> None:
    release, payloads = _public_release_fixture(tmp_path)
    legacy_version = f"{transition.EXPECTED_LEGACY_SHA} - 2026-07-18T09:06:46Z\n".encode()
    legacy_evidence = transition._legacy_version_evidence_from_bytes(legacy_version)
    live_payloads = {**payloads, "public/VERSION": legacy_version}
    baseline = transition.verify_legacy_public_baseline(
        release,
        legacy_version,
        legacy_evidence,
        fetcher=_public_fetcher(live_payloads),
    )
    assert baseline["/VERSION"] == legacy_evidence["sha256"]
    with pytest.raises(transition.TransitionError, match="equivalence"):
        transition.verify_public_equivalence(release, fetcher=_public_fetcher(live_payloads))
    transition.verify_public_equivalence(release, fetcher=_public_fetcher(payloads))


def test_legacy_public_baseline_rejects_changed_old_version_or_non_version_file(tmp_path: Path) -> None:
    release, payloads = _public_release_fixture(tmp_path)
    legacy_version = f"{transition.EXPECTED_LEGACY_SHA} - 2026-07-18T09:06:46Z\n".encode()
    evidence = transition._legacy_version_evidence_from_bytes(legacy_version)
    live_payloads = {**payloads, "public/VERSION": legacy_version}
    with pytest.raises(transition.TransitionError, match="equivalence"):
        transition.verify_legacy_public_baseline(
            release,
            legacy_version,
            evidence,
            fetcher=_public_fetcher({**live_payloads, "public/index.html": b"changed\n"}),
        )
    with pytest.raises(transition.TransitionError, match="equivalence"):
        transition.verify_legacy_public_baseline(
            release,
            legacy_version,
            evidence,
            fetcher=_public_fetcher({**live_payloads, "public/VERSION": b"different\n"}),
        )


def test_legacy_public_baseline_records_raw_version_and_forensic_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, payloads = _public_release_fixture(tmp_path)
    legacy_version = f"{transition.EXPECTED_LEGACY_SHA} - 2026-07-18T09:06:46Z\n".encode()
    evidence = transition._legacy_version_evidence_from_bytes(legacy_version)
    monkeypatch.setattr(transition, "datetime_utc", lambda: "2026-07-20T00:00:00Z")
    baseline = transition._write_legacy_public_baseline(
        tmp_path / "forensics",
        release,
        legacy_version,
        evidence,
        base_url="https://nura-ai.ru",
        fetcher=_public_fetcher({**payloads, "public/VERSION": legacy_version}),
    )
    saved = json.loads((tmp_path / "forensics/legacy-public-baseline.json").read_text(encoding="utf-8"))
    assert saved == baseline
    assert saved["legacy_version"] == evidence
    assert saved["expected_legacy_sha"] == transition.EXPECTED_LEGACY_SHA
    assert (tmp_path / "forensics/legacy-VERSION").read_bytes() == legacy_version
    loaded_bytes, loaded_evidence = transition._load_legacy_public_baseline(tmp_path / "forensics", release)
    assert loaded_bytes == legacy_version and loaded_evidence == evidence


def test_transition_rejects_legacy_public_file_absent_from_release(tmp_path: Path) -> None:
    _release, payloads = _public_release_fixture(tmp_path)
    canonical = [{"path": name.removeprefix("public/")} for name in payloads]
    legacy = [*canonical, {"path": "stale-public-file.txt"}]
    assert transition._legacy_extras(legacy, canonical) == [{"path": "stale-public-file.txt"}]


def test_transition_allows_only_explicit_acme_inventory_exclusion(tmp_path: Path) -> None:
    _release, payloads = _public_release_fixture(tmp_path)
    canonical = [{"path": name.removeprefix("public/")} for name in payloads]
    legacy = [*canonical, {"path": ".well-known/acme-challenge/token"}]
    assert transition._legacy_extras(legacy, canonical) == []


def test_transition_recovery_marker_is_exclusive(tmp_path: Path) -> None:
    marker = transition._write_recovery_marker(tmp_path, "restore verification failed")
    assert json.loads(marker.read_text(encoding="utf-8"))["status"] == "recovery_required"
    with pytest.raises(transition.TransitionError, match="refusing overwrite"):
        transition._write_recovery_marker(tmp_path, "second failure")


def _extra_inventory() -> dict[str, object]:
    extra = {
        "path": "historical.txt",
        "size": 11,
        "sha256": "a" * 64,
        "mode": "0o644",
        "uid": 1000,
        "gid": 1000,
    }
    return {
        "inventory_sha256": "b" * 64,
        "legacy_extra_files": [extra],
        "legacy_extra_inventory_sha256": transition._inventory_digest([extra]),
    }


def test_drop_candidate_is_deterministic_and_owner_review_required() -> None:
    inventory = _extra_inventory()
    first = transition._canonical_json(transition._drop_candidate(inventory))
    second = transition._canonical_json(transition._drop_candidate(copy.deepcopy(inventory)))
    assert first == second
    assert json.loads(first)["status"] == "owner_review_required"


def test_missing_or_unapproved_drop_manifest_blocks_extras(tmp_path: Path) -> None:
    inventory = _extra_inventory()
    with pytest.raises(transition.TransitionError, match="require"):
        transition._verify_approved_drop_manifest(None, inventory)
    candidate = tmp_path / "candidate.json"
    candidate.write_bytes(transition._canonical_json(transition._drop_candidate(inventory)))
    with pytest.raises(transition.TransitionError, match="exactly match"):
        transition._verify_approved_drop_manifest(candidate, inventory)


def test_zero_extra_inventory_requires_no_approval() -> None:
    inventory = {
        "inventory_sha256": "b" * 64,
        "legacy_extra_files": [],
        "legacy_extra_inventory_sha256": transition._inventory_digest([]),
    }
    assert transition._verify_approved_drop_manifest(None, inventory) is None


def test_exact_approved_drop_manifest_passes_and_is_copied_to_evidence(tmp_path: Path) -> None:
    inventory = _extra_inventory()
    approved = transition._drop_candidate(inventory, status="approved")
    path = tmp_path / "approved.json"
    path.write_bytes(transition._canonical_json(approved) + b"\n")
    assert transition._verify_approved_drop_manifest(path, inventory) == approved
    args = SimpleNamespace(approved_drop_manifest=path)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    transition._copy_approved_drop_evidence(args, inventory, evidence)
    assert json.loads((evidence / "approved-drop-manifest.json").read_text()) == approved


@pytest.mark.parametrize("field", ["path", "size", "sha256"])
def test_approved_drop_manifest_exact_identity_mismatch_blocks(tmp_path: Path, field: str) -> None:
    inventory = _extra_inventory()
    approved = transition._drop_candidate(inventory, status="approved")
    approved["legacy_extra_files"][0][field] = "changed" if field != "size" else 12
    path = tmp_path / "approved.json"
    path.write_bytes(transition._canonical_json(approved))
    with pytest.raises(transition.TransitionError, match="exactly match"):
        transition._verify_approved_drop_manifest(path, inventory)


def test_newly_appeared_extra_invalidates_approved_manifest(tmp_path: Path) -> None:
    original = _extra_inventory()
    path = tmp_path / "approved.json"
    path.write_bytes(
        transition._canonical_json(transition._drop_candidate(original, status="approved"))
    )
    changed = copy.deepcopy(original)
    changed["legacy_extra_files"].append(
        {"path": "new.txt", "size": 1, "sha256": "c" * 64, "mode": "0o644", "uid": 0, "gid": 0}
    )
    changed["legacy_extra_inventory_sha256"] = transition._inventory_digest(
        changed["legacy_extra_files"]
    )
    with pytest.raises(transition.TransitionError, match="exactly match"):
        transition._verify_approved_drop_manifest(path, changed)


def test_legacy_extra_change_after_approval_is_detected(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    _write(root / "historical.txt", "before\n")
    approved_inventory = transition._public_inventory(root)
    _write(root / "historical.txt", "after\n")
    with pytest.raises(transition.TransitionError, match="changed after approval"):
        transition._assert_legacy_inventory_unchanged(root, approved_inventory)


def test_apply_rebuilds_authoritative_inventory_under_common_lock() -> None:
    source = TRANSITION_PATH.read_text(encoding="utf-8")
    apply_source = source[source.index("def apply_transition") : source.index("def datetime_utc")]
    lock = apply_source.index("fcntl.flock")
    locked_inventory = apply_source.index("locked_inventory = collect_inventory(args)")
    snapshot = apply_source.index("_snapshot(args, inventory, transition_dir)")
    approval = apply_source.index("_copy_approved_drop_evidence")
    mutation = apply_source.index("candidate.write_bytes")
    assert lock < locked_inventory < snapshot < approval < mutation
    assert apply_source.count("_assert_legacy_inventory_unchanged") == 2


def test_current_history_and_previous_pointer_are_validated_before_any_mutation() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    preflight = script.index("current activation_history is invalid")
    pointer = script.index("previous state pointer does not match activation_history[0]")
    fetch = script.index('git -C "$REPO_ROOT" fetch')
    rollback = script.index('if [[ "$COMMAND" == rollback ]]')
    build = script.index("docker build")
    assert preflight < fetch < rollback
    assert pointer < fetch < build


def test_dry_run_inventory_reports_exact_extras_and_excludes_acme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    args = _transition_args(tmp_path)
    extra = args.legacy_web_root / "historical.txt"
    acme = args.legacy_web_root / ".well-known/acme-challenge/token"
    _write(extra, "historical\n")
    _write(acme, "token\n")
    monkeypatch.setattr(transition, "_service_map", lambda _repo: {})
    canonical = [
        {"path": path.name, "size": path.stat().st_size, "sha256": transition._sha256(path)}
        for path in (args.legacy_web_root / "index.html", args.legacy_web_root / "VERSION")
    ]
    inventory = transition.collect_inventory(args, canonical)
    assert inventory["legacy_extra_file_count"] == 1
    assert inventory["legacy_extra_files"][0]["path"] == "historical.txt"
    assert inventory["acme_excluded_file_count"] == 1


def test_existing_legacy_release_is_verified_and_reused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    args = _transition_args(tmp_path)
    final = args.release_root / "releases" / transition.EXPECTED_LEGACY_SHA
    final.mkdir(parents=True)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    archive, checksum, manifest = (
        artifact / "a.tar.gz",
        artifact / "a.sha256",
        artifact / "release-manifest.json",
    )
    for path in (archive, checksum):
        path.write_bytes(b"fixture")
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(transition, "_build_legacy_artifact", lambda *_args: (archive, checksum, manifest))
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(transition, "_run", lambda *command, **_kwargs: calls.append(command) or "")
    prepared = transition._prepare_legacy_release(args, tmp_path / "evidence")
    assert prepared.final_path == final and prepared.staging_path is None
    assert any("verify_release_directory" in " ".join(call) for call in calls)


def test_existing_mismatched_legacy_release_requires_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    args = _transition_args(tmp_path)
    final = args.release_root / "releases" / transition.EXPECTED_LEGACY_SHA
    final.mkdir(parents=True)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    files = tuple(artifact / name for name in ("a.tar.gz", "a.sha256", "release-manifest.json"))
    for path in files:
        path.write_bytes(b"fixture")
    monkeypatch.setattr(transition, "_build_legacy_artifact", lambda *_args: files)
    monkeypatch.setattr(transition, "_run", lambda *_args, **_kwargs: (_ for _ in ()).throw(transition.TransitionError("mismatch")))
    with pytest.raises(transition.TransitionError, match="mismatch"):
        transition._prepare_legacy_release(args, tmp_path / "evidence")


def test_matching_legacy_tags_reuse_and_conflicting_tags_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    image_id = f"sha256:{'0' * 64}"
    services = {name: {"image_id": image_id} for name in transition.APPLICATION_SERVICES}
    monkeypatch.setattr(
        transition.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=f"{image_id}\n"),
    )
    assert len(transition._protect_legacy_images(services)) == 5
    monkeypatch.setattr(
        transition.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=f"sha256:{'1' * 64}\n"),
    )
    with pytest.raises(transition.TransitionError, match="conflict"):
        transition._protect_legacy_images(services)


def test_partial_current_state_disagreement_requires_recovery(tmp_path: Path) -> None:
    args = _transition_args(tmp_path)
    (args.state_root / "releases").mkdir(parents=True)
    (args.state_root / "current.json").write_text("{}", encoding="utf-8")
    final = args.release_root / "releases" / transition.EXPECTED_LEGACY_SHA
    final.mkdir(parents=True)
    prepared = transition.PreparedLegacyRelease(final, final, None, tmp_path / "a", tmp_path / "m")
    with pytest.raises(transition.TransitionError, match="partial"):
        transition._existing_transition_status(args, prepared, {}, {"services": {}}, b"")


def test_fully_prepared_host_returns_without_reload_or_rewrite(tmp_path: Path) -> None:
    args = _transition_args(tmp_path)
    final = args.release_root / "releases" / transition.EXPECTED_LEGACY_SHA
    (final / "public").mkdir(parents=True)
    manifest = final / "public/release-manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    archive = tmp_path / "legacy.tar.gz"
    archive.write_bytes(b"archive")
    current = args.release_root / "current"
    try:
        current.symlink_to(Path("releases") / transition.EXPECTED_LEGACY_SHA, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    reviewed = b"server { root /var/www/nura-releases/current/public; }\n"
    canonical = args.sites_available / "nura-ai.ru.conf"
    canonical.write_bytes(reviewed)
    for name in transition.ENABLED_CONFIG_ALLOWLIST:
        (args.sites_enabled / name).unlink()
    (args.sites_enabled / "nura-ai.ru.conf").symlink_to(canonical)
    image_id = f"sha256:{'0' * 64}"
    tags = {service: f"nura-legacy:{service}-{transition.EXPECTED_LEGACY_SHA[:12]}" for service in transition.APPLICATION_SERVICES}
    services = {service: {"image_id": image_id} for service in transition.APPLICATION_SERVICES}
    state = {
        "sha": transition.EXPECTED_LEGACY_SHA,
        "status": "successful",
        "legacy": True,
        "rollback_eligibility": True,
        "static_release_path": str(final),
        "artifact_sha256": transition._sha256(archive),
        "public_manifest_sha256": transition._sha256(manifest),
        "per_service_image_mapping": tags,
        "per_service_image_ids": {service: image_id for service in transition.APPLICATION_SERVICES},
        "migration_delta": False,
    }
    record = args.state_root / "releases" / f"{transition.EXPECTED_LEGACY_SHA}.json"
    record.parent.mkdir(parents=True)
    args.state_root.mkdir(exist_ok=True)
    record.write_text(json.dumps(state), encoding="utf-8")
    (args.state_root / "current.json").write_text(json.dumps(state), encoding="utf-8")
    prepared = transition.PreparedLegacyRelease(final, final, None, archive, manifest)
    assert transition._existing_transition_status(args, prepared, tags, {"services": services}, reviewed) == "already_prepared"


def test_transition_retry_contract_keeps_legacy_root_and_verified_final() -> None:
    source = TRANSITION_PATH.read_text(encoding="utf-8")
    apply_source = source[source.index("def apply_transition") : source.index("def datetime_utc")]
    assert "_remove_staging(prepared, args)" in source
    assert "_finalize_prepared_release" in source
    assert "already_prepared" in source
    assert "rmtree(args.legacy_web_root" not in source
    assert "unlink(args.legacy_web_root" not in source
    assert apply_source.index("_write_legacy_public_baseline(") < apply_source.index("_finalize_prepared_release")
    assert apply_source.index("_existing_transition_status") < apply_source.index("candidate.write_bytes")


def test_activation_history_sequences_are_bounded_and_cycle_free() -> None:
    a, b, c = "a" * 40, "b" * 40, "c" * 40
    state_a = {"sha": a}
    assert transition.next_activation_history(state_a, b) == [a]
    state_b = {"sha": b, "activation_history": [a]}
    assert transition.next_activation_history(state_b, c) == [b, a]
    state_c = {"sha": c, "activation_history": [b, a]}
    assert transition.next_activation_history(state_c, b) == [c, a]
    rolled_back_b = {"sha": b, "activation_history": [c, a]}
    assert transition.next_activation_history(rolled_back_b, c) == [b, a]


@pytest.mark.parametrize(
    "state",
    [
        {"sha": "a" * 40, "activation_history": ["b" * 40, "c" * 40, "d" * 40]},
        {"sha": "a" * 40, "activation_history": ["b" * 40, "b" * 40]},
        {"sha": "a" * 40, "activation_history": ["invalid"]},
        {"sha": "a" * 40, "activation_history": ["a" * 40]},
    ],
)
def test_invalid_activation_history_is_rejected(state: dict[str, object]) -> None:
    with pytest.raises(transition.TransitionError, match="activation_history"):
        transition.validate_activation_history(state)


def test_legacy_state_without_activation_history_is_supported() -> None:
    assert transition.validate_activation_history({"sha": "a" * 40}) == []


def test_retention_protects_current_two_previous_and_legacy_records() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    retention = script[script.index("retention cleanup is best-effort") :]
    assert 'protected={current["sha"],*history}' in retention
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
    assert "release state lineage contains a cycle" not in script
    assert "activation_history" in script
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
