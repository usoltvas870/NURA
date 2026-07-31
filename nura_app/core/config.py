import os
import re
import stat
from urllib.parse import quote, quote_plus, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings


SUPPORTED_APP_ENVIRONMENTS = frozenset(
    {"development", "test", "staging", "sandbox", "production"}
)
INSECURE_SECRET_KEYS = frozenset(
    {"change-me", "change-me-to-a-random-string-64-chars-min"}
)

NURA_TG_RUNTIME_PROFILE = "nura_tg"
NURA_TG_DATABASE_URL_FILE = "/run/secrets/database_url"
NURA_TG_REDIS_PASSWORD_FILE = "/run/secrets/redis_password"
SUPPORTED_RUNTIME_PROFILES = frozenset({"legacy", NURA_TG_RUNTIME_PROFILE})
RUNTIME_PROFILE_ALIASES = {"pilot": NURA_TG_RUNTIME_PROFILE}


def _read_secret_fd(path: str, label: str) -> str:
    """Read one regular, non-linked secret file through its checked descriptor."""
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or (
                    os.name != "nt"
                    and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
                )
            ):
                raise ValueError(f"{label}_file_unsafe")
            value = os.read(descriptor, info.st_size + 1).decode("utf-8")
        finally:
            os.close(descriptor)
    except ValueError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"{label}_file_unreadable") from exc
    if not value or "\n" in value or "\r" in value or "\x00" in value:
        raise ValueError(f"{label}_file_invalid")
    return value


def _read_secret_file(path: str, label: str) -> str:
    return _read_secret_fd(path, label)


def is_production_environment(app_env: str) -> bool:
    return app_env == "production"


