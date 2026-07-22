#!/bin/bash
set -Eeuo pipefail

readonly TARGET_SHA='9da6ad8cf0146b26bdd2b60ebf99b54a58ccd532'
readonly EXPECTED_REVISION='d1e2f3a4b5c6'

if [[ $# -ne 3 ]]; then
  echo "usage: deploy_audited_p6b_transition.sh <archive> <checksum> <manifest>" >&2
  exit 2
fi

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly LAUNCHER_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
readonly LAUNCHER_HEAD="$(git -C "$LAUNCHER_ROOT" rev-parse HEAD)"

git -C "$LAUNCHER_ROOT" cat-file -e "$TARGET_SHA^{commit}"
git -C "$LAUNCHER_ROOT" merge-base --is-ancestor "$TARGET_SHA" "$LAUNCHER_HEAD"
[[ -f "$LAUNCHER_ROOT/deploy.sh" && ! -L "$LAUNCHER_ROOT/deploy.sh" ]] \
  || { echo "audited deploy launcher is missing" >&2; exit 2; }

export NURA_PREAPPLIED_MIGRATION_REVISION="$EXPECTED_REVISION"
export NURA_ACKNOWLEDGE_BACKWARD_COMPATIBLE_SCHEMA=1

exec bash "$LAUNCHER_ROOT/deploy.sh" deploy "$TARGET_SHA" "$1" "$2" "$3"
