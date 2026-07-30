"""Telegram boundary and safe error classification for broadcast deliveries."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core.config import settings


@dataclass(frozen=True)
class BroadcastSendResult:
    message_id: int


class BroadcastTelegramError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        blocked_reason: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.blocked_reason = blocked_reason
        self.retry_after = retry_after


class BroadcastTelegramAdapter:
    def __init__(self, bot: Bot | None = None) -> None:
        self._bot = bot
        self._owns_bot = bot is None

    async def __aenter__(self) -> "BroadcastTelegramAdapter":
        if self._bot is None:
            if not settings.telegram_bot_token:
                raise BroadcastTelegramError("telegram_not_configured", retryable=True)
            self._bot = Bot(
                token=settings.telegram_bot_token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_bot and self._bot is not None:
            await self._bot.session.close()
            self._bot = None

    @staticmethod
    def keyboard(ctas: list[dict], token: str, *, test: bool = False) -> InlineKeyboardMarkup:
        prefix = "bct" if test else "bc"
        rows = [
            [
                InlineKeyboardButton(
                    text=str(cta["label"]),
                    callback_data=f"{prefix}:{token}:{cta['key']}",
                )
            ]
            for cta in ctas
        ]
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def send_media(self, chat_id: int, media_type: str, file_id: str) -> BroadcastSendResult:
        bot = self._require_bot()
        try:
            if media_type == "photo":
                message = await bot.send_photo(chat_id=chat_id, photo=file_id)
            elif media_type == "animation":
                message = await bot.send_animation(chat_id=chat_id, animation=file_id)
            elif media_type == "video":
                message = await bot.send_video(chat_id=chat_id, video=file_id)
            else:
                raise BroadcastTelegramError("invalid_media_type", retryable=False)
            return BroadcastSendResult(message_id=message.message_id)
        except BroadcastTelegramError:
            raise
        except Exception as error:
            raise self.classify(error) from None

    async def send_text(
        self,
        chat_id: int,
        text: str,
        ctas: list[dict],
        token: str,
        *,
        test: bool = False,
    ) -> BroadcastSendResult:
        bot = self._require_bot()
        try:
            message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=self.keyboard(ctas, token, test=test),
            )
            return BroadcastSendResult(message_id=message.message_id)
        except Exception as error:
            raise self.classify(error) from None

    def _require_bot(self) -> Bot:
        if self._bot is None:
            raise BroadcastTelegramError("telegram_adapter_not_open", retryable=True)
        return self._bot

    @staticmethod
    def classify(error: Exception) -> BroadcastTelegramError:
        if isinstance(error, TelegramForbiddenError):
            return BroadcastTelegramError(
                "telegram_forbidden", retryable=False, blocked_reason="bot_blocked"
            )
        if isinstance(error, TelegramRetryAfter):
            seconds = max(1, min(int(error.retry_after), settings.broadcast_retry_max_seconds))
            return BroadcastTelegramError(
                "telegram_retry_after", retryable=True, retry_after=seconds
            )
        if isinstance(error, TelegramBadRequest):
            message = str(error).lower()
            if any(marker in message for marker in ("chat not found", "user not found", "invalid user")):
                return BroadcastTelegramError(
                    "telegram_chat_not_found",
                    retryable=False,
                    blocked_reason="chat_not_found",
                )
            if any(marker in message for marker in ("wrong file identifier", "file_id", "failed to get http url content")):
                return BroadcastTelegramError("invalid_media_file_id", retryable=False)
            return BroadcastTelegramError("telegram_bad_request", retryable=False)
        if isinstance(error, (TelegramNetworkError, httpx.TransportError, asyncio.TimeoutError)):
            return BroadcastTelegramError("telegram_network", retryable=True)
        return BroadcastTelegramError("telegram_provider_error", retryable=True)
