import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from api.middleware import SandboxPublicIngressMiddleware
from core.config import settings
from core.tasks import _sandbox_schedule


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
COMPOSE = ROOT / "docker-compose.sandbox.yml"
PREFLIGHT = ROOT / "tools" / "external_sandbox_preflight.py"


def _secret(tmp_path: Path, name: str, value: str) -> str:
    path = tmp_path / name
    path.write_text(value, encoding="utf-8")
    return str(path)


def _safe_environment(tmp_path: Path) -> dict[str, str]:
    environment_id = "nura-sbx-202607"
    hostname = "nura-sbx-202607.sandbox.example.test"
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "sandbox",
            "NURA_DISABLE_DOTENV": "1",
            "SECRET_KEY_FILE": _secret(tmp_path, "secret-key", "s" * 48),
            "DATABASE_URL_FILE": _secret(
                tmp_path,
                "database-url",
                "postgresql+asyncpg://nura:db-pass@postgres-sandbox:5432/nura_sbx_202607",
            ),
            "REDIS_PASSWORD_FILE": _secret(
                tmp_path, "redis-password", "redis-pass"
            ),
            "REDIS_URL": "redis://redis-sandbox:6379/0",
            "NURA_CELERY_BROKER_URL": "redis://redis-sandbox:6379/1",
            "NURA_CELERY_RESULT_BACKEND": "redis://redis-sandbox:6379/2",
            "CELERY_TASK_QUEUE": f"nura-sandbox-{environment_id}",
            "TELEGRAM_BOT_TOKEN_FILE": _secret(
                tmp_path, "telegram-token", "123456:SANDBOX"
            ),
            "TELEGRAM_POLLING_ENABLED": "false",
            "YOOKASSA_SHOP_ID": "sandbox-shop",
            "YOOKASSA_SECRET_KEY_FILE": _secret(
                tmp_path, "yookassa-key", "sandbox-yookassa-key"
            ),
            "YOOKASSA_EXPECT_TEST_MODE": "true",
            "YOOKASSA_VERIFY_ON_WEBHOOK": "true",
            "YOOKASSA_RECEIPT_ENABLED": "true",
            "YOOKASSA_RECEIPT_VAT_CODE": "1",
            "YOOKASSA_RECEIPT_PAYMENT_MODE": "full_payment",
            "YOOKASSA_RECEIPT_PAYMENT_SUBJECT": "service",
            "DEEPSEEK_API_KEY_FILE": _secret(
                tmp_path, "deepseek-key", "sandbox-deepseek-key"
            ),
            "DEEPSEEK_BASE_URL": "https://sandbox-ai.example.test/v1",
            "DEEPSEEK_MODEL": "sandbox-model",
            "REPORT_BASE_URL": f"https://{hostname}",
            "CORS_ALLOWED_ORIGINS": f"https://{hostname}",
            "SANDBOX_ENVIRONMENT_ID": environment_id,
            "SANDBOX_PUBLIC_BASE_URL": f"https://{hostname}",
            "SANDBOX_EXPECTED_HOSTNAME": hostname,
            "SANDBOX_EXPECTED_ALEMBIC_HEAD": "d8e9f0a1b2c3",
            "SANDBOX_EXPECTED_DATABASE_HOST": "postgres-sandbox",
            "SANDBOX_EXPECTED_DATABASE_PORT": "5432",
            "SANDBOX_EXPECTED_DATABASE_NAME": "nura_sbx_202607",
            "SANDBOX_EXPECTED_REDIS_HOST": "redis-sandbox",
            "SANDBOX_EXPECTED_REDIS_PORT": "6379",
            "SANDBOX_EXPECTED_REDIS_DATA_DB": "0",
            "SANDBOX_EXPECTED_REDIS_BROKER_DB": "1",
            "SANDBOX_EXPECTED_REDIS_BACKEND_DB": "2",
            "SANDBOX_TELEGRAM_ALLOWED_USER_IDS": "101,202",
            "SANDBOX_TELEGRAM_BOT_ID": "123456",
            "SANDBOX_TELEGRAM_BOT_USERNAME": "nura_sandbox_bot",
            "SANDBOX_YOOKASSA_EXPECTED_SHOP_ID": "sandbox-shop",
            "SANDBOX_AI_ALLOWED_BASE_URL": "https://sandbox-ai.example.test/v1",
            "SANDBOX_AI_ALLOWED_MODEL": "sandbox-model",
            "SANDBOX_AI_MAX_EXTERNAL_CALLS": "20",
            "SANDBOX_AI_MAX_TOTAL_TOKENS": "100000",
            "SANDBOX_REDIS_KEY_PREFIX": f"sandbox:{environment_id}:",
            "SANDBOX_EVIDENCE_OWNER": "sandbox-owner",
            "SANDBOX_CLEANUP_OWNER": "sandbox-cleanup-owner",
            "SANDBOX_INGRESS_CONTRACT_FILE": str(
                ROOT / "config" / "sandbox-ingress-paths.json"
            ),
        }
    )
    for forbidden in (
        "SECRET_KEY",
        "TELEGRAM_BOT_TOKEN",
        "DEEPSEEK_API_KEY",
        "YOOKASSA_SECRET_KEY",
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
    ):
        environment.pop(forbidden, None)
    return environment


