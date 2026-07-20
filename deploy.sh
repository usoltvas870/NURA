#!/bin/bash
set -Eeuo pipefail

readonly SHA_PATTERN='^[0-9a-f]{40}$'
readonly -a APPLICATION_SERVICES=(api bot celery-worker celery-beat admin-bot)
readonly -a DATA_SERVICES=(postgres redis)

fail() { echo "ERROR: $*" >&2; exit 1; }
log() { echo "[release] $*"; }
require_command() { command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"; }

assert_clean_checkout() {
  local status
  status="$(git -C "$REPO_ROOT" status --porcelain --untracked-files=normal)"
  [[ -z "$status" ]] || { echo "$status" >&2; fail "server checkout contains changes"; }
}

assert_no_git_operation() {
  local name path
  for name in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD REBASE_HEAD rebase-merge rebase-apply; do
    path="$(git -C "$REPO_ROOT" rev-parse --git-path "$name")"
    [[ ! -e "$path" ]] || fail "server checkout has an active Git operation: $name"
  done
}

validate_sha() { [[ "$1" =~ $SHA_PATTERN ]] || fail "$2 must be an exact lowercase 40-character SHA"; }

if [[ $# -lt 2 ]]; then
  fail "usage: deploy.sh deploy <sha> <archive> <checksum> <manifest> | deploy.sh rollback <sha>"
fi
readonly COMMAND="$1"
readonly TARGET_SHA="$2"
validate_sha "$TARGET_SHA" "target SHA"
case "$COMMAND:$#" in
  deploy:5)
    readonly ARTIFACT_PATH="$3"
    readonly CHECKSUM_PATH="$4"
    readonly MANIFEST_PATH="$5"
    ;;
  rollback:2)
    readonly ARTIFACT_PATH=""
    readonly CHECKSUM_PATH=""
    readonly MANIFEST_PATH=""
    ;;
  *) fail "ambiguous arguments; use an explicit deploy or rollback subcommand" ;;
esac

case "${NURA_DEPLOY_TEST_MODE:-0}" in
  0)
    readonly REPO_ROOT="/opt/nura"
    readonly RELEASE_ROOT="/var/www/nura-releases"
    readonly STATE_ROOT="/var/lib/nura-release-state"
    readonly INCOMING_ROOT="/var/tmp/nura-release-incoming"
    readonly LOCK_FILE="/var/lock/nura-deploy.lock"
    readonly ENABLED_NGINX_DIR="/etc/nginx/sites-enabled"
    readonly BASE_URL="https://nura-ai.ru"
    ;;
  1)
    readonly REPO_ROOT="${NURA_TEST_REPO_ROOT:?required}"
    readonly RELEASE_ROOT="${NURA_TEST_RELEASE_ROOT:?required}"
    readonly STATE_ROOT="${NURA_TEST_STATE_ROOT:?required}"
    readonly INCOMING_ROOT="${NURA_TEST_INCOMING_ROOT:?required}"
    readonly LOCK_FILE="${NURA_TEST_LOCK_FILE:?required}"
    readonly ENABLED_NGINX_DIR="${NURA_TEST_NGINX_DIR:?required}"
    readonly BASE_URL="${NURA_TEST_BASE_URL:-https://fixture.invalid}"
    [[ "$REPO_ROOT" != /opt/nura && "$RELEASE_ROOT" != /var/www/nura-releases ]] \
      || fail "test mode cannot target production roots"
    ;;
  *) fail "NURA_DEPLOY_TEST_MODE must be 0 or 1" ;;
esac

readonly RELEASES_DIR="$RELEASE_ROOT/releases"
readonly STAGING_DIR="$RELEASE_ROOT/staging"
readonly CURRENT_LINK="$RELEASE_ROOT/current"
readonly RELEASE_STATE_DIR="$STATE_ROOT/releases"
readonly CURRENT_STATE="$STATE_ROOT/current.json"
readonly PREVIOUS_STATE="$STATE_ROOT/previous.json"
readonly ARTIFACT_HELPER="$REPO_ROOT/scripts/build_release_artifact.py"
readonly STATIC_HELPER="$REPO_ROOT/scripts/deploy_static_release.py"
readonly IMAGE_TAG="nura-release:$TARGET_SHA"

for command_name in git flock python3 node docker curl awk mktemp readlink find stat df grep cmp install mv sha256sum date; do
  require_command "$command_name"
