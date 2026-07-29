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
    assert "NURA_TG_BOT_TOKEN" not in workflow
    assert "telegram_bot_token" not in workflow


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
    assert "env_file:" not in compose
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


def test_pilot_verified_requires_authenticated_redis_probe_and_unauth_rejection() -> None:
    source = CONTROLLER.read_text(encoding="utf-8")
    assert '"python", "-m", "core.redis_auth_probe"' in source
    assert "pilot_redis_unauthenticated_access" in source
    assert source.index('"core.redis_auth_probe"') < source.index('write_state(state, "pilot_verified"')
    assert "cwd=app, environment=environment" in source


def test_authoritative_secret_paths_are_checked_before_symlink_resolution() -> None:
    source = CONTROLLER.read_text(encoding="utf-8")
    assert "PILOT_TOKEN_FILE.resolve" not in source
    assert "PILOT_DATABASE_URL_FILE.resolve" not in source
    assert "read_authoritative_secret(token)" in source
    assert "O_NOFOLLOW" in source
    assert "info.st_nlink != 1" in source


def _authoritative_secret_tree(tmp_path: Path) -> tuple[Path, Path]:
    directory = tmp_path / "opt" / "nura" / "secrets" / "nura_tg"
    directory.mkdir(parents=True, mode=0o700)
    for parent in (tmp_path / "opt", tmp_path / "opt" / "nura", tmp_path / "opt" / "nura" / "secrets", directory):
        parent.chmod(0o700)
    secret = directory / "telegram_bot_token"
    secret.write_bytes(b"test-token")
    secret.chmod(0o600)
    return tmp_path, secret


@pytest.mark.skipif(__import__("os").name == "nt", reason="openat semantics are POSIX-only")
def test_authoritative_secret_reader_rejects_symlink_each_parent_component(tmp_path: Path) -> None:
    import os
    import shutil

    for component in ("opt", "nura", "secrets", "nura_tg"):
        root, secret = _authoritative_secret_tree(tmp_path / component)
        link = root / "opt"
        for name in ("nura", "secrets", "nura_tg"):
            if name == component:
                break
            link = link / name
        shutil.rmtree(link)
        link.symlink_to(root)
        with pytest.raises(controller.PilotError, match="unsafe_secret_path"):
            controller.read_authoritative_secret(
                Path("/opt/nura/secrets/nura_tg/telegram_bot_token"),
                root=root,
                owner_ids=frozenset({os.getuid()}),
            )


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX mode bits are unavailable")
@pytest.mark.parametrize("case", ["unsafe_permissions", "wrong_owner", "non_directory", "hard_link"])
def test_authoritative_secret_reader_rejects_unsafe_chain(tmp_path: Path, case: str) -> None:
    import os

    root, secret = _authoritative_secret_tree(tmp_path)
    if case == "unsafe_permissions":
        secret.parent.chmod(0o722)
    elif case == "wrong_owner":
        owner_ids = frozenset({os.getuid() + 1})
        with pytest.raises(controller.PilotError, match="unsafe_secret_path"):
            controller.read_authoritative_secret(Path("/opt/nura/secrets/nura_tg/telegram_bot_token"), root=root, owner_ids=owner_ids)
        return
    elif case == "non_directory":
        secret.unlink()
        secret.parent.rmdir()
        secret.parent.write_text("not-a-directory", encoding="utf-8")
    else:
        os.link(secret, secret.with_name("another_link"))
    with pytest.raises(controller.PilotError, match="unsafe_secret_path"):
        controller.read_authoritative_secret(Path("/opt/nura/secrets/nura_tg/telegram_bot_token"), root=root, owner_ids=frozenset({os.getuid()}))


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX mode bits are unavailable")
def test_authoritative_secret_reader_reads_valid_regular_file(tmp_path: Path) -> None:
    import os

    root, _ = _authoritative_secret_tree(tmp_path)
    assert controller.read_authoritative_secret(
        Path("/opt/nura/secrets/nura_tg/telegram_bot_token"), root=root, owner_ids=frozenset({os.getuid()})
    ) == b"test-token"