def _run_preflight(environment: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PREFLIGHT), *args],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_compose_is_full_stack_isolated_and_secret_file_only() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")

    for service in (
        "postgres-sandbox:",
        "redis-sandbox:",
        "api:",
        "bot:",
        "celery-worker:",
        "celery-beat:",
    ):
        assert service in compose
    assert "env_file:" not in compose
    assert "external: true" not in compose
    assert "container_name:" not in compose
    assert 'ports:' not in compose
    assert "sandbox-private:" in compose and "internal: true" in compose
    assert "DATABASE_URL_FILE: /run/secrets/database_url" in compose
    assert "TELEGRAM_BOT_TOKEN_FILE: /run/secrets/telegram_bot_token" in compose
    assert "DEEPSEEK_API_KEY_FILE: /run/secrets/deepseek_api_key" in compose
    assert "YOOKASSA_SECRET_KEY_FILE: /run/secrets/yookassa_secret_key" in compose
    assert "env_file" not in compose
    assert "deploy.yml" not in compose


def test_compose_contract_renders_with_local_fake_secret_files(tmp_path) -> None:
    environment = _safe_environment(tmp_path)
    environment.update(
        {
            "SANDBOX_POSTGRES_USER": "nura_sbx",
            "SANDBOX_POSTGRES_DB": "nura_sbx_202607",
            "SANDBOX_YOOKASSA_RECEIPT_VAT_CODE": "1",
            "SANDBOX_YOOKASSA_RECEIPT_PAYMENT_MODE": "full_payment",
            "SANDBOX_YOOKASSA_RECEIPT_PAYMENT_SUBJECT": "service",
            "SANDBOX_SECRET_KEY_FILE": _secret(
                tmp_path, "compose-secret-key", "s" * 48
            ),
            "SANDBOX_POSTGRES_PASSWORD_FILE": _secret(
                tmp_path, "compose-postgres-password", "postgres-pass"
            ),
            "SANDBOX_DATABASE_URL_FILE": environment["DATABASE_URL_FILE"],
            "SANDBOX_REDIS_PASSWORD_FILE": environment["REDIS_PASSWORD_FILE"],
            "SANDBOX_TELEGRAM_BOT_TOKEN_FILE": environment[
                "TELEGRAM_BOT_TOKEN_FILE"
            ],
            "SANDBOX_TELEGRAM_IDENTITY_EVIDENCE_FILE": _secret(
                tmp_path, "compose-telegram-evidence", "{}"
            ),
            "SANDBOX_YOOKASSA_SECRET_KEY_FILE": environment[
                "YOOKASSA_SECRET_KEY_FILE"
            ],
            "SANDBOX_YOOKASSA_IDENTITY_EVIDENCE_FILE": _secret(
                tmp_path, "compose-yookassa-evidence", "{}"
            ),
            "SANDBOX_DEEPSEEK_API_KEY_FILE": environment[
                "DEEPSEEK_API_KEY_FILE"
            ],
        }
    )

    completed = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "config", "--quiet"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr


