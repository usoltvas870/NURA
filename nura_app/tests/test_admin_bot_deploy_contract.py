from __future__ import annotations

import ast
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_BOT_ROOT = REPO_ROOT / "nura_app" / "admin_bot"
DOCKER_CLIENT = ADMIN_BOT_ROOT / "services" / "docker_client.py"
DEPLOY_HANDLER = ADMIN_BOT_ROOT / "handlers" / "deploy.py"
MAIN_MODULE = ADMIN_BOT_ROOT / "main.py"
HANDLERS_INIT = ADMIN_BOT_ROOT / "handlers" / "__init__.py"
HELP_HANDLER = ADMIN_BOT_ROOT / "handlers" / "help.py"
DEPRECATED_STUB = REPO_ROOT / "scripts" / "deploy.sh"
DEPLOY_DOC = REPO_ROOT / "DEPLOY.md"
ADMIN_SPEC = REPO_ROOT / "ADMIN_BOT_SPEC.md"


def _bash_executable() -> str:
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if os.name == "nt" and git_bash.exists():
        return str(git_bash)
    configured = shutil.which("bash")
    if configured:
        return configured
    pytest.skip("bash is unavailable")


def test_deprecated_cli_stub_fails_closed_without_mutation_commands() -> None:
    script = DEPRECATED_STUB.read_text(encoding="utf-8")
    lowered = script.lower()
    for forbidden in (
        "git push",
        "git pull",
        "git fetch",
        "ssh ",
        "docker",
        "compose",
        "../deploy.sh",
        "nura-vps",
    ):
        assert forbidden not in lowered

    result = subprocess.run(
        [_bash_executable(), str(DEPRECATED_STUB)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "GitHub Actions" in result.stderr
    assert "Deploy to production" in result.stderr
    assert "production approval" in result.stderr
    assert "not supported" in result.stderr


def test_admin_bot_has_no_deploy_handler_method_or_caller() -> None:
    assert not DEPLOY_HANDLER.exists()
    docker_source = DOCKER_CLIENT.read_text(encoding="utf-8")
    docker_tree = ast.parse(docker_source)
    method_names = {
        node.name
        for node in ast.walk(docker_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "run_deploy" not in method_names

    combined_source = "\n".join(
        path.read_text(encoding="utf-8") for path in ADMIN_BOT_ROOT.rglob("*.py")
    )
    assert "run_deploy" not in combined_source
    assert "git pull" not in combined_source
    assert "docker compose" not in combined_source.lower()
    assert "/opt/nura" not in combined_source


def test_active_router_and_command_list_excludes_deploy_but_preserves_operations() -> None:
    main_source = MAIN_MODULE.read_text(encoding="utf-8")
    init_source = HANDLERS_INIT.read_text(encoding="utf-8")
    help_source = HELP_HANDLER.read_text(encoding="utf-8")

    assert "deploy_router" not in main_source
    assert "deploy_router" not in init_source
    assert 'command="deploy"' not in main_source
    assert "/deploy" not in help_source
    for router in ("status_router", "restart_router", "cache_router", "chat_router", "help_router"):
        assert f"dp.include_router({router})" in main_source
        assert router in init_source
    for command in ("status", "restart", "cache", "help"):
        assert f'command="{command}"' in main_source


def test_deploy_documentation_describes_only_approved_manual_workflow() -> None:
    document = DEPLOY_DOC.read_text(encoding="utf-8")
    assert "GitHub Actions" in document
    assert "Deploy to production" in document
    assert "Run workflow" in document
    assert "environment `production`" in document
    assert "exact target SHA" in document
    assert "allow_migrations" in document
    assert "in place" in document
    assert "P4.2B2" in document and "P4.1B" in document
    assert "git pull --" not in document
    assert "git add -A &&" not in document
    assert "git stash" not in document
    assert "Fallback —" not in document
    assert "scripts/deploy.sh" in document
    assert "fail-closed deprecated stub" in document
    assert "emergency deploy не поддерживаются" in document


def test_admin_bot_spec_matches_no_deploy_no_db_contract() -> None:
    specification = ADMIN_SPEC.read_text(encoding="utf-8")
    assert "/deploy" not in specification
    assert "/db" not in specification
    assert "handlers/deploy.py" not in specification
    assert "source checkout" in specification
    assert "production build" in specification
    assert "production-deploy command" in specification
    assert "approved manual GitHub Actions workflow" in specification
    for command in ("/status", "/restart", "/cache clear", "/help"):
        assert command in specification
