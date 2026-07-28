"""Test-only run-scoped artifacts for Telegram-first security acceptance.

The helper never receives real credentials.  Its registry is deliberately
ephemeral; only a scrubbed summary is copied outside the run directory.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


CONTEXT_ENV = "NURA_SECURITY_RUN_CONTEXT"
ROLE_ENV = "NURA_SECURITY_PROCESS_ROLE"
_ALIASES = (
    "telegram_token", "yookassa_shop_id", "yookassa_secret", "ai_api_key",
    "sentry_dsn_secret_fragment", "database_password", "redis_password",
    "receipt_email", "birth_date_marker", "telegram_identity_marker",
    "checkout_capability", "webhook_event_marker", "provider_payment_marker",
    "report_content_marker", "pdf_content_marker", "internal_support_marker",
)
_COUNTERS = (
    "non_loopback_connection_attempts", "blocked_connection_attempts",
    "telegram_external_attempts", "yookassa_external_attempts", "ai_external_attempts",
    "sentry_external_attempts", "email_external_attempts", "analytics_external_attempts",
    "support_external_attempts", "local_fake_http_calls", "postgres_connection_attempts",
    "redis_connection_attempts",
)
_SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,95}$")
_GENERIC_FORBIDDEN_PATTERNS = {
    "authorization_header": re.compile(rb"(?i)authorization\s*[:=]\s*[^\s,;}]+"),
    "cookie_header": re.compile(rb"(?i)cookie\s*[:=]\s*[^\r\n]+"),
    "database_url": re.compile(rb"(?i)postgres(?:ql)?(?:\+asyncpg)?://[^\s\"']+"),
    "redis_url": re.compile(rb"(?i)redis://[^\s\"']+"),
}
_ARTIFACT_REQUIREMENTS = {
    "uvicorn-stdout": ("logs/uvicorn-cycle-*.stdout.log", False),
    "uvicorn-stderr": ("logs/uvicorn-cycle-*.stderr.log", False),
    "uvicorn-access": ("logs/uvicorn-checkout-access.log", True),
    "fastapi-application": ("logs/fallback-rendering-warning.log", True),
    "telegram-stdout": ("logs/telegram-cycle-*.stdout.log", False),
    "telegram-stderr": ("logs/telegram-cycle-*.stderr.log", False),
    "telegram-runtime": ("logs/telegram-cycle-*.stdout.log", True),
    "aiogram-error": ("logs/security-acceptance-cycle-*.application.log", True),
    "celery-worker-stdout": ("logs/celery-worker-cycle-*.stdout.log", False),
    "celery-worker-stderr": ("logs/celery-worker-cycle-*.stderr.log", False),
    "celery-worker": ("logs/celery-worker-cycle-*.*.log", True),
    "celery-beat-stdout": ("logs/celery-beat-cycle-*.stdout.log", False),
    "celery-beat-stderr": ("logs/celery-beat-cycle-*.stderr.log", False),
    "celery-beat": ("logs/celery-beat-cycle-*.*.log", True),
    "payment-webhook": ("responses/webhook-rejections.json", True),
    "generation-failure": ("logs/security-contract-generation-delivery-*.stdout.log", True),
    "delivery-failure": ("logs/security-contract-generation-delivery-*.stdout.log", True),
    "refund-deletion": ("logs/security-contract-refund-account-deletion-*.stdout.log", True),
    "fallback-rendering": ("logs/fallback-rendering-warning.log", True),
    "sentry-probe": ("summaries/sentry-proof.json", True),
    "sentry-envelope": ("sentry/envelope-*.bin", True),
    "security-events": ("events/*.jsonl", True),
    "runner-summary": ("summaries/security-matrix.json", True),
    "cleanup-summary": ("summaries/error-path-proofs.jsonl", True),
    "http-response": ("responses/*", True),
}


def _safe_token(alias: str, run_id: str) -> str:
    # Some production capability columns are VARCHAR(64), so the synthetic
    # value must remain a valid boundary input as well as be run-unique.
    return f"nura-{alias[:12]}-{run_id[:8]}-{secrets.token_urlsafe(12)}"


def _endpoint(url: str) -> dict[str, Any]:
    parts = urlsplit(url)
    return {"host": parts.hostname or "", "port": parts.port or (443 if parts.scheme == "https" else 80)}


@dataclass(frozen=True)
class SecurityContext:
    path: Path
    run_id: str
    registry: dict[str, str]

    @classmethod
    def create(cls, env: dict[str, str]) -> "SecurityContext":
        run_id = uuid.uuid4().hex
        path = Path(tempfile.mkdtemp(prefix=f"nura-security-{run_id}-"))
        for name in ("events", "logs", "responses", "sentry", "summaries"):
            (path / name).mkdir()
        registry = {alias: _safe_token(alias, run_id) for alias in _ALIASES}
        registry["telegram_token"] = "123456:" + _safe_token("telegram", run_id)
        registry["sentry_dsn_secret_fragment"] = secrets.token_hex(16)
        registry["receipt_email"] = f"security-{run_id[:12]}@example.test"
        allowlist = {"loopback": True, "endpoints": []}
        for key, category in (("DATABASE_URL", "postgres"), ("REDIS_URL", "redis")):
            if env.get(key):
                endpoint = _endpoint(env[key])
                endpoint["category"] = category
                allowlist["endpoints"].append(endpoint)
        (path / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
        (path / "allowlist.json").write_text(json.dumps(allowlist), encoding="utf-8")
        return cls(path, run_id, registry)

    def child_environment(self, env: dict[str, str], *, role: str = "security-runner") -> dict[str, str]:
        child = env.copy()
        child[CONTEXT_ENV] = str(self.path)
        child[ROLE_ENV] = role
        tools_path = str(Path(__file__).resolve().parent)
        child["PYTHONPATH"] = tools_path + os.pathsep + child.get("PYTHONPATH", "")
        return child

    def add_endpoint(self, host: str, port: int, category: str) -> None:
        allowlist_path = self.path / "allowlist.json"
        allowlist = json.loads(allowlist_path.read_text(encoding="utf-8"))
        allowlist["endpoints"].append({"host": host, "port": port, "category": category})
        allowlist_path.write_text(json.dumps(allowlist), encoding="utf-8")

    def write_matrix(self, rows: list[dict[str, Any]]) -> None:
        """Persist only bounded matrix metadata after every referenced probe passed."""
        required = {
            "asset", "threat", "production_control", "probe", "result",
            "severity", "disposition", "sinks",
        }
        for row in rows:
            if set(row) != required or row["result"] != "PASS":
                raise RuntimeError("security_matrix_invalid_row")
            for key in ("asset", "threat", "production_control", "probe"):
                if not isinstance(row[key], str) or len(row[key]) > 240:
                    raise RuntimeError("security_matrix_unbounded_field")
            if row["severity"] not in {"P0", "P1", "P2", "P3"}:
                raise RuntimeError("security_matrix_invalid_severity")
            if row["disposition"] not in {
                "FIXED", "SUFFICIENT", "ACCEPTED_LIMITATION", "EXTERNAL_GATE", "OUT_OF_SCOPE"
            }:
                raise RuntimeError("security_matrix_invalid_disposition")
            if not isinstance(row["sinks"], list) or not row["sinks"]:
                raise RuntimeError("security_matrix_missing_sink")
        (self.path / "summaries" / "security-matrix.json").write_text(
            json.dumps({"run_id": self.run_id, "rows": rows}, sort_keys=True),
            encoding="utf-8",
        )

    def record_proof(self, scenario: str, *sinks: str) -> None:
        """Record a proof only after its production-boundary assertions passed."""
        values = (scenario, *sinks)
        if not sinks or any(not _SAFE_NAME.fullmatch(value) for value in values):
            raise RuntimeError("security_proof_invalid_name")
        proof = {
            "run_id": self.run_id,
            "scenario": scenario,
            "sinks": list(sinks),
            "status": "PASS",
        }
        with (self.path / "summaries" / "error-path-proofs.jsonl").open(
            "a", encoding="utf-8"
        ) as handle:
            handle.write(json.dumps(proof, sort_keys=True) + "\n")

    def safe_summary(self, status: str, cleanup: str) -> Path:
        counters = aggregate_events(self.path)
        envelope_count = len(list((self.path / "sentry").glob("envelope-*.bin")))
        role_counts: dict[str, int] = {}
        unsafe_egress_categories: set[str] = set()
        for event_file in (self.path / "events").glob("*.jsonl"):
            for line in event_file.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                role = str(event.get("process_role", "unknown"))
                role_counts[role] = role_counts.get(role, 0) + 1
                if event.get("event_type") == "socket_attempt" and (
                    event.get("blocked") or event.get("host_category") != "loopback"
                ):
                    unsafe_egress_categories.add(
                        f"{role}:{event.get('destination_category', 'unknown')}:"
                        f"{event.get('host_category', 'unknown')}:"
                        f"{event.get('safe_route_category', 'unknown')}"
                    )
        required_zero = (
            "non_loopback_connection_attempts",
            "blocked_connection_attempts",
            "telegram_external_attempts",
            "yookassa_external_attempts",
            "ai_external_attempts",
            "sentry_external_attempts",
            "email_external_attempts",
            "analytics_external_attempts",
            "support_external_attempts",
        )
        if any(counters[name] for name in required_zero):
            detail = ",".join(sorted(unsafe_egress_categories)) or "adapter_counter"
            raise RuntimeError(f"security_egress_counters_not_zero:{detail}")
        if counters["local_fake_http_calls"] < 1 or envelope_count < 1:
            raise RuntimeError("sentry_collector_proof_incomplete")
        if counters["postgres_connection_attempts"] < 1 or counters["redis_connection_attempts"] < 1:
            missing = ",".join(
                name
                for name in ("postgres", "redis")
                if counters[f"{name}_connection_attempts"] < 1
            )
            raise RuntimeError(f"dependency_connection_counters_incomplete:{missing}")
        matrix_path = self.path / "summaries" / "security-matrix.json"
        proof_path = self.path / "summaries" / "error-path-proofs.jsonl"
        if not matrix_path.exists() or not proof_path.exists():
            raise RuntimeError("security_matrix_proof_missing")
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        proofs = [json.loads(line) for line in proof_path.read_text(encoding="utf-8").splitlines()]
        proven_scenarios = {proof["scenario"] for proof in proofs if proof.get("status") == "PASS"}
        matrix_scenarios = {row["asset"] for row in matrix.get("rows", [])}
        if matrix_scenarios != proven_scenarios:
            raise RuntimeError("security_matrix_proof_mismatch")
        required_sinks = {
            sink for row in matrix["rows"] for sink in row.get("sinks", [])
        }
        required_sinks.update(
            {
                "uvicorn-stdout", "uvicorn-stderr", "telegram-stdout",
                "telegram-stderr", "celery-worker-stdout",
                "celery-worker-stderr", "celery-beat-stdout",
                "celery-beat-stderr",
            }
        )
        artifact_coverage: dict[str, int] = {}
        for sink in sorted(required_sinks):
            requirement = _ARTIFACT_REQUIREMENTS.get(sink)
            if requirement is None:
                raise RuntimeError(f"security_sink_requirement_unknown:{sink}")
            pattern, require_nonempty = requirement
            matches = [
                item for item in self.path.glob(pattern)
                if item.is_file() and (not require_nonempty or item.stat().st_size > 0)
            ]
            if not matches:
                raise RuntimeError(f"security_sink_artifact_missing:{sink}")
            artifact_coverage[sink] = len(matches)
        open_counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        for row in matrix["rows"]:
            if row["result"] != "PASS" or row["disposition"] not in {"FIXED", "SUFFICIENT"}:
                open_counts[row["severity"]] += 1
        artifacts = [
            item for item in self.path.rglob("*")
            if item.is_file() and item.name != "registry.json"
        ]
        sink_counts: dict[str, int] = {}
        for artifact in artifacts:
            sink = _sink_type(artifact.relative_to(self.path))
            sink_counts[sink] = sink_counts.get(sink, 0) + 1
        summary = {
            "run_id": self.run_id,
            "sentinel_aliases": list(self.registry),
            "scanned_files": scan_artifacts(self.path, self.registry),
            "event_counts": counters.pop("event_counts"),
            "process_role_counts": role_counts,
            "envelope_count": envelope_count,
            "egress_counters": counters,
            "log_sink_artifact_counts": sink_counts,
            "required_sink_coverage": artifact_coverage,
            "security_matrix": {
                "rows": len(matrix["rows"]),
                "open": open_counts,
                "accepted_limitations": sum(
                    row["disposition"] == "ACCEPTED_LIMITATION" for row in matrix["rows"]
                ),
                "external_gates": sum(
                    row["disposition"] == "EXTERNAL_GATE" for row in matrix["rows"]
                ),
            },
            "status": status,
            "cleanup": cleanup,
        }
        internal_summary = self.path / "summaries" / "security-runner-summary.json"
        internal_summary.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
        summary["scanned_files"] = scan_artifacts(self.path, self.registry)
        internal_summary.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
        scan_artifacts(self.path, self.registry)
        destination = Path(tempfile.gettempdir()) / f"nura-security-safe-summary-{self.run_id}.json"
        destination.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
        return destination

    def cleanup(self) -> None:
        registry = self.path / "registry.json"
        if registry.exists():
            registry.unlink()
        shutil.rmtree(self.path, ignore_errors=False)


def _context_path() -> Path | None:
    value = os.environ.get(CONTEXT_ENV)
    return Path(value) if value else None


def emit_event(event_type: str, **fields: Any) -> None:
    """Append only safe metadata to the current process' private JSONL file."""
    context = _context_path()
    if context is None:
        return
    _append_event(
        context,
        os.environ.get(ROLE_ENV, "unknown"),
        os.getpid(),
        os.environ.get("NURA_SECURITY_PROCESS_CYCLE", "1"),
        event_type,
        fields,
    )


