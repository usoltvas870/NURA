#!/usr/bin/env python3
"""Offline, redacted readiness gate for the current-VPS owner prelaunch."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlsplit

import yaml

from core.config import Settings, _read_multiline_secret_file, _read_secret_file
from core.services.prompt_governance import prompt_registry
from tools.current_vps_migration_contract import validate_migration_contract


SECRET_PROFILE_VERSION = "production-files-v1"
PRODUCTION_SECRET_DIRECTORY = Path("/opt/nura/secrets/production")
EXPECTED_ALEMBIC_HEAD = "d8e9f0a1b2c3"
APP_SERVICES_FOR_SETTINGS = ("api", "bot", "celery-worker", "celery-beat", "admin-bot")


@dataclass(frozen=True)
class SecretContract:
    name: str
    multiline: bool
    consumers: tuple[str, ...]


SECRET_CONTRACTS = (
    SecretContract("postgres_password", False, ("postgres",)),
    SecretContract("secret_key", False, ("api", "bot", "celery-worker", "celery-beat", "admin-bot")),
    SecretContract("database_url", False, ("api", "bot", "celery-worker", "celery-beat", "admin-bot")),
    SecretContract("redis_password", False, ("redis", "api", "bot", "celery-worker", "celery-beat", "admin-bot")),
    SecretContract("telegram_bot_token", False, ("api", "bot", "celery-worker")),
    SecretContract("deepseek_api_key", False, ("api", "bot", "celery-worker", "admin-bot")),
    SecretContract("vapid_private_key", True, ("api", "celery-worker")),
    SecretContract("admin_bot_token", False, ("celery-worker", "admin-bot")),
    SecretContract("admin_token", False, ("api",)),
    SecretContract("smtp_password", False, ("celery-worker",)),
    SecretContract("vk_client_secret", False, ("api",)),
)

DIRECT_SECRET_KEYS = frozenset(
    {
        "SECRET_KEY",
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "TELEGRAM_BOT_TOKEN",
        "DEEPSEEK_API_KEY",
        "VAPID_PRIVATE_KEY",
        "ADMIN_BOT_TOKEN",
        "ADMIN_TOKEN",
        "SMTP_PASSWORD",
        "VK_CLIENT_SECRET",
        "YOOKASSA_SECRET_KEY",
    }
)


class PreflightError(RuntimeError):
    """A bounded readiness failure that never includes a secret value."""


def parse_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    folded: dict[str, tuple[str, str]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise PreflightError("environment_unreadable") from exc
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or "\x00" in line:
            raise PreflightError("environment_syntax_invalid")
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", line)
        if match is None:
            raise PreflightError("environment_syntax_invalid")
        key, value = match.groups()
        if key in values:
            raise PreflightError("environment_duplicate_key")
        folded_key = key.casefold()
        previous = folded.get(folded_key)
        if previous is not None and previous != (key, value):
            raise PreflightError("environment_conflicting_alias")
        folded[folded_key] = (key, value)
        values[key] = value
    return values


def _exact_environment_gates(values: dict[str, str]) -> dict[str, bool]:
    owner = values.get("PRELAUNCH_TELEGRAM_ALLOWED_USER_IDS", "")
    admin = values.get("ADMIN_TELEGRAM_ID", "")
    required = {
        "APP_ENV": "production",
        "PRELAUNCH_OWNER_ONLY": "true",
        "PAYMENTS_ENABLED": "false",
        "TEST_MODE": "false",
        "ENABLE_INTERNAL_PAYMENT_SHORTCUT": "false",
        "YOOKASSA_EXPECT_TEST_MODE": "false",
        "ENABLE_EXPANDED_TAROT": "false",
        "ENABLE_COMPATIBILITY": "false",
        "ENABLE_REFERRAL_PROMOTION": "false",
        "SESSION_COOKIE_SECURE": "true",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        "DEEPSEEK_MODEL": "deepseek-chat",
        "REPORT_PROMPT_BUNDLE_VERSION": "v1",
        "CHAT_PROMPT_BUNDLE_VERSION": "v1",
        "REPORT_BASE_URL": "https://nura-ai.ru",
        "PRODUCTION_HOSTNAME": "nura-ai.ru",
        "POSTGRES_USER": "nura",
        "POSTGRES_DB": "nura",
        "CORS_ALLOWED_ORIGINS": "https://nura-ai.ru,https://www.nura-ai.ru",
        "REDIS_URL": "redis://redis:6379/0",
        "NURA_CELERY_BROKER_URL": "redis://redis:6379/1",
        "NURA_CELERY_RESULT_BACKEND": "redis://redis:6379/2",
    }
    forbidden = bool(
        DIRECT_SECRET_KEYS.intersection(values)
        or any(key.casefold() in {item.casefold() for item in DIRECT_SECRET_KEYS} for key in values)
        or any(key.startswith("YOOKASSA_") and key != "YOOKASSA_EXPECT_TEST_MODE" for key in values)
        or any(key.endswith("_FILE") for key in values)
    )
    return {
        "environment": all(values.get(key) == expected for key, expected in required.items()),
        "owner_allowlist": bool(owner.isdigit() and admin.isdigit() and owner == admin and "," not in owner),
        "payments_disabled": values.get("PAYMENTS_ENABLED") == "false",
        "yookassa_absent": not any(key.startswith("YOOKASSA_") and key != "YOOKASSA_EXPECT_TEST_MODE" for key in values),
        "feature_flags": all(values.get(key) == "false" for key in ("ENABLE_EXPANDED_TAROT", "ENABLE_COMPATIBILITY", "ENABLE_REFERRAL_PROMOTION")),
        "no_plaintext_secrets": not forbidden,
        "redis_celery_auth_contract": all("@" not in values.get(key, "") for key in ("REDIS_URL", "NURA_CELERY_BROKER_URL", "NURA_CELERY_RESULT_BACKEND")),
        "production_public_url": values.get("REPORT_BASE_URL") == "https://nura-ai.ru",
    }


def _validate_secret_directory(
    directory: Path,
    allowed_owner_ids: frozenset[int],
) -> tuple[dict[str, bool], dict[str, str]]:
    try:
        metadata = directory.lstat()
    except OSError as exc:
        raise PreflightError("secret_directory_unreadable") from exc
    if (
        directory.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or (os.name != "nt" and stat.S_IMODE(metadata.st_mode) != 0o700)
        or (os.name != "nt" and metadata.st_uid not in allowed_owner_ids)
    ):
        raise PreflightError("secret_directory_unsafe")
    values: dict[str, str] = {}
    for contract in SECRET_CONTRACTS:
        path = directory / contract.name
        try:
            info = path.lstat()
        except OSError as exc:
            raise PreflightError(f"secret_{contract.name}_unreadable") from exc
        if (
            path.is_symlink()
            or not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or (os.name != "nt" and stat.S_IMODE(info.st_mode) not in {0o400, 0o600})
            or (os.name != "nt" and info.st_uid not in allowed_owner_ids)
        ):
            raise PreflightError(f"secret_{contract.name}_unsafe")
        reader = _read_multiline_secret_file if contract.multiline else _read_secret_file
        try:
            values[contract.name] = reader(str(path), contract.name)
        except ValueError as exc:
            raise PreflightError(str(exc)) from None
    return {"secret_directory": True, "secret_files": True}, values


def _validate_secret_semantics(
    values: dict[str, str],
    environment: dict[str, str],
    directory: Path,
) -> dict[str, bool]:
    try:
        database = urlsplit(values["database_url"])
        postgres_password = unquote(database.password or "")
        database_valid = (
            database.scheme == "postgresql+asyncpg"
            and unquote(database.username or "") == environment["POSTGRES_USER"]
            and postgres_password == values["postgres_password"]
            and database.hostname == "postgres"
            and database.port == 5432
            and database.path == f"/{environment['POSTGRES_DB']}"
            and not database.query
            and not database.fragment
        )
    except (KeyError, ValueError):
        database_valid = False
    telegram_token = re.compile(r"[1-9][0-9]{5,11}:[A-Za-z0-9_-]{30,80}\Z")
    vapid = values.get("vapid_private_key", "")
    vapid_valid = bool(
        re.fullmatch(r"[A-Za-z0-9_-]{40,256}", vapid)
        or (
            "-----BEGIN PRIVATE KEY-----" in vapid
            and "-----END PRIVATE KEY-----" in vapid
        )
    )
    semantic = {
        "database_url_semantics": database_valid,
        "secret_key_semantics": len(values.get("secret_key", "")) >= 32,
        "redis_password_semantics": len(values.get("redis_password", "")) >= 16,
        "telegram_token_semantics": bool(telegram_token.fullmatch(values.get("telegram_bot_token", ""))),
        "admin_bot_token_semantics": bool(telegram_token.fullmatch(values.get("admin_bot_token", ""))),
        "deepseek_key_semantics": bool(re.fullmatch(r"sk-[A-Za-z0-9_-]{20,200}", values.get("deepseek_api_key", ""))),
        "vapid_private_key_semantics": vapid_valid,
        "admin_token_semantics": len(values.get("admin_token", "")) >= 32,
        "smtp_password_semantics": len(values.get("smtp_password", "")) >= 8,
        "vk_client_secret_semantics": len(values.get("vk_client_secret", "")) >= 8,
    }
    if not all(semantic.values()):
        return semantic

    base: dict[str, object] = {key.lower(): value for key, value in environment.items()}
    broker = environment.get("NURA_CELERY_BROKER_URL")
    backend = environment.get("NURA_CELERY_RESULT_BACKEND")
    if not broker or not backend:
        semantic["service_settings_semantics"] = False
        return semantic
    base["celery_broker_url"] = broker
    base["celery_result_backend"] = backend
    base["telegram_polling_enabled"] = False
    field_names = {contract.name: f"{contract.name}_file" for contract in SECRET_CONTRACTS}
    field_names["secret_key"] = "secret_key_file"
    service_settings = True
    ambient = os.environ.copy()
    try:
        os.environ.clear()
        os.environ["NURA_DISABLE_DOTENV"] = "1"
        for service in APP_SERVICES_FOR_SETTINGS:
            payload = dict(base)
            for contract in SECRET_CONTRACTS:
                if service in contract.consumers:
                    payload[field_names[contract.name]] = str(directory / contract.name)
            try:
                settings = Settings(_env_file=None, **payload)
                if settings.production_readiness_errors:
                    service_settings = False
            except (RuntimeError, ValueError):
                service_settings = False
    finally:
        os.environ.clear()
        os.environ.update(ambient)
    semantic["service_settings_semantics"] = service_settings
    return semantic


def _mount_names(service: dict[str, object]) -> set[str]:
    result: set[str] = set()
    for item in service.get("secrets", []) if isinstance(service, dict) else []:
        if isinstance(item, str):
            result.add(item)
        elif isinstance(item, dict) and isinstance(item.get("source"), str):
            result.add(item["source"])
        else:
            raise PreflightError("compose_secret_mount_invalid")
    return result


def _validate_compose(path: Path) -> dict[str, bool]:
    try:
        compose = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise PreflightError("compose_unreadable") from exc
    if not isinstance(compose, dict) or not isinstance(compose.get("services"), dict):
        raise PreflightError("compose_schema_invalid")
    services = compose["services"]
    expected = {contract.name for contract in SECRET_CONTRACTS}
    declared = set((compose.get("secrets") or {}).keys())
    if declared != expected:
        raise PreflightError("compose_secret_declarations_mismatch")
    for contract in SECRET_CONTRACTS:
        declaration = compose["secrets"].get(contract.name)
        expected_path = str(PRODUCTION_SECRET_DIRECTORY / contract.name).replace("\\", "/")
        if declaration != {"file": expected_path}:
            raise PreflightError("compose_secret_source_mismatch")
    for service_name in services:
        actual = _mount_names(services[service_name])
        required = {contract.name for contract in SECRET_CONTRACTS if service_name in contract.consumers}
        if actual != required:
            raise PreflightError(f"compose_{service_name}_secret_mounts_mismatch")
    postgres = services["postgres"]
    if postgres.get("environment", {}).get("POSTGRES_PASSWORD_FILE") != "/run/secrets/postgres_password" or "POSTGRES_PASSWORD" in postgres.get("environment", {}):
        raise PreflightError("compose_postgres_secret_contract_invalid")
    redis = services["redis"]
    if redis.get("command") != ["/bin/sh", "/usr/local/bin/nura-redis-entrypoint"]:
        raise PreflightError("compose_redis_secret_contract_invalid")
    serialized = json.dumps(compose, sort_keys=True)
    if "YOOKASSA" in serialized or "RUN_MIGRATIONS\": \"1" in serialized:
        raise PreflightError("compose_prelaunch_containment_invalid")
    return {
        "compose_secret_declarations": True,
        "compose_exact_mounts": True,
        "postgres_password_file": True,
        "redis_password_file": True,
        "compose_no_yookassa": True,
        "compose_no_automatic_migrations": True,
    }


def run_preflight(
    *,
    env_file: Path,
    compose_file: Path,
    secrets_dir: Path,
    versions_dir: Path,
    allowed_owner_ids: frozenset[int],
    execution: bool = False,
    authorization_manifest: Path | None = None,
) -> dict[str, object]:
    gates: dict[str, bool] = {}
    try:
        values = parse_environment(env_file)
        gates.update(_exact_environment_gates(values))
        secret_gates, secret_values = _validate_secret_directory(
            secrets_dir,
            allowed_owner_ids,
        )
        gates.update(secret_gates)
        gates.update(_validate_secret_semantics(secret_values, values, secrets_dir))
        gates.update(_validate_compose(compose_file))
        prompt_registry.resolve("report.full", values.get("REPORT_PROMPT_BUNDLE_VERSION", ""))
        prompt_registry.resolve("chat.free", values.get("CHAT_PROMPT_BUNDLE_VERSION", ""))
        gates["prompt_bundles"] = True
        migration = validate_migration_contract(versions_dir)
        gates["target_alembic_head"] = migration["target_revision"] == EXPECTED_ALEMBIC_HEAD
        gates["release_transition_authorization"] = bool(
            not execution
            or (
                authorization_manifest is not None
                and authorization_manifest.is_file()
                and not authorization_manifest.is_symlink()
            )
        )
    except (PreflightError, RuntimeError, ValueError) as exc:
        gates.setdefault(str(exc), False)
    ready = bool(gates) and all(gates.values())
    return {
        "schema": 1,
        "secret_profile_version": SECRET_PROFILE_VERSION,
        "gates": dict(sorted(gates.items())),
        "secret_inventory": [contract.name for contract in SECRET_CONTRACTS],
        "result": "READY_FOR_HOST_BACKUP_AND_RECOVERY" if ready else "BLOCKED",
    }


def _owner_ids() -> frozenset[int]:
    return frozenset({0})


def main(argv: Iterable[str] | None = None) -> int:
    app_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=app_root / ".env")
    parser.add_argument("--compose-file", type=Path, default=app_root / "docker-compose.yml")
    parser.add_argument("--secrets-dir", type=Path, default=PRODUCTION_SECRET_DIRECTORY)
    parser.add_argument("--versions-dir", type=Path, default=app_root / "alembic" / "versions")
    parser.add_argument("--execution", action="store_true")
    parser.add_argument("--authorization-manifest", type=Path)
    args = parser.parse_args(argv)
    result = run_preflight(
        env_file=args.env_file,
        compose_file=args.compose_file,
        secrets_dir=args.secrets_dir,
        versions_dir=args.versions_dir,
        allowed_owner_ids=_owner_ids(),
        execution=args.execution,
        authorization_manifest=args.authorization_manifest,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["result"] == "READY_FOR_HOST_BACKUP_AND_RECOVERY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
