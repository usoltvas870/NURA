#!/bin/bash
set -Eeuo pipefail

readonly SHA_PATTERN='^[0-9a-f]{40}$'
readonly -a APPLICATION_SERVICES=(api bot celery-worker celery-beat admin-bot)
readonly -a DATA_SERVICES=(postgres redis)
readonly AUDITED_MIGRATION_FROM_SHA='d0d39ae8717ceb0920d98f27dd9092f746755c6c'
readonly AUDITED_MIGRATION_TARGET_SHA='9da6ad8cf0146b26bdd2b60ebf99b54a58ccd532'
readonly AUDITED_MIGRATION_REVISION='d1e2f3a4b5c6'

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

target_alembic_head() {
  python3 - "$REPO_ROOT" "$TARGET_SHA" <<'PY'
import ast
import subprocess
import sys

repo, target = sys.argv[1:]
paths = subprocess.run(
    ["git", "-C", repo, "ls-tree", "-r", "--name-only", target, "--", "nura_app/alembic/versions"],
    check=True,
    capture_output=True,
    text=True,
).stdout.splitlines()
revisions: set[str] = set()
parents: set[str] = set()
for path in paths:
    if not path.endswith(".py"):
        continue
    source = subprocess.run(
        ["git", "-C", repo, "show", f"{target}:{path}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    values: dict[str, object] = {}
    for node in ast.parse(source, filename=path).body:
        name = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, value = node.target.id, node.value
        if name in {"revision", "down_revision"} and value is not None:
            values[name] = ast.literal_eval(value)
    revision = values.get("revision")
    down_revision = values.get("down_revision")
    if not isinstance(revision, str) or not revision:
        raise SystemExit(f"invalid revision metadata: {path}")
    revisions.add(revision)
    if isinstance(down_revision, str):
        parents.add(down_revision)
    elif isinstance(down_revision, (tuple, list)):
        if not all(isinstance(item, str) for item in down_revision):
            raise SystemExit(f"invalid down_revision metadata: {path}")
        parents.update(down_revision)
    elif down_revision is not None:
        raise SystemExit(f"invalid down_revision metadata: {path}")
heads = revisions - parents
if len(heads) != 1:
    raise SystemExit(f"target must have exactly one Alembic head, found {sorted(heads)}")
print(heads.pop())
PY
}

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
readonly STATE_HELPER="$REPO_ROOT/scripts/prepare_atomic_release_host.py"
readonly IMAGE_TAG="nura-release:$TARGET_SHA"
readonly SOURCE_LABEL="https://github.com/usoltvas870/NURA"

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
readonly CURRENT_SHA="$(python3 - "$CURRENT_STATE" "$PREVIOUS_STATE" <<'PY'
import json, pathlib, re, sys
state = json.load(open(sys.argv[1], encoding="utf-8"))
sha = state.get("sha", "")
if state.get("status") != "successful" or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
    raise SystemExit("current release state is not successful and exact")
history=state.get("activation_history",[])
if not isinstance(history,list) or len(history)>2: raise SystemExit("current activation_history is invalid")
if any(not isinstance(item,str) or re.fullmatch(r"[0-9a-f]{40}",item) is None for item in history):
    raise SystemExit("current activation_history contains an invalid SHA")
if len(history)!=len(set(history)) or sha in history: raise SystemExit("current activation_history contains duplicate or self SHA")
previous=pathlib.Path(sys.argv[2])
if history:
    if not previous.is_file() or previous.is_symlink(): raise SystemExit("previous state pointer is missing for activation_history")
    if json.load(previous.open(encoding="utf-8")).get("sha")!=history[0]:
        raise SystemExit("previous state pointer does not match activation_history[0]")
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
  local status="$1" failure_stage="${2:-}" failure_reason="${3:-}" previous_sha="${4:-$CURRENT_SHA}" compensation_verified="${5:-false}"
  TARGET_STATUS="$status" FAILURE_STAGE="$failure_stage" FAILURE_REASON="$failure_reason" \
  PREVIOUS_SHA_VALUE="$previous_sha" IMAGE_ID_VALUE="${TARGET_IMAGE_ID:-}" \
  COMPENSATION_VERIFIED="$compensation_verified" RELEASE_PATH_VALUE="$TARGET_RELEASE" \
  OCI_CREATED_VALUE="$CREATED_LABEL" WORKFLOW_RUN_VALUE="${GITHUB_RUN_ID:-}" \
  python3 - "$RELEASE_STATE_DIR/$TARGET_SHA.json" "$CURRENT_STATE" "$STATE_HELPER" <<'PY'
import importlib.util, json, os, pathlib, re, tempfile, time, sys
path = pathlib.Path(__import__("sys").argv[1])
current = json.load(open(sys.argv[2], encoding="utf-8"))
spec=importlib.util.spec_from_file_location("release_state_helper",sys.argv[3]); helper=importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
path.parent.mkdir(parents=True, exist_ok=True)
sha = path.stem
image_tag = f"nura-release:{sha}"
services = ["api", "bot", "celery-worker", "celery-beat", "admin-bot"]
immutable = {
    "sha": sha, "static_release_path": os.environ["RELEASE_PATH_VALUE"],
    "artifact_sha256": os.environ.get("ARTIFACT_DIGEST", ""),
    "public_manifest_sha256": os.environ.get("PUBLIC_MANIFEST_DIGEST", ""),
    "application_image_tag": image_tag, "application_image_id": os.environ.get("IMAGE_ID_VALUE", ""),
    "oci_revision": sha, "oci_source": "https://github.com/usoltvas870/NURA",
    "oci_created": os.environ["OCI_CREATED_VALUE"],
    "per_service_image_mapping": {name: image_tag for name in services},
    "per_service_image_ids": {name: os.environ.get("IMAGE_ID_VALUE", "") for name in services},
    "migration_delta": False,
}
value = json.load(path.open(encoding="utf-8")) if path.is_file() and not path.is_symlink() else {}
existing = bool(value)
old_history=value.get("activation_history",[])
if not isinstance(old_history,list) or len(old_history)>2 or len(old_history)!=len(set(old_history)):
    raise SystemExit("target activation_history is invalid")
if any(not isinstance(item,str) or re.fullmatch(r"[0-9a-f]{40}",item) is None for item in old_history) or sha in old_history:
    raise SystemExit("target activation_history contains invalid or self SHA")
for key, expected in immutable.items():
    if existing and value.get(key) != expected:
        raise SystemExit(f"immutable release provenance mismatch: {key}")
value.update(immutable)
previous = os.environ.get("PREVIOUS_SHA_VALUE") or None
if previous == sha:
    raise SystemExit("refusing to create a self-referential release lineage")
history=helper.next_activation_history(current,sha)
value.update({
    "schema": 2, "status": os.environ["TARGET_STATUS"],
    "previous_successful_sha": os.environ.get("PREVIOUS_SHA_VALUE") or None,
    "activation_history": history,
    "activation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "workflow_run_id": os.environ.get("WORKFLOW_RUN_VALUE") or None,
    "rollback_eligibility": os.environ["TARGET_STATUS"] in {"successful", "rolled_back"},
    "compensation_verified": os.environ["COMPENSATION_VERIFIED"] == "true",
    "failure_stage": os.environ.get("FAILURE_STAGE") or None,
    "failure_reason": (os.environ.get("FAILURE_REASON") or "")[:500] or None,
})
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

verify_state_pointers() {
  python3 - "$CURRENT_STATE" "$PREVIOUS_STATE" <<'PY'
import json, pathlib, re, sys
current=json.load(open(sys.argv[1],encoding="utf-8")); history=current.get("activation_history",[])
if not isinstance(history,list) or len(history)>2 or len(history)!=len(set(history)):
    raise SystemExit("current activation_history is invalid after state update")
if any(not isinstance(item,str) or re.fullmatch(r"[0-9a-f]{40}",item) is None for item in history) or current.get("sha") in history:
    raise SystemExit("current activation_history contains invalid or self SHA after state update")
previous=pathlib.Path(sys.argv[2])
if history and (not previous.is_file() or previous.is_symlink() or json.load(previous.open(encoding="utf-8")).get("sha")!=history[0]):
    raise SystemExit("previous.json does not match activation_history[0]")
PY
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
import json, os, pathlib, time, sys
path=pathlib.Path(sys.argv[1]); path.parent.mkdir(parents=True,exist_ok=True)
value={"schema":1,"target_sha":path.name.split("-")[2],"status":"recovery_required","original_exit":os.environ["ORIGINAL_EXIT"],"recorded_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())}
try: fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o640)
except FileExistsError: raise SystemExit("recovery evidence already exists; refusing overwrite")
with os.fdopen(fd,"w",encoding="utf-8") as stream: json.dump(value,stream,sort_keys=True,separators=(",",":")); stream.write("\n")
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
TARGET_RELEASE=""
TARGET_IMAGE_ID=""
CREATED_LABEL=""
CANDIDATE_TAG=""
STATE_STAGED=0
APP_MUTATED=0
STATIC_SWITCHED=0
SUCCESS=0
PREVIOUS_RELEASE_PATH=""
TARGET_STATE_SNAPSHOT=""
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
      if [[ "$COMMAND" == rollback && -n "$TARGET_STATE_SNAPSHOT" ]] && \
        ! atomic_copy_state "$TARGET_STATE_SNAPSHOT" "$RELEASE_STATE_DIR/$TARGET_SHA.json"; then compensation_ok=0; fi
    fi
    if [[ $compensation_ok -eq 1 && "$COMMAND" == deploy && $STATE_STAGED -eq 1 ]]; then
      write_state failed "activation" "verified automatic compensation after exit $exit_code" "$CURRENT_SHA" true || compensation_ok=0
    fi
    if [[ $compensation_ok -ne 1 ]]; then
      write_recovery_required "$exit_code" || true
      log "ERROR: automatic compensation could not prove a coherent release; operator recovery is required"
      exit_code=2
    elif [[ "$COMMAND" == deploy && $STATE_STAGED -eq 0 ]] && \
      { [[ -e "$TARGET_RELEASE" || -L "$TARGET_RELEASE" ]] || docker image inspect "$IMAGE_TAG" >/dev/null 2>&1; }; then
      write_recovery_required "$exit_code" || true
      log "ERROR: immutable release material exists without staged provenance; operator recovery is required"
      exit_code=2
    fi
  fi
  cleanup_incoming "$SUCCESS" || log "WARNING: incoming artifact cleanup was incomplete"
  [[ -z "$STAGING_PATH" || ! -d "$STAGING_PATH" ]] || true
  [[ -z "$COMPOSE_OVERRIDE" ]] || rm -f -- "$COMPOSE_OVERRIDE"
  if [[ -n "$CANDIDATE_TAG" ]] && docker image inspect "$CANDIDATE_TAG" >/dev/null 2>&1; then
    docker image rm "$CANDIDATE_TAG" >/dev/null || true
  fi
  rm -f -- "$PREVIOUS_STATE_FILE"
  [[ -z "$TARGET_STATE_SNAPSHOT" ]] || rm -f -- "$TARGET_STATE_SNAPSHOT"
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
  TARGET_STATE_SNAPSHOT="$(mktemp "${TMPDIR:-/tmp}/nura-target-state.XXXXXX.json")"
  install -m 0640 "$TARGET_STATE" "$TARGET_STATE_SNAPSHOT"
  python3 - "$CURRENT_STATE" "$TARGET_STATE" <<'PY'
import json, re, sys
current = json.load(open(sys.argv[1], encoding="utf-8")); target = json.load(open(sys.argv[2], encoding="utf-8"))
if target.get("status") not in {"successful", "rolled_back"} or not target.get("rollback_eligibility"):
    raise SystemExit("rollback target is not a protected successful release")
if target.get("migration_delta") is not False:
    raise SystemExit("schema-incompatible release cannot be rolled back automatically")
target_history=target.get("activation_history",[])
if not isinstance(target_history,list) or len(target_history)>2 or len(target_history)!=len(set(target_history)):
    raise SystemExit("rollback target activation_history is invalid")
if any(not isinstance(item,str) or re.fullmatch(r"[0-9a-f]{40}",item) is None for item in target_history) or target.get("sha") in target_history:
    raise SystemExit("rollback target activation_history contains invalid or self SHA")
if target.get("sha") not in current.get("activation_history",[]):
    raise SystemExit("rollback target is outside current activation_history")
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
  python3 - "$TARGET_STATE" "$PREVIOUS_STATE_FILE" "$STATE_HELPER" <<'PY'
import importlib.util, json, os, sys, tempfile
p=sys.argv[1]; v=json.load(open(p,encoding="utf-8")); current=json.load(open(sys.argv[2],encoding="utf-8"))
spec=importlib.util.spec_from_file_location("release_state_helper",sys.argv[3]); helper=importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
v.update({"schema":2,"status":"successful","rollback_eligibility":True,"activation_history":helper.next_activation_history(current,v["sha"]),"previous_successful_sha":current["sha"]})
fd,t=tempfile.mkstemp(prefix=".rollback.",dir=os.path.dirname(p))
with os.fdopen(fd,"w",encoding="utf-8") as stream: json.dump(v,stream,sort_keys=True,separators=(",",":")); stream.write("\n")
os.chmod(t,0o640); os.replace(t,p)
PY
  atomic_copy_state "$TARGET_STATE" "$CURRENT_STATE"
  verify_state_pointers
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
if [[ -n "$MIGRATION_OUTPUT" ]]; then
  [[ "$CURRENT_SHA" == "$AUDITED_MIGRATION_FROM_SHA" && "$TARGET_SHA" == "$AUDITED_MIGRATION_TARGET_SHA" ]] \
    || { echo "$MIGRATION_OUTPUT" >&2; fail "migration delta blocks deployment outside the audited transition"; }
  [[ "${NURA_PREAPPLIED_MIGRATION_REVISION:-}" == "$AUDITED_MIGRATION_REVISION" ]] \
    || fail "audited transition requires the exact pre-applied migration revision acknowledgement"
  [[ "${NURA_ACKNOWLEDGE_BACKWARD_COMPATIBLE_SCHEMA:-0}" == 1 ]] \
    || fail "audited transition requires backward-compatible schema acknowledgement"
  readonly TARGET_ALEMBIC_HEAD="$(target_alembic_head)"
  [[ "$TARGET_ALEMBIC_HEAD" == "$AUDITED_MIGRATION_REVISION" ]] \
    || fail "audited migration revision does not equal the target Alembic head"
  readonly DATABASE_ALEMBIC_REVISION="$(
    docker compose --project-directory "$REPO_ROOT/nura_app" -f "$COMPOSE_BASE" exec -T postgres \
      sh -lc 'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -X -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM alembic_version"'
  )"
  [[ "$DATABASE_ALEMBIC_REVISION" == "$AUDITED_MIGRATION_REVISION" ]] \
    || fail "production database is not at the audited target revision"
  log "verified the audited pre-applied backward-compatible migration"
else
  [[ -z "${NURA_PREAPPLIED_MIGRATION_REVISION:-}" ]] \
    || fail "pre-applied migration acknowledgement is invalid without a migration delta"
  [[ "${NURA_ACKNOWLEDGE_BACKWARD_COMPATIBLE_SCHEMA:-0}" == 0 ]] \
    || fail "backward-compatible schema acknowledgement is invalid without a migration delta"
fi

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
TARGET_RELEASE="$RELEASES_DIR/$TARGET_SHA"
CREATED_LABEL="$(git -C "$REPO_ROOT" show -s --format=%cI "$TARGET_SHA")"
readonly TARGET_STATE_FILE="$RELEASE_STATE_DIR/$TARGET_SHA.json"
REUSE_RELEASE=0
if [[ -e "$TARGET_STATE_FILE" || -L "$TARGET_STATE_FILE" ]]; then
  [[ -f "$TARGET_STATE_FILE" && ! -L "$TARGET_STATE_FILE" ]] || fail "release state is not a regular file"
  mapfile -t REUSE_VALUES < <(ARTIFACT_DIGEST="$ARTIFACT_DIGEST" PUBLIC_MANIFEST_DIGEST="$PUBLIC_MANIFEST_DIGEST" \
    python3 - "$TARGET_STATE_FILE" "$TARGET_RELEASE" <<'PY'
import json, os, re, sys
p, expected_path=sys.argv[1:]; value=json.load(open(p,encoding="utf-8")); sha=value.get("sha")
status=value.get("status")
if status not in {"successful","rolled_back","failed"}: raise SystemExit("incomplete release state requires operator recovery")
if status=="failed" and value.get("compensation_verified") is not True: raise SystemExit("failed release is not proven compensated")
history=value.get("activation_history",[])
if not isinstance(history,list) or len(history)>2 or len(history)!=len(set(history)):
    raise SystemExit("target activation_history is invalid")
if any(not isinstance(item,str) or re.fullmatch(r"[0-9a-f]{40}",item) is None for item in history) or sha in history:
    raise SystemExit("target activation_history contains invalid or self SHA")
services={"api","bot","celery-worker","celery-beat","admin-bot"}; tag=f"nura-release:{sha}"
checks={
 "static_release_path":expected_path,"artifact_sha256":os.environ["ARTIFACT_DIGEST"],
 "public_manifest_sha256":os.environ["PUBLIC_MANIFEST_DIGEST"],"application_image_tag":tag,
 "oci_revision":sha,"oci_source":"https://github.com/usoltvas870/NURA","migration_delta":False,
}
for key, expected in checks.items():
    if value.get(key)!=expected: raise SystemExit(f"immutable release provenance mismatch: {key}")
if set(value.get("per_service_image_mapping",{}))!=services or set(value.get("per_service_image_ids",{}))!=services:
    raise SystemExit("immutable service image provenance is incomplete")
if any(v!=tag for v in value["per_service_image_mapping"].values()): raise SystemExit("immutable service image tag mismatch")
image_id=value.get("application_image_id","")
if not image_id.startswith("sha256:") or any(v!=image_id for v in value["per_service_image_ids"].values()):
    raise SystemExit("immutable service image ID mismatch")
created=value.get("oci_created","")
if not created: raise SystemExit("immutable OCI created label is missing")
print(image_id); print(created)
PY
  )
  [[ ${#REUSE_VALUES[@]} -eq 2 ]] || fail "existing release state could not be validated"
  TARGET_IMAGE_ID="${REUSE_VALUES[0]}"
  [[ "${REUSE_VALUES[1]}" == "$CREATED_LABEL" ]] || fail "immutable OCI created label mismatch"
  python3 -c 'import importlib.util,json,sys,pathlib; s=importlib.util.spec_from_file_location("a",sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); manifest=json.load(open(sys.argv[3],encoding="utf-8")); m.verify_release_directory(pathlib.Path(sys.argv[2]),manifest)' "$ARTIFACT_HELPER" "$TARGET_RELEASE" "$MANIFEST_PATH"
  if docker image inspect "$IMAGE_TAG" >/dev/null 2>&1; then
    [[ "$(docker image inspect --format '{{.Id}}' "$IMAGE_TAG")" == "$TARGET_IMAGE_ID" ]] || fail "final release tag conflicts with immutable state"
  else
    docker image inspect "$TARGET_IMAGE_ID" >/dev/null 2>&1 || fail "recorded immutable image ID is unavailable"
    docker image tag "$TARGET_IMAGE_ID" "$IMAGE_TAG"
  fi
  REUSE_RELEASE=1
else
  [[ ! -e "$TARGET_RELEASE" && ! -L "$TARGET_RELEASE" ]] || fail "final static release exists without immutable state; operator recovery is required"
  ! docker image inspect "$IMAGE_TAG" >/dev/null 2>&1 || fail "final image tag exists without immutable state; operator recovery is required"
fi

if [[ $REUSE_RELEASE -eq 0 ]]; then
  STAGING_PATH="$STAGING_DIR/$TARGET_SHA-$RUN_ID-$(date +%s%N)"
  python3 "$ARTIFACT_HELPER" extract --archive "$ARTIFACT_PATH" --checksum "$CHECKSUM_PATH" --manifest "$MANIFEST_PATH" --target-sha "$TARGET_SHA" --staging "$STAGING_PATH"
  TARGET_RELEASE="$(python3 "$ARTIFACT_HELPER" finalize --staging "$STAGING_PATH" --releases-root "$RELEASES_DIR" --target-sha "$TARGET_SHA")"
  STAGING_PATH=""
  CANDIDATE_TAG="nura-release-candidate:$TARGET_SHA-$RUN_ID"
  ! docker image inspect "$CANDIDATE_TAG" >/dev/null 2>&1 || fail "unique candidate image tag already exists"
  git -C "$REPO_ROOT" archive --format=tar "$TARGET_SHA:nura_app" | docker build --pull=false --tag "$CANDIDATE_TAG" \
    --label "org.opencontainers.image.revision=$TARGET_SHA" \
    --label "org.opencontainers.image.source=$SOURCE_LABEL" \
    --label "org.opencontainers.image.created=$CREATED_LABEL" -
  TARGET_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$CANDIDATE_TAG")"
  IMAGE_LABELS="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}|{{index .Config.Labels "org.opencontainers.image.source"}}|{{index .Config.Labels "org.opencontainers.image.created"}}' "$CANDIDATE_TAG")"
  [[ "$IMAGE_LABELS" == "$TARGET_SHA|$SOURCE_LABEL|$CREATED_LABEL" ]] || fail "candidate application image OCI labels mismatch"
  ! docker image inspect "$IMAGE_TAG" >/dev/null 2>&1 || fail "final image tag appeared before immutable publication; operator recovery is required"
  docker image tag "$CANDIDATE_TAG" "$IMAGE_TAG"
fi
[[ "$(docker image inspect --format '{{.Id}}' "$IMAGE_TAG")" == "$TARGET_IMAGE_ID" ]] || fail "final application image ID mismatch"
IMAGE_LABELS="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}|{{index .Config.Labels "org.opencontainers.image.source"}}|{{index .Config.Labels "org.opencontainers.image.created"}}' "$IMAGE_TAG")"
[[ "$IMAGE_LABELS" == "$TARGET_SHA|$SOURCE_LABEL|$CREATED_LABEL" ]] || fail "final application image OCI labels mismatch"
if [[ -n "$CANDIDATE_TAG" ]]; then docker image rm "$CANDIDATE_TAG" >/dev/null; CANDIDATE_TAG=""; fi
export TARGET_IMAGE_ID

PREVIOUS_RELEASE_PATH="$RELEASES_DIR/$CURRENT_SHA"
write_state staged "" "" "$CURRENT_SHA"
STATE_STAGED=1
COMPOSE_OVERRIDE="$(mktemp "${TMPDIR:-/tmp}/nura-target-compose.XXXXXX.yml")"
compose_override_for_map "$COMPOSE_OVERRIDE" "$RELEASE_STATE_DIR/$TARGET_SHA.json"
write_state activating "" "" "$CURRENT_SHA"
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
verify_state_pointers
python3 "$ARTIFACT_HELPER" validate-current --current "$CURRENT_LINK" --expected-sha "$TARGET_SHA" >/dev/null

SUCCESS=1
log "coordinated activation completed at $TARGET_SHA"
log "static staging rename and current symlink replacement are filesystem-atomic; Docker and database are not"
log "retention cleanup is best-effort under the common lock"
if CLEANUP_PLAN="$(python3 - "$RELEASES_DIR" "$STAGING_DIR" "$RELEASE_STATE_DIR" "$CURRENT_STATE" <<'PY'
import json, pathlib, shutil, sys, time
releases, staging, records, current_path = map(pathlib.Path, sys.argv[1:])
current=json.load(open(current_path,encoding="utf-8")); history=current.get("activation_history",[])
if not isinstance(history,list) or len(history)>2 or len(history)!=len(set(history)) or current["sha"] in history:
    raise SystemExit("current activation_history is invalid during retention")
protected={current["sha"],*history}
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