def redis_url_has_credentials(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return parsed.scheme in {"redis", "rediss"} and bool(parsed.password)


def redis_url_with_password(url: str, password: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        raise ValueError("invalid_redis_url")
    username = quote(parsed.username or "", safe="")
    credential = f"{username}:{quote(password, safe='')}"
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit(
        (parsed.scheme, f"{credential}@{host}{port}", parsed.path, parsed.query, "")
    )


class Settings(BaseSettings):
    app_env: str = "development"
    secret_key: str = "change-me"
    secret_key_file: str | None = None

    # Database
    postgres_user: str = "nura"
    postgres_password: str = "nura"
    postgres_db: str = "nura"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    database_url_file: str | None = None
    runtime_profile: str = Field(
        default="legacy",
        validation_alias=AliasChoices(
            "NURA_RUNTIME_PROFILE",
            "RUNTIME_PROFILE",
            "runtime_profile",
        ),
    )

    @property
    def database_url(self) -> str:
        if self.database_url_file:
            return _read_secret_file(self.database_url_file, "database_url")
        encoded_password = quote_plus(self.postgres_password)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:"
            f"{encoded_password}@{self.postgres_host}:"
            f"{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        if self.database_url_file:
            return _read_secret_file(self.database_url_file, "database_url").replace("+asyncpg", "")
        encoded_password = quote_plus(self.postgres_password)
        return (
            f"postgresql://{self.postgres_user}:"
            f"{encoded_password}@{self.postgres_host}:"
            f"{self.postgres_port}/{self.postgres_db}"
        )

    # Redis
    redis_password_file: str | None = None
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = Field(
        default="redis://localhost:6379/1",
        validation_alias=AliasChoices(
            "NURA_CELERY_BROKER_URL",
            "CELERY_BROKER_URL",
            "celery_broker_url",
        ),
    )
    celery_result_backend: str = Field(
        default="redis://localhost:6379/2",
        validation_alias=AliasChoices(
            "NURA_CELERY_RESULT_BACKEND",
            "CELERY_RESULT_BACKEND",
            "celery_result_backend",
        ),
    )
    celery_task_queue: str = "celery"
    nura_tg_pilot: bool = False

    # Report generation scheduling
    report_generation_dispatch_interval_seconds: int = Field(
        default=60, ge=15, le=300
    )
    report_generation_dispatch_limit: int = Field(
        default=20, ge=1, le=100
    )
    report_generation_reconciliation_interval_seconds: int = Field(
        default=300, ge=60, le=1800
    )
    report_generation_reconciliation_limit: int = Field(
        default=50, ge=1, le=200
    )

    # DeepSeek AI
    deepseek_api_key: str | None = None
    deepseek_api_key_file: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    report_prompt_bundle_version: str = "v1"
    chat_prompt_bundle_version: str = "v1"

    # Chat
    chat_free_message_limit: int = Field(default=5, ge=1, le=100)
    chat_quota_timezone: str = "Europe/Moscow"
    enable_expanded_tarot: bool = False
    enable_compatibility: bool = False
    enable_referral_promotion: bool = False
    default_daily_tarot_timezone: str = "Europe/Moscow"
    daily_tarot_claim_timeout_seconds: int = Field(default=900, ge=60, le=3600)

    # Telegram
    telegram_bot_token: str | None = None
    telegram_bot_token_file: str | None = None
    telegram_polling_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "NURA_TG_POLLING_ENABLED",
            "TELEGRAM_POLLING_ENABLED",
            "telegram_polling_enabled",
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _reject_plaintext_pilot_token(cls, values: object) -> object:
        if not isinstance(values, dict):
            return values
        pilot = values.get("nura_tg_pilot", values.get("NURA_TG_PILOT", False))
        profile = values.get("runtime_profile", values.get("NURA_RUNTIME_PROFILE", "legacy"))
        profile = RUNTIME_PROFILE_ALIASES.get(profile, profile)
        direct = values.get("telegram_bot_token", values.get("TELEGRAM_BOT_TOKEN"))
        database_url = values.get("database_url", values.get("DATABASE_URL"))
        if pilot and direct:
            raise ValueError("pilot_plaintext_telegram_token_forbidden")
        if pilot and database_url:
            raise ValueError("pilot_plaintext_database_url_forbidden")
        database_url_file = values.get("database_url_file", values.get("DATABASE_URL_FILE"))
        if profile == NURA_TG_RUNTIME_PROFILE:
            if database_url:
                raise ValueError("nura_tg_plaintext_database_url_forbidden")
            if database_url_file != NURA_TG_DATABASE_URL_FILE:
                raise ValueError("nura_tg_database_url_file_required")
        app_env = values.get("app_env", values.get("APP_ENV", "development"))
        if app_env == "sandbox":
            plaintext_fields = (
                ("SECRET_KEY", "secret_key", "sandbox_plaintext_secret_key_forbidden"),
                (
                    "TELEGRAM_BOT_TOKEN",
                    "telegram_bot_token",
                    "sandbox_plaintext_telegram_token_forbidden",
                ),
                (
                    "DEEPSEEK_API_KEY",
                    "deepseek_api_key",
                    "sandbox_plaintext_deepseek_key_forbidden",
                ),
                (
                    "YOOKASSA_SECRET_KEY",
                    "yookassa_secret_key",
                    "sandbox_plaintext_yookassa_key_forbidden",
                ),
                (
                    "DATABASE_URL",
                    "database_url",
                    "sandbox_plaintext_database_url_forbidden",
                ),
                (
                    "POSTGRES_PASSWORD",
                    "postgres_password",
                    "sandbox_plaintext_postgres_password_forbidden",
                ),
            )
            for env_name, field_name, error_code in plaintext_fields:
                if values.get(field_name, values.get(env_name)) not in (None, ""):
                    raise ValueError(error_code)
            redis_urls = (
                ("REDIS_URL", "redis_url"),
                ("NURA_CELERY_BROKER_URL", "celery_broker_url"),
                ("NURA_CELERY_RESULT_BACKEND", "celery_result_backend"),
            )
            for env_name, field_name in redis_urls:
                raw_url = values.get(field_name, values.get(env_name))
                if not isinstance(raw_url, str) or not raw_url:
                    continue
                try:
                    parsed = urlsplit(raw_url)
                except ValueError as exc:
                    raise ValueError("sandbox_redis_url_invalid") from exc
                if parsed.query or parsed.fragment:
                    raise ValueError("sandbox_redis_url_query_forbidden")
                if parsed.username is not None or parsed.password is not None:
                    raise ValueError("sandbox_plaintext_redis_credentials_forbidden")
        return values
    bot_username: str | None = None
    telegram_document_max_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    telegram_delivery_claim_timeout_seconds: int = Field(default=900, ge=60, le=3600)
    chat_delivery_result_ttl_seconds: int = Field(default=86400, ge=3600, le=7 * 86400)
    broadcast_admin_telegram_ids: str = ""
    broadcast_frequency_max: int = Field(default=3, ge=1, le=20)
    broadcast_frequency_window_days: int = Field(default=7, ge=1, le=30)
    broadcast_attribution_window_days: int = Field(default=7, ge=1, le=30)
    broadcast_selection_batch_size: int = Field(default=500, ge=10, le=5000)
    broadcast_delivery_batch_size: int = Field(default=100, ge=1, le=1000)
    broadcast_delivery_concurrency: int = Field(default=5, ge=1, le=20)
    broadcast_retry_max_attempts: int = Field(default=5, ge=1, le=20)
    broadcast_retry_max_seconds: int = Field(default=3600, ge=30, le=86400)

    @model_validator(mode="after")
    def _load_telegram_token_file(self) -> "Settings":
        if not self.telegram_bot_token_file:
            return self
        self.telegram_bot_token = _read_secret_file(
            self.telegram_bot_token_file, "telegram_bot_token"
        )
        return self

    @model_validator(mode="after")
    def _require_pilot_secret_contract(self) -> "Settings":
        """Pilot credentials must enter only through the read-only secret file."""
        if self.runtime_profile == NURA_TG_RUNTIME_PROFILE:
            if self.database_url_file != NURA_TG_DATABASE_URL_FILE:
                raise ValueError("nura_tg_database_url_file_required")
            _read_secret_file(self.database_url_file, "database_url")
        if not self.nura_tg_pilot:
            return self
        if not self.telegram_bot_token_file or not self.telegram_bot_token:
            raise ValueError("pilot_telegram_token_file_required")
        return self

    @property
    def payments_enabled(self) -> bool:
        """The isolated Telegram pilot is intentionally sandbox-only."""
        return not self.nura_tg_pilot

    # Admin Bot
    admin_bot_token: str | None = None
    admin_telegram_id: int | None = None

    @property
    def broadcast_admin_ids(self) -> tuple[int, ...]:
        values: set[int] = set()
        if self.admin_telegram_id is not None and self.admin_telegram_id > 0:
            values.add(self.admin_telegram_id)
        for raw in self.broadcast_admin_telegram_ids.split(","):
            item = raw.strip()
            if item:
                parsed = int(item)
                if not 0 < parsed < 2**63:
                    raise ValueError("invalid_broadcast_admin_telegram_id")
                values.add(parsed)
        return tuple(sorted(values))

    # YooKassa
    yookassa_shop_id: str | None = None
    yookassa_secret_key: str | None = None
    yookassa_secret_key_file: str | None = None
    yookassa_verify_on_webhook: bool = True
    yookassa_expect_test_mode: bool = False
    enable_internal_payment_shortcut: bool = False
    yookassa_ip_whitelist: str = ""
    # Fiscal receipt. Values are deliberately unset until the merchant confirms
    # its YooKassa / tax configuration; payment creation then fails closed.
    yookassa_receipt_enabled: bool = False
    yookassa_receipt_vat_code: str | None = None
    yookassa_receipt_payment_mode: str | None = None
    yookassa_receipt_payment_subject: str | None = None
    payment_event_claim_ttl_seconds: int = Field(default=300, ge=30, le=3600)

    @property
    def is_production(self) -> bool:
        return is_production_environment(self.app_env)

    @property
    def is_sandbox(self) -> bool:
        return self.app_env == "sandbox"

    @property
    def payment_webhook_configuration_error(self) -> str | None:
        """Return a non-sensitive payment-webhook readiness failure, if any."""
        if not self.is_production:
            return None
        if not self.yookassa_verify_on_webhook:
            return "production_payment_webhook_verification_required"
        if not self.yookassa_shop_id or not self.yookassa_secret_key:
            return "production_payment_webhook_credentials_required"
        return None

    @property
    def yookassa_receipt_configuration_error(self) -> str | None:
        if not self.yookassa_receipt_enabled:
            return "yookassa_receipt_enabled_required"
        if not self.yookassa_receipt_vat_code:
            return "yookassa_receipt_vat_code_required"
        if not self.yookassa_receipt_payment_mode:
            return "yookassa_receipt_payment_mode_required"
        if not self.yookassa_receipt_payment_subject:
            return "yookassa_receipt_payment_subject_required"
        return None

    @property
    def production_readiness_errors(self) -> tuple[str, ...]:
        """Return non-sensitive blockers for a controlled production switch."""
        errors: list[str] = []
        if self.secret_key in INSECURE_SECRET_KEYS or len(self.secret_key) < 32:
            errors.append("production_secret_key_required")
        if not self.session_cookie_secure:
            errors.append("production_secure_session_cookie_required")
        if self.test_mode:
            errors.append("production_test_mode_forbidden")
        if self.enable_internal_payment_shortcut:
            errors.append("production_internal_payment_shortcut_forbidden")
        if self.yookassa_expect_test_mode:
            errors.append("production_yookassa_test_mode_forbidden")
        if not self.yookassa_verify_on_webhook:
            errors.append("production_payment_webhook_verification_required")
        if not self.yookassa_shop_id or not self.yookassa_secret_key:
            errors.append("production_payment_webhook_credentials_required")
        receipt_error = self.yookassa_receipt_configuration_error
        if receipt_error:
            errors.append(receipt_error)
        if not redis_url_has_credentials(self.redis_url):
            errors.append("production_redis_auth_required")
        if not redis_url_has_credentials(self.celery_broker_url):
            errors.append("production_celery_broker_auth_required")
        if not redis_url_has_credentials(self.celery_result_backend):
            errors.append("production_celery_backend_auth_required")
        return tuple(errors)

    @model_validator(mode="after")
    def _load_redis_password_file(self) -> "Settings":
        if not self.redis_password_file:
            return self
        password = _read_secret_file(self.redis_password_file, "redis_password")
        for field_name in (
            "redis_url",
            "celery_broker_url",
            "celery_result_backend",
        ):
            url = getattr(self, field_name)
            if not redis_url_has_credentials(url):
                setattr(self, field_name, redis_url_with_password(url, password))
        return self

    @model_validator(mode="after")
    def _load_secret_files(self) -> "Settings":
        file_fields = (
            ("secret_key_file", "secret_key", "secret_key"),
            ("deepseek_api_key_file", "deepseek_api_key", "deepseek_api_key"),
            ("yookassa_secret_key_file", "yookassa_secret_key", "yookassa_secret_key"),
        )
        for path_field, value_field, label in file_fields:
            path = getattr(self, path_field)
            if path:
                setattr(self, value_field, _read_secret_file(path, label))
        return self

    @model_validator(mode="after")
    def _require_safe_production_configuration(self) -> "Settings":
        if self.is_production and self.production_readiness_errors:
            raise ValueError(";".join(self.production_readiness_errors))
        return self

    @field_validator("app_env", mode="before")
    @classmethod
    def _validate_app_env(cls, value: object) -> str:
        if not isinstance(value, str) or value not in SUPPORTED_APP_ENVIRONMENTS:
            supported = ",".join(sorted(SUPPORTED_APP_ENVIRONMENTS))
            raise ValueError(f"app_env_must_be_one_of:{supported}")
        return value

    @field_validator("runtime_profile", mode="before")
    @classmethod
    def _validate_runtime_profile(cls, value: object) -> str:
        normalized = RUNTIME_PROFILE_ALIASES.get(value, value)
        if not isinstance(normalized, str) or normalized not in SUPPORTED_RUNTIME_PROFILES:
            supported = ",".join(
                sorted(SUPPORTED_RUNTIME_PROFILES | RUNTIME_PROFILE_ALIASES.keys())
            )
            raise ValueError(f"runtime_profile_must_be_one_of:{supported}")
        return normalized

    @field_validator("chat_quota_timezone", "default_daily_tarot_timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (TypeError, ZoneInfoNotFoundError) as error:
            raise ValueError("invalid_timezone") from error
        return value

    @field_validator("report_prompt_bundle_version", "chat_prompt_bundle_version")
    @classmethod
    def _validate_prompt_bundle_version(cls, value: str) -> str:
        if not re.fullmatch(r"v[1-9][0-9]*", value):
            raise ValueError("invalid_prompt_bundle_version")
        return value

    @field_validator("broadcast_admin_telegram_ids")
    @classmethod
    def _validate_broadcast_admin_ids(cls, value: str) -> str:
        for raw in value.split(","):
            item = raw.strip()
            if not item:
                continue
            if not item.isdigit() or not 0 < int(item) < 2**63:
                raise ValueError("invalid_broadcast_admin_telegram_id")
        return value

    @property
    def yookassa_ip_whitelist_list(self) -> list[str]:
        return [
            s.strip()
            for s in self.yookassa_ip_whitelist.split(",")
            if s.strip()
        ]

    # Report
    report_base_url: str = "https://nura-ai.ru"
    report_token_ttl_days: int = 90
    cors_allowed_origins: str = "https://nura-ai.ru,https://www.nura-ai.ru"

    # Fail-closed external sandbox profile. These values are inert outside
    # APP_ENV=sandbox and are validated by one canonical startup gate.
    sandbox_environment_id: str | None = None
    sandbox_public_base_url: str | None = None
    sandbox_expected_hostname: str | None = None
    sandbox_expected_alembic_head: str | None = None
    sandbox_expected_database_host: str | None = None
    sandbox_expected_database_port: int | None = Field(default=None, ge=1, le=65535)
    sandbox_expected_database_name: str | None = None
    sandbox_expected_redis_host: str | None = None
    sandbox_expected_redis_port: int | None = Field(default=None, ge=1, le=65535)
    sandbox_expected_redis_data_db: int | None = Field(default=None, ge=0, le=15)
    sandbox_expected_redis_broker_db: int | None = Field(default=None, ge=0, le=15)
    sandbox_expected_redis_backend_db: int | None = Field(default=None, ge=0, le=15)
    sandbox_telegram_allowed_user_ids: str = ""
    sandbox_telegram_bot_id: int | None = None
    sandbox_telegram_bot_username: str | None = None
    sandbox_telegram_identity_evidence_file: str | None = None
    sandbox_yookassa_expected_shop_id: str | None = None
    sandbox_yookassa_identity_evidence_file: str | None = None
    sandbox_ai_allowed_base_url: str | None = None
    sandbox_ai_allowed_model: str | None = None
    sandbox_ai_max_external_calls: int = Field(default=0, ge=0, le=100_000)
    sandbox_ai_max_total_tokens: int = Field(default=0, ge=0, le=100_000_000)
    sandbox_redis_key_prefix: str | None = None
    sandbox_evidence_owner: str | None = None
    sandbox_cleanup_owner: str | None = None
    sandbox_ingress_contract_file: str | None = None

    @property
    def cors_allowed_origins_list(self) -> tuple[str, ...]:
        return tuple(
            item.strip().rstrip("/")
            for item in self.cors_allowed_origins.split(",")
            if item.strip()
        )

    @property
    def sandbox_telegram_allowed_ids(self) -> tuple[int, ...]:
        values: set[int] = set()
        for raw in self.sandbox_telegram_allowed_user_ids.split(","):
            item = raw.strip()
            if not item:
                continue
            if not item.isdigit() or not 0 < int(item) < 2**63:
                raise ValueError("sandbox_telegram_allowed_user_ids_invalid")
            values.add(int(item))
        return tuple(sorted(values))

    # Pricing
    tarot_subscription_price_rub: int = 390
    matrix_one_time_price_rub: int = 890

    # Web Push (VAPID)
    vapid_private_key: str | None = None
    vapid_public_key: str | None = None
    vapid_claims_email: str = "admin@nura-ai.ru"

    # Web session
    web_session_ttl_seconds: int = 7776000  # 90 days
    session_cookie_secure: bool = True

    # Auth & retention
    smtp_host: str = "smtp.beget.com"
    smtp_port: int = 465
    smtp_secure: bool = True
    smtp_user: str = "noreply@nura-ai.ru"
    smtp_password: str = ""
    smtp_from: str = "NURA <noreply@nura-ai.ru>"
    unisender_api_key: str = ""  # deprecated, replaced by SMTP
    sms_ru_api_id: str = ""  # deprecated, SMS auth removed
    vk_client_id: str = ""
    vk_client_secret: str = ""
    vk_redirect_uri: str = "https://nura-ai.ru/vk-callback.html"
    guest_profile_ttl_days: int = 30
    magic_link_ttl_minutes: int = 15
    sms_code_ttl_minutes: int = 5  # deprecated, SMS auth removed

    # Admin Panel
    admin_token: str | None = None

    # Sentry
    sentry_dsn: str | None = None

    # Test mode bypass (WARNING: only for dev)
    test_mode: bool = False

    @field_validator("vapid_private_key", "vapid_public_key", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v):
        """Convert empty string from .env to None."""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "hide_input_in_errors": True,
        "populate_by_name": True,
    }

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings,
    ):
        """Disable dotenv unconditionally for sandbox and isolated local harnesses."""
        init_kwargs = getattr(init_settings, "init_kwargs", {})
        initial_app_env = init_kwargs.get("app_env") if isinstance(init_kwargs, dict) else None
        environment_app_env = os.environ.get("APP_ENV")
        if (
            initial_app_env == "sandbox"
            or environment_app_env == "sandbox"
            or os.environ.get("NURA_DISABLE_DOTENV") == "1"
        ):
            return init_settings, env_settings, file_secret_settings
        return init_settings, env_settings, dotenv_settings, file_secret_settings


settings = Settings()
