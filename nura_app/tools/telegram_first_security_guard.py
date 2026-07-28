"""Socket guard loaded only through test-only ``sitecustomize``."""

from __future__ import annotations

import json
import ipaddress
import os
import socket
from pathlib import Path
from typing import Any

try:  # Script bootstrap imports helpers directly; pytest imports namespace package.
    from telegram_first_security_context import CONTEXT_ENV, emit_event
except ModuleNotFoundError:  # pragma: no cover - selected by the import path
    from tools.telegram_first_security_context import CONTEXT_ENV, emit_event


_installed = False
_original_connect = socket.socket.connect
_original_create_connection = socket.create_connection


def _host_category(host: str) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "hostname"
    if address.is_loopback:
        return "loopback"
    if address.is_private:
        return "private"
    if address.is_link_local:
        return "link-local"
    return "public"


def _classify(address: Any) -> tuple[bool, str, str]:
    host, port = str(address[0]), int(address[1])
    context = Path(os.environ[CONTEXT_ENV])
    allowlist = json.loads((context / "allowlist.json").read_text(encoding="utf-8"))
    for endpoint in allowlist["endpoints"]:
        if endpoint["host"] == host and endpoint["port"] == port:
            host_category = _host_category(host)
            return True, endpoint["category"], host_category
    if host == "localhost" or _host_category(host) == "loopback":
        return True, "loopback", "loopback"
    return False, "blocked", _host_category(host)


def _connect(sock: socket.socket, address: Any) -> Any:
    if not os.environ.get(CONTEXT_ENV):
        return _original_connect(sock, address)
    allowed, destination, host_category = _classify(address)
    emit_event("socket_attempt", destination_category=destination, host_category=host_category, allowed=allowed, blocked=not allowed, safe_route_category=f"port-{address[1]}")
    if not allowed:
        raise OSError("security_guard_blocked_destination")
    return _original_connect(sock, address)


def _create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
    if not os.environ.get(CONTEXT_ENV):
        return _original_create_connection(address, *args, **kwargs)
    allowed, destination, host_category = _classify(address)
    emit_event("socket_attempt", destination_category=destination, host_category=host_category, allowed=allowed, blocked=not allowed, safe_route_category=f"port-{address[1]}")
    if not allowed:
        raise OSError("security_guard_blocked_destination")
    return _original_create_connection(address, *args, **kwargs)


def install() -> None:
    global _installed
    if _installed or not os.environ.get(CONTEXT_ENV):
        return
    socket.socket.connect = _connect
    socket.create_connection = _create_connection
    _installed = True
    emit_event("process_start")
