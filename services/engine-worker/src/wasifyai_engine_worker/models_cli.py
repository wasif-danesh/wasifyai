"""`python -m wasifyai_engine_worker.models_cli [model id ...]`: list the speech models, or
fetch some into the worker's data folder. The size is shown first and the download is checked by
the same code as the desktop app's. Until the web has an admin screen for it (ADR-0087, P5) this
is how a model gets onto the machine that runs the worker."""

import asyncio
import sys
from pathlib import Path
from typing import Any

from wasifyai_api.config import get_settings
from wasifyai_api.local_speech import build_local_engine
from wasifyai_platform_sdk import VoiceModel


def _gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


LIPSYNC_ENGINE = "lipsync-engine"


async def install_lipsync_engine(engine: Any) -> int:
    """MuseTalk's code and environment (the model files are fetched as `musetalk-v15`)."""
    installer = engine.lipsync_sidecar.installer
    plan = installer.plan()
    if engine.lipsync_sidecar.installed:
        print("lip sync engine: already set up")
        return 0
    if not plan["supported"]:
        print("lip sync engine: there is none for this kind of computer yet")
        return 1
    print(f"lip sync engine: setting up MuseTalk and its environment ({_gb(plan['bytes'])})")
    try:
        installer.start(plan["bytes"])
    except Exception as e:
        print(f"lip sync engine: {e}")
        return 1
    while installer.running:
        p = installer.progress
        print(f"\r  {p.step or ''}: {p.message}", end="", flush=True)
        await asyncio.sleep(2)
    print()
    ok = installer.progress.state == "ready"
    print("lip sync engine: ready" if ok else f"lip sync engine: {installer.progress.message}")
    return 0 if ok else 1


async def get(ids: list[str]) -> int:
    api = get_settings()
    engine = build_local_engine(api, Path(api.products_dir))
    service = engine.models_service
    wants_engine = LIPSYNC_ENGINE in ids
    ids = [i for i in ids if i != LIPSYNC_ENGINE]
    if not ids and not wants_engine:
        print("Models this worker can fetch (state on this machine):")
        for m in engine.models(None):
            size = _gb(int(m["bytes_missing"])) if m["bytes_missing"] else ""
            print(f"  {m['id']:34} {m['state']:14} {size}")
        return 0
    status = 0
    for model_id in ids:
        entry = service.catalogue.get(model_id)
        voice: VoiceModel | None = getattr(entry, "voice", None)
        if entry is None or voice is None:
            print(f"{model_id}: not a speech model of this app")
            status = 1
            continue
        missing = [f for f in entry.files if service.locate(f) is None]
        if not missing:
            print(f"{model_id}: already here")
            continue
        total = sum(f.size for f in missing)
        print(f"{model_id}: fetching {_gb(total)} from {entry.source} ({entry.licence})")
        d = service.downloads.start(entry, missing, service.models_dir)
        while d.status == "running":
            print(
                f"\r  {d.bytes_done / max(1, d.bytes_total):6.1%}  {d.current}", end="", flush=True
            )
            await asyncio.sleep(1)
        print()
        if d.status != "done":
            print(f"{model_id}: {d.error or d.status}")
            status = 1
    if wants_engine:
        status = max(status, await install_lipsync_engine(engine))
    if engine.install is None:
        print(
            "The speech runtime (audio.cpp) is not set up here: set it up in the desktop app first."
        )
    return status


def main() -> None:
    sys.exit(asyncio.run(get(sys.argv[1:])))


if __name__ == "__main__":
    main()
