"""Offline production owner-prelaunch readiness and Compose secret topology."""

import os
from pathlib import Path

from tools.current_vps_prelaunch_preflight import SECRET_CONTRACTS, run_preflight


ROOT = Path(__file__).resolve().parents[1]


def materialize_environment(tmp_path: Path, *extra: str) -> Path:
    source = (ROOT / ".env.prelaunch.example").read_text(encoding="utf-8")
    source = source.replace("PRELAUNCH_TELEGRAM_ALLOWED_USER_IDS=", "PRELAUNCH_TELEGRAM_ALLOWED_USER_IDS=101")
    source = source.replace("ADMIN_TELEGRAM_ID=", "ADMIN_TELEGRAM_ID=101")
    path = tmp_path / ".env"
    path.write_text(source + "".join(f"\n{line}" for line in extra) + "\n", encoding="utf-8")
    return path


def materialize_secrets(tmp_path: Path) -> Path:
    directory = tmp_path / "secrets"
    directory.mkdir()
    if os.name != "nt":
        directory.chmod(0o700)
    values = {
        "postgres_password": "fixture-postgres-password-2026",
        "secret_key": "s" * 48,
        "database_url": "postgresql+asyncpg://nura:fixture-postgres-password-2026@postgres:5432/nura",
        "redis_password": "fixture-redis-password-2026",
        "telegram_bot_token": "123456:" + "T" * 40,
        "deepseek_api_key": "sk-" + "D" * 32,
        "vapid_private_key": "V" * 48,
        "admin_bot_token": "654321:" + "A" * 40,
        "admin_token": "N" * 48,
        "smtp_password": "fixture-smtp-password",
        "vk_client_secret": "fixture-vk-client-secret",
    }
    for contract in SECRET_CONTRACTS:
        value = values[contract.name]
        path = directory / contract.name
        path.write_text(value, encoding="utf-8")
        if os.name != "nt":
            path.chmod(0o600)
    return directory


def preflight(tmp_path: Path, env_file: Path, secrets_dir: Path) -> dict[str, object]:
    owner = 0 if not hasattr(os, "geteuid") else os.geteuid()
    return run_preflight(
        env_file=env_file,
        compose_file=ROOT / "docker-compose.yml",
        secrets_dir=secrets_dir,
        versions_dir=ROOT / "alembic" / "versions",
        allowed_owner_ids=frozenset({owner}),
    )


def test_valid_owner_prelaunch_is_offline_ready(tmp_path: Path) -> None:
    result = preflight(tmp_path, materialize_environment(tmp_path), materialize_secrets(tmp_path))
    assert result["result"] == "READY_FOR_HOST_BACKUP_AND_RECOVERY"
    assert all(result["gates"].values())
    serialized = repr(result)
    assert "s" * 48 not in serialized
    assert "/opt/nura/secrets" not in serialized


def test_missing_or_unsafe_secret_blocks(tmp_path: Path) -> None:
    secrets = materialize_secrets(tmp_path)
    (secrets / "admin_token").unlink()
    result = preflight(tmp_path, materialize_environment(tmp_path), secrets)
    assert result["result"] == "BLOCKED"
    assert result["gates"]["secret_admin_token_unreadable"] is False


def test_semantically_invalid_database_secret_blocks_before_execution(tmp_path: Path) -> None:
    secrets = materialize_secrets(tmp_path)
    (secrets / "database_url").write_text("fixture-database_url", encoding="utf-8")
    result = preflight(tmp_path, materialize_environment(tmp_path), secrets)
    assert result["result"] == "BLOCKED"
    assert result["gates"]["database_url_semantics"] is False


def test_duplicate_lowercase_alias_blocks(tmp_path: Path) -> None:
    result = preflight(
        tmp_path,
        materialize_environment(tmp_path, "test_mode=true"),
        materialize_secrets(tmp_path),
    )
    assert result["result"] == "BLOCKED"
    assert result["gates"]["environment_conflicting_alias"] is False


def test_missing_celery_url_blocks_without_crashing(tmp_path: Path) -> None:
    environment = materialize_environment(tmp_path)
    content = environment.read_text(encoding="utf-8").replace(
        "NURA_CELERY_RESULT_BACKEND=redis://redis:6379/2\n",
        "",
    )
    environment.write_text(content, encoding="utf-8")
    result = preflight(tmp_path, environment, materialize_secrets(tmp_path))
    assert result["result"] == "BLOCKED"
    assert result["gates"]["service_settings_semantics"] is False


def test_yookassa_or_wrong_owner_blocks(tmp_path: Path) -> None:
    result = preflight(
        tmp_path,
        materialize_environment(tmp_path, "YOOKASSA_SHOP_ID=forbidden"),
        materialize_secrets(tmp_path),
    )
    assert result["result"] == "BLOCKED"
    assert result["gates"]["yookassa_absent"] is False or result["gates"]["no_plaintext_secrets"] is False


def test_compose_contains_no_fixture_secret_values(tmp_path: Path) -> None:
    secrets = materialize_secrets(tmp_path)
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for contract in SECRET_CONTRACTS:
        assert str(secrets / contract.name) not in compose
    assert "YOOKASSA_SECRET_KEY" not in compose
    assert "POSTGRES_PASSWORD:" not in compose
