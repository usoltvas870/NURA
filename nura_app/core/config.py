from urllib.parse import quote_plus

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings


def is_production_environment(app_env: str) -> bool:
    return app_env.strip().lower() == "production"


class Settings(BaseSettings):
    app_env: str = "development"
    secret_key: str = "change-me"

    # Database
    postgres_user: str = "nura"
    postgres_password: str = "nura"
    postgres_db: str = "nura"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    @property
    def database_url(self) -> str:
        encoded_password = quote_plus(self.postgres_password)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:"
            f"{encoded_password}@{self.postgres_host}:"
            f"{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        encoded_password = quote_plus(self.postgres_password)
        return (
            f"postgresql://{self.postgres_user}:"
            f"{encoded_password}@{self.postgres_host}:"
            f"{self.postgres_port}/{self.postgres_db}"
        )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

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
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    # Telegram
    telegram_bot_token: str | None = None
    bot_username: str | None = None

    # Admin Bot
    admin_bot_token: str | None = None
    admin_telegram_id: int | None = None

    # YooKassa
    yookassa_shop_id: str | None = None
    yookassa_secret_key: str | None = None
    yookassa_verify_on_webhook: bool = True
    yookassa_ip_whitelist: str = ""

    @property
    def is_production(self) -> bool:
        return is_production_environment(self.app_env)

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

    @model_validator(mode="after")
    def _require_production_webhook_verification(self) -> "Settings":
        if self.is_production and not self.yookassa_verify_on_webhook:
            raise ValueError("production_payment_webhook_verification_required")
        return self

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

    @field_validator("test_mode", mode="before")
    @classmethod
    def _protect_test_mode(cls, v: bool, info) -> bool:
        """Принудительно False в production, что бы ни было в .env."""
        if is_production_environment(str(info.data.get("app_env", ""))):
            return False
        return v

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
    }


settings = Settings()
