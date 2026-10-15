#!/usr/bin/env bash
# Build the engine bundle the desktop app installs from (ADR-0056, docs/desktop-profile.md):
#
#   engine-bundle/
#     bundle.json         what is in it, with a SHA-256 for every file
#     requirements.lock   every third-party package, pinned, with hashes (from uv.lock)
#     wheels/             our own packages as wheels
#     products/           product config (product.yaml, workflows) for the products the desktop serves
#     comfyui/            a hashed requirements lock per platform for the optional ComfyUI component
#
# The app's provisioner checks each file against bundle.json and installs with `--require-hashes`.
# Usage: scripts/build-engine-bundle.sh [output-dir]    (default: apps/desktop/engine-bundle)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/apps/desktop/engine-bundle}"
PACKAGES="wasifyai-contracts wasifyai-platform-sdk wasifyai-api wasifyai-media-worker wasifyai-image wasifyai-assistant"
PRODUCTS="wasifyai-image wasifyai-assistant"

cd "$ROOT"
rm -rf "$OUT"
mkdir -p "$OUT/wheels" "$OUT/products"

for p in $PACKAGES; do
  echo "building $p"
  uv build --wheel --package "$p" --out-dir "$OUT/wheels" >/dev/null
done

rm -f "$OUT/wheels/.gitignore"  # uv writes one; it is not part of the bundle
echo "locking third-party packages"
uv export --package wasifyai-api --extra desktop --no-emit-workspace --no-dev --hashes \
  --format requirements-txt --no-header --quiet > "$OUT/requirements.lock"

# The optional ComfyUI component (ADR-0059): a hashed lock per platform the manifest lists, compiled from the
# requirements of the pinned release. Torch is not pinned by ComfyUI, so the version released with the app
# is the one resolved here.
MANIFEST="$ROOT/apps/desktop/src-tauri/engine-manifest.json"
COMFY_VERSION="$(uv run --no-project python -c "import json,sys; print(json.load(open(sys.argv[1]))['comfyui']['version'])" "$MANIFEST")"
COMFY_PLATFORMS="$(uv run --no-project python -c "import json,sys; print(' '.join(json.load(open(sys.argv[1]))['comfyui']['platforms']))" "$MANIFEST")"
PY_VERSION="$(uv run --no-project python -c "import json,sys; print(json.load(open(sys.argv[1]))['python']['version'])" "$MANIFEST")"
mkdir -p "$OUT/comfyui"
COMFY_REQ="$OUT/comfyui/requirements.txt"
curl -fsSL "https://raw.githubusercontent.com/comfyanonymous/ComfyUI/v${COMFY_VERSION}/requirements.txt" -o "$COMFY_REQ"
for target in $COMFY_PLATFORMS; do
  echo "locking ComfyUI $COMFY_VERSION for $target"
  uv pip compile "$COMFY_REQ" --python-version "${PY_VERSION%.*}" --python-platform "$target" \
    --generate-hashes --no-header --quiet -o "$OUT/comfyui/requirements-$target.lock"
done
rm -f "$COMFY_REQ"

for p in $PRODUCTS; do
  mkdir -p "$OUT/products/$p"
  cp "products/$p/product.yaml" "$OUT/products/$p/"
  [ -f "products/$p/models.yaml" ] && cp "products/$p/models.yaml" "$OUT/products/$p/"
  [ -d "products/$p/workflows" ] && cp -R "products/$p/workflows" "$OUT/products/$p/workflows"
done

uv run --no-project python - "$OUT" "$PRODUCTS" "$COMFY_VERSION" <<'PY'
import hashlib, json, pathlib, sys

out = pathlib.Path(sys.argv[1])
products = sys.argv[2].split()
comfy_version = sys.argv[3]


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def entry(path: pathlib.Path) -> dict:
    return {"file": path.relative_to(out).as_posix(), "sha256": sha256(path), "size": path.stat().st_size}


bundle = {
    "schema": 1,
    "requirements": entry(out / "requirements.lock"),
    "wheels": [entry(w) for w in sorted((out / "wheels").glob("*.whl"))],
    "products": products,
    "product_files": [
        entry(f) for f in sorted((out / "products").rglob("*")) if f.is_file()
    ],
    "comfyui": {
        "version": comfy_version,
        "locks": {
            f.name.removeprefix("requirements-").removesuffix(".lock"): entry(f)
            for f in sorted((out / "comfyui").glob("requirements-*.lock"))
        },
    },
}
(out / "bundle.json").write_text(json.dumps(bundle, indent=2) + "\n")
print(f"{len(bundle['wheels'])} wheels, {len(bundle['product_files'])} product files")
PY
echo "engine bundle: $OUT"
