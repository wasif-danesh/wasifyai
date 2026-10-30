"""Finding the models and tools already on this computer (ADR-0063).

    read_gguf / read_safetensors   what a file's header says it is (nothing else is read)
    scan_folders                   a bounded walk of the known folders, one tool at a time
    DiscoveryService               the result, kept in the settings store, rescanned at start
    router                         `/desktop/discovery/...` routes the window uses

Everything here is read-only and local. A file is never copied, moved or changed, a folder that
does not exist is skipped, and the walk has a time and file budget. The folders come from
`discovery.yaml`.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import struct
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from wasifyai_platform_sdk import Identity

from wasifyai_api.desktop_fit import (
    Machine,
    Need,
    assess_fit,
    need_declared,
    need_of_image,
    need_of_language,
)
from wasifyai_api.desktop_models import ModelEntry, ModelsService
from wasifyai_api.identity import get_identity
from wasifyai_api.services import services_of
from wasifyai_api.settings_store import SettingsStore

log = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).with_name("discovery.yaml")
KEY = "desktop.discovery"
MAX_ITEMS = 1500
MAX_DEPTH = 7
MAX_FILES_VISITED = 60_000
TIME_BUDGET_S = 25.0
MAX_HEADER_BYTES = 16 * 1024 * 1024
MIN_BYTES = 1_000_000
MODEL_SUFFIXES = (".gguf", ".safetensors", ".ckpt")
SKIP_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", "site-packages", "venv", ".venv", "env", "cache",
     "Cache", "tmp", ".tmp", "logs"}
)  # fmt: skip
SHARD = re.compile(r"^(?P<stem>.+?)-(?P<n>\d{4,5})-of-(?P<of>\d{4,5})(?P<ext>\.[a-z]+)$")

# ComfyUI's folder names say what a file is when its header does not
FOLDER_KINDS = {
    "checkpoints": "diffusion", "diffusion_models": "diffusion", "unet": "diffusion",
    "text_encoders": "text_encoder", "clip": "text_encoder", "vae": "vae", "loras": "lora",
    "controlnet": "controlnet", "upscale_models": "upscaler", "embeddings": "embedding",
    "clip_vision": "vision_encoder",
}  # fmt: skip

# GGUF `general.architecture` values that are not language models
GGUF_OTHER = {
    "clip": ("other", "vision projector"),
    "bert": ("embedding", "bert"), "nomic-bert": ("embedding", "nomic-bert"),
    "flux": ("diffusion", "flux"), "sd3": ("diffusion", "sd3"), "lumina2": ("diffusion", "lumina2"),
    "hidream": ("diffusion", "hidream"), "qwen_image": ("diffusion", "qwen-image"),
    "wan": ("video", "wan"), "ltxv": ("video", "ltx-video"), "hyvid": ("video", "hunyuan-video"),
    "t5": ("text_encoder", "t5"), "t5encoder": ("text_encoder", "t5"),
}  # fmt: skip

FTYPES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1", 10: "Q2_K",
    11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S",
    17: "Q5_K_M", 18: "Q6_K", 19: "IQ2_XXS", 20: "IQ2_XS", 21: "Q2_K_S", 22: "IQ3_XS",
    23: "IQ3_XXS", 24: "IQ1_S", 25: "IQ4_NL", 26: "IQ3_S", 27: "IQ3_M", 28: "IQ2_S", 29: "IQ2_M",
    30: "IQ4_XS", 31: "IQ1_M", 32: "BF16",
}  # fmt: skip


# ---- headers ----------------------------------------------------------------------------------


@dataclass
class Header:
    """What a file's header says. `kind` is one of language, embedding, diffusion, video, lora, vae,
    text_encoder, controlnet, upscaler, vision_encoder, other, unknown."""

    kind: str = "unknown"
    family: str = ""
    quant: str = ""
    name: str = ""
    context: int = 0
    tensors: int = -1  # GGUF only: 0 means a vocabulary file, not a model
    layers: int = 0
    kv_heads: int = 0
    head_dim: int = 0


_SCALAR = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q",
           11: "<q", 12: "<d"}  # fmt: skip


def _gguf_string(f: BinaryIO) -> str:
    (n,) = struct.unpack("<Q", f.read(8))
    if n > 1 << 20:
        raise ValueError("string too long")
    return f.read(n).decode("utf-8", "replace")


def _gguf_value(f: BinaryIO, vtype: int) -> Any:
    if vtype in _SCALAR:
        fmt = _SCALAR[vtype]
        return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]
    if vtype == 8:
        return _gguf_string(f)
    if vtype == 9:  # array: skipped, never materialised (tokenizer lists have 100k+ entries)
        (etype,) = struct.unpack("<I", f.read(4))
        (count,) = struct.unpack("<Q", f.read(8))
        if etype in _SCALAR:
            f.seek(count * struct.calcsize(_SCALAR[etype]), os.SEEK_CUR)
        elif etype == 8:
            for _ in range(min(count, 1_000_000)):
                (n,) = struct.unpack("<Q", f.read(8))
                f.seek(n, os.SEEK_CUR)
        else:
            raise ValueError("unsupported array")
        return None
    raise ValueError(f"unknown value type {vtype}")


def _kv_heads(meta: dict[str, Any], arch: str) -> int:
    heads = meta.get(f"{arch}.attention.head_count_kv") or meta.get(f"{arch}.attention.head_count")
    return int(heads) if isinstance(heads, int) else 0


def _head_dim(meta: dict[str, Any], arch: str) -> int:
    key = meta.get(f"{arch}.attention.key_length")
    if isinstance(key, int) and key > 0:
        return key
    embed, heads = meta.get(f"{arch}.embedding_length"), meta.get(f"{arch}.attention.head_count")
    if isinstance(embed, int) and isinstance(heads, int) and heads > 0:
        return embed // heads
    return 0


def read_gguf(path: Path) -> Header | None:
    """Architecture, name and quantisation from a GGUF header; None when it is not one."""
    try:
        with path.open("rb") as f:
            if f.read(4) != b"GGUF":
                return None
            (version,) = struct.unpack("<I", f.read(4))
            if version not in (2, 3):
                return None
            n_tensors, count = struct.unpack("<QQ", f.read(16))
            meta: dict[str, Any] = {}
            for _ in range(min(count, 5000)):
                key = _gguf_string(f)
                (vtype,) = struct.unpack("<I", f.read(4))
                if key.startswith("tokenizer."):
                    break  # general.* and the architecture's keys come first
                meta[key] = _gguf_value(f, vtype)
                if f.tell() > MAX_HEADER_BYTES:
                    break
    except (OSError, struct.error, ValueError):
        return None
    arch = str(meta.get("general.architecture") or "")
    kind, family = GGUF_OTHER.get(arch, ("language", arch))
    ftype = meta.get("general.file_type")
    return Header(
        kind=kind if arch else "unknown",
        family=family,
        quant=FTYPES.get(ftype, "") if isinstance(ftype, int) else "",
        name=str(meta.get("general.name") or ""),
        context=int(meta.get(f"{arch}.context_length") or 0) if arch else 0,
        tensors=int(n_tensors),
        layers=int(meta.get(f"{arch}.block_count") or 0) if arch else 0,
        kv_heads=_kv_heads(meta, arch),
        head_dim=_head_dim(meta, arch),
    )


def gguf_chat_template(path: Path) -> str | None:
    """The chat template a GGUF carries: its text, "" when it has none, None when the header cannot
    be read.

    The template sits after the tokenizer's big lists, so this walks the whole key list (lists are
    skipped, not loaded). Ollama keeps templates outside the file, so its blobs often have none: the
    engine then falls back to a generic template and a model may answer oddly."""
    try:
        with path.open("rb") as f:
            if f.read(4) != b"GGUF":
                return None
            (version,) = struct.unpack("<I", f.read(4))
            if version not in (2, 3):
                return None
            _tensors, count = struct.unpack("<QQ", f.read(16))
            for _ in range(min(count, 100_000)):
                key = _gguf_string(f)
                (vtype,) = struct.unpack("<I", f.read(4))
                value = _gguf_value(f, vtype)
                if key == "tokenizer.chat_template":
                    return str(value or "")
    except (OSError, struct.error, ValueError):
        return None
    return ""


def gguf_has_chat_template(path: Path) -> bool | None:
    """Does this GGUF carry its own chat template? None when the header cannot be read."""
    template = gguf_chat_template(path)
    return None if template is None else bool(template)


def can_think(template: str | None) -> bool:
    """Can a model with this chat template think when asked? Templates that take the switch
    (Qwen3 and Qwen3.5, and others) read `enable_thinking`."""
    return bool(template) and "enable_thinking" in str(template)


def read_safetensors_header(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as f:
            raw = f.read(8)
            if len(raw) != 8:
                return None
            (n,) = struct.unpack("<Q", raw)
            if n == 0 or n > MAX_HEADER_BYTES:
                return None
            head = json.loads(f.read(n))
    except (OSError, ValueError, struct.error):
        return None
    return head if isinstance(head, dict) else None


def classify_tensors(names: list[str]) -> tuple[str, str]:
    """(kind, family) from tensor names alone. Best effort: `unknown` is a fine answer."""
    has = lambda s: any(s in n for n in names)  # noqa: E731
    starts = lambda s: any(n.startswith(s) for n in names)  # noqa: E731
    if has("lora_down") or has("lora_up") or has(".lora_A") or has(".lora_B") or has("lora_unet_"):
        family = (
            "flux" if has("double_blocks") or has("single_blocks")
            else "ltx-video" if starts("transformer_blocks.") and has("attn1.") and has("attn2.")
            else "wan" if has("patch_embedding")
            else "sdxl" if has("label_emb") or has("lora_unet_input_blocks") else ""
        )  # fmt: skip
        return "lora", family
    vae_like = sum(
        n.startswith(("encoder.", "decoder.", "quant_conv", "post_quant_conv")) for n in names
    )
    if names and vae_like >= 0.9 * len(names):
        return "vae", ""
    if has("double_blocks.") and has("single_blocks."):
        return "diffusion", "flux"
    if has("joint_blocks."):
        return "diffusion", "sd3"
    if has("patch_embedding") and has("blocks.") and has("head.head"):
        return "video", "wan"
    if has("adaln_single") and has("transformer_blocks."):
        return "video", "ltx-video"
    if has("diffusion_model.") or has("model.diffusion_model"):
        if has("label_emb"):
            return "diffusion", "sdxl"
        return "diffusion", "sd15" if has("input_blocks.") else ""
    if has("down_blocks.") and has("up_blocks.") and has("mid_block"):
        return "diffusion", "sdxl" if has("add_embedding") else "sd15"
    if has("self_attn.q_proj") and has("embed_tokens") and has("model.layers."):
        return "language", "transformers"
    if has("encoder.block.") and has("shared.weight"):
        return "text_encoder", "t5"
    if has("text_model.encoder.layers."):
        return "text_encoder", "clip"
    if starts("embeddings.") or has("pooler.dense") or has("encoder.layer."):
        return "embedding", "bert"
    return "unknown", ""


def read_safetensors(path: Path) -> Header:
    head = read_safetensors_header(path)
    if head is None:
        return Header()
    raw_meta = head.get("__metadata__")
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    tensors = {k: v for k, v in head.items() if k != "__metadata__" and isinstance(v, dict)}
    kind, family = classify_tensors(list(tensors))
    counts: dict[str, int] = {}
    for t in tensors.values():
        d = str(t.get("dtype", ""))
        counts[d] = counts.get(d, 0) + 1
    quant = max(counts, key=lambda d: counts[d]) if counts else ""
    return Header(
        kind=kind, family=family, quant=quant,
        name=str(meta.get("modelspec.title") or meta.get("name") or ""),
    )  # fmt: skip


def read_header(path: Path, folder_hint: str = "") -> Header:
    """Read a file's header and settle a doubtful kind with the folder it sits in."""
    suffix = path.suffix.lower()
    if suffix == ".gguf":
        h = read_gguf(path) or Header()
    elif suffix == ".safetensors":
        h = read_safetensors(path)
    else:  # .ckpt is a pickle: never opened, only named
        h = Header()
    hint = FOLDER_KINDS.get(folder_hint.lower())
    if hint and h.kind in ("unknown", "language", "other"):
        if not (h.kind == "language" and hint in ("diffusion", "lora", "vae")):
            h.kind = hint
    return h


