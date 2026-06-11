import json
import logging

from pywebpush import webpush, WebPushException

from core.config import settings

logger = logging.getLogger(__name__)


class PushSubscriptionExpired(WebPushException):
    """410 Gone — подписка перманентно невалидна, нужно сбросить."""


async def send_web_push(
    endpoint: str,
    p256dh: str,
    auth: str,
    title: str,
    body: str,
    url: str = "/app",
    tag: str = "nura-default",
) -> bool:
    if not settings.vapid_private_key:
        logger.warning("VAPID_PRIVATE_KEY not configured — skipping web push")
        return False

    try:
        webpush(
            subscription_info={
                "endpoint": endpoint,
                "keys": {"p256dh": p256dh, "auth": auth},
            },
            data=json.dumps({
                "title": title,
                "body": body,
                "url": url,
                "tag": tag,
            }),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={
                "sub": f"mailto:{settings.vapid_claims_email}",
            },
        )
        logger.info("Web push sent: tag=%s endpoint=%.40s", tag, endpoint)
        return True

    except WebPushException as exc:
        if exc.response is not None and exc.response.status_code == 410:
            logger.info("Push subscription expired (410): %.40s", endpoint)
            raise PushSubscriptionExpired(str(exc)) from exc
        logger.error("Web push failed: %s", exc)
        return False

    except Exception as exc:
        logger.exception("Unexpected web push error: %s", exc)
        return False
