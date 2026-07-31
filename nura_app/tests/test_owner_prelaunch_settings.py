"""Owner-only production prelaunch configuration contracts."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from api import main as api_main
from core.config import Settings


def production_security_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "app_env": "production",
        "secret_key": "test-only-non-default-secret-at-least-32-chars",
        "session_cookie_secure": True,
        "test_mode": False,
        "enable_internal_payment_shortcut": False,
        "yookassa_expect_test_mode": False,
        "redis_url": "redis://:test-password@redis:6379/0",
        "celery_broker_url": "redis://:test-password@redis:6379/1",
        "celery_result_backend": "redis://:test-password@redis:6379/2",
    }
    values.update(overrides)
    return values


def owner_prelaunch_settings(**overrides: object) -> Settings:
    values = production_security_values(
        prelaunch_owner_only=True,
        prelaunch_telegram_allowed_user_ids="101",
        admin_telegram_id=101,
        payments_enabled=False,
        enable_expanded_tarot=False,
        enable_compatibility=False,
        enable_referral_promotion=False,
        yookassa_shop_id=None,
        yookassa_secret_key=None,
        yookassa_receipt_enabled=False,
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_prelaunch_is_off_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.prelaunch_owner_only is False
    assert settings.telegram_access_restricted is False
    assert settings.payments_enabled is True


def test_owner_prelaunch_allows_current_production_ai_without_yookassa() -> None:
    settings = owner_prelaunch_settings()

    assert settings.is_owner_prelaunch is True
    assert settings.prelaunch_telegram_allowed_ids == (101,)
    assert settings.telegram_restricted_allowed_ids == (101,)
    assert settings.production_readiness_errors == ()
    assert settings.payment_webhook_configuration_error is None
    assert settings.deepseek_base_url == "https://api.deepseek.com/v1"
    assert settings.deepseek_model == "deepseek-chat"


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        (
            {"prelaunch_telegram_allowed_user_ids": ""},
            "prelaunch_telegram_allowlist_required",
        ),
        (
            {"prelaunch_telegram_allowed_user_ids": "101,not-an-id"},
            "telegram_allowed_user_ids_invalid",
        ),
        (
            {"prelaunch_telegram_allowed_user_ids": "101,202"},
            "prelaunch_single_owner_required",
        ),
        (
            {"admin_telegram_id": 202},
            "prelaunch_owner_must_match_admin",
        ),
        ({"payments_enabled": True}, "prelaunch_payments_must_be_disabled"),
        (
            {"yookassa_shop_id": "inherited-shop"},
            "prelaunch_yookassa_credentials_forbidden",
        ),
        ({"test_mode": True}, "production_test_mode_forbidden"),
        (
            {"enable_internal_payment_shortcut": True},
            "production_internal_payment_shortcut_forbidden",
        ),
        (
            {"yookassa_expect_test_mode": True},
            "production_yookassa_test_mode_forbidden",
        ),
        (
            {"enable_expanded_tarot": True},
            "prelaunch_feature_flags_must_be_disabled",
        ),
    ],
)
def test_owner_prelaunch_invalid_combinations_fail_closed(
    overrides: dict[str, object],
    error_code: str,
) -> None:
    with pytest.raises(ValidationError, match=error_code):
        owner_prelaunch_settings(**overrides)


def test_public_production_still_requires_payments_and_yookassa() -> None:
    with pytest.raises(ValidationError, match="production_payments_required"):
        Settings(
            _env_file=None,
            **production_security_values(payments_enabled=False),
        )
    with pytest.raises(
        ValidationError,
        match="production_payment_webhook_credentials_required",
    ):
        Settings(
            _env_file=None,
            **production_security_values(payments_enabled=True),
        )


def test_owner_prelaunch_readiness_marks_payments_disabled_but_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = owner_prelaunch_settings()
    monkeypatch.setattr(api_main, "settings", runtime)

    assert api_main.payment_webhook_readiness_status() == "disabled"


def test_prelaunch_example_is_non_secret_and_yookassa_free() -> None:
    root = Path(__file__).parents[2]
    source = (root / "nura_app" / ".env.prelaunch.example").read_text(
        encoding="utf-8"
    )

    assert "APP_ENV=production" in source
    assert "PRELAUNCH_OWNER_ONLY=true" in source
    assert "PRELAUNCH_TELEGRAM_ALLOWED_USER_IDS=" in source
    assert "ADMIN_TELEGRAM_ID=" in source
    assert "PAYMENTS_ENABLED=false" in source
    assert "TEST_MODE=false" in source
    assert "ENABLE_INTERNAL_PAYMENT_SHORTCUT=false" in source
    assert "YOOKASSA_SHOP_ID" not in source
    assert "YOOKASSA_SECRET_KEY" not in source
    assert "TELEGRAM_BOT_TOKEN=" not in source
    assert "DEEPSEEK_API_KEY=" not in source


def test_current_vps_runbook_is_plan_without_shell_placeholders() -> None:
    source = (
        Path(__file__).parents[2] / "docs" / "current-vps-prelaunch.md"
    ).read_text(encoding="utf-8")

    assert "RUNBOOK — NOT EXECUTION PROOF" in source
    assert "не обещает" in source
    assert "Alembic/database rollback" in source
    assert "```" not in source
    assert "<SHA>" not in source