# ---- found items ------------------------------------------------------------------------------


@dataclass
class Found:
    id: str
    name: str
    kind: str
    family: str
    format: str
    quant: str
    size: int
    path: str
    tool: str
    tool_title: str
    state: str = "later"  # ready, can_use, later, unsupported
    reason: str = ""
    use_root: str | None = None  # the folder `can_use` would add
    use: str = ""  # what `can_use` does: "folder" (add its models folder) or "chat" (choose it)
    lora_name: str = ""  # a LoRA: its name relative to a `loras` folder, as a workflow names it
    needs_gb: float = 0.0
    fit: dict[str, Any] | None = None
    # what a language model's memory need is worked out from (GGUF header; 0 when unknown)
    layers: int = 0
    kv_heads: int = 0
    head_dim: int = 0
    context: int = 0

    def public(self) -> dict[str, Any]:
        return asdict(self)


def _item_id(path: str) -> str:
    return hashlib.sha256(path.encode()).hexdigest()[:20]


def _clean_name(file: Path, header: Header) -> str:
    return header.name or file.stem


@dataclass
class Tool:
    id: str
    title: str
    layout: str
    folders: list[Path]
    needs_permission: bool = False
    servers: list[dict[str, str]] = field(default_factory=list)


def load_config(path: Path = CONFIG_FILE) -> list[dict[str, Any]]:
    raw = yaml.safe_load(path.read_text()) or {}
    return list(raw.get("tools") or [])


