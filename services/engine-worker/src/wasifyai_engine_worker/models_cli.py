"""`python -m wasifyai_engine_worker.models_cli [model id ...]`: list the speech models, or
fetch some into the worker's data folder. The size is shown first and the download is checked by
the same code as the desktop app's. The web's Workers page (ADR-0087, P5) does the same through
`admin.*` jobs; this is for a machine with no signed-in admin to hand."""

import asyncio
import sys
from pathlib import Path

from wasifyai_api.config import get_settings
from wasifyai_api.local_speech import build_local_engine

from wasifyai_engine_worker.admin import AdminComponent
from wasifyai_engine_worker.handlers import Failed

LIPSYNC_ENGINE = "lipsync-engine"


def _gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


async def _show(fraction: float, label: str) -> None:
    print(f"\r  {fraction:6.1%}  {label}", end="", flush=True)


async def get(ids: list[str]) -> int:
    api = get_settings()
    engine = build_local_engine(api, Path(api.products_dir))
    admin = AdminComponent(engine)
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
        print(f"{model_id}: fetching")
        try:
            done = await admin.fetch_model(model_id, _show)
        except Failed as e:
            print(f"\n{model_id}: {e.message}")
            status = 1
            continue
        print(f"\n{model_id}: " + ("already here" if done["already"] else "done"))
    if wants_engine:
        try:
            await admin.fetch_engine(LIPSYNC_ENGINE, _show)
            print("\nlip sync engine: ready")
        except Failed as e:
            print(f"\nlip sync engine: {e.message}")
            status = 1
    if engine.install is None:
        print(
            "The speech runtime (audio.cpp) is not set up here: set it up in the desktop app first."
        )
    return status


def main() -> None:
    sys.exit(asyncio.run(get(sys.argv[1:])))


if __name__ == "__main__":
    main()
