from pydantic import field_validator
from pydantic_settings import BaseSettings


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
        return (
            f"postgresql+asyncpg://{self.postgres_user}:"
            f"{self.postgres_password}@{self.postgres_host}:"
            f"{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:"
            f"{self.postgres_password}@{self.postgres_host}:"
            f"{self.postgres_port}/{self.postgres_db}"
        )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # DeepSeek AI
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    # Telegram
    telegram_bot_token: str | None = None
    bot_username: str | None = None

    # YooKassa
    yookassa_shop_id: str | None = None
    yookassa_secret_key: str | None = None

    # Report
    report_base_url: str = "https://nura-ai.ru"

    # Pricing
    subscription_price_rub: int = 590
    tarot_subscription_price_rub: int = 390
    matrix_one_time_price_rub: int = 890

    # Web Push (VAPID)
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_claims_email: str = "admin@nura-ai.ru"

    # Admin Panel
    admin_token: str | None = None

    # Test mode bypass (WARNING: only for dev)
    test_mode: bool = False

    @field_validator("test_mode", mode="before")
    @classmethod
    def _protect_test_mode(cls, v: bool, info) -> bool:
        """Принудительно False в production, что бы ни было в .env."""
        if info.data.get("app_env") == "production":
            return False
        return v

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
