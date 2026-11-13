#!/usr/bin/env bash
# Compiles the decision trainer's hashed locks (ADR-0075) into the repository:
#   products/wasifyai-training/trainer/decision-requirements-<target>.lock
# One lock per platform the trainer runs on: a Mac with Apple silicon (PyTorch on the graphics chip), and
# Windows and Linux with an NVIDIA graphics card (PyTorch's CUDA 12.8 build from PyTorch's own index; the
# engine installs with the same --torch-backend, see CUDA_BACKEND in decision_setup.py). CUDA 12.8 covers
# cards from Volta to the RTX 50 series on drivers 570 and later.
# The Mac lock is resolved natively, on an Apple-silicon Mac: resolving it for the target from elsewhere
# assumes an older macOS and picks older wheels. The other targets resolve from any machine.
# Run it when products/wasifyai-training/trainer/decision-requirements.in changes, and commit the result.
set -euo pipefail
cd "$(dirname "$0")/.."

DIR="products/wasifyai-training/trainer"
CUDA_BACKEND="cu128"  # keep in step with CUDA_BACKEND in services/api/src/wasifyai_api/decision_setup.py

if [ "$(uname -s)-$(uname -m)" = "Darwin-arm64" ]; then
  echo "locking the decision trainer for aarch64-apple-darwin"
  uv pip compile "$DIR/decision-requirements.in" --python-version 3.12 --generate-hashes --no-header \
    --quiet -o "$DIR/decision-requirements-aarch64-apple-darwin.lock"
else
  echo "not on an Apple-silicon Mac: the Mac lock is left as it is" >&2
fi
for target in x86_64-unknown-linux-gnu aarch64-unknown-linux-gnu x86_64-pc-windows-msvc; do
  echo "locking the decision trainer for $target"
  uv pip compile "$DIR/decision-requirements.in" --python-version 3.12 --python-platform "$target" \
    --torch-backend "$CUDA_BACKEND" --generate-hashes --no-header --quiet \
    -o "$DIR/decision-requirements-$target.lock"
done
echo "wrote $(ls "$DIR"/decision-requirements-*.lock | wc -l | tr -d ' ') lock files in $DIR"
