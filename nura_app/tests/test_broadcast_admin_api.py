import json

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.main import app
from core.config import settings
from core.tasks import _send_broadcast_async


CAMPAIGN = {
    "campaign_type": "editorial",
    "text": "<b>Редакционное сообщение</b>",
    "ctas": [
        {"key": "primary", "label": "Профиль", "destination": "profile"}
    ],
    "segment_type": "all_editorial_enabled",
}


@pytest.mark.asyncio
async def test_admin_campaign_create_get_update_and_legacy_endpoint_is_gone(
    db_engine, monkeypatch
):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("api.routes.admin_api.get_async_sessionmaker", lambda: factory)
    monkeypatch.setattr(settings, "admin_token", "test-admin-token")
    transport = httpx.ASGITransport(app=app)
    headers = {
        "X-Admin-Token": "test-admin-token",
        "X-Admin-Actor": "operator.test",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.post(
            "/api/v1/admin/campaigns",
            json=CAMPAIGN,
            headers={"X-Admin-Token": "test-admin-token", "X-Admin-Actor": "bad actor"},
        )
        assert denied.status_code == 422
        created = await client.post(
            "/api/v1/admin/campaigns", json=CAMPAIGN, headers=headers
        )
        assert created.status_code == 201, created.text
        campaign_id = created.json()["campaign_id"]
        fetched = await client.get(
            f"/api/v1/admin/campaigns/{campaign_id}",
            headers={"X-Admin-Token": "test-admin-token"},
        )
        assert fetched.status_code == 200 and fetched.json()["content_version"] == 1
        updated = await client.patch(
            f"/api/v1/admin/campaigns/{campaign_id}",
            json={"text": "Версия 2", "reason": "editorial revision"},
            headers=headers,
        )
        assert updated.status_code == 200 and updated.json()["content_version"] == 2
        legacy = await client.post(
            "/api/v1/admin/broadcast",
            json={"text": "unsafe", "channels": ["telegram"], "filter": "all"},
            headers={"X-Admin-Token": "test-admin-token"},
        )
        assert legacy.status_code == 410


@pytest.mark.asyncio
async def test_direct_legacy_task_is_fail_closed(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.values = {}

        async def set(self, key, value):
            self.values[key] = value

    redis = FakeRedis()
    monkeypatch.setattr("core.tasks.get_redis", lambda: redis)
    result = await _send_broadcast_async(
        "legacy-task",
        "unsafe",
        ["telegram", "push"],
        "all",
        "title",
        "/app",
    )
    assert result["status"] == "deprecated" and result["sent"] == 0
    assert json.loads(redis.values["broadcast:legacy-task"])["error_code"] == "direct_broadcast_disabled"


def test_default_beat_excludes_legacy_editorial_and_nura_1_5_bypasses() -> None:
    from core.tasks import celery_app

    schedule = celery_app.conf.beat_schedule
    forbidden = {
        "send-weekly-tarot-spread",
        "send-monthly-tarot-portal",
        "check-inactive-users",
        "check-expiring-subscriptions",
        "charge-recurring-subscriptions",
    }
    assert forbidden.isdisjoint(schedule)
    assert schedule["reconcile-broadcast-campaigns"]["task"] == "core.tasks.reconcile_broadcast_campaigns"
