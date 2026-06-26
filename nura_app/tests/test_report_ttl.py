import uuid
from datetime import datetime, timedelta, timezone

import pytest

from api.routes import reports as reports_module


@pytest.fixture
def fake_report_factory():
    def _make(expires_at=None):
        class _Report:
            def __init__(self):
                self.id = uuid.uuid4()
                self.user_id = uuid.uuid4()
                self.report_type = "mini"
                self.token = "tok-123"
                self.matrix_data = {"birth_date": "01.01.2000", "center": 8}
                self.ai_analysis = {}
                self.kitchen_analysis = None
                self.expires_at = expires_at

        return _Report()

    return _make


def _call(handler, request, token):
    return handler.__wrapped__(request, token) if hasattr(handler, "__wrapped__") else handler(request, token)


@pytest.mark.asyncio
async def test_is_expired_null_never_expires(fake_report_factory):
    report = fake_report_factory(expires_at=None)
    assert reports_module._is_expired(report) is False


@pytest.mark.asyncio
async def test_is_expired_future_not_expired(fake_report_factory):
    report = fake_report_factory(expires_at=datetime.now(timezone.utc) + timedelta(days=10))
    assert reports_module._is_expired(report) is False


@pytest.mark.asyncio
async def test_is_expired_past_expired(fake_report_factory):
    report = fake_report_factory(expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    assert reports_module._is_expired(report) is True


@pytest.mark.asyncio
async def test_serve_report_expired_returns_410(monkeypatch, fake_report_factory):
    expired_report = fake_report_factory(
        expires_at=datetime.now(timezone.utc) - timedelta(days=1)
    )

    async def _fake_get(_sf, _token):
        return expired_report

    monkeypatch.setattr(reports_module.ReportService, "get_report_by_token", _fake_get)

    class _Req:
        pass

    resp = await _call(reports_module.serve_report, _Req(), "tok-123")
    assert resp.status_code == 410
    assert "истёк" in resp.body.decode("utf-8").lower() or "истёк" in resp.body.decode("utf-8")


@pytest.mark.asyncio
async def test_serve_report_null_expiry_serves(monkeypatch, fake_report_factory):
    report = fake_report_factory(expires_at=None)

    async def _fake_get(_sf, _token):
        return report

    monkeypatch.setattr(reports_module.ReportService, "get_report_by_token", _fake_get)
    monkeypatch.setattr(reports_module.os.path, "exists", lambda _p: False)

    async def _fake_render(_report, _sf):
        return "<html>ok</html>"

    monkeypatch.setattr(reports_module, "_render_report_by_type", _fake_render)

    class _Req:
        pass

    resp = await _call(reports_module.serve_report, _Req(), "tok-123")
    assert resp.status_code == 200
    assert "ok" in resp.body.decode("utf-8")


@pytest.mark.asyncio
async def test_repo_create_sets_default_expires_at(test_user, db_engine):
    from core.repositories.report import ReportRepository
    from core.models import ReportType
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    repo = ReportRepository(factory)
    report = await repo.create(
        user_id=test_user.id,
        report_type=ReportType.MINI,
        token="ttl-default-001",
        matrix_data={"center": 8},
    )
    assert report.expires_at is not None
    stored = report.expires_at
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=timezone.utc)
    assert stored > datetime.now(timezone.utc)
    assert ReportRepository.is_expired(report) is False


@pytest.mark.asyncio
async def test_repo_is_expired_true_for_past(test_user, db_engine):
    from core.repositories.report import ReportRepository
    from core.models import ReportType
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    repo = ReportRepository(factory)
    past = datetime.now(timezone.utc) - timedelta(days=5)
    report = await repo.create(
        user_id=test_user.id,
        report_type=ReportType.MINI,
        token="ttl-past-001",
        matrix_data={"center": 8},
        expires_at=past,
    )
    assert ReportRepository.is_expired(report) is True
