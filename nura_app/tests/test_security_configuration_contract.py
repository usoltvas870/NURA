"""Security configuration and Redis Compose contracts."""

import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import unquote, urlsplit

import pytest
import yaml
from pydantic import ValidationError

import core.config as config
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
        "yookassa_receipt_enabled": True,
        "yookassa_receipt_vat_code": "test_vat",
        "yookassa_receipt_payment_mode": "test_mode",
        "yookassa_receipt_payment_subject": "test_subject",
        "redis_url": "redis://:test-password@redis:6379/0",
        "celery_broker_url": "redis://:test-password@redis:6379/1",
        "celery_result_backend": "redis://:test-password@redis:6379/2",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


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
        Settings(_env_file=None, app_env=environment)


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
            _env_file=None,
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


def test_nura_runtime_environment_aliases_control_actual_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_secret = tmp_path / "database_url"
    database_secret.write_text(
        "postgresql+asyncpg://user:password@db/nura",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "NURA_TG_DATABASE_URL_FILE", str(database_secret))
    monkeypatch.setenv("DATABASE_URL_FILE", str(database_secret))
    monkeypatch.setenv("NURA_RUNTIME_PROFILE", "pilot")
    monkeypatch.setenv("NURA_TG_POLLING_ENABLED", "false")

    runtime = Settings(_env_file=None)

    assert runtime.runtime_profile == "nura_tg"
    assert runtime.telegram_polling_enabled is False


def test_runtime_environment_defaults_and_legacy_aliases_remain_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aliases = (
        "NURA_RUNTIME_PROFILE",
        "RUNTIME_PROFILE",
        "NURA_TG_POLLING_ENABLED",
        "TELEGRAM_POLLING_ENABLED",
    )
    for alias in aliases:
        monkeypatch.delenv(alias, raising=False)
    defaults = Settings(_env_file=None)
    assert defaults.runtime_profile == "legacy"
    assert defaults.telegram_polling_enabled is True

    monkeypatch.setenv("RUNTIME_PROFILE", "legacy")
    monkeypatch.setenv("TELEGRAM_POLLING_ENABLED", "false")
    legacy = Settings(_env_file=None)
    assert legacy.runtime_profile == "legacy"
    assert legacy.telegram_polling_enabled is False


def test_unknown_runtime_profile_fails_closed() -> None:
    with pytest.raises(ValidationError, match="runtime_profile_must_be_one_of"):
        Settings(_env_file=None, runtime_profile="unknown")


def test_nura_tg_settings_require_only_fixed_database_secret_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_file = tmp_path / "database_url"
    secret_file.write_text("postgresql+asyncpg://user:password@db/nura", encoding="utf-8")
    monkeypatch.setattr(config, "NURA_TG_DATABASE_URL_FILE", str(secret_file))

    settings = Settings(_env_file=None, runtime_profile="nura_tg", database_url_file=str(secret_file))
    assert settings.database_url == "postgresql+asyncpg://user:password@db/nura"
    assert "DATABASE_URL" not in os.environ

    for values in (
        {},
        {"database_url_file": "wrong-path"},
        {"DATABASE_URL": "postgresql://secret"},
        {"DATABASE_URL": "postgresql://secret", "database_url_file": str(secret_file)},
    ):
        with pytest.raises(ValidationError, match="nura_tg_.*database_url") as exc_info:
            Settings(_env_file=None, runtime_profile="nura_tg", **values)
        assert "postgresql://secret" not in str(exc_info.value)


@pytest.mark.parametrize("contents", ["", "postgresql://one\ntwo", "postgresql://one\rtwo"])
def test_nura_tg_database_secret_invalid_content_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contents: str
) -> None:
    secret_file = tmp_path / "database_url"
    secret_file.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(config, "NURA_TG_DATABASE_URL_FILE", str(secret_file))
    with pytest.raises(ValidationError, match="database_url_file_(invalid|unreadable)"):
        Settings(_env_file=None, runtime_profile="nura_tg", database_url_file=str(secret_file))


