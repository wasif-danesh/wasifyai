#!/usr/bin/env bash
# Compiles the writing trainer's hashed lock (ADR-0074) into the repository:
#   products/wasifyai-training/trainer/language-requirements-aarch64-apple-darwin.lock
# mlx-lm runs on MLX, so there is one lock, for Apple silicon, resolved on the Mac this runs on (see
# lock-trainer.sh for why). Run it when products/wasifyai-training/trainer/language-requirements.in
# changes, and commit the result.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$(uname -s)-$(uname -m)" != "Darwin-arm64" ]; then
  echo "lock-language-trainer.sh must run on an Apple-silicon Mac (MLX has no wheels elsewhere for this lock)" >&2
  exit 1
fi
DIR="products/wasifyai-training/trainer"
uv pip compile "$DIR/language-requirements.in" --python-version 3.12 --generate-hashes --no-header --quiet \
  -o "$DIR/language-requirements-aarch64-apple-darwin.lock"
echo "wrote $DIR/language-requirements-aarch64-apple-darwin.lock"
