"""Channel-neutral durable chat request orchestration."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Awaitable, Callable

from core.fallbacks import FALLBACK_CHAT
from core.services.ai import AIService
from core.services.chat_quota import ChatChannel, ChatQuotaService, QuotaReservationKind


class ChatResultKind(StrEnum):
    COMPLETED_NEW = "completed_new"
    COMPLETED_REPLAYED = "completed_replayed"
    IN_PROGRESS = "in_progress"
    QUOTA_EXHAUSTED = "quota_exhausted"
    PROVIDER_FAILURE = "provider_failure"
    DUPLICATE_RELEASED_FAILURE = "duplicate_released_failure"
    PERSISTENCE_FAILURE = "persistence_failure"
    HISTORY_FINALIZATION_PENDING = "history_finalization_pending"


@dataclass(frozen=True)
class ChatApplicationResult:
    kind: ChatResultKind
    reply: str | None
    quota: object
    history: list[dict]
    replayed: bool = False
    error_code: str | None = None


class ChatApplicationService:
    def __init__(self, quota_service: ChatQuotaService) -> None:
        self._quota_service = quota_service

    @staticmethod
    def _history_with_pair(history: list[dict], request_key: str, message: str, reply: str) -> list[dict]:
        if any(item.get("request_key") == request_key for item in history):
            return history[-20:]
        return [*history, {"role": "user", "content": message, "request_key": request_key},
                {"role": "assistant", "content": reply, "request_key": request_key}][-20:]

    async def respond(self, *, user_id: object, request_key: str, channel: ChatChannel,
                      subscriber: bool, message: str, history: list[dict], matrix_data: dict,
                      user_name: str,
                      history_finalizer: Callable[[str], Awaitable[bool]] | None = None) -> ChatApplicationResult:
        if history_finalizer is None:
            async def history_finalizer(_: str) -> bool:
                return True
        reservation = await self._quota_service.reserve(user_id, request_key, channel, subscriber=subscriber)
        if reservation.kind == QuotaReservationKind.EXHAUSTED:
            return ChatApplicationResult(ChatResultKind.QUOTA_EXHAUSTED, None, reservation.state, history)
        if reservation.kind == QuotaReservationKind.DUPLICATE_RESERVED:
            return ChatApplicationResult(ChatResultKind.IN_PROGRESS, None, reservation.state, history)
        if reservation.kind == QuotaReservationKind.DUPLICATE_RELEASED:
            return ChatApplicationResult(ChatResultKind.DUPLICATE_RELEASED_FAILURE, None, reservation.state, history,
                                         error_code=reservation.error_code)
        if reservation.kind == QuotaReservationKind.DUPLICATE_RESULT:
            if reservation.usage_id is None or not reservation.response_text:
                return ChatApplicationResult(ChatResultKind.PERSISTENCE_FAILURE, None, reservation.state, history)
            try:
                await history_finalizer(reservation.response_text)
                quota = await self._quota_service.consume(reservation.usage_id)
            except Exception:
                return ChatApplicationResult(ChatResultKind.HISTORY_FINALIZATION_PENDING, reservation.response_text,
                                             reservation.state, history, True, "history_finalization_pending")
            return ChatApplicationResult(ChatResultKind.COMPLETED_REPLAYED, reservation.response_text, quota,
                                         self._history_with_pair(history, request_key, message, reservation.response_text), True)
        if reservation.usage_id is None:
            return ChatApplicationResult(ChatResultKind.PERSISTENCE_FAILURE, None, reservation.state, history)
        try:
            reply = await AIService.chat_response(user_message=message, chat_history=history[-10:],
                                                  matrix_data=matrix_data, user_name=user_name)
        except Exception:
            quota = await self._quota_service.release(reservation.usage_id, reason="provider_failure")
            return ChatApplicationResult(ChatResultKind.PROVIDER_FAILURE, None, quota, history,
                                         error_code="provider_failure")
        if reply == FALLBACK_CHAT:
            quota = await self._quota_service.release(reservation.usage_id, reason="fallback")
            return ChatApplicationResult(ChatResultKind.PROVIDER_FAILURE, None, quota, history, error_code="fallback")
        try:
            await self._quota_service.store_result(reservation.usage_id, reply)
            await history_finalizer(reply)
            quota = await self._quota_service.consume(reservation.usage_id)
        except Exception:
            return ChatApplicationResult(ChatResultKind.HISTORY_FINALIZATION_PENDING, reply, reservation.state,
                                         history, error_code="history_finalization_pending")
        return ChatApplicationResult(ChatResultKind.COMPLETED_NEW, reply, quota,
                                     self._history_with_pair(history, request_key, message, reply))