def resolve_tools(
    config: list[dict[str, Any]],
    platform: str | None = None,
    env: dict[str, str] | None = None,
    home: Path | None = None,
) -> list[Tool]:
    platform = platform or sys.platform
    key = "win32" if platform.startswith("win") else "darwin" if platform == "darwin" else "linux"
    env = dict(os.environ if env is None else env)
    home = home or Path.home()

    def expand(p: str) -> Path:
        if p == "~" or p.startswith("~/"):
            p = str(home) + p[1:]
        for name, value in env.items():  # %VAR% and $VAR from the given environment
            p = p.replace(f"%{name}%", value).replace(f"${name}", value)
        return Path(p)

    tools: list[Tool] = []
    for t in config:
        folders = [expand(p) for p in (t.get("folders") or {}).get(key, [])]
        override = env.get(str(t.get("env") or ""))
        if override:
            folders = [Path(override).expanduser(), *folders[1:]]
        tools.append(
            Tool(
                id=t["id"], title=t["title"], layout=t.get("layout", "files"), folders=folders,
                needs_permission=bool(t.get("needs_permission")),
                servers=list(t.get("servers") or []),
            )
        )  # fmt: skip
    return tools


class Budget:
    def __init__(self, seconds: float = TIME_BUDGET_S, files: int = MAX_FILES_VISITED):
        self.deadline = time.monotonic() + seconds
        self.files_left = files
        self.truncated = False

    def spend(self) -> bool:
        self.files_left -= 1
        if self.files_left < 0 or time.monotonic() > self.deadline:
            self.truncated = True
            return False
        return True


