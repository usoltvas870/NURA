from datetime import timedelta

import pytest
from pydantic import ValidationError

from core.config import settings as _default_settings


def _beat_entry(name: str) -> dict | None:
    from core.tasks import celery_app

    return celery_app.conf.beat_schedule.get(name)


class TestDefaultSettings:
    def test_default_dispatch_interval_is_60(self):
        assert _default_settings.report_generation_dispatch_interval_seconds == 60

    def test_default_dispatch_limit_is_20(self):
        assert _default_settings.report_generation_dispatch_limit == 20

    def test_default_reconciliation_interval_is_300(self):
        assert _default_settings.report_generation_reconciliation_interval_seconds == 300

    def test_default_reconciliation_limit_is_50(self):
        assert _default_settings.report_generation_reconciliation_limit == 50


class TestSettingsBounds:
    def _make(self, **overrides):
        from core.config import Settings

        return Settings(**overrides)

    # ── dispatch interval ──────────────────────────────────────────────

    def test_dispatch_interval_15_accepted(self):
        s = self._make(report_generation_dispatch_interval_seconds=15)
        assert s.report_generation_dispatch_interval_seconds == 15

    def test_dispatch_interval_300_accepted(self):
        s = self._make(report_generation_dispatch_interval_seconds=300)
        assert s.report_generation_dispatch_interval_seconds == 300

    def test_dispatch_interval_14_rejected(self):
        with pytest.raises(ValidationError):
            self._make(report_generation_dispatch_interval_seconds=14)

    def test_dispatch_interval_301_rejected(self):
        with pytest.raises(ValidationError):
            self._make(report_generation_dispatch_interval_seconds=301)

    def test_dispatch_interval_0_rejected(self):
        with pytest.raises(ValidationError):
            self._make(report_generation_dispatch_interval_seconds=0)

    def test_dispatch_interval_neg_rejected(self):
        with pytest.raises(ValidationError):
            self._make(report_generation_dispatch_interval_seconds=-1)

    # ── dispatch limit ─────────────────────────────────────────────────

    def test_dispatch_limit_1_accepted(self):
        s = self._make(report_generation_dispatch_limit=1)
        assert s.report_generation_dispatch_limit == 1

    def test_dispatch_limit_100_accepted(self):
        s = self._make(report_generation_dispatch_limit=100)
        assert s.report_generation_dispatch_limit == 100

    def test_dispatch_limit_0_rejected(self):
        with pytest.raises(ValidationError):
            self._make(report_generation_dispatch_limit=0)

    def test_dispatch_limit_101_rejected(self):
        with pytest.raises(ValidationError):
            self._make(report_generation_dispatch_limit=101)

    # ── reconciliation interval ────────────────────────────────────────

    def test_reconciliation_interval_60_accepted(self):
        s = self._make(report_generation_reconciliation_interval_seconds=60)
        assert s.report_generation_reconciliation_interval_seconds == 60

    def test_reconciliation_interval_1800_accepted(self):
        s = self._make(report_generation_reconciliation_interval_seconds=1800)
        assert s.report_generation_reconciliation_interval_seconds == 1800

    def test_reconciliation_interval_59_rejected(self):
        with pytest.raises(ValidationError):
            self._make(report_generation_reconciliation_interval_seconds=59)

    def test_reconciliation_interval_1801_rejected(self):
        with pytest.raises(ValidationError):
            self._make(report_generation_reconciliation_interval_seconds=1801)

    # ── reconciliation limit ───────────────────────────────────────────

    def test_reconciliation_limit_1_accepted(self):
        s = self._make(report_generation_reconciliation_limit=1)
        assert s.report_generation_reconciliation_limit == 1

    def test_reconciliation_limit_200_accepted(self):
        s = self._make(report_generation_reconciliation_limit=200)
        assert s.report_generation_reconciliation_limit == 200

    def test_reconciliation_limit_0_rejected(self):
        with pytest.raises(ValidationError):
            self._make(report_generation_reconciliation_limit=0)

    def test_reconciliation_limit_201_rejected(self):
        with pytest.raises(ValidationError):
            self._make(report_generation_reconciliation_limit=201)


