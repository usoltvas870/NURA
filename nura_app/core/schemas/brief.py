from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class SceneBrief(BaseModel):
    index: int
    format_type: Literal[
        "type1_talking_head", "type2_stock_text", "type3_parchment"
    ] = "type2_stock_text"
    purpose: Literal["hook", "main", "cta"] = "main"
    nura_text: str = ""
    source_keywords: list[str] = []
    duration_sec: float = 8.0
    transition: Literal["dissolve", "fade", "slideleft", "slideright"] = "dissolve"
    transition_duration: float = 0.5
    zoom_enabled: bool = False
    zoom_from: float = 1.0
    zoom_to: float = 1.08
    text_overlay: str | None = None


class StockInsertion(BaseModel):
    keywords: list[str]
    description: str
    scene_index: int
    duration_sec: float


class CarouselSlideBrief(BaseModel):
    slide_number: int = Field(ge=1, le=10)
    template: Literal["cover", "quote", "list", "text_image", "cta"] = "cover"
    heading: str | None = None
    body: str | None = None
    visual_hint: str | None = None


class ContentBrief(BaseModel):
    video_id: str
    url: str
    author_username: str
    original_caption: str

    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    engagement_rate: float = 0.0
    comment_density: float = 0.0
    viral_score: float = 0.0
    final_score: float = 0.0

    topic: str = ""
    hook_type: str = ""
    hook_reason: str = ""
    virality_reason: str = ""
    pain_point: str = ""

    recommended_format: Literal["type1", "type2", "type3"] = "type2"
    target_duration_sec: int = 45
    tone: str = "warm"
    bpm: int = 120

    cta: str = ""
    draft_voiceover: str = ""
    draft_description: str = ""
    hashtags: list[str] = []

    scenes: list[SceneBrief] = []
    stock_insertions: list[StockInsertion] = []
    carousel_slides: list[CarouselSlideBrief] = []

    source_type: str = ""
    source_value: str = ""
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
