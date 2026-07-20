#!/bin/bash
set -Eeuo pipefail

readonly SHA_PATTERN='^[0-9a-f]{40}$'

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

log() {
  echo "[deploy] $*"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

require_tracked_regular_file() {
  local relative_path="$1"
  git -C "$REPO_ROOT" ls-files --error-unmatch -- "$relative_path" >/dev/null 2>&1 \
    || fail "required source is not tracked: $relative_path"
  [[ -f "$REPO_ROOT/$relative_path" && ! -L "$REPO_ROOT/$relative_path" ]] \
    || fail "required source is missing, not regular, or a symlink: $relative_path"
}

require_exact_target_file() {
  local relative_path="$1"
  local target_blob worktree_blob
  require_tracked_regular_file "$relative_path"
  target_blob="$(git -C "$REPO_ROOT" rev-parse "${TARGET_SHA}:${relative_path}")" \
    || fail "required target blob is unavailable: $relative_path"
  worktree_blob="$(git -C "$REPO_ROOT" hash-object --no-filters "$REPO_ROOT/$relative_path")" \
    || fail "cannot hash worktree source: $relative_path"
  [[ "$worktree_blob" == "$target_blob" ]] \
    || fail "worktree source differs from exact target blob: $relative_path"
}

assert_clean_checkout() {
  local status
  status="$(git -C "$REPO_ROOT" status --porcelain --untracked-files=normal)"
  [[ -z "$status" ]] || {
    echo "$status" >&2
    fail "server checkout contains tracked, staged, or non-ignored untracked changes"
  }
}

assert_no_git_operation() {
  local state_name state_path
  for state_name in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD REBASE_HEAD rebase-merge rebase-apply; do
    state_path="$(git -C "$REPO_ROOT" rev-parse --git-path "$state_name")"
    [[ ! -e "$state_path" ]] || fail "server checkout has an active Git operation: $state_name"
  done
}

if [[ $# -ne 1 ]]; then
  fail "usage: deploy.sh <40-character-lowercase-target-sha>"
fi

readonly TARGET_SHA="$1"
[[ "$TARGET_SHA" =~ $SHA_PATTERN ]] \
  || fail "target SHA must be exactly 40 lowercase hexadecimal characters"

case "${ALLOW_MIGRATIONS:-false}" in
  true)
    readonly MIGRATIONS_APPROVED=true
    ;;
  false|0|no|"")
    readonly MIGRATIONS_APPROVED=false
    ;;
  *)
    fail "ALLOW_MIGRATIONS must be an explicit boolean"
    ;;
esac

