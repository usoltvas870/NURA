"""Fail-closed contracts for the future external NURA sandbox.

The static profile validator is deliberately offline. External Telegram and
YooKassa identities are separate, explicit evidence gates used only immediately
before polling or payment-provider execution.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from sqlalchemy import text

from core.config import Settings, _read_secret_file


SANDBOX_ALEMBIC_HEAD = "d8e9f0a1b2c3"
SANDBOX_PUBLIC_INGRESS_PATHS = (
    "/health",
    "/ready",
    "/api/v1/payment/webhook",
    "/api/v1/payment/full-matrix/checkout/{public_id}",
    "/api/v1/payment/full-matrix/return/{public_id}",
)
_ENVIRONMENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{5,47}$")
_BOT_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_BANNED_ENVIRONMENT_IDS = frozenset({"production", "prod", "main"})
_SECRET_MARKERS = ("secret", "token", "password", "passwd", "api-key", "apikey")
_PRODUCTION_HOSTNAMES = frozenset({"nura-ai.ru", "www.nura-ai.ru"})
_PRODUCTION_AI_HOSTNAMES = frozenset({"api.deepseek.com"})
_PRODUCTION_RESOURCE_MARKER_RE = re.compile(
    r"(?:^|[._-])(prod|production|main)(?:[._-]|$)"
)
_SANDBOX_CAPABILITY_PATH_RE = re.compile(
    r"^/api/v1/payment/full-matrix/(checkout|return)/[A-Za-z0-9_-]{40,64}$"
)


@dataclass(frozen=True)
class SandboxGate:
    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "gate": self.name,
            "status": "PASS" if self.passed else "FAIL",
            "detail": self.detail,
        }


class SandboxConfigurationError(RuntimeError):
    """Bounded startup failure that never contains a credential or endpoint."""

    def __init__(self, gate: str) -> None:
        self.gate = gate
        super().__init__(f"sandbox_startup_gate_failed:{gate}")


class SandboxIdentityError(RuntimeError):
    """Typed external-identity blocker with a bounded non-sensitive code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AsyncSqlExecutor(Protocol):
    async def execute(self, statement: object) -> object: ...


def _gate(name: str, passed: bool, detail: str = "contract_satisfied") -> SandboxGate:
    return SandboxGate(name=name, passed=passed, detail=detail if passed else f"{name}_invalid")


def _safe_url(value: str | None) -> tuple[str, str, str] | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname.endswith(".")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        return None
    origin = f"https://{parsed.hostname}"
    if port is not None:
        origin += f":{port}"
    return origin, parsed.hostname.casefold(), parsed.scheme


def _safe_https_endpoint(value: str | None) -> bool:
    if not value:
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.hostname.endswith(".")
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and parsed.hostname.casefold() not in {"localhost", "127.0.0.1", "::1"}
    )


def _production_ai_endpoint(value: str | None) -> bool:
    if not value:
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        hostname = (parsed.hostname or "").casefold().rstrip(".")
    except ValueError:
        return True
    return hostname in _PRODUCTION_AI_HOSTNAMES


def _production_public_hostname(hostname: str) -> bool:
    return (
        hostname in _PRODUCTION_HOSTNAMES
        or hostname.endswith(".nura-ai.ru")
        or bool(_PRODUCTION_RESOURCE_MARKER_RE.search(hostname))
    )


def _production_like_resource(value: str) -> bool:
    return bool(_PRODUCTION_RESOURCE_MARKER_RE.search(value.casefold()))


def sandbox_public_path_allowed(path: str) -> bool:
    """Enforce the executable public ingress boundary inside the API process."""

    return path in {
        "/health",
        "/ready",
        "/api/v1/payment/webhook",
    } or bool(_SANDBOX_CAPABILITY_PATH_RE.fullmatch(path))


def _url_identity(value: str) -> tuple[str, int | None, str] | None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"redis", "rediss"}
        or not parsed.hostname
        or parsed.hostname.endswith(".")
        or not parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return None
    return parsed.hostname.casefold(), port, parsed.path.lstrip("/")


