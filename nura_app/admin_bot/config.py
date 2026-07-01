from dataclasses import dataclass, field

from core.config import settings


@dataclass
class AdminBotConfig:
    token: str | None = settings.admin_bot_token
    admin_telegram_id: int | None = settings.admin_telegram_id
    allowed_containers: set[str] = field(
        default_factory=lambda: {"api", "bot", "celery-worker", "celery-beat", "postgres", "redis"}
    )
    project_prefix: str = "nura_app"
