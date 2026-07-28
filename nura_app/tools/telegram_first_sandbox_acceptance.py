#!/usr/bin/env python3
"""Run the local Telegram-first acceptance proof without external APIs.

The runner owns only the containers labelled ``nura.test=telegram-first-acceptance``.
It never reads .env values and always executes application tests with APP_ENV=test.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

try:  # Supports both ``python tools/...`` and ``import tools...``.
    from telegram_first_security_context import (
        SecurityContext,
        sanitize_text,
        scan_artifacts,
    )
except ModuleNotFoundError:
    from tools.telegram_first_security_context import (
        SecurityContext,
        sanitize_text,
        scan_artifacts,
    )


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
TEST_FILES = (
    "tests/test_attribution.py",
    "tests/test_attribution_migration_contract.py",
    "tests/test_mini_report_application.py",
    "tests/test_mini_report_telegram_delivery.py",
    "tests/test_mini_report_generation_migration_contract.py",
    "tests/test_daily_tarot_application.py",
    "tests/test_daily_tarot_migration_contract.py",
    "tests/test_lifetime_chat_contract.py",
    "tests/test_full_matrix_checkout.py",
    "tests/test_payment_webhook_verification.py",
    "tests/test_full_report_telegram_delivery.py",
    "tests/test_full_matrix_account_deletion.py",
    "tests/test_report_generation_celery_wiring.py",
    "tests/test_security_configuration_contract.py",
    "tests/test_security_rendering_gate.py",
    "tests/test_sandbox_settings_isolation.py",
    "tests/test_celery_async_postgres.py",
)
RUNTIME_PROBE = """
import asyncio
from redis.asyncio import Redis
from sqlalchemy import text
from core.database import dispose_async_database_state, get_async_sessionmaker
from core.config import settings
from tools.telegram_first_security_context import emit_event

async def main():
    factory = get_async_sessionmaker()
    try:
        async with factory() as session:
            version = (await session.execute(text('SHOW server_version'))).scalar_one()
        assert str(version).startswith('16.')
        emit_event(
            'postgres_connection',
            destination_category='postgres',
            host_category='loopback',
            allowed=True,
        )
        redis = Redis.from_url(settings.redis_url)
        try:
            assert await redis.ping() is True
            emit_event(
                'redis_connection',
                destination_category='redis',
                host_category='loopback',
                allowed=True,
            )
        finally:
            await redis.aclose()
    finally:
        await dispose_async_database_state()