done
[[ -d "$REPO_ROOT" && ! -L "$REPO_ROOT" ]] || fail "repository root must be a real directory"
[[ -d "$RELEASE_ROOT" && ! -L "$RELEASE_ROOT" ]] || fail "release root is not prepared; run the separately approved host transition"
[[ -d "$STATE_ROOT" && ! -L "$STATE_ROOT" ]] || fail "state root is not prepared; run the separately approved host transition"
[[ -d "$ENABLED_NGINX_DIR" && ! -L "$ENABLED_NGINX_DIR" ]] || fail "Nginx enabled directory is invalid"
[[ -d "$(dirname "$LOCK_FILE")" ]] || fail "deployment lock directory is missing"

exec 9>"$LOCK_FILE"
flock -n 9 || fail "another deploy or rollback holds the common lock"
log "acquired common release lock"

readonly ACTUAL_REPO_ROOT="$(git -C "$REPO_ROOT" rev-parse --show-toplevel)"
[[ "$ACTUAL_REPO_ROOT" == "$REPO_ROOT" ]] || fail "repository path mismatch"
[[ "$(git -C "$REPO_ROOT" symbolic-ref --quiet --short HEAD)" == main ]] \
  || fail "server checkout must be on main"
assert_clean_checkout
assert_no_git_operation

