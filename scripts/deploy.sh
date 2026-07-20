#!/bin/bash
set -Eeuo pipefail

echo "ERROR: direct CLI production deploy is disabled." >&2
echo "Use GitHub Actions -> Deploy to production -> Run workflow." >&2
echo "The approved workflow requires production approval and deploys one exact commit SHA." >&2
echo "Direct and emergency CLI deployment are not supported." >&2
exit 64