asyncio.run(main())
"""
GOLDEN_PATH_TEST = "tests/test_telegram_first_postgres_golden_path.py"
FAILURE_RETRY_TEST = "tests/test_telegram_first_postgres_failure_retry.py"
SECURITY_ACCEPTANCE_TEST = "tests/test_telegram_first_security_acceptance.py"
SECURITY_TEST_CATEGORIES = (
    ("rendering-escaping", (
        "tests/test_security_rendering_gate.py",
    )),
    ("config-isolation", (
        "tests/test_security_configuration_contract.py",
        "tests/test_sandbox_settings_isolation.py",
    )),
    ("authorization-idor", (
        f"{SECURITY_ACCEPTANCE_TEST}::test_security_database_is_postgresql_and_idor_is_enforced",
        f"{SECURITY_ACCEPTANCE_TEST}::test_forged_report_callbacks_fail_closed",
    )),
    ("checkout-webhook-payment", (
        f"{SECURITY_ACCEPTANCE_TEST}::test_invalid_checkout_never_calls_provider",
        f"{SECURITY_ACCEPTANCE_TEST}::test_real_uvicorn_access_log_redacts_checkout_capability",
        f"{SECURITY_ACCEPTANCE_TEST}::test_full_matrix_webhook_rejections_never_activate",
        "tests/test_full_matrix_checkout.py",
        "tests/test_payment_webhook_verification.py",
    )),
    ("refund-account-deletion", (
        "tests/test_full_report_telegram_delivery.py::test_refund_and_missing_telegram_identity_block_send",
        "tests/test_full_report_telegram_delivery.py::test_refund_after_claim_is_rechecked_before_first_telegram_call",
        "tests/test_full_report_telegram_delivery.py::test_refund_during_invalid_file_id_flow_blocks_artifact_fallback",
        "tests/test_full_matrix_account_deletion.py",
    )),
    ("logging-uvicorn-sentry", (
        f"{SECURITY_ACCEPTANCE_TEST}::test_uvicorn_access_log_redacts_checkout_capability",
        f"{SECURITY_ACCEPTANCE_TEST}::test_unknown_report_type_log_redacts_report_capability",
        f"{SECURITY_ACCEPTANCE_TEST}::test_global_bot_error_log_does_not_expose_exception_payload",
        f"{SECURITY_ACCEPTANCE_TEST}::test_sentry_scrubber_removes_sensitive_fields_and_keeps_exception_shape",
    )),
    ("generation-delivery", (
        "tests/test_matrix_report_worker_lifecycle.py::TestWorkerFailure::test_retryable_failure_saves_safe_category",
        "tests/test_matrix_report_worker_lifecycle.py::TestWorkerPrivacy::test_retryable_failure_logs_no_raw_exception",
        "tests/test_full_report_telegram_delivery.py::test_retryable_sender_failure_does_not_mutate_report_or_order",
        "tests/test_mini_report_telegram_delivery.py::test_pdf_failure_preserves_sent_text_and_retry_sends_only_pdf",
    )),
    ("service-network-guard", (
        f"{SECURITY_ACCEPTANCE_TEST}::test_security_guard_blocks_public_destination_only_with_marker",
    )),
    ("security-context-scanner", (
        f"{SECURITY_ACCEPTANCE_TEST}::test_security_scanner_negative_control_does_not_disclose_value",
        f"{SECURITY_ACCEPTANCE_TEST}::test_security_scanner_pairwise_control_is_safe",
    )),
)
SECURITY_MATRIX_ROWS = (
    ("uvicorn-capability", "capability disclosure", "access-log redaction", "real Uvicorn checkout matrix", "P1", "FIXED", ("uvicorn-access", "http-response")),
    ("report-token-warning", "report capability disclosure", "bounded fallback warning", "fallback render warning proof", "P1", "FIXED", ("fallback-rendering", "fastapi-application")),
    ("telegram-startup-logs", "credential disclosure", "run-scoped service boot capture", "two-cycle Telegram boot", "P1", "SUFFICIENT", ("telegram-runtime",)),
    ("telegram-error-logs", "exception payload disclosure", "bounded aiogram error category", "global error regression", "P1", "FIXED", ("aiogram-error",)),
    ("celery-worker-logs", "worker credential disclosure", "run-scoped stdout stderr capture", "registered worker boot", "P2", "SUFFICIENT", ("celery-worker",)),
    ("celery-beat-logs", "scheduler credential disclosure", "run-scoped stdout stderr capture", "live beat boot", "P2", "SUFFICIENT", ("celery-beat",)),
    ("payment-webhook-rejection", "unverified activation", "provider verification and durable claim", "categorized webhook contracts", "P0", "SUFFICIENT", ("payment-webhook", "http-response")),
    ("generation-failure", "prompt or key disclosure", "safe category retry lifecycle", "retryable worker failure", "P1", "SUFFICIENT", ("generation-failure",)),
    ("delivery-failure", "Telegram payload disclosure", "typed retryable delivery state", "retryable sender failure", "P1", "SUFFICIENT", ("delivery-failure",)),
    ("idor-list-view-resend", "cross-user report access", "repository ownership predicates", "PostgreSQL owner attacker proof", "P0", "SUFFICIENT", ("fastapi-application", "http-response")),
    ("checkout-invalid-terminal", "invalid payment attempt", "opaque capability and terminal state checks", "real Uvicorn negative matrix", "P0", "SUFFICIENT", ("uvicorn-access", "http-response")),
    ("forged-webhook", "forged entitlement activation", "canonical provider lookup", "full matrix rejection matrix", "P0", "SUFFICIENT", ("payment-webhook", "security-events")),
    ("refund-protection", "post-refund delivery", "eligibility recheck before send", "refund race contracts", "P0", "SUFFICIENT", ("refund-deletion",)),
    ("account-deletion-replay", "identity resurrection", "idempotent deletion and Redis retry", "deletion replay contracts", "P0", "SUFFICIENT", ("refund-deletion",)),
    ("sentry-no-dsn", "unexpected public telemetry", "conditional canonical init", "official SDK no-DSN probe", "P1", "SUFFICIENT", ("sentry-probe",)),
    ("sentry-envelope", "telemetry payload disclosure", "generic before_send scrubber", "loopback envelope scan", "P1", "FIXED", ("sentry-envelope",)),
    ("cross-process-egress", "external network escape", "sitecustomize socket guard", "all security subprocesses", "P0", "SUFFICIENT", ("security-events",)),
    ("cleanup-failure-paths", "orphan process or raw artifact", "fail-closed owned cleanup", "success negative and partial-start proofs", "P1", "SUFFICIENT", ("cleanup-summary", "runner-summary")),
)
FAILURE_CONTRACT_FILES = (
    "tests/test_mini_report_telegram_delivery.py",
    "tests/test_daily_tarot_application.py",
    "tests/test_daily_tarot_migration_contract.py",
    "tests/test_lifetime_chat_contract.py",
    "tests/test_full_matrix_checkout.py",
    "tests/test_payment_webhook_verification.py",
    "tests/test_matrix_report_worker_lifecycle.py",
    "tests/test_report_generation_reconciliation.py",
    "tests/test_full_report_telegram_delivery.py",
    "tests/test_full_matrix_account_deletion.py",
)


def _run_service_boot(env: dict[str, str]) -> None:
    try:
        from tools.telegram_first_service_boot import run_service_boot
    except ModuleNotFoundError:
        from telegram_first_service_boot import run_service_boot

    run_service_boot(env)


@dataclass(frozen=True)
class Sandbox:
    postgres_name: str
    redis_name: str
    database_url: str
    failure_database_url: str
    security_database_url: str
    redis_url: str


def _run(label: str, *args: str, env: dict[str, str] | None = None) -> None:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    diagnostic = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    )
    if env and env.get("NURA_SECURITY_RUN_CONTEXT"):
        context = Path(env["NURA_SECURITY_RUN_CONTEXT"])
        role = env.get("NURA_SECURITY_PROCESS_ROLE", "security-runner")
        safe_label = "".join(
            character if character.isalnum() or character in "-." else "-"
            for character in label
        )[:96]
        (context / "logs" / f"{role}-{safe_label}.stdout.log").write_text(
            completed.stdout, encoding="utf-8"
        )
        (context / "logs" / f"{role}-{safe_label}.stderr.log").write_text(
            completed.stderr, encoding="utf-8"
        )
    for key in ("DATABASE_URL", "NURA_FAILURE_RETRY_DATABASE_URL", "POSTGRES_PASSWORD"):
        secret = (env or {}).get(key)
        if secret:
            diagnostic = diagnostic.replace(secret, "<redacted>")
    if env and env.get("NURA_SECURITY_RUN_CONTEXT"):
        registry_path = Path(env["NURA_SECURITY_RUN_CONTEXT"]) / "registry.json"
        if registry_path.exists():
            diagnostic = sanitize_text(diagnostic, json.loads(registry_path.read_text(encoding="utf-8")))
    if completed.returncode:
        print(diagnostic[-8000:])
        raise RuntimeError(f"command_failed:{label}")
    if diagnostic:
        print(diagnostic.rstrip())
    print(f"PASS: {label}")


def _docker(*args: str) -> str:
    completed = subprocess.run(
        ("docker", *args), text=True, capture_output=True, check=False
    )
    if completed.returncode:
        raise RuntimeError(f"docker_failed:{args[0]}")
    return completed.stdout.strip()


def _owned_volume_names(container: str) -> tuple[str, ...]:
    completed = subprocess.run(
        (
            "docker",
            "inspect",
            "--format",
            "{{range .Mounts}}{{if eq .Type \"volume\"}}{{println .Name}}{{end}}{{end}}",
            container,
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        return ()
    return tuple(line.strip() for line in completed.stdout.splitlines() if line.strip())


def _confirmed_absent(completed: subprocess.CompletedProcess[str], kind: str) -> bool:
    if completed.returncode == 0:
        return False
    detail = f"{completed.stdout}\n{completed.stderr}".casefold()
    expected = {
        "container": ("no such object", "no such container"),
        "volume": ("no such volume",),
    }
    return any(marker in detail for marker in expected[kind])


def _cleanup_owned_containers(*containers: str) -> bool:
    """Remove exact runner-owned containers/volumes and verify their absence."""
    volumes = {
        volume
        for container in containers
        for volume in _owned_volume_names(container)
    }
    clean = True
    for container in containers:
        removed = False
        for _attempt in range(3):
            subprocess.run(
                ("docker", "rm", "--force", "--volumes", container),
                text=True,
                capture_output=True,
                check=False,
            )
            inspected = subprocess.run(
                ("docker", "inspect", container),
                text=True,
                capture_output=True,
                check=False,
            )
            if _confirmed_absent(inspected, "container"):
                removed = True
                break
            time.sleep(0.25)
        if not removed:
            print(f"FAIL: cleanup_container_remaining:{container}")
            clean = False
    for volume in volumes:
        inspected = subprocess.run(
            ("docker", "volume", "inspect", volume),
            text=True,
            capture_output=True,
            check=False,
        )
        if not _confirmed_absent(inspected, "volume"):
            print(f"FAIL: cleanup_volume_remaining:{volume}")
            clean = False
    return clean


def _assert_no_labelled_resources() -> None:
    containers = _docker(
        "ps", "-a", "--filter", "label=nura.test=telegram-first-acceptance",
        "--format", "{{.ID}}",
    )
    volumes = _docker(
        "volume", "ls", "--filter", "label=nura.test=telegram-first-acceptance",
        "--format", "{{.Name}}",
    )
    if containers or volumes:
        raise RuntimeError("cleanup_proof_labelled_resource_remaining")


def _write_cleanup_proof(
    context: SecurityContext, proof: str, *, cleanup: str
) -> Path:
    destination = (
        Path(tempfile.gettempdir())
        / f"nura-security-cleanup-proof-{proof}-{context.run_id}.json"
    )
    destination.write_text(
        json.dumps(
            {
                "run_id": context.run_id,
                "proof": proof,
                "status": "PASS",
                "cleanup": cleanup,
                "managed_processes": 0,
                "occupied_ports": 0,
                "security_database": "absent",
                "redis_prefix": "absent",
                "labelled_containers": 0,
                "labelled_volumes": 0,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return destination


def _complete_cleanup_proof(
    context: SecurityContext, proof: str, destination: Path
) -> None:
    context.cleanup()
    if context.path.exists():
        raise RuntimeError(f"cleanup_proof_run_directory_remaining:{proof}")
    _assert_no_labelled_resources()
    data = json.loads(destination.read_text(encoding="utf-8"))
    data["cleanup"] = "PASS"
    destination.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def _run_cleanup_failure_proofs() -> tuple[Path, Path]:
    """Prove isolated scanner and partial-start cleanup before Docker creation."""
    _assert_no_labelled_resources()
    negative = SecurityContext.create({})
    negative_summary: Path | None = None
    try:
        leaked = negative.registry["checkout_capability"]
        (negative.path / "sentry" / "negative-control.bin").write_text(
            leaked, encoding="utf-8"
        )
        try:
            scan_artifacts(negative.path, negative.registry)
        except RuntimeError as error:
            if leaked in str(error) or "alias=checkout_capability" not in str(error):
                raise RuntimeError("negative_cleanup_scanner_diagnostic_unsafe") from error
        else:
            raise RuntimeError("negative_cleanup_scanner_did_not_fail")
        negative_summary = _write_cleanup_proof(
            negative, "negative-control", cleanup="pending"
        )
    finally:
        if negative_summary is None:
            negative.cleanup()
    assert negative_summary is not None
    _complete_cleanup_proof(negative, "negative-control", negative_summary)

    partial = SecurityContext.create({})
    partial_summary: Path | None = None
    try:
        from telegram_first_service_boot import prove_partial_start_cleanup

        prove_partial_start_cleanup(
            partial.child_environment(
                {
                    "APP_ENV": "test",
                    "NURA_DISABLE_DOTENV": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    **{
                        key: value
                        for key, value in os.environ.items()
                        if key.upper()
                        in {
                            "COMSPEC", "PATH", "PATHEXT", "SYSTEMROOT",
                            "TEMP", "TMP", "WINDIR",
                        }
                    },
                },
                role="partial-start-proof",
            )
        )
        scan_artifacts(partial.path, partial.registry)
        partial_summary = _write_cleanup_proof(
            partial, "partial-start", cleanup="pending"
        )
    finally:
        if partial_summary is None:
            partial.cleanup()
    assert partial_summary is not None
    _complete_cleanup_proof(partial, "partial-start", partial_summary)
    return negative_summary, partial_summary


def _wait_for_postgres(container: str, user: str, database: str) -> int:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        completed = subprocess.run(
            ("docker", "exec", container, "pg_isready", "--username", user, "--dbname", database),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode == 0:
            mapping = _docker("port", container, "5432/tcp")
            return int(mapping.rsplit(":", 1)[1])
        time.sleep(0.25)
    raise RuntimeError("postgres_not_ready")


def _wait_for_redis(container: str) -> int:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        completed = subprocess.run(
            ("docker", "exec", container, "redis-cli", "ping"),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip() == "PONG":
            mapping = _docker("port", container, "6379/tcp")
            return int(mapping.rsplit(":", 1)[1])
        time.sleep(0.25)
    raise RuntimeError("redis_not_ready")


def _create_postgres_database(
    container: str, user: str, database: str
) -> None:
    """Wait through the image's temporary init server before creating a database."""
    deadline = time.monotonic() + 30
    last_detail = "unknown"
    while time.monotonic() < deadline:
        created = subprocess.run(
            (
                "docker",
                "exec",
                container,
                "createdb",
                "--username",
                user,
                database,
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        if created.returncode == 0:
            return
        last_detail = (created.stderr or created.stdout).strip()[-1000:]
        time.sleep(0.25)
    raise RuntimeError(
        f"failure_database_create_failed:{last_detail or 'unknown'}"
    )


def _create_sandbox() -> Sandbox:
    suffix = uuid.uuid4().hex[:12]
    postgres_name = f"nura-telegram-acceptance-pg-{suffix}"
    redis_name = f"nura-telegram-acceptance-redis-{suffix}"
    user = f"nura_{suffix}"
    database = f"nura_{suffix}"
    password = secrets.token_urlsafe(24)
    _docker(
        "run", "--detach", "--name", postgres_name,
        "--label", "nura.test=telegram-first-acceptance",
        "--env", f"POSTGRES_USER={user}",
        "--env", f"POSTGRES_PASSWORD={password}",
        "--env", f"POSTGRES_DB={database}",
        "--publish", "127.0.0.1::5432", "postgres:16-alpine",
    )
    try:
        pg_port = _wait_for_postgres(postgres_name, user, database)
        failure_database = f"nura_failure_{suffix}"
        _create_postgres_database(postgres_name, user, failure_database)
        security_database = f"nura_security_{suffix}"
        _create_postgres_database(postgres_name, user, security_database)
        _docker(
            "run", "--detach", "--name", redis_name,
            "--label", "nura.test=telegram-first-acceptance",
            "--publish", "127.0.0.1::6379", "redis:7-alpine",
        )
        redis_port = _wait_for_redis(redis_name)
    except Exception:
        _cleanup_owned_containers(redis_name, postgres_name)
        raise
    return Sandbox(
        postgres_name, redis_name,
        f"postgresql+asyncpg://{user}:{password}@127.0.0.1:{pg_port}/{database}",
        f"postgresql+asyncpg://{user}:{password}@127.0.0.1:{pg_port}/{failure_database}",
        f"postgresql+asyncpg://{user}:{password}@127.0.0.1:{pg_port}/{security_database}",
        f"redis://127.0.0.1:{redis_port}/0",
    )


def _environment(sandbox: Sandbox) -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items()
        if key.upper() in {"COMSPEC", "PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP", "WINDIR"}
    }
    database_url = sandbox.database_url
    postgres_prefix, database_name = database_url.rsplit("/", 1)
    credentials, host_port = postgres_prefix.removeprefix("postgresql+asyncpg://").rsplit("@", 1)
    user, password = credentials.split(":", 1)
    host, port = host_port.rsplit(":", 1)
    env.update({
        "APP_ENV": "test",
        "NURA_DISABLE_DOTENV": "1",
        "DATABASE_URL": database_url,
        "NURA_GOLDEN_PATH_DATABASE_URL": database_url,
        "NURA_FAILURE_RETRY_DATABASE_URL": sandbox.failure_database_url,
        "NURA_SECURITY_DATABASE_URL": sandbox.security_database_url,
        "NURA_SECURITY_REDIS_PREFIX": f"nura:security:{database_name}:",
        "POSTGRES_USER": user,
        "POSTGRES_PASSWORD": password,
        "POSTGRES_DB": database_name,
        "POSTGRES_HOST": host,
        "POSTGRES_PORT": port,
        "REDIS_URL": sandbox.redis_url,
        "NURA_CELERY_BROKER_URL": sandbox.redis_url.rsplit("/", 1)[0] + "/1",
        "NURA_CELERY_RESULT_BACKEND": sandbox.redis_url.rsplit("/", 1)[0] + "/2",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return env


def _failure_environment(env: dict[str, str]) -> dict[str, str]:
    failure_env = env.copy()
    failure_env["DATABASE_URL"] = failure_env["NURA_FAILURE_RETRY_DATABASE_URL"]
    return failure_env


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--security-only",
        action="store_true",
        help="run only the isolated PostgreSQL security acceptance proof",
    )
    parser.add_argument(
        "--golden-path-only",
        action="store_true",
        help="run only the handler-level PostgreSQL golden path",
    )
    parser.add_argument(
        "--failure-retry-only",
        action="store_true",
        help="run only the isolated PostgreSQL failure/retry proof",
    )
    parser.add_argument(
        "--service-boot-only",
        action="store_true",
        help="run only the local required-service subprocess proof",
    )
    parser.add_argument(
        "--safe-suite-only",
        action="store_true",
        help="run deterministic local pytest file shards with per-shard cleanup checks",
    )
    return parser.parse_args()


def _run_golden_path(env: dict[str, str]) -> None:
    _run(
        "attribution_link_setup",
        PYTHON,
        "-m",
        "scripts.attribution_links",
        "create",
        "--platform",
        "telegram",
        "--source",
        "sandbox",
        "--campaign",
        "golden_path",
        "--content-id",
        "handler_segment",
        "--topic",
        "acceptance",
        "--code",
        "nura_start_01",
        env=env,
    )
    for test_name, label in (
        (
            "test_handler_golden_path_start_consent_and_onboarding",
            "postgresql_handler_golden_path",
        ),
        (
            "test_handler_golden_path_survives_fresh_process",
            "postgresql_handler_golden_path_restart",
        ),
        (
            "test_mini_report_generation_and_delivery",
            "postgresql_mini_report_generation_and_delivery",
        ),
        (
            "test_mini_report_restart_and_repeated_access",
            "postgresql_mini_report_restart_and_repeated_access",
        ),
        (
            "test_daily_tarot_initial_and_same_process_replay",
            "postgresql_daily_tarot_initial_and_replay",
        ),
        (
            "test_daily_tarot_restart_reuses_durable_result",
            "postgresql_daily_tarot_restart_replay",
        ),
        (
            "test_lifetime_chat_five_telegram_requests_and_replay",
            "postgresql_lifetime_chat_five_requests_and_replay",
        ),
        (
            "test_lifetime_chat_restart_replay_and_sixth_request_are_durable",
            "postgresql_lifetime_chat_restart_replay_and_sixth_request",
        ),
        (
            "test_checkout_get_rejects_unknown_capability",
            "postgresql_checkout_unknown_capability_rejected",
        ),
        (
            "test_full_matrix_checkout_is_durable_and_non_activating",
            "postgresql_full_matrix_checkout",
        ),
        (
            "test_verified_webhook_activates_checkout_once",
            "postgresql_verified_webhook",
        ),
        (
            "test_verified_webhook_fresh_process_replay",
            "postgresql_verified_webhook_fresh_process_replay",
        ),
        (
            "test_full_report_generation_uses_existing_job_and_dispatches_delivery_once",
            "postgresql_full_report_generation",
        ),
        (
            "test_full_report_generation_fresh_process_replay_is_idempotent",
            "postgresql_full_report_generation_fresh_process_replay",
        ),
        (
            "test_automatic_full_report_delivery_uses_queued_registered_task",
            "postgresql_automatic_full_report_delivery",
        ),
        (
            "test_automatic_full_report_delivery_fresh_process_replay_has_no_sends",
            "postgresql_automatic_full_report_delivery_fresh_process_replay",
        ),
        (
            "test_manual_full_report_resend_reuses_persisted_file_id",
            "postgresql_manual_full_report_resend",
        ),
        (
            "test_manual_full_report_resend_fresh_process_replay_has_no_sends",
            "postgresql_manual_full_report_resend_fresh_process_replay",
        ),
        (
            "test_full_restart_durability",
            "postgresql_full_restart_durability",
        ),
        (
            "test_refund_replay_revokes_entitlement_and_blocks_delivery",
            "postgresql_refund_replay",
        ),
        (
            "test_account_deletion_replay_anonymizes_financial_state_and_clears_redis",
            "postgresql_account_deletion_replay",
        ),
    ):
        _run(
            label,
            PYTHON,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            f"{GOLDEN_PATH_TEST}::{test_name}",
            "-q",
            env=env,
        )


def _run_failure_retry(env: dict[str, str]) -> None:
    failure_env = _failure_environment(env)
    _run("failure_retry_alembic_upgrade", PYTHON, "-m", "alembic", "upgrade", "head", env=failure_env)
    _run("postgresql_failure_retry", PYTHON, "-m", "pytest", "-p", "no:cacheprovider", FAILURE_RETRY_TEST, "-q", env=failure_env)
    _run(
        "failure_retry_targeted_contracts",
        PYTHON,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        *FAILURE_CONTRACT_FILES,
        "-q",
        env=failure_env,
    )


def _run_security(env: dict[str, str], context: SecurityContext) -> Path:
    security_env = context.child_environment(env, role="security-runner")
    security_env["DATABASE_URL"] = security_env["NURA_SECURITY_DATABASE_URL"]
    migration_env = context.child_environment(security_env, role="security-migration")
    acceptance_env = context.child_environment(security_env, role="security-acceptance")
    _run("security_alembic_upgrade", PYTHON, "-m", "alembic", "upgrade", "head", env=migration_env)
    _run(
        "security_runtime_dependency_probe",
        PYTHON,
        "-c",
        RUNTIME_PROBE,
        env=context.child_environment(security_env, role="security-dependency-probe"),
    )
    _run(
        "postgresql_security_acceptance",
        PYTHON, "-m", "pytest", "-p", "no:cacheprovider", SECURITY_ACCEPTANCE_TEST, "-q",
        env=acceptance_env,
    )
    _run_service_boot(context.child_environment(security_env, role="service-boot"))
    from telegram_first_sentry_probe import run_sentry_probes

    run_sentry_probes(context.child_environment(security_env, role="sentry-probe"), context.path)
    for category, exact_paths in SECURITY_TEST_CATEGORIES:
        _run(
            f"security_contract_{category}",
            PYTHON,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            *exact_paths,
            "-q",
            env=context.child_environment(
                security_env, role=f"security-contract-{category}"
            ),
        )
    rows = [
        {
            "asset": asset,
            "threat": threat,
            "production_control": control,
            "probe": probe,
            "result": "PASS",
            "severity": severity,
            "disposition": disposition,
            "sinks": list(sinks),
        }
        for asset, threat, control, probe, severity, disposition, sinks
        in SECURITY_MATRIX_ROWS
    ]
    for row in rows:
        context.record_proof(row["asset"], *row["sinks"])
    context.write_matrix(rows)
    return context.safe_summary("PASS", "pending_runner_cleanup")


def main() -> int:
    args = _parse_args()
    if args.safe_suite_only:
        from telegram_first_safe_suite import run_safe_suite

        exit_code, summary = run_safe_suite()
        print(f"{summary['status']}: safe_suite_summary={summary['output_directory']}/summary.json")
        return exit_code
    if shutil.which("docker") is None:
        print("BLOCKED_BY_ENVIRONMENT: docker_not_found")
        return 2
    try:
        _docker("info", "--format", "{{.ServerVersion}}")
    except RuntimeError:
        print("BLOCKED_BY_ENVIRONMENT: docker_daemon_unavailable")
        return 2

    sandbox: Sandbox | None = None
    security_context: SecurityContext | None = None
    security_summary: Path | None = None
    exit_code = 0
    success_message: str | None = None
    try:
        runs_security = args.security_only or not any(
            (args.failure_retry_only, args.golden_path_only, args.service_boot_only)
        )
        if runs_security:
            cleanup_proofs = _run_cleanup_failure_proofs()
            print(
                "PASS: cleanup_failure_proofs="
                + ",".join(str(path) for path in cleanup_proofs)
            )
        sandbox = _create_sandbox()
        env = _environment(sandbox)
        _run("alembic_upgrade", PYTHON, "-m", "alembic", "upgrade", "head", env=env)
        if args.security_only:
            security_context = SecurityContext.create(env)
            security_summary = _run_security(env, security_context)
            print(f"PASS: security_safe_summary={security_summary}")
            success_message = "PASS: PostgreSQL security acceptance completed"
        elif args.failure_retry_only:
            _run_failure_retry(env)
            success_message = "PASS: PostgreSQL failure/retry chain completed"
        elif args.golden_path_only:
            _run_golden_path(env)
            success_message = (
                "PASS: PostgreSQL golden path segments completed: "
                "start_and_onboarding, mini_report, daily_tarot, lifetime_chat, checkout, "
                "verified_webhook, full_report_generation, automatic_delivery, manual_resend, "
                "full_restart_durability, refund_and_account_deletion_replay"
            )
        elif args.service_boot_only:
            _run_service_boot(env)
            success_message = "PASS: Telegram-first service boot completed"
        else:
            _run("alembic_downgrade", PYTHON, "-m", "alembic", "downgrade", "-1", env=env)
            _run("alembic_repeat_upgrade", PYTHON, "-m", "alembic", "upgrade", "head", env=env)
            _run("alembic_heads", PYTHON, "-m", "alembic", "heads", env=env)
            _run("runtime_postgres_redis_probe", PYTHON, "-c", RUNTIME_PROBE, env=env)
            _run_service_boot(env)
            print("PASS: Telegram-first service boot completed")
            security_context = SecurityContext.create(env)
            security_summary = _run_security(env, security_context)
            print(f"PASS: security_safe_summary={security_summary}")
            _run_failure_retry(env)
            _run_golden_path(env)
            _run("telegram_first_contract_suite", PYTHON, "-m", "pytest", "-v", *TEST_FILES, env=env)
            success_message = "PASS: local Telegram-first acceptance contracts completed"
    except RuntimeError as error:
        print(f"FAIL: {error}")
        exit_code = 1
    finally:
        if security_context is not None:
            try:
                security_context.cleanup()
                if security_summary is not None:
                    summary_data = json.loads(security_summary.read_text(encoding="utf-8"))
                    summary_data["cleanup"] = "PASS"
                    security_summary.write_text(
                        json.dumps(summary_data, sort_keys=True), encoding="utf-8"
                    )
            except Exception as error:  # noqa: BLE001 - cleanup is a security proof
                print(f"FAIL: security_context_cleanup:{type(error).__name__}")
                exit_code = 1
        if sandbox is not None and not _cleanup_owned_containers(
            sandbox.redis_name, sandbox.postgres_name
        ):
            exit_code = 1
    if exit_code == 0 and success_message:
        print(success_message)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
