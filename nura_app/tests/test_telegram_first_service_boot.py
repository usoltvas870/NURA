"""Standalone disposable PostgreSQL/Redis proof for required local services."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from tools.telegram_first_sandbox_acceptance import (
    PYTHON,
    _create_sandbox,
    _environment,
    _run,
)
from tools import telegram_first_service_boot as service_boot
from tools.telegram_first_service_boot import run_service_boot


ROOT = Path(__file__).resolve().parents[1]
NETWORK_AUDIT_BOOTSTRAP = """
import ipaddress
import os
import sys

audit_path = os.environ["NURA_NETWORK_AUDIT_PATH"]


def audit(event, args):
    if event == "socket.connect":
        host = str(args[1][0])
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = host == "localhost"
        if not is_loopback:
            with open(audit_path, "a", encoding="utf-8") as stream:
                stream.write("non_loopback_socket_attempt\\n")


sys.addaudithook(audit)
"""


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(
        ("docker", "info", "--format", "{{.ServerVersion}}"),
        capture_output=True,
        check=False,
    ).returncode == 0


def test_celery_warm_shutdown_is_a_graceful_boot_cleanup_marker() -> None:
    managed = type("Managed", (), {
        "name": "celery",
        "lines": ["worker: Warm shutdown (MainProcess)\n"],
        "process": type("Process", (), {"returncode": 1})(),
    })()

    assert service_boot._completed_graceful_shutdown(managed)


def test_celery_warm_shutdown_with_fatal_output_is_not_graceful() -> None:
    managed = type("Managed", (), {
        "name": "celery",
        "lines": ["Warm shutdown (MainProcess)\n", "ERROR/MainProcess fatal\n"],
        "process": type("Process", (), {"returncode": 1})(),
    })()

    assert not service_boot._completed_graceful_shutdown(managed)


@pytest.mark.parametrize("telegram_token", [None, "", " \t "])
def test_telegram_entrypoint_fails_closed_without_token(
    tmp_path: Path,
    telegram_token: str | None,
) -> None:
    bootstrap_dir = tmp_path / "network-audit"
    bootstrap_dir.mkdir()
    (bootstrap_dir / "sitecustomize.py").write_text(
        NETWORK_AUDIT_BOOTSTRAP,
        encoding="utf-8",
    )
    audit_path = tmp_path / "network-attempts.log"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {
            "COMSPEC",
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "WINDIR",
        }
    }
    environment.update(
        {
            "APP_ENV": "test",
            "NURA_DISABLE_DOTENV": "1",
            "NURA_NETWORK_AUDIT_PATH": str(audit_path),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(bootstrap_dir),
        }
    )
    if telegram_token is not None:
        environment["TELEGRAM_BOT_TOKEN"] = telegram_token

    started_at = time.monotonic()
    process = subprocess.Popen(
        (sys.executable, "-m", "bot.main"),
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)
        pytest.fail("telegram entrypoint did not fail closed within 15 seconds")

    output = stdout + stderr
    assert process.pid > 0
    assert process.returncode not in (None, 0)
    assert process.poll() == process.returncode
    assert time.monotonic() - started_at < 15
    assert "telegram_bot_token_not_configured" in output
    assert "Bot commands registered" not in output
    assert "Bot polling started" not in output
    assert not audit_path.exists() or not audit_path.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN" not in output
    assert "Settings(" not in output
    assert "Traceback" not in output


@pytest.mark.skipif(not _docker_available(), reason="docker_daemon_unavailable")
def test_telegram_first_service_boot_with_disposable_dependencies() -> None:
    sandbox = _create_sandbox()
    try:
        environment = _environment(sandbox)
        _run(
            "alembic_upgrade",
            PYTHON,
            "-m",
            "alembic",
            "upgrade",
            "head",
            env=environment,
        )
        run_service_boot(environment)
    finally:
        for container in (sandbox.redis_name, sandbox.postgres_name):
            subprocess.run(
                ("docker", "rm", "--force", "--volumes", container),
                capture_output=True,
                check=False,
            )
