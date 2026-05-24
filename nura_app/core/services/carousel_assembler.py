from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from core.schemas.carousel import BrandConfig, CarouselConfig, CarouselSettings, CarouselSlide

NURA_ROOT = Path(__file__).resolve().parent.parent.parent.parent
NURA_APP = NURA_ROOT / "nura_app"


class CarouselAssembler:
    TEMPLATE_DIR = NURA_APP / "frontend" / "carousel" / "templates"
    OUTPUT_DIR = NURA_APP / "frontend" / "carousel" / "output"

    _TEMPLATE_MAP = {
        "cover": "slide_cover.html",
        "quote": "slide_quote.html",
        "list": "slide_list.html",
        "text_image": "slide_text_image.html",
        "cta": "slide_cta.html",
    }

    @classmethod
    def _env(cls) -> Environment:
        return Environment(
            loader=FileSystemLoader(str(cls.TEMPLATE_DIR)),
            autoescape=False,
        )

    @classmethod
    def _render_slide(
        cls,
        slide: CarouselSlide,
        brand: BrandConfig,
        settings: CarouselSettings,
        slide_index: int,
        total: int,
    ) -> str:
        template_name = cls._TEMPLATE_MAP[slide.template_id]
        env = cls._env()
        tpl = env.get_template(template_name)
        return tpl.render(
            slide=slide,
            brand=brand,
            settings=settings,
            index=slide_index,
            total=total,
        )

    @classmethod
    async def _screenshot(
        cls,
        html: str,
        index: int,
        cfg_name: str,
        width: int,
        height: int,
    ) -> Path:
        from playwright.async_api import async_playwright

        cls.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = cls.OUTPUT_DIR / f"{cfg_name}_slide_{index:02d}.png"

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page(
                    viewport={"width": width, "height": height},
                )
                await page.set_content(html, wait_until="networkidle")
                await page.screenshot(path=output_path, full_page=True)
            finally:
                await browser.close()

        return output_path

    @classmethod
    async def assemble(cls, cfg: CarouselConfig) -> list[Path]:
        total = len(cfg.slides)
        paths: list[Path] = []

        for i, slide in enumerate(cfg.slides):
            html = cls._render_slide(
                slide=slide,
                brand=cfg.brand,
                settings=cfg.settings,
                slide_index=i,
                total=total,
            )
            path = await cls._screenshot(
                html=html,
                index=slide.slide_number if slide.slide_number else i + 1,
                cfg_name=cfg.name,
                width=cfg.settings.width,
                height=cfg.settings.height,
            )
            paths.append(path)

        return paths
