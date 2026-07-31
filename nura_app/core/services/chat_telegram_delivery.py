"""Resumable delivery of an already persisted chat response to Telegram."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from bot.utils.formatting import split_telegram_html_text
from core.services.chat_quota import ChatQuotaService
from core.services.telegram_report_delivery import TelegramDeliveryError, TelegramDocumentAdapter
from core.services.telegram_sandbox import (
    SandboxTelegramRecipientBlocked,
    require_telegram_recipient_allowed,
)


@dataclass(frozen=True)
class TelegramChatDeliveryResult:
    status: str
    retryable: bool = False
    quota: object | None = None


class TelegramChatDeliveryService:
    """Claims one logical chat delivery and durably advances it chunk by chunk."""

    def __init__(
        self, quota_service: ChatQuotaService, adapter: TelegramDocumentAdapter | None = None
    ) -> None:
        self._quota = quota_service
        self._adapter = adapter or TelegramDocumentAdapter()

    @staticmethod
    def chunks(response_text: str) -> list[str]:
        return split_telegram_html_text(response_text)

    async def deliver(
        self,
        usage_id: object,
        *,
        send_chunk: Callable[[str], Awaitable[object]] | None = None,
    ) -> TelegramChatDeliveryResult:
        claim = await self._quota.claim_telegram_delivery(usage_id)
        if claim is None:
            return TelegramChatDeliveryResult("not_claimed")
        chunks = self.chunks(claim.response_text)
        if len(chunks) != claim.total_chunks or claim.next_chunk_index > len(chunks):
            await self._quota.fail_telegram_delivery(
                claim.usage_id, claim.attempt, error_code="delivery_chunks_invalid", retryable=False
            )
            return TelegramChatDeliveryResult("failed")
        try:
            require_telegram_recipient_allowed(claim.chat_id)
            for chunk_index in range(claim.next_chunk_index, len(chunks)):
                if send_chunk is None:
                    await self._adapter.send_message(claim.chat_id, chunks[chunk_index])
                else:
                    await send_chunk(chunks[chunk_index])
                if not await self._quota.mark_telegram_chunk_delivered(
                    claim.usage_id, claim.attempt, chunk_index
                ):
                    return TelegramChatDeliveryResult("claim_lost", retryable=True)
            quota = await self._quota.complete_telegram_delivery(claim.usage_id, claim.attempt)
            return TelegramChatDeliveryResult("delivered", quota=quota)
        except SandboxTelegramRecipientBlocked as error:
            quota = await self._quota.fail_telegram_delivery(
                claim.usage_id,
                claim.attempt,
                error_code=error.code,
                retryable=False,
            )
            return TelegramChatDeliveryResult("failed", quota=quota)
        except TelegramDeliveryError as error:
            quota = await self._quota.fail_telegram_delivery(
                claim.usage_id, claim.attempt, error_code=error.code, retryable=error.retryable
            )
            return TelegramChatDeliveryResult(
                "retryable_failure" if error.retryable else "failed",
                retryable=error.retryable,
                quota=quota,
            )
        except Exception as error:
            classified = self._adapter._classify(error)
            quota = await self._quota.fail_telegram_delivery(
                claim.usage_id, claim.attempt,
                error_code=classified.code, retryable=classified.retryable,
            )
            return TelegramChatDeliveryResult(
                "retryable_failure" if classified.retryable else "failed",
                retryable=classified.retryable,
                quota=quota,
            )
