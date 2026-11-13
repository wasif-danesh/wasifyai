#!/usr/bin/env bash
# Compiles the Indian-language speech engine's hashed lock (docs/voice-languages-plan.md, L5):
#   services/api/src/wasifyai_api/indic_server/indic.lock.txt
# One universal lock for every platform (CUDA wheels on Linux, the CPU on Windows, the graphics chip
# on a Mac), so it can run anywhere. Run it when requirements.in or overrides.txt changes, then put
# the new SHA-256 in the `indic` part of every components/manifests/<platform>.yaml and commit.
set -euo pipefail
cd "$(dirname "$0")/../services/api/src/wasifyai_api/indic_server"
uv pip compile requirements.in --override overrides.txt --universal --python-version 3.12 \
  --generate-hashes --quiet -o indic.lock.txt
if grep -q "git+" indic.lock.txt; then
  echo "the lock names a git requirement, which cannot carry a hash: pin its archive in overrides.txt" >&2
  exit 1
fi
echo "wrote indic.lock.txt, sha256 $(shasum -a 256 indic.lock.txt | cut -d' ' -f1)"
