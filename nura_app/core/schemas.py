from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    telegram_id: int
    birth_date: str | None = None


class UserResponse(BaseModel):
    id: UUID
    telegram_id: int
    birth_date: str | None
    subscription_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MatrixData(BaseModel):
    birth_date: str
    center: int
    top: int
    bottom: int
    left: int
    right: int
    talent_zone: int
    comfort_zone: int
    portrait_zone: int
    karmic_tail: list[int]
    arcana_names: dict[str, str] = Field(default_factory=dict)


class MiniAnalysisResult(BaseModel):
    main_archetype: str
    core_strength: str
    emotional_conflict: str
    relationship_pattern: str
    financial_block: str


class FullReportResult(BaseModel):
    main_archetype: str
    strengths: str
    shadow_side: str
    relationship_dynamics: str
    financial_scenario: str
    recurring_mistakes: str
    internal_conflicts: str
    life_cycles: str
    ai_recommendations: str


class ReportResponse(BaseModel):
    id: UUID
    token: str
    report_type: str
    matrix_data: dict | None
    ai_analysis: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaymentCreate(BaseModel):
    telegram_id: int


class PaymentResponse(BaseModel):
    id: UUID
    user_id: UUID
    amount: int
    status: str
    payment_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str = "ok"
