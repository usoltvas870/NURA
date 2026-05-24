from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from core.schemas.carousel import BrandConfig, CarouselConfig, CarouselSettings, CarouselSlide
from core.services.carousel_assembler import CarouselAssembler


# ── test data ──

_MINIMAL_SLIDES = [
    CarouselSlide(slide_number=1, template_id="cover", heading="Title"),
    CarouselSlide(slide_number=2, template_id="cta", heading="End", cta="Subscribe"),
]

_FULL_SLIDES = [
    CarouselSlide(slide_number=1, template_id="cover", heading="Cover", subheading="Sub"),
    CarouselSlide(slide_number=2, template_id="quote", heading="Author", body="Quote text"),
    CarouselSlide(slide_number=3, template_id="list", heading="List", list_items=["A", "B", "C"]),
    CarouselSlide(slide_number=4, template_id="text_image", heading="Image", body="Desc", visual_hint="Sunset"),
    CarouselSlide(slide_number=5, template_id="cta", heading="CTA", cta="Click here"),
    CarouselSlide(slide_number=6, template_id="cover", heading="Final", tone="warm"),
    CarouselSlide(slide_number=7, template_id="quote", body="Short quote"),
    CarouselSlide(slide_number=8, template_id="text_image", heading="Left right"),
]


# ── TestCarouselSchemas ──

class TestCarouselSchemas:

    def test_minimal_config(self):
        cfg = CarouselConfig(
            name="test",
            slides=_MINIMAL_SLIDES,
        )
        assert cfg.name == "test"
        assert cfg.format == "carousel"
        assert len(cfg.slides) == 2
        assert isinstance(cfg.brand, BrandConfig)
        assert isinstance(cfg.settings, CarouselSettings)

    def test_minimal_config_from_dict(self):
        raw = {
            "name": "test",
            "slides": [
                {"slide_number": 1, "template_id": "cover", "heading": "A"},
                {"slide_number": 2, "template_id": "cta", "heading": "B"},
            ],
        }
        cfg = CarouselConfig.model_validate(raw)
        assert cfg.name == "test"
        assert len(cfg.slides) == 2

    def test_invalid_template_id(self):
        with pytest.raises(ValidationError):
            CarouselSlide(slide_number=1, template_id="invalid")

    def test_slides_min_length(self):
        with pytest.raises(ValidationError):
            CarouselConfig(
                name="test",
                slides=[
                    CarouselSlide(slide_number=1, template_id="cover", heading="Only one"),
                ],
            )

    def test_slides_max_length(self):
        slides = [
            CarouselSlide(slide_number=1, template_id="cover", heading=str(i))
            for i in range(11)
        ]
        with pytest.raises(ValidationError):
            CarouselConfig(name="test", slides=slides)

    def test_slide_number_bounds(self):
        with pytest.raises(ValidationError):
            CarouselSlide(slide_number=0, template_id="cover", heading="Zero")
        with pytest.raises(ValidationError):
            CarouselSlide(slide_number=11, template_id="cover", heading="Eleven")

    def test_format_literal(self):
        with pytest.raises(ValidationError):
            CarouselConfig(
                name="test",
                format="video",
                slides=_MINIMAL_SLIDES,
            )

    def test_settings_format_literal(self):
        with pytest.raises(ValidationError):
            CarouselSettings(format="tiktok")

    def test_brand_defaults(self):
        brand = BrandConfig()
        assert brand.primary_color == "#D97A32"
        assert brand.accent_color == "#8C6A3B"
        assert brand.bg_dark == "#0B0B0B"
        assert "radial-gradient" in brand.bg_gradient


# ── TestCarouselRendering ──

