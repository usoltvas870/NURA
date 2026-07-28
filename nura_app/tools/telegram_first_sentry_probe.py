"""Test-only Sentry probes using the canonical ``api.main`` initialization."""

from __future__ import annotations

import json
import gzip
import brotli
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:  # Runner imports tools directly; unit tests import the namespace package.
    from telegram_first_security_context import emit_context_event
except ModuleNotFoundError:  # pragma: no cover - selected by the import path
    from tools.telegram_first_security_context import emit_context_event


class _Collector(BaseHTTPRequestHandler):
    destination: Path
    sequence = 0

    def do_POST(self) -> None:  # noqa: N802
        payload = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        encoding = self.headers.get("Content-Encoding")
        if encoding == "gzip":
            payload = gzip.decompress(payload)
        elif encoding == "br":
            payload = brotli.decompress(payload)
        elif encoding:
            raise RuntimeError("sentry_collector_unsupported_content_encoding")
        type(self).sequence += 1
        self.destination.with_name(f"envelope-{type(self).sequence}.bin").write_bytes(payload)
        emit_context_event(
            self.destination.parents[1],
            "sentry-collector",
            "local_fake_call",
            destination_category="sentry",
            host_category="loopback",
            allowed=True,
        )
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def _run_child(env: dict[str, str], source: str, label: str) -> None:
    completed = subprocess.run((sys.executable, "-c", source), cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, check=False)
    context = Path(env["NURA_SECURITY_RUN_CONTEXT"])
    (context / "logs" / f"sentry-{label}.stdout.log").write_text(
        completed.stdout, encoding="utf-8"
    )
    (context / "logs" / f"sentry-{label}.stderr.log").write_text(
        completed.stderr, encoding="utf-8"
    )
    if completed.returncode:
        raise RuntimeError(f"sentry_probe_failed:{label}:{type(completed).__name__}")


def run_sentry_probes(env: dict[str, str], context_path: Path) -> int:
    """Prove disabled and loopback-DSN modes without exposing their values."""
    no_dsn = env.copy()
    no_dsn.pop("SENTRY_DSN", None)
    _run_child(no_dsn, "import api.main; import sentry_sdk; assert sentry_sdk.Hub.current.client is None", "no_dsn")
    collector = ThreadingHTTPServer(("127.0.0.1", 0), _Collector)
    _Collector.destination = context_path / "sentry" / "envelope.bin"
    _Collector.sequence = 0
    thread = threading.Thread(target=collector.serve_forever, daemon=True)
    thread.start()
    envelope_count = 0
    try:
        allowlist = context_path / "allowlist.json"
        data = json.loads(allowlist.read_text(encoding="utf-8"))
        data["endpoints"].append({"host": "127.0.0.1", "port": collector.server_port, "category": "local-fake-sentry"})
        allowlist.write_text(json.dumps(data), encoding="utf-8")
        synthetic = env.copy()
        registry = json.loads((context_path / "registry.json").read_text(encoding="utf-8"))
        synthetic["SENTRY_DSN"] = f"http://{registry['sentry_dsn_secret_fragment']}@127.0.0.1:{collector.server_port}/1"
        source = """
import json, os, sentry_sdk
from pathlib import Path
import api.main
values=json.loads((Path(os.environ['NURA_SECURITY_RUN_CONTEXT'])/'registry.json').read_text())
def enrich(event, hint):
    event['request']={'method':'POST','url':'http://local/checkout?token='+values['checkout_capability'],'headers':{'Authorization':values['internal_support_marker'],'Cookie':values['telegram_identity_marker']},'data':values['report_content_marker']}
    event['user']={'id':values['telegram_identity_marker'],'email':values['receipt_email']}
    event.setdefault('extra',{}).update({'receipt_email':values['receipt_email'],'pdf':values['pdf_content_marker']})
    event.setdefault('contexts',{}).update({'provider':{'marker':values['provider_payment_marker']},'report':{'content':values['report_content_marker']}})
    event['breadcrumbs']={'values':[{'message':values['internal_support_marker']}]}
    return event
scope=sentry_sdk.get_current_scope()
scope.add_event_processor(enrich)
leaked_local=values['pdf_content_marker']
try: raise RuntimeError(values['checkout_capability'])
except RuntimeError as error:
    sentry_sdk.capture_exception(error)
sentry_sdk.flush(timeout=10)
"""
        _run_child(synthetic, source, "synthetic_dsn")
        if not list((context_path / "sentry").glob("envelope-*.bin")):
            raise RuntimeError("sentry_probe_failed:envelope_missing")
        envelope_count = len(list((context_path / "sentry").glob("envelope-*.bin")))
        (context_path / "summaries" / "sentry-proof.json").write_text(
            json.dumps(
                {
                    "no_dsn": "PASS",
                    "synthetic_dsn": "PASS",
                    "flush": "PASS",
                    "envelope_count": envelope_count,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    finally:
        collector.shutdown()
        collector.server_close()
        thread.join(timeout=5)
    if thread.is_alive() or collector.socket.fileno() != -1:
        raise RuntimeError("sentry_probe_failed:collector_cleanup")
    return envelope_count