def _database_identity(value: str) -> tuple[str, int | None, str] | None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "postgresql+asyncpg"
        or not parsed.hostname
        or parsed.hostname.endswith(".")
        or not parsed.username
        or not parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return None
    database = parsed.path.lstrip("/")
    if not database:
        return None
    return parsed.hostname.casefold(), port, database.casefold()


def _read_ingress_contract(path: str | None) -> tuple[str, ...] | None:
    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    paths = payload.get("public_paths") if isinstance(payload, dict) else None
    if not isinstance(paths, list) or not all(isinstance(item, str) for item in paths):
        return None
    return tuple(paths)


def sandbox_profile_gates(settings: Settings) -> tuple[SandboxGate, ...]:
    """Return every static sandbox gate without performing any network call."""

    if not settings.is_sandbox:
        return (_gate("environment", False),)

    environment_id = settings.sandbox_environment_id or ""
    environment_id_valid = bool(
        _ENVIRONMENT_ID_RE.fullmatch(environment_id)
        and environment_id not in _BANNED_ENVIRONMENT_IDS
        and not any(marker in environment_id for marker in _SECRET_MARKERS)
    )
    normalized_database_id = environment_id.replace("-", "_")
    public = _safe_url(settings.sandbox_public_base_url)
    expected_hostname = (settings.sandbox_expected_hostname or "").casefold()
    public_origin = public[0].rstrip("/") if public else ""
    public_hostname = public[1] if public else ""

    try:
        allowed_ids = settings.sandbox_telegram_allowed_ids
    except ValueError:
        allowed_ids = ()

    try:
        database_identity = _database_identity(settings.database_url)
    except ValueError:
        database_identity = None
    redis_identity = _url_identity(settings.redis_url)
    broker_identity = _url_identity(settings.celery_broker_url)
    backend_identity = _url_identity(settings.celery_result_backend)
    redis_hosts = {
        identity[0]
        for identity in (redis_identity, broker_identity, backend_identity)
        if identity is not None
    }
    sandbox_redis_host = next(iter(redis_hosts), "")

    expected_queue = f"nura-sandbox-{environment_id}" if environment_id else ""
    expected_prefix = f"sandbox:{environment_id}:" if environment_id else ""
    secrets_from_files = all(
        (
            settings.secret_key_file,
            settings.database_url_file,
            settings.redis_password_file,
            settings.telegram_bot_token_file,
            settings.deepseek_api_key_file,
            settings.yookassa_secret_key_file,
        )
    )
    production_origins = {
        "https://nura-ai.ru",
        "https://www.nura-ai.ru",
    }
    configured_origins = set(settings.cors_allowed_origins_list)
    ingress_paths = _read_ingress_contract(settings.sandbox_ingress_contract_file)

    gates = (
        _gate("environment", settings.app_env == "sandbox"),
        _gate("sandbox_environment_id", environment_id_valid),
        _gate(
            "sandbox_public_url",
            bool(
                public
                and expected_hostname == public_hostname
                and not _production_public_hostname(public_hostname)
                and public_hostname not in {"localhost", "127.0.0.1", "::1"}
            ),
        ),
        _gate(
            "report_base_url",
            bool(public and settings.report_base_url.rstrip("/") == public_origin),
        ),
        _gate(
            "cors",
            bool(
                public
                and configured_origins == {public_origin}
                and not configured_origins.intersection(production_origins)
            ),
        ),
        _gate(
            "telegram_allowlist",
            bool(
                allowed_ids
                and settings.sandbox_telegram_bot_id
                and settings.sandbox_telegram_bot_id > 0
                and settings.sandbox_telegram_bot_username
                and _BOT_USERNAME_RE.fullmatch(settings.sandbox_telegram_bot_username)
            ),
        ),
        _gate(
            "yookassa_mode",
            bool(
                not settings.enable_internal_payment_shortcut
                and settings.yookassa_expect_test_mode
                and settings.yookassa_verify_on_webhook
                and settings.sandbox_yookassa_expected_shop_id
                and settings.yookassa_shop_id
                == settings.sandbox_yookassa_expected_shop_id
                and settings.yookassa_receipt_configuration_error is None
            ),
        ),
        _gate(
            "ai_egress",
            bool(
                public
                and settings.sandbox_ai_allowed_base_url
                and _safe_https_endpoint(settings.sandbox_ai_allowed_base_url)
                and not _production_ai_endpoint(settings.sandbox_ai_allowed_base_url)
                and settings.deepseek_base_url.rstrip("/")
                == settings.sandbox_ai_allowed_base_url.rstrip("/")
                and settings.sandbox_ai_allowed_model
                and settings.deepseek_model == settings.sandbox_ai_allowed_model
                and settings.sandbox_ai_max_external_calls > 0
                and settings.sandbox_ai_max_total_tokens > 0
            ),
        ),
        _gate(
            "database_identity",
            bool(
                database_identity
                and settings.sandbox_expected_database_host
                and settings.sandbox_expected_database_port
                and settings.sandbox_expected_database_name
                and database_identity[0]
                == settings.sandbox_expected_database_host.casefold()
                and database_identity[1]
                == settings.sandbox_expected_database_port
                and database_identity[2]
                == settings.sandbox_expected_database_name.casefold()
                and not _production_like_resource(database_identity[0])
                and not _production_like_resource(database_identity[2])
                and normalized_database_id
                and normalized_database_id in database_identity[2]
                and database_identity[2] not in {"nura", "postgres", "production"}
            ),
        ),
        _gate(
            "redis_identity",
            bool(
                redis_identity
                and broker_identity
                and backend_identity
                and len(redis_hosts) == 1
                and settings.sandbox_expected_redis_host
                and settings.sandbox_expected_redis_port
                and sandbox_redis_host
                == settings.sandbox_expected_redis_host.casefold()
                and not _production_like_resource(sandbox_redis_host)
                and redis_identity[1]
                == settings.sandbox_expected_redis_port
                and broker_identity[1]
                == settings.sandbox_expected_redis_port
                and backend_identity[1]
                == settings.sandbox_expected_redis_port
                and redis_identity[2]
                == str(settings.sandbox_expected_redis_data_db)
                and broker_identity[2]
                == str(settings.sandbox_expected_redis_broker_db)
                and backend_identity[2]
                == str(settings.sandbox_expected_redis_backend_db)
                and len(
                    {
                        settings.sandbox_expected_redis_data_db,
                        settings.sandbox_expected_redis_broker_db,
                        settings.sandbox_expected_redis_backend_db,
                    }
                )
                == 3
                and settings.sandbox_redis_key_prefix == expected_prefix
            ),
        ),
        _gate(
            "celery_queue",
            bool(
                expected_queue
                and settings.celery_task_queue == expected_queue
                and settings.celery_task_queue != "celery"
            ),
        ),
        _gate(
            "migration_head",
            settings.sandbox_expected_alembic_head == SANDBOX_ALEMBIC_HEAD,
        ),
        _gate("secret_files", bool(secrets_from_files)),
        _gate(
            "feature_flags",
            not settings.test_mode
            and not settings.enable_expanded_tarot
            and not settings.enable_compatibility
            and not settings.enable_referral_promotion,
        ),
        _gate(
            "ingress_contract",
            ingress_paths == SANDBOX_PUBLIC_INGRESS_PATHS,
        ),
        _gate(
            "evidence_ownership",
            bool(
                settings.sandbox_evidence_owner
                and len(settings.sandbox_evidence_owner) <= 100
                and settings.sandbox_cleanup_owner
                and len(settings.sandbox_cleanup_owner) <= 100
            ),
        ),
    )
    return gates


