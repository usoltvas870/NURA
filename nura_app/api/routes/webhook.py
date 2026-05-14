import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.config import settings

router = APIRouter(prefix="/webhook")

TELEGRAM_API = f"https://api.telegram.org/bot{settings.telegram_bot_token}"


@router.post("/telegram")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
    except (json.JSONDecodeError, ValueError):
        return JSONResponse({"status": "invalid json"}, status_code=400)

    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.post(f"{TELEGRAM_API}/processUpdate", json=data)

    return JSONResponse({"status": "ok"})
