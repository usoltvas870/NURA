"""Production secret-file readers and owner-prelaunch plaintext containment."""

from pathlib import Path

import os
import pytest
from pydantic import ValidationError

from core.config import Settings, _read_multiline_secret_file, _read_secret_file


@pytest.fixture(autouse=True)
def isolate_secret_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "SECRET_KEY", "DATABASE_URL", "POSTGRES_PASSWORD", "REDIS_PASSWORD",
        "TELEGRAM_BOT_TOKEN", "DEEPSEEK_API_KEY", "VAPID_PRIVATE_KEY",
        "ADMIN_BOT_TOKEN", "ADMIN_TOKEN", "SMTP_PASSWORD", "VK_CLIENT_SECRET",
        "YOOKASSA_SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def secret(path: Path, value: str, mode: int = 0o600) -> str:
    path.write_text(value, encoding="utf-8")
    if os.name != "nt":
        path.chmod(mode)
    return str(path)


def owner_values(tmp_path: Path) -> dict[str, object]:
    return {
        "app_env": "production",
        "prelaunch_owner_only": True,
        "prelaunch_telegram_allowed_user_ids": "101",
        "admin_telegram_id": 101,
        "payments_enabled": False,
        "secret_key_file": secret(tmp_path / "secret_key", "s" * 48),
        "database_url_file": secret(tmp_path / "database_url", "postgresql+asyncpg://u:p@db/nura"),
        "redis_password_file": secret(tmp_path / "redis_password", "redis-pass"),
        "redis_url": "redis://redis:6379/0",
        "celery_broker_url": "redis://redis:6379/1",
        "celery_result_backend": "redis://redis:6379/2",
        "session_cookie_secure": True,
        "test_mode": False,
        "enable_internal_payment_shortcut": False,
        "yookassa_expect_test_mode": False,
        "enable_expanded_tarot": False,
        "enable_compatibility": False,
        "enable_referral_promotion": False,
    }


def test_all_new_secret_file_fields_load_without_plaintext(tmp_path: Path) -> None:
    values = owner_values(tmp_path)
    values.update(
        {
            "telegram_bot_token_file": secret(tmp_path / "telegram", "123456:token"),
            "deepseek_api_key_file": secret(tmp_path / "deepseek", "deepseek-key"),
            "vapid_private_key_file": secret(tmp_path / "vapid", "-----BEGIN KEY-----\nabc\n-----END KEY-----\n"),
            "admin_bot_token_file": secret(tmp_path / "admin_bot", "654321:token"),
            "admin_token_file": secret(tmp_path / "admin_api", "admin-api-token"),
            "smtp_password_file": secret(tmp_path / "smtp", "smtp-password"),
            "vk_client_secret_file": secret(tmp_path / "vk", "vk-secret"),
        }
    )
    current = Settings(_env_file=None, **values)

    assert current.telegram_bot_token == "123456:token"
    assert current.deepseek_api_key == "deepseek-key"
    assert current.vapid_private_key == "-----BEGIN KEY-----\nabc\n-----END KEY-----\n"
    assert current.admin_bot_token == "654321:token"
    assert current.admin_token == "admin-api-token"
    assert current.smtp_password == "smtp-password"
    assert current.vk_client_secret == "vk-secret"


def test_multiline_reader_preserves_newlines_and_rejects_links(tmp_path: Path) -> None:
    key = Path(secret(tmp_path / "key.pem", "line1\nline2\n"))
    assert _read_multiline_secret_file(str(key), "private_key") == "line1\nline2\n"
    if os.name != "nt":
        linked = tmp_path / "linked.pem"
        linked.symlink_to(key)
        with pytest.raises(ValueError, match="private_key_file_unreadable"):
            _read_multiline_secret_file(str(linked), "private_key")
        hardlink = tmp_path / "hardlink.pem"
        os.link(key, hardlink)
        with pytest.raises(ValueError, match="private_key_file_unsafe"):
            _read_multiline_secret_file(str(key), "private_key")


def test_single_line_reader_is_bounded_and_redacted(tmp_path: Path) -> None:
    marker = "must-never-appear"
    path = Path(secret(tmp_path / "secret", f"{marker}\nsecond"))
    with pytest.raises(ValueError, match="credential_file_invalid") as error:
        _read_secret_file(str(path), "credential")
    assert marker not in str(error.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("secret_key", "x" * 48),
        ("telegram_bot_token", "123456:plaintext"),
        ("deepseek_api_key", "plaintext-ai"),
        ("admin_bot_token", "654321:plaintext"),
        ("admin_token", "plaintext-admin"),
        ("smtp_password", "plaintext-smtp"),
        ("vk_client_secret", "plaintext-vk"),
        ("vapid_private_key", "plaintext-vapid"),
    ],
)
def test_owner_prelaunch_rejects_plaintext_alternatives(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    values = owner_values(tmp_path)
    values[field] = value
    with pytest.raises(ValidationError, match=f"prelaunch_plaintext_{field}_forbidden") as error:
        Settings(_env_file=None, **values)
    assert value not in str(error.value)


def test_owner_prelaunch_requires_core_file_contracts(tmp_path: Path) -> None:
    values = owner_values(tmp_path)
    values["database_url_file"] = None
    with pytest.raises(ValidationError, match="prelaunch_database_url_file_required"):
        Settings(_env_file=None, **values)
