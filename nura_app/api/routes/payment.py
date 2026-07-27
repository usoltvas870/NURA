import ipaddress
import json
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from api.deps import limiter
from core.config import settings
from core.database import get_async_sessionmaker
from core.services.payment import PaymentService
from core.services.full_matrix_checkout import FullMatrixCheckoutService

router = APIRouter(prefix="/api/v1/payment")

_networks_cache: tuple[str, list] = ("", [])


def _whitelist_networks() -> list:
    global _networks_cache
    raw = settings.yookassa_ip_whitelist
    if _networks_cache[0] == raw:
        return _networks_cache[1]
    nets: list = []
    for part in settings.yookassa_ip_whitelist_list:
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue
    _networks_cache = (raw, nets)
    return nets


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else ""


@router.post("/webhook")
@limiter.limit("10/minute")
async def payment_webhook(request: Request):
    if settings.yookassa_ip_whitelist:
        ip = _client_ip(request)
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            addr = None
        allowed = False
        if addr is not None:
            for net in _whitelist_networks():
                if addr in net:
                    allowed = True
                    break
        if not allowed:
            raise HTTPException(status_code=403, detail="Forbidden")

    try:
        data = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=400, detail="invalid_webhook_payload"
        ) from None
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="invalid_webhook_payload")
    try:
        raw_object = data.get("object")
        raw_metadata = raw_object.get("metadata") if isinstance(raw_object, dict) else None
        if isinstance(raw_metadata, dict) and raw_metadata.get("product_code") == "full_matrix":
            result = await FullMatrixCheckoutService(get_async_sessionmaker()).process_webhook(data)
            if result.get("result") == "retryable_failure":
                raise HTTPException(
                    status_code=503,
                    detail="payment_verification_unavailable",
                )
            if result.get("result") == "activated":
                from core.tasks import notify_full_matrix_payment_confirmed
                notify_full_matrix_payment_confirmed.delay(result["order_id"])
            return result
        result = await PaymentService.process_webhook(
            get_async_sessionmaker(), data
        )
        if result.get("reason") == "verification_unavailable":
            raise HTTPException(
                status_code=503,
                detail="payment_verification_unavailable",
            )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/full-matrix/checkout/{public_id}", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def full_matrix_checkout_page(request: Request, public_id: str) -> HTMLResponse:
    # The opaque id is an authorization capability; never expose user or payment data.
    if len(public_id) < 40 or len(public_id) > 64:
        raise HTTPException(status_code=404, detail="checkout_not_found")
    body = (
        "<!doctype html><html lang='ru'><meta charset='utf-8'><meta name='robots' content='noindex'>"
        "<title>Оплата NURA</title><body><main><h1>Полная Матрица судьбы</h1>"
        "<p>890 ₽ · разовая оплата через ЮKassa</p>"
        f"<form method='post' action='/api/v1/payment/full-matrix/checkout/{public_id}'>"
        "<label>Email для чека <input type='email' name='email' required autocomplete='email'></label>"
        "<p>На этот адрес придёт электронный чек</p>"
        "<button type='submit'>Перейти к оплате</button></form></main></body></html>"
    )
    return HTMLResponse(body, headers={"Cache-Control": "no-store"})


@router.post("/full-matrix/checkout/{public_id}")
@limiter.limit("10/minute")
async def start_full_matrix_checkout(request: Request, public_id: str) -> RedirectResponse:
    try:
        if len(public_id) < 40 or len(public_id) > 64:
            raise ValueError("checkout_not_available")
        body = await request.body()
        if len(body) > 4096:
            raise ValueError("checkout_email_invalid")
        values = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        emails = values.get("email", [])
        if len(emails) != 1:
            raise ValueError("checkout_email_invalid")
        url = await FullMatrixCheckoutService(get_async_sessionmaker()).start_checkout(public_id, emails[0])
    except ValueError:
        raise HTTPException(status_code=404, detail="checkout_not_available") from None
    return RedirectResponse(url, status_code=303, headers={"Cache-Control": "no-store"})


@router.get("/full-matrix/return/{public_id}", response_class=HTMLResponse)
async def full_matrix_return(public_id: str) -> HTMLResponse:
    # A browser return is deliberately informational: only a verified webhook activates.
    return HTMLResponse(
        "<!doctype html><html lang='ru'><meta charset='utf-8'><title>NURA</title>"
        "<p>Проверяем оплату. После подтверждения начнём готовить полный разбор.</p>",
        headers={"Cache-Control": "no-store"},
    )