mapfile -t ENABLED_CONFIGS < <(find "$ENABLED_NGINX_DIR" -mindepth 1 -maxdepth 1 \( -type f -o -type l \) -printf '%f\n' | sort)
[[ ${#ENABLED_CONFIGS[@]} -eq 1 && "${ENABLED_CONFIGS[0]}" == "nura-ai.ru.conf" ]] \
  || fail "host transition is incomplete: exactly one canonical enabled Nginx config is required"
readonly ACTIVE_NGINX_CONFIG="$(readlink -f "$ENABLED_NGINX_DIR/nura-ai.ru.conf")"
grep -Fq 'root /var/www/nura-releases/current/public;' "$ACTIVE_NGINX_CONFIG" \
  || fail "active Nginx config does not use the immutable current release root"

[[ -f "$CURRENT_STATE" && ! -L "$CURRENT_STATE" ]] || fail "current release state is missing"
readonly CURRENT_SHA="$(python3 - "$CURRENT_STATE" <<'PY'
import json, re, sys
state = json.load(open(sys.argv[1], encoding="utf-8"))
sha = state.get("sha", "")
if state.get("status") != "successful" or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
    raise SystemExit("current release state is not successful and exact")
print(sha)
PY
)"
[[ "$TARGET_SHA" != "$CURRENT_SHA" ]] \
  || fail "target SHA is already current; refusing to create a self-referential release lineage"
PREVIOUS_STATE_FILE="$(mktemp "${TMPDIR:-/tmp}/nura-current-state.XXXXXX.json")"
install -m 0640 "$CURRENT_STATE" "$PREVIOUS_STATE_FILE"
PREVIOUS_POINTER_SNAPSHOT=""
if [[ -f "$PREVIOUS_STATE" && ! -L "$PREVIOUS_STATE" ]]; then
  PREVIOUS_POINTER_SNAPSHOT="$(mktemp "${TMPDIR:-/tmp}/nura-previous-state.XXXXXX.json")"
  install -m 0640 "$PREVIOUS_STATE" "$PREVIOUS_POINTER_SNAPSHOT"
fi

git -C "$REPO_ROOT" fetch --no-tags origin main
git -C "$REPO_ROOT" cat-file -e "$TARGET_SHA^{commit}" || fail "target commit does not exist"
git -C "$REPO_ROOT" merge-base --is-ancestor "$TARGET_SHA" refs/remotes/origin/main \
  || fail "target commit is not in origin/main history"
git -C "$REPO_ROOT" show "$TARGET_SHA:nura_app/nginx/nura-ai.ru.conf" | cmp - "$ACTIVE_NGINX_CONFIG" \
  || fail "active Nginx config does not match the reviewed target config; a separate transition is required"

write_state() {
  local status="$1" failure_stage="${2:-}" failure_reason="${3:-}" previous_sha="${4:-$CURRENT_SHA}"
  TARGET_STATUS="$status" FAILURE_STAGE="$failure_stage" FAILURE_REASON="$failure_reason" \
  PREVIOUS_SHA_VALUE="$previous_sha" IMAGE_ID_VALUE="${TARGET_IMAGE_ID:-}" \
  WORKFLOW_RUN_VALUE="${GITHUB_RUN_ID:-}" python3 - "$RELEASE_STATE_DIR/$TARGET_SHA.json" <<'PY'
import json, os, pathlib, tempfile, time
path = pathlib.Path(__import__("sys").argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
sha = path.stem
image_tag = f"nura-release:{sha}"
services = ["api", "bot", "celery-worker", "celery-beat", "admin-bot"]
value = {
    "schema": 1, "sha": sha, "status": os.environ["TARGET_STATUS"],
    "static_release_path": f"/var/www/nura-releases/releases/{sha}",
    "artifact_sha256": os.environ.get("ARTIFACT_DIGEST", ""),
    "public_manifest_sha256": os.environ.get("PUBLIC_MANIFEST_DIGEST", ""),
    "application_image_tag": image_tag, "application_image_id": os.environ.get("IMAGE_ID_VALUE", ""),
    "oci_revision": sha, "per_service_image_mapping": {name: image_tag for name in services},
    "per_service_image_ids": {name: os.environ.get("IMAGE_ID_VALUE", "") for name in services},
    "previous_successful_sha": os.environ.get("PREVIOUS_SHA_VALUE") or None,
    "activation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "workflow_run_id": os.environ.get("WORKFLOW_RUN_VALUE") or None,
    "migration_delta": False, "rollback_eligibility": os.environ["TARGET_STATUS"] == "successful",
    "failure_stage": os.environ.get("FAILURE_STAGE") or None,
    "failure_reason": (os.environ.get("FAILURE_REASON") or "")[:500] or None,
}
fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
with os.fdopen(fd, "w", encoding="utf-8") as stream:
    json.dump(value, stream, sort_keys=True, separators=(",", ":")); stream.write("\n")
os.chmod(temporary, 0o640); os.replace(temporary, path)
PY
}

atomic_copy_state() {
  local source="$1" destination="$2" temporary
  temporary="$(mktemp "$(dirname "$destination")/.${destination##*/}.XXXXXX")"
  install -m 0640 "$source" "$temporary"
  mv -f "$temporary" "$destination"
}

compose_override_for_map() {
  local output="$1" map_file="$2"
  python3 - "$output" "$map_file" <<'PY'
import json, sys
state = json.load(open(sys.argv[2], encoding="utf-8"))
mapping = state.get("per_service_image_mapping", {})
services = ["api", "bot", "celery-worker", "celery-beat", "admin-bot"]
if set(mapping) != set(services): raise SystemExit("release state service mapping is incomplete")
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    stream.write("services:\n")
    for service in services:
        stream.write(f"  {service}:\n    image: {mapping[service]}\n")
        if service == "api": stream.write('    environment:\n      RUN_MIGRATIONS: "0"\n')
PY
}

recorded_service_image_id() {
  python3 - "$1" "$2" <<'PY'
import json, sys
state=json.load(open(sys.argv[1],encoding="utf-8")); service=sys.argv[2]
image_id=state.get("per_service_image_ids",{}).get(service) or state.get("application_image_id","")
if not image_id.startswith("sha256:"): raise SystemExit(f"recorded image ID is missing: {service}")
print(image_id)
PY
}

run_compose() {
  docker compose --project-directory "$REPO_ROOT/nura_app" -f "$COMPOSE_BASE" -f "$COMPOSE_OVERRIDE" "$@"
}

verify_data_services() {
  local service container inspection
  for service in "${DATA_SERVICES[@]}"; do
    container="$(docker compose --project-directory "$REPO_ROOT/nura_app" -f "$COMPOSE_BASE" ps -q --all "$service")"
    [[ -n "$container" && "$container" != *$'\n'* ]] || fail "data service is missing or ambiguous: $service"
    inspection="$(docker inspect --format '{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container")"
    [[ "$inspection" == true\|* && "$inspection" != *\|unhealthy ]] || fail "data service is not healthy: $service"
  done
}

verify_application_fleet() {
  local expected_image="$1" expected_id="$2" expected_revision="$3" service container inspection running health tag image_id revision
  for service in "${APPLICATION_SERVICES[@]}"; do
    container="$(run_compose ps -q --all "$service")"
    [[ -n "$container" && "$container" != *$'\n'* ]] || fail "application service is missing or ambiguous: $service"
    inspection="$(docker inspect --format '{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.Config.Image}}|{{.Image}}|{{index .Config.Labels "org.opencontainers.image.revision"}}' "$container")"
    IFS='|' read -r running health tag image_id revision <<< "$inspection"
    [[ "$running" == true ]] || fail "application service is not running: $service"
    [[ "$health" != unhealthy ]] || fail "application service is unhealthy: $service"
    [[ "$tag" == "$expected_image" ]] || fail "application service tag mismatch: $service"
    [[ -z "$expected_id" || "$image_id" == "$expected_id" ]] || fail "application service image ID mismatch: $service"
    [[ -z "$expected_revision" || "$revision" == "$expected_revision" ]] || fail "application service revision mismatch: $service"
  done
}

activate_from_state() {
  local state_file="$1" expected_sha="$2" override service tag expected_id container inspection running health actual_tag actual_id revision legacy
  [[ -z "$COMPOSE_OVERRIDE" ]] || rm -f -- "$COMPOSE_OVERRIDE" || return 1
  override="$(mktemp "${TMPDIR:-/tmp}/nura-rollback-compose.XXXXXX.yml")" || return 1
  compose_override_for_map "$override" "$state_file" || return 1
  COMPOSE_OVERRIDE="$override"
  git -C "$REPO_ROOT" show "$expected_sha:nura_app/docker-compose.yml" > "$COMPOSE_BASE" || return 1
  legacy="$(python3 -c 'import json,sys; print("true" if json.load(open(sys.argv[1])).get("legacy") else "false")' "$state_file")" || return 1
  for service in "${APPLICATION_SERVICES[@]}"; do
    tag="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["per_service_image_mapping"][sys.argv[2]])' "$state_file" "$service")" || return 1
    expected_id="$(recorded_service_image_id "$state_file" "$service")" || return 1
    actual_id="$(docker image inspect --format '{{.Id}}' "$tag")" || return 1
    [[ "$actual_id" == "$expected_id" ]] || {
      echo "ERROR: rollback tag no longer identifies the recorded immutable image: $service" >&2
      return 1
    }
  done
  run_compose up -d --no-build --no-deps --wait --wait-timeout 180 "${APPLICATION_SERVICES[@]}" || return 1
  for service in "${APPLICATION_SERVICES[@]}"; do
    tag="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["per_service_image_mapping"][sys.argv[2]])' "$state_file" "$service")" || return 1
    expected_id="$(recorded_service_image_id "$state_file" "$service")" || return 1
    container="$(run_compose ps -q --all "$service")" || return 1
    [[ -n "$container" && "$container" != *$'\n'* ]] || return 1
    inspection="$(docker inspect --format '{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.Config.Image}}|{{.Image}}|{{index .Config.Labels "org.opencontainers.image.revision"}}' "$container")" || return 1
    IFS='|' read -r running health actual_tag actual_id revision <<< "$inspection"
    [[ "$running" == true && "$health" != unhealthy ]] || return 1
    [[ "$actual_tag" == "$tag" && "$actual_id" == "$expected_id" ]] || return 1
    [[ "$legacy" == true || "$revision" == "$expected_sha" ]] || return 1
  done
}

public_smoke() {
  local expected_sha="$1" endpoint version_temp
  if [[ "${NURA_DEPLOY_TEST_MODE:-0}" == 1 ]]; then
    [[ "${NURA_TEST_FAIL_PHASE:-}" != smoke ]] || return 1
    python3 "$ARTIFACT_HELPER" validate-current --current "$CURRENT_LINK" --expected-sha "$expected_sha" >/dev/null
    return
  fi
  for endpoint in / /VERSION /service-worker.js /pwa-release.js /pwa-release.json /manifest.json /offline.html /app/ /app/index.html /app/nura-pwa.js /health /vk-callback.html; do
    curl --fail --silent --show-error "$BASE_URL$endpoint" --output /dev/null
  done
  version_temp="$(mktemp)"; curl --fail --silent --show-error "$BASE_URL/VERSION" -o "$version_temp"
  [[ "$(awk 'NR == 1 {print $1; exit}' "$version_temp")" == "$expected_sha" ]] || { rm -f "$version_temp"; return 1; }
  rm -f "$version_temp"
}

write_recovery_required() {
  local original_exit="$1"
  ORIGINAL_EXIT="$original_exit" python3 - "$STATE_ROOT/logs/recovery-required-$TARGET_SHA-${GITHUB_RUN_ID:-manual}.json" <<'PY'
import json, os, pathlib, tempfile, time, sys
path=pathlib.Path(sys.argv[1]); path.parent.mkdir(parents=True,exist_ok=True)
value={"schema":1,"target_sha":path.name.split("-")[2],"status":"recovery_required","original_exit":os.environ["ORIGINAL_EXIT"],"recorded_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())}
fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.",dir=path.parent)
with os.fdopen(fd,"w",encoding="utf-8") as stream: json.dump(value,stream,sort_keys=True,separators=(",",":")); stream.write("\n")
os.chmod(tmp,0o640); os.replace(tmp,path)
PY
}

cleanup_incoming() {
  local completed="$1"
  [[ "$COMMAND" == deploy && -n "$INCOMING_DIR" ]] || return 0
  python3 - "$INCOMING_ROOT" "$INCOMING_DIR" "$completed" <<'PY'
import pathlib, shutil, sys, time
root=pathlib.Path(sys.argv[1]).resolve(strict=True); incoming=pathlib.Path(sys.argv[2])
if incoming.is_symlink() or incoming.resolve(strict=True).parent != root: raise SystemExit("unsafe incoming cleanup target")
if sys.argv[3]=="1" and incoming.exists(): shutil.rmtree(incoming)
failed=sorted((p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and time.time()-p.stat().st_mtime>=7*86400),key=lambda p:p.stat().st_mtime,reverse=True)
for path in failed[2:]: shutil.rmtree(path)
PY
}

COMPOSE_BASE="$(mktemp "${TMPDIR:-/tmp}/nura-compose-base.XXXXXX.yml")"
COMPOSE_OVERRIDE=""
STAGING_PATH=""
INCOMING_DIR=""
APP_MUTATED=0
STATIC_SWITCHED=0
SUCCESS=0
PREVIOUS_RELEASE_PATH=""
cleanup() {
  local exit_code=$?
  local compensation_ok=1
  trap - EXIT
  if [[ $SUCCESS -ne 1 ]]; then
    if [[ $STATIC_SWITCHED -eq 1 && -n "$PREVIOUS_RELEASE_PATH" ]]; then
      if ! python3 "$ARTIFACT_HELPER" switch-current --current "$CURRENT_LINK" --target "$PREVIOUS_RELEASE_PATH"; then
        compensation_ok=0
      fi
    fi
    if [[ $APP_MUTATED -eq 1 ]]; then
      if ! activate_from_state "$PREVIOUS_STATE_FILE" "$CURRENT_SHA"; then
        compensation_ok=0
      fi
    fi
    if [[ $STATIC_SWITCHED -eq 1 || $APP_MUTATED -eq 1 ]]; then
      if ! python3 "$ARTIFACT_HELPER" validate-current --current "$CURRENT_LINK" --expected-sha "$CURRENT_SHA" >/dev/null; then
        compensation_ok=0
      fi
      if ! public_smoke "$CURRENT_SHA"; then
        compensation_ok=0
      fi
    fi
    if [[ $compensation_ok -eq 1 ]]; then
      if ! atomic_copy_state "$PREVIOUS_STATE_FILE" "$CURRENT_STATE"; then compensation_ok=0; fi
      if [[ -n "$PREVIOUS_POINTER_SNAPSHOT" ]] && ! atomic_copy_state "$PREVIOUS_POINTER_SNAPSHOT" "$PREVIOUS_STATE"; then compensation_ok=0; fi
    fi
    if [[ $compensation_ok -eq 1 && "$COMMAND" == deploy ]]; then
      write_state failed "activation" "verified automatic compensation after exit $exit_code" "$CURRENT_SHA" || compensation_ok=0
    fi
    if [[ $compensation_ok -ne 1 ]]; then
      write_recovery_required "$exit_code" || true
      log "ERROR: automatic compensation could not prove a coherent release; operator recovery is required"
      exit_code=2
    fi
  fi
  cleanup_incoming "$SUCCESS" || log "WARNING: incoming artifact cleanup was incomplete"
  [[ -z "$STAGING_PATH" || ! -d "$STAGING_PATH" ]] || true
  [[ -z "$COMPOSE_OVERRIDE" ]] || rm -f -- "$COMPOSE_OVERRIDE"
  rm -f -- "$PREVIOUS_STATE_FILE"
  [[ -z "$PREVIOUS_POINTER_SNAPSHOT" ]] || rm -f -- "$PREVIOUS_POINTER_SNAPSHOT"
  rm -f -- "$COMPOSE_BASE"
  exit "$exit_code"
}
trap cleanup EXIT
python3 "$ARTIFACT_HELPER" validate-current --current "$CURRENT_LINK" --expected-sha "$CURRENT_SHA" >/dev/null
for service_name in "${APPLICATION_SERVICES[@]}"; do
  previous_tag="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["per_service_image_mapping"][sys.argv[2]])' "$PREVIOUS_STATE_FILE" "$service_name")"
  recorded_previous_id="$(recorded_service_image_id "$PREVIOUS_STATE_FILE" "$service_name")"
  actual_previous_id="$(docker image inspect --format '{{.Id}}' "$previous_tag")" \
    || fail "current release rollback image is missing before activation: $service_name"
  [[ "$actual_previous_id" == "$recorded_previous_id" ]] \
    || fail "current rollback tag does not match its recorded immutable image ID: $service_name"
done
git -C "$REPO_ROOT" show "$TARGET_SHA:nura_app/docker-compose.yml" > "$COMPOSE_BASE"
verify_data_services

if [[ "$COMMAND" == rollback ]]; then
  readonly TARGET_STATE="$RELEASE_STATE_DIR/$TARGET_SHA.json"
  [[ -f "$TARGET_STATE" && ! -L "$TARGET_STATE" ]] || fail "rollback target release state is missing"
  python3 - "$CURRENT_STATE" "$TARGET_STATE" "$RELEASE_STATE_DIR" <<'PY'
import json, pathlib, sys
current = json.load(open(sys.argv[1], encoding="utf-8")); target = json.load(open(sys.argv[2], encoding="utf-8"))
if target.get("status") not in {"successful", "rolled_back"} or not target.get("rollback_eligibility"):
    raise SystemExit("rollback target is not a protected successful release")
if target.get("migration_delta") is not False:
    raise SystemExit("schema-incompatible release cannot be rolled back automatically")
allowed=[]; cursor=current; seen={current.get("sha")}
for _ in range(2):
    sha=cursor.get("previous_successful_sha")
    if not sha: break
    if sha in seen: raise SystemExit("release state lineage contains a cycle")
    seen.add(sha)
    allowed.append(sha); path=pathlib.Path(sys.argv[3]) / f"{sha}.json"
    if not path.is_file(): break
    cursor=json.load(open(path, encoding="utf-8"))
if target.get("sha") not in allowed: raise SystemExit("rollback target is not one of two protected predecessors")
PY
  readonly TARGET_RELEASE="$RELEASES_DIR/$TARGET_SHA"
  python3 "$ARTIFACT_HELPER" validate-current --current "$CURRENT_LINK" --expected-sha "$CURRENT_SHA" >/dev/null
  python3 -c 'import importlib.util,sys; p=sys.argv[1]; s=importlib.util.spec_from_file_location("a",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.verify_release_directory(__import__("pathlib").Path(sys.argv[2]))' "$ARTIFACT_HELPER" "$TARGET_RELEASE"
  PREVIOUS_RELEASE_PATH="$RELEASES_DIR/$CURRENT_SHA"
  python3 "$ARTIFACT_HELPER" switch-current --current "$CURRENT_LINK" --target "$TARGET_RELEASE"
  STATIC_SWITCHED=1
  APP_MUTATED=1
  activate_from_state "$TARGET_STATE" "$TARGET_SHA"
  public_smoke "$TARGET_SHA" || fail "public rollback verification failed"
  atomic_copy_state "$CURRENT_STATE" "$PREVIOUS_STATE"
  python3 - "$TARGET_STATE" <<'PY'
import json, os, sys, tempfile
p=sys.argv[1]; v=json.load(open(p,encoding="utf-8")); v["status"]="successful"; v["rollback_eligibility"]=True
fd,t=tempfile.mkstemp(prefix=".rollback.",dir=os.path.dirname(p)); os.write(fd,(json.dumps(v,sort_keys=True,separators=(",",":"))+"\n").encode()); os.close(fd); os.replace(t,p)
PY
  atomic_copy_state "$TARGET_STATE" "$CURRENT_STATE"
  SUCCESS=1
  log "coordinated rollback completed at $TARGET_SHA; no database rollback was attempted"
  exit 0
fi

[[ -f "$ARTIFACT_PATH" && ! -L "$ARTIFACT_PATH" ]] || fail "incoming archive is missing"
[[ -f "$CHECKSUM_PATH" && ! -L "$CHECKSUM_PATH" ]] || fail "incoming checksum is missing"
[[ -f "$MANIFEST_PATH" && ! -L "$MANIFEST_PATH" ]] || fail "incoming manifest is missing"
INCOMING_DIR="$(dirname "$(readlink -f "$ARTIFACT_PATH")")"
readonly RESOLVED_INCOMING_ROOT="$(readlink -f "$INCOMING_ROOT")"
[[ "$(dirname "$INCOMING_DIR")" == "$RESOLVED_INCOMING_ROOT" && ! -L "$INCOMING_DIR" ]] \
  || fail "archive is outside a direct unique incoming directory"
[[ "$(dirname "$(readlink -f "$CHECKSUM_PATH")")" == "$INCOMING_DIR" ]] \
  || fail "checksum is outside the validated incoming directory"
[[ "$(dirname "$(readlink -f "$MANIFEST_PATH")")" == "$INCOMING_DIR" ]] \
  || fail "manifest is outside the validated incoming directory"

readonly MIGRATION_OUTPUT="$(git -C "$REPO_ROOT" diff --name-only "$CURRENT_SHA" "$TARGET_SHA" -- nura_app/alembic/versions)"
[[ -z "$MIGRATION_OUTPUT" ]] || { echo "$MIGRATION_OUTPUT" >&2; fail "migration delta blocks deployment; P4.2B2 has no override"; }

readonly CHECKOUT_HEAD="$(git -C "$REPO_ROOT" rev-parse HEAD)"
git -C "$REPO_ROOT" merge-base --is-ancestor "$CHECKOUT_HEAD" "$TARGET_SHA" \
  || fail "server main cannot fast-forward to target"
git -C "$REPO_ROOT" merge --ff-only --no-edit "$TARGET_SHA"
[[ "$(git -C "$REPO_ROOT" rev-parse HEAD)" == "$TARGET_SHA" ]] || fail "checkout did not reach exact target"
assert_clean_checkout
python3 "$REPO_ROOT/scripts/build_pwa_release.py" --check
node "$REPO_ROOT/frontend/test_pwa_release.mjs"

python3 "$ARTIFACT_HELPER" verify --archive "$ARTIFACT_PATH" --checksum "$CHECKSUM_PATH" --manifest "$MANIFEST_PATH" --target-sha "$TARGET_SHA"
export ARTIFACT_DIGEST="$(awk 'NR==1 {print $1}' "$CHECKSUM_PATH")"
export PUBLIC_MANIFEST_DIGEST="$(sha256sum "$MANIFEST_PATH" | awk '{print $1}')"
readonly EXTRACTED_SIZE="$(python3 -c 'import json,sys; print(sum(x["size"] for x in json.load(open(sys.argv[1]))["files"]))' "$MANIFEST_PATH")"
readonly FILE_COUNT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["file_count"])' "$MANIFEST_PATH")"
python3 "$ARTIFACT_HELPER" disk-gate --path "$RELEASE_ROOT" --archive-size "$(stat -c %s "$ARTIFACT_PATH")" --extracted-size "$EXTRACTED_SIZE" --docker-headroom "${NURA_DOCKER_BUILD_HEADROOM_BYTES:-1073741824}" --reserve-bytes "${NURA_DISK_RESERVE_BYTES:-536870912}" --required-inodes "$((FILE_COUNT * 3 + 1024))"
if [[ "$(stat -c %d "$INCOMING_ROOT")" != "$(stat -c %d "$RELEASE_ROOT")" ]]; then
  python3 "$ARTIFACT_HELPER" disk-gate --path "$INCOMING_ROOT" --archive-size 0 --extracted-size 0 --docker-headroom 0 --reserve-bytes "${NURA_DISK_RESERVE_BYTES:-536870912}" --required-inodes 128
fi

readonly RUN_ID="${GITHUB_RUN_ID:-manual}-${GITHUB_RUN_ATTEMPT:-0}"
STAGING_PATH="$STAGING_DIR/$TARGET_SHA-$RUN_ID-$(date +%s%N)"
python3 "$ARTIFACT_HELPER" extract --archive "$ARTIFACT_PATH" --checksum "$CHECKSUM_PATH" --manifest "$MANIFEST_PATH" --target-sha "$TARGET_SHA" --staging "$STAGING_PATH"
readonly TARGET_RELEASE="$(python3 "$ARTIFACT_HELPER" finalize --staging "$STAGING_PATH" --releases-root "$RELEASES_DIR" --target-sha "$TARGET_SHA")"
STAGING_PATH=""

readonly CREATED_LABEL="$(git -C "$REPO_ROOT" show -s --format=%cI "$TARGET_SHA")"
readonly SOURCE_LABEL="https://github.com/usoltvas870/NURA"
git -C "$REPO_ROOT" archive --format=tar "$TARGET_SHA:nura_app" | docker build --pull=false --tag "$IMAGE_TAG" \
  --label "org.opencontainers.image.revision=$TARGET_SHA" \
  --label "org.opencontainers.image.source=$SOURCE_LABEL" \
  --label "org.opencontainers.image.created=$CREATED_LABEL" -
TARGET_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE_TAG")"
readonly IMAGE_LABELS="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}|{{index .Config.Labels "org.opencontainers.image.source"}}|{{index .Config.Labels "org.opencontainers.image.created"}}' "$IMAGE_TAG")"
[[ "$IMAGE_LABELS" == "$TARGET_SHA|$SOURCE_LABEL|$CREATED_LABEL" ]] || fail "application image OCI labels mismatch"
export TARGET_IMAGE_ID

PREVIOUS_RELEASE_PATH="$RELEASES_DIR/$CURRENT_SHA"
write_state activating "" "" "$CURRENT_SHA"
COMPOSE_OVERRIDE="$(mktemp "${TMPDIR:-/tmp}/nura-target-compose.XXXXXX.yml")"
compose_override_for_map "$COMPOSE_OVERRIDE" "$RELEASE_STATE_DIR/$TARGET_SHA.json"
APP_MUTATED=1
run_compose up -d --no-build --no-deps --wait --wait-timeout 180 "${APPLICATION_SERVICES[@]}"
verify_application_fleet "$IMAGE_TAG" "$TARGET_IMAGE_ID" "$TARGET_SHA"
verify_data_services

python3 "$ARTIFACT_HELPER" switch-current --current "$CURRENT_LINK" --target "$TARGET_RELEASE"
STATIC_SWITCHED=1
public_smoke "$TARGET_SHA" || fail "public smoke failed after static switch"
write_state successful "" "" "$CURRENT_SHA"
atomic_copy_state "$CURRENT_STATE" "$PREVIOUS_STATE"
atomic_copy_state "$RELEASE_STATE_DIR/$TARGET_SHA.json" "$CURRENT_STATE"
python3 "$ARTIFACT_HELPER" validate-current --current "$CURRENT_LINK" --expected-sha "$TARGET_SHA" >/dev/null

SUCCESS=1
log "coordinated activation completed at $TARGET_SHA"
log "static staging rename and current symlink replacement are filesystem-atomic; Docker and database are not"
log "retention cleanup is best-effort under the common lock"
if CLEANUP_PLAN="$(python3 - "$RELEASES_DIR" "$STAGING_DIR" "$RELEASE_STATE_DIR" "$CURRENT_STATE" <<'PY'
import json, pathlib, shutil, sys, time
releases, staging, records, current_path = map(pathlib.Path, sys.argv[1:])
current=json.load(open(current_path,encoding="utf-8")); protected={current["sha"]}; cursor=current
for _ in range(2):
    sha=cursor.get("previous_successful_sha")
    if not sha: break
    if sha in protected: raise SystemExit("release state lineage contains a cycle")
    protected.add(sha); path=records/f"{sha}.json"
    if not path.is_file(): break
    cursor=json.load(open(path,encoding="utf-8"))
for path in releases.iterdir():
    if path.is_symlink() or not path.is_dir() or path.name in protected: continue
    if len(path.name)!=40 or not all(c in "0123456789abcdef" for c in path.name): continue
    record=records/f"{path.name}.json"
    if record.is_file() and json.load(open(record,encoding="utf-8")).get("legacy"): continue
    shutil.rmtree(path); print(f"IMAGE {path.name}")
failed=sorted((p for p in staging.iterdir() if p.is_dir() and not p.is_symlink() and time.time()-p.stat().st_mtime >= 7*86400), key=lambda p:p.stat().st_mtime, reverse=True)
for path in failed[2:]: shutil.rmtree(path)
cutoff=time.time()-30*86400
for path in records.glob("*.json"):
    if path.stem in protected: continue
    value=json.load(open(path,encoding="utf-8"))
    if value.get("legacy") or path.stat().st_mtime >= cutoff: continue
    path.unlink()
PY
)"; then
  CLEANUP_FAILED=0
  while read -r kind sha; do
    [[ -n "$kind" ]] || continue
    if [[ "$kind" != IMAGE || ! "$sha" =~ $SHA_PATTERN ]]; then
      CLEANUP_FAILED=1
      continue
    fi
    if docker image inspect "nura-release:$sha" >/dev/null 2>&1; then
      docker image rm "nura-release:$sha" >/dev/null || CLEANUP_FAILED=1
    fi
  done <<< "$CLEANUP_PLAN"
  if [[ $CLEANUP_FAILED -ne 0 ]]; then
    log "WARNING: retention image cleanup was incomplete; the successful release remains active"
  fi
else
  log "WARNING: retention cleanup failed; successful release remains active and the next disk gate must pass"
fi
