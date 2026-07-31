import sentry_sdk
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.admin import setup_admin
from api.deps import limiter
from api.logging import configure_uvicorn_access_redaction, scrub_sentry_event
from api.middleware import RequestCorrelationMiddleware, SandboxPublicIngressMiddleware
from api.routes.reports import router as reports_router
from api.routes.web import router as web_router
from api.routes.payment import router as payment_router
from api.routes.push import router as push_router
from api.routes.admin_api import router as admin_api_router
from api.routes.tarot_pwa import router as tarot_pwa_router
from api.routes.auth import router as auth_router

from core.config import settings
from core.database import get_async_sessionmaker, get_redis
from core.services.prompt_governance import validate_active_prompt_bundles
from core.services.external_sandbox import (
    validate_sandbox_database_head,
    validate_sandbox_startup,
)


configure_uvicorn_access_redaction()
validate_sandbox_startup(settings)
validate_active_prompt_bundles()


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with get_async_sessionmaker()() as session:
        await validate_sandbox_database_head(session, settings)
    yield


def payment_webhook_readiness_status() -> str:
    """Expose only a safe category for payment webhook configuration."""
    return "ok" if settings.payment_webhook_configuration_error is None else "missing_configuration"

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=0.3,
        environment=settings.app_env,
        send_default_pii=False,
        before_send=scrub_sentry_event,
    )

app = FastAPI(
    title="NURA API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allowed_origins_list),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestCorrelationMiddleware)
app.add_middleware(SandboxPublicIngressMiddleware)

app.include_router(web_router)
app.include_router(reports_router)
app.include_router(payment_router)
app.include_router(push_router)
app.include_router(admin_api_router)
app.include_router(tarot_pwa_router)
app.include_router(auth_router)

setup_admin(app)


@app.get("/health")
async def health(request: Request):
    """Liveness probe: it deliberately does not call external dependencies."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request.state.request_id,
    }


@app.get("/ready")
async def readiness(request: Request):
    """Readiness probe with safe dependency categories and no secret output."""
    dependencies: dict[str, str] = {
        "database": "ok",
        "redis": "ok",
        "ai_configuration": "ok" if settings.deepseek_api_key else "missing_configuration",
        "payment_configuration": payment_webhook_readiness_status(),
    }
    try:
        async with get_async_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
            await validate_sandbox_database_head(session, settings)
    except Exception:
        dependencies["database"] = "unavailable"
    try:
        await get_redis().ping()
    except Exception:
        dependencies["redis"] = "unavailable"

    ready = all(value == "ok" for value in dependencies.values())
    payload = {
        "status": "ready" if ready else "not_ready",
        "dependencies": dependencies,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request.state.request_id,
    }
    return JSONResponse(payload, status_code=200 if ready else 503)
