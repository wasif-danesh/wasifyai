"""Start AI Toolkit's `run.py` with FLUX.2 klein reading the text encoder the app gives it.

Run by the picture trainer as `<AI Toolkit's python> -P training_aitk_run.py <its folder> <config>`
(-P: this folder's modules must not shadow the standard library). It runs in AI Toolkit's own
environment, so it uses the standard library and AI Toolkit only.

Why: AI Toolkit's klein models ignore the config's `te_name_or_path` and always ask the Hub for
"Qwen/Qwen3-4B" (commit f7a1fb9a, and main of 2026-11-04). That is the text encoder the image model
already keeps (`qwen_3_4b.safetensors`), so a second 8 GB copy is not needed. The owner's
character-lora project made klein read it with a five-line edit to AI Toolkit's file; this does
the same without changing AI Toolkit's files, so the checkout stays as it was downloaded.

Also: the app runs AI Toolkit offline (`HF_HUB_OFFLINE=1`, every file fetched first), and the
diffusers AI Toolkit installs (0.39 dev) still asks the Hub API whether a split model's parts
exist before reading them from the cache, which offline mode refuses. `cache_only_shards` makes
that check read the cache only, which is what offline means. And transformers (5.5) reads "not in
the cache" as "cannot connect" even for a file a repo does not have (a tokenizer folder's
`config.json`), so the load stops where it would carry on online. The app's fetch keeps a whole
pinned copy of each repo, so offline a file not in the cache is not there: `missing_is_absent`
says so, as the Hub would.

And FLUX.3's position encoding (`rope`) is worked out in float64, which Apple's graphics chip does
not have. On a Mac, `flux3_rope_on_mac` works the frequencies out in float64 on the processor and
uses them in float32, as ComfyUI does for FLUX on a Mac. LTX-2.5's position encodings (diffusers'
`LTX2AudioVideoRotaryPosEmbed` and the text connectors' `LTX2RotaryPosEmbed1d`) make their table
of frequencies in float64 too, then turn it into float32; on a Mac `ltx2_rope_on_mac` makes it in
float32 (`double_precision` off), which differs only by float32's rounding of that table."""

import functools
import json
import os
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


def cache_only_shards() -> None:
    """Offline, a split model's parts are looked up in the cache only (see the module's note)."""
    if os.environ.get("HF_HUB_OFFLINE") != "1":
        return
    try:
        from diffusers.models import modeling_utils
        from diffusers.utils import hub_utils
    except ImportError:  # not a diffusers model: nothing to do
        return
    original = hub_utils._get_checkpoint_shard_files  # noqa: SLF001

    @functools.wraps(original)
    def from_cache(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        kwargs["local_files_only"] = True
        return original(*args, **kwargs)

    hub_utils._get_checkpoint_shard_files = from_cache  # noqa: SLF001
    modeling_utils._get_checkpoint_shard_files = from_cache  # noqa: SLF001


def missing_is_absent() -> None:
    """Offline, a file not in the cache is answered as one the repo does not have."""
    if os.environ.get("HF_HUB_OFFLINE") != "1":
        return
    try:
        import huggingface_hub
        from huggingface_hub import file_download
        from huggingface_hub.errors import EntryNotFoundError, LocalEntryNotFoundError
    except ImportError:
        return
    original = file_download.hf_hub_download

    @functools.wraps(original)
    def absent(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        try:
            return original(*args, **kwargs)
        except LocalEntryNotFoundError as e:
            raise EntryNotFoundError(str(e)) from e

    file_download.hf_hub_download = absent
    huggingface_hub.hf_hub_download = absent
    try:
        from transformers.utils import hub as transformers_hub
    except ImportError:
        return
    transformers_hub.hf_hub_download = absent


def uses_arch(config: dict, prefix: str) -> bool:
    return any(
        p.get("model", {}).get("arch", "").startswith(prefix)
        for p in config.get("config", {}).get("process", [])
    )


def flux3_rope_on_mac() -> None:
    """FLUX.3's `rope` without float64 on Apple's graphics chip (see the module's note)."""
    try:
        import torch
        from einops import rearrange
        from extensions_built_in.diffusion_models.flux3.src import transformer
    except ImportError:  # an AI Toolkit without FLUX.3: it says so itself
        return

    original = transformer.rope

    @functools.wraps(original)
    def rope(pos, dim: int, theta: int):  # noqa: ANN001, ANN202
        if pos.device.type != "mps":
            return original(pos, dim, theta)
        scale = torch.arange(0, dim, 2, dtype=torch.float64) / dim
        omega = (1.0 / (theta**scale)).to(torch.float32).to(pos.device)
        out = torch.einsum("...n,d->...nd", pos.float(), omega)
        out = torch.stack([torch.cos(out), -torch.sin(out), torch.sin(out), torch.cos(out)], -1)
        return rearrange(out, "b n d (i j) -> b n d i j", i=2, j=2).float()

    transformer.rope = rope


def ltx2_rope_on_mac() -> list[str]:
    """LTX-2.5's position encodings without float64 on Apple's graphics chip (see the module's
    note). Answers the classes it changed."""
    import importlib

    changed = []
    for module, name in (
        ("diffusers.models.transformers.transformer_ltx2", "LTX2AudioVideoRotaryPosEmbed"),
        ("diffusers.pipelines.ltx2.connectors", "LTX2RotaryPosEmbed1d"),
    ):
        try:
            cls = getattr(importlib.import_module(module), name)
        except (ImportError, AttributeError):
            continue  # a diffusers without LTX-2: AI Toolkit says so itself
        original = cls.__init__

        @functools.wraps(original)
        def init(self, *args, _original=original, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
            _original(self, *args, **kwargs)
            self.double_precision = False

        cls.__init__ = init
        changed.append(name)
    return changed


def main(home: Path, cfg: Path) -> None:
    sys.path.insert(0, str(home))
    cache_only_shards()
    missing_is_absent()
    config = json.loads(cfg.read_text())
    if sys.platform == "darwin" and uses_arch(config, "flux3"):
        flux3_rope_on_mac()
    if sys.platform == "darwin" and uses_arch(config, "ltx2"):
        ltx2_rope_on_mac()
    found = klein_text_encoder(config)
    if found is not None:
        point_klein_at(*found)
    sys.argv = [str(home / "run.py"), str(cfg)]
    runpy.run_path(str(home / "run.py"), run_name="__main__")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
