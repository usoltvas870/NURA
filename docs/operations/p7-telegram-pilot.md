# P7 Telegram pilot owner runbook

This runbook documents repository-side readiness only. It is not authority to
launch the production workflow, change production, rotate credentials, or run
SSH commands manually.

1. Create a new, separate Telegram bot with BotFather.
2. Do not send its token in chat, an issue, a commit, or a pull request.
3. Do not add the value to GitHub Actions. A separately authorized SSH
   provisioning operation must place it in the fixed owner-only host file.
4. Do not change the legacy bot token.
5. Wait for green main CI before using any production workflow.
6. Use only a new `workflow_dispatch` run of **P7 Telegram pilot deploy** with
   the exact merged controller SHA, target SHA, and approved production host.

The controller rejects reruns, malformed or mutable SHA inputs, host mismatch,
missing token material, and unsafe controller bundles before a pilot mutation.
It runs an isolated `nura_tg` Compose project: bot, worker, and dedicated Redis
only. It does not create PostgreSQL, legacy Redis, web/PWA, admin-bot, or
celery-beat services. Pilot payments and recurring schedules are disabled.

The token is materialized atomically into an owner-only secret file, mounted
read-only, and supplied only through `TELEGRAM_BOT_TOKEN_FILE`. Never add the
actual token or a token hash to this document or to any repository file.

No production workflow was launched while preparing this runbook.
