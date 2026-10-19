#!/usr/bin/env bash
# Compiles the notebooks' document reader lock files (ADR-0065 decision 7) into the repository:
#   products/wasifyai-notebooks/reader/requirements-<target>.lock
# One hashed lock per platform. The engine installs the lock for its own platform with --require-hashes, from
# a development checkout and from the engine bundle alike (scripts/build-engine-bundle.sh copies these files).
# Run it when products/wasifyai-notebooks/reader/requirements.in changes or the Python version in
# apps/desktop/src-tauri/engine-manifest.json moves, and commit the result.
set -euo pipefail
cd "$(dirname "$0")/.."

MANIFEST="apps/desktop/src-tauri/engine-manifest.json"
PY_VERSION="$(uv run --no-project python -c "import json,sys; print(json.load(open(sys.argv[1]))['python']['version'])" "$MANIFEST")"
DIR="products/wasifyai-notebooks/reader"

# Intel Macs are left out (torch no longer ships for them).
READER_PLATFORMS="aarch64-apple-darwin x86_64-unknown-linux-gnu aarch64-unknown-linux-gnu x86_64-pc-windows-msvc"
for target in $READER_PLATFORMS; do
  echo "locking the document reader for $target"
  # PyPI's Linux torch brings about 3 GB of CUDA wheels; the CPU build comes from PyTorch's own index
  # (the installer passes the same index, see reader_install.py)
  EXTRA=""
  case "$target" in
    *linux*) EXTRA="--extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match" ;;
  esac
  # shellcheck disable=SC2086
  uv pip compile "$DIR/requirements.in" --python-version "${PY_VERSION%.*}" \
    --python-platform "$target" --generate-hashes --no-header --quiet $EXTRA \
    -o "$DIR/requirements-$target.lock"
done
echo "wrote $(ls "$DIR"/requirements-*.lock | wc -l | tr -d ' ') lock files in $DIR"
