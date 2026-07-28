from core.config import Settings


def test_sandbox_opt_out_ignores_ambient_dotenv(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("POSTGRES_HOST=dotenv-only-host\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NURA_DISABLE_DOTENV", "1")

    settings = Settings()

    assert settings.postgres_host != "dotenv-only-host"
