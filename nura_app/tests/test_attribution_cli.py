from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from scripts import attribution_links


def test_cli_creates_link_without_exposing_configuration(monkeypatch, capsys):
    class Service:
        def __init__(self, _factory):
            pass

        async def create_link(self, **_values):
            return SimpleNamespace(
                code="post_001", platform="telegram", source="channel",
                campaign="launch", content_id="post-42", topic="identity",
            )

    monkeypatch.setattr(attribution_links, "AttributionService", Service)
    monkeypatch.setattr(attribution_links, "get_async_sessionmaker", lambda: object())
    monkeypatch.setattr(attribution_links.settings, "bot_username", "nura_test_bot")

    result = attribution_links.main([
        "create", "--platform", "telegram", "--source", "channel",
        "--campaign", "launch", "--content-id", "post-42", "--topic", "identity",
    ])

    output = capsys.readouterr().out
    assert result == 0
    assert "a_post_001" in output
    assert "https://t.me/nura_test_bot?start=a_post_001" in output
    assert "database" not in output.lower()
    assert "token" not in output.lower()


def test_cli_passes_custom_code_and_metadata(monkeypatch):
    captured = {}

    class Service:
        def __init__(self, _factory):
            pass

        async def create_link(self, **values):
            captured.update(values)
            return SimpleNamespace(code="mixed_01", **{
                key: values[key]
                for key in ("platform", "source", "campaign", "content_id", "topic")
            })

    monkeypatch.setattr(attribution_links, "AttributionService", Service)
    monkeypatch.setattr(attribution_links, "get_async_sessionmaker", lambda: object())
    monkeypatch.setattr(attribution_links.settings, "bot_username", None)
    monkeypatch.setattr(attribution_links.settings, "app_env", "test")

    result = attribution_links.main([
        "create", "--platform", "telegram", "--source", "channel",
        "--campaign", "launch", "--content-id", "post-42", "--topic", "identity",
        "--code", "MiXeD_01",
    ])

    assert result == 0
    assert captured["code"] == "MiXeD_01"


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (attribution_links.AttributionValidationError("invalid attribution code"), 2),
        (IntegrityError("insert", {}, Exception("duplicate")), 2),
        (RuntimeError("database unavailable"), 1),
    ],
)
def test_cli_returns_nonzero_without_secret_details(
    monkeypatch, capsys, error, expected_code
):
    class Service:
        def __init__(self, _factory):
            pass

        async def create_link(self, **_values):
            raise error

    monkeypatch.setattr(attribution_links, "AttributionService", Service)
    monkeypatch.setattr(attribution_links, "get_async_sessionmaker", lambda: object())
    monkeypatch.setattr(attribution_links.settings, "app_env", "test")

    result = attribution_links.main([
        "create", "--platform", "telegram", "--source", "channel",
        "--campaign", "launch", "--content-id", "post-42", "--topic", "identity",
    ])

    captured = capsys.readouterr()
    assert result == expected_code
    assert "postgresql://" not in captured.err
    assert "token" not in captured.err.lower()


def test_cli_refuses_implicit_production_connection(monkeypatch, capsys):
    monkeypatch.setattr(attribution_links.settings, "app_env", "production")
    monkeypatch.setattr(
        attribution_links,
        "get_async_sessionmaker",
        lambda: (_ for _ in ()).throw(AssertionError("database must not be opened")),
    )

    result = attribution_links.main([
        "create", "--platform", "telegram", "--source", "channel",
        "--campaign", "launch", "--content-id", "post-42", "--topic", "identity",
    ])

    assert result == 2
    assert "--allow-production" in capsys.readouterr().err


def test_cli_requires_all_metadata():
    with pytest.raises(SystemExit) as exc_info:
        attribution_links.main(["create", "--platform", "telegram"])
    assert exc_info.value.code == 2