def _walk(root: Path, budget: Budget, depth: int = 0) -> Iterator[Path]:
    """Files under `root`, to a bounded depth, without following folder links."""
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError:
        return
    for e in entries:
        if not budget.spend():
            return
        try:
            if e.is_dir(follow_symlinks=False):
                if depth < MAX_DEPTH and e.name not in SKIP_DIRS:
                    yield from _walk(Path(e.path), budget, depth + 1)
            elif e.is_file():  # a file link counts: the Hugging Face cache is made of them
                yield Path(e.path)
        except OSError:
            continue


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _group_shards(files: list[Path]) -> list[tuple[Path, list[Path]]]:
    """(first file, all parts): the `-00001-of-00004` files of one model are one model."""
    groups: dict[tuple[Path, str, str], list[Path]] = {}
    out: list[tuple[Path, list[Path]]] = []
    for f in files:
        m = SHARD.match(f.name)
        if m:
            groups.setdefault((f.parent, m["stem"], m["ext"]), []).append(f)
        else:
            out.append((f, [f]))
    for parts in groups.values():
        parts.sort()
        out.append((parts[0], parts))
    return sorted(out, key=lambda t: str(t[0]))


def _file_item(
    first: Path, parts: list[Path], tool: Tool, display: str | None = None
) -> Found | None:
    fmt = first.suffix.lower().lstrip(".")
    h = read_header(first, first.parent.name)
    if h.tensors == 0:
        return None  # a vocabulary file, not a model
    if h.kind == "unknown" and fmt != "ckpt" and not display:
        # a header that says nothing, in a folder that says nothing: not worth listing
        return None
    size = sum(_size(p) for p in parts)
    if size < MIN_BYTES:
        return None  # test files and stubs
    return Found(
        id=_item_id(str(first)), name=display or _clean_name(first, h), kind=h.kind,
        family=h.family,
        format=fmt, quant=h.quant, size=size, path=str(first), tool=tool.id,
        tool_title=tool.title, needs_gb=round(size * 1.15 / 1e9, 1),
        layers=h.layers, kv_heads=h.kv_heads, head_dim=h.head_dim, context=h.context,
    )  # fmt: skip


def _scan_files_layout(root: Path, tool: Tool, budget: Budget) -> list[Found]:
    files = [p for p in _walk(root, budget) if p.suffix.lower() in MODEL_SUFFIXES]
    out = []
    for first, parts in _group_shards(files):
        item = _file_item(first, parts, tool)
        if item:
            out.append(item)
    return out


def _scan_ollama(root: Path, tool: Tool, budget: Budget) -> list[Found]:
    manifests = root / "manifests"
    out: list[Found] = []
    for m in _walk(manifests, budget):
        try:
            doc = json.loads(m.read_text())
            layer = next(
                (lay for lay in doc.get("layers", [])
                 if str(lay.get("mediaType", "")).endswith(".image.model")),
                None,
            )  # fmt: skip
        except (OSError, ValueError, AttributeError):
            continue
        if not layer or ":" not in str(layer.get("digest", "")):
            continue
        blob = root / "blobs" / str(layer["digest"]).replace(":", "-")
        if not blob.is_file():
            continue
        parts = m.relative_to(manifests).parts  # registry.ollama.ai / library / llama3.2 / 3b
        if len(parts) < 3:
            continue
        name = "/".join(parts[1:-1]).removeprefix("library/") + f":{parts[-1]}"
        h = read_gguf(blob) or Header()
        size = _size(blob)
        if h.tensors == 0 or size < MIN_BYTES:
            continue
        out.append(
            Found(
                id=_item_id(str(blob)), name=name,
                kind=h.kind if h.kind != "unknown" else "language",
                family=h.family, format="gguf", quant=h.quant, size=size, path=str(blob),
                tool=tool.id, tool_title=tool.title,
                needs_gb=round(size * 1.15 / 1e9, 1),
                layers=h.layers, kv_heads=h.kv_heads, head_dim=h.head_dim, context=h.context,
            )
        )  # fmt: skip
    return out


DIFFUSERS_CLASSES = (
    ("Wan", "video", "wan"), ("LTX", "video", "ltx-video"),
    ("HunyuanVideo", "video", "hunyuan-video"),
    ("CogVideo", "video", "cogvideo"), ("Mochi", "video", "mochi"),
    ("Flux", "diffusion", "flux"), ("StableDiffusion3", "diffusion", "sd3"),
    ("StableDiffusionXL", "diffusion", "sdxl"), ("StableDiffusion", "diffusion", "sd15"),
    ("QwenImage", "diffusion", "qwen-image"), ("Lumina", "diffusion", "lumina"),
    ("PixArt", "diffusion", "pixart"), ("Sana", "diffusion", "sana"),
)  # fmt: skip


