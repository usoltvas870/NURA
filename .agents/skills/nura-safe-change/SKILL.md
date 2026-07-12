---
name: nura-safe-change
description: Safely change files in the NURA repository. Use for every write task, including configuration, code, docs, tests, or assets; preserve unrelated worktree changes and enforce scoped validation, review, and authorized finalization.
---

# NURA safe change

1. Read the applicable `AGENTS.md` files and state the exact scope.
2. Run `git status --short` before editing; identify unrelated changes and preserve them outside staging.
3. Inspect real execution paths before editing and make the smallest compatible change.
4. Run proportionate lint/tests, then inspect `git diff`, `git diff --check`, staged scope, secrets, and accidental generated files.
5. Use only the relevant read-only reviewer for meaningful diffs; address confirmed findings and repeat affected checks.
6. Separate read-only audit, local implementation, and commit/push finalization. Commit or push only with current-task authorization.

Never use `reset --hard`, force push, blind `git clean`, mass checkout/restore, or automatic rebase/merge. Treat auth, payments, legal, migrations, manifests, service workers, Nginx, SSH, VPS, and deploy as protected scope requiring explicit owner approval.