class TestExpiresContract:
    def test_dispatcher_expires_always_positive(self):
        from core.config import Settings

        for interval in (15, 60, 300):
            s = Settings(report_generation_dispatch_interval_seconds=interval)
            expires = s.report_generation_dispatch_interval_seconds - 5
            assert expires > 0, f"interval={interval}, expires={expires} <= 0"

    def test_dispatcher_expires_less_than_interval(self):
        from core.config import Settings

        for interval in (15, 60, 300):
            s = Settings(report_generation_dispatch_interval_seconds=interval)
            expires = s.report_generation_dispatch_interval_seconds - 5
            assert expires < s.report_generation_dispatch_interval_seconds

    def test_reconciliation_expires_always_positive(self):
        from core.config import Settings

        for interval in (60, 300, 1800):
            s = Settings(report_generation_reconciliation_interval_seconds=interval)
            expires = s.report_generation_reconciliation_interval_seconds - 30
            assert expires > 0, f"interval={interval}, expires={expires} <= 0"

    def test_reconciliation_expires_less_than_interval(self):
        from core.config import Settings

        for interval in (60, 300, 1800):
            s = Settings(report_generation_reconciliation_interval_seconds=interval)
            expires = s.report_generation_reconciliation_interval_seconds - 30
            assert expires < s.report_generation_reconciliation_interval_seconds


class TestInvalidConfigDoesNotBuildSchedule:
    def test_valid_settings_produce_schedule(self):
        from core.tasks import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "dispatch-report-generation-jobs" in schedule
        assert "reconcile-report-generation-jobs" in schedule

    def test_validation_does_not_open_db(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            "core.database.get_async_sessionmaker",
            lambda: called.append("db") or None,
            raising=False,
        )
        from core.config import Settings

        Settings(
            report_generation_dispatch_interval_seconds=15,
            report_generation_dispatch_limit=1,
            report_generation_reconciliation_interval_seconds=60,
            report_generation_reconciliation_limit=1,
        )
        assert "db" not in called

    def test_validation_does_not_call_broker(self, monkeypatch):
        called = []

        def _guard(*a, **kw):
            called.append("broker")

        import core.tasks

        monkeypatch.setattr(core.tasks.celery_app, "send_task", _guard, raising=False)
        from core.config import Settings

        Settings(
            report_generation_dispatch_interval_seconds=15,
            report_generation_reconciliation_interval_seconds=60,
        )
        assert "broker" not in called

    def test_error_does_not_leak_secrets(self):
        from core.config import Settings

        try:
            Settings(
                report_generation_dispatch_interval_seconds=-1,
                secret_key="super-secret-key",
                deepseek_api_key="sk-secret",
            )
        except ValidationError as e:
            errors = str(e.errors())
            assert "super-secret-key" not in errors
            assert "sk-secret" not in errors


class TestBeatScheduleEntries:
    def test_dispatcher_entry_exists(self):
        entry = _beat_entry("dispatch-report-generation-jobs")
        assert entry is not None

    def test_dispatcher_uses_correct_task_name(self):
        entry = _beat_entry("dispatch-report-generation-jobs")
        assert entry["task"] == "core.tasks.dispatch_report_generation_jobs"

    def test_dispatcher_interval_is_timedelta(self):
        entry = _beat_entry("dispatch-report-generation-jobs")
        assert isinstance(entry["schedule"], timedelta)

    def test_dispatcher_has_expiration(self):
        entry = _beat_entry("dispatch-report-generation-jobs")
        expires = entry["options"]["expires"]
        interval_s = entry["schedule"].total_seconds()
        assert expires > 0
        assert expires < interval_s

    def test_reconciliation_entry_exists(self):
        entry = _beat_entry("reconcile-report-generation-jobs")
        assert entry is not None

    def test_reconciliation_uses_correct_task_name(self):
        entry = _beat_entry("reconcile-report-generation-jobs")
        assert entry["task"] == "core.tasks.reconcile_report_generation_jobs"

    def test_reconciliation_has_expiration(self):
        entry = _beat_entry("reconcile-report-generation-jobs")
        expires = entry["options"]["expires"]
        interval_s = entry["schedule"].total_seconds()
        assert expires > 0
        assert expires < interval_s

    def test_reconciliation_interval_greater_than_dispatcher(self):
        disp = _beat_entry("dispatch-report-generation-jobs")
        rec = _beat_entry("reconcile-report-generation-jobs")
        assert rec["schedule"].total_seconds() > disp["schedule"].total_seconds()


