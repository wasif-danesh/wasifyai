"""`python -m wasifyai_api.comfy_models <models folder> [product] [model id ...]`: fetch an image
or video model's files onto a ComfyUI host (ADR-0097, MV6).

On the web an admin chooses which model Images and Video use (Admin › Media › Models); ComfyUI runs
it from its own models folder, which this fills. With no model ids it lists each model of the
product and what is missing; with ids it shows the size first, then fetches every missing file with
the desktop's own downloader: pinned to a commit, checked by size and SHA-256, continued where it
stopped. A gated repository needs `HF_TOKEN` in the environment (sent only to huggingface.co).
"""

import asyncio
import os
import sys
from pathlib import Path

from wasifyai_api.desktop_models import (
    DownloadError,
    DownloadManager,
    FolderModels,
    load_catalogue,
)

PRODUCTS = ("wasifyai-image", "wasifyai-video")


def _gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


def _products_dir() -> Path:
    return Path(os.environ.get("PRODUCTS_DIR") or Path(__file__).resolve().parents[4] / "products")


async def run(argv: list[str], out=print) -> int:
    if not argv:
        out((__doc__ or "").strip().splitlines()[0])
        return 2
    folder = Path(argv[0])  # `main` expands a leading ~
    products: list[str] = [argv[1]] if len(argv) > 1 else list(PRODUCTS)
    wanted = argv[2:]
    folders = FolderModels(load_catalogue(_products_dir(), products), folder)
    if not wanted:
        for e in folders.catalogue.values():
            missing = sum(f.size for f in e.files if folders.locate(f) is None)
            state = f"missing {_gb(missing)}" if missing else "ready"
            out(f"  {e.id:24} {e.title:28} {state}")
        return 0
    unknown = [w for w in wanted if w not in folders.catalogue]
    if unknown:
        out(f"Not a model of {', '.join(products)}: {', '.join(unknown)}")
        return 2
    manager = DownloadManager(token=os.environ.get("HF_TOKEN") or None)
    status = 0
    for model_id in wanted:
        entry = folders.catalogue[model_id]
        missing = [f for f in entry.files if folders.locate(f) is None]
        if not missing:
            out(f"{entry.title}: ready")
            continue
        out(f"{entry.title}: fetching {len(missing)} files, {_gb(sum(f.size for f in missing))}")
        try:
            d = manager.start(entry, missing, folder)
        except DownloadError as exc:
            out(f"  {exc}")
            status = 1
            continue
        while d.status == "running":
            await asyncio.sleep(2)
            out(f"\r  {d.bytes_done / max(d.bytes_total, 1):6.1%}  {d.current}", end="")
        out("")
        if d.status != "done":
            out(f"  {d.error or d.status}")
            status = 1
    return status


def main() -> None:
    argv = [os.path.expanduser(a) if n == 0 else a for n, a in enumerate(sys.argv[1:])]
    sys.exit(asyncio.run(run(argv, out=lambda *a, **k: print(*a, **k, flush=True))))


if __name__ == "__main__":
    main()
