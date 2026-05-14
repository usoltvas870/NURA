from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.deps import limiter
from api.routes.reports import router as reports_router
from api.routes.webhook import router as webhook_router
from api.routes.payment import router as payment_router

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

app.include_router(webhook_router)
app.include_router(reports_router)
app.include_router(payment_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
