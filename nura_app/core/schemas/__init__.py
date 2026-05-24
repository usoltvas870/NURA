from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from core.schemas.carousel import (
    BrandConfig,
    CarouselConfig,
    CarouselSettings,
    CarouselSlide,
)


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
    inner_f: int
    inner_g: int
    inner_h: int
    inner_i: int
    sky_line: list[int]
    earth_line: list[int]
    relationship_line: list[int]
    money_line: list[int]
    relationship_point: int
    arcana_names: dict[str, str] = Field(default_factory=dict)


class MiniAnalysisResult(BaseModel):
    main_archetype: str
    core_strength: str
    emotional_conflict: str
    relationship_pattern: str
    financial_block: str


class FullReportResult(BaseModel):
    main_archetype: str = Field(
        ...,
        min_length=400,
        max_length=1200,
        description="глубокий разбор главного архетипа, жизненная стратегия, стиль решений",
    )
    strengths: str = Field(
        ...,
        min_length=300,
        max_length=1000,
        description="сильные стороны, таланты, ресурсы, врождённые способности",
    )
    shadow_side: str = Field(
        ...,
        min_length=300,
        max_length=1000,
        description="теневая сторона, слепые пятна, зоны роста",
    )
    relationship_dynamics: str = Field(
        ...,
        min_length=350,
        max_length=1000,
        description="динамика отношений, паттерны привязанности, тип партнёра",
    )
    financial_scenario: str = Field(
        ...,
        min_length=400,
        max_length=1200,
        description="финансовый сценарий, каналы дохода, блоки, стратегии",
    )
    recurring_mistakes: str = Field(
        ...,
        min_length=250,
        max_length=800,
        description="повторяющиеся ошибки, циклы и паттерны",
    )
    internal_conflicts: str = Field(
        ...,
        min_length=300,
        max_length=1000,
        description="внутренние конфликты, противоречия между энергиями",
    )
    life_cycles: str = Field(
        ...,
        min_length=250,
        max_length=800,
        description="жизненные циклы, периоды подъёма и спада",
    )
    ai_recommendations: str = Field(
        ...,
        min_length=300,
        max_length=1500,
        description="рекомендации на 7 дней, привязанные к позициям матрицы",
    )
    karmic_tail_analysis: str = Field(
        ...,
        min_length=400,
        max_length=1200,
        description="кармический хвост: причина→следствие→урок, как выйти из цикла",
    )
    ancestral_programs: str = Field(
        ...,
        min_length=400,
        max_length=1200,
        description="родовые программы: линия отца, линия матери, влияние на жизнь",
    )
    life_purpose: str = Field(
        ...,
        min_length=400,
        max_length=1200,
        description="предназначение: линия неба, кармический дар, денежный канал, профессии",
    )
    life_forecast: str = Field(
        ...,
        min_length=300,
        max_length=1000,
        description="прогноз периодов: ключевые возраста, энергия года, 3-летний прогноз",
    )


class KitchenEntry(BaseModel):
    positions: list[str]
    energies: list[str]
    logic: str


class KitchenReportResult(BaseModel):
    main_archetype: KitchenEntry
    strengths: KitchenEntry
    shadow_side: KitchenEntry
    relationship_dynamics: KitchenEntry
    financial_scenario: KitchenEntry
    recurring_mistakes: KitchenEntry
    internal_conflicts: KitchenEntry
    life_cycles: KitchenEntry
    karmic_tail_analysis: KitchenEntry
    ancestral_programs: KitchenEntry
    life_purpose: KitchenEntry
    life_forecast: KitchenEntry


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


class CompatibilityMiniResult(BaseModel):
    archetype_first: str
    archetype_second: str
    emotional_compatibility: str


class CompatibilityFullResult(BaseModel):
    archetype_first: str
    archetype_second: str
    emotional_compatibility: str
    conflict_zones: str
    pair_strengths: str
    ai_recommendation: str


class DailyInsightResult(BaseModel):
    insight: str
    focus_area: str


class HealthResponse(BaseModel):
    status: str = "ok"


__all__ = [
    "BrandConfig",
    "CarouselConfig",
    "CarouselSettings",
    "CarouselSlide",
    "UserCreate",
    "UserResponse",
    "MatrixData",
    "MiniAnalysisResult",
    "KitchenEntry",
    "KitchenReportResult",
    "FullReportResult",
    "ReportResponse",
    "PaymentCreate",
    "PaymentResponse",
    "CompatibilityMiniResult",
    "CompatibilityFullResult",
    "DailyInsightResult",
    "HealthResponse",
]
