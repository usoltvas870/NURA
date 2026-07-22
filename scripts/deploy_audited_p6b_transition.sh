#!/bin/bash
set -Eeuo pipefail

readonly TARGET_SHA='9da6ad8cf0146b26bdd2b60ebf99b54a58ccd532'
readonly EXPECTED_REVISION='d1e2f3a4b5c6'
readonly ENGINE_COMMIT='f8716a7ca08190255a58b42fa420ce6aacc793e7'
readonly ENGINE_BLOB='832d773a24d9fcbaaec22ec64138a71705874684'
readonly ARTIFACT_HELPER_BLOB='b2ef31a30252a476faf21e3b41409b633aa33d58'
readonly STATIC_HELPER_BLOB='e42eb64abed196aaf1d529518269936ad5ed990d'

if [[ $# -ne 3 ]]; then
  echo "usage: deploy_audited_p6b_transition.sh <archive> <checksum> <manifest>" >&2
  exit 2
fi

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly LAUNCHER_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
git -C "$LAUNCHER_ROOT" cat-file -e "$ENGINE_COMMIT^{commit}"
git -C "$LAUNCHER_ROOT" merge-base --is-ancestor "$TARGET_SHA" "$ENGINE_COMMIT"
umask 077
readonly ENGINE_DIR="$(mktemp -d "${TMPDIR:-/var/tmp}/nura-p6b-engine.XXXXXX")"
readonly ENGINE_FILE="$ENGINE_DIR/deploy.sh"
cleanup() {
  local status=$?
  trap - EXIT
  rm -f -- "$ENGINE_FILE" "$ENGINE_DIR/build_release_artifact.py" "$ENGINE_DIR/deploy_static_release.py" || true
  rmdir -- "$ENGINE_DIR/__pycache__" 2>/dev/null || true
  rmdir -- "$ENGINE_DIR" 2>/dev/null || true
  exit "$status"
}
trap cleanup EXIT

extract_blob() {
  local source_path="$1" expected_blob="$2" destination="$3"
  [[ "$(git -C "$LAUNCHER_ROOT" rev-parse "$ENGINE_COMMIT:$source_path")" == "$expected_blob" ]] \
    || { echo "audited deploy component provenance mismatch: $source_path" >&2; exit 2; }
  git -C "$LAUNCHER_ROOT" show "$ENGINE_COMMIT:$source_path" > "$destination"
  [[ "$(git hash-object "$destination")" == "$expected_blob" ]] \
    || { echo "audited deploy component extraction mismatch: $source_path" >&2; exit 2; }
}

extract_blob deploy.sh "$ENGINE_BLOB" "$ENGINE_FILE"
extract_blob scripts/build_release_artifact.py "$ARTIFACT_HELPER_BLOB" "$ENGINE_DIR/build_release_artifact.py"
extract_blob scripts/deploy_static_release.py "$STATIC_HELPER_BLOB" "$ENGINE_DIR/deploy_static_release.py"

export NURA_PREAPPLIED_MIGRATION_REVISION="$EXPECTED_REVISION"
export NURA_ACKNOWLEDGE_BACKWARD_COMPATIBLE_SCHEMA=1
export NURA_AUDITED_ENGINE_HELPER_ROOT="$ENGINE_DIR"
export PYTHONDONTWRITEBYTECODE=1

bash "$ENGINE_FILE" deploy "$TARGET_SHA" "$1" "$2" "$3"
