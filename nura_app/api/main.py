import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.admin import setup_admin
from api.deps import limiter
from api.routes.reports import router as reports_router
from api.routes.web import router as web_router
from api.routes.payment import router as payment_router
from api.routes.push import router as push_router
from api.routes.admin_api import router as admin_api_router
from api.routes.tarot_pwa import router as tarot_pwa_router

app = FastAPI(title="NURA API", version="1.0.0", docs_url=None, redoc_url=None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://nura-ai.ru", "https://www.nura-ai.ru"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(web_router)
app.include_router(reports_router)
app.include_router(payment_router)
app.include_router(push_router)
app.include_router(admin_api_router)
app.include_router(tarot_pwa_router)

setup_admin(app)


@app.on_event("startup")
async def startup():
    from core.database import create_engine
    from core.models import Base
    engine = create_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    logger = logging.getLogger(__name__)
    logger.info("Database tables ensured")


@app.get("/health")
async def health():
    return {"status": "ok"}
