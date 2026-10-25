#!/usr/bin/env bash
# Compiles the picture trainer's hashed lock (ADR-0073) into the repository:
#   products/wasifyai-training/trainer/requirements-aarch64-apple-darwin.lock
# mflux runs on MLX, so there is one lock, for Apple silicon. It is resolved on the Mac this runs on (uv's
# `aarch64-apple-darwin` target assumes macOS 13 and MLX's wheels need 14). Run it when
# products/wasifyai-training/trainer/requirements.in changes, and commit the result.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$(uname -s)-$(uname -m)" != "Darwin-arm64" ]; then
  echo "lock-trainer.sh must run on an Apple-silicon Mac (MLX has no wheels elsewhere for this lock)" >&2
  exit 1
fi
DIR="products/wasifyai-training/trainer"
uv pip compile "$DIR/requirements.in" --python-version 3.12 --generate-hashes --no-header --quiet \
  -o "$DIR/requirements-aarch64-apple-darwin.lock"
echo "wrote $DIR/requirements-aarch64-apple-darwin.lock"
