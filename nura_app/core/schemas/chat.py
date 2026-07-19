from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)

    @field_validator("message")
    @classmethod
    def message_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message must contain non-whitespace characters")
        return value


class ChatQuotaState(BaseModel):
    access: Literal["free", "subscriber"]
    can_send: bool
    daily_limit: int | None
    used: int | None
    messages_left: int | None
    reset_at: datetime | None
    timezone: str
    code: str | None = None


class ChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatStateResponse(ChatQuotaState):
    history: list[ChatHistoryItem] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    quota: ChatQuotaState
