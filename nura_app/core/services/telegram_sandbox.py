"""Global Telegram allowlist boundary for APP_ENV=sandbox."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from aiogram import BaseMiddleware, Bot
from aiogram.methods import TelegramMethod
from aiogram.types import TelegramObject, User as TelegramUser

from core.config import Settings, settings
from core.services.external_sandbox import (
    SandboxIdentityError,
    require_telegram_identity_evidence,
    validate_telegram_identity,
)


logger = logging.getLogger(__name__)


class SandboxTelegramRecipientBlocked(RuntimeError):
    """Typed terminal error raised before an outbound Telegram transport call."""

    code = "sandbox_telegram_recipient_not_allowed"

    def __init__(self) -> None:
        super().__init__(self.code)


class TelegramIdentityVerifier(Protocol):
    async def get_identity(self) -> tuple[int, str]: ...


def _safe_telegram_fingerprint(telegram_id: int, environment_id: str | None) -> str:
    material = f"{environment_id or 'sandbox'}|{telegram_id}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:12]


def telegram_user_is_allowed(
    telegram_id: int | str,
    *,
    current_settings: Settings = settings,
) -> bool:
    if not current_settings.is_sandbox:
        return True
    if not isinstance(telegram_id, int):
        return False
    return telegram_id in current_settings.sandbox_telegram_allowed_ids


def require_telegram_recipient_allowed(
    telegram_id: int | str,
    *,
    current_settings: Settings = settings,
) -> None:
    if telegram_user_is_allowed(telegram_id, current_settings=current_settings):
        return
    logger.warning(
        "sandbox_telegram_outbound_blocked recipient=%s",
        _safe_telegram_fingerprint(
            int(telegram_id) if isinstance(telegram_id, int) else 0,
            current_settings.sandbox_environment_id,
        ),
    )
    raise SandboxTelegramRecipientBlocked()


async def verify_telegram_identity_with(
    verifier: TelegramIdentityVerifier,
    *,
    current_settings: Settings = settings,
) -> dict[str, object]:
    """Run an injected identity verifier and return only bounded evidence."""

    if not current_settings.is_sandbox:
        raise SandboxIdentityError("sandbox_telegram_identity_check_requires_sandbox")
    actual_bot_id, actual_username = await verifier.get_identity()
    validate_telegram_identity(
        expected_bot_id=int(current_settings.sandbox_telegram_bot_id or 0),
        expected_username=current_settings.sandbox_telegram_bot_username or "",
        actual_bot_id=actual_bot_id,
        actual_username=actual_username,
    )
    return {
        "status": "verified",
        "environment_id": current_settings.sandbox_environment_id,
        "bot_id": actual_bot_id,
        "bot_username": actual_username.lstrip("@"),
    }


class SandboxTelegramInboundMiddleware(BaseMiddleware):
    """Drop disallowed updates before registration, attribution or handlers."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_user: TelegramUser | None = data.get("event_from_user")
        if (
            settings.is_sandbox
            and telegram_user is not None
            and not telegram_user.is_bot
            and not telegram_user_is_allowed(telegram_user.id)
        ):
            logger.warning(
                "sandbox_telegram_inbound_blocked sender=%s",
                _safe_telegram_fingerprint(
                    telegram_user.id, settings.sandbox_environment_id
                ),
            )
            return None
        return await handler(event, data)


class SandboxGuardedBot(Bot):
    """Aiogram boundary that guards every method carrying a recipient chat_id."""

    async def __call__(
        self,
        method: TelegramMethod[Any],
        request_timeout: int | None = None,
    ) -> Any:
        require_telegram_identity_evidence(settings)
        chat_id = getattr(method, "chat_id", None)
        if chat_id is not None:
            require_telegram_recipient_allowed(chat_id)
        return await super().__call__(method, request_timeout=request_timeout)
