#!/usr/bin/env bash
# Compiles the song analysis tool's hashed lock (ADR-0090) into the repository:
#   products/wasifyai-voice/analysis/requirements-aarch64-apple-darwin.lock
# PyTorch has wheels for Apple silicon, so there is one lock, resolved on the Mac this runs on (see
# lock-trainer.sh for why). Run it when products/wasifyai-voice/analysis/requirements.in changes, and
# commit the result.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$(uname -s)-$(uname -m)" != "Darwin-arm64" ]; then
  echo "lock-music-analysis.sh must run on an Apple-silicon Mac (this lock is for Apple silicon)" >&2
  exit 1
fi
DIR="products/wasifyai-voice/analysis"
uv pip compile "$DIR/requirements.in" --python-version 3.12 --generate-hashes --no-header --quiet \
  -o "$DIR/requirements-aarch64-apple-darwin.lock"
echo "wrote $DIR/requirements-aarch64-apple-darwin.lock"