case "${NURA_DEPLOY_TEST_MODE:-0}" in
  0)
    readonly REPO_ROOT="/opt/nura"
    readonly WEB_ROOT="/var/www/nura-ai.ru"
    readonly NGINX_DEST="/etc/nginx/sites-available/nura-ai.ru.conf"
    readonly VERSION_FILE="$WEB_ROOT/VERSION"
    readonly LOCK_FILE="/var/lock/nura-deploy.lock"
    readonly BASE_URL="https://nura-ai.ru"
    ;;
  1)
    readonly REPO_ROOT="${NURA_TEST_REPO_ROOT:?NURA_TEST_REPO_ROOT is required in test mode}"
    readonly WEB_ROOT="${NURA_TEST_WEB_ROOT:?NURA_TEST_WEB_ROOT is required in test mode}"
    readonly NGINX_DEST="${NURA_TEST_NGINX_DEST:?NURA_TEST_NGINX_DEST is required in test mode}"
    readonly VERSION_FILE="${NURA_TEST_VERSION_FILE:?NURA_TEST_VERSION_FILE is required in test mode}"
    readonly LOCK_FILE="${NURA_TEST_LOCK_FILE:?NURA_TEST_LOCK_FILE is required in test mode}"
    readonly BASE_URL="${NURA_TEST_BASE_URL:-https://fixture.invalid}"
    [[ "$REPO_ROOT" != "/opt/nura" ]] || fail "test mode cannot target the production checkout"
    [[ "$WEB_ROOT" != "/var/www/nura-ai.ru" ]] || fail "test mode cannot target the production web root"
    [[ "$NGINX_DEST" != /etc/nginx/* ]] || fail "test mode cannot target production nginx"
    ;;
  *)
    fail "NURA_DEPLOY_TEST_MODE must be 0 or 1"
    ;;
esac

readonly MANIFEST_HELPER="scripts/deploy_static_release.py"
readonly NGINX_SOURCE="nura_app/nginx/nura-ai.ru.conf"

for command_name in git flock python3 node install nginx systemctl docker curl awk mktemp; do
  require_command "$command_name"
done

[[ -d "$REPO_ROOT" ]] || fail "expected repository path is missing: $REPO_ROOT"
[[ -d "$WEB_ROOT" && ! -L "$WEB_ROOT" ]] || fail "web root must be an existing real directory"
[[ -d "$(dirname "$NGINX_DEST")" ]] || fail "nginx destination directory is missing"
[[ -d "$(dirname "$VERSION_FILE")" ]] || fail "VERSION destination directory is missing"
[[ -d "$(dirname "$LOCK_FILE")" ]] || fail "deployment lock directory is missing"

# The host lock is acquired before checkout, static, nginx, API, or VERSION mutation.
exec 9>"$LOCK_FILE"
flock -n 9 || fail "another deployment holds the common host lock"
log "acquired common deployment lock"

readonly ACTUAL_REPO_ROOT="$(git -C "$REPO_ROOT" rev-parse --show-toplevel)"
[[ "$ACTUAL_REPO_ROOT" == "$REPO_ROOT" ]] \
  || fail "repository path mismatch: expected $REPO_ROOT, got $ACTUAL_REPO_ROOT"
readonly CURRENT_BRANCH="$(git -C "$REPO_ROOT" symbolic-ref --quiet --short HEAD)"
[[ "$CURRENT_BRANCH" == "main" ]] || fail "server checkout must be on main"
assert_clean_checkout
assert_no_git_operation

[[ -f "$VERSION_FILE" && ! -L "$VERSION_FILE" ]] \
  || fail "existing production VERSION is missing, not regular, or a symlink"
readonly CURRENT_PRODUCTION_SHA="$(awk 'NR == 1 { print $1; exit }' "$VERSION_FILE")"
[[ "$CURRENT_PRODUCTION_SHA" =~ $SHA_PATTERN ]] \
  || fail "existing production VERSION does not start with a valid commit SHA"

log "fetching refs needed to verify exact target $TARGET_SHA"
git -C "$REPO_ROOT" fetch --no-tags origin main
git -C "$REPO_ROOT" cat-file -e "$TARGET_SHA^{commit}" \
  || fail "target commit does not exist after fetch"
git -C "$REPO_ROOT" cat-file -e "$CURRENT_PRODUCTION_SHA^{commit}" \
  || fail "current production VERSION commit does not exist"
git -C "$REPO_ROOT" merge-base --is-ancestor "$TARGET_SHA" refs/remotes/origin/main \
  || fail "target commit is not in origin/main history"

readonly CHECKOUT_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
git -C "$REPO_ROOT" merge-base --is-ancestor "$CHECKOUT_HEAD" "$TARGET_SHA" \
  || fail "server main cannot fast-forward to target; rollback is forbidden"
git -C "$REPO_ROOT" merge-base --is-ancestor "$CURRENT_PRODUCTION_SHA" "$TARGET_SHA" \
  || fail "current production VERSION is not an ancestor of target"

git -C "$REPO_ROOT" merge --ff-only --no-edit "$TARGET_SHA"
[[ "$(git -C "$REPO_ROOT" rev-parse HEAD)" == "$TARGET_SHA" ]] \
  || fail "server checkout HEAD does not equal exact target"
assert_clean_checkout
assert_no_git_operation
log "server checkout fast-forwarded to exact target $TARGET_SHA"

require_exact_target_file "$MANIFEST_HELPER"
require_exact_target_file "scripts/build_pwa_release.py"
require_exact_target_file "frontend/test_pwa_release.mjs"
require_exact_target_file "$NGINX_SOURCE"
require_exact_target_file "nura_app/docker-compose.yml"
require_exact_target_file "nura_app/Dockerfile"
require_exact_target_file "nura_app/requirements.txt"
require_exact_target_file "nura_app/scripts/entrypoint.sh"

log "validating deterministic release metadata"
python3 "$REPO_ROOT/scripts/build_pwa_release.py" --check
node "$REPO_ROOT/frontend/test_pwa_release.mjs"

readonly MANIFEST_FILE="$(mktemp "${TMPDIR:-/tmp}/nura-deploy-manifest.XXXXXX.json")"
COMPOSE_OVERRIDE=""
COMPOSE_BASE=""
NGINX_BACKUP=""
NGINX_CANDIDATE=""
VERSION_TEMP=""
cleanup() {
  rm -f -- "$MANIFEST_FILE"
  [[ -z "$COMPOSE_OVERRIDE" ]] || rm -f -- "$COMPOSE_OVERRIDE"
  [[ -z "$COMPOSE_BASE" ]] || rm -f -- "$COMPOSE_BASE"
  [[ -z "$NGINX_BACKUP" ]] || rm -f -- "$NGINX_BACKUP"
  [[ -z "$NGINX_CANDIDATE" ]] || rm -f -- "$NGINX_CANDIDATE"
  [[ -z "$VERSION_TEMP" ]] || rm -f -- "$VERSION_TEMP"
}
trap cleanup EXIT
python3 "$REPO_ROOT/$MANIFEST_HELPER" build-manifest \
  --repo-root "$REPO_ROOT" \
  --target-sha "$TARGET_SHA" \
  --output "$MANIFEST_FILE"

readonly MIGRATION_OUTPUT="$(
  python3 "$REPO_ROOT/$MANIFEST_HELPER" migration-delta \
    --repo-root "$REPO_ROOT" \
    --current-sha "$CURRENT_PRODUCTION_SHA" \
    --target-sha "$TARGET_SHA"
)"
MIGRATION_FILES=()
if [[ -n "$MIGRATION_OUTPUT" ]]; then
  mapfile -t MIGRATION_FILES <<< "$MIGRATION_OUTPUT"
fi
if (( ${#MIGRATION_FILES[@]} > 0 )); then
  log "migration delta detected between $CURRENT_PRODUCTION_SHA and $TARGET_SHA:"
  printf '  %s\n' "${MIGRATION_FILES[@]}"
  [[ "$MIGRATIONS_APPROVED" == true ]] \
    || fail "migration delta requires explicit allow_migrations=true after readiness review"
  log "migration delta explicitly approved; deploy.sh will not run migrations or downgrade commands"
else
  log "no migration delta detected"
fi

log "preflight complete; beginning verified in-place static copy"
if [[ "${NURA_DEPLOY_TEST_MODE:-0}" == 1 && "${NURA_TEST_FAIL_PHASE:-}" == copy ]]; then
  fail "injected mandatory copy failure"
fi
python3 "$REPO_ROOT/$MANIFEST_HELPER" copy-manifest \
  --repo-root "$REPO_ROOT" \
  --web-root "$WEB_ROOT" \
  --manifest "$MANIFEST_FILE"

log "installing and validating nginx configuration"
[[ -f "$NGINX_DEST" && ! -L "$NGINX_DEST" ]] \
  || fail "active nginx configuration must be an existing regular file"
NGINX_BACKUP="$(mktemp "$(dirname "$NGINX_DEST")/.nura-nginx-backup.XXXXXX")"
NGINX_CANDIDATE="$(mktemp "${TMPDIR:-/tmp}/nura-nginx-candidate.XXXXXX.conf")"
install -m 0644 "$NGINX_DEST" "$NGINX_BACKUP"
git -C "$REPO_ROOT" show "${TARGET_SHA}:${NGINX_SOURCE}" > "$NGINX_CANDIDATE"
install -m 0644 "$NGINX_CANDIDATE" "$NGINX_DEST"
if ! nginx -t; then
  install -m 0644 "$NGINX_BACKUP" "$NGINX_DEST"
  nginx -t || true
  fail "candidate nginx configuration is invalid; previous configuration restored"
fi
if ! systemctl reload nginx; then
  install -m 0644 "$NGINX_BACKUP" "$NGINX_DEST"
  nginx -t || true
  systemctl reload nginx || true
  fail "nginx reload failed; previous configuration restored"
fi
rm -f -- "$NGINX_BACKUP"
NGINX_BACKUP=""
rm -f -- "$NGINX_CANDIDATE"
NGINX_CANDIDATE=""

readonly RELEASE_IMAGE="nura-release:$TARGET_SHA"
log "building application image from the exact tracked target archive"
git -C "$REPO_ROOT" archive --format=tar "${TARGET_SHA}:nura_app" \
  | docker build --pull=false --tag "$RELEASE_IMAGE" -

COMPOSE_OVERRIDE="$(mktemp "${TMPDIR:-/tmp}/nura-compose-override.XXXXXX.yml")"
COMPOSE_BASE="$(mktemp "${TMPDIR:-/tmp}/nura-compose-base.XXXXXX.yml")"
git -C "$REPO_ROOT" show "${TARGET_SHA}:nura_app/docker-compose.yml" > "$COMPOSE_BASE"
cat > "$COMPOSE_OVERRIDE" <<EOF
services:
  api:
    image: $RELEASE_IMAGE
    environment:
      RUN_MIGRATIONS: "0"
  admin-bot:
    image: $RELEASE_IMAGE
EOF

log "activating API and admin-bot from the exact target image without migrations"
(
  cd "$REPO_ROOT/nura_app"
  docker compose \
    --project-directory "$REPO_ROOT/nura_app" \
    -f "$COMPOSE_BASE" \
    -f "$COMPOSE_OVERRIDE" \
    up -d --no-build --no-deps --wait --wait-timeout 180 api admin-bot
)

log "running mandatory smoke checks before VERSION update"
readonly -a SMOKE_PATHS=(
  "/"
  "/service-worker.js"
  "/pwa-release.js"
  "/pwa-release.json"
  "/manifest.json"
  "/offline.html"
  "/app/"
  "/app/index.html"
  "/app/nura-pwa.js"
  "/health"
)
if [[ "${NURA_DEPLOY_TEST_MODE:-0}" == 1 ]]; then
  [[ "${NURA_TEST_FAIL_PHASE:-}" != curl ]] || fail "injected smoke/health failure"
  log "test mode: mandatory smoke/health phase reached without network access"
else
  for endpoint in "${SMOKE_PATHS[@]}"; do
    curl --fail --silent --show-error "$BASE_URL$endpoint" --output /dev/null
  done
fi

VERSION_TEMP="$(mktemp "$(dirname "$VERSION_FILE")/.VERSION.XXXXXX")"
printf '%s - %s\n' "$TARGET_SHA" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$VERSION_TEMP"
chmod 0644 "$VERSION_TEMP"
mv "$VERSION_TEMP" "$VERSION_FILE"
[[ "$(awk 'NR == 1 { print $1; exit }' "$VERSION_FILE")" == "$TARGET_SHA" ]] \
  || fail "VERSION verification failed"

log "deploy complete at exact SHA $TARGET_SHA"
log "WARNING: P4.2B1 still copies in place; release-level atomicity and rollback are absent."
log "WARNING: production release remains blocked pending P4.2B2, P4.1B, final readiness, and owner approval."