def _hf_snapshot_item(repo: str, snap: Path, tool: Tool, budget: Budget) -> list[Found]:
    """One item for a whole diffusers or transformers repo, per-file items for loose weights."""
    files = list(_walk(snap, budget))
    size = sum(_size(p) for p in files if p.suffix.lower() in MODEL_SUFFIXES or p.suffix == ".bin")
    index, config = snap / "model_index.json", snap / "config.json"

    def repo_item(kind: str, family: str) -> Found:
        return Found(
            id=_item_id(str(snap)), name=repo, kind=kind, family=family, format="repo", quant="",
            size=size, path=str(snap), tool=tool.id, tool_title=tool.title,
            needs_gb=round(size * 1.15 / 1e9, 1),
        )  # fmt: skip

    if index.is_file():
        try:
            cls = str(json.loads(index.read_text()).get("_class_name", ""))
        except (OSError, ValueError):
            cls = ""
        kind, family = next(
            ((k, f) for prefix, k, f in DIFFUSERS_CLASSES if prefix in cls), ("diffusion", cls)
        )
        return [repo_item(kind, family)]
    if config.is_file():
        try:
            doc = json.loads(config.read_text())
        except (OSError, ValueError):
            doc = {}
        arch = str((doc.get("architectures") or [""])[0])
        mtype = str(doc.get("model_type", ""))
        if any(s in arch for s in ("CausalLM", "ConditionalGeneration", "LMHeadModel")):
            kind = "language"
        elif arch.endswith(("Model", "Encoder")) and mtype in ("bert", "xlm-roberta", "nomic_bert"):
            kind = "embedding"
        else:
            kind = "other"
        if size > 0:
            return [repo_item(kind, mtype)]
    out: list[Found] = []
    loose = [p for p in files if p.suffix.lower() in MODEL_SUFFIXES]
    for first, parts in _group_shards(loose):
        item = _file_item(first, parts, tool)
        if item:
            item.name = f"{repo} / {item.name}"
            out.append(item)
    return out


def _scan_hf_cache(root: Path, tool: Tool, budget: Budget) -> list[Found]:
    out: list[Found] = []
    try:
        repos = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("models--"))
    except OSError:
        return out
    for repo_dir in repos:
        repo = repo_dir.name.removeprefix("models--").replace("--", "/")
        snaps = repo_dir / "snapshots"
        try:
            revs = sorted(snaps.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            continue
        for snap in revs[:1]:  # the newest revision is what the repo is now
            if snap.is_dir():
                out += _hf_snapshot_item(repo, snap, tool, budget)
    return out


_LAYOUTS: dict[str, Callable[[Path, Tool, Budget], list[Found]]] = {
    "files": _scan_files_layout, "ollama": _scan_ollama, "hf-cache": _scan_hf_cache,
}  # fmt: skip


@dataclass
class ScanResult:
    items: list[Found]
    scanned: list[dict[str, Any]]
    truncated: bool
    seconds: float


def scan_folders(
    tools: list[Tool], extra_folders: list[Path], budget: Budget | None = None
) -> ScanResult:
    """The whole scan. `extra_folders` are the ones the person added (plain model folders,
    which is also how a `needs_permission` folder is allowed)."""
    started = time.monotonic()
    budget = budget or Budget()
    seen: set[str] = set()
    items: list[Found] = []
    scanned: list[dict[str, Any]] = []
    extras = {p.expanduser() for p in extra_folders}
    jobs: list[tuple[Tool, Path]] = []
    for tool in tools:
        for folder in tool.folders:
            if tool.needs_permission and folder not in extras:
                continue
            jobs.append((tool, folder))
    for folder in sorted(extras - {f for _, f in jobs}):
        jobs.append((Tool("added", "a folder you added", "files", [folder]), folder))
    for tool, folder in jobs:
        if not folder.is_dir():
            continue
        before = len(items)
        for item in _LAYOUTS.get(tool.layout, _scan_files_layout)(folder, tool, budget):
            try:
                real = str(Path(item.path).resolve())
            except OSError:
                real = item.path
            twin = f"{tool.id}:{item.size}:{item.kind}"
            if real in seen or (item.size > 100_000_000 and twin in seen):
                continue  # the same file reached twice, or one model under two names
            seen.add(real)
            seen.add(twin)
            items.append(item)
        scanned.append({"tool": tool.title, "folder": str(folder), "found": len(items) - before})
    items.sort(key=lambda i: (i.kind, i.name.lower()))
    return ScanResult(items[:MAX_ITEMS], scanned, budget.truncated, time.monotonic() - started)


# ---- what can be done with an item ------------------------------------------------------------

KIND_WORDS = {
    "language": "language model", "embedding": "embedding model", "diffusion": "image model",
    "video": "video model", "lora": "LoRA", "vae": "VAE", "text_encoder": "text encoder",
    "controlnet": "ControlNet", "upscaler": "upscaler", "vision_encoder": "vision encoder",
    "other": "model", "unknown": "model",
}  # fmt: skip

LATER = {
    "language": "The assistant (a coming stage) will be able to run this.",
    "embedding": "Search and documents (a coming stage) will be able to use this.",
    "diffusion": "No image workflow of ours uses this model yet.",
    "video": "Video generation is a coming stage.",
    "lora": "Put it in a `loras` folder of a models folder to use it.",
    "vae": "Used together with an image model; no workflow of ours takes it on its own yet.",
    "text_encoder": "Used together with an image model; no workflow of ours takes it alone yet.",
}  # fmt: skip


# Architectures a tool stores under its own name, which llama.cpp does not read. Found by running
# the engine on a real model: Ollama's own gpt-oss file says "gptoss", llama.cpp's says "gpt-oss".
INCOMPATIBLE = {
    "gptoss": "Ollama keeps this model in its own format, which llama.cpp cannot read. A file of "
    "the same model made for llama.cpp works.",
}

LORA_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()/-]{0,200}\.safetensors$")


