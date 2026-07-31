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
        description="глубокий разбор: ключевая фраза, жизненная стратегия, стиль решений, проявление в работе/отношениях/деньгах",
    )
    strengths: str = Field(
        ...,
        description="сильные стороны, таланты, ресурсы, примеры реализации",
    )
    shadow_side: str = Field(
        ...,
        description="возможные слепые пятна и напряжения как интерпретативные гипотезы, не диагноз",
    )
    relationship_dynamics: str = Field(
        ...,
        description="возможная динамика отношений по supplied positions, без совместимости с неизвестными людьми",
    )
    financial_scenario: str = Field(
        ...,
        description="legacy key: возможный паттерн отношения к ресурсам и безопасности, без обещаний дохода и финансовых советов",
    )
    recurring_mistakes: str = Field(
        ...,
        description="повторяющиеся сценарии, циклы и причины",
    )
    internal_conflicts: str = Field(
        ...,
        description="внутренние конфликты между энергиями матрицы, путь разрешения",
    )
    life_cycles: str = Field(
        ...,
        description="legacy key: повторяющийся ритм внимания и выбора, без прогноза лет или возрастов",
    )
    ai_recommendations: str = Field(
        ...,
        description="несколько необязательных практических действий, связанных с supplied Matrix positions",
    )
    karmic_tail_analysis: str = Field(
        ...,
        description="legacy key: символическая тема последовательности supplied positions без фатальных утверждений",
    )
    ancestral_programs: str = Field(
        ...,
        description="legacy key: метафорическое сравнение supplied G/I lines без выдуманной семейной истории",
    )
    life_purpose: str = Field(
        ...,
        description="legacy key: возможные направления реализации ценностей без назначения профессии как истины",
    )
    life_forecast: str = Field(
        ...,
        description="legacy key: вопросы и варианты действий в текущем контексте без дат, возрастов и предсказаний",
    )
    psychological_blocks: str = Field(
        ...,
        description="legacy key: возможные внутренние напряжения без диагноза, травмы или защитного механизма как факта",
    )
    health_analysis: str = Field(
        ...,
        description="legacy key: общий ресурс и безопасное самонаблюдение без органов, заболеваний, чакр или медицинских выводов",
    )
    dashboard_insights: dict | None = None


class KitchenEntry(BaseModel):
    positions: str | list[str] | None = None
    energies: str | list[str] | None = None
    logic: str = ""


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
    psychological_blocks: KitchenEntry = Field(default_factory=KitchenEntry)
    health_analysis: KitchenEntry = Field(default_factory=KitchenEntry)


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
    portrait_user: str
    portrait_partner: str
    how_you_interact: str
    tension_zones: str
    pair_strengths: str
    recommendation: str


class DailyInsightResult(BaseModel):
    insight: str
    focus_area: str


class TarotDailyCardResult(BaseModel):
    card_number: int
    card_name: str
    key_phrase: str
    interpretation: str
    matrix_link: str
    advice: str
    affirmation: str


class TarotWeeklyPosition(BaseModel):
    card_number: int
    card_name: str
    energy: str
    interpretation: str
    practice: str


class TarotWeeklySpreadResult(BaseModel):
    body: TarotWeeklyPosition
    mind: TarotWeeklyPosition
    spirit: TarotWeeklyPosition
    overall: str


class TarotQuestionPosition(BaseModel):
    card_number: int
    card_name: str
    meaning: str
    how_it_relates: str


class TarotQuestionResult(BaseModel):
    past: TarotQuestionPosition
    present: TarotQuestionPosition
    future: TarotQuestionPosition
    summary: str
    advice: str


class TarotMiniPosition(BaseModel):
    card_number: int
    card_name: str
    interpretation: str
    advice: str | None = None


class TarotMiniSpreadResult(BaseModel):
    context: TarotMiniPosition
    inner_resource: TarotMiniPosition
    next_step: TarotMiniPosition
    summary: str


class HealthResponse(BaseModel):
    status: str = "ok"


__all__ = [
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
    "TarotDailyCardResult",
    "TarotWeeklyPosition",
    "TarotWeeklySpreadResult",
    "TarotQuestionPosition",
    "TarotQuestionResult",
    "TarotMiniPosition",
    "TarotMiniSpreadResult",
    "HealthResponse",
]
