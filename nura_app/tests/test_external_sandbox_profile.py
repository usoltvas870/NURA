import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from core.config import Settings
from core.config import settings as runtime_settings
from core.services.payment import PaymentService
from core.services.external_sandbox import (
    SANDBOX_ALEMBIC_HEAD,
    SandboxConfigurationError,
    SandboxIdentityError,
    require_telegram_identity_evidence,
    require_yookassa_identity_evidence,
    sandbox_profile_gates,
    validate_sandbox_database_head,
    validate_sandbox_startup,
    validate_telegram_identity,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _remove_ambient_plaintext_secrets(monkeypatch) -> None:
    for name in (
        "SECRET_KEY",
        "TELEGRAM_BOT_TOKEN",
        "DEEPSEEK_API_KEY",
        "YOOKASSA_SECRET_KEY",
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)


def _secret(tmp_path: Path, name: str, value: str) -> str:
    path = tmp_path / name
    path.write_text(value, encoding="utf-8")
    return str(path)


def safe_sandbox_settings(tmp_path: Path, **overrides: object) -> Settings:
    environment_id = "nura-sbx-202607"
    hostname = "nura-sbx-202607.sandbox.example.test"
    values: dict[str, object] = {
        "_env_file": None,
        "app_env": "sandbox",
        "secret_key_file": _secret(tmp_path, "secret-key", "s" * 48),
        "database_url_file": _secret(
            tmp_path,
            "database-url",
            "postgresql+asyncpg://nura:db-pass@postgres-sandbox:5432/nura_sbx_202607",
        ),
        "redis_password_file": _secret(tmp_path, "redis-password", "redis-pass"),
        "redis_url": "redis://redis-sandbox:6379/0",
        "celery_broker_url": "redis://redis-sandbox:6379/1",
        "celery_result_backend": "redis://redis-sandbox:6379/2",
        "celery_task_queue": f"nura-sandbox-{environment_id}",
        "telegram_bot_token_file": _secret(
            tmp_path, "telegram-token", "123456:SANDBOX"
        ),
        "telegram_polling_enabled": False,
        "yookassa_shop_id": "sandbox-shop",
        "yookassa_secret_key_file": _secret(
            tmp_path, "yookassa-key", "sandbox-yookassa-key"
        ),
        "yookassa_expect_test_mode": True,
        "yookassa_verify_on_webhook": True,
        "yookassa_receipt_enabled": True,
        "yookassa_receipt_vat_code": "1",
        "yookassa_receipt_payment_mode": "full_payment",
        "yookassa_receipt_payment_subject": "service",
        "deepseek_api_key_file": _secret(
            tmp_path, "deepseek-key", "sandbox-deepseek-key"
        ),
        "deepseek_base_url": "https://sandbox-ai.example.test/v1",
        "deepseek_model": "sandbox-model",
        "report_base_url": f"https://{hostname}",
        "cors_allowed_origins": f"https://{hostname}",
        "sandbox_environment_id": environment_id,
        "sandbox_public_base_url": f"https://{hostname}",
        "sandbox_expected_hostname": hostname,
        "sandbox_expected_alembic_head": SANDBOX_ALEMBIC_HEAD,
        "sandbox_expected_database_host": "postgres-sandbox",
        "sandbox_expected_database_port": 5432,
        "sandbox_expected_database_name": "nura_sbx_202607",
        "sandbox_expected_redis_host": "redis-sandbox",
        "sandbox_expected_redis_port": 6379,
        "sandbox_expected_redis_data_db": 0,
        "sandbox_expected_redis_broker_db": 1,
        "sandbox_expected_redis_backend_db": 2,
        "sandbox_telegram_allowed_user_ids": "101,202",
        "sandbox_telegram_bot_id": 123456,
        "sandbox_telegram_bot_username": "nura_sandbox_bot",
        "sandbox_yookassa_expected_shop_id": "sandbox-shop",
        "sandbox_ai_allowed_base_url": "https://sandbox-ai.example.test/v1",
        "sandbox_ai_allowed_model": "sandbox-model",
        "sandbox_ai_max_external_calls": 20,
        "sandbox_ai_max_total_tokens": 100_000,
        "sandbox_redis_key_prefix": f"sandbox:{environment_id}:",
        "sandbox_evidence_owner": "sandbox-owner",
        "sandbox_cleanup_owner": "sandbox-cleanup-owner",
        "sandbox_ingress_contract_file": str(
            ROOT / "config" / "sandbox-ingress-paths.json"
        ),
    }
    values.update(overrides)
    return Settings(**values)


def test_safe_synthetic_profile_passes_every_static_gate(tmp_path) -> None:
    current = safe_sandbox_settings(tmp_path)

    gates = sandbox_profile_gates(current)

    assert gates
    assert all(gate.passed for gate in gates)
    validate_sandbox_startup(current)


@pytest.mark.asyncio
async def test_connected_database_must_match_exact_pinned_head(tmp_path) -> None:
    current = safe_sandbox_settings(tmp_path)

    class ScalarResult:
        def __init__(self, versions: tuple[str, ...]) -> None:
            self._versions = versions

        def scalars(self) -> "ScalarResult":
            return self

        def all(self) -> tuple[str, ...]:
            return self._versions

    class Executor:
        def __init__(self, versions: tuple[str, ...]) -> None:
            self._versions = versions

        async def execute(self, _: object) -> ScalarResult:
            return ScalarResult(self._versions)

    await validate_sandbox_database_head(
        Executor((SANDBOX_ALEMBIC_HEAD,)),
        current,
    )
    with pytest.raises(SandboxConfigurationError, match="migration_head"):
        await validate_sandbox_database_head(Executor(("wrong-head",)), current)
    with pytest.raises(SandboxConfigurationError, match="migration_head"):
        await validate_sandbox_database_head(Executor(tuple()), current)


@pytest.mark.parametrize(
    ("field", "value", "gate"),
    [
        ("sandbox_environment_id", None, "sandbox_environment_id"),
        ("sandbox_environment_id", "production", "sandbox_environment_id"),
        ("sandbox_public_base_url", "http://sandbox.example.test", "sandbox_public_url"),
        ("sandbox_expected_hostname", "nura-ai.ru", "sandbox_public_url"),
        ("sandbox_expected_hostname", "nura-ai.ru.", "sandbox_public_url"),
        ("report_base_url", "https://nura-ai.ru", "report_base_url"),
        (
            "cors_allowed_origins",
            "https://nura-ai.ru,https://nura-sbx-202607.sandbox.example.test",
            "cors",
        ),
        ("celery_task_queue", "celery", "celery_queue"),
        ("deepseek_model", "wrong-model", "ai_egress"),
        ("deepseek_base_url", "https://api.deepseek.com/v1", "ai_egress"),
        ("deepseek_base_url", "https://api.deepseek.com/v2", "ai_egress"),
        ("deepseek_base_url", "https://api.deepseek.com./v1", "ai_egress"),
        ("enable_internal_payment_shortcut", True, "yookassa_mode"),
        ("test_mode", True, "feature_flags"),
    ],
)
def test_production_like_or_ambiguous_profile_fails_closed(
    tmp_path, field, value, gate
) -> None:
    current = safe_sandbox_settings(tmp_path)
    setattr(current, field, value)

    with pytest.raises(SandboxConfigurationError, match=gate):
        validate_sandbox_startup(current)


def test_sandbox_ignores_malicious_ambient_dotenv(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            (
                "REPORT_BASE_URL=https://nura-ai.ru",
                "DEEPSEEK_BASE_URL=https://api.deepseek.com/v1",
                "CELERY_TASK_QUEUE=celery",
                "TELEGRAM_BOT_TOKEN=production-like-token",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    current = safe_sandbox_settings(tmp_path)

    assert current.report_base_url.endswith(".sandbox.example.test")
    assert current.telegram_bot_token == "123456:SANDBOX"
    validate_sandbox_startup(current)


def test_sandbox_rejects_plaintext_secret_input(tmp_path) -> None:
    with pytest.raises(ValidationError, match="sandbox_plaintext_telegram_token"):
        safe_sandbox_settings(
            tmp_path,
            telegram_bot_token="123456:PLAINTEXT",
            telegram_bot_token_file=None,
        )


@pytest.mark.parametrize(
    "field",
    ("redis_url", "celery_broker_url", "celery_result_backend"),
)
def test_sandbox_rejects_inline_redis_credentials(tmp_path, field) -> None:
    with pytest.raises(
        ValidationError,
        match="sandbox_plaintext_redis_credentials_forbidden",
    ):
        safe_sandbox_settings(
            tmp_path,
            **{field: "redis://inline:plaintext@redis-sandbox:6379/0"},
        )


def test_production_like_resource_identities_fail_closed(tmp_path) -> None:
    current = safe_sandbox_settings(
        tmp_path,
        sandbox_public_base_url="https://prod.nura-ai.ru",
        sandbox_expected_hostname="prod.nura-ai.ru",
        report_base_url="https://prod.nura-ai.ru",
        cors_allowed_origins="https://prod.nura-ai.ru",
    )
    with pytest.raises(SandboxConfigurationError, match="sandbox_public_url"):
        validate_sandbox_startup(current)

    current = safe_sandbox_settings(tmp_path)
    current.sandbox_expected_database_host = "prod-sandbox-db"
    current.database_url_file = _secret(
        tmp_path,
        "prod-database-url",
        "postgresql+asyncpg://nura:db-pass@prod-sandbox-db:5432/nura_sbx_202607",
    )
    with pytest.raises(SandboxConfigurationError, match="database_identity"):
        validate_sandbox_startup(current)


def test_database_query_override_fails_closed(tmp_path) -> None:
    current = safe_sandbox_settings(tmp_path)
    current.database_url_file = _secret(
        tmp_path,
        "query-database-url",
        (
            "postgresql+asyncpg://nura:db-pass@postgres-sandbox:5432/"
            "nura_sbx_202607?host=prod-db.internal&port=5439"
        ),
    )

    with pytest.raises(SandboxConfigurationError, match="database_identity"):
        validate_sandbox_startup(current)


def test_redis_query_override_is_rejected_during_settings_load(tmp_path) -> None:
    with pytest.raises(ValidationError, match="sandbox_redis_url_query_forbidden"):
        safe_sandbox_settings(
            tmp_path,
            redis_url="redis://redis-sandbox:6379/0?db=15",
        )


@pytest.mark.asyncio
async def test_legacy_payment_provider_is_blocked_in_sandbox_before_sdk(
    monkeypatch,
) -> None:
    monkeypatch.setattr(runtime_settings, "app_env", "sandbox")

    with patch("core.services.payment.YooPayment.create") as provider_create:
        with pytest.raises(
            RuntimeError,
            match="legacy_payments_disabled_for_external_sandbox",
        ):
            await PaymentService.create_subscription(telegram_id=101)

    provider_create.assert_not_called()


def test_missing_secret_file_fails_settings_load(tmp_path) -> None:
    with pytest.raises(ValidationError, match="deepseek_api_key_file_unreadable"):
        safe_sandbox_settings(
            tmp_path,
            deepseek_api_key_file=str(tmp_path / "missing-deepseek-key"),
        )


def test_telegram_identity_evidence_match_and_mismatch(tmp_path) -> None:
    current = safe_sandbox_settings(tmp_path)
    evidence = tmp_path / "telegram-evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "status": "verified",
                "environment_id": current.sandbox_environment_id,
                "bot_id": current.sandbox_telegram_bot_id,
                "bot_username": current.sandbox_telegram_bot_username,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    current.sandbox_telegram_identity_evidence_file = str(evidence)

    require_telegram_identity_evidence(current)
    with pytest.raises(SandboxIdentityError, match="identity_mismatch"):
        validate_telegram_identity(
            expected_bot_id=1,
            expected_username="expected_bot",
            actual_bot_id=2,
            actual_username="other_bot",
        )


def test_yookassa_identity_evidence_is_hashed_and_bound_to_environment(
    tmp_path,
) -> None:
    current = safe_sandbox_settings(tmp_path)
    import hashlib

    evidence = tmp_path / "yookassa-evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "status": "verified",
                "environment_id": current.sandbox_environment_id,
                "shop_id_sha256": hashlib.sha256(b"sandbox-shop").hexdigest(),
                "test_mode": True,
                "receipt_configured": True,
                "hostname": current.sandbox_expected_hostname,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    current.sandbox_yookassa_identity_evidence_file = str(evidence)

    require_yookassa_identity_evidence(current)
    assert "sandbox-shop" not in evidence.read_text(encoding="utf-8")