def validate_sandbox_startup(settings: Settings) -> None:
    """Apply the same static profile gate to API, bot, worker and Beat."""

    if not settings.is_sandbox:
        return
    for gate in sandbox_profile_gates(settings):
        if not gate.passed:
            raise SandboxConfigurationError(gate.name)


async def validate_sandbox_database_head(
    executor: AsyncSqlExecutor,
    settings: Settings,
) -> None:
    """Fail closed when the connected sandbox database is not at the pinned head."""

    if not settings.is_sandbox:
        return
    try:
        result = await executor.execute(text("SELECT version_num FROM alembic_version"))
        versions = tuple(result.scalars().all())  # type: ignore[attr-defined]
    except Exception as exc:
        raise SandboxConfigurationError("migration_head") from exc
    validate_sandbox_database_versions(versions, settings)


def validate_sandbox_database_versions(
    versions: tuple[str, ...],
    settings: Settings,
) -> None:
    """Validate versions obtained through either an async or sync DB boundary."""

    if not settings.is_sandbox:
        return
    if versions != (settings.sandbox_expected_alembic_head,):
        raise SandboxConfigurationError("migration_head")


def validate_telegram_identity(
    *,
    expected_bot_id: int,
    expected_username: str,
    actual_bot_id: int,
    actual_username: str,
) -> None:
    """Pure identity comparison used by fake and future external verifiers."""

    if (
        actual_bot_id != expected_bot_id
        or actual_username.lstrip("@").casefold()
        != expected_username.lstrip("@").casefold()
    ):
        raise SandboxIdentityError("sandbox_telegram_identity_mismatch")