def test_nura_tg_bot_and_worker_share_settings_resolver() -> None:
    bot = (APP_ROOT / "bot" / "main.py").read_text("utf-8")
    worker = (APP_ROOT / "core" / "tasks.py").read_text("utf-8")
    assert "from core.config import settings" in bot
    assert "from core.config import settings" in worker
    assert "core.redis_auth_probe" in (APP_ROOT.parent / "scripts" / "p7_telegram_pilot_controller.py").read_text("utf-8")


@pytest.mark.asyncio
async def test_authenticated_redis_probe_requires_authenticated_pong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import redis_auth_probe

    calls: list[object] = []

    class FakeRedis:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

        async def ping(self) -> bool:
            return True

        async def aclose(self) -> None:
            calls.append("closed")

    monkeypatch.setattr(redis_auth_probe, "Redis", FakeRedis)
    monkeypatch.setattr(redis_auth_probe, "_read_secret_file", lambda *_: "probe-secret")
    assert await redis_auth_probe.authenticated_redis_pong() is True
    assert calls[0] == {"host": "redis", "port": 6379, "password": "probe-secret", "decode_responses": False}
    assert calls[-1] == "closed"


@pytest.mark.asyncio
async def test_authenticated_redis_probe_rejects_wrong_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import redis_auth_probe

    class RejectingRedis:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def ping(self) -> bool:
            raise RuntimeError("WRONGPASS")

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(redis_auth_probe, "Redis", RejectingRedis)
    monkeypatch.setattr(redis_auth_probe, "_read_secret_file", lambda *_: "wrong-secret")
    with pytest.raises(RuntimeError, match="WRONGPASS"):
        await redis_auth_probe.authenticated_redis_pong()


def test_redis_compose_uses_secret_files_and_non_sensitive_commands() -> None:
    compose = yaml.safe_load((APP_ROOT / "docker-compose.yml").read_text("utf-8"))
    redis = compose["services"]["redis"]

    assert redis["command"] == ["/bin/sh", "/usr/local/bin/nura-redis-entrypoint"]
    assert redis["healthcheck"]["test"] == [
        "CMD",
        "/bin/sh",
        "/usr/local/bin/nura-redis-healthcheck",
    ]
    assert redis["secrets"] == [
        {"source": "redis_password", "target": "redis_password", "mode": 0o444}
    ]
    assert compose["secrets"]["redis_password"] == {
        "environment": "REDIS_PASSWORD"
    }

    for service_name in ("api", "bot", "celery-worker", "celery-beat", "admin-bot"):
        service = compose["services"][service_name]
        assert service["secrets"] == [
            {"source": "redis_password", "target": "redis_password", "mode": 0o444}
        ]
        assert service["environment"]["REDIS_PASSWORD"] == ""
        assert service["environment"]["REDIS_PASSWORD_FILE"] == (
            "/run/secrets/redis_password"
        )
        assert service["environment"]["REDIS_URL"] == "redis://redis:6379/0"
        assert service["environment"]["CELERY_BROKER_URL"] == ""
        assert service["environment"]["CELERY_RESULT_BACKEND"] == ""
        assert service["environment"]["NURA_CELERY_BROKER_URL"] == (
            "redis://redis:6379/1"
        )
        assert service["environment"]["NURA_CELERY_RESULT_BACKEND"] == (
            "redis://redis:6379/2"
        )

    inspectable = repr({"command": redis["command"], "healthcheck": redis["healthcheck"]})
    assert "REDIS_PASSWORD" not in inspectable
    assert "--requirepass" not in inspectable
    assert "'-a'" not in inspectable


