#!/usr/bin/env bash
# Compiles the video trainer's hashed lock (ADR-0073) into the repository:
#   products/wasifyai-training/trainer/video-requirements-aarch64-apple-darwin.lock
# PyTorch has wheels for Apple silicon, so there is one lock, resolved on the Mac this runs on (see
# lock-trainer.sh for why). Run it when products/wasifyai-training/trainer/video-requirements.in
# changes, and commit the result.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$(uname -s)-$(uname -m)" != "Darwin-arm64" ]; then
  echo "lock-video-trainer.sh must run on an Apple-silicon Mac (this lock is for Apple silicon)" >&2
  exit 1
fi
DIR="products/wasifyai-training/trainer"
uv pip compile "$DIR/video-requirements.in" --python-version 3.12 --generate-hashes --no-header --quiet \
  -o "$DIR/video-requirements-aarch64-apple-darwin.lock"
echo "wrote $DIR/video-requirements-aarch64-apple-darwin.lock"
