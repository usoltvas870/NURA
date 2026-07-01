import re
from typing import Any


class LogParser:
    ERROR_PATTERNS: list[re.Pattern] = [
        re.compile(r"\bERROR\b", re.IGNORECASE),
        re.compile(r"\bCRITICAL\b", re.IGNORECASE),
        re.compile(r"\bFATAL\b", re.IGNORECASE),
        re.compile(r"\bException\b"),
        re.compile(r"\bTraceback\b"),
        re.compile(r"\bUnhandled\b", re.IGNORECASE),
        re.compile(r"HTTP/\d\.\d\s+5\d{2}"),
    ]

    # Patterns to exclude from error reports (noise)
    FILTER_OUT: list[re.Pattern] = [
        re.compile(r"heartbeat", re.IGNORECASE),
        re.compile(r"keepalive", re.IGNORECASE),
        re.compile(r"health check", re.IGNORECASE),
        re.compile(r"GET /health", re.IGNORECASE),
        re.compile(r"HEAD /", re.IGNORECASE),
    ]

    @classmethod
    def is_error_line(cls, line: str) -> bool:
        for pat in cls.FILTER_OUT:
            if pat.search(line):
                return False
        for pat in cls.ERROR_PATTERNS:
            if pat.search(line):
                return True
        return False

    @classmethod
    def extract_errors(
        cls, lines: list[str], max_per_container: int = 10
    ) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        for line in lines:
            if cls.is_error_line(line):
                errors.append({"line": line[:500]})
                if len(errors) >= max_per_container:
                    break
        return errors

    @classmethod
    def extract_traceback(cls, lines: list[str], error_index: int) -> str:
        """Extract traceback context around an error line."""
        start = max(0, error_index - 5)
        end = min(len(lines), error_index + 15)
        return "\n".join(lines[start:end])
