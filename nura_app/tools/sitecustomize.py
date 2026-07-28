"""Test-only Python bootstrap; inert outside a security-run context."""

import os

if os.environ.get("NURA_SECURITY_RUN_CONTEXT"):
    from telegram_first_security_context import install_security_log_capture
    from telegram_first_security_guard import install

    install_security_log_capture()
    install()
