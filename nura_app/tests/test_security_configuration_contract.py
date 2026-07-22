"""Security configuration and Redis Compose contracts."""

import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import unquote, urlsplit

import pytest
import yaml
from pydantic import ValidationError

from core.config import Settings


APP_ROOT = Path(__file__).resolve().parents[1]


def safe_production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "secret_key": "test-only-non-default-secret-at-least-32-chars",
        "session_cookie_secure": True,
        "test_mode": False,
        "yookassa_verify_on_webhook": True,
        "yookassa_shop_id": "test-shop",
        "yookassa_secret_key": "test-provider-secret",
        "redis_url": "redis://:test-password@redis:6379/0",
        "celery_broker_url": "redis://:test-password@redis:6379/1",
        "celery_result_backend": "redis://:test-password@redis:6379/2",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize(
    "environment", ["development", "test", "staging", "production"]
)
def test_supported_app_environments_are_explicit(environment: str) -> None:
    settings = safe_production_settings(app_env=environment)
    assert settings.app_env == environment
    assert settings.is_production is (environment == "production")


@pytest.mark.parametrize("environment", ["dev", "prod", "stage", "Development", ""])
def test_app_environment_aliases_and_unknown_values_fail_closed(
    environment: str,
) -> None:
    with pytest.raises(ValidationError, match="app_env_must_be_one_of"):
        Settings(app_env=environment)


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"secret_key": "change-me"}, "production_secret_key_required"),
        (
            {"session_cookie_secure": False},
            "production_secure_session_cookie_required",
        ),
        ({"test_mode": True}, "production_test_mode_forbidden"),
        (
            {"yookassa_verify_on_webhook": False},
            "production_payment_webhook_verification_required",
        ),
        (
            {"yookassa_secret_key": None},
            "production_payment_webhook_credentials_required",
        ),
        ({"redis_url": "redis://redis:6379/0"}, "production_redis_auth_required"),
        (
            {"celery_broker_url": "redis://redis:6379/1"},
            "production_celery_broker_auth_required",
        ),
        (
            {"celery_result_backend": "redis://redis:6379/2"},
            "production_celery_backend_auth_required",
        ),
    ],
)
def test_invalid_production_configuration_fails_with_safe_error(
    overrides: dict[str, object], error_code: str
) -> None:
    with pytest.raises(ValidationError, match=error_code):
        safe_production_settings(**overrides)


def test_development_and_test_keep_transitional_configuration_compatible() -> None:
    for environment in ("development", "test"):
        settings = Settings(
            app_env=environment,
            test_mode=True,
            yookassa_verify_on_webhook=False,
            session_cookie_secure=False,
        )
        assert settings.test_mode is True
        assert settings.yookassa_verify_on_webhook is False
        assert settings.session_cookie_secure is False


def test_safe_production_contract_has_no_readiness_errors() -> None:
    assert safe_production_settings().production_readiness_errors == ()


def test_public_example_secret_key_cannot_start_production() -> None:
    example = (APP_ROOT / ".env.example").read_text("utf-8")
    placeholder = next(
        line.removeprefix("SECRET_KEY=")
        for line in example.splitlines()
        if line.startswith("SECRET_KEY=")
    )

    with pytest.raises(ValidationError, match="production_secret_key_required"):
        safe_production_settings(secret_key=placeholder)


def test_short_application_secret_cannot_start_production() -> None:
    with pytest.raises(ValidationError, match="production_secret_key_required"):
        safe_production_settings(secret_key="short-non-default")