def lora_location(path: Path) -> tuple[Path, str] | None:
    """(the models folder, the name a workflow uses) for a LoRA that sits under a `loras` folder."""
    for parent in path.parents:
        if parent.name == "loras":
            name = path.relative_to(parent).as_posix()
            if LORA_NAME.match(name) and ".." not in name:
                return parent.parent, name
            return None
    return None


def _assess_lora(it: Found, path: Path, roots: list[Path]) -> None:
    found = lora_location(path)
    if found is None:
        it.state = "unsupported"
        it.reason = (
            "The image engine reads LoRAs from a `loras` folder, and this file is not in one "
            "(or its name has characters it cannot use)."
        )
        return
    root, name = found
    it.lora_name = name
    try:
        used = any(root.resolve() == r.resolve() for r in roots if r.exists())
    except OSError:
        used = False
    if it.family == "ltx-video":  # a look for the video model, chosen on the Video screens
        if used:
            it.state, it.reason = "ready", "The video engine can apply this look (LoRA)."
        else:
            it.state, it.use, it.use_root = "can_use", "folder", str(root)
            it.reason = "One click lets the video engine read this look where it is."
    elif used:
        it.state, it.reason = "ready", "The image engine can apply this style (LoRA)."
    else:
        it.state, it.use, it.use_root = "can_use", "folder", str(root)
        it.reason = (
            "One click lets the image engine read this style where it is. Make sure it was "
            "trained for FLUX.2 klein 4B."
        )


PARTS = frozenset(
    {"lora", "vae", "text_encoder", "controlnet", "upscaler", "vision_encoder", "other", "unknown"}
)


def need_of(item: Found) -> Need | None:
    """What running this model asks of the computer; None for parts that are not run alone."""
    if item.kind in PARTS:
        return None
    if item.kind in ("language", "embedding"):
        return need_of_language(item.size, item.layers, item.kv_heads, item.head_dim, item.context)
    return need_of_image(item.size, video=item.kind == "video")


@dataclass(frozen=True)
class LanguageHint:
    """What assess needs to know about the language engine."""

    ready: bool  # the engine is installed
    selected_path: str | None  # the file chosen for chat, if any
    context: int  # the context the person chose
    machine: Machine | None  # the computer as the engine sees it (its backend decides the device)


def assess(
    items: list[Found],
    catalogue: list[ModelEntry],
    roots: list[Path],
    machine: Machine | None,
    language: LanguageHint | None = None,
) -> None:
    """Set each item's state and reason (used already, usable in place, planned, or not usable) and
    whether it fits this computer. A model that cannot fit is never offered for use."""
    wanted: dict[tuple[str, int], tuple[str, str, ModelEntry]] = {}
    for e in catalogue:
        for f in e.files:
            wanted[(f.name, f.size)] = (f.folder, e.title, e)
    resolved_roots = []
    for r in roots:
        try:
            resolved_roots.append(r.resolve())
        except OSError:
            continue
    for it in items:
        p = Path(it.path)
        match = wanted.get((p.name, it.size))
        need = need_of(it)
        if match and p.parent.name == match[0]:
            if match[2].approx_ram_gb:
                need = need_declared(match[2].approx_ram_gb)  # the whole pipeline, measured
            root = p.parent.parent
            used = any(root.resolve() == r for r in resolved_roots if root.exists())
            it.state = "ready" if used else "can_use"
            it.use_root = None if used else str(root)
            it.reason = (
                f"Used for {match[1]}." if used
                else f"This is a file of {match[1]}. One click lets the app use it where it is."
            )  # fmt: skip
        elif it.format == "gguf" and it.family in INCOMPATIBLE:
            it.state = "unsupported"
            it.reason = INCOMPATIBLE[it.family]
        elif it.format == "ckpt":
            it.state = "unsupported"
            it.reason = "Old .ckpt files can run code when opened, so the app does not open them."
        elif it.kind == "language" and it.format != "gguf":
            it.state = "unsupported"
            it.reason = (
                "The language engine reads GGUF files. This is a transformers folder: download "
                "a GGUF version of the model instead."
            )
        elif it.kind == "language":
            if language is not None and language.selected_path == it.path:
                it.state, it.reason = "ready", "Chosen for chat."
            elif language is not None and language.ready:
                it.state, it.use = "can_use", "chat"
                it.reason = "The language engine can run this. Choose it to chat with it."
            else:
                it.state = "later"
                it.reason = (
                    "Set up the language engine in Settings, then this can be chosen for chat."
                )
        elif it.kind == "lora" and it.format == "safetensors":
            _assess_lora(it, p, roots)
        elif it.kind in LATER:
            it.state = "later"
            it.reason = LATER[it.kind]
        else:
            it.state = "unsupported"
            it.reason = f"The app does not recognise this {KIND_WORDS.get(it.kind, 'file')} yet."
        it.fit = None
        if match and p.parent.name == match[0] and it.state == "can_use":
            it.use = "folder"
        machine_for_fit = machine
        if it.kind == "language" and language is not None and it.format == "gguf":
            need = need_of_language(
                it.size, it.layers, it.kv_heads, it.head_dim, it.context, chosen=language.context
            )
            machine_for_fit = language.machine
        if need is not None and machine_for_fit is not None and it.state != "unsupported":
            fit = assess_fit(need, machine_for_fit)
            it.fit = fit.public()
            it.needs_gb = round(fit.needed_bytes / 1e9, 1)
            if fit.verdict == "too_big":
                it.state = "unsupported"
                it.use_root = None
                it.use = ""
                it.reason = fit.reason
            elif fit.verdict == "tight":
                it.reason = f"{it.reason} {fit.reason}"


