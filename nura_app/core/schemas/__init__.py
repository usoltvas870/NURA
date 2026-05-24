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
        min_length=600,
        max_length=2500,
        description="глубокий разбор: ключевая фраза, жизненная стратегия, стиль решений, проявление в работе/отношениях/деньгах",
    )
    strengths: str = Field(
        ...,
        min_length=500,
        max_length=2000,
        description="сильные стороны, таланты, ресурсы, примеры реализации",
    )
    shadow_side: str = Field(
        ...,
        min_length=500,
        max_length=2000,
        description="теневая сторона, слепые пятна, психологические защиты",
    )
    relationship_dynamics: str = Field(
        ...,
        min_length=600,
        max_length=3000,
        description="динамика отношений: тип партнёра (точка отношений), паттерн входа/выхода, совместимость с архетипами",
    )
    financial_scenario: str = Field(
        ...,
        min_length=600,
        max_length=3000,
        description="финансовый сценарий: 2-3 профессии/ниши, стратегия дохода, конкретные денежные блоки",
    )
    recurring_mistakes: str = Field(
        ...,
        min_length=400,
        max_length=1500,
        description="повторяющиеся сценарии, циклы и причины",
    )
    internal_conflicts: str = Field(
        ...,
        min_length=500,
        max_length=2000,
        description="внутренние конфликты между энергиями матрицы, путь разрешения",
    )
    life_cycles: str = Field(
        ...,
        min_length=400,
        max_length=1500,
        description="жизненные циклы, периоды подъёма и спада",
    )
    ai_recommendations: str = Field(
        ...,
        min_length=500,
        max_length=3000,
        description="7 дней рекомендаций в категориях тело/ум/дух, каждый с конкретным арканом и действием",
    )
    karmic_tail_analysis: str = Field(
        ...,
        min_length=800,
        max_length=4000,
        description="детальный разбор: причина→следствие→урок, история трёх арканов, практический выход из цикла",
    )
    ancestral_programs: str = Field(
        ...,
        min_length=800,
        max_length=4000,
        description="родовые программы: линия отца (G) и матери (I), их влияние, ресурс vs блоки, путь проработки",
    )
    life_purpose: str = Field(
        ...,
        min_length=1000,
        max_length=5000,
        description="предназначение: 4 уровня (личное/социальное/духовное/кармическое), кармический дар (F), денежный канал (H), конкретные сферы реализации",
    )
    life_forecast: str = Field(
        ...,
        min_length=1000,
        max_length=5000,
        description="прогноз: текущий год по сферам (карьера/отношения/здоровье/деньги), прогноз 3 года, ключевые возраста и их энергии",
    )
    psychological_blocks: str = Field(
        ...,
        min_length=800,
        max_length=3500,
        description="психологические блоки: какие убеждения формирует каждый ключевой аркан, к каким ситуациям приводит, как изменить",
    )
    health_analysis: str = Field(
        ...,
        min_length=1000,
        max_length=5000,
        description="карта здоровья: 7 чакр с детальным разбором — состояние, причина дисбаланса, органы под управлением, практика восстановления (на основе арканов матрицы)",
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
    psychological_blocks: KitchenEntry
    health_analysis: KitchenEntry


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
