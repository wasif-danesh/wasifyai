"""Start AI Toolkit's `run.py` with FLUX.2 klein reading the text encoder the app gives it.

Run by the picture trainer as `<AI Toolkit's python> -P training_aitk_run.py <its folder> <config>`
(-P: this folder's modules must not shadow the standard library). It runs in AI Toolkit's own
environment, so it uses the standard library and AI Toolkit only.

Why: AI Toolkit's klein models ignore the config's `te_name_or_path` and always ask the Hub for
"Qwen/Qwen3-4B" (commit f7a1fb9a, and main of 2026-11-04). That is the text encoder the image model
already keeps (`qwen_3_4b.safetensors`), so a second 8 GB copy is not needed. The owner's
character-lora project made klein read it with a five-line edit to AI Toolkit's file; this does
the same without changing AI Toolkit's files, so the checkout stays as it was downloaded."""

import json
import runpy
import sys
from pathlib import Path


def klein_text_encoder(config: dict) -> tuple[str, str] | None:
    """(the architecture, the text encoder folder) of a klein run that names one, else None."""
    for process in config.get("config", {}).get("process", []):
        model = process.get("model", {})
        arch, te = model.get("arch", ""), model.get("te_name_or_path")
        if arch.startswith("flux2_klein") and te:
            return arch, te
    return None


def point_klein_at(arch: str, te: str) -> None:
    from extensions_built_in.diffusion_models.flux2 import flux2_klein_model as klein

    found = False
    todo = [klein.Flux2KleinModel]
    while todo:
        cls = todo.pop()
        todo.extend(cls.__subclasses__())
        if getattr(cls, "arch", None) == arch:
            cls.flux2_klein_te_path = te
            found = True
    if not found:
        raise SystemExit(f"AITK-RUN this AI Toolkit has no klein model called {arch}")


def main(home: Path, cfg: Path) -> None:
    sys.path.insert(0, str(home))
    found = klein_text_encoder(json.loads(cfg.read_text()))
    if found is not None:
        point_klein_at(*found)
    sys.argv = [str(home / "run.py"), str(cfg)]
    runpy.run_path(str(home / "run.py"), run_name="__main__")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