def emit_context_event(
    context: Path, process_role: str, event_type: str, **fields: Any
) -> None:
    """Write a safe parent-owned event without mutating process environment."""
    _append_event(context, process_role, os.getpid(), "1", event_type, fields)


def install_security_log_capture() -> None:
    """Capture real process logging into the current raw run directory."""
    context = _context_path()
    if context is None:
        return
    role = os.environ.get(ROLE_ENV, "unknown")
    cycle = os.environ.get("NURA_SECURITY_PROCESS_CYCLE", "1")
    marker = f"nura-security:{context}:{role}:{cycle}"
    root = logging.getLogger()
    if any(getattr(handler, "_nura_security_marker", None) == marker for handler in root.handlers):
        return
    path = context / "logs" / f"{role}-cycle-{cycle}.application.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(levelname)s %(name)s %(message)s")
    )
    handler._nura_security_marker = marker  # type: ignore[attr-defined]
    root.addHandler(handler)
    handler.emit(
        logging.LogRecord(
            name="nura.security.capture",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="security_log_capture_ready role=%s",
            args=(role,),
            exc_info=None,
        )
    )


def _append_event(
    context: Path,
    role: str,
    pid: int,
    cycle: str,
    event_type: str,
    fields: dict[str, Any],
) -> None:
    event = {
        "timestamp": int(time.time()), "run_id": context.name.removeprefix("nura-security-").split("-")[0],
        "process_role": role, "pid": pid, "event_type": event_type,
    }
    permitted = {"destination_category", "host_category", "allowed", "blocked", "safe_route_category", "correlation_id"}
    event.update({key: value for key, value in fields.items() if key in permitted})
    path = context / "events" / f"{role}-cycle-{cycle}-{pid}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def aggregate_events(path: Path) -> dict[str, Any]:
    counters = {name: 0 for name in _COUNTERS}
    event_counts: dict[str, int] = {}
    local_fake_categories: dict[str, int] = {}
    for event_file in (path / "events").glob("*.jsonl"):
        for line in event_file.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            event_type = event.get("event_type", "unknown")
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
            if event_type == "socket_attempt":
                if event.get("host_category") != "loopback":
                    counters["non_loopback_connection_attempts"] += 1
                if event.get("blocked"):
                    counters["blocked_connection_attempts"] += 1
                if event.get("destination_category") == "postgres":
                    counters["postgres_connection_attempts"] += 1
                if event.get("destination_category") == "redis":
                    counters["redis_connection_attempts"] += 1
            if event_type == "postgres_connection":
                counters["postgres_connection_attempts"] += 1
            if event_type == "redis_connection":
                counters["redis_connection_attempts"] += 1
            if event_type == "local_fake_call":
                counters["local_fake_http_calls"] += 1
                category = str(event.get("destination_category", "unknown"))
                local_fake_categories[category] = (
                    local_fake_categories.get(category, 0) + 1
                )
    counters["event_counts"] = event_counts
    counters["local_fake_calls_by_category"] = local_fake_categories
    return counters


