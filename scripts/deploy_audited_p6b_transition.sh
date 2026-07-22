#!/bin/bash
set -Eeuo pipefail

readonly TARGET_SHA='9da6ad8cf0146b26bdd2b60ebf99b54a58ccd532'
readonly EXPECTED_REVISION='d1e2f3a4b5c6'
readonly ENGINE_COMMIT='a8f9140795255804afe1bc46924d996a57b81d45'
readonly ENGINE_BLOB='71a1e91374483876a1059ddec6d6c6b32c41df67'

if [[ $# -ne 3 ]]; then
  echo "usage: deploy_audited_p6b_transition.sh <archive> <checksum> <manifest>" >&2
  exit 2
fi

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly LAUNCHER_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
git -C "$LAUNCHER_ROOT" cat-file -e "$ENGINE_COMMIT^{commit}"
git -C "$LAUNCHER_ROOT" merge-base --is-ancestor "$TARGET_SHA" "$ENGINE_COMMIT"
[[ "$(git -C "$LAUNCHER_ROOT" rev-parse "$ENGINE_COMMIT:deploy.sh")" == "$ENGINE_BLOB" ]] \
  || { echo "audited deploy engine provenance mismatch" >&2; exit 2; }

umask 077
readonly ENGINE_FILE="$(mktemp "${TMPDIR:-/var/tmp}/nura-p6b-engine.XXXXXX")"
trap 'rm -f -- "$ENGINE_FILE"' EXIT
git -C "$LAUNCHER_ROOT" show "$ENGINE_COMMIT:deploy.sh" > "$ENGINE_FILE"
[[ "$(git hash-object "$ENGINE_FILE")" == "$ENGINE_BLOB" ]] \
  || { echo "audited deploy engine extraction mismatch" >&2; exit 2; }

export NURA_PREAPPLIED_MIGRATION_REVISION="$EXPECTED_REVISION"
export NURA_ACKNOWLEDGE_BACKWARD_COMPATIBLE_SCHEMA=1

bash "$ENGINE_FILE" deploy "$TARGET_SHA" "$1" "$2" "$3"
