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
            generated_at=date.today().strftime("%d.%m.%Y"),
            bot_username=settings.bot_username,
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
        import re

        lines = [ln.strip() for ln in ai_recommendations.strip().split("\n") if ln.strip()]
        result = []
        for i, line in enumerate(lines, 1):
            cleaned = line
            if cleaned and cleaned[0].isdigit() and ". " in cleaned[:4]:
                cleaned = cleaned.split(". ", 1)[-1]

            lower = cleaned.lower()
            if any(w in lower for w in ["тело", "физическ", "йог", "дыхание", "спорт", "сон", "движение", "тренировк", "прогулк"]):
                category = "Тело"
            elif any(w in lower for w in ["ум", "мысл", "анализ", "изучени", "чтение", "план", "интеллект", "обучени", "запис", "внимание"]):
                category = "Ум"
            elif any(w in lower for w in ["дух", "медитаци", "осознанност", "тишина", "благодарност", "духовн", "молитв", "смысл"]):
                category = "Дух"
            else:
                category = "Практика"

            effect = ""
            m = re.search(
                r"(?:ожидаемый\s+)?эффект\s*[:\-–—]\s*(.+?)$",
                cleaned, re.IGNORECASE,
            )
            if m:
                effect = m.group(1).strip().rstrip(".")
                cleaned = re.sub(
                    r"\s*(?:ожидаемый\s+)?эффект\s*[:\-–—]\s*.+?$",
                    "", cleaned, flags=re.IGNORECASE,
                ).strip()

            result.append({"number": i, "text": cleaned, "category": category, "effect": effect})
        return result

    @staticmethod
    def parse_psych_blocks(raw_text: str, arcana_names: dict[str, str] | None = None) -> list[dict]:
        if not raw_text or not raw_text.strip():
            return [{"arcana": "", "arcana_name": "", "belief": raw_text or "", "manifestation": "", "strategy": ""}]

        import re

        arcana_names = arcana_names or {}
        blocks: list[dict] = []

        sections = re.split(
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*)*(?:Аркан\s*(\d+)|(\d+)-?(?:й|ой|ий)?\s*аркан)",
            raw_text.strip(), flags=re.IGNORECASE,
        )
        sections = [s.strip() for s in sections if s and s.strip() and not s.strip().isdigit()]

        if not sections:
            sections = [raw_text.strip()]

        for section in sections:
            block: dict[str, str] = {"arcana": "", "arcana_name": "", "belief": "", "manifestation": "", "strategy": ""}

            arcana_match = re.search(r"Аркан\s*(\d+)|(\d+)-?(?:й|ой|ий)?\s*аркан", section, re.IGNORECASE)
            if arcana_match:
                num = arcana_match.group(1) or arcana_match.group(2)
                block["arcana"] = num
                from core.services.matrix import ARCANA
                block["arcana_name"] = arcana_names.get(num, ARCANA.get(int(num), {}).get("name", ""))

            def _extract(label_pattern: str, next_labels: list[str]) -> str:
                pat = rf"(?:{label_pattern})\s*[:\-–—]?\s*(.+?)(?=(?:{'|'.join(next_labels)})|$)"
                m = re.search(pat, section, re.IGNORECASE | re.DOTALL)
                return m.group(1).strip() if m else ""

            block["belief"] = _extract(
                r"убеждени[ея]|установк[аи]",
                [r"как\s+проявляет", r"проявлени", r"в\s+поведени", r"пример", r"стратеги", r"перепрограммир"],
            )
            block["manifestation"] = _extract(
                r"как\s+проявляет|проявлени[ея]|в\s+поведении|пример[ы]\s*в\s+жизни",
                [r"стратеги", r"перепрограммир", r"как\s+изменить", r"шаг", r"действи", r"практик"],
            )
            block["strategy"] = _extract(
                r"стратеги[яю]|перепрограммир|как\s+изменить|шаг[и]?|действи[ея]|практик[аи]",
                [],
            )

            if any(v for v in block.values()):
                blocks.append(block)
            else:
                blocks.append({
                    "arcana": block["arcana"],
                    "arcana_name": block["arcana_name"],
                    "belief": section,
                    "manifestation": "",
                    "strategy": "",
                })

        return blocks if blocks else [{"arcana": "", "arcana_name": "", "belief": raw_text, "manifestation": "", "strategy": ""}]