# ---- running tools ----------------------------------------------------------------------------


def _server_models(kind: str, response: httpx.Response) -> list[str]:
    """The model names a running tool offers, from its listing (best effort; none is fine)."""
    try:
        body = response.json()
        if kind == "ollama":
            names = [m.get("name") for m in body.get("models", [])]
        elif kind == "openai":
            names = [m.get("id") for m in body.get("data", [])]
        else:
            names = []
    except (ValueError, AttributeError, TypeError):
        return []
    return [n for n in names if isinstance(n, str)][:100]


async def probe_servers(
    tools: list[Tool], client: httpx.AsyncClient | None = None
) -> list[dict[str, Any]]:
    """Which of the known local servers answer. Loopback addresses from our own list only."""
    own = client or httpx.AsyncClient(timeout=0.6)

    async def one(tool: Tool, s: dict[str, str]) -> dict[str, Any] | None:
        url = s["url"]
        if not url.startswith("http://127.0.0.1:"):
            return None
        try:
            r = await own.get(url + s["probe"])
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        return {
            "tool": tool.id, "title": tool.title, "url": url, "kind": s["kind"],
            "models": _server_models(s["kind"], r),
        }  # fmt: skip

    try:
        # all at once: a tool that is not running costs its timeout once,
        # not once for every tool before it
        answers = await asyncio.gather(*(one(t, s) for t in tools for s in t.servers))
    finally:
        if client is None:
            await own.aclose()
    return [a for a in answers if a is not None]


# ---- the service ------------------------------------------------------------------------------


