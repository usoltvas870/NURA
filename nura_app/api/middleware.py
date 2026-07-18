"""Request-scoped observability primitives."""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def request_id_from_header(value: str | None) -> str:
    """Accept a bounded opaque correlation ID or generate a new one."""
    if value and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return uuid.uuid4().hex


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request_id_from_header(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed event=request_failed request_id=%s method=%s path=%s",
                request_id,
                request.method,
                request.url.path,
            )
            raise
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request_completed event=request_completed request_id=%s method=%s path=%s status=%s duration_ms=%d",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response