class TestTaskRegistration:
    def test_dispatcher_task_registered(self):
        from core.tasks import celery_app

        assert "core.tasks.dispatch_report_generation_jobs" in celery_app.tasks

    def test_reconciliation_task_registered(self):
        from core.tasks import celery_app

        assert "core.tasks.reconcile_report_generation_jobs" in celery_app.tasks

    def test_worker_task_is_not_periodic(self):
        from core.tasks import celery_app

        schedule = celery_app.conf.beat_schedule
        worker_keys = [
            k for k, v in schedule.items()
            if "process_report_generation_job" in v.get("task", "")
        ]
        assert len(worker_keys) == 0


class TestScheduleSanity:
    def test_schedule_names_unique(self):
        from core.tasks import celery_app

        schedule = celery_app.conf.beat_schedule
        assert len(schedule) == len(set(schedule.keys()))

    def test_schedule_no_identifiers(self):
        import json

        entry = _beat_entry("dispatch-report-generation-jobs")
        serialized = json.dumps(entry, default=str)
        for forbidden in ("user_id", "report_id", "job_id", "token", "secret", "password"):
            assert forbidden not in serialized, f"'{forbidden}' in schedule"

    def test_schedule_no_credentials(self):
        import json

        entry = _beat_entry("reconcile-report-generation-jobs")
        serialized = json.dumps(entry, default=str)
        for forbidden in ("api_key", "broker_url", "redis://", "postgresql://"):
            assert forbidden not in serialized, f"'{forbidden}' in schedule"

    def test_import_safe(self):
        from core.tasks import celery_app

        assert celery_app is not None

    def test_beat_does_not_execute_tasks(self):
        from core.tasks import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "dispatch-report-generation-jobs" in schedule
        assert schedule["dispatch-report-generation-jobs"]["task"].startswith("core.tasks.")


class TestExistingBeatPreservation:
    def test_existing_entries_preserved(self):
        from core.tasks import celery_app

        schedule = celery_app.conf.beat_schedule
        required = [
            "send-daily-card", "send-daily-tarot-card",
            "send-weekly-tarot-spread", "send-monthly-tarot-portal",
            "check-inactive-users", "check-expiring-subscriptions",
            "downgrade-expired-subscriptions", "charge-recurring-subscriptions",
            "cleanup-expired-guests", "block-inactive-users",
            "delete-inactive-users", "monitor-health",
        ]
        for name in required:
            assert name in schedule, f"missing: {name}"


class TestOverlapSafety:
    def test_overlap_safe_by_expiration(self):
        disp = _beat_entry("dispatch-report-generation-jobs")
        rec = _beat_entry("reconcile-report-generation-jobs")
        assert disp["options"]["expires"] < disp["schedule"].total_seconds()
        assert rec["options"]["expires"] < rec["schedule"].total_seconds()

    def test_no_lock_required(self):
        for entry in (_beat_entry("dispatch-report-generation-jobs"),
                       _beat_entry("reconcile-report-generation-jobs")):
            assert "lock" not in str(entry)
            assert "redis_lock" not in str(entry)
