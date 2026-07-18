"""Local-only ASGI API harness for E2E tests against real PWA assets."""

from __future__ import annotations

import asyncio
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from api.routes.tarot_pwa import DailyCardResponse, SpreadRequest, SpreadResponse
from api.routes.web import (
    CreatePaymentRequest,
    CreatePaymentResponse,
    GenerateLinkTokenResponse,
    MiniAnalysisResponse,
    NotificationPrefRequest,
    NotificationPrefsResponse,
    ReportItem,
    SubscribeRequest,
    SubscribeResponse,
    UserProfileResponse,
)
from core.schemas.auth import EmailAuthRequest, EmailAuthResponse
from core.schemas.chat import ChatQuotaState, ChatRequest, ChatResponse


ROOT = Path(__file__).resolve().parents[2]
PWA = ROOT / "frontend" / "pwa"
APP = PWA / "app"
VENDOR = ROOT / "frontend" / "assets" / "vendor"
PERSONA_HEADER = "X-NURA-E2E-Persona"
PERSONAS = frozenset(
    {
        "guest", "free", "premium", "expired", "matrix_owner", "report_owner",
        "telegram_connected", "telegram_disconnected", "chat_limit", "loading",
        "telegram_pending", "telegram_linked", "telegram_expired",
        "telegram_confirm_invalid", "telegram_confirm_missing", "telegram_confirm_conflict",
        "telegram_confirm_failure", "telegram_confirm_timeout", "telegram_cancel_failure",
        "error", "offline", "slow", "http_400", "http_401", "http_402",
        "http_403", "http_404", "http_409", "http_422", "http_429", "http_500",
        "http_502", "http_503", "timeout",
    }
)
ERROR_PERSONAS = {name: int(name.removeprefix("http_")) for name in PERSONAS if name.startswith("http_")}
E2E_NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
SLOW_SECONDS = 0.05


class RequestRecord(BaseModel):
    order: int
    timestamp: str
    method: str
    path: str
    persona: str
    payload: dict[str, Any]


class HarnessState(BaseModel):
    persona: str = Field(default="free", pattern=r"^[a-z_]+$")
    notifications: dict[str, dict[str, bool]] = Field(default_factory=dict)
    request_log: list[RequestRecord] = Field(default_factory=list)
    release: Any = Field(default_factory=threading.Event, exclude=True)
    email_tokens: dict[str, dict[str, Any]] = Field(default_factory=dict)
    email_outbox: list[dict[str, Any]] = Field(default_factory=list)
    email_provider_failed: bool = False


def _telegram_status(persona: str) -> dict[str, Any]:
    if persona == "telegram_linked":
        return {"status": "linked"}
    if persona == "telegram_expired":
        return {"status": "expired"}
    if persona == "telegram_pending" or persona.startswith("telegram_confirm_") or persona == "telegram_cancel_failure":
        return {"status": "pending_confirmation", "expires_in": 540, "attempts_remaining": 3}
    return {"status": "idle"}


def _reports(persona: str) -> list[ReportItem]:
    if persona == "matrix_owner":
        return [ReportItem(token="e2e-matrix-report", report_type="full", created_at="01.01.2030", url="/report/e2e-matrix-report")]
    if persona == "report_owner":
        return [ReportItem(token="e2e-finished-report", report_type="mini", created_at="01.01.2030", url="/report/e2e-finished-report")]
    return []


def _profile(persona: str) -> UserProfileResponse:
    if persona == "guest":
        raise HTTPException(status_code=401, detail="authentication_required")
    reports = _reports(persona)
    premium = persona == "premium"
    expired = persona == "expired"
    matrix = persona == "matrix_owner"
    return UserProfileResponse(
        user_id=f"e2e-{persona}", name="E2E User", birth_date="01.01.1990",
        archetype="The Magician", archetype_number=1, has_matrix=matrix,
        has_tarot=premium, report_token=reports[0].token if matrix else None,
        subscription_status="expired" if expired else ("premium" if premium else "free"),
        subscription_until="31.12.2029" if expired else ("31.12.2030" if premium else None),
        tarot_until="31.12.2029" if expired else ("31.12.2030" if premium else None),
        has_pwa_push=False, telegram_linked=persona in {"telegram_connected", "telegram_linked"},
        reports=reports, ref_link=None,
    )


def _daily() -> DailyCardResponse:
    return DailyCardResponse(
        arcana_number=1, arcana_name="The Magician", arcana_symbol="∞",
        key_phrase="Act with attention.", interpretation="A deterministic E2E card.",
        advice="Take one measured step.", affirmation="I can begin.",
        date_label="1 January", user_archetype_name="The Magician", user_archetype_number=1,
    )


