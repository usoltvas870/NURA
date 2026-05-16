import uuid
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from core.config import settings


class ReportService:
    TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "reports" / "templates"
    OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "reports" / "output"

    @classmethod
    def _env(cls) -> Environment:
        return Environment(loader=FileSystemLoader(str(cls.TEMPLATE_DIR)))

    @classmethod
    def generate_html_report(cls, report_data: dict, template_name: str = "full_report.html") -> str:
        env = cls._env()
        tmpl = env.get_template(template_name)
        return tmpl.render(
            **report_data,
            report_base_url=settings.report_base_url,
            report_price_rub=settings.report_price_rub,
            generated_at=date.today().strftime("%d.%m.%Y"),
        )

    @classmethod
    async def generate_pdf(cls, html_content: str) -> bytes:
        from weasyprint import HTML

        return HTML(string=html_content).write_pdf()

    @classmethod
    def get_report_path(cls, token: str) -> dict:
        return {
            "html": str(cls.OUTPUT_DIR / f"{token}.html"),
            "pdf": str(cls.OUTPUT_DIR / f"{token}.pdf"),
        }

    @classmethod
    def save_report_files(cls, token: str, html: str, pdf: bytes) -> dict:
        cls.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        html_path = cls.OUTPUT_DIR / f"{token}.html"
        pdf_path = cls.OUTPUT_DIR / f"{token}.pdf"

        html_path.write_text(html, encoding="utf-8")
        pdf_path.write_bytes(pdf)

        return {
            "html": str(html_path),
            "pdf": str(pdf_path),
        }

    @staticmethod
    def generate_token() -> str:
        return uuid.uuid4().hex[:32]

    @staticmethod
    def report_url(token: str) -> str:
        return f"{settings.report_base_url}/report/{token}"

    @staticmethod
    def parse_recommendations(ai_recommendations: str) -> list[dict]:
        lines = [ln.strip() for ln in ai_recommendations.strip().split("\n") if ln.strip()]
        result = []
        for i, line in enumerate(lines, 1):
            cleaned = line
            if cleaned and cleaned[0].isdigit() and ". " in cleaned[:4]:
                cleaned = cleaned.split(". ", 1)[-1]

            lower = cleaned.lower()
            if any(w in lower for w in ["тело", "физическ", "йог", "дыхание", "спорт", "сон", "движение", "тренировк", "прогулк"]):
                category = "Тело"
            elif any(w in lower for w in ["ум", "мысл", "анализ", "изучени", "чтение", "план", "интеллект", "обучени", "запис"]):
                category = "Ум"
            elif any(w in lower for w in ["дух", "медитаци", "осознанност", "тишина", "благодарност", "духовн", "молитв"]):
                category = "Дух"
            else:
                category = "Практика"

            result.append({"number": i, "text": cleaned, "category": category})
        return result
