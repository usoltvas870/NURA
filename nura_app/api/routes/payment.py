import ipaddress

from fastapi import APIRouter, HTTPException, Request

from api.deps import limiter
from core.config import settings
from core.database import get_async_sessionmaker
from core.services.payment import PaymentService

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

    data = await request.json()
    try:
        return await PaymentService.process_webhook(
            get_async_sessionmaker(), data
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))