def validate_yookassa_identity(
    *,
    expected_shop_id: str,
    expected_test_mode: bool,
    actual_shop_id: str,
    actual_test_mode: bool,
    receipt_configured: bool,
    allowed_hostname: str,
    actual_hostname: str,
) -> None:
    """Pure YooKassa identity comparison without retaining provider payloads."""

    if (
        actual_shop_id != expected_shop_id
        or actual_test_mode is not expected_test_mode
        or not receipt_configured
        or actual_hostname.casefold() != allowed_hostname.casefold()
    ):
        raise SandboxIdentityError("sandbox_yookassa_identity_mismatch")


def _identity_evidence(path: str | None, label: str) -> dict:
    if not path:
        raise SandboxIdentityError(f"{label}_evidence_required")
    try:
        payload = json.loads(_read_secret_file(path, f"{label}_evidence"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise SandboxIdentityError(f"{label}_evidence_invalid") from exc
    if not isinstance(payload, dict) or payload.get("status") != "verified":
        raise SandboxIdentityError(f"{label}_evidence_invalid")
    return payload


def require_telegram_identity_evidence(settings: Settings) -> None:
    if not settings.is_sandbox:
        return
    evidence = _identity_evidence(
        settings.sandbox_telegram_identity_evidence_file, "sandbox_telegram_identity"
    )
    if evidence.get("environment_id") != settings.sandbox_environment_id:
        raise SandboxIdentityError("sandbox_telegram_identity_environment_mismatch")
    try:
        actual_bot_id = int(evidence.get("bot_id"))
    except (TypeError, ValueError) as exc:
        raise SandboxIdentityError("sandbox_telegram_identity_evidence_invalid") from exc
    validate_telegram_identity(
        expected_bot_id=int(settings.sandbox_telegram_bot_id or 0),
        expected_username=settings.sandbox_telegram_bot_username or "",
        actual_bot_id=actual_bot_id,
        actual_username=str(evidence.get("bot_username") or ""),
    )


def require_yookassa_identity_evidence(settings: Settings) -> None:
    if not settings.is_sandbox:
        return
    evidence = _identity_evidence(
        settings.sandbox_yookassa_identity_evidence_file, "sandbox_yookassa_identity"
    )
    if evidence.get("environment_id") != settings.sandbox_environment_id:
        raise SandboxIdentityError("sandbox_yookassa_identity_environment_mismatch")
    expected_shop = settings.sandbox_yookassa_expected_shop_id or ""
    expected_hash = hashlib.sha256(expected_shop.encode("utf-8")).hexdigest()
    if evidence.get("shop_id_sha256") != expected_hash:
        raise SandboxIdentityError("sandbox_yookassa_identity_mismatch")
    validate_yookassa_identity(
        expected_shop_id=expected_hash,
        expected_test_mode=settings.yookassa_expect_test_mode,
        actual_shop_id=str(evidence.get("shop_id_sha256") or ""),
        actual_test_mode=evidence.get("test_mode"),
        receipt_configured=evidence.get("receipt_configured") is True,
        allowed_hostname=settings.sandbox_expected_hostname or "",
        actual_hostname=str(evidence.get("hostname") or ""),
    )
