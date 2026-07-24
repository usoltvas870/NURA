from pathlib import Path
import importlib.util

import pytest


ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = ROOT / "scripts" / "p7_telegram_pilot_controller.py"
WORKFLOW = ROOT / ".github" / "workflows" / "p7-telegram-pilot.yml"
COMPOSE = ROOT / "nura_app" / "docker-compose.nura-tg.yml"
spec = importlib.util.spec_from_file_location("p7_controller", CONTROLLER)
assert spec and spec.loader
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


def test_exact_controller_workflow_is_dispatch_only_and_non_repeatable() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "controller_sha:" in workflow
    assert "target_sha:" in workflow
    assert "expected_production_host:" in workflow
    assert 'test "$GITHUB_RUN_ATTEMPT" = 1' in workflow
    assert 'git show "$CONTROLLER_SHA:scripts/release_execution_bundle.py"' in workflow
    assert "NURA_TG_BOT_TOKEN" in workflow
    assert "printf '%s' \"$NURA_TG_BOT_TOKEN\" > \"$token_file\"" in workflow


def test_controller_has_no_shell_input_and_records_secret_free_phases() -> None:
    source = CONTROLLER.read_text(encoding="utf-8")
    assert 'choices=("preflight", "deploy")' in source
    assert "shell=True" not in source
    for phase in ("pilot_deploy_intent", "pilot_polling_intent", "pilot_verified", "pilot_rollback_verified"):
        assert phase in source
    assert "controller_digest_mismatch" in source
    assert "production_host_identity_mismatch" in source


def test_compose_isolated_from_plaintext_tokens_and_schedulers() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "celery-beat:" not in compose
    assert "admin-bot:" not in compose
    assert "\n  postgres:" not in compose
    assert "env_file: [${NURA_TG_ENV_FILE:?required}]" in compose
    assert "TELEGRAM_BOT_TOKEN: \"\"" in compose
    assert "TELEGRAM_BOT_TOKEN_FILE" in compose
    assert "nura_tg_redis_data" in compose


@pytest.mark.parametrize("line", [
    "TELEGRAM_BOT_TOKEN=value # note", "TELEGRAM_BOT_TOKEN = 'value#kept'",
    'export TELEGRAM_BOT_TOKEN = "value#kept"',
    "export TELEGRAM_BOT_TOKEN = 'value' # note",
    'export TELEGRAM_BOT_TOKEN = "value"#note',
])
def test_legacy_token_parser_accepts_safe_dotenv_forms(tmp_path: Path, line: str) -> None:
    path = tmp_path / ".env"
    path.write_text(line + "\r\n", encoding="utf-8")
    assert controller.legacy_token_from_env(path).startswith(b"value")


@pytest.mark.parametrize("line", [
    "TELEGRAM_BOT_TOKEN='unterminated", "TELEGRAM_BOT_TOKEN=$(id)",
    "TELEGRAM_BOT_TOKEN=one\nTELEGRAM_BOT_TOKEN=two",
])
def test_legacy_token_parser_rejects_unsafe_or_ambiguous_values(tmp_path: Path, line: str) -> None:
    path = tmp_path / ".env"
    path.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(controller.PilotError):
        controller.legacy_token_from_env(path)


def test_legacy_token_parser_rejects_text_after_quote(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("TELEGRAM_BOT_TOKEN='token' unexpected\n", encoding="utf-8")
    with pytest.raises(controller.PilotError):
        controller.legacy_token_from_env(path)


def test_polling_receipt_requires_runtime_marker_and_verified_rollback() -> None:
    source = CONTROLLER.read_text(encoding="utf-8")
    bot = (ROOT / "nura_app" / "bot" / "main.py").read_text(encoding="utf-8")
    assert "nura_tg:polling_active" in source
    assert "pilot_polling_start_unconfirmed" in source
    assert source.index('write_state(state, "pilot_polling_active"') < source.index('write_state(state, "pilot_verified"')
    assert "pilot_rollback_runtime_unverified" in source
    assert "polling_marker_key" in bot