def test_sandbox_beat_contains_only_reconciliation_tasks() -> None:
    tasks = {entry["task"] for entry in _sandbox_schedule.values()}

    assert tasks == {
        "core.tasks.reconcile_chat_deliveries",
        "core.tasks.dispatch_report_generation_jobs",
        "core.tasks.reconcile_report_generation_jobs",
    }
    assert not any(
        marker in task
        for task in tasks
        for marker in (
            "charge_recurring",
            "inactive",
            "weekly",
            "monthly",
            "cleanup",
            "monitor",
            "broadcast",
        )
    )


def test_every_sandbox_process_uses_the_shared_startup_validator() -> None:
    sources = {
        path: (ROOT / path).read_text(encoding="utf-8")
        for path in ("api/main.py", "bot/main.py", "core/tasks.py")
    }

    assert "validate_sandbox_startup(settings)" in sources["api/main.py"]
    assert "validate_sandbox_database_head(session, settings)" in sources["api/main.py"]
    assert "validate_sandbox_startup(settings)" in sources["bot/main.py"]
    assert "validate_sandbox_database_head(conn, settings)" in sources["bot/main.py"]
    assert "validate_sandbox_startup(settings)" in sources["core/tasks.py"]
    assert "validate_sandbox_database_versions(versions, settings)" in sources["core/tasks.py"]
    assert "@worker_init.connect" in sources["core/tasks.py"]
    assert "@beat_init.connect" in sources["core/tasks.py"]
    bot_source = sources["bot/main.py"]
    assert bot_source.index("if not settings.telegram_polling_enabled:") < (
        bot_source.index("await bot.set_my_commands")
    )


def test_sandbox_ingress_is_enforced_before_route_execution(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "sandbox")
    application = FastAPI()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["https://nura-sbx-202607.sandbox.example.test"],
        allow_methods=["*"],
    )
    application.add_middleware(SandboxPublicIngressMiddleware)

    @application.get("/{path:path}")
    async def catch_all(path: str) -> dict[str, str]:
        return {"path": path}

    capability = "a" * 40
    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        assert (
            client.get(
                f"/api/v1/payment/full-matrix/checkout/{capability}"
            ).status_code
            == 200
        )
        assert client.get("/api/v1/admin/users").status_code == 404
        assert client.options(
            "/api/v1/admin/users",
            headers={
                "Origin": "https://nura-sbx-202607.sandbox.example.test",
                "Access-Control-Request-Method": "GET",
            },
        ).status_code == 404
        assert client.get("/app").status_code == 404
        assert client.get("/report/token").status_code == 404


def test_offline_preflight_safe_fixture_is_ready_and_redacted(tmp_path) -> None:
    completed = _run_preflight(_safe_environment(tmp_path))

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["result"] == "READY_FOR_EXTERNAL_IDENTITY_CHECK"
    assert payload["external_network_calls"] == 0
    assert all(gate["status"] == "PASS" for gate in payload["gates"])
    output = completed.stdout
    assert "sandbox-yookassa-key" not in output
    assert "sandbox-deepseek-key" not in output
    assert "db-pass" not in output


def test_offline_preflight_production_like_fixture_is_blocked(tmp_path) -> None:
    environment = _safe_environment(tmp_path)
    environment["REPORT_BASE_URL"] = "https://nura-ai.ru"

    completed = _run_preflight(environment)

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["result"] == "BLOCKED"
    assert any(
        gate["gate"] == "report_base_url" and gate["status"] == "FAIL"
        for gate in payload["gates"]
    )


def test_external_identity_mode_is_explicit_and_has_no_bundled_network_call(
    tmp_path,
) -> None:
    completed = _run_preflight(
        _safe_environment(tmp_path),
        "--external-identity-check",
        "telegram",
    )

    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["result"] == "BLOCKED"
    assert payload["external_network_calls"] == 0
    source = PREFLIGHT.read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "socket" not in source


def test_production_workflows_do_not_reference_sandbox_compose() -> None:
    workflows = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / ".github" / "workflows").glob("*.yml")
    )

    assert "docker-compose.sandbox.yml" not in workflows
