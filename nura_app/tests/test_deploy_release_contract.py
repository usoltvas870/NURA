from __future__ import annotations

import copy
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "deploy.sh"
AUDITED_P6B_SCRIPT = REPO_ROOT / "scripts" / "deploy_audited_p6b_transition.sh"
STATIC_HELPER_PATH = REPO_ROOT / "scripts" / "deploy_static_release.py"
ARTIFACT_HELPER_PATH = REPO_ROOT / "scripts" / "build_release_artifact.py"
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
ROLLBACK_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "rollback.yml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-cd.yml"
NGINX_PATH = REPO_ROOT / "nura_app" / "nginx" / "nura-ai.ru.conf"
COMPOSE_PATH = REPO_ROOT / "nura_app" / "docker-compose.yml"
ENTRYPOINT_PATH = REPO_ROOT / "nura_app" / "scripts" / "entrypoint.sh"


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


static_helper = _load_module("deploy_static_release", STATIC_HELPER_PATH)


def _run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result


def _write(path: Path, content: str = "fixture\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _populate_static_sources(repo: Path) -> None:
    for source, _destination in static_helper.EXPLICIT_MAPPINGS:
        _write(repo / source, f"{source}\n")
    for source_prefix, _destination_prefix in static_helper.DIRECTORY_MAPPINGS:
        suffix = "index.html" if source_prefix.endswith("/app") else "fixture.txt"
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


def test_static_manifest_contains_complete_required_contract(
    manifest_repo: tuple[Path, str],
) -> None:
    repo, target = manifest_repo
    manifest = static_helper.build_manifest(repo, target)
    destinations = {entry["destination"] for entry in manifest["entries"]}
    assert {
        "vk-callback.html",
        "pwa-release.js",
        "pwa-release.json",
        "service-worker.js",
        "app/index.html",
    } <= destinations
    assert all(len(entry["sha256"]) == 64 for entry in manifest["entries"])


@pytest.mark.parametrize(
    "missing_source",
    [
        "vk-callback.html",
        "frontend/pwa/pwa-release.js",
        "frontend/pwa/pwa-release.json",
        "frontend/service-worker.js",
    ],
)
def test_static_manifest_rejects_missing_required_source(
    manifest_repo: tuple[Path, str], missing_source: str
) -> None:
    repo, target = manifest_repo
    (repo / missing_source).unlink()
    with pytest.raises(static_helper.DeploymentContractError, match="missing"):
        static_helper.build_manifest(repo, target)


def test_static_manifest_rejects_duplicate_and_traversal(
    manifest_repo: tuple[Path, str],
) -> None:
    repo, target = manifest_repo
    manifest = static_helper.build_manifest(repo, target)
    duplicate = copy.deepcopy(manifest)
    duplicate["entries"][1]["destination"] = duplicate["entries"][0]["destination"]
    with pytest.raises(static_helper.DeploymentContractError, match="Duplicate destination"):
        static_helper.validate_manifest_structure(duplicate)
    traversal = copy.deepcopy(manifest)
    traversal["entries"][0]["destination"] = "../outside"
    with pytest.raises(static_helper.DeploymentContractError, match="Invalid manifest destination"):
        static_helper.validate_manifest_structure(traversal)


def test_manifest_rejects_head_target_or_hidden_worktree_drift(
    manifest_repo: tuple[Path, str],
) -> None:
    repo, target = manifest_repo
    with pytest.raises(static_helper.DeploymentContractError, match="HEAD/target mismatch"):
        static_helper.build_manifest(repo, "0" * 40)
    _write(repo / "index.html", "hidden drift\n")
    _run("git", "update-index", "--skip-worktree", "index.html", cwd=repo)
    with pytest.raises(static_helper.DeploymentContractError, match="differs from target blob"):
        static_helper.build_manifest(repo, target)


def test_migration_delta_reports_any_change(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    base = _init_repo(repo)
    _write(repo / static_helper.MIGRATION_DIRECTORY / "new_revision.py", "revision='fixture'\n")
    _run("git", "add", "--all", cwd=repo)
    _run("git", "commit", "-m", "migration", cwd=repo)
    target = _run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    assert static_helper.migration_delta(repo, base, target) == [
        f"{static_helper.MIGRATION_DIRECTORY}/new_revision.py"
    ]


def _bash_executable() -> str:
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    configured = shutil.which("bash")
    if os.name == "nt" and git_bash.exists():
        return str(git_bash)
    if configured:
        return configured
    pytest.skip("bash is unavailable")


@pytest.mark.parametrize(
    "arguments",
    [[], ["deploy"], ["deploy", "abc"], ["deploy", "A" * 40], ["rollback", "0" * 39]],
)
def test_root_engine_rejects_ambiguous_or_malformed_cli(arguments: list[str]) -> None:
    result = subprocess.run(
        [_bash_executable(), str(DEPLOY_SCRIPT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "usage" in result.stderr or "SHA" in result.stderr or "ambiguous" in result.stderr


def test_root_engine_has_one_audited_preapplied_migration_transition() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "migration delta blocks deployment outside the audited transition" in script
    assert "ALLOW_MIGRATIONS" not in script
    assert "allow_migrations" not in script
    assert "alembic upgrade" not in script
    assert "alembic downgrade" not in script
    assert "AUDITED_MIGRATION_FROM_SHA='d0d39ae8717ceb0920d98f27dd9092f746755c6c'" in script
    assert "AUDITED_MIGRATION_TARGET_SHA='9da6ad8cf0146b26bdd2b60ebf99b54a58ccd532'" in script
    assert "AUDITED_MIGRATION_REVISION='d1e2f3a4b5c6'" in script
    assert "NURA_PREAPPLIED_MIGRATION_REVISION" in script
    assert "NURA_ACKNOWLEDGE_BACKWARD_COMPATIBLE_SCHEMA" in script
    assert "NURA_AUDITED_ENGINE_HELPER_ROOT" in script
    assert 'ARTIFACT_HELPER="$AUDITED_HELPER_ROOT/build_release_artifact.py"' in script
    assert "target_alembic_head" in script
    assert "SELECT version_num FROM alembic_version" in script
    assert 'RUN_MIGRATIONS: "0"' in script
    assert script.index("MIGRATION_OUTPUT") < script.index("extract --archive")
    assert script.index("MIGRATION_OUTPUT") < script.index("docker build")
    assert 'build_pwa_release.py" --check' in script
    assert 'frontend/test_pwa_release.mjs"' in script


def test_audited_p6b_wrapper_reaches_exact_immutable_target() -> None:
    source = AUDITED_P6B_SCRIPT.read_text(encoding="utf-8")
    assert "TARGET_SHA='9da6ad8cf0146b26bdd2b60ebf99b54a58ccd532'" in source
    assert "EXPECTED_REVISION='d1e2f3a4b5c6'" in source
    assert "ENGINE_COMMIT='a8f9140795255804afe1bc46924d996a57b81d45'" in source
    assert "ENGINE_BLOB='71a1e91374483876a1059ddec6d6c6b32c41df67'" in source
    assert 'export NURA_PREAPPLIED_MIGRATION_REVISION="$EXPECTED_REVISION"' in source
    assert "export NURA_ACKNOWLEDGE_BACKWARD_COMPATIBLE_SCHEMA=1" in source
    assert 'bash "$ENGINE_FILE" deploy "$TARGET_SHA"' in source
    assert 'merge-base --is-ancestor "$TARGET_SHA" "$ENGINE_COMMIT"' in source
    assert 'git -C "$LAUNCHER_ROOT" show "$ENGINE_COMMIT:deploy.sh" > "$ENGINE_FILE"' in source
    assert 'git hash-object "$ENGINE_FILE"' in source
    assert '"$LAUNCHER_ROOT/deploy.sh"' not in source
    assert "alembic upgrade" not in source
    assert "alembic downgrade" not in source

    result = subprocess.run(
        [_bash_executable(), str(AUDITED_P6B_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "usage:" in result.stderr


def test_root_engine_uses_one_exact_image_and_verifies_all_five_services() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert 'IMAGE_TAG="nura-release:$TARGET_SHA"' in script
    assert "org.opencontainers.image.revision" in script
    assert "org.opencontainers.image.source" in script
    assert "org.opencontainers.image.created" in script
    assert 'APPLICATION_SERVICES=(api bot celery-worker celery-beat admin-bot)' in script
    assert "application service is missing or ambiguous" in script
    assert "application service is not running" in script
    assert "application service is unhealthy" in script
    assert "application service tag mismatch" in script
    assert "application service image ID mismatch" in script
    assert "application service revision mismatch" in script
    assert 'DATA_SERVICES=(postgres redis)' in script
    assert "--no-build --no-deps --wait --wait-timeout 180" in script


def test_root_engine_orders_activation_and_compensation() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    activation = [
        "run_compose up -d",
        'switch-current --current "$CURRENT_LINK" --target "$TARGET_RELEASE"',
        'public_smoke "$TARGET_SHA"',
        "write_state successful",
    ]
    assert [script.index(item) for item in activation] == sorted(script.index(item) for item in activation)
    cleanup = script[script.index("cleanup()") : script.index("trap cleanup EXIT")]
    assert cleanup.index("switch-current") < cleanup.index("activate_from_state")
    rollback = script[script.index('if [[ "$COMMAND" == rollback ]]') : script.index('[[ -f "$ARTIFACT_PATH"')]
    assert rollback.index("switch-current") < rollback.index("activate_from_state")
    assert "no database rollback was attempted" in rollback


def test_root_engine_has_no_moving_or_destructive_git_and_no_nginx_reload() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "git pull" not in script
    assert "reset --hard" not in script
    assert "git clean" not in script
    assert "force-push" not in script
    assert "flock -n" in script
    assert "merge --ff-only" in script
    assert "systemctl reload nginx" not in script
    assert "nginx -t" not in script
    assert "exactly one canonical enabled Nginx config" in script


def _trigger_block(workflow: str) -> str:
    return workflow.split("\nconcurrency:", maxsplit=1)[0]


@pytest.mark.parametrize("path", [DEPLOY_WORKFLOW, ROLLBACK_WORKFLOW])
def test_release_workflows_are_manual_main_protected_and_serial(path: Path) -> None:
    workflow = path.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in _trigger_block(workflow)
    assert "\n  push:" not in _trigger_block(workflow)
    assert "environment: production" in workflow
    assert "group: deploy-production" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "refs/heads/main" in workflow
    assert "fingerprint: ${{ secrets.VPS_SSH_FINGERPRINT }}" in workflow
    assert "git pull" not in workflow
    assert re.search(r"uses:\s+actions/[^@]+@v\d+\s*$", workflow, re.MULTILINE) is None


def test_deploy_workflow_builds_exact_deterministic_artifact_for_14_days() -> None:
    workflow = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    assert "TARGET_SHA: ${{ github.sha }}" in workflow
    assert "build_release_artifact.py build" in workflow
    assert "build_release_artifact.py verify" in workflow
    assert "cmp \"$RUNNER_TEMP/release-a/nura-static-$TARGET_SHA.tar.gz\"" in workflow
    assert "retention-days: 14" in workflow
    assert "compression-level: 0" in workflow
    assert "overwrite: false" in workflow
    assert 'bash "$launcher" deploy "$TARGET_SHA"' in workflow
    assert "allow_migrations" not in workflow
    assert "MIGRATIONS_APPROVED" not in workflow
    assert 'node-version: "24.15.0"' in workflow
    assert 'python-version: "3.11.9"' in workflow
    assert "python --version" in workflow and "node --version" in workflow
    assert "artifact-digest" not in workflow
    assert "EXPECTED_ACTION_DIGEST" not in workflow
    assert "actions/setup-node@v5" not in workflow
    assert "actions/setup-python@v6" not in workflow


def test_rollback_workflow_requires_exact_target_and_acknowledgement() -> None:
    workflow = ROLLBACK_WORKFLOW.read_text(encoding="utf-8")
    assert "target_sha:" in workflow
    assert "acknowledge_rollback:" in workflow
    assert "inputs.acknowledge_rollback" in workflow
    assert 'bash deploy.sh rollback "$TARGET_SHA"' in workflow
    assert "git checkout" not in workflow
    assert "alembic" not in workflow.lower()
    assert workflow.count("release-check=1") == 6


@pytest.mark.parametrize(
    "contract",
    [
        'CANDIDATE_TAG="nura-release-candidate:$TARGET_SHA-$RUN_ID"',
        "final image tag exists without immutable state",
        "final static release exists without immutable state",
        "incomplete release state requires operator recovery",
        "failed release is not proven compensated",
        "immutable release provenance mismatch",
        "recorded immutable image ID is unavailable",
        "final release tag conflicts with immutable state",
        "candidate application image OCI labels mismatch",
        "final application image OCI labels mismatch",
        "write_state staged",
        "compensation_verified",
        "oci_source",
        "oci_created",
        "recovery evidence already exists; refusing overwrite",
    ],
)
def test_immutable_release_identity_contracts_are_explicit(contract: str) -> None:
    assert contract in DEPLOY_SCRIPT.read_text(encoding="utf-8")


def test_candidate_is_validated_published_and_removed_before_application_mutation() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    build = script.index('docker build --pull=false --tag "$CANDIDATE_TAG"')
    publish = script.index('docker image tag "$CANDIDATE_TAG" "$IMAGE_TAG"')
    staged = script.index("write_state staged")
    mutate = script.index("APP_MUTATED=1", staged)
    assert build < publish < staged < mutate
    assert script.index('docker image rm "$CANDIDATE_TAG"', publish) < staged


def test_reactivation_path_reuses_recorded_static_and_image_without_build() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    reuse = script[script.index('if [[ -e "$TARGET_STATE_FILE"') : script.index("if [[ $REUSE_RELEASE -eq 0 ]]")]
    assert "verify_release_directory" in reuse
    assert 'docker image tag "$TARGET_IMAGE_ID" "$IMAGE_TAG"' in reuse
    assert "docker build" not in reuse
    assert "extract --archive" not in reuse


def test_activation_history_is_authoritative_for_rollback_retention_and_pointers() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    rollback = script[script.index('if [[ "$COMMAND" == rollback ]]') : script.index('[[ -f "$ARTIFACT_PATH"')]
    retention = script[script.index("retention cleanup is best-effort") :]
    assert 'target.get("sha") not in current.get("activation_history",[])' in rollback
    assert "rollback target is outside current activation_history" in rollback
    assert 'protected={current["sha"],*history}' in retention
    assert "previous_successful_sha" not in retention
    assert "previous.json does not match activation_history[0]" in script
    assert "release state lineage contains a cycle" not in script
    cleanup = script[script.index("cleanup()") : script.index("trap cleanup EXIT")]
    assert 'atomic_copy_state "$TARGET_STATE_SNAPSHOT"' in cleanup


def test_ci_workflow_has_no_deployment() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "environment: production" not in workflow
    assert "ssh-action" not in workflow
    assert "scp-action" not in workflow
    assert "deploy.sh deploy" not in workflow


def test_nginx_uses_release_root_except_stable_acme() -> None:
    config = NGINX_PATH.read_text(encoding="utf-8")
    assert "root /var/www/nura-releases/current/public;" in config
    assert "location = /vk-callback.html" in config
    assert "location = /VERSION" in config
    assert "location = /release-manifest.json" in config
    assert "/opt/nura" not in config
    acme_blocks = config.split("location /.well-known/acme-challenge/ {")[1:]
    assert len(acme_blocks) == 2
    assert all("root /var/www/nura-ai.ru;" in block.split("}", 1)[0] for block in acme_blocks)
    without_acme = config
    for block in acme_blocks:
        fragment = "location /.well-known/acme-challenge/ {" + block.split("}", 1)[0] + "}"
        without_acme = without_acme.replace(fragment, "")
    assert "/var/www/nura-ai.ru" not in without_acme


def test_compose_and_entrypoint_migrations_are_overridden_not_executed() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT_PATH.read_text(encoding="utf-8")
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert 'RUN_MIGRATIONS: "1"' in compose
    assert "alembic upgrade head" in entrypoint
    assert 'RUN_MIGRATIONS: "0"' in script
    assert "alembic upgrade" not in script
