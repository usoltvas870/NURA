from datetime import datetime

from pydantic import BaseModel, Field

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class GuestProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    birth_date: str = Field(..., pattern=r"^\d{2}\.\d{2}\.\d{4}$")
    quiz_answers: dict | None = None


class GuestProfileResponse(BaseModel):
    guest_token: str
    expires_at: datetime


class GuestProfileFetchResponse(BaseModel):
    guest_token: str
    name: str | None
    birth_date: str | None
    quiz_answers: dict | None
    expires_at: datetime
    merged: bool


class EmailAuthRequest(BaseModel):
    email: str = Field(..., pattern=EMAIL_PATTERN)
    guest_token: str | None = None


class EmailAuthResponse(BaseModel):
    message: str
    expires_in: int


class VKTokenRequest(BaseModel):
    access_token: str | None = None
    user_id: str | None = None
    code: str | None = None
    guest_token: str | None = None


class VKAuthResponse(BaseModel):
    success: bool
    user_id: str


class MergeGuestRequest(BaseModel):
    guest_token: str


class MergeGuestResponse(BaseModel):
    success: bool
    user_id: str