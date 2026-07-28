"""Production-safe redaction for sensitive Uvicorn request targets."""

from __future__ import annotations

import logging
import re
from typing import Any


_CHECKOUT_PATH = re.compile(
    r"(/api/v1/payment/full-matrix/(?:checkout|return)/)[^/?#]+"
)


class UvicornAccessRedactionFilter(logging.Filter):
    """Retain access-log observability while removing bearer capabilities."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 3 or not isinstance(args[2], str):
            return True
        redacted_path = _CHECKOUT_PATH.sub(r"\1<redacted>", args[2])
        if redacted_path != args[2]:
            record.args = (*args[:2], redacted_path, *args[3:])
        return True


def configure_uvicorn_access_redaction() -> None:
    """Install one idempotent filter for canonical ``api.main:app`` startup."""
    logger = logging.getLogger("uvicorn.access")
    if any(isinstance(item, UvicornAccessRedactionFilter) for item in logger.filters):
        return
    logger.addFilter(UvicornAccessRedactionFilter())


def scrub_sentry_event(
    event: dict[str, Any], _hint: dict[str, Any]
) -> dict[str, Any]:
    """Remove user-controlled values while retaining bounded diagnostics."""
    request = event.get("request")
    if isinstance(request, dict):
        method = request.get("method")
        event["request"] = {"method": method} if isinstance(method, str) else {}
    event.pop("user", None)
    event.pop("breadcrumbs", None)
    event.pop("contexts", None)
    event.pop("logentry", None)
    event.pop("message", None)

    extra = event.get("extra")
    if isinstance(extra, dict):
        event["extra"] = {
            key: value
            for key, value in extra.items()
            if key in {"error_category", "correlation_id"}
            and isinstance(value, (str, int, float, bool, type(None)))
        }
    tags = event.get("tags")
    if isinstance(tags, dict):
        event["tags"] = {
            key: value
            for key, value in tags.items()
            if key in {"service", "error_category", "correlation_id"}
            and isinstance(value, (str, int, float, bool, type(None)))
        }

    exception = event.get("exception")
    values = exception.get("values", []) if isinstance(exception, dict) else []
    for value in values:
        if not isinstance(value, dict):
            continue
        if "value" in value:
            value["value"] = "<redacted>"
        stacktrace = value.get("stacktrace")
        frames = stacktrace.get("frames", []) if isinstance(stacktrace, dict) else []
        for frame in frames:
            if isinstance(frame, dict):
                frame.pop("vars", None)
    return event
