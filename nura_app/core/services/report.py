import uuid
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy.ext.asyncio import async_sessionmaker

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
    async def get_report_by_token(session_factory: async_sessionmaker, token: str):
        from core.repositories.report import ReportRepository
        repo = ReportRepository(session_factory)
        return await repo.get_by_token(token)

    @staticmethod
    async def render_report_html(report, session_factory: async_sessionmaker) -> str | None:
        from core.repositories.user import UserRepository
        from core.services.matrix import ARCANA, MatrixService
        from core.services.daily_arcana import get_today_arcana_with_name

        matrix_data = report.matrix_data or {}
        analysis = report.ai_analysis or {}
        user_id = matrix_data.get("user_id") or str(report.user_id)
        uid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

        user_repo = UserRepository(session_factory)
        user = await user_repo.get(uid)

        if not user:
            user_name = "пользователь"
            archetype_name = ARCANA.get(matrix_data.get("center", 0), {}).get("name", "Неизвестный")
            archetype_number = matrix_data.get("center", 0)
        else:
            user_name = user.first_name or user.username or "пользователь"
            archetype_number = user.main_archetype_number or matrix_data.get("center", 0)
            archetype_name = user.main_archetype or ARCANA.get(archetype_number, {}).get("name", "Неизвестный")

        recommendations_parsed = ReportService.parse_recommendations(
            analysis.get("ai_recommendations", "")
        )
        psych_blocks = ReportService.parse_psych_blocks(
            analysis.get("psychological_blocks", ""),
            arcana_names=matrix_data.get("arcana_names", {}),
        )

        matrix_obj = None
        birth_date = matrix_data.get("birth_date", "") or (user.birth_date if user else "")
        try:
            if matrix_data.get("center"):
                from core.schemas import MatrixData
                matrix_obj = MatrixData(**matrix_data)
        except Exception:
            pass

        if matrix_obj:
            chakra_data = MatrixService.calculate_chakras(matrix_obj)
            bd_parts = birth_date.split(".")
            if len(bd_parts) == 3:
                try:
                    bd = date(int(bd_parts[2]), int(bd_parts[1]), int(bd_parts[0]))
                    current_year = date.today().year
                    life_periods = MatrixService.calculate_life_periods(bd)
                    year_forecast = MatrixService.calculate_year_forecast(bd, current_year)
                    current_year_arcana = MatrixService.calculate_year_arcana(bd, current_year)
                    daily_tarot_arcana = get_today_arcana_with_name(birth_date, matrix_data.get("arcana_names", {}))
                except Exception:
                    chakra_data = {}
                    life_periods = {}
                    year_forecast = {}
                    current_year_arcana = 0
                    daily_tarot_arcana = {}
            else:
                chakra_data = {}
                life_periods = {}
                year_forecast = {}
                current_year_arcana = 0
                daily_tarot_arcana = {}
        else:
            chakra_data = {}
            life_periods = {}
            year_forecast = {}
            current_year_arcana = 0
            daily_tarot_arcana = {}

        matrix_raw = {
            "center": matrix_data.get("center"),
            "top": matrix_data.get("top"),
            "bottom": matrix_data.get("bottom"),
            "left": matrix_data.get("left"),
            "right": matrix_data.get("right"),
            "talent_zone": matrix_data.get("talent_zone"),
            "comfort_zone": matrix_data.get("comfort_zone"),
            "portrait_zone": matrix_data.get("portrait_zone"),
            "karmic_tail": matrix_data.get("karmic_tail"),
            "sky_line": matrix_data.get("sky_line"),
            "earth_line": matrix_data.get("earth_line"),
            "relationship_line": matrix_data.get("relationship_line"),
            "money_line": matrix_data.get("money_line"),
            "relationship_point": matrix_data.get("relationship_point"),
            "arcana_names": matrix_data.get("arcana_names", {}),
        }

        report_data = {
            "matrix": matrix_raw,
            "analysis": analysis,
            "kitchen_analysis": report.kitchen_analysis,
            "user_name": user_name,
            "archetype_name": archetype_name,
            "archetype_number": archetype_number,
            "recommendations_parsed": recommendations_parsed,
            "psych_blocks": psych_blocks,
            "chakra_data": chakra_data,
            "life_periods": life_periods,
            "year_forecast": year_forecast,
            "current_year_arcana": current_year_arcana,
            "daily_tarot_arcana": daily_tarot_arcana,
        }

        return ReportService.generate_html_report(report_data)

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
