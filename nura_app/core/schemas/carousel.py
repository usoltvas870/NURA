from typing import Literal

from pydantic import BaseModel, Field


class BrandConfig(BaseModel):
    primary_color: str = "#D97A32"
    accent_color: str = "#8C6A3B"
    bg_dark: str = "#0B0B0B"
    bg_gradient: str = (
        "radial-gradient(circle at 30% 20%, rgba(217,122,50,0.08), transparent 60%), "
        "linear-gradient(135deg, #0B0B0B, #0F1A17)"
    )
    font_heading: str = "'Cormorant Garamond', Georgia, serif"
    font_body: str = "'DM Sans', Arial, sans-serif"


class CarouselSettings(BaseModel):
    width: int = 1080
    height: int = 1350
    format: Literal[
        "instagram_portrait", "instagram_square", "instagram_landscape"
    ] = "instagram_portrait"
    font_scale: float = 1.0


class CarouselSlide(BaseModel):
    slide_number: int = Field(ge=1, le=10)
    template_id: Literal["cover", "quote", "list", "text_image", "cta"]
    heading: str | None = None
    subheading: str | None = None
    body: str | None = None
    list_items: list[str] = []
    cta: str | None = None
    visual_hint: str | None = None
    tone: str | None = None


class CarouselConfig(BaseModel):
    name: str
    format: Literal["carousel"] = "carousel"
    brand: BrandConfig = BrandConfig()
    slides: list[CarouselSlide] = Field(min_length=2, max_length=10)
    settings: CarouselSettings = CarouselSettings()
