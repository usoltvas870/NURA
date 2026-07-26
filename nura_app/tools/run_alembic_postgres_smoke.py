"""Run all Alembic smoke harnesses against disposable PostgreSQL 16.

This is the only smoke component that manages Docker. It creates one uniquely
named container bound to an ephemeral loopback port, passes ``DATABASE_URL``
only to child processes, and removes that exact container in ``finally``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import psycopg2

REPO_ROOT = Path(__file__).resolve().parents[2]
NURA_APP_ROOT = REPO_ROOT / "nura_app"
IMAGE = "postgres:16-alpine"
HARNESS_PATHS = (
    NURA_APP_ROOT / "tools" / "alembic_postgres_bootstrap_smoke.py",
    NURA_APP_ROOT / "tools" / "alembic_fk_normalization_smoke.py",
    NURA_APP_ROOT / "tools" / "alembic_production_reconciliation_smoke.py",
    NURA_APP_ROOT / "tools" / "telegram_report_delivery_postgres_smoke.py",
    NURA_APP_ROOT / "tools" / "lifetime_chat_postgres_smoke.py",
    NURA_APP_ROOT / "tools" / "daily_tarot_postgres_smoke.py",
)
READY_TIMEOUT_SECONDS = 45
_EXECUTION_ENV_KEYS = (
    "COMSPEC",
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "WINDIR",
)
_ALEMBIC_LAUNCHER = (
    "from pydantic_settings.sources import DotEnvSettingsSource;"
    "DotEnvSettingsSource.__call__=lambda self:{};"
    "from alembic.config import CommandLine;"
    "CommandLine(prog='alembic').main()"
)


def _child_env(
    database_url: str, evidence_dir: Path | None = None
) -> dict[str, str]:
    env = {key: os.environ[key] for key in _EXECUTION_ENV_KEYS if key in os.environ}
    env.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": database_url,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(NURA_APP_ROOT),
        }
    )
    if evidence_dir is not None:
        env["RECONCILIATION_EVIDENCE_DIR"] = str(evidence_dir)
    return env


def _alembic_command(*args: str) -> list[str]:
    return [sys.executable, "-c", _ALEMBIC_LAUNCHER, *args]


def _sanitize(text: str, secrets_to_mask: tuple[str, ...]) -> str:
    for value in sorted((value for value in secrets_to_mask if value), key=len, reverse=True):
        replacement = "postgresql://***/***" if value.startswith("postgresql") else "***"
        text = text.replace(value, replacement)
    text = re.sub(
        r"postgresql(?:\+[^:/]+)?://[^\s@]+@[^/\s]+/[^\s]+",
        "postgresql://***/***",
        text,
    )
    return re.sub(
        r"password=[^\s&\"']+", "password=***", text, flags=re.IGNORECASE
    )


def _run(
    command: list[str],
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
    secrets_to_mask: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=NURA_APP_ROOT,
        env=env,
    )
    if check and result.returncode != 0:
        detail = _sanitize(result.stdout + result.stderr, secrets_to_mask)
        raise RuntimeError(f"Command failed with exit {result.returncode}: {detail}")
    return result


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, value: object) -> None:
    _write(path, json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


def _database_evidence(database_url: str) -> tuple[str, list[dict[str, object]], list[dict[str, object]]]:
    tables = [
        "users",
        "reports",
        "payments",
        "promo_codes",
        "promo_reservations",
        "report_generation_jobs",
        "mini_report_generations",
        "telegram_report_deliveries",
        "chat_message_usages",
        "daily_tarot_draws",
        "guest_profiles",
        "referral_rewards",
        "alembic_version",
    ]
    with psycopg2.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version()")
            postgres_version = str(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT table_name, ordinal_position, column_name, data_type,
                       udt_name, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = ANY(%s)
                ORDER BY table_name, ordinal_position
                """,
                (tables,),
            )
            catalog = [
                dict(zip([column.name for column in cursor.description], row, strict=True))
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT c.conrelid::regclass::text AS table_name, c.conname,
                       c.contype, pg_get_constraintdef(c.oid) AS definition
                FROM pg_catalog.pg_constraint c
                WHERE c.connamespace = 'public'::regnamespace
                ORDER BY 1, 2
                """
            )
            constraints = [
                dict(zip([column.name for column in cursor.description], row, strict=True))
                for row in cursor.fetchall()
            ]
    return postgres_version, catalog, constraints


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        help="Optional external directory for redacted validation evidence.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    suffix = secrets.token_hex(6)
    container_name = f"nura-alembic-smoke-{suffix}"
    username = f"smoke_{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(24)
    database = f"smoke_{secrets.token_hex(4)}"
    database_url = ""
    secrets_to_mask = (username, password, database)
    container_created = False
    exit_code = 1
    harness_results: list[tuple[Path, subprocess.CompletedProcess[str]]] = []

    try:
        _run(["docker", "version"])
        _run(["docker", "info"])
        _run(["docker", "image", "inspect", IMAGE])
        result = _run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container_name,
                "-e",
                f"POSTGRES_USER={username}",
                "-e",
                f"POSTGRES_PASSWORD={password}",
                "-e",
                f"POSTGRES_DB={database}",
                "-p",
                "127.0.0.1::5432",
                IMAGE,
            ],
            secrets_to_mask=secrets_to_mask,
        )
        container_created = bool(result.stdout.strip())

        deadline = time.monotonic() + READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            ready = _run(
                ["docker", "exec", container_name, "pg_isready", "-U", username, "-d", database],
                check=False,
                secrets_to_mask=secrets_to_mask,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Disposable PostgreSQL readiness timed out")

        port_result = _run(["docker", "port", container_name, "5432/tcp"])
        port_line = port_result.stdout.strip().splitlines()[-1]
        match = re.fullmatch(r"127\.0\.0\.1:(\d+)", port_line)
        if not match:
            raise RuntimeError(f"Unexpected loopback port mapping: {port_line}")
        port = match.group(1)
        database_url = (
            f"postgresql://{quote(username)}:{quote(password)}@127.0.0.1:{port}/{quote(database)}"
        )
        secrets_to_mask = (*secrets_to_mask, database_url)

        evidence_dir = args.evidence_dir.resolve() if args.evidence_dir else None
        child_env = _child_env(database_url, evidence_dir)

        for harness_path in HARNESS_PATHS:
            result = _run(
                [sys.executable, str(harness_path)],
                check=False,
                env=child_env,
                secrets_to_mask=secrets_to_mask,
            )
            harness_results.append((harness_path, result))
            output = _sanitize(result.stdout + result.stderr, secrets_to_mask)
            print(f"--- {harness_path.name} ---")
            print(output, end="" if output.endswith("\n") else "\n")

        if args.evidence_dir:
            assert evidence_dir is not None
            evidence_dir.mkdir(parents=True, exist_ok=True)
            docker_version = _run(["docker", "version"], secrets_to_mask=secrets_to_mask)
            _write(evidence_dir / "docker-version.txt", docker_version.stdout + docker_version.stderr)
            outputs = {path.name: result for path, result in harness_results}
            _write(
                evidence_dir / "bootstrap-smoke.txt",
                _sanitize(
                    outputs[HARNESS_PATHS[0].name].stdout + outputs[HARNESS_PATHS[0].name].stderr,
                    secrets_to_mask,
                ),
            )
            _write(
                evidence_dir / "fk-normalization-smoke.txt",
                _sanitize(
                    outputs[HARNESS_PATHS[1].name].stdout + outputs[HARNESS_PATHS[1].name].stderr,
                    secrets_to_mask,
                ),
            )
            _write(
                evidence_dir / "production-reconciliation-smoke.txt",
                _sanitize(
                    outputs[HARNESS_PATHS[2].name].stdout + outputs[HARNESS_PATHS[2].name].stderr,
                    secrets_to_mask,
                ),
            )
            _write(
                evidence_dir / "telegram-report-delivery-smoke.txt",
                _sanitize(
                    outputs[HARNESS_PATHS[3].name].stdout
                    + outputs[HARNESS_PATHS[3].name].stderr,
                    secrets_to_mask,
                ),
            )
            _write(
                evidence_dir / "lifetime-chat-smoke.txt",
                _sanitize(
                    outputs[HARNESS_PATHS[4].name].stdout
                    + outputs[HARNESS_PATHS[4].name].stderr,
                    secrets_to_mask,
                ),
            )
            heads = _run(_alembic_command("heads"), env=child_env, secrets_to_mask=secrets_to_mask)
            history = _run(_alembic_command("history"), env=child_env, secrets_to_mask=secrets_to_mask)
            _write(evidence_dir / "alembic-heads.txt", heads.stdout + heads.stderr)
            _write(evidence_dir / "alembic-history.txt", history.stdout + history.stderr)
            postgres_version, catalog, constraints = _database_evidence(database_url)
            _write(evidence_dir / "postgres-version.txt", postgres_version + "\n")
            _write_json(evidence_dir / "schema-catalog.json", catalog)
            _write_json(evidence_dir / "constraints.json", constraints)
            _write_json(
                evidence_dir / "validation-summary.json",
                {
                    "container_name": container_name,
                    "database_url": "postgresql://***/***",
                    "image": IMAGE,
                    "harnesses": {
                        path.name: {"exit_code": result.returncode}
                        for path, result in harness_results
                    },
                    "loopback_only": True,
                    "cleanup": f"docker rm -f -v {container_name}",
                },
            )
            _write(
                evidence_dir / "commands-run.txt",
                "\n".join(
                    [
                        "docker version",
                        "docker info",
                        f"docker image inspect {IMAGE}",
                        "docker run <unique-name> -p 127.0.0.1::<postgres-port> <disposable-credentials>",
                        "python tools/alembic_postgres_bootstrap_smoke.py",
                        "python tools/alembic_fk_normalization_smoke.py",
                        "python tools/alembic_production_reconciliation_smoke.py",
                        "python tools/telegram_report_delivery_postgres_smoke.py",
                        "python tools/lifetime_chat_postgres_smoke.py",
                        "python tools/daily_tarot_postgres_smoke.py",
                        "alembic heads",
                        "alembic history",
                        f"docker rm -f -v {container_name}",
                    ]
                )
                + "\n",
            )

        exit_code = 0 if all(result.returncode == 0 for _, result in harness_results) else 1
    except Exception as exc:
        print(f"FATAL: {_sanitize(str(exc), secrets_to_mask)}", file=sys.stderr)
        exit_code = 1
    finally:
        if container_created:
            cleanup = _run(
                ["docker", "rm", "-f", "-v", container_name],
                check=False,
                secrets_to_mask=secrets_to_mask,
            )
            if cleanup.returncode == 0:
                print(f"Cleanup: removed exact container {container_name}")
            else:
                print("Cleanup failed for the exact disposable container", file=sys.stderr)
                exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