def scan_artifacts(path: Path, registry: dict[str, str]) -> int:
    """Raise with aliases and relative paths only; never disclose test values."""
    artifacts = [item for item in path.rglob("*") if item.is_file() and item.name != "registry.json"]
    for artifact in artifacts:
        payload = artifact.read_bytes()
        relative = artifact.relative_to(path)
        sink_type = _sink_type(relative)
        birth_value = registry.get("birth_date_marker")
        identity_value = registry.get("telegram_identity_marker")
        birth = birth_value.encode() if birth_value else b""
        identity = identity_value.encode() if identity_value else b""
        pairwise_count = 0
        for offset in range(0, len(payload), 512):
            window = payload[max(0, offset - 512):offset + 1024]
            if birth and identity and birth in window and identity in window:
                pairwise_count += 1
        if pairwise_count:
            raise RuntimeError(
                "sentinel_pair_leak:alias=birth_date_marker+telegram_identity_marker:"
                f"path={relative}:role={_process_role(relative)}:"
                f"sink={sink_type}:count={pairwise_count}"
            )
        for alias, value in registry.items():
            occurrence_count = payload.count(value.encode())
            if occurrence_count:
                raise RuntimeError(
                    f"sentinel_leak:alias={alias}:path={relative}:"
                    f"role={_process_role(relative)}:sink={sink_type}:count={occurrence_count}"
                )
        for alias, pattern in _GENERIC_FORBIDDEN_PATTERNS.items():
            occurrence_count = len(pattern.findall(payload))
            if occurrence_count:
                raise RuntimeError(
                    f"sensitive_pattern_leak:alias={alias}:path={relative}:"
                    f"role={_process_role(relative)}:sink={sink_type}:count={occurrence_count}"
                )
    return len(artifacts)


def _sink_type(relative: Path) -> str:
    return {
        "events": "security_event",
        "logs": "subprocess_log",
        "responses": "http_response",
        "sentry": "sentry_envelope",
        "summaries": "runner_summary",
    }.get(relative.parts[0], "artifact")


def _process_role(relative: Path) -> str:
    return (
        relative.name.split("-cycle-", 1)[0]
        if "-cycle-" in relative.name
        else relative.parts[0]
    )


def sanitize_text(value: str, registry: dict[str, str]) -> str:
    for secret in registry.values():
        value = value.replace(secret, "<redacted>")
    return re.sub(r"(Authorization|Cookie):[^\r\n]+", r"\1:<redacted>", value, flags=re.I)
