#!/usr/bin/env bash
set -euo pipefail
DEST="${1:-data/raw/amazon-last-mile}"
mkdir -p "$DEST"
if ! command -v aws >/dev/null 2>&1; then
  echo "AWS CLI is required. Install it, then rerun this command." >&2
  exit 1
fi
aws s3 sync --no-sign-request s3://amazon-last-mile-challenges/almrrc2021/ "$DEST/"
echo "Downloaded under the dataset's CC BY-NC 4.0 license."