def test_neutral_celery_transport_inputs_avoid_cli_environment_override(
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "redis_password"
    secret_file.write_text("integration-password", encoding="utf-8")

    settings = Settings(
        _env_file=None,
        redis_password_file=str(secret_file),
        redis_url="redis://redis:6379/0",
        NURA_CELERY_BROKER_URL="redis://redis:6379/1",
        NURA_CELERY_RESULT_BACKEND="redis://redis:6379/2",
    )

    assert unquote(urlsplit(settings.celery_broker_url).password or "") == (
        "integration-password"
    )
    assert unquote(urlsplit(settings.celery_result_backend).password or "") == (
        "integration-password"
    )


def test_redis_helpers_read_only_the_secret_file_at_runtime() -> None:
    entrypoint = (APP_ROOT / "scripts" / "redis-entrypoint.sh").read_text("utf-8")
    healthcheck = (APP_ROOT / "scripts" / "redis-healthcheck.sh").read_text("utf-8")

    assert "/run/secrets/redis_password" in entrypoint
    assert "/run/secrets/redis_password" not in healthcheck
    assert "${REDIS_PASSWORD}" not in entrypoint
    assert "${REDIS_PASSWORD}" not in healthcheck
    assert "redis-cli -a" not in healthcheck
    assert "REDISCLI_AUTH" not in healthcheck
    assert "--askpass" not in healthcheck
    assert "requirepass" in entrypoint
    assert "NOAUTH Authentication required." in healthcheck
    assert "$()" not in healthcheck


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are unavailable")
def test_redis_healthcheck_bind_mount_does_not_require_executable_mode() -> None:
    helper = APP_ROOT / "scripts" / "redis-healthcheck.sh"
    compose = yaml.safe_load((APP_ROOT / "docker-compose.yml").read_text("utf-8"))

    assert helper.stat().st_mode & 0o111 == 0
    assert compose["services"]["redis"]["healthcheck"]["test"] == [
        "CMD",
        "/bin/sh",
        "/usr/local/bin/nura-redis-healthcheck",
    ]


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("sh") is None,
    reason="POSIX direct-exec semantics are unavailable",
)
def test_nonexecutable_redis_healthcheck_reproduces_direct_exec_126() -> None:
    helper = APP_ROOT / "scripts" / "redis-healthcheck.sh"

    result = subprocess.run(
        ["sh", "-c", '"$1"', "sh", str(helper)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 126
    assert "permission denied" in result.stderr.lower()


def test_redis_helpers_use_linux_line_endings() -> None:
    for helper_name in ("redis-entrypoint.sh", "redis-healthcheck.sh"):
        assert b"\r\n" not in (APP_ROOT / "scripts" / helper_name).read_bytes()


def fake_redis_cli(tmp_path: Path) -> tuple[Path, Path]:
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    argument_capture = tmp_path / "redis-cli-arguments"
    executable = binary_directory / "redis-cli"
    executable.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$@" > "$ARG_CAPTURE"\n'
        'if [ "$1" != "--no-auth-warning" ] || [ "$2" != "ping" ]; then\n'
        '    echo "NOAUTH Authentication required." >&2\n'
        "    exit 1\n"
        "fi\n"
        'echo "NOAUTH Authentication required." >&2\n'
        "exit 1\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    return binary_directory, argument_capture


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("sh") is None,
    reason="POSIX executable and PATH semantics are unavailable",
)
def test_redis_healthcheck_is_secret_free_liveness_probe(
    tmp_path: Path,
) -> None:
    binary_directory, argument_capture = fake_redis_cli(tmp_path)
    environment = os.environ | {
        "ARG_CAPTURE": str(argument_capture),
        "PATH": f"{binary_directory}{os.pathsep}{os.environ.get('PATH', '')}",
    }

    result = subprocess.run(
        ["sh", str(APP_ROOT / "scripts" / "redis-healthcheck.sh")],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    arguments = argument_capture.read_text(encoding="utf-8")
    assert arguments.splitlines() == ["--no-auth-warning", "ping"]


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("sh") is None,
    reason="POSIX executable and PATH semantics are unavailable",
)
def test_redis_healthcheck_requires_noauth_response(
    tmp_path: Path,
) -> None:
    binary_directory, _ = fake_redis_cli(tmp_path)
    environment = os.environ | {
        "ARG_CAPTURE": str(tmp_path / "args"),
        "PATH": f"{binary_directory}{os.pathsep}{os.environ.get('PATH', '')}",
    }

    result = subprocess.run(
        ["sh", str(APP_ROOT / "scripts" / "redis-healthcheck.sh")],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0


@pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX shell is unavailable")
@pytest.mark.parametrize(
    "helper_name", ["redis-entrypoint.sh"]
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
