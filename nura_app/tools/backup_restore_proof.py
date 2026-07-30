"""Prove a synthetic PostgreSQL 16 custom-archive backup and restore.

This runner deliberately creates and destroys its own labeled Docker network,
source container, target container, databases, credentials, and evidence.  It
does not accept a DSN and is not a production backup or restore executor.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import UUID

import psycopg2
from psycopg2 import sql

try:
    from tools.backup_restore_fixtures import (
        EXPECTED_ROW_COUNTS,
        fixture_manifest,
        insert_synthetic_fixtures,
    )
except ModuleNotFoundError:  # Direct ``python tools/...`` invocation.
    from backup_restore_fixtures import (  # type: ignore[no-redef]
        EXPECTED_ROW_COUNTS,
        fixture_manifest,
        insert_synthetic_fixtures,
    )

REPO_ROOT = Path(__file__).resolve().parents[2]
NURA_APP_ROOT = REPO_ROOT / "nura_app"
IMAGE = "postgres:16.13"
EXPECTED_IMAGE_DIGEST = (
    "postgres@sha256:5d143123fdf80462d1778cd4f24b9f7ca13c87174bca19141fb194c5a1ebca59"
)
PURPOSE_LABEL = "p5b-backup-restore-proof"
READY_TIMEOUT_SECONDS = 60
COMMAND_TIMEOUT_SECONDS = 180
RESTORE_CEILING_SECONDS = 15 * 60
VERIFY_CEILING_SECONDS = 10 * 60
TOTAL_CEILING_SECONDS = 30 * 60
EXPECTED_PUBLIC_TABLES = {
    "alembic_version",
    "attribution_links",
    "attribution_touches",
    "broadcast_audit_entries",
    "broadcast_campaigns",
    "broadcast_cta_clicks",
    "broadcast_cta_click_events",
    "broadcast_deliveries",
    "chat_message_usages",
    "daily_tarot_draws",
    "full_report_telegram_deliveries",
    "guest_profiles",
    "mini_report_generations",
    "orders",
    "payment_attempts",
    "payment_events",
    "payments",
    "promo_codes",
    "promo_reservations",
    "referral_rewards",
    "report_generation_jobs",
    "reports",
    "telegram_report_deliveries",
    "telegram_suppressions",
    "users",
}
APPLICATION_TABLES = EXPECTED_PUBLIC_TABLES - {"alembic_version"}
_SAFE_ENV_KEYS = (
    "APPDATA",
    "COMSPEC",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
)
_ALEMBIC_LAUNCHER = (
    "from pydantic_settings.sources import DotEnvSettingsSource;"
    "DotEnvSettingsSource.__call__=lambda self:{};"
    "from alembic.config import CommandLine;"
    "CommandLine(prog='alembic').main()"
)
_IDENTIFIER_PATTERNS = {
    "run": re.compile(r"^p5b_[0-9a-f]{12}$"),
    "source_database": re.compile(r"^p5b_source_[0-9a-f]{12}$"),
    "target_database": re.compile(r"^p5b_target_[0-9a-f]{12}$"),
    "source_container": re.compile(r"^nura-p5b-source-[0-9a-f]{12}$"),
    "target_container": re.compile(r"^nura-p5b-target-[0-9a-f]{12}$"),
    "network": re.compile(r"^nura-p5b-network-[0-9a-f]{12}$"),
}
_RESTORED_CHECK_ARRAY_LITERAL = re.compile(
    r"\(('[^']*'::character varying)\)::text"
)
_SOURCE_CHECK_ARRAY_CAST = re.compile(r"\(ARRAY\[([^\[\]]*)\]\)::text\[\]")
_MANIFEST_KEYS = {
    "alembic_revision",
    "archive_filename",
    "archive_sha256",
    "archive_size_bytes",
    "current_branch",
    "current_git_sha",
    "catalog_counts",
    "encryption_status",
    "fixture_manifest_sha256",
    "image_digest",
    "object_inventory_summary",
    "pg_dump_version",
    "pg_restore_version",
    "postgresql_server_version",
    "proof_status",
    "remote_main_sha",
    "repository_clean",
    "row_counts",
    "run_id",
    "source_database",
    "source_schema_fingerprint",
    "target_database",
    "timestamps_utc",
}
_PROOF_CONNECTION_COUNT = 0


class ProofError(RuntimeError):
    """A fail-closed P5B contract violation."""


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass(frozen=True)
class RepositoryState:
    current_git_sha: str
    current_branch: str
    remote_main_sha: str
    repository_clean: bool


@dataclass(frozen=True)
class DockerEndpoint:
    context_name: str
    endpoint: str
    redacted_endpoint: str
    scheme: str


@dataclass(frozen=True)
class DatabaseSnapshot:
    revision: str
    schema_fingerprint: str
    catalog: dict[str, list[dict[str, object]]]
    catalog_counts: dict[str, int]
    row_counts: dict[str, int]
    data_checksums: dict[str, str]
    sequence_states: dict[str, dict[str, object]]
    logical_size_bytes: int
    pii_guard: dict[str, object]


@dataclass(frozen=True)
class SchemaDifference:
    object_type: str
    path: str
    source_value: str
    restored_value: str


@dataclass(frozen=True)
class ProofResult:
    run_id: str
    evidence_dir: str
    archive_path: str
    archive_sha256: str
    archive_size_bytes: int
    source_revision: str
    restored_revision: str
    source_fingerprint: str
    restored_fingerprint: str
    image_digest: str
    server_version: str
    client_versions: dict[str, str]
    timings: dict[str, float]
    throughput: dict[str, float | int]
    fail_closed_matrix: dict[str, str]
    cleanup: dict[str, object]


def _sanitize(text: str, secrets_to_mask: tuple[str, ...] = ()) -> str:
    for value in sorted((value for value in secrets_to_mask if value), key=len, reverse=True):
        text = text.replace(value, "***")
    text = re.sub(
        r"postgresql(?:\+[^:/]+)?://[^\s@]+@[^/\s]+/[^\s]+",
        "postgresql://***/***",
        text,
    )
    return re.sub(r"password=[^\s&\"']+", "password=***", text, flags=re.I)


def _run(
    command: list[str],
    *,
    check: bool = True,
    cwd: Path = NURA_APP_ROOT,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: int = COMMAND_TIMEOUT_SECONDS,
    secrets_to_mask: tuple[str, ...] = (),
) -> CommandResult:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            input=input_text,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProofError(f"Command timed out after {timeout}s: {command[0]}") from exc
    result = CommandResult(
        command=tuple(_sanitize(argument, secrets_to_mask) for argument in command),
        returncode=completed.returncode,
        stdout=_sanitize(completed.stdout, secrets_to_mask),
        stderr=_sanitize(completed.stderr, secrets_to_mask),
        duration_seconds=time.monotonic() - started,
    )
    if check and result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        raise ProofError(
            f"Command failed with exit {result.returncode}: {command[0]}: {detail}"
        )
    return result


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _command_env(values: dict[str, str] | None = None) -> dict[str, str]:
    env = {key: os.environ[key] for key in _SAFE_ENV_KEYS if key in os.environ}
    if values:
        env.update(values)
    return env


def _docker_bootstrap_env() -> dict[str, str]:
    env = _command_env()
    for key in ("DOCKER_CONTEXT", "DOCKER_HOST"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _validate_local_docker_endpoint(context_name: str, endpoint: str) -> DockerEndpoint:
    candidate = endpoint.strip()
    parsed = urlsplit(candidate)
    scheme = parsed.scheme.lower()
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProofError("Docker endpoint contains forbidden credentials or parameters")
    if scheme == "unix":
        if parsed.netloc or not parsed.path.startswith("/"):
            raise ProofError("Unix Docker endpoint is not a local absolute socket")
    elif scheme == "npipe":
        if parsed.netloc or not parsed.path.lower().startswith("//./pipe/"):
            raise ProofError("Docker named-pipe endpoint is not local")
    elif scheme == "tcp":
        try:
            host = parsed.hostname
            if host is None or (
                host.lower() != "localhost"
                and not ipaddress.ip_address(host).is_loopback
            ):
                raise ProofError("Docker TCP endpoint is not loopback-local")
        except ValueError as exc:
            raise ProofError("Docker TCP endpoint host is not a loopback IP") from exc
        if parsed.port is None:
            raise ProofError("Docker TCP endpoint has no explicit port")
    else:
        raise ProofError("Docker endpoint scheme is not an approved local transport")
    redacted = f"{scheme}://{parsed.netloc}{parsed.path}"
    return DockerEndpoint(context_name, candidate, redacted, scheme)


def _docker_endpoint_preflight(evidence_dir: Path) -> DockerEndpoint:
    bootstrap_env = _docker_bootstrap_env()
    context_name = _run(
        ["docker", "context", "show"], env=bootstrap_env, timeout=30
    ).stdout.strip()
    if not context_name:
        raise ProofError("Docker active context could not be determined")
    configured_context = os.environ.get("DOCKER_CONTEXT", "").strip()
    configured_host = os.environ.get("DOCKER_HOST", "").strip()
    if configured_context and configured_host:
        raise ProofError("Conflicting DOCKER_CONTEXT and DOCKER_HOST are not allowed")
    inspected = _run(
        [
            "docker",
            "context",
            "inspect",
            context_name,
            "--format",
            "{{json .Endpoints.docker.Host}}",
        ],
        env=bootstrap_env,
        timeout=30,
    ).stdout.strip()
    try:
        context_endpoint = json.loads(inspected)
    except json.JSONDecodeError as exc:
        raise ProofError("Docker context endpoint inspection returned invalid JSON") from exc
    if not isinstance(context_endpoint, str) or not context_endpoint.strip():
        raise ProofError("Docker context has no inspectable endpoint")
    effective_endpoint = configured_host or context_endpoint
    verified = _validate_local_docker_endpoint(context_name, effective_endpoint)
    _write_json(
        evidence_dir / "04_docker_endpoint_gate.json",
        {
            "status": "PASS",
            "context_name": verified.context_name,
            "endpoint_scheme": verified.scheme,
            "redacted_endpoint": verified.redacted_endpoint,
            "local_endpoint_verified": True,
        },
    )
    return verified


def _docker(
    endpoint: DockerEndpoint,
    arguments: list[str],
    *,
    check: bool = True,
    timeout: int = COMMAND_TIMEOUT_SECONDS,
    secrets_to_mask: tuple[str, ...] = (),
    env_values: dict[str, str] | None = None,
) -> CommandResult:
    return _run(
        ["docker", "--host", endpoint.endpoint, *arguments],
        check=check,
        env=_command_env(env_values),
        timeout=timeout,
        secrets_to_mask=secrets_to_mask,
    )


def _secure_path(path: Path, *, directory: bool) -> None:
    if os.name == "nt":
        username = os.environ.get("USERNAME", "").strip()
        if not username:
            raise ProofError("Unable to identify the Windows evidence owner")
        permission = f"{username}:(OI)(CI)F" if directory else f"{username}:F"
        _run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", permission],
            cwd=path.parent,
            timeout=30,
        )
        listing = _run(["icacls", str(path)], cwd=path.parent, timeout=30).stdout.lower()
        broad_principals = (
            "authenticated users",
            "builtin\\users",
            "everyone",
            "пользователи",
            "прошедшие проверку",
            "все",
        )
        if any(principal in listing for principal in broad_principals):
            raise ProofError("Evidence path retains a broad Windows ACL")
        return
    path.chmod(0o700 if directory else 0o600)
    if path.stat().st_mode & 0o077:
        raise ProofError("Evidence path permissions are not owner-only")


def _verify_secure_path(path: Path, *, directory: bool) -> None:
    if not path.exists():
        raise ProofError("Protected evidence path is missing")
    _secure_path(path, directory=directory)


def _write_json(path: Path, value: object) -> None:
    _write(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_disposable_identifier(value: str, kind: str) -> None:
    pattern = _IDENTIFIER_PATTERNS.get(kind)
    if pattern is None or pattern.fullmatch(value) is None:
        raise ProofError(f"Rejected non-disposable {kind} identifier")


def validate_loopback_hostname(hostname: str) -> None:
    if hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ProofError("Remote PostgreSQL hostnames are forbidden")


def validate_distinct_resources(
    source_container: str,
    target_container: str,
    source_database: str,
    target_database: str,
) -> None:
    if source_container == target_container or source_database == target_database:
        raise ProofError("Source and target resources must be distinct")


def parse_client_major(version_output: str) -> int:
    match = re.search(r"\b(\d+)(?:\.\d+)?\b", version_output)
    if match is None:
        raise ProofError("Unable to parse PostgreSQL client version")
    return int(match.group(1))


def parse_client_version(version_output: str) -> str:
    match = re.search(r"\b(\d+\.\d+)\b", version_output)
    if match is None:
        raise ProofError("Unable to parse exact PostgreSQL client version")
    return match.group(1)


def validate_client_versions(versions: dict[str, str]) -> None:
    for tool in ("pg_dump", "pg_restore", "psql"):
        if parse_client_major(versions.get(tool, "")) != 16:
            raise ProofError(f"{tool} major version must be 16")
        if parse_client_version(versions.get(tool, "")) != "16.13":
            raise ProofError(f"{tool} exact version must be 16.13")


def validate_manifest(manifest: object) -> dict[str, object]:
    if not isinstance(manifest, dict):
        raise ProofError("Backup manifest must be a JSON object")
    missing = sorted(_MANIFEST_KEYS - set(manifest))
    if missing:
        raise ProofError(f"Backup manifest is missing required keys: {', '.join(missing)}")
    if manifest.get("proof_status") not in {
        "PASS",
        "FAILED",
        "PENDING_RESTORE",
        "PENDING_CLEANUP",
    }:
        raise ProofError("Backup manifest has an invalid proof status")
    return manifest


def validate_artifact(path: Path, expected_sha256: str | None = None) -> str:
    if not path.is_file():
        raise ProofError("Backup artifact is missing")
    if path.stat().st_size <= 0:
        raise ProofError("Backup artifact is empty")
    checksum = _sha256(path)
    if expected_sha256 is not None and checksum != expected_sha256:
        raise ProofError("Backup artifact checksum mismatch")
    return checksum


def verify_expected_metadata(
    *,
    actual_revision: str,
    expected_revision: str,
    actual_fingerprint: str,
    expected_fingerprint: str,
    fixture_checksum: str,
    expected_fixture_checksum: str,
    actual_catalog: dict[str, list[dict[str, object]]] | None = None,
    expected_catalog: dict[str, list[dict[str, object]]] | None = None,
) -> None:
    if actual_revision != expected_revision:
        raise ProofError("Alembic revision mismatch")
    if actual_fingerprint != expected_fingerprint:
        message = (
            "Schema fingerprint mismatch: "
            f"source_fingerprint={expected_fingerprint}; "
            f"restored_fingerprint={actual_fingerprint}"
        )
        if actual_catalog is not None and expected_catalog is not None:
            difference = _first_schema_difference(expected_catalog, actual_catalog)
            if difference is not None:
                message += (
                    f"; object={difference.object_type}; path={difference.path}; "
                    f"source_value={difference.source_value}; "
                    f"restored_value={difference.restored_value}"
                )
        if len(message) > _SCHEMA_DIAGNOSTIC_MESSAGE_LIMIT:
            message = message[: _SCHEMA_DIAGNOSTIC_MESSAGE_LIMIT - 3] + "..."
        raise ProofError(message)
    if fixture_checksum != expected_fixture_checksum:
        raise ProofError("Fixture checksum mismatch")


def _safe_child_env(database_url: str) -> dict[str, str]:
    env = {key: os.environ[key] for key in _SAFE_ENV_KEYS if key in os.environ}
    env.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": database_url,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(NURA_APP_ROOT),
        }
    )
    return env


def _alembic(database_url: str, *arguments: str) -> CommandResult:
    return _run(
        [sys.executable, "-c", _ALEMBIC_LAUNCHER, *arguments],
        env=_safe_child_env(database_url),
        secrets_to_mask=(database_url,),
    )


def _database_url(
    username: str,
    password: str,
    database: str,
    port: int,
    application_name: str,
) -> str:
    validate_loopback_hostname("127.0.0.1")
    return (
        f"postgresql://{quote(username)}:{quote(password)}@127.0.0.1:{port}/"
        f"{quote(database)}?application_name={quote(application_name)}"
    )


def _connect(database_url: str) -> Any:
    global _PROOF_CONNECTION_COUNT
    connection = psycopg2.connect(database_url, connect_timeout=10)
    _PROOF_CONNECTION_COUNT += 1
    return connection


def _query(
    database_url: str,
    statement: str,
    parameters: tuple[object, ...] = (),
) -> tuple[list[str], list[tuple[object, ...]]]:
    try:
        with closing(_connect(database_url)) as connection:
            with connection.cursor() as cursor:
                if parameters:
                    cursor.execute(statement, parameters)
                else:
                    cursor.execute(statement)
                headers = [column.name for column in cursor.description] if cursor.description else []
                rows = cursor.fetchall() if cursor.description else []
        return headers, rows
    except Exception as exc:
        raise ProofError(_sanitize(str(exc), (database_url,))) from None


def _rows_as_dicts(
    database_url: str,
    statement: str,
    parameters: tuple[object, ...] = (),
) -> list[dict[str, object]]:
    headers, rows = _query(database_url, statement, parameters)
    return [dict(zip(headers, row, strict=True)) for row in rows]


def _canonical_value(value: object) -> object:
    if value is None:
        return {"type": "null"}
    if isinstance(value, datetime):
        normalized = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return {"type": "timestamp", "value": normalized.isoformat().replace("+00:00", "Z")}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": format(value, "f")}
    if isinstance(value, UUID):
        return {"type": "uuid", "value": str(value)}
    if isinstance(value, bytes):
        return {"type": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {
            "type": "json_object",
            "value": {str(key): _canonical_value(item) for key, item in sorted(value.items())},
        }
    if isinstance(value, (list, tuple)):
        return {"type": "json_array", "value": [_canonical_value(item) for item in value]}
    if isinstance(value, bool):
        return {"type": "boolean", "value": value}
    if isinstance(value, int):
        return {"type": "integer", "value": value}
    if isinstance(value, float):
        return {"type": "float", "value": repr(value)}
    return {"type": "text", "value": str(value)}


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _catalog_snapshot(database_url: str) -> dict[str, list[dict[str, object]]]:
    queries = {
        "tables": (
            "SELECT tablename AS table_name FROM pg_catalog.pg_tables "
            "WHERE schemaname='public' ORDER BY tablename"
        ),
        "columns": (
            "SELECT table_name, column_name, data_type, udt_name, "
            "is_nullable, column_default, is_identity, identity_generation, "
            "is_generated, generation_expression FROM information_schema.columns "
            "WHERE table_schema='public' ORDER BY table_name, ordinal_position"
        ),
        "constraints": (
            "SELECT c.conrelid::regclass::text AS table_name, c.conname, c.contype, "
            "c.condeferrable, c.condeferred, c.convalidated, "
            "pg_get_constraintdef(c.oid) AS definition FROM pg_catalog.pg_constraint c "
            "WHERE c.connamespace='public'::regnamespace ORDER BY 1, 2"
        ),
        "indexes": (
            "SELECT t.relname AS table_name, i.relname AS index_name, x.indisunique, "
            "x.indisprimary, x.indisvalid, x.indisready, pg_get_indexdef(i.oid) AS definition "
            "FROM pg_catalog.pg_index x JOIN pg_catalog.pg_class i ON i.oid=x.indexrelid "
            "JOIN pg_catalog.pg_class t ON t.oid=x.indrelid "
            "JOIN pg_catalog.pg_namespace n ON n.oid=t.relnamespace "
            "WHERE n.nspname='public' ORDER BY t.relname, i.relname"
        ),
        "sequences": (
            "SELECT sequencename AS sequence_name, data_type, start_value, min_value, "
            "max_value, increment_by, cycle, cache_size FROM pg_catalog.pg_sequences "
            "WHERE schemaname='public' ORDER BY sequencename"
        ),
        "views": (
            "SELECT viewname AS view_name, definition FROM pg_catalog.pg_views "
            "WHERE schemaname='public' ORDER BY viewname"
        ),
        "materialized_views": (
            "SELECT matviewname AS view_name, definition FROM pg_catalog.pg_matviews "
            "WHERE schemaname='public' ORDER BY matviewname"
        ),
        "functions": (
            "SELECT p.proname AS function_name, pg_get_function_identity_arguments(p.oid) AS arguments, "
            "pg_get_functiondef(p.oid) AS definition FROM pg_catalog.pg_proc p "
            "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' ORDER BY p.proname, arguments"
        ),
        "triggers": (
            "SELECT c.relname AS table_name, t.tgname AS trigger_name, "
            "pg_get_triggerdef(t.oid) AS definition FROM pg_catalog.pg_trigger t "
            "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY c.relname, t.tgname"
        ),
        "types": (
            "SELECT t.typname AS type_name, t.typtype AS type_kind, "
            "COALESCE(string_agg(e.enumlabel, ',' ORDER BY e.enumsortorder), '') AS enum_values "
            "FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace "
            "LEFT JOIN pg_catalog.pg_enum e ON e.enumtypid=t.oid "
            "WHERE n.nspname='public' AND t.typtype IN ('d','e') "
            "GROUP BY t.typname, t.typtype ORDER BY t.typname"
        ),
        "extensions": (
            "SELECT extname AS extension_name, extversion AS extension_version "
            "FROM pg_catalog.pg_extension ORDER BY extname"
        ),
    }
    return {name: _rows_as_dicts(database_url, statement) for name, statement in queries.items()}


def _canonical_check_expression(definition: object) -> object:
    """Normalize the one textual array-cast representation changed by pg_restore."""
    if not isinstance(definition, str):
        return definition
    normalized = _RESTORED_CHECK_ARRAY_LITERAL.sub(r"\1", definition)
    return _SOURCE_CHECK_ARRAY_CAST.sub(r"ARRAY[\1]", normalized)


def _canonical_partial_index_definition(definition: object) -> object:
    """Normalize only the predicate of a partial index, never its key expression."""
    if not isinstance(definition, str):
        return definition
    prefix, separator, predicate = definition.partition(" WHERE ")
    if not separator:
        return definition
    return prefix + separator + str(_canonical_check_expression(predicate))


def _catalog_for_comparison(
    catalog: dict[str, list[dict[str, object]]],
) -> dict[str, list[dict[str, object]]]:
    """Compare CHECK expressions without accepting semantic drift.

    ``pg_restore`` can render an equivalent CHECK expression with different
    array casts. The expression can occur in a CHECK constraint or a partial
    index predicate. Normalize only that known rendering delta; all other SQL
    expression content remains part of the schema fingerprint and comparison.
    """
    comparison: dict[str, list[dict[str, object]]] = {}
    for name, rows in catalog.items():
        comparison_rows: list[dict[str, object]] = []
        for row in rows:
            normalized = dict(row)
            is_check_constraint = (
                name == "constraints" and normalized.get("contype") == "c"
            )
            if is_check_constraint:
                normalized["definition"] = _canonical_check_expression(
                    normalized.get("definition")
                )
            elif name == "indexes":
                normalized["definition"] = _canonical_partial_index_definition(
                    normalized.get("definition")
                )
            comparison_rows.append(normalized)
        comparison[name] = comparison_rows
    return comparison


_CATALOG_KEY_FIELDS = {
    "tables": ("table_name",),
    "columns": ("table_name", "column_name"),
    "constraints": ("table_name", "conname"),
    "indexes": ("table_name", "index_name"),
    "sequences": ("sequence_name",),
    "views": ("view_name",),
    "materialized_views": ("view_name",),
    "functions": ("function_name", "arguments"),
    "triggers": ("table_name", "trigger_name"),
    "types": ("type_name",),
    "extensions": ("extension_name",),
}
_SCHEMA_DIAGNOSTIC_IDENTITY_LIMIT = 80
_SCHEMA_DIAGNOSTIC_MESSAGE_LIMIT = 1024


def _schema_value_summary(value: object) -> str:
    if value is None or isinstance(value, (bool, int, float)):
        return repr(value)
    canonical = _canonical_json(_canonical_value(value))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"<{type(value).__name__} length={len(canonical)} sha256={digest}>"


def _catalog_row_key(
    object_type: str, row: dict[str, object]
) -> tuple[tuple[str, str], ...]:
    fields = _CATALOG_KEY_FIELDS.get(object_type)
    if fields is None:
        return (("canonical_row", _canonical_json(row)),)
    return tuple((field, str(row.get(field))) for field in fields)


def _catalog_path(object_type: str, key: tuple[tuple[str, str], ...]) -> str:
    def safe_identity(value: str) -> str:
        sanitized = _sanitize(value).replace("\r", "\\r").replace("\n", "\\n")
        if len(sanitized) <= _SCHEMA_DIAGNOSTIC_IDENTITY_LIMIT:
            return sanitized
        digest = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()[:16]
        return f"<length={len(sanitized)} sha256={digest}>"

    identity = ",".join(f"{field}={safe_identity(value)}" for field, value in key)
    return f"{object_type}[{identity}]"


def _first_schema_difference(
    source_catalog: dict[str, list[dict[str, object]]],
    restored_catalog: dict[str, list[dict[str, object]]],
) -> SchemaDifference | None:
    source = _catalog_for_comparison(source_catalog)
    restored = _catalog_for_comparison(restored_catalog)
    for object_type in sorted(set(source) | set(restored)):
        source_rows = {
            _catalog_row_key(object_type, row): row for row in source.get(object_type, [])
        }
        restored_rows = {
            _catalog_row_key(object_type, row): row
            for row in restored.get(object_type, [])
        }
        for key in sorted(set(source_rows) | set(restored_rows)):
            path = _catalog_path(object_type, key)
            if key not in source_rows:
                return SchemaDifference(object_type, path, "<missing>", "<present>")
            if key not in restored_rows:
                return SchemaDifference(object_type, path, "<present>", "<missing>")
            source_row = source_rows[key]
            restored_row = restored_rows[key]
            for field in sorted(set(source_row) | set(restored_row)):
                source_value = source_row.get(field)
                restored_value = restored_row.get(field)
                if source_value != restored_value:
                    return SchemaDifference(
                        object_type,
                        f"{path}.{field}",
                        _schema_value_summary(source_value),
                        _schema_value_summary(restored_value),
                    )
    return None


def _schema_fingerprint(catalog: dict[str, list[dict[str, object]]]) -> str:
    comparison_catalog = _catalog_for_comparison(catalog)
    canonical = {
        name: [
            {key: _canonical_value(value) for key, value in sorted(row.items())}
            for row in rows
        ]
        for name, rows in sorted(comparison_catalog.items())
    }
    return hashlib.sha256(_canonical_json(canonical).encode("utf-8")).hexdigest()


def _table_snapshot(database_url: str) -> tuple[dict[str, int], dict[str, str]]:
    row_counts: dict[str, int] = {}
    checksums: dict[str, str] = {}
    with closing(_connect(database_url)) as connection:
        with connection.cursor() as cursor:
            for table_name in sorted(APPLICATION_TABLES):
                cursor.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                    (table_name,),
                )
                columns = [str(row[0]) for row in cursor.fetchall()]
                cursor.execute(
                    sql.SQL("SELECT {} FROM {}").format(
                        sql.SQL(", ").join(map(sql.Identifier, columns)),
                        sql.Identifier("public", table_name),
                    )
                )
                encoded_rows = [
                    _canonical_json(
                        {
                            "columns": columns,
                            "values": [_canonical_value(value) for value in row],
                        }
                    )
                    for row in cursor.fetchall()
                ]
                encoded_rows.sort()
                row_counts[table_name] = len(encoded_rows)
                checksums[table_name] = hashlib.sha256(
                    _canonical_json(encoded_rows).encode("utf-8")
                ).hexdigest()
    return row_counts, checksums


def _sequence_states(database_url: str) -> dict[str, dict[str, object]]:
    _, rows = _query(
        database_url,
        "SELECT sequencename FROM pg_catalog.pg_sequences "
        "WHERE schemaname='public' ORDER BY sequencename",
    )
    states: dict[str, dict[str, object]] = {}
    with closing(_connect(database_url)) as connection:
        with connection.cursor() as cursor:
            for (sequence_name,) in rows:
                cursor.execute(
                    sql.SQL("SELECT last_value, is_called FROM {}").format(
                        sql.Identifier("public", str(sequence_name))
                    )
                )
                last_value, is_called = cursor.fetchone()
                states[str(sequence_name)] = {
                    "last_value": int(last_value),
                    "is_called": bool(is_called),
                }
    return states


def _walk_named_values(name: str, value: object) -> list[tuple[str, object]]:
    if isinstance(value, dict):
        return [
            nested
            for key, item in value.items()
            for nested in _walk_named_values(str(key), item)
        ]
    if isinstance(value, (list, tuple)):
        return [
            nested for item in value for nested in _walk_named_values(name, item)
        ]
    return [(name, value)]


def _walk_values(value: object) -> list[object]:
    return [scalar for _name, scalar in _walk_named_values("", value)]


def _actual_value_hits(column: str, value: object) -> dict[str, int]:
    hits = {
        "unexpected_email_domain": 0,
        "phone_like_value": 0,
        "credential_or_private_key": 0,
        "production_marker_or_domain": 0,
        "non_synthetic_identifier": 0,
    }
    identifier_columns = {
        "celery_task_id",
        "guest_token",
        "idempotency_key",
        "payment_method_id",
        "provider_payment_id",
        "report_token",
        "token",
        "vk_id",
        "yookassa_id",
    }
    prohibited_credential_columns = {
        "access_token",
        "api_key",
        "client_secret",
        "password",
        "private_key",
        "secret",
        "secret_key",
        "session_token",
        "web_session_id",
    }
    for scalar_column, scalar in _walk_named_values(column, value):
        if scalar is None:
            continue
        if scalar_column in {"telegram_id", "referred_by"} and isinstance(scalar, int):
            hits["non_synthetic_identifier"] += int(scalar < 900000000000000000)
        if scalar_column in identifier_columns and isinstance(scalar, str):
            hits["non_synthetic_identifier"] += int(
                not scalar.lower().startswith("synthetic_")
            )
        normalized_column = scalar_column.lower()
        is_credential_name = (
            normalized_column in prohibited_credential_columns
            or normalized_column == "authorization"
            or normalized_column.endswith(("_secret", "_secret_key", "_api_key"))
            or normalized_column.endswith("_password")
        )
        if is_credential_name and scalar != "":
            hits["credential_or_private_key"] += 1
        if normalized_column.endswith("_token") and isinstance(scalar, str):
            hits["credential_or_private_key"] += int(
                not scalar.lower().startswith("synthetic_")
            )
        if not isinstance(scalar, str):
            continue
        for email in re.findall(
            r"(?i)\b[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@([a-z0-9.-]+\.[a-z]{2,})\b",
            scalar,
        ):
            hits["unexpected_email_domain"] += int(email.lower() != "example.invalid")
        if scalar_column == "phone" or (
            not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+Z-]+)?", scalar)
            and not re.fullmatch(
                r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                scalar,
            )
            and re.fullmatch(r"(?:\+\d[\d ()-]{8,}\d|\d[\d]*[ ()-][\d ()-]{7,}\d)", scalar)
        ):
            hits["phone_like_value"] += 1
        if re.search(
            r"(?i)(?:bearer\s+[a-z0-9._~-]{8,}|"
            r"(?:access|session)[_-]?token\s*[:=]\s*['\"]?[a-z0-9._~-]{8,}|"
            r"api[_-]?key\s*[:=]\s*['\"]?[a-z0-9_-]{8,}|"
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----)",
            scalar,
        ):
            hits["credential_or_private_key"] += 1
        if re.search(
            r"(?i)(?:production[_-](?:dump|database|host)|"
            r"protected[_-]production[_-](?:dump|database|host)|nura[_-]?prod)",
            scalar,
        ):
            hits["production_marker_or_domain"] += 1
        if re.search(
            r"(?i)\b(?:[a-z0-9-]+\.)*nura(?:-[a-z0-9-]+)?\.[a-z]{2,}\b",
            scalar,
        ):
            hits["production_marker_or_domain"] += 1
        for host in re.findall(r"(?i)https?://([^/:\s]+)", scalar):
            if "nura" in host.lower() and not host.lower().endswith("example.invalid"):
                hits["production_marker_or_domain"] += 1
    return hits


def _pii_guard(database_url: str) -> dict[str, object]:
    totals = {name: 0 for name in _actual_value_hits("", None)}
    hit_columns: set[str] = set()
    scanned_rows = 0
    scanned_scalar_values = 0
    with closing(_connect(database_url)) as connection:
        with connection.cursor() as cursor:
            for table_name in sorted(APPLICATION_TABLES):
                cursor.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                    (table_name,),
                )
                columns = [str(row[0]) for row in cursor.fetchall()]
                cursor.execute(
                    sql.SQL("SELECT {} FROM {}").format(
                        sql.SQL(", ").join(map(sql.Identifier, columns)),
                        sql.Identifier("public", table_name),
                    )
                )
                for row in cursor.fetchall():
                    scanned_rows += 1
                    for column, value in zip(columns, row, strict=True):
                        scanned_scalar_values += len(_walk_values(value))
                        for category, count in _actual_value_hits(column, value).items():
                            totals[category] += count
                            if count:
                                hit_columns.add(f"{table_name}.{column}:{category}")
    if any(totals.values()):
        failed = ", ".join(name for name, count in totals.items() if count)
        raise ProofError(
            f"Synthetic actual-value guard failed: {failed}; columns={','.join(sorted(hit_columns))}"
        )
    return {
        "status": "PASS",
        "scanned_tables": len(APPLICATION_TABLES),
        "scanned_rows": scanned_rows,
        "scanned_scalar_values": scanned_scalar_values,
        "category_hit_counts": totals,
    }


def _database_snapshot(database_url: str) -> DatabaseSnapshot:
    catalog = _catalog_snapshot(database_url)
    public_tables = {str(row["table_name"]) for row in catalog["tables"]}
    if public_tables != EXPECTED_PUBLIC_TABLES:
        raise ProofError("Unexpected or missing public application objects")
    invalid_constraints = [row for row in catalog["constraints"] if not row["convalidated"]]
    invalid_indexes = [
        row for row in catalog["indexes"] if not row["indisvalid"] or not row["indisready"]
    ]
    if invalid_constraints or invalid_indexes:
        raise ProofError("Invalid constraints or indexes detected")
    _, revision_rows = _query(
        database_url, "SELECT version_num FROM alembic_version ORDER BY version_num"
    )
    if len(revision_rows) != 1:
        raise ProofError("Database must contain exactly one Alembic revision")
    row_counts, checksums = _table_snapshot(database_url)
    _, size_rows = _query(database_url, "SELECT pg_database_size(current_database())")
    return DatabaseSnapshot(
        revision=str(revision_rows[0][0]),
        schema_fingerprint=_schema_fingerprint(catalog),
        catalog=catalog,
        catalog_counts={name: len(rows) for name, rows in catalog.items()},
        row_counts=row_counts,
        data_checksums=checksums,
        sequence_states=_sequence_states(database_url),
        logical_size_bytes=int(size_rows[0][0]),
        pii_guard=_pii_guard(database_url),
    )


def _empty_target_gate(database_url: str) -> dict[str, object]:
    _, rows = _query(
        database_url,
        "SELECT count(*) FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m','f')",
    )
    object_count = int(rows[0][0])
    _, schema_rows = _query(
        database_url,
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name NOT IN ('public','information_schema') "
        "AND schema_name NOT LIKE 'pg_%' ORDER BY schema_name",
    )
    if object_count != 0 or schema_rows:
        raise ProofError("Restore target is not empty")
    return {
        "status": "PASS",
        "public_object_count": object_count,
        "unexpected_user_schemas": [str(row[0]) for row in schema_rows],
        "alembic_version_present": False,
    }


def _quiescence_gate(database_url: str) -> dict[str, object]:
    rows = _rows_as_dicts(
        database_url,
        "SELECT pid, application_name, state, xact_start IS NOT NULL AS in_transaction "
        "FROM pg_stat_activity WHERE datname=current_database() "
        "AND backend_type='client backend' AND pid <> pg_backend_pid() ORDER BY pid",
    )
    if rows:
        raise ProofError("Unexpected application connection or transaction detected")
    _, snapshot_rows = _query(
        database_url,
        "SELECT txid_current_snapshot()::text, pg_current_wal_lsn()::text, "
        "current_setting('transaction_isolation'), current_setting('transaction_read_only')",
    )
    snapshot, wal_lsn, isolation, read_only = snapshot_rows[0]
    stats = _rows_as_dicts(
        database_url,
        "SELECT sessions, tup_inserted, tup_updated, tup_deleted, conflicts, deadlocks, "
        "temp_files, stats_reset FROM pg_catalog.pg_stat_database "
        "WHERE datname=current_database()",
    )[0]
    return {
        "status": "PASS",
        "active_other_connections": len(rows),
        "unexpected_connections": 0,
        "transaction_snapshot": str(snapshot),
        "wal_lsn": str(wal_lsn),
        "isolation": str(isolation),
        "read_only": str(read_only),
        "database_activity_counters": stats,
        "proof_connections_opened": _PROOF_CONNECTION_COUNT,
        "application_services_attached": False,
    }


def _validate_quiescence_interval(
    before: dict[str, object],
    after: dict[str, object],
    source_before: DatabaseSnapshot,
    source_after: DatabaseSnapshot,
    *,
    expected_dump_sessions: int,
) -> None:
    before_counters = dict(before["database_activity_counters"])
    after_counters = dict(after["database_activity_counters"])
    for counter in ("tup_inserted", "tup_updated", "tup_deleted", "conflicts", "deadlocks"):
        if before_counters.get(counter) != after_counters.get(counter):
            raise ProofError(f"Database activity changed during backup interval: {counter}")
    if before_counters.get("stats_reset") != after_counters.get("stats_reset"):
        raise ProofError("Database activity statistics reset during backup interval")
    expected_sessions = (
        int(after["proof_connections_opened"])
        - int(before["proof_connections_opened"])
        + expected_dump_sessions
    )
    actual_sessions = int(after_counters["sessions"]) - int(before_counters["sessions"])
    if actual_sessions != expected_sessions:
        raise ProofError("Unexpected completed session detected during backup interval")
    if (
        source_before.revision != source_after.revision
        or source_before.schema_fingerprint != source_after.schema_fingerprint
        or source_before.row_counts != source_after.row_counts
        or source_before.data_checksums != source_after.data_checksums
        or source_before.sequence_states != source_after.sequence_states
    ):
        raise ProofError("Source schema or data changed during backup interval")


def _wait_for_postgres(
    endpoint: DockerEndpoint,
    container: str,
    username: str,
    database: str,
    secrets_to_mask: tuple[str, ...],
) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        result = _docker(
            endpoint,
            ["exec", container, "pg_isready", "-U", username, "-d", database],
            check=False,
            timeout=10,
            secrets_to_mask=secrets_to_mask,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise ProofError("Disposable PostgreSQL readiness timed out")


def _mapped_port(endpoint: DockerEndpoint, container: str) -> int:
    output = _docker(endpoint, ["port", container, "5432/tcp"]).stdout.strip()
    match = re.search(r"127\.0\.0\.1:(\d+)", output)
    if match is None:
        raise ProofError("Disposable PostgreSQL loopback port is unavailable")
    return int(match.group(1))


def _docker_exec_pg(
    endpoint: DockerEndpoint,
    container: str,
    password: str,
    arguments: list[str],
    *,
    check: bool = True,
) -> CommandResult:
    return _docker(
        endpoint,
        ["exec", "-e", "PGPASSWORD", container, *arguments],
        check=check,
        env_values={"PGPASSWORD": password},
        secrets_to_mask=(password,),
    )


def _docker_image_metadata(
    endpoint: DockerEndpoint, *, pull_if_missing: bool
) -> tuple[str, str]:
    inspected = _docker(
        endpoint,
        ["image", "inspect", IMAGE, "--format", "{{json .RepoDigests}}"],
        check=False,
    )
    if inspected.returncode != 0:
        if not pull_if_missing:
            raise ProofError(f"Required exact image is not available locally: {IMAGE}")
        _docker(endpoint, ["pull", IMAGE], timeout=600)
        inspected = _docker(
            endpoint, ["image", "inspect", IMAGE, "--format", "{{json .RepoDigests}}"]
        )
    repo_digests = json.loads(inspected.stdout)
    if not repo_digests:
        raise ProofError("Exact PostgreSQL image has no repository digest")
    digest = str(repo_digests[0])
    if digest != EXPECTED_IMAGE_DIGEST:
        raise ProofError("PostgreSQL image digest is not the approved official digest")
    tags = json.loads(
        _docker(
            endpoint, ["image", "inspect", IMAGE, "--format", "{{json .RepoTags}}"]
        ).stdout
    )
    if IMAGE not in tags:
        raise ProofError("PostgreSQL image does not carry the exact approved tag")
    image_id = _docker(
        endpoint, ["image", "inspect", IMAGE, "--format", "{{.Id}}"]
    ).stdout.strip()
    return digest, image_id


def _encryption_proof(archive_path: Path, evidence_dir: Path) -> dict[str, object]:
    discovered: dict[str, str] = {}
    for tool in ("age", "rage", "gpg"):
        executable = shutil.which(tool)
        if executable:
            result = _run([executable, "--version"], check=False, timeout=30)
            discovered[tool] = (result.stdout or result.stderr).splitlines()[0]

    selected = ""
    keygen = ""
    for candidate, companion in (("age", "age-keygen"), ("rage", "rage-keygen")):
        if candidate in discovered and shutil.which(companion):
            selected = candidate
            keygen = companion
            break
    if not selected and "gpg" in discovered:
        selected = "gpg"
    if not selected:
        return {
            "status": "NOT EXECUTED — PRODUCTION TOOLING DECISION PENDING",
            "discovered_tools": discovered,
            "private_key_persisted": False,
        }

    encrypted_path = archive_path.with_suffix(archive_path.suffix + f".{selected}")
    with tempfile.TemporaryDirectory(prefix="nura-p5b-encryption-") as raw_temp:
        temp_dir = Path(raw_temp)
        _secure_path(temp_dir, directory=True)
        decrypted_path = temp_dir / "decrypted.dump"
        if selected in {"age", "rage"}:
            key_path = temp_dir / "identity.txt"
            _run([keygen, "-o", str(key_path)], timeout=60)
            _secure_path(key_path, directory=False)
            public_key = _run([keygen, "-y", str(key_path)], timeout=60).stdout.strip()
            if not public_key:
                raise ProofError("Encryption key generation returned no public key")
            _run(
                [selected, "-r", public_key, "-o", str(encrypted_path), str(archive_path)],
                timeout=120,
            )
            _run(
                [
                    selected,
                    "-d",
                    "-i",
                    str(key_path),
                    "-o",
                    str(decrypted_path),
                    str(encrypted_path),
                ],
                timeout=120,
            )
        else:
            passphrase = secrets.token_urlsafe(36)
            gpg_home = temp_dir / "gnupg"
            gpg_home.mkdir()
            _secure_path(gpg_home, directory=True)
            gpg_env = _command_env({"GNUPGHOME": str(gpg_home)})
            _run(
                [
                    "gpg",
                    "--homedir",
                    str(gpg_home),
                    "--batch",
                    "--yes",
                    "--pinentry-mode",
                    "loopback",
                    "--passphrase-fd",
                    "0",
                    "--symmetric",
                    "--cipher-algo",
                    "AES256",
                    "--force-mdc",
                    "--output",
                    str(encrypted_path),
                    str(archive_path),
                ],
                input_text=passphrase + "\n",
                env=gpg_env,
                secrets_to_mask=(passphrase,),
                timeout=120,
            )
            _run(
                [
                    "gpg",
                    "--homedir",
                    str(gpg_home),
                    "--batch",
                    "--yes",
                    "--pinentry-mode",
                    "loopback",
                    "--passphrase-fd",
                    "0",
                    "--decrypt",
                    "--output",
                    str(decrypted_path),
                    str(encrypted_path),
                ],
                input_text=passphrase + "\n",
                env=gpg_env,
                secrets_to_mask=(passphrase,),
                timeout=120,
            )
        _secure_path(encrypted_path, directory=False)
        _secure_path(decrypted_path, directory=False)
        if _sha256(decrypted_path) != _sha256(archive_path):
            raise ProofError("Encryption round-trip checksum mismatch")
    _verify_secure_path(encrypted_path, directory=False)
    return {
        "status": "PASS",
        "tool": selected,
        "version": discovered[selected],
        "encrypted_artifact": encrypted_path.name,
        "plaintext_sha256": _sha256(archive_path),
        "decrypted_sha256": _sha256(archive_path),
        "private_key_persisted": False,
        "integrity_protection": (
            "age authenticated encryption"
            if selected in {"age", "rage"}
            else "OpenPGP MDC plus decrypted SHA-256 verification"
        ),
    }


def _repository_heads() -> list[str]:
    result = _run(
        [sys.executable, "-c", _ALEMBIC_LAUNCHER, "heads"],
        env=_safe_child_env("postgresql://unused:unused@127.0.0.1:1/unused"),
    )
    heads = re.findall(r"^([0-9a-f]+) \(head\)$", result.stdout, flags=re.M)
    if len(heads) != 1:
        raise ProofError("Repository must have exactly one Alembic head")
    return heads


def _fixture_checksum(snapshot: DatabaseSnapshot) -> str:
    return hashlib.sha256(
        _canonical_json(
            {"row_counts": snapshot.row_counts, "data_checksums": snapshot.data_checksums}
        ).encode("utf-8")
    ).hexdigest()


def _compare_snapshots(
    source: DatabaseSnapshot,
    target: DatabaseSnapshot,
    repository_head: str,
) -> dict[str, object]:
    fixture_checksum = _fixture_checksum(target)
    verify_expected_metadata(
        actual_revision=target.revision,
        expected_revision=repository_head,
        actual_fingerprint=target.schema_fingerprint,
        expected_fingerprint=source.schema_fingerprint,
        fixture_checksum=fixture_checksum,
        expected_fixture_checksum=_fixture_checksum(source),
        actual_catalog=target.catalog,
        expected_catalog=source.catalog,
    )
    comparisons = {
        "revision": source.revision == target.revision == repository_head,
        "catalog": _catalog_for_comparison(source.catalog)
        == _catalog_for_comparison(target.catalog),
        "catalog_counts": source.catalog_counts == target.catalog_counts,
        "row_counts": source.row_counts == target.row_counts,
        "data_checksums": source.data_checksums == target.data_checksums,
        "sequence_states": source.sequence_states == target.sequence_states,
        "constraints_validated": all(
            bool(row["convalidated"]) for row in target.catalog["constraints"]
        ),
        "indexes_valid_and_ready": all(
            bool(row["indisvalid"]) and bool(row["indisready"])
            for row in target.catalog["indexes"]
        ),
        "pii_guard": target.pii_guard["status"] == "PASS",
    }
    if not all(comparisons.values()):
        failed = ", ".join(name for name, passed in comparisons.items() if not passed)
        raise ProofError(f"Restore verification failed: {failed}")
    return comparisons


def _run_fail_closed_matrix(
    *,
    docker_endpoint: DockerEndpoint,
    source_url: str,
    target_url: str,
    source_container: str,
    target_container: str,
    target_password: str,
    target_username: str,
    target_database: str,
    archive_path: Path,
    source_snapshot: DatabaseSnapshot,
) -> dict[str, str]:
    matrix: dict[str, str] = {}
    corrupted_path = archive_path.with_name("corrupted-not-evidence.dump")
    corrupted = bytearray(archive_path.read_bytes())
    corrupted[: min(16, len(corrupted))] = b"\x00" * min(16, len(corrupted))
    corrupted_path.write_bytes(corrupted)
    try:
        _docker(
            docker_endpoint,
            ["cp", str(corrupted_path), f"{target_container}:/tmp/corrupted.dump"],
        )
        result = _docker_exec_pg(
            docker_endpoint,
            target_container,
            target_password,
            ["pg_restore", "--list", "/tmp/corrupted.dump"],
            check=False,
        )
        if result.returncode == 0:
            raise ProofError("Corrupted archive was unexpectedly readable")
        matrix["corrupted_archive"] = "PASS (rejected)"
    finally:
        corrupted_path.unlink(missing_ok=True)
        _docker(
            docker_endpoint,
            ["exec", target_container, "rm", "-f", "/tmp/corrupted.dump"],
            check=False,
        )

    try:
        _empty_target_gate(source_url)
    except ProofError:
        matrix["non_empty_target"] = "PASS (rejected)"
    else:
        raise ProofError("Non-empty target gate did not reject source database")

    for label, database_url in (
        ("source_actual_value_guard", source_url),
        ("restored_actual_value_guard", target_url),
    ):
        with closing(_connect(database_url)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, ai_analysis FROM reports ORDER BY id LIMIT 1")
                report_id, original_analysis = cursor.fetchone()
                cursor.execute(
                    "UPDATE reports SET ai_analysis=%s WHERE id=%s",
                    (
                        json.dumps(
                            {
                                "nested": [
                                    {"marker": "protected_production_database_marker"}
                                ]
                            }
                        ),
                        report_id,
                    ),
                )
            connection.commit()
        try:
            _pii_guard(database_url)
        except ProofError:
            matrix[label] = "PASS (rejected nested marker)"
        else:
            raise ProofError(f"{label} did not reject a nested production marker")
        finally:
            with closing(_connect(database_url)) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE reports SET ai_analysis=%s WHERE id=%s",
                        (json.dumps(original_analysis), report_id),
                    )
                connection.commit()

    for label, database_url in (
        ("source_credential_guard", source_url),
        ("restored_credential_guard", target_url),
    ):
        with closing(_connect(database_url)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM users ORDER BY id LIMIT 1")
                user_id = cursor.fetchone()[0]
                cursor.execute(
                    "UPDATE users SET web_session_id=%s WHERE id=%s",
                    ("protected_session_value_0123456789", user_id),
                )
            connection.commit()
        try:
            _pii_guard(database_url)
        except ProofError:
            matrix[label] = "PASS (rejected credential field)"
        else:
            raise ProofError(f"{label} did not reject a session credential")
        finally:
            with closing(_connect(database_url)) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE users SET web_session_id=NULL WHERE id=%s", (user_id,)
                    )
                connection.commit()

    for label, database_url in (
        ("source_nested_credential_guard", source_url),
        ("restored_nested_credential_guard", target_url),
    ):
        with closing(_connect(database_url)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, ai_analysis FROM reports ORDER BY id LIMIT 1")
                report_id, original_analysis = cursor.fetchone()
                cursor.execute(
                    "UPDATE reports SET ai_analysis=%s WHERE id=%s",
                    (
                        json.dumps(
                            {
                                "nested": [
                                    {
                                        "refresh_token": "protected_refresh_value",
                                        "secret_key": "protected_secret_key_value",
                                    }
                                ]
                            }
                        ),
                        report_id,
                    ),
                )
            connection.commit()
        try:
            _pii_guard(database_url)
        except ProofError:
            matrix[label] = "PASS (rejected nested credential)"
        else:
            raise ProofError(f"{label} did not reject nested credentials")
        finally:
            with closing(_connect(database_url)) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE reports SET ai_analysis=%s WHERE id=%s",
                        (json.dumps(original_analysis), report_id),
                    )
                connection.commit()

    unexpected_url = re.sub(
        r"application_name=[^&]+", "application_name=unexpected_synthetic_client", source_url
    )
    unexpected_connection = _connect(unexpected_url)
    try:
        unexpected_connection.autocommit = False
        with unexpected_connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        try:
            _quiescence_gate(source_url)
        except ProofError:
            matrix["unexpected_application_transaction"] = "PASS (rejected)"
        else:
            raise ProofError("Unexpected application transaction was not rejected")
    finally:
        unexpected_connection.close()

    interval_before = _quiescence_gate(source_url)
    interval_snapshot_before = _database_snapshot(source_url)
    completed_guest = "20000000-0000-0000-0000-000000000098"
    with closing(_connect(source_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO guest_profiles (id, guest_token, created_at, expires_at) "
                "VALUES (%s, %s, %s, %s)",
                (
                    completed_guest,
                    "synthetic_completed_interval",
                    datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
                    datetime(2026, 2, 15, 12, 0, tzinfo=UTC),
                ),
            )
            cursor.execute("DELETE FROM guest_profiles WHERE id=%s", (completed_guest,))
        connection.commit()
    interval_snapshot_after = _database_snapshot(source_url)
    interval_after = _quiescence_gate(source_url)
    try:
        _validate_quiescence_interval(
            interval_before,
            interval_after,
            interval_snapshot_before,
            interval_snapshot_after,
            expected_dump_sessions=0,
        )
    except ProofError:
        matrix["completed_transaction_during_gate"] = "PASS (detected)"
    else:
        raise ProofError("Completed transaction during backup gate was not detected")

    read_only_before = _quiescence_gate(source_url)
    read_only_snapshot = _database_snapshot(source_url)
    with closing(psycopg2.connect(source_url, connect_timeout=10)) as read_only_connection:
        with read_only_connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        read_only_connection.commit()
    read_only_after = _quiescence_gate(source_url)
    try:
        _validate_quiescence_interval(
            read_only_before,
            read_only_after,
            read_only_snapshot,
            read_only_snapshot,
            expected_dump_sessions=0,
        )
    except ProofError:
        matrix["completed_read_only_session_during_gate"] = "PASS (detected)"
    else:
        raise ProofError("Completed read-only session during backup gate was not detected")

    collision_error = False
    try:
        validate_distinct_resources(
            source_container,
            source_container,
            "p5b_source_000000000000",
            "p5b_source_000000000000",
        )
    except ProofError:
        collision_error = True
    if not collision_error:
        raise ProofError("Target/source identity collision was not rejected")
    matrix["target_source_identity_collision"] = "PASS (rejected)"

    extra_guest = UUID("20000000-0000-0000-0000-000000000099")
    with closing(_connect(target_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO guest_profiles (id, guest_token, created_at, expires_at) "
                "VALUES (%s, %s, %s, %s)",
                (
                    str(extra_guest),
                    "synthetic_negative_row",
                    datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
                    datetime(2026, 2, 15, 12, 0, tzinfo=UTC),
                ),
            )
        connection.commit()
    mutated_counts, _ = _table_snapshot(target_url)
    if mutated_counts == source_snapshot.row_counts:
        raise ProofError("Restored row-count mismatch was not detected")
    matrix["restored_row_count_mismatch"] = "PASS (detected)"
    mutated_snapshot = _database_snapshot(target_url)
    try:
        _compare_snapshots(source_snapshot, mutated_snapshot, source_snapshot.revision)
    except ProofError:
        pass
    else:
        raise ProofError("Row-count mismatch did not fail the hard verifier")
    with closing(_connect(target_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM guest_profiles WHERE id=%s", (str(extra_guest),))
        connection.commit()

    with closing(_connect(target_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET name=%s WHERE id=%s",
                ("Synthetic Mutated", "10000000-0000-0000-0000-000000000001"),
            )
        connection.commit()
    _, mutated_checksums = _table_snapshot(target_url)
    if mutated_checksums == source_snapshot.data_checksums:
        raise ProofError("Restored deterministic checksum mismatch was not detected")
    matrix["restored_data_checksum_mismatch"] = "PASS (detected)"
    mutated_snapshot = _database_snapshot(target_url)
    try:
        _compare_snapshots(source_snapshot, mutated_snapshot, source_snapshot.revision)
    except ProofError:
        pass
    else:
        raise ProofError("Data-checksum mismatch did not fail the hard verifier")
    with closing(_connect(target_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET name=%s WHERE id=%s",
                ("Synthetic Aurora", "10000000-0000-0000-0000-000000000001"),
            )
        connection.commit()

    sequence_name, source_state = next(iter(source_snapshot.sequence_states.items()))
    with closing(_connect(target_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("SELECT setval(%s, %s, true)"),
                (f"public.{sequence_name}", int(source_state["last_value"]) + 1),
            )
        connection.commit()
    if _sequence_states(target_url) == source_snapshot.sequence_states:
        raise ProofError("Restored sequence mismatch was not detected")
    matrix["sequence_mismatch"] = "PASS (detected)"
    mutated_snapshot = _database_snapshot(target_url)
    try:
        _compare_snapshots(source_snapshot, mutated_snapshot, source_snapshot.revision)
    except ProofError:
        pass
    else:
        raise ProofError("Sequence mismatch did not fail the hard verifier")
    with closing(_connect(target_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT setval(%s, %s, %s)",
                (
                    f"public.{sequence_name}",
                    int(source_state["last_value"]),
                    bool(source_state["is_called"]),
                ),
            )
        connection.commit()

    matrix["clean_source_backup_restore"] = "PASS"
    return matrix


def _create_container(
    *,
    endpoint: DockerEndpoint,
    name: str,
    network: str,
    run_id: str,
    username: str,
    password: str,
    database: str,
) -> None:
    _docker(
        endpoint,
        [
            "run",
            "-d",
            "--name",
            name,
            "--label",
            f"nura.purpose={PURPOSE_LABEL}",
            "--label",
            f"nura.run_id={run_id}",
            "--network",
            network,
            "-e",
            "POSTGRES_USER",
            "-e",
            "POSTGRES_PASSWORD",
            "-e",
            "POSTGRES_DB",
            "-e",
            "POSTGRES_INITDB_ARGS",
            "-p",
            "127.0.0.1::5432",
            IMAGE,
        ],
        env_values={
            "POSTGRES_USER": username,
            "POSTGRES_PASSWORD": password,
            "POSTGRES_DB": database,
            "POSTGRES_INITDB_ARGS": "--encoding=UTF8 --locale=C.UTF-8",
        },
        secrets_to_mask=(username, password, database),
    )


def _write_sha256s(evidence_dir: Path) -> None:
    lines: list[str] = []
    for path in sorted(evidence_dir.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            relative = path.relative_to(evidence_dir).as_posix()
            lines.append(f"{_sha256(path)}  {relative}")
    _write(evidence_dir / "SHA256SUMS.txt", "\n".join(lines) + "\n")


def _scan_generated_evidence(
    evidence_dir: Path, *, ephemeral_secrets: tuple[str, ...]
) -> dict[str, object]:
    counts = {
        "known_ephemeral_secret": 0,
        "private_key_material": 0,
        "unredacted_database_dsn": 0,
    }
    files_scanned = 0
    for path in sorted(evidence_dir.rglob("*")):
        if not path.is_file():
            continue
        content = path.read_bytes()
        files_scanned += 1
        counts["known_ephemeral_secret"] += sum(
            content.count(secret.encode("utf-8")) for secret in ephemeral_secrets if secret
        )
        counts["private_key_material"] += len(
            re.findall(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----", content)
        )
        counts["unredacted_database_dsn"] += len(
            re.findall(rb"postgresql(?:\+[^:/]+)?://[^\s/@:]+:[^\s/@]+@", content)
        )
    if any(counts.values()):
        failed = ", ".join(name for name, count in counts.items() if count)
        raise ProofError(f"Generated evidence secret scan failed: {failed}")
    return {
        "status": "PASS",
        "files_scanned": files_scanned,
        "category_hit_counts": counts,
    }


def _cleanup_resources(
    endpoint: DockerEndpoint | None,
    run_id: str,
    containers: tuple[str, ...],
    network: str,
) -> dict[str, object]:
    if endpoint is None:
        return {
            "status": "PASS",
            "removed": [],
            "errors": [],
            "remaining_containers": [],
            "remaining_networks": [],
            "docker_endpoint_verified": False,
        }
    errors: list[str] = []
    removed: list[str] = []
    expected_labels = {
        "nura.purpose": PURPOSE_LABEL,
        "nura.run_id": run_id,
    }

    def inspect_labels(kind: str, name: str, template: str) -> dict[str, str] | None:
        try:
            result = _docker(
                endpoint,
                [kind, "inspect", name, "--format", template],
                check=False,
                timeout=30,
            )
        except Exception as exc:
            errors.append(f"inspect:{kind}:{name}:{_sanitize(str(exc))}")
            return None
        if result.returncode != 0:
            detail = (result.stdout + result.stderr).lower()
            if "no such" in detail or "not found" in detail:
                return None
            errors.append(f"inspect-failed:{kind}:{name}:exit-{result.returncode}")
            return None
        try:
            labels = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            errors.append(f"invalid-labels:{kind}:{name}")
            return None
        if not isinstance(labels, dict) or any(
            labels.get(key) != value for key, value in expected_labels.items()
        ):
            errors.append(f"label-mismatch:{kind}:{name}")
            return None
        return {str(key): str(value) for key, value in labels.items()}

    for container in reversed(containers):
        labels = inspect_labels("container", container, "{{json .Config.Labels}}")
        if labels is None:
            continue
        try:
            result = _docker(
                endpoint, ["rm", "-f", "-v", container], check=False, timeout=60
            )
            if result.returncode == 0:
                removed.append(container)
            else:
                errors.append(f"remove:container:{container}")
        except Exception as exc:
            errors.append(f"remove:container:{container}:{_sanitize(str(exc))}")

    labels = inspect_labels("network", network, "{{json .Labels}}")
    if labels is not None:
        try:
            result = _docker(
                endpoint, ["network", "rm", network], check=False, timeout=60
            )
            if result.returncode == 0:
                removed.append(network)
            else:
                errors.append(f"remove:network:{network}")
        except Exception as exc:
            errors.append(f"remove:network:{network}:{_sanitize(str(exc))}")

    remaining_containers: list[str] = []
    remaining_networks: list[str] = []
    try:
        result = _docker(
            endpoint,
            [
                "ps",
                "-a",
                "--filter",
                f"label=nura.run_id={run_id}",
                "--filter",
                f"label=nura.purpose={PURPOSE_LABEL}",
                "--format",
                "{{.Names}}",
            ],
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            errors.append(f"inspect:remaining-containers:exit-{result.returncode}")
        else:
            remaining_containers = result.stdout.splitlines()
    except Exception as exc:
        errors.append(f"inspect:remaining-containers:{_sanitize(str(exc))}")
    try:
        result = _docker(
            endpoint,
            [
                "network",
                "ls",
                "--filter",
                f"label=nura.run_id={run_id}",
                "--filter",
                f"label=nura.purpose={PURPOSE_LABEL}",
                "--format",
                "{{.Name}}",
            ],
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            errors.append(f"inspect:remaining-networks:exit-{result.returncode}")
        else:
            remaining_networks = result.stdout.splitlines()
    except Exception as exc:
        errors.append(f"inspect:remaining-networks:{_sanitize(str(exc))}")
    if remaining_containers or remaining_networks:
        errors.append("labeled resources remain")
    return {
        "status": "PASS" if not errors else "FAIL",
        "removed": removed,
        "errors": errors,
        "remaining_containers": remaining_containers,
        "remaining_networks": remaining_networks,
        "docker_endpoint_verified": True,
    }


def _initialize_evidence(evidence_dir: Path) -> None:
    if evidence_dir.exists() and any(evidence_dir.iterdir()):
        raise ProofError("Evidence directory already exists and is not empty")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _secure_path(evidence_dir, directory=True)
    artifacts = evidence_dir / "artifacts"
    artifacts.mkdir()
    _secure_path(artifacts, directory=True)
    for name in (
        "27_test_results.txt",
        "29_git_diff_and_allowlist.txt",
        "30_commit.txt",
        "31_draft_pr.txt",
        "32_remote_ci.txt",
        "33_final_report.md",
    ):
        _write(evidence_dir / name, "PENDING\n")


def _validate_repository_state(
    *,
    status: str,
    head: str,
    branch: str,
    remote: str,
    remote_is_ancestor: bool,
) -> RepositoryState:
    if status:
        raise ProofError("Repository worktree must be completely clean")
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ProofError("Current Git HEAD is not a valid commit SHA")
    if not branch:
        raise ProofError("Detached HEAD is not allowed for the proof runner")
    if not re.fullmatch(r"[0-9a-f]{40}", remote):
        raise ProofError("origin/main could not be resolved to a commit SHA")
    if branch == "main":
        if head != remote:
            raise ProofError("Local main must exactly match origin/main")
    elif not remote_is_ancestor:
        raise ProofError("Feature branch must contain the current origin/main commit")
    return RepositoryState(head, branch, remote, True)


def _read_repository_state() -> RepositoryState:
    status = _run(
        ["git", "status", "--short", "--untracked-files=all", "-z"], cwd=REPO_ROOT
    ).stdout
    head = _run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).stdout.strip()
    branch = _run(["git", "branch", "--show-current"], cwd=REPO_ROOT).stdout.strip()
    remote_result = _run(
        ["git", "ls-remote", "origin", "refs/heads/main"], cwd=REPO_ROOT
    ).stdout.split()
    remote = remote_result[0] if remote_result else ""
    remote_is_ancestor = branch == "main"
    if branch and branch != "main" and re.fullmatch(r"[0-9a-f]{40}", remote):
        remote_is_ancestor = (
            _run(
                ["git", "merge-base", "--is-ancestor", remote, head],
                check=False,
                cwd=REPO_ROOT,
            ).returncode
            == 0
        )
    return _validate_repository_state(
        status=status,
        head=head,
        branch=branch,
        remote=remote,
        remote_is_ancestor=remote_is_ancestor,
    )


def _assert_repository_binding(
    expected: RepositoryState, actual: RepositoryState
) -> None:
    if actual != expected:
        raise ProofError("Repository state drifted after the committed preflight")


def _assert_repository_unchanged(expected: RepositoryState) -> None:
    _assert_repository_binding(expected, _read_repository_state())


def _repository_preflight(evidence_dir: Path) -> RepositoryState:
    state = _read_repository_state()
    _write(
        evidence_dir / "00_preflight.txt",
        "result=PASS\n"
        f"current_git_sha={state.current_git_sha}\n"
        f"current_branch={state.current_branch}\n"
        f"remote_main_sha={state.remote_main_sha}\n"
        f"repository_clean={str(state.repository_clean).lower()}\n",
    )
    return state


def run_disposable_proof(
    evidence_dir: Path,
    *,
    pull_image_if_missing: bool = False,
    verify_repository: bool = True,
    run_fail_closed_checks: bool = True,
) -> ProofResult:
    evidence_dir = evidence_dir.resolve()
    if evidence_dir == REPO_ROOT or REPO_ROOT in evidence_dir.parents:
        raise ProofError("Evidence must be stored outside the repository")
    _initialize_evidence(evidence_dir)
    started_total = time.monotonic()
    suffix = secrets.token_hex(6)
    run_id = f"p5b_{suffix}"
    source_container = f"nura-p5b-source-{suffix}"
    target_container = f"nura-p5b-target-{suffix}"
    network = f"nura-p5b-network-{suffix}"
    source_database = f"p5b_source_{suffix}"
    target_database = f"p5b_target_{suffix}"
    source_username = f"p5b_source_user_{suffix}"
    target_username = f"p5b_target_user_{suffix}"
    source_password = secrets.token_urlsafe(32)
    target_password = secrets.token_urlsafe(32)
    secrets_to_mask = (
        source_username,
        target_username,
        source_password,
        target_password,
        source_database,
        target_database,
    )
    for value, kind in (
        (run_id, "run"),
        (source_container, "source_container"),
        (target_container, "target_container"),
        (network, "network"),
        (source_database, "source_database"),
        (target_database, "target_database"),
    ):
        validate_disposable_identifier(value, kind)
    validate_distinct_resources(
        source_container, target_container, source_database, target_database
    )

    repository = RepositoryState("TEST_BYPASS", "TEST_BYPASS", "TEST_BYPASS", False)
    docker_endpoint: DockerEndpoint | None = None
    cleanup: dict[str, object] = {"status": "PENDING", "removed": [], "errors": []}
    proof_result: ProofResult | None = None
    failure: Exception | None = None
    manifest_for_finalization: dict[str, object] | None = None
    pii_guard_for_finalization: dict[str, object] | None = None
    archive_path = evidence_dir / "artifacts" / f"{run_id}.dump"

    try:
        if verify_repository:
            repository = _repository_preflight(evidence_dir)
        else:
            _write(
                evidence_dir / "00_preflight.txt",
                "internal_test_only_bypass=true\nrepository_clean=false\nresult=PASS\n",
            )
        _write(
            evidence_dir / "01_owner_decisions.md",
            "# Owner decisions\n\n"
            "- Synthetic-only PostgreSQL 16 proof.\n"
            "- Custom archive (`pg_dump -Fc`), full database, no owner, no ACL.\n"
            "- Production encryption, custody, storage, retention, deletion, and RTO remain pending.\n"
            "- Synthetic timing does not establish production RTO.\n",
        )
        _write(
            evidence_dir / "02_worktree_and_branch.txt",
            f"worktree={REPO_ROOT}\ncurrent_branch={repository.current_branch}\n"
            f"run_id={run_id}\n",
        )
        _write(
            evidence_dir / "03_repository_baseline.txt",
            f"current_git_sha={repository.current_git_sha}\n"
            f"remote_main_sha={repository.remote_main_sha}\n"
            f"repository_clean={str(repository.repository_clean).lower()}\n",
        )
        docker_endpoint = _docker_endpoint_preflight(evidence_dir)
        environment = {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "docker_client": _docker(docker_endpoint, ["--version"]).stdout.strip(),
            "docker_server": _docker(
                docker_endpoint, ["info", "--format", "{{.ServerVersion}}"]
            ).stdout.strip(),
            "docker_context": docker_endpoint.context_name,
            "docker_endpoint_scheme": docker_endpoint.scheme,
            "docker_endpoint_redacted": docker_endpoint.redacted_endpoint,
            "docker_local_endpoint_verified": True,
        }
        _write_json(evidence_dir / "04_environment_versions.txt", environment)
        if verify_repository:
            _assert_repository_unchanged(repository)
        image_digest, image_id = _docker_image_metadata(
            docker_endpoint, pull_if_missing=pull_image_if_missing
        )
        _write_json(
            evidence_dir / "05_postgres_images_and_digests.txt",
            {"image": IMAGE, "repo_digest": image_digest, "image_id": image_id},
        )

        docker_started = time.monotonic()
        _docker(
            docker_endpoint,
            [
                "network",
                "create",
                "--label",
                f"nura.purpose={PURPOSE_LABEL}",
                "--label",
                f"nura.run_id={run_id}",
                network,
            ]
        )
        _create_container(
            endpoint=docker_endpoint,
            name=source_container,
            network=network,
            run_id=run_id,
            username=source_username,
            password=source_password,
            database=source_database,
        )
        _create_container(
            endpoint=docker_endpoint,
            name=target_container,
            network=network,
            run_id=run_id,
            username=target_username,
            password=target_password,
            database=target_database,
        )
        _wait_for_postgres(
            docker_endpoint,
            source_container,
            source_username,
            source_database,
            secrets_to_mask,
        )
        _wait_for_postgres(
            docker_endpoint,
            target_container,
            target_username,
            target_database,
            secrets_to_mask,
        )
        source_port = _mapped_port(docker_endpoint, source_container)
        target_port = _mapped_port(docker_endpoint, target_container)
        source_url = _database_url(
            source_username,
            source_password,
            source_database,
            source_port,
            f"nura_p5b_source_{suffix}",
        )
        target_url = _database_url(
            target_username,
            target_password,
            target_database,
            target_port,
            f"nura_p5b_target_{suffix}",
        )
        docker_startup_seconds = time.monotonic() - docker_started
        _write_json(
            evidence_dir / "06_source_creation.txt",
            {
                "status": "PASS",
                "source_container": source_container,
                "target_container": target_container,
                "network": network,
                "source_database": source_database,
                "target_database": target_database,
                "encoding": "UTF8",
                "locale": "C.UTF-8",
                "labels": {
                    "nura.purpose": PURPOSE_LABEL,
                    "nura.run_id": run_id,
                },
            },
        )

        client_versions = {
            tool: _docker(
                docker_endpoint, ["exec", source_container, tool, "--version"]
            ).stdout.strip()
            for tool in ("pg_dump", "pg_restore", "psql")
        }
        validate_client_versions(client_versions)
        _, early_version_rows = _query(
            source_url,
            "SELECT current_setting('server_version_num'), "
            "current_setting('server_version'), version()",
        )
        server_version_num, exact_server_version, version_text_early = early_version_rows[0]
        if str(server_version_num) != "160013" or "PostgreSQL 16.13" not in str(version_text_early):
            raise ProofError("PostgreSQL server exact version must be 16.13")
        if verify_repository:
            _assert_repository_unchanged(repository)
        repository_heads = _repository_heads()
        migration = _alembic(source_url, "upgrade", "head")
        if migration.returncode != 0:
            raise ProofError("Normal Alembic upgrade head failed")
        repository_head = repository_heads[0]
        _, revision_rows = _query(source_url, "SELECT version_num FROM alembic_version")
        source_revision = str(revision_rows[0][0])
        if source_revision != repository_head:
            raise ProofError("Source Alembic revision does not match repository head")
        _write_json(
            evidence_dir / "07_alembic_upgrade.txt",
            {
                "status": "PASS",
                "command": "alembic upgrade head",
                "repository_heads": repository_heads,
                "database_revision": source_revision,
                "duration_seconds": migration.duration_seconds,
            },
        )

        with closing(_connect(source_url)) as connection:
            insert_synthetic_fixtures(connection)
        fixtures = fixture_manifest()
        _write_json(evidence_dir / "08_fixture_manifest.json", fixtures)
        source_snapshot = _database_snapshot(source_url)
        if source_snapshot.row_counts != EXPECTED_ROW_COUNTS:
            raise ProofError("Synthetic fixture row counts do not match the fixture contract")
        _write_json(evidence_dir / "09_source_verification.json", asdict(source_snapshot))

        quiescence_before = _quiescence_gate(source_url)
        backup_started = time.monotonic()
        container_archive = f"/tmp/{run_id}.dump"
        backup_command = [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-acl",
            f"--file={container_archive}",
            "--username",
            source_username,
            source_database,
        ]
        _docker_exec_pg(docker_endpoint, source_container, source_password, backup_command)
        _docker(
            docker_endpoint,
            ["cp", f"{source_container}:{container_archive}", str(archive_path)],
        )
        _secure_path(archive_path, directory=False)
        _docker(
            docker_endpoint,
            ["exec", source_container, "rm", "-f", container_archive],
            check=False,
        )
        backup_seconds = time.monotonic() - backup_started
        source_after_dump = _database_snapshot(source_url)
        quiescence_after = _quiescence_gate(source_url)
        _validate_quiescence_interval(
            quiescence_before,
            quiescence_after,
            source_snapshot,
            source_after_dump,
            expected_dump_sessions=1,
        )
        _write_json(
            evidence_dir / "10_quiescence_gate.json",
            {"before": quiescence_before, "after": quiescence_after, "status": "PASS"},
        )
        _write(
            evidence_dir / "11_backup_command_redacted.txt",
            "pg_dump --format=custom --no-owner --no-acl "
            "--file=<external-synthetic-artifact> <synthetic-source-database>\n",
        )
        archive_sha = validate_artifact(archive_path)
        archive_size = archive_path.stat().st_size
        _verify_secure_path(archive_path, directory=False)
        _docker(
            docker_endpoint,
            ["cp", str(archive_path), f"{target_container}:/tmp/{run_id}.dump"],
        )
        catalog_result = _docker_exec_pg(
            docker_endpoint,
            target_container,
            target_password,
            ["pg_restore", "--list", f"/tmp/{run_id}.dump"],
        )
        if not catalog_result.stdout.strip():
            raise ProofError("Archive catalog is empty")
        _write(evidence_dir / "13_archive_catalog.txt", catalog_result.stdout)
        _write(
            evidence_dir / "14_archive_checksum.txt",
            f"sha256={archive_sha}\nsize_bytes={archive_size}\nstatus=PASS\n",
        )
        encryption = _encryption_proof(archive_path, evidence_dir)
        _write_json(evidence_dir / "15_encryption_proof.md", encryption)

        target_gate = _empty_target_gate(target_url)
        _write_json(evidence_dir / "16_target_empty_gate.json", target_gate)
        restore_command = [
            "pg_restore",
            "--exit-on-error",
            "--no-owner",
            "--no-acl",
            "--username",
            target_username,
            "--dbname",
            target_database,
            f"/tmp/{run_id}.dump",
        ]
        _write(
            evidence_dir / "17_restore_command_redacted.txt",
            "pg_restore --exit-on-error --no-owner --no-acl "
            "--dbname=<empty-synthetic-target> <synthetic-artifact>\n",
        )
        restore_started = time.monotonic()
        restore_result = _docker_exec_pg(
            docker_endpoint, target_container, target_password, restore_command
        )
        restore_seconds = time.monotonic() - restore_started
        if restore_result.returncode != 0:
            raise ProofError("Restore exit code was non-zero")

        verify_started = time.monotonic()
        target_snapshot = _database_snapshot(target_url)
        _write_json(
            evidence_dir / "18_restore_verification.json",
            {
                "status": "PENDING_COMPARISON",
                "source": asdict(source_snapshot),
                "target": asdict(target_snapshot),
            },
        )
        comparisons = _compare_snapshots(source_snapshot, target_snapshot, repository_head)
        fail_closed_matrix = (
            _run_fail_closed_matrix(
                docker_endpoint=docker_endpoint,
                source_url=source_url,
                target_url=target_url,
                source_container=source_container,
                target_container=target_container,
                target_password=target_password,
                target_username=target_username,
                target_database=target_database,
                archive_path=archive_path,
                source_snapshot=source_snapshot,
            )
            if run_fail_closed_checks
            else {"clean_source_backup_restore": "PASS"}
        )
        final_target_snapshot = _database_snapshot(target_url)
        _compare_snapshots(source_snapshot, final_target_snapshot, repository_head)
        verification_seconds = time.monotonic() - verify_started
        total_seconds = time.monotonic() - started_total
        if restore_seconds > RESTORE_CEILING_SECONDS:
            raise ProofError("Restore duration exceeded the rehearsal ceiling")
        if verification_seconds > VERIFY_CEILING_SECONDS:
            raise ProofError("Verification duration exceeded the rehearsal ceiling")
        if total_seconds > TOTAL_CEILING_SECONDS:
            raise ProofError("Total duration exceeded the rehearsal ceiling")

        _, version_rows = _query(
            source_url,
            "SELECT version(), current_setting('server_version'), "
            "current_setting('server_encoding'), d.datcollate, d.datctype "
            "FROM pg_catalog.pg_database d WHERE d.datname=current_database()",
        )
        version_text, server_version, encoding, collation, ctype = version_rows[0]
        throughput: dict[str, float | int] = {
            "source_logical_size_bytes": source_snapshot.logical_size_bytes,
            "archive_size_bytes": archive_size,
            "total_row_count": sum(source_snapshot.row_counts.values()),
            "object_count": sum(source_snapshot.catalog_counts.values()),
            "backup_mb_per_second": round(
                archive_size / (1024 * 1024) / max(backup_seconds, 0.000001), 6
            ),
            "restore_mb_per_second": round(
                archive_size / (1024 * 1024) / max(restore_seconds, 0.000001), 6
            ),
            "verification_rows_per_second": round(
                sum(source_snapshot.row_counts.values())
                / max(verification_seconds, 0.000001),
                6,
            ),
            "fixed_startup_overhead_seconds": round(
                total_seconds - backup_seconds - restore_seconds - verification_seconds, 6
            ),
            "docker_startup_seconds": round(docker_startup_seconds, 6),
        }
        timings = {
            "backup_seconds": round(backup_seconds, 6),
            "restore_seconds": round(restore_seconds, 6),
            "verification_seconds": round(verification_seconds, 6),
            "total_seconds": round(total_seconds, 6),
            "restore_ceiling_seconds": RESTORE_CEILING_SECONDS,
            "verification_ceiling_seconds": VERIFY_CEILING_SECONDS,
            "total_ceiling_seconds": TOTAL_CEILING_SECONDS,
        }
        manifest = {
            "run_id": run_id,
            "timestamps_utc": {
                "completed": datetime.now(UTC).isoformat().replace("+00:00", "Z")
            },
            "current_git_sha": repository.current_git_sha,
            "current_branch": repository.current_branch,
            "remote_main_sha": repository.remote_main_sha,
            "repository_clean": repository.repository_clean,
            "postgresql_server_version": str(server_version),
            "postgresql_version_text": str(version_text),
            "encoding": str(encoding),
            "collation": str(collation),
            "ctype": str(ctype),
            "pg_dump_version": client_versions["pg_dump"],
            "pg_restore_version": client_versions["pg_restore"],
            "psql_version": client_versions["psql"],
            "image_digest": image_digest,
            "source_database": source_database,
            "target_database": target_database,
            "alembic_revision": source_snapshot.revision,
            "source_schema_fingerprint": source_snapshot.schema_fingerprint,
            "archive_filename": archive_path.name,
            "archive_size_bytes": archive_size,
            "archive_sha256": archive_sha,
            "fixture_manifest_sha256": fixtures["manifest_sha256"],
            "fixture_data_sha256": _fixture_checksum(source_snapshot),
            "catalog_counts": source_snapshot.catalog_counts,
            "row_counts": source_snapshot.row_counts,
            "object_inventory_summary": source_snapshot.catalog_counts,
            "backup_duration_seconds": backup_seconds,
            "encryption_status": encryption["status"],
            "proof_status": "PENDING_CLEANUP",
        }
        validate_manifest(manifest)
        manifest_for_finalization = manifest
        _write_json(evidence_dir / "12_backup_manifest.json", manifest)
        _write_json(
            evidence_dir / "18_restore_verification.json",
            {
                "status": "PASS",
                "source_revision": source_snapshot.revision,
                "target_revision": final_target_snapshot.revision,
                "repository_head": repository_head,
                "source_fingerprint": source_snapshot.schema_fingerprint,
                "target_fingerprint": final_target_snapshot.schema_fingerprint,
                "comparisons": comparisons,
            },
        )
        _write_json(
            evidence_dir / "19_catalog_comparison.json",
            {
                "status": "PASS",
                "source_counts": source_snapshot.catalog_counts,
                "target_counts": final_target_snapshot.catalog_counts,
                "equal": source_snapshot.catalog == final_target_snapshot.catalog,
            },
        )
        _write_json(
            evidence_dir / "20_row_counts.json",
            {
                "status": "PASS",
                "source": source_snapshot.row_counts,
                "target": final_target_snapshot.row_counts,
            },
        )
        _write_json(
            evidence_dir / "21_data_checksums.json",
            {
                "status": "PASS",
                "source": source_snapshot.data_checksums,
                "target": final_target_snapshot.data_checksums,
            },
        )
        _write_json(
            evidence_dir / "22_sequences.json",
            {
                "status": "PASS",
                "source": source_snapshot.sequence_states,
                "target": final_target_snapshot.sequence_states,
            },
        )
        _write_json(
            evidence_dir / "23_constraints_indexes_objects.json",
            {
                "status": "PASS",
                "constraints_validated": comparisons["constraints_validated"],
                "indexes_valid_and_ready": comparisons["indexes_valid_and_ready"],
                "catalog_equal": comparisons["catalog"],
                "object_counts": final_target_snapshot.catalog_counts,
            },
        )
        _write_json(
            evidence_dir / "25_timings_and_throughput.json",
            {
                "status": "PASS",
                "timings": timings,
                "throughput": throughput,
                "statement": "Synthetic P5B timing does not establish production RTO.",
            },
        )
        _write(
            evidence_dir / "26_fail_closed_matrix.md",
            "# Fail-closed integration matrix\n\n"
            + "\n".join(f"- {name}: {status}" for name, status in fail_closed_matrix.items())
            + "\n",
        )
        _write(
            evidence_dir / "33_final_report.md",
            "# P5B disposable proof\n\n"
            "Core logical backup/restore proof: PENDING CLEANUP.\n\n"
            f"Encryption capability: {encryption['status']}.\n\n"
            "Synthetic P5B timing does not establish production RTO.\n",
        )
        if verify_repository:
            _assert_repository_unchanged(repository)
        evidence_secret_scan = _scan_generated_evidence(
            evidence_dir, ephemeral_secrets=(source_password, target_password)
        )
        pii_guard_for_finalization = {
            "status": "PASS",
            "source_actual_values": source_snapshot.pii_guard,
            "restored_actual_values": final_target_snapshot.pii_guard,
            "generated_evidence": evidence_secret_scan,
        }
        _write_json(evidence_dir / "24_pii_guard.json", pii_guard_for_finalization)
        proof_result = ProofResult(
            run_id=run_id,
            evidence_dir=str(evidence_dir),
            archive_path=str(archive_path),
            archive_sha256=archive_sha,
            archive_size_bytes=archive_size,
            source_revision=source_snapshot.revision,
            restored_revision=final_target_snapshot.revision,
            source_fingerprint=source_snapshot.schema_fingerprint,
            restored_fingerprint=final_target_snapshot.schema_fingerprint,
            image_digest=image_digest,
            server_version=str(server_version),
            client_versions=client_versions,
            timings=timings,
            throughput=throughput,
            fail_closed_matrix=fail_closed_matrix,
            cleanup=cleanup,
        )
    except Exception as exc:
        failure = exc
        _write(
            evidence_dir / "33_final_report.md",
            f"# P5B disposable proof\n\nFAILED: {_sanitize(str(exc), secrets_to_mask)}\n",
        )
    finally:
        cleanup = _cleanup_resources(
            docker_endpoint, run_id, (source_container, target_container), network
        )
        _write_json(evidence_dir / "28_cleanup.txt", cleanup)
        if failure is None and pii_guard_for_finalization is not None:
            try:
                if verify_repository:
                    _assert_repository_unchanged(repository)
                pii_guard_for_finalization["generated_evidence"] = (
                    _scan_generated_evidence(
                        evidence_dir,
                        ephemeral_secrets=(source_password, target_password),
                    )
                )
                _write_json(
                    evidence_dir / "24_pii_guard.json", pii_guard_for_finalization
                )
            except Exception as exc:
                failure = exc
        final_pass = cleanup["status"] == "PASS" and failure is None
        if manifest_for_finalization is not None:
            manifest_for_finalization["proof_status"] = "PASS" if final_pass else "FAILED"
            manifest_for_finalization["cleanup_status"] = cleanup["status"]
            _write_json(
                evidence_dir / "12_backup_manifest.json", manifest_for_finalization
            )
        if final_pass:
            _write(
                evidence_dir / "33_final_report.md",
                "# P5B disposable proof\n\n"
                "Core logical backup/restore proof: PASS.\n\n"
                f"Encryption capability: {manifest_for_finalization['encryption_status']}.\n\n"
                "Synthetic P5B timing does not establish production RTO.\n",
            )
        else:
            detail = _sanitize(str(failure), secrets_to_mask) if failure else "cleanup failed"
            _write(
                evidence_dir / "33_final_report.md",
                f"# P5B disposable proof\n\nFAILED: {detail}\n"
                f"\nCleanup status: {cleanup['status']}\n",
            )
        _write_sha256s(evidence_dir)

    if cleanup["status"] != "PASS":
        raise ProofError("Disposable resource cleanup failed")
    if failure is not None:
        if isinstance(failure, ProofError):
            raise failure
        raise ProofError(_sanitize(str(failure), secrets_to_mask)) from failure
    if proof_result is None:
        raise ProofError("Proof ended without a structured result")
    return ProofResult(**{**asdict(proof_result), "cleanup": cleanup})


def _parse_args(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a synthetic-only disposable PostgreSQL 16 backup/restore proof. "
            "This is not a production backup executor."
        )
    )
    parser.add_argument(
        "--synthetic-disposable-proof",
        action="store_true",
        help="Required acknowledgement that only disposable synthetic resources may be used.",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
        help="New or empty external directory for synthetic proof evidence.",
    )
    parser.add_argument(
        "--pull-image-if-missing",
        action="store_true",
        help=f"Allow pulling only the official exact image {IMAGE} when absent.",
    )
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    args = _parse_args(arguments)
    if not args.synthetic_disposable_proof:
        print(
            "FATAL: --synthetic-disposable-proof acknowledgement is required",
            file=sys.stderr,
        )
        return 2
    try:
        result = run_disposable_proof(
            args.evidence_dir,
            pull_image_if_missing=args.pull_image_if_missing,
        )
    except ProofError as exc:
        print(f"P5B PROOF FAILED: {_sanitize(str(exc))}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
