"""Canonical fail-closed Telegram allowlist boundary for restricted runtimes."""

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


class TelegramRecipientBlocked(RuntimeError):
    """Typed terminal error raised before an outbound Telegram transport call."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(self.code)


SandboxTelegramRecipientBlocked = TelegramRecipientBlocked


class TelegramIdentityVerifier(Protocol):
    async def get_identity(self) -> tuple[int, str]: ...


def _safe_telegram_fingerprint(telegram_id: int, environment_id: str | None) -> str:
    material = f"{environment_id or 'restricted'}|{telegram_id}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:12]


def telegram_user_is_allowed(
    telegram_id: int | str,
    *,
    current_settings: Settings = settings,
) -> bool:
    if not current_settings.telegram_access_restricted:
        return True
    if not isinstance(telegram_id, int):
        return False
    return telegram_id in current_settings.telegram_restricted_allowed_ids


def require_telegram_recipient_allowed(
    telegram_id: int | str,
    *,
    current_settings: Settings = settings,
) -> None:
    if telegram_user_is_allowed(telegram_id, current_settings=current_settings):
        return
    scope = current_settings.telegram_restriction_scope or "restricted"
    logger.warning(
        "telegram_restricted_outbound_blocked scope=%s recipient=%s",
        scope,
        _safe_telegram_fingerprint(
            int(telegram_id) if isinstance(telegram_id, int) else 0,
            (
                current_settings.sandbox_environment_id
                if current_settings.is_sandbox
                else "owner-prelaunch"
            ),
        ),
    )
    raise TelegramRecipientBlocked(f"{scope}_telegram_recipient_not_allowed")


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


class RestrictedTelegramInboundMiddleware(BaseMiddleware):
    """Drop disallowed updates before registration, attribution or handlers."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_user: TelegramUser | None = data.get("event_from_user")
        if settings.telegram_access_restricted and (
            telegram_user is None
            or telegram_user.is_bot
            or not telegram_user_is_allowed(telegram_user.id)
        ):
            scope = settings.telegram_restriction_scope or "restricted"
            sender = (
                _safe_telegram_fingerprint(
                    telegram_user.id,
                    (
                        settings.sandbox_environment_id
                        if settings.is_sandbox
                        else "owner-prelaunch"
                    ),
                )
                if telegram_user is not None
                else "missing"
            )
            logger.warning(
                "telegram_restricted_inbound_blocked scope=%s sender=%s",
                scope,
                sender,
            )
            return None
        return await handler(event, data)


SandboxTelegramInboundMiddleware = RestrictedTelegramInboundMiddleware


class RestrictedTelegramBot(Bot):
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


SandboxGuardedBot = RestrictedTelegramBot
