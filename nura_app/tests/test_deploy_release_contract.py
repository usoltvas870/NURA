from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "deploy.sh"
HELPER_PATH = REPO_ROOT / "scripts" / "deploy_static_release.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
NGINX_PATH = REPO_ROOT / "nura_app" / "nginx" / "nura-ai.ru.conf"
COMPOSE_PATH = REPO_ROOT / "nura_app" / "docker-compose.yml"
ENTRYPOINT_PATH = REPO_ROOT / "nura_app" / "scripts" / "entrypoint.sh"


def _load_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("deploy_static_release", HELPER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helper = _load_helper()


def _run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result


def _write(path: Path, content: str = "fixture\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _populate_static_sources(repo: Path) -> None:
    for source, _destination in helper.EXPLICIT_MAPPINGS:
        _write(repo / source, f"{source}\n")
    for source_prefix, _destination_prefix in helper.DIRECTORY_MAPPINGS:
        suffix = "fixture.html" if source_prefix.endswith("/app") else "fixture.txt"
        _write(repo / source_prefix / suffix, f"{source_prefix}\n")


def _init_repo(path: Path) -> str:
    _run("git", "init", "--initial-branch=main", str(path), cwd=path.parent)
    _run("git", "config", "core.autocrlf", "false", cwd=path)
    _run("git", "config", "user.email", "fixture@example.invalid", cwd=path)
    _run("git", "config", "user.name", "Fixture", cwd=path)
    _populate_static_sources(path)
    _run("git", "add", "--all", cwd=path)
    _run("git", "commit", "-m", "fixture", cwd=path)
    return _run("git", "rev-parse", "HEAD", cwd=path).stdout.strip()


@pytest.fixture
def manifest_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo, _init_repo(repo)


def test_valid_exact_sha_manifest_copies_and_verifies_hashes(
    manifest_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, target = manifest_repo
    manifest = helper.build_manifest(repo, target)
    destinations = {entry["destination"] for entry in manifest["entries"]}
    assert {"pwa-release.js", "pwa-release.json", "service-worker.js", "app/fixture.html"} <= destinations
    assert all(len(entry["sha256"]) == 64 for entry in manifest["entries"])

    web_root = tmp_path / "web"
    web_root.mkdir()
    helper.copy_manifest(repo, web_root, manifest)
    for entry in manifest["entries"]:
        assert helper.sha256_file(web_root / entry["destination"]) == entry["sha256"]


def test_manifest_rejects_head_target_mismatch(manifest_repo: tuple[Path, str]) -> None:
    repo, _target = manifest_repo
    with pytest.raises(helper.DeploymentContractError, match="HEAD/target mismatch"):
        helper.build_manifest(repo, "0" * 40)


@pytest.mark.parametrize(
    "missing_source",
    ["frontend/pwa/pwa-release.js", "frontend/pwa/pwa-release.json", "frontend/service-worker.js"],
)
def test_manifest_fails_when_required_release_source_is_missing(
    manifest_repo: tuple[Path, str], missing_source: str
) -> None:
    repo, target = manifest_repo
    (repo / missing_source).unlink()
    with pytest.raises(helper.DeploymentContractError, match="missing"):
        helper.build_manifest(repo, target)


def test_manifest_rejects_duplicate_destination_and_traversal(
    manifest_repo: tuple[Path, str]
) -> None:
    repo, target = manifest_repo
    manifest = helper.build_manifest(repo, target)

    duplicate = copy.deepcopy(manifest)
    duplicate["entries"][1]["destination"] = duplicate["entries"][0]["destination"]
    with pytest.raises(helper.DeploymentContractError, match="Duplicate destination"):
        helper.validate_manifest_structure(duplicate)

    traversal = copy.deepcopy(manifest)
    traversal["entries"][0]["destination"] = "../outside"
    with pytest.raises(helper.DeploymentContractError, match="Invalid manifest destination"):
        helper.validate_manifest_structure(traversal)


def test_manifest_rejects_source_change_after_plan(
    manifest_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, target = manifest_repo
    manifest = helper.build_manifest(repo, target)
    _write(repo / "index.html", "changed after planning\n")
    web_root = tmp_path / "web"
    web_root.mkdir()
    with pytest.raises(helper.DeploymentContractError, match="differs from target blob"):
        helper.copy_manifest(repo, web_root, manifest)


def test_manifest_rejects_worktree_bytes_hidden_by_skip_worktree(
    manifest_repo: tuple[Path, str],
) -> None:
    repo, target = manifest_repo
    _write(repo / "index.html", "hidden tracked drift\n")
    _run("git", "update-index", "--skip-worktree", "index.html", cwd=repo)
    assert _run("git", "status", "--porcelain", cwd=repo).stdout == ""
    with pytest.raises(helper.DeploymentContractError, match="differs from target blob"):
        helper.build_manifest(repo, target)


def test_copy_detects_injected_hash_mismatch(
    manifest_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, target = manifest_repo
    manifest = helper.build_manifest(repo, target)
    web_root = tmp_path / "web"
    web_root.mkdir()

    def corrupt_copy(_source: Path, destination: Path) -> None:
        destination.write_bytes(b"corrupt")

    with pytest.raises(helper.DeploymentContractError, match="hash mismatch"):
        helper.copy_manifest(repo, web_root, manifest, copy_file=corrupt_copy)
    assert not (web_root / "index.html").exists()


def test_copy_rejects_destination_symlink(
    manifest_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, target = manifest_repo
    manifest = helper.build_manifest(repo, target)
    web_root = tmp_path / "web"
    outside = tmp_path / "outside"
    web_root.mkdir()
    outside.mkdir()
    try:
        (web_root / "app").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not available on this platform")
    with pytest.raises(helper.DeploymentContractError, match="destination symlink"):
        helper.copy_manifest(repo, web_root, manifest)


def test_migration_delta_reports_real_project_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    base = _init_repo(repo)
    _write(repo / helper.MIGRATION_DIRECTORY / "new_revision.py", "revision = 'fixture'\n")
    _run("git", "add", "--all", cwd=repo)
    _run("git", "commit", "-m", "migration", cwd=repo)
    target = _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    assert helper.migration_delta(repo, base, target) == [
        f"{helper.MIGRATION_DIRECTORY}/new_revision.py"
    ]


def _bash_executable() -> str:
    configured = shutil.which("bash")
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if os.name == "nt" and git_bash.exists():
        return str(git_bash)
    if configured:
        return configured
    pytest.skip("bash is unavailable")


def test_root_deploy_rejects_missing_and_malformed_sha_before_mutation(tmp_path: Path) -> None:
    bash = _bash_executable()
    for arguments in ([], ["abc"], ["A" * 40], ["0" * 39]):
        result = subprocess.run(
            [bash, str(DEPLOY_SCRIPT), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "target SHA" in result.stderr or "usage" in result.stderr
    assert list(tmp_path.iterdir()) == []


@dataclass
class DeployFixture:
    server: Path
    source: Path
    web_root: Path
    nginx_destination: Path
    version_file: Path
    lock_file: Path
    fake_bin: Path
    call_log: Path
    current_sha: str
    target_sha: str


def _make_executable(path: Path, content: str) -> None:
    _write(path, content)
    path.chmod(0o755)


def _create_deploy_fixture(tmp_path: Path, *, migration_delta: bool = False) -> DeployFixture:
    remote = tmp_path / "remote.git"
    source = tmp_path / "source"
    server = tmp_path / "server"
    source.mkdir()
    _run("git", "init", "--bare", str(remote), cwd=tmp_path)
    _run("git", "init", "--initial-branch=main", str(source), cwd=tmp_path)
    _run("git", "config", "core.autocrlf", "false", cwd=source)
    _run("git", "config", "user.email", "fixture@example.invalid", cwd=source)
    _run("git", "config", "user.name", "Fixture", cwd=source)
    _populate_static_sources(source)
    (source / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HELPER_PATH, source / "scripts" / "deploy_static_release.py")
    _write(
        source / "scripts" / "build_pwa_release.py",
        "import sys\nraise SystemExit(0 if '--check' in sys.argv else 2)\n",
    )
    _write(source / "frontend" / "test_pwa_release.mjs", "// fixture\n")
    _write(source / "nura_app" / "nginx" / "nura-ai.ru.conf", "events {}\n")
    _write(source / "nura_app" / "docker-compose.yml", "services: {}\n")
    _write(source / "nura_app" / "Dockerfile", "FROM scratch\n")
    _write(source / "nura_app" / "requirements.txt", "# fixture\n")
    _write(source / "nura_app" / "scripts" / "entrypoint.sh", "#!/bin/sh\nexec \"$@\"\n")
    _run("git", "add", "--all", cwd=source)
    _run("git", "commit", "-m", "base", cwd=source)
    current_sha = _run("git", "rev-parse", "HEAD", cwd=source).stdout.strip()
    _run("git", "remote", "add", "origin", str(remote), cwd=source)
    _run("git", "push", "-u", "origin", "main", cwd=source)
    _run(
        "git",
        "-c",
        "core.autocrlf=false",
        "clone",
        "--branch",
        "main",
        str(remote),
        str(server),
        cwd=tmp_path,
    )

    target_sha = current_sha
    if migration_delta:
        _write(source / helper.MIGRATION_DIRECTORY / "target_revision.py", "revision = 'target'\n")
        _run("git", "add", "--all", cwd=source)
        _run("git", "commit", "-m", "target migration", cwd=source)
        target_sha = _run("git", "rev-parse", "HEAD", cwd=source).stdout.strip()
        _run("git", "push", "origin", "main", cwd=source)

    web_root = tmp_path / "web"
    nginx_destination = tmp_path / "nginx" / "nura-ai.ru.conf"
    version_file = web_root / "VERSION"
    lock_file = tmp_path / "lock" / "deploy.lock"
    fake_bin = tmp_path / "bin"
    call_log = tmp_path / "calls.log"
    web_root.mkdir()
    nginx_destination.parent.mkdir()
    lock_file.parent.mkdir()
    fake_bin.mkdir()
    version_file.write_text(f"{current_sha} - fixture\n", encoding="utf-8")
    nginx_destination.write_text("previous nginx configuration\n", encoding="utf-8")

    python_path = Path(sys.executable).as_posix()
    _make_executable(fake_bin / "python3", f'#!/bin/sh\nexec "{python_path}" "$@"\n')
    for command in ("flock", "node", "nginx", "systemctl", "curl"):
        phase = "lock" if command == "flock" else command
        _make_executable(
            fake_bin / command,
            "#!/bin/sh\n"
            f'echo "{command} $*" >> "$NURA_TEST_CALL_LOG"\n'
            f'if test "${{NURA_TEST_FAIL_PHASE:-}}" = "{phase}"; then exit 23; fi\n'
            "exit 0\n",
        )
    _make_executable(
        fake_bin / "docker",
        "#!/bin/sh\n"
        'echo "docker $*" >> "$NURA_TEST_CALL_LOG"\n'
        'if test "$1" = "build"; then cat >/dev/null; fi\n'
        'if test "${NURA_TEST_FAIL_PHASE:-}" = "docker"; then exit 23; fi\n'
        'case " $* " in\n'
        '  *" ps -q --all "*) printf "fixture-container\\n" ;;\n'
        '  *" inspect --format "*)\n'
        '    case "${NURA_TEST_FAIL_PHASE:-}" in\n'
        '      service-running) printf "false|none|nura-release:%s\\n" "$NURA_TEST_TARGET_SHA" ;;\n'
        '      service-health) printf "true|unhealthy|nura-release:%s\\n" "$NURA_TEST_TARGET_SHA" ;;\n'
        '      service-image) printf "true|none|unexpected-image\\n" ;;\n'
        '      *) printf "true|none|nura-release:%s\\n" "$NURA_TEST_TARGET_SHA" ;;\n'
        '    esac\n'
        '    ;;\n'
        'esac\n'
        "exit 0\n",
    )

    return DeployFixture(
        server=server,
        source=source,
        web_root=web_root,
        nginx_destination=nginx_destination,
        version_file=version_file,
        lock_file=lock_file,
        fake_bin=fake_bin,
        call_log=call_log,
        current_sha=current_sha,
        target_sha=target_sha,
    )


def _run_deploy(
    fixture: DeployFixture,
    *,
    approval: str = "false",
    fail_phase: str = "",
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "ALLOW_MIGRATIONS": approval,
            "NURA_DEPLOY_TEST_MODE": "1",
            "NURA_TEST_REPO_ROOT": fixture.server.as_posix(),
            "NURA_TEST_WEB_ROOT": fixture.web_root.as_posix(),
            "NURA_TEST_NGINX_DEST": fixture.nginx_destination.as_posix(),
            "NURA_TEST_VERSION_FILE": fixture.version_file.as_posix(),
            "NURA_TEST_LOCK_FILE": fixture.lock_file.as_posix(),
            "NURA_TEST_CALL_LOG": fixture.call_log.as_posix(),
            "NURA_TEST_FAIL_PHASE": fail_phase,
            "NURA_TEST_TARGET_SHA": fixture.target_sha,
            "PATH": f"{fixture.fake_bin}{os.pathsep}{env.get('PATH', '')}",
        }
    )
    return subprocess.run(
        [_bash_executable(), str(DEPLOY_SCRIPT), fixture.target_sha],
        cwd=fixture.server,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("dirty_kind", ["tracked", "untracked"])
def test_dirty_checkout_fails_before_production_mutation(
    tmp_path: Path, dirty_kind: str
) -> None:
    fixture = _create_deploy_fixture(tmp_path)
    original_version = fixture.version_file.read_text(encoding="utf-8")
    if dirty_kind == "tracked":
        _write(fixture.server / "index.html", "dirty\n")
    else:
        _write(fixture.server / "unexpected.txt", "untracked\n")
    result = _run_deploy(fixture)
    assert result.returncode != 0
    assert "checkout contains" in result.stderr
    assert fixture.version_file.read_text(encoding="utf-8") == original_version
    calls = fixture.call_log.read_text(encoding="utf-8") if fixture.call_log.exists() else ""
    assert "nginx" not in calls and "docker" not in calls and "curl" not in calls


@pytest.mark.parametrize("approval", ["false", "0", "no", ""])
def test_migration_delta_requires_explicit_true(tmp_path: Path, approval: str) -> None:
    fixture = _create_deploy_fixture(tmp_path, migration_delta=True)
    original_version = fixture.version_file.read_text(encoding="utf-8")
    result = _run_deploy(fixture, approval=approval)
    assert result.returncode != 0
    assert "migration delta requires" in result.stderr
    assert fixture.version_file.read_text(encoding="utf-8") == original_version
    assert not fixture.call_log.exists() or "nginx" not in fixture.call_log.read_text(encoding="utf-8")


def test_migration_delta_with_explicit_true_completes_fixture_flow(tmp_path: Path) -> None:
    fixture = _create_deploy_fixture(tmp_path, migration_delta=True)
    result = _run_deploy(fixture, approval="true")
    assert result.returncode == 0, result.stderr
    assert fixture.version_file.read_text(encoding="utf-8").split()[0] == fixture.target_sha
    assert (fixture.web_root / "pwa-release.js").is_file()
    assert (fixture.web_root / "pwa-release.json").is_file()


@pytest.mark.parametrize(
    "phase",
    [
        "lock",
        "copy",
        "nginx",
        "systemctl",
        "docker",
        "service-running",
        "service-health",
        "service-image",
        "curl",
    ],
)
def test_injected_phase_failure_prevents_version_update(tmp_path: Path, phase: str) -> None:
    fixture = _create_deploy_fixture(tmp_path)
    original_version = fixture.version_file.read_text(encoding="utf-8")
    result = _run_deploy(fixture, fail_phase=phase)
    assert result.returncode != 0
    assert fixture.version_file.read_text(encoding="utf-8") == original_version
    calls = fixture.call_log.read_text(encoding="utf-8") if fixture.call_log.exists() else ""
    if phase in {"nginx", "systemctl"}:
        assert fixture.nginx_destination.read_text(encoding="utf-8") == (
            "previous nginx configuration\n"
        )
    if phase == "nginx":
        assert "systemctl" not in calls
        assert "docker" not in calls
    if phase in {"copy", "nginx", "systemctl"}:
        assert "docker" not in calls
    if phase in {"nginx", "systemctl"}:
        assert "phase static-copy" not in calls
    if phase == "copy":
        assert "nginx -t" in calls
        assert "systemctl reload nginx" in calls
        assert "phase static-copy" in calls
        assert fixture.nginx_destination.read_text(encoding="utf-8") == "events {}\n"
    if phase.startswith("service-"):
        assert "phase smoke" not in calls
        assert "phase version" not in calls


def test_successful_fixture_flow_writes_version_last(tmp_path: Path) -> None:
    fixture = _create_deploy_fixture(tmp_path)
    result = _run_deploy(fixture)
    assert result.returncode == 0, result.stderr
    assert fixture.version_file.read_text(encoding="utf-8").split()[0] == fixture.target_sha
    calls = fixture.call_log.read_text(encoding="utf-8")
    assert "nginx -t" in calls
    assert "systemctl reload nginx" in calls
    assert "docker build --pull=false --tag nura-release:" in calls
    assert "up -d --no-build --no-deps --wait --wait-timeout 180 api bot celery-worker celery-beat admin-bot" in calls
    for service in ("api", "bot", "celery-worker", "celery-beat", "admin-bot"):
        assert f"ps -q --all {service}" in calls
    assert calls.count("inspect --format") == 5
    phase_order = (
        "nginx -t",
        "systemctl reload nginx",
        "phase static-copy",
        "phase image-build",
        "up -d --no-build --no-deps --wait --wait-timeout 180",
        "phase service-verification",
        "phase smoke",
        "phase version",
    )
    assert [calls.index(item) for item in phase_order] == sorted(calls.index(item) for item in phase_order)
    assert "mandatory smoke/health phase reached" in result.stdout
    assert "in-place" in result.stdout
    assert "atomicity" in result.stdout


def test_workflow_is_manual_main_only_and_passes_exact_sha() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    trigger_block = workflow.split("\nconcurrency:", maxsplit=1)[0]
    assert "workflow_dispatch:" in trigger_block
    assert "\n  push:" not in trigger_block
    assert "environment: production" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "if: github.ref == 'refs/heads/main'" in workflow
    assert "TARGET_SHA: ${{ github.sha }}" in workflow
    assert 'git show "$TARGET_SHA:deploy.sh" > "$launcher"' in workflow
    assert 'bash "$launcher" "$TARGET_SHA"' in workflow
    assert 'bash deploy.sh "$TARGET_SHA"' not in workflow
    assert 'merge-base --is-ancestor "$TARGET_SHA" refs/remotes/origin/main' in workflow
    assert 'git -C /opt/nura show "$target_sha:frontend/pwa/pwa-release.js"' in workflow
    assert 'git -C /opt/nura show "$target_sha:frontend/pwa/pwa-release.json"' in workflow
    assert "/opt/nura/frontend/pwa/pwa-release" not in workflow
    assert "envs: TARGET_SHA,DEPLOY_REF,MIGRATIONS_APPROVED" in workflow
    assert "type: boolean" in workflow and "default: false" in workflow
    assert "git pull" not in workflow
    assert "git push" not in workflow
    for endpoint in (
        "/VERSION",
        "/service-worker.js",
        "/pwa-release.js",
        "/pwa-release.json",
        "/manifest.json",
        "/offline.html",
        "/app/",
        "/app/index.html",
        "/app/nura-pwa.js",
        "/health",
    ):
        assert endpoint in workflow
    assert "release ID mismatch" in workflow
    assert "importScripts('/pwa-release.js');" in workflow
    for source, target in (
        ("https://www.nura-ai.ru/app/?release-check=1", "https://nura-ai.ru/app/?release-check=1"),
        ("http://www.nura-ai.ru/app/?release-check=1", "https://nura-ai.ru/app/?release-check=1"),
        ("http://nura-ai.ru/app/?release-check=1", "https://nura-ai.ru/app/?release-check=1"),
    ):
        assert source in workflow
        assert target in workflow


def _location_body(config: str, path: str) -> str:
    marker = f"location = {path} {{"
    start = config.index(marker)
    next_location = config.find("\n    location ", start + len(marker))
    end_server = config.find("\n}", start + len(marker))
    end = min(value for value in (next_location, end_server) if value != -1)
    return config[start:end]


def test_nginx_metadata_cache_and_canonical_origin_contract() -> None:
    config = NGINX_PATH.read_text(encoding="utf-8")
    js_location = _location_body(config, "/pwa-release.js")
    json_location = _location_body(config, "/pwa-release.json")
    assert 'Cache-Control "no-cache, must-revalidate" always' in js_location
    assert "default_type application/javascript" in js_location
    assert "immutable" not in js_location
    assert 'Cache-Control "no-cache, must-revalidate" always' in json_location
    assert "default_type application/json" in json_location
    assert "immutable" not in json_location
    assert config.index("location = /pwa-release.js") < config.index("location ~*")
    assert config.index("location = /pwa-release.json") < config.index("location ~*")
    assert "server_name nura-ai.ru;" in config
    assert "server_name www.nura-ai.ru;" in config
    assert "return 301 https://nura-ai.ru$request_uri;" in config
    assert "root /var/www/nura-ai.ru;" in config
    assert "location /api/" in config and "location /app/" in config
    assert "/opt/nura" not in config


def test_deploy_build_and_migration_execution_paths_are_fail_closed() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT_PATH.read_text(encoding="utf-8")

    assert 'RUN_MIGRATIONS: "1"' in compose
    assert "alembic upgrade head" in entrypoint
    assert 'RUN_MIGRATIONS: "0"' in script
    assert "require_exact_target_file" in script
    assert 'archive --format=tar "${TARGET_SHA}:nura_app"' in script
    assert "docker build --pull=false" in script
    assert 'show "${TARGET_SHA}:${NGINX_SOURCE}"' in script
    assert 'show "${TARGET_SHA}:nura_app/docker-compose.yml"' in script
    assert "cache-safe nginx policy active" in script
    assert script.index("cache-safe nginx policy active") < script.index("copy-manifest")
    assert script.index("copy-manifest") < script.index("docker build --pull=false")
    assert "--no-build --no-deps --wait --wait-timeout 180" in script
    assert 'APPLICATION_SERVICES=(api bot celery-worker celery-beat admin-bot)' in script
    assert script.count('RUN_MIGRATIONS: "0"') == 1
    override_block = script[script.index('cat > "$COMPOSE_OVERRIDE"') : script.index('readonly -a APPLICATION_SERVICES')]
    assert 'RUN_MIGRATIONS: "1"' not in override_block
    for service in ("api", "bot", "celery-worker", "celery-beat", "admin-bot"):
        assert f"  {service}:\n    image: $RELEASE_IMAGE" in script
    assert "ps -q --all" in script
    assert "application service image does not match target" in script
    assert "postgres" not in script[script.index("APPLICATION_SERVICES=") : script.index("log \"running mandatory smoke")]
    assert "redis" not in script[script.index("APPLICATION_SERVICES=") : script.index("log \"running mandatory smoke")]
    assert "docker compose up -d --build" not in script


def test_root_deploy_has_no_moving_pull_or_destructive_git_commands() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "set -Eeuo pipefail" in script
    assert "git pull" not in script
    assert "reset --hard" not in script
    assert "git clean" not in script
    assert "force" not in script.lower()
    assert "flock -n" in script
    assert "merge --ff-only" in script
    assert "pwa-release.js" in HELPER_PATH.read_text(encoding="utf-8")
    assert "pwa-release.json" in HELPER_PATH.read_text(encoding="utf-8")