class TestCarouselRendering:

    def test_render_cover(self):
        html = CarouselAssembler._render_slide(
            slide=_FULL_SLIDES[0],
            brand=BrandConfig(),
            settings=CarouselSettings(),
            slide_index=0,
            total=len(_FULL_SLIDES),
        )
        assert "slide-cover-heading" in html
        assert "Cover" in html
        assert "Sub" in html
        assert "slide-number" in html
        assert "slide-divider" in html
        assert "slide-logo" in html

    def test_render_quote(self):
        html = CarouselAssembler._render_slide(
            slide=_FULL_SLIDES[1],
            brand=BrandConfig(),
            settings=CarouselSettings(),
            slide_index=1,
            total=len(_FULL_SLIDES),
        )
        assert "slide-quote-body" in html
        assert "slide-quote-source" in html
        assert "Quote text" in html
        assert "Author" in html

    def test_render_list(self):
        html = CarouselAssembler._render_slide(
            slide=_FULL_SLIDES[2],
            brand=BrandConfig(),
            settings=CarouselSettings(),
            slide_index=2,
            total=len(_FULL_SLIDES),
        )
        assert "slide-list-heading" in html
        assert "slide-list-item" in html
        assert "slide-list-bullet" in html
        assert "A" in html
        assert "B" in html
        assert "C" in html

    def test_render_text_image(self):
        html = CarouselAssembler._render_slide(
            slide=_FULL_SLIDES[3],
            brand=BrandConfig(),
            settings=CarouselSettings(),
            slide_index=3,
            total=len(_FULL_SLIDES),
        )
        assert "slide-text-image-grid" in html
        assert "slide-text-image-heading" in html
        assert "slide-text-image-body" in html
        assert "slide-text-image-placeholder" in html
        assert "slide-text-image-hint" in html
        assert "Sunset" in html

    def test_render_cta(self):
        html = CarouselAssembler._render_slide(
            slide=_FULL_SLIDES[4],
            brand=BrandConfig(),
            settings=CarouselSettings(),
            slide_index=4,
            total=len(_FULL_SLIDES),
        )
        assert "slide-cta-heading" in html
        assert "slide-cta-body" in html
        assert "slide-cta-button" in html
        assert "Click here" in html

    def test_render_all_templates(self):
        for i, slide in enumerate(_FULL_SLIDES):
            html = CarouselAssembler._render_slide(
                slide=slide,
                brand=BrandConfig(),
                settings=CarouselSettings(),
                slide_index=i,
                total=len(_FULL_SLIDES),
            )
            assert "<!DOCTYPE html>" in html
            assert "NURA" in html
            assert "slide" in html.lower()
            assert "slide-logo" in html

    def test_render_empty_fields(self):
        slide = CarouselSlide(slide_number=1, template_id="cover", heading="Only heading")
        html = CarouselAssembler._render_slide(
            slide=slide,
            brand=BrandConfig(),
            settings=CarouselSettings(),
            slide_index=0,
            total=1,
        )
        assert "Only heading" in html
        assert "slide-cover-heading" in html
        assert "slide-number" in html

    def test_render_list_empty(self):
        slide = CarouselSlide(slide_number=3, template_id="list", heading="Empty list", list_items=[])
        html = CarouselAssembler._render_slide(
            slide=slide,
            brand=BrandConfig(),
            settings=CarouselSettings(),
            slide_index=2,
            total=3,
        )
        assert "Empty list" in html
        assert 'class="slide-list-item"' not in html


# ── TestCarouselAssembler ──

class TestCarouselAssembler:

    @patch.object(CarouselAssembler, "_screenshot", new_callable=AsyncMock)
    async def test_assemble_creates_pngs(self, mock_screenshot, tmp_path):
        mock_screenshot.return_value = tmp_path / "test_slide_01.png"

        cfg = CarouselConfig(name="test_png", slides=_MINIMAL_SLIDES)
        CarouselAssembler.OUTPUT_DIR = tmp_path

        paths = await CarouselAssembler.assemble(cfg)

        assert len(paths) == 2
        assert mock_screenshot.call_count == 2

    @patch.object(CarouselAssembler, "_screenshot", new_callable=AsyncMock)
    async def test_assemble_with_minimal_config(self, mock_screenshot, tmp_path):
        mock_screenshot.return_value = tmp_path / "minimal_slide_01.png"
        CarouselAssembler.OUTPUT_DIR = tmp_path

        cfg = CarouselConfig(
            name="minimal",
            slides=_MINIMAL_SLIDES,
        )
        paths = await CarouselAssembler.assemble(cfg)

        assert len(paths) == 2

    @patch.object(CarouselAssembler, "_screenshot", new_callable=AsyncMock)
    async def test_assemble_single_slide_in_config(self, mock_screenshot, tmp_path):
        mock_screenshot.return_value = tmp_path / "single_slide_01.png"

        with pytest.raises(ValidationError):
            CarouselConfig(
                name="single",
                slides=[
                    CarouselSlide(slide_number=1, template_id="cover", heading="Only one"),
                ],
            )

    @patch.object(CarouselAssembler, "_screenshot", new_callable=AsyncMock)
    async def test_assemble_all_templates(self, mock_screenshot, tmp_path):
        CarouselAssembler.OUTPUT_DIR = tmp_path

        slides = [
            CarouselSlide(slide_number=i + 1, template_id=tid, heading=f"Slide {i + 1}")
            for i, tid in enumerate(["cover", "quote", "list", "text_image", "cta"])
        ]
        slides[2].list_items = ["X", "Y"]
        slides[3].body = "Body text"
        slides[4].cta = "Click"

        cfg = CarouselConfig(name="all_templates", slides=slides)
        mock_screenshot.side_effect = [
            tmp_path / f"all_templates_slide_{i+1:02d}.png"
            for i in range(len(slides))
        ]

        paths = await CarouselAssembler.assemble(cfg)

        assert len(paths) == 5
        assert mock_screenshot.call_count == 5