class DiscoveryService:
    def __init__(
        self,
        store: SettingsStore,
        models: ModelsService | None,
        tools: list[Tool] | None = None,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ):
        self._store = store
        self.models = models
        self.tools = tools if tools is not None else resolve_tools(load_config())
        self._client_factory = client_factory
        self.language: Any = None  # the LanguageService: what is chosen, the engine's machine
        self.enabled = True
        self.folders: list[Path] = []
        self.items: list[Found] = []
        self.scanned: list[dict[str, Any]] = []
        self.servers: list[dict[str, Any]] = []
        self.scanned_at: float | None = None
        self.truncated = False
        self.running = False
        self._task: asyncio.Task | None = None

    async def load(self) -> None:
        saved = await self._store.get(KEY)
        if not isinstance(saved, dict):
            return
        self.enabled = bool(saved.get("enabled", True))
        self.folders = [Path(str(p)) for p in saved.get("folders", []) if str(p).strip()]
        self.scanned_at = saved.get("scanned_at")
        self.scanned = list(saved.get("scanned", []))
        self.truncated = bool(saved.get("truncated", False))
        # a field an older app saved and this one no longer has (`licence`, ADR-0094) is left
        # out, so a saved scan never stops the engine from starting
        known = set(Found.__dataclass_fields__)
        self.items = [
            Found(**{k: v for k, v in i.items() if k in known})
            for i in saved.get("items", [])
            if isinstance(i, dict)
        ]

    async def _save(self) -> None:
        await self._store.put(
            KEY,
            {
                "enabled": self.enabled, "folders": [str(p) for p in self.folders],
                "scanned_at": self.scanned_at, "scanned": self.scanned,
                "truncated": self.truncated, "items": [i.public() for i in self.items],
            },
            "engine",
        )  # fmt: skip

    def start(self, delay: float = 2.0) -> None:
        """Scan in the background shortly after the engine is up, so start-up is not slowed."""
        if self.enabled and self._task is None:
            self._task = asyncio.create_task(self._later(delay))

    async def _later(self, delay: float) -> None:
        # the running tools first, at once: a model chosen in Ollama or LM Studio is found
        # before the window asks for it, not after the slower look through the folders
        await self.probe()
        await asyncio.sleep(delay)
        await self.scan()

    async def probe(self) -> None:
        """Look again at which local tools run and what they offer (a few loopback requests)."""
        try:
            client = self._client_factory() if self._client_factory else None
            self.servers = await probe_servers(self.tools, client)
        except Exception:
            log.exception("looking for running tools failed")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def scan(self) -> None:
        if self.running:
            return
        self.running = True
        try:
            tools = list(self.tools)
            if self.models is not None:  # what this app downloaded itself (the model hub)
                tools.append(
                    Tool(
                        "app", "Wasify AI", "files",
                        [self.models.models_dir / "language", self.models.models_dir / "loras"],
                    )
                )  # fmt: skip
            result = await asyncio.to_thread(scan_folders, tools, list(self.folders))
            roots = self.models.roots() if self.models else []
            catalogue = list(self.models.catalogue.values()) if self.models else []
            machine = await self.models.machine() if self.models else None
            hint = None
            if self.language is not None:
                chosen = self.language.selected
                hint = LanguageHint(
                    ready=self.language.llama.installed,
                    selected_path=chosen.path if chosen and chosen.kind == "file" else None,
                    context=chosen.context if chosen else 8192,
                    machine=await self.language.machine(),
                )
            assess(result.items, catalogue, roots, machine, hint)
            self.items, self.scanned, self.truncated = (
                result.items,
                result.scanned,
                result.truncated,
            )
            self.scanned_at = time.time()
            client = self._client_factory() if self._client_factory else None
            self.servers = await probe_servers(self.tools, client)
            await self._save()
        except Exception:
            log.exception("model discovery failed")
        finally:
            self.running = False

    def suggested(self) -> list[dict[str, str]]:
        """Known folders that exist but need the person's permission first."""
        have = {p.expanduser() for p in self.folders}
        return [
            {"tool": t.title, "folder": str(f)}
            for t in self.tools if t.needs_permission
            for f in t.folders if f.is_dir() and f not in have
        ]  # fmt: skip

    def state(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled, "running": self.running, "scanned_at": self.scanned_at,
            "truncated": self.truncated, "items": [i.public() for i in self.items],
            "scanned": self.scanned, "servers": self.servers,
            "folders": [str(p) for p in self.folders],
            "suggested": self.suggested(),
        }  # fmt: skip

    async def set_settings(self, enabled: bool, folders: list[str]) -> None:
        self.enabled = enabled
        self.folders = await asyncio.to_thread(
            lambda: [Path(p).expanduser() for p in folders if p.strip()]
        )
        await self._save()

    async def use(self, item_id: str) -> str:
        """Let the app use a file where it is: add its models folder to the read-only folders."""
        item = next((i for i in self.items if i.id == item_id), None)
        if item is None or item.state != "can_use" or not item.use_root or self.models is None:
            raise KeyError(item_id)
        extra = [str(p) for p in self.models.extra_dirs]
        if item.use_root not in extra:
            extra.append(item.use_root)
        await self.models.set_folders(str(self.models.models_dir), extra)
        return item.use_root


# ---- routes -----------------------------------------------------------------------------------

router = APIRouter(prefix="/desktop", tags=["desktop"])


def _svc(request: Request) -> DiscoveryService:
    svc = services_of(request).desktop_discovery
    if svc is None:
        raise HTTPException(404, "not available in this deployment")
    return svc


class Settings(BaseModel):
    enabled: bool
    folders: list[str] = []


class Use(BaseModel):
    id: str


@router.get("/discovery")
async def get_discovery(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    return _svc(request).state()


@router.get("/loras")
async def loras(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    """The styles (LoRAs) the image engine can apply now, and the ones one click away."""
    items = _svc(request).items

    def row(i: Found) -> dict[str, Any]:
        return {
            "id": i.id, "name": i.lora_name, "title": i.name, "family": i.family,
            "size": i.size, "tool": i.tool_title, "reason": i.reason, "use": i.use,
        }  # fmt: skip

    # looks for the video model are chosen on the Video screens, not offered as picture styles
    kind = [i for i in items if i.kind == "lora" and i.lora_name and i.family != "ltx-video"]
    return {
        "ready": [row(i) for i in kind if i.state == "ready"],
        "available": [row(i) for i in kind if i.state == "can_use"],
    }


@router.post("/discovery/scan")
async def scan_now(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    svc = _svc(request)
    if not svc.running:
        asyncio.create_task(svc.scan())  # the window polls GET /discovery
    return {"running": True}


@router.put("/discovery/settings")
async def put_settings(
    body: Settings, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    svc = _svc(request)
    await svc.set_settings(body.enabled, body.folders)
    if body.enabled and not svc.running:
        asyncio.create_task(svc.scan())
    return svc.state()


@router.post("/discovery/use")
async def use_item(
    body: Use, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    svc = _svc(request)
    try:
        root = await svc.use(body.id)
    except KeyError:
        raise HTTPException(404, "that file cannot be used in place") from None
    except OSError as exc:
        raise HTTPException(422, f"That folder cannot be used: {exc.strerror or exc}") from None
    asyncio.create_task(svc.scan())
    return {"folder": root}
