#!/usr/bin/env bash
# Compiles the coding engine's hashed lock (ADR-0102, decision 1) into the repository:
#   services/coding-engine/requirements-aarch64-apple-darwin.lock
# The four OpenHands packages at the one version in services/coding-engine/VERSION are resolved for
# Python 3.12 on an Apple-silicon Mac, then every package named in services/coding-engine/leave-out.txt
# is taken out: the app installs the list with --no-deps, so what is not listed is not fetched.
# Run it when VERSION or leave-out.txt changes, put the new SHA-256 in the `coding` component of
# services/api/src/wasifyai_api/components/manifests/darwin-arm64.yaml, run `make test-coding`
# (the server and a real start must still work on the trimmed list) and commit the result.
set -euo pipefail
cd "$(dirname "$0")/../services/coding-engine"

TARGET="aarch64-apple-darwin"
VERSION="$(tr -d '[:space:]' < VERSION)"
FULL="$(mktemp)"
trap 'rm -f "$FULL"' EXIT

printf 'openhands-agent-server==%s\nopenhands-sdk==%s\nopenhands-tools==%s\nopenhands-workspace==%s\n' \
  "$VERSION" "$VERSION" "$VERSION" "$VERSION" |
  uv pip compile - --python-version 3.12 --python-platform "$TARGET" --generate-hashes --no-header \
    --no-annotate --quiet -o "$FULL"
if grep -q "git+" "$FULL"; then
  echo "the lock names a git requirement, which cannot carry a hash" >&2
  exit 1
fi

uv run --no-project python - "$FULL" leave-out.txt "requirements-$TARGET.lock" "$VERSION" <<'PY'
import pathlib
import re
import sys

full, leave_out, out, version = sys.argv[1:5]


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


drop = {
    norm(line.split("#")[0].strip())
    for line in pathlib.Path(leave_out).read_text().splitlines()
    if line.split("#")[0].strip()
}
blocks = re.split(r"\n(?=\S)", pathlib.Path(full).read_text().strip())
kept, dropped = [], set()
for block in blocks:
    name = norm(re.match(r"[A-Za-z0-9_.\-]+", block).group(0))
    if name in drop:
        dropped.add(name)
    else:
        kept.append(block)
missing = sorted(drop - dropped)
if missing:
    sys.exit(f"leave-out.txt names packages the lock does not have: {', '.join(missing)}")
head = (
    f"# The coding engine's packages: OpenHands' Agent Server {version} for Python 3.12 on an Apple-silicon Mac,\n"
    "# without the packages named in leave-out.txt. Written by scripts/lock-coding-engine.sh; do not edit.\n"
)
pathlib.Path(out).write_text(head + "\n".join(kept) + "\n")
print(f"{len(kept)} packages kept, {len(dropped)} left out")
PY
echo "wrote services/coding-engine/requirements-$TARGET.lock, sha256 $(shasum -a 256 "requirements-$TARGET.lock" | cut -d' ' -f1)"
