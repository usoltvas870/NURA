from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "NURA"
    app_env: str = "development"
    debug: bool = False
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
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_url: str = ""

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    # YooKassa
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_return_url: str = ""

    # Report
    report_base_url: str = "https://nura-ai.ru"
    report_price_rub: int = 590

    # Subscription
    subscription_price_rub: int = 390

    # Rate limit
    rate_limit_requests: int = 30
    rate_limit_window: int = 60

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
