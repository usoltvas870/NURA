import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.schemas import MatrixData

logger = logging.getLogger(__name__)

BANNED_WORDS = [
    "гадание",
    "карма",
    "порча",
    "магия",
    "сглаз",
    "проклятие",
    "шаман",
    "ведьма",
    "колдовство",
    "экстрасенс",
]

GENERIC_PHRASES = [
    "будь собой",
    "слушай сердце",
    "доверяй себе",
    "всё будет хорошо",
    "просто будь",
    "прислушайся к себе",
    "внутренний голос подскажет",
]


@dataclass
class VerificationResult:
    passed: bool
    issues: list[str] = field(default_factory=list)


class ContentVerifier:

    @staticmethod
    def check_length(
        text: str, min_words: int = 50, field_name: str = ""
    ) -> str | None:
        word_count = len(text.split())
        if word_count < min_words:
            label = f"«{field_name}»" if field_name else "поле"
            return f"{label}: {word_count} слов, минимум {min_words}"
        return None

    @staticmethod
    def check_max_length(
        text: str, max_words: int = 250, field_name: str = ""
    ) -> str | None:
        word_count = len(text.split())
        if word_count > max_words:
            label = f"«{field_name}»" if field_name else "поле"
            return f"{label}: {word_count} слов, максимум {max_words}"
        return None

    @staticmethod
    def check_banned_words(text: str) -> list[str]:
        found: list[str] = []
        text_lower = text.lower()
        for word in BANNED_WORDS:
            if word in text_lower:
                found.append(f"запрещённое слово «{word}»")
        return found

    @staticmethod
    def check_generic_phrases(text: str) -> list[str]:
        found: list[str] = []
        text_lower = text.lower()
        for phrase in GENERIC_PHRASES:
            if phrase in text_lower:
                found.append(f"общая фраза «{phrase}»")
        return found

    @staticmethod
    def check_name_in_text(text: str, user_name: str) -> list[str]:
        found: list[str] = []
        name_lower = user_name.lower()
        if name_lower and name_lower not in text.lower():
            found.append(f"нет обращения по имени «{user_name}»")
        return found

    @staticmethod
    def check_not_empty(result_dict: dict) -> list[str]:
        issues: list[str] = []
        for key, value in result_dict.items():
            if value is None:
                issues.append(f"«{key}»: None")
            elif isinstance(value, str) and not value.strip():
                issues.append(f"«{key}»: пустая строка")
            elif isinstance(value, str) and len(value.split()) < 3:
                issues.append(f"«{key}»: слишком коротко ({len(value.split())} слов)")
        return issues

    @staticmethod
    def check_arcana_consistency(
        text: str, matrix_data: Optional["MatrixData"]
    ) -> list[str]:
        if matrix_data is None:
            return []
        matrix_values: set[int] = set()
        for attr in [
            "center", "top", "bottom", "left", "right",
            "talent_zone", "comfort_zone", "portrait_zone",
            "relationship_point", "inner_f", "inner_g", "inner_h", "inner_i",
        ]:
            val = getattr(matrix_data, attr, None)
            if isinstance(val, int) and 1 <= val <= 22:
                matrix_values.add(val)
        for attr in ["karmic_tail", "sky_line", "earth_line", "relationship_line", "money_line"]:
            vals = getattr(matrix_data, attr, None)
            if isinstance(vals, list):
                for v in vals:
                    if isinstance(v, int) and 1 <= v <= 22:
                        matrix_values.add(v)
        issues: list[str] = []
        text_lower = text.lower()
        for arc_num in range(1, 23):
            if arc_num in matrix_values:
                continue
            patterns = [
                f"аркан {arc_num}",
                f"арканом {arc_num}",
                f"аркане {arc_num}",
                f"{arc_num}-й аркан",
                f"энергия {arc_num}",
            ]
            for pat in patterns:
                if pat in text_lower:
                    issues.append(
                        f"упоминается аркан {arc_num}, но его нет в матрице"
                    )
                    break
        return issues

    @staticmethod
    def check_dashboard_insights(insights: dict | None) -> list[str]:
        if insights is None:
            return []
        issues: list[str] = []
        scores = insights.get("scores", {})
        for key in ("career", "relationships", "finance", "health", "spirit"):
            val = scores.get(key)
            if val is not None and not (1 <= val <= 10):
                issues.append(f"dashboard score «{key}» вне диапазона 1-10: {val}")
        return issues

    @classmethod
    def verify_report(
        cls,
        report_dict: dict,
        matrix_data: Optional["MatrixData"] = None,
        min_words: int = 50,
    ) -> VerificationResult:
        issues: list[str] = []
        report_for_empty = {}
        for key, value in report_dict.items():
            if key == "dashboard_insights":
                if isinstance(value, dict):
                    issues.extend(cls.check_dashboard_insights(value))
                continue
            report_for_empty[key] = value
            if isinstance(value, str):
                issues.extend(cls.check_banned_words(value))
                issues.extend(cls.check_generic_phrases(value))
                length_issue = cls.check_length(value, min_words=min_words, field_name=key)
                if length_issue:
                    issues.append(length_issue)
        issues.extend(cls.check_not_empty(report_for_empty))
        if matrix_data:
            all_text = " ".join(
                str(v) for v in report_dict.values() if isinstance(v, str)
            )
            issues.extend(cls.check_arcana_consistency(all_text, matrix_data))
        if issues:
            logger.warning("Content verification: %d issue(s)", len(issues))
            for issue in issues:
                logger.debug("  - %s", issue)
        return VerificationResult(passed=len(issues) == 0, issues=issues)

    @classmethod
    def verify_text(
        cls,
        text: str,
        min_words: int = 50,
        max_words: int | None = None,
        check_banned: bool = True,
        check_tone: bool = True,
        field_name: str = "",
        user_name: str = "",
    ) -> VerificationResult:
        issues: list[str] = []
        length_issue = cls.check_length(text, min_words=min_words, field_name=field_name)
        if length_issue:
            issues.append(length_issue)
        if max_words is not None:
            max_issue = cls.check_max_length(text, max_words=max_words, field_name=field_name)
            if max_issue:
                issues.append(max_issue)
        if check_banned:
            issues.extend(cls.check_banned_words(text))
        if check_tone:
            issues.extend(cls.check_generic_phrases(text))
        if user_name:
            issues.extend(cls.check_name_in_text(text, user_name))
        return VerificationResult(passed=len(issues) == 0, issues=issues)