def _quota(persona: str) -> ChatQuotaState:
    if persona == "premium":
        return ChatQuotaState(access="subscriber", can_send=True, daily_limit=None, used=None,
                              messages_left=None, reset_at=None, timezone="UTC")
    if persona == "chat_limit":
        return ChatQuotaState(access="free", can_send=False, daily_limit=10, used=10,
                              messages_left=0, reset_at=E2E_NOW, timezone="UTC", code="limit_reached")
    return ChatQuotaState(access="free", can_send=True, daily_limit=10, used=0,
                          messages_left=10, reset_at=E2E_NOW, timezone="UTC")


def _safe_payload(body: Any) -> dict[str, Any]:
    if body is None:
        return {"keys": []}
    if not isinstance(body, dict):
        return {"type": type(body).__name__}
    return {"keys": sorted(str(key) for key in body)}


def create_e2e_harness() -> FastAPI:
    """Return a safe test API and production PWA static files on one origin."""
    if os.environ.get("APP_ENV") != "test":
        raise RuntimeError("NURA E2E harness can run only when APP_ENV=test")

    app = FastAPI(title="NURA E2E harness", docs_url=None, redoc_url=None)
    app.state.e2e = HarnessState()

    def persona(request: Request) -> str:
        selected = request.headers.get(PERSONA_HEADER, app.state.e2e.persona)
        if selected not in PERSONAS:
            raise HTTPException(status_code=400, detail="unknown_e2e_persona")
        return selected

    def record(request: Request, body: Any = None) -> None:
        state: HarnessState = app.state.e2e
        state.request_log.append(RequestRecord(
            order=len(state.request_log) + 1, timestamp=f"2030-01-01T00:00:{len(state.request_log):02d}Z",
            method=request.method, path=request.url.path, persona=persona(request), payload=_safe_payload(body),
        ))

    @app.middleware("http")
    async def e2e_policy(request: Request, call_next):
        request_id = f"e2e-{len(app.state.e2e.request_log) + 1}"
        try:
            selected = persona(request)
            if request.url.path.startswith("/api/") and selected in ERROR_PERSONAS:
                response = JSONResponse(status_code=ERROR_PERSONAS[selected], content={"detail": "e2e_forced_error", "code": selected})
            elif request.url.path == "/api/v1/web/me" and selected == "loading":
                await asyncio.to_thread(app.state.e2e.release.wait)
                app.state.e2e.release.clear()
                response = await call_next(request)
            elif request.url.path.startswith("/api/") and selected == "slow":
                await asyncio.sleep(SLOW_SECONDS)
                response = await call_next(request)
            elif request.url.path == "/api/v1/web/me" and selected == "timeout":
                await asyncio.to_thread(app.state.e2e.release.wait)
                app.state.e2e.release.clear()
                response = JSONResponse(status_code=504, content={"detail": "e2e_timeout", "code": "timeout"})
            elif request.url.path == "/api/v1/web/confirm-telegram-link" and selected == "telegram_confirm_timeout":
                await asyncio.to_thread(app.state.e2e.release.wait)
                app.state.e2e.release.clear()
                response = JSONResponse(status_code=504, content={"detail": "e2e_timeout", "code": "timeout"})
            else:
                response = await call_next(request)
        except HTTPException as exc:
            response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = request_id
        return response

    @app.get("/__e2e__/state")
    async def e2e_state(request: Request) -> dict[str, Any]:
        return {"persona": persona(request), "offline": persona(request) == "offline", "clock": E2E_NOW.isoformat()}

    @app.post("/__e2e__/reset")
    async def reset(request: Request) -> dict[str, bool]:
        app.state.e2e.request_log.clear()
        app.state.e2e.notifications.clear()
        app.state.e2e.release.clear()
        return {"ok": True}

    @app.post("/__e2e__/release")
    async def release(request: Request) -> dict[str, bool]:
        app.state.e2e.release.set()
        return {"ok": True}

    @app.get("/__e2e__/requests")
    async def request_log(request: Request) -> dict[str, Any]:
        return {"count": len(app.state.e2e.request_log), "requests": [item.model_dump() for item in app.state.e2e.request_log]}

    @app.get("/__e2e__/email/outbox")
    async def email_outbox() -> dict[str, Any]:
        return {"count": len(app.state.e2e.email_outbox), "messages": app.state.e2e.email_outbox}

    @app.post("/__e2e__/email/outbox/reset")
    async def reset_email_outbox() -> dict[str, bool]:
        app.state.e2e.email_outbox.clear()
        app.state.e2e.email_tokens.clear()
        app.state.e2e.email_provider_failed = False
        return {"ok": True}

    @app.post("/__e2e__/email/token/expire")
    async def expire_email_token() -> dict[str, bool]:
        for token in app.state.e2e.email_tokens.values():
            token["expired"] = True
        return {"ok": True}

    @app.post("/__e2e__/email/provider/fail")
    async def fail_email_provider() -> dict[str, bool]:
        app.state.e2e.email_provider_failed = True
        return {"ok": True}

    @app.get("/__e2e__/email/state")
    async def email_state() -> dict[str, Any]:
        return {"tokens": len(app.state.e2e.email_tokens), "provider_calls": len(app.state.e2e.email_outbox), "sessions": sum(int(token.get("used", False)) for token in app.state.e2e.email_tokens.values())}

    @app.get("/service-worker.js")
    async def disabled_service_worker() -> Response:
        return Response(status_code=404)

    @app.get("/pwa-install.js")
    async def e2e_install_adapter() -> Response:
        return Response("window.NURA_PWA=window.NURA_PWA||{};", media_type="application/javascript")

    @app.get("/assets/vendor/vkid-sdk.js")
    async def e2e_vkid_asset() -> FileResponse:
        asset = VENDOR / "vkid-sdk.js"
        if not asset.is_file():
            raise HTTPException(status_code=404, detail="not_found")
        return FileResponse(asset, media_type="application/javascript")

    @app.get("/app/{page}")
    async def pwa_page(page: str) -> FileResponse:
        candidate = (APP / page).resolve()
        if candidate.parent != APP.resolve() or not candidate.is_file():
            raise HTTPException(status_code=404, detail="not_found")
        return FileResponse(candidate)

    @app.get("/app/{asset_path:path}")
    async def pwa_asset(asset_path: str) -> FileResponse:
        candidate = (APP / asset_path).resolve()
        if not str(candidate).startswith(str(APP.resolve())) or not candidate.is_file():
            raise HTTPException(status_code=404, detail="not_found")
        return FileResponse(candidate)

    @app.get("/api/v1/web/session-check")
    async def session_check(request: Request) -> dict[str, bool]:
        _profile(persona(request))
        return {"authenticated": True}

    @app.post("/api/v1/auth/email/send", response_model=EmailAuthResponse)
    async def email_send(request: Request, body: EmailAuthRequest) -> EmailAuthResponse:
        if app.state.e2e.email_provider_failed:
            raise HTTPException(status_code=503, detail="email_unavailable")
        order = len(app.state.e2e.email_outbox) + 1
        token = f"e2e-email-{order}"
        app.state.e2e.email_tokens[token] = {"expired": False, "used": False, "flow": "email"}
        app.state.e2e.email_outbox.append({"order": order, "recipient": "e***@example.test", "token": token, "expires_at": "2030-01-01T00:15:00Z", "status": "queued", "timestamp": f"2030-01-01T00:00:{order:02d}Z"})
        record(request, {"email": "redacted", "guest_token": bool(body.guest_token)})
        return EmailAuthResponse(message="If the address can receive mail, a sign-in link has been sent.", expires_in=900)

    @app.get("/api/v1/auth/email/verify")
    async def email_verify(token: str) -> Response:
        entry = app.state.e2e.email_tokens.get(token)
        if not entry or entry["expired"] or entry["used"] or entry["flow"] != "email":
            return Response(status_code=302, headers={"Location": "/?error=token_expired"})
        entry["used"] = True
        response = Response(status_code=302, headers={"Location": "/app/"})
        response.set_cookie("web_session", "e2e-session", httponly=True, samesite="lax")
        return response

    @app.get("/api/v1/web/me", response_model=UserProfileResponse)
    async def me(request: Request) -> UserProfileResponse:
        return _profile(persona(request))

    @app.post("/api/v1/web/logout")
    async def logout(request: Request) -> dict[str, bool]:
        record(request)
        return {"ok": True}

    @app.delete("/api/v1/web/account")
    async def account(request: Request) -> dict[str, bool]:
        record(request)
        return {"ok": True}

    @app.post("/api/v1/web/mini-analysis", response_model=MiniAnalysisResponse)
    async def mini_analysis(request: Request) -> MiniAnalysisResponse:
        record(request)
        return MiniAnalysisResponse(main_archetype="The Magician", core_strength="Focus", emotional_conflict="Doubt", relationship_pattern="Honesty", financial_block="Delay")

    @app.post("/api/v1/web/create-payment", response_model=CreatePaymentResponse)
    async def create_payment(request: Request, body: CreatePaymentRequest) -> CreatePaymentResponse:
        record(request, body.model_dump(exclude_none=True))
        return CreatePaymentResponse(payment_url="https://payments.invalid/e2e-matrix")

    @app.post("/api/v1/web/subscribe", response_model=SubscribeResponse)
    async def subscribe(request: Request, body: SubscribeRequest | None = None) -> SubscribeResponse:
        record(request, body.model_dump(exclude_none=True) if body else {})
        return SubscribeResponse(payment_url="https://payments.invalid/e2e-tarot")

    @app.get("/api/v1/web/chat/state", response_model=ChatQuotaState)
    async def chat_state(request: Request) -> ChatQuotaState:
        _profile(persona(request))
        return _quota(persona(request))

    @app.post("/api/v1/web/chat", response_model=ChatResponse)
    async def chat(request: Request, body: ChatRequest) -> ChatResponse | JSONResponse:
        selected = persona(request)
        _profile(selected)
        record(request, body.model_dump())
        quota = _quota(selected)
        if not quota.can_send:
            return JSONResponse(status_code=402, content=quota.model_dump(mode="json"))
        return ChatResponse(reply="Deterministic E2E reply.", quota=quota)

    @app.get("/api/v1/web/notifications", response_model=NotificationPrefsResponse)
    async def notifications(request: Request) -> NotificationPrefsResponse:
        selected = persona(request)
        _profile(selected)
        prefs = app.state.e2e.notifications.setdefault(selected, {"daily_card": True, "weekly_spread": False, "practices": False, "news": False})
        return NotificationPrefsResponse(prefs=prefs)

    @app.patch("/api/v1/web/notifications", response_model=NotificationPrefsResponse)
    async def update_notifications(request: Request, body: NotificationPrefRequest) -> NotificationPrefsResponse:
        selected = persona(request)
        _profile(selected)
        prefs = app.state.e2e.notifications.setdefault(selected, {"daily_card": True, "weekly_spread": False, "practices": False, "news": False})
        if body.key not in prefs:
            raise HTTPException(status_code=422, detail="invalid_notification")
        prefs[body.key] = body.enabled
        record(request, body.model_dump())
        return NotificationPrefsResponse(prefs=prefs)

    @app.post("/api/v1/web/generate-link-token", response_model=GenerateLinkTokenResponse)
    async def link(request: Request) -> GenerateLinkTokenResponse:
        _profile(persona(request))
        record(request)
        return GenerateLinkTokenResponse(token="e2e-link-token", tg_url="https://t.me/nura_e2e_bot?start=link_e2e")

    @app.get("/api/v1/web/telegram-link-status")
    async def telegram_link_status(request: Request) -> dict[str, Any]:
        _profile(persona(request))
        return _telegram_status(persona(request))

    @app.post("/api/v1/web/confirm-telegram-link")
    async def confirm_telegram_link(request: Request, body: dict[str, Any]) -> Any:
        _profile(persona(request))
        record(request, body)
        selected = persona(request)
        if selected == "telegram_confirm_invalid":
            return JSONResponse(status_code=400, content={"detail": "invalid_confirmation_code"})
        if selected == "telegram_confirm_missing":
            return JSONResponse(status_code=404, content={"detail": "pending_confirmation_not_found"})
        if selected == "telegram_confirm_conflict":
            return JSONResponse(status_code=409, content={"detail": "telegram_account_conflict"})
        if selected == "telegram_confirm_failure":
            return JSONResponse(status_code=500, content={"detail": "internal_error"})
        return {"ok": True}

    @app.delete("/api/v1/web/cancel-telegram-link")
    async def cancel_telegram_link(request: Request) -> Any:
        _profile(persona(request))
        record(request)
        if persona(request) == "telegram_cancel_failure":
            return JSONResponse(status_code=500, content={"detail": "internal_error"})
        return {"ok": True}

    @app.delete("/api/v1/web/unlink-telegram")
    async def unlink(request: Request) -> dict[str, bool]:
        _profile(persona(request))
        record(request)
        return {"ok": True}

    @app.get("/api/v1/tarot/daily-card", response_model=DailyCardResponse)
    async def daily(request: Request) -> DailyCardResponse:
        _profile(persona(request))
        return _daily()

    @app.post("/api/v1/tarot/spread", response_model=SpreadResponse)
    async def spread(request: Request, body: SpreadRequest) -> SpreadResponse:
        _profile(persona(request))
        record(request, body.model_dump(exclude_none=True))
        return SpreadResponse(spread_type=body.spread_type, spread_name="E2E spread", cards=[{"position_name": "Now", "arcana_number": 1, "arcana_name": "The Magician", "interpretation": "Deterministic interpretation.", "advice": "Proceed."}], summary="Deterministic summary.", affirmation="I can begin.")

    @app.get("/{asset_path:path}")
    async def root_asset(asset_path: str) -> FileResponse:
        candidate = (ROOT / asset_path).resolve()
        if not str(candidate).startswith(str(ROOT)) or not candidate.is_file():
            raise HTTPException(status_code=404, detail="not_found")
        return FileResponse(candidate)

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_e2e_harness(), host="127.0.0.1", port=4174, log_level="warning")