def test_redis_password_file_populates_runtime_urls_without_environment_secret(
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "redis_password"
    secret_file.write_text('test p@ssword:"\\value', encoding="utf-8")

    settings = safe_production_settings(
        redis_password_file=str(secret_file),
        redis_url="redis://redis:6379/0",
        celery_broker_url="redis://redis:6379/1",
        celery_result_backend="redis://redis:6379/2",
    )

    for url in (
        settings.redis_url,
        settings.celery_broker_url,
        settings.celery_result_backend,
    ):
        parsed = urlsplit(url)
        assert parsed.hostname == "redis"
        assert unquote(parsed.password or "") == 'test p@ssword:"\\value'


def test_redis_password_file_errors_hide_sensitive_inputs(tmp_path: Path) -> None:
    marker = "must-not-appear-in-validation-error"
    secret_file = tmp_path / "redis_password"
    secret_file.write_text(f"{marker}\ninvalid", encoding="utf-8")

    with pytest.raises(ValidationError, match="redis_password_file_invalid") as exc_info:
        safe_production_settings(redis_password_file=str(secret_file))

    assert marker not in str(exc_info.value)


def test_redis_compose_uses_secret_files_and_non_sensitive_commands() -> None:
    compose = yaml.safe_load((APP_ROOT / "docker-compose.yml").read_text("utf-8"))
    redis = compose["services"]["redis"]

    assert redis["command"] == ["/bin/sh", "/usr/local/bin/nura-redis-entrypoint"]
    assert redis["healthcheck"]["test"] == [
        "CMD",
        "/bin/sh",
        "/usr/local/bin/nura-redis-healthcheck",
    ]
    assert redis["secrets"] == ["redis_password"]
    assert compose["secrets"]["redis_password"] == {
        "environment": "REDIS_PASSWORD"
    }

    for service_name in ("api", "bot", "celery-worker", "celery-beat", "admin-bot"):
        service = compose["services"][service_name]
        assert service["secrets"] == ["redis_password"]
        assert service["environment"]["REDIS_PASSWORD"] == ""
        assert service["environment"]["REDIS_PASSWORD_FILE"] == (
            "/run/secrets/redis_password"
        )
        assert service["environment"]["REDIS_URL"] == "redis://redis:6379/0"

    inspectable = repr({"command": redis["command"], "healthcheck": redis["healthcheck"]})
    assert "REDIS_PASSWORD" not in inspectable
    assert "--requirepass" not in inspectable
    assert "'-a'" not in inspectable


def test_redis_helpers_read_only_the_secret_file_at_runtime() -> None:
    entrypoint = (APP_ROOT / "scripts" / "redis-entrypoint.sh").read_text("utf-8")
    healthcheck = (APP_ROOT / "scripts" / "redis-healthcheck.sh").read_text("utf-8")

    assert "/run/secrets/redis_password" in entrypoint
    assert "/run/secrets/redis_password" in healthcheck
    assert "${REDIS_PASSWORD}" not in entrypoint
    assert "${REDIS_PASSWORD}" not in healthcheck
    assert "redis-cli -a" not in healthcheck
    assert "REDISCLI_AUTH" in healthcheck


def test_redis_helpers_use_linux_line_endings() -> None:
    for helper_name in ("redis-entrypoint.sh", "redis-healthcheck.sh"):
        assert b"\r\n" not in (APP_ROOT / "scripts" / helper_name).read_bytes()


@pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX shell is unavailable")
@pytest.mark.parametrize(
    "helper_name", ["redis-entrypoint.sh", "redis-healthcheck.sh"]
)
@pytest.mark.parametrize(
    "secret_bytes",
    [
        b"test-password\n",
        b"test-password\r",
        b"test-password\r\n",
        b"test-password\x00suffix",
    ],
)
def test_redis_helpers_reject_newline_terminated_secret_before_execution(
    helper_name: str, secret_bytes: bytes, tmp_path: Path
) -> None:
    secret_file = tmp_path / "redis_password"
    secret_file.write_bytes(secret_bytes)
    environment = os.environ | {"REDIS_PASSWORD_FILE": str(secret_file)}

    result = subprocess.run(
        ["sh", str(APP_ROOT / "scripts" / helper_name)],
        env=environment,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0


def test_docker_build_context_excludes_runtime_environment() -> None:
    dockerignore = (APP_ROOT / ".dockerignore").read_text("utf-8").splitlines()
    assert ".env" in dockerignore
    assert ".env.*" in dockerignore
    assert "!.env.example" in dockerignore
