import uuid
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.config import settings

ROMAN_NUMBERS = {
    1: "I", 2: "II", 3: "III", 4: "IV", 5: "V",
    6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X",
    11: "XI", 12: "XII", 13: "XIII", 14: "XIV", 15: "XV",
    16: "XVI", 17: "XVII", 18: "XVIII", 19: "XIX", 20: "XX",
    21: "XXI", 22: "XXII",
}

MONTH_NAMES = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}

MONTH_NAMES_GEN = {
    1: "январь", 2: "февраль", 3: "март", 4: "апрель",
    5: "май", 6: "июнь", 7: "июль", 8: "август",
    9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
}


def int_to_roman(n: int) -> str:
    return ROMAN_NUMBERS.get(n, str(n))


def format_line_nums(nums: list[int] | None) -> str:
    if not nums:
        return ""
    return " — ".join(str(n) for n in nums)


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
    async def render_report_html(report, session_factory: async_sessionmaker, template_name: str = "full_report.html") -> str | None:
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
            "inner_f": matrix_data.get("inner_f"),
            "inner_g": matrix_data.get("inner_g"),
            "inner_h": matrix_data.get("inner_h"),
            "inner_i": matrix_data.get("inner_i"),
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
            "archetype_key": analysis.get("archetype_key", ""),
            "year_arcana_name": ARCANA.get(current_year_arcana, {}).get("name", ""),
            "current_year": date.today().year,
            "recommendations_parsed": recommendations_parsed,
            "psych_blocks": psych_blocks,
            "chakra_data": chakra_data,
            "life_periods": life_periods,
            "year_forecast": year_forecast,
            "current_year_arcana": current_year_arcana,
            "daily_tarot_arcana": daily_tarot_arcana,
        }

        return ReportService.generate_html_report(report_data, template_name=template_name)

    @staticmethod
    def _build_v2_report_data(matrix_data: dict, analysis: dict, kitchen_analysis: dict | None,
                               user_name: str, archetype_number: int, archetype_name: str,
                               token: str) -> dict:
        from core.services.matrix import ARCANA

        arcana_names = matrix_data.get("arcana_names", {})

        birth_date_raw = matrix_data.get("birth_date", "")
        bd_parts = birth_date_raw.split(".") if birth_date_raw else []
        bd_obj = None
        age = 0
        birth_date_formatted = birth_date_raw
        if len(bd_parts) == 3:
            try:
                bd_obj = date(int(bd_parts[2]), int(bd_parts[1]), int(bd_parts[0]))
                today = date.today()
                age = today.year - bd_obj.year - ((today.month, today.day) < (bd_obj.month, bd_obj.day))
                birth_date_formatted = f"{int(bd_parts[0])} {MONTH_NAMES.get(int(bd_parts[1]), bd_parts[1])} {bd_parts[2]} года"
            except (ValueError, IndexError):
                pass

        archetype_roman = int_to_roman(archetype_number)
        archetype_full = f"{archetype_roman}. {archetype_name}"

        today = date.today()
        current_year = today.year
        generated_at_raw = today.strftime("%d.%m.%Y")
        generated_at_formatted = f"{today.day} {MONTH_NAMES_GEN.get(today.month, today.month)} {today.year}"

        initials = "".join(c for c in user_name if c.isalpha() and c.isascii())[:2].upper()
        report_number = f"NR-{today.year}-{today.month:02d}{today.day:02d}-{initials or 'XX'}"

        sky_line_list = matrix_data.get("sky_line", [])
        earth_line_list = matrix_data.get("earth_line", [])
        money_line_list = matrix_data.get("money_line", [])
        karmic_tail_list = matrix_data.get("karmic_tail", [])

        sky_line_nums = format_line_nums(sky_line_list)
        earth_line_nums = format_line_nums(earth_line_list)
        money_line_nums = format_line_nums(money_line_list)
        karmic_tail_nums = format_line_nums(karmic_tail_list)

        inner_f = matrix_data.get("inner_f", 0)
        inner_g = matrix_data.get("inner_g", 0)
        inner_h = matrix_data.get("inner_h", 0)
        inner_i = matrix_data.get("inner_i", 0)
        center = matrix_data.get("center", 0)
        top = matrix_data.get("top", 0)
        left = matrix_data.get("left", 0)
        right = matrix_data.get("right", 0)
        bottom = matrix_data.get("bottom", 0)

        father_line_nums = format_line_nums([inner_g, center, inner_i])
        mother_line_nums = format_line_nums([inner_f, center, inner_h])

        matrix_svg_cells = [
            inner_f, top, inner_g,
            left, center, right,
            matrix_data.get("comfort_zone", 0), bottom, matrix_data.get("portrait_zone", 0),
        ]

        talent_zone = matrix_data.get("talent_zone", 0)
        comfort_zone = matrix_data.get("comfort_zone", 0)
        portrait_zone = matrix_data.get("portrait_zone", 0)

        dashboard_talent_title = arcana_names.get("talent_zone", "") or ARCANA.get(talent_zone, {}).get("name", "")
        dashboard_talent_sub = "зона таланта"
        dashboard_block_title = arcana_names.get("comfort_zone", "") or ARCANA.get(comfort_zone, {}).get("name", "")
        dashboard_block_sub = "зона комфорта"
        dashboard_purpose_title = arcana_names.get("portrait_zone", "") or ARCANA.get(portrait_zone, {}).get("name", "")
        dashboard_purpose_sub = "зона портрета"

        year_arcana_num = 0
        year_arcana_name_val = ""
        if bd_obj:
            try:
                from core.services.matrix import MatrixService
                year_arcana_num = MatrixService.calculate_year_arcana(bd_obj, current_year)
                year_arcana_name_val = ARCANA.get(year_arcana_num, {}).get("name", "")
            except Exception:
                pass
        year_arcana_roman = int_to_roman(year_arcana_num) if year_arcana_num else ""
        year_arcana_full = f"{year_arcana_roman}. {year_arcana_name_val}" if year_arcana_roman else ""

        karmic_analysis = analysis.get("karmic_tail_analysis", "")
        karmic_cause_text = ""
        karmic_effect_text = ""
        karmic_lesson_text = ""
        if karmic_analysis:
            parts = karmic_analysis.split("Следствие")
            if len(parts) >= 2:
                karmic_cause_text = parts[0].strip()
                rest = "Следствие" + parts[1]
                parts2 = rest.split("Урок")
                if len(parts2) >= 2:
                    karmic_effect_text = parts2[0].strip()
                    karmic_lesson_text = "Урок" + parts2[1].strip()
                else:
                    karmic_effect_text = rest.strip()
            else:
                karmic_cause_text = karmic_analysis

        chakra_data = {}
        life_periods_data = {}
        daily_tarot_arcana = {}
        if bd_obj:
            try:
                from core.services.matrix import MatrixService
                from core.schemas import MatrixData
                from core.services.daily_arcana import get_today_arcana_with_name
                matrix_obj = MatrixData(**matrix_data)
                chakra_data = MatrixService.calculate_chakras(matrix_obj)
                life_periods_data = MatrixService.calculate_life_periods(bd_obj)
                daily_tarot_arcana = get_today_arcana_with_name(
                    birth_date_raw, arcana_names
                )
            except Exception:
                pass

        psy_raw = analysis.get("psychological_blocks", "")
        psych_blocks = ReportService.parse_psych_blocks(psy_raw, arcana_names)

        life_periods_nodes = []
        if life_periods_data:
            raw_nodes = life_periods_data if isinstance(life_periods_data, list) else life_periods_data.get("nodes", [])
            for node in raw_nodes:
                node_age = node.get("age", 0) if isinstance(node, dict) else getattr(node, "age", 0)
                node_arcana = node.get("arcana", 0) if isinstance(node, dict) else getattr(node, "arcana", 0)
                passed = node_age < age
                now = node_age == age or (age > 0 and abs(node_age - age) <= 3)
                arcana_label = ARCANA.get(node_arcana, {}).get("name", "")[:10] if node_arcana else ""
                age_label = f"{node_age} лет" if node_age != age else f"{node_age} · сейчас"
                life_periods_nodes.append({
                    "age": node_age,
                    "age_label": age_label,
                    "arcana": node_arcana,
                    "arcana_name": arcana_label,
                    "passed": passed,
                    "now": now,
                })

        return {
            "user_name": user_name,
            "birth_date_raw": birth_date_raw,
            "birth_date_formatted": birth_date_formatted,
            "age": age,
            "archetype_name": archetype_name,
            "archetype_number": archetype_number,
            "archetype_roman": archetype_roman,
            "archetype_full": archetype_full,
            "archetype_key": analysis.get("archetype_key", ""),
            "sky_line_nums": sky_line_nums,
            "earth_line_nums": earth_line_nums,
            "karmic_tail_nums": karmic_tail_nums,
            "karmic_tail_list": karmic_tail_list,
            "money_line_nums": money_line_nums,
            "father_line_nums": father_line_nums,
            "mother_line_nums": mother_line_nums,
            "current_year": current_year,
            "year_arcana_name": year_arcana_name_val,
            "year_arcana_roman": year_arcana_roman,
            "year_arcana_full": year_arcana_full,
            "generated_at_raw": generated_at_raw,
            "generated_at_formatted": generated_at_formatted,
            "report_number": report_number,
            "matrix_svg_cells": matrix_svg_cells,
            "arcana_names": arcana_names,
            "dashboard_talent_title": dashboard_talent_title,
            "dashboard_talent_sub": dashboard_talent_sub,
            "dashboard_block_title": dashboard_block_title,
            "dashboard_block_sub": dashboard_block_sub,
            "dashboard_purpose_title": dashboard_purpose_title,
            "dashboard_purpose_sub": dashboard_purpose_sub,
            "karmic_cause_text": karmic_cause_text,
            "karmic_effect_text": karmic_effect_text,
            "karmic_lesson_text": karmic_lesson_text,
            "analysis": analysis,
            "kitchen_analysis": kitchen_analysis,
            "dashboard_insights": analysis.get("dashboard_insights") or {},
            "chakra_data": chakra_data,
            "life_periods": {"nodes": life_periods_nodes} if life_periods_nodes else {},
            "daily_tarot_arcana": daily_tarot_arcana,
            "psych_blocks": psych_blocks,
            "recommendations_parsed": ReportService.parse_recommendations(
                analysis.get("ai_recommendations", "")
            ),
        }

    @staticmethod
    async def render_report_v2_html(report, session_factory: async_sessionmaker) -> str | None:
        from core.repositories.user import UserRepository
        from core.services.matrix import ARCANA

        matrix_data = report.matrix_data or {}
        analysis = report.ai_analysis or {}
        user_id = matrix_data.get("user_id") or str(report.user_id)
        uid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

        user_repo = UserRepository(session_factory)
        user = await user_repo.get(uid)

        if not user:
            user_name = "пользователь"
            archetype_number = matrix_data.get("center", 0)
            archetype_name = ARCANA.get(archetype_number, {}).get("name", "Неизвестный")
        else:
            user_name = user.first_name or user.username or "пользователь"
            archetype_number = user.main_archetype_number or matrix_data.get("center", 0)
            archetype_name = user.main_archetype or ARCANA.get(archetype_number, {}).get("name", "Неизвестный")

        report_data = ReportService._build_v2_report_data(
            matrix_data=matrix_data,
            analysis=analysis,
            kitchen_analysis=report.kitchen_analysis,
            user_name=user_name,
            archetype_number=archetype_number,
            archetype_name=archetype_name,
            token=report.token,
        )

        return ReportService.generate_html_report(report_data, template_name="full_report_v2.html")

    @staticmethod
    def _is_fallback_analysis(analysis: dict | None) -> bool:
        if not analysis or not isinstance(analysis, dict):
            return True
        fallback_markers = [
            "чуть больше времени",
            "мне нужно время",
            "вернусь с точным",
            "вернусь с результатом",
            "попробуй запросить разбор",
            "повтори запрос через минуту",
            "запроси разбор повторно",
            "мне требуется дополнительное время",
            "я подготовлю точный",
            "уточню анализ",
            "я уточню расчёты",
            "я подготовлю детальный разбор",
            "я подготовлю разбор и вернусь",
        ]
        for _field, value in analysis.items():
            if isinstance(value, str):
                for marker in fallback_markers:
                    if marker.lower() in value.lower():
                        return True
        return False

    @staticmethod
    def parse_recommendations(text: str) -> list[dict]:
        """
        Парсит ai_recommendations в список до 7 элементов.
        Ожидаемые форматы:
          "1. текст 2. текст..." (без newline) или
          "1. текст\n2. текст\n..." (с newline)
        """
        import re
        parts = re.split(r'\s+(?=\d+\.\s)', text.strip())
        if len(parts) < 2:
            parts = re.split(r'\n(?=\d+\.)', text.strip())
        result = []
        for item in parts:
            match = re.match(r'^(\d+)\.\s*(.+)', item.strip(), re.DOTALL)
            if match:
                number = int(match.group(1))
                day_text = match.group(2).strip()
                telo = ['тело', 'физич', 'йога', 'дыхан', 'спорт', 'сон', 'движен', 'прогулк', 'вода']
                um = ['ум', 'мысл', 'анализ', 'изучен', 'чтен', 'план', 'запис', 'вниман', 'фокус']
                duh = ['медитац', 'осознан', 'тишин', 'благодарн', 'смысл', 'рефлекс', 'духовн']
                low = day_text.lower()
                if any(w in low for w in telo):
                    category = 'Тело'
                elif any(w in low for w in um):
                    category = 'Ум'
                elif any(w in low for w in duh):
                    category = 'Дух'
                else:
                    category = 'Практика'
                result.append({'number': number, 'text': day_text, 'category': category})
        if len(result) == 0:
            result = [{'number': 1, 'text': text[:500], 'category': 'Практика'}]
        return result[:7]

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
