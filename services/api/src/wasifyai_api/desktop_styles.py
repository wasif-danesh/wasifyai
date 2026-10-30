"""Styles (LoRAs) for the image screens: records, checks, import and delete (ADR-0091, stage S1).

A style is a weight file in the image engine's `loras` folder plus a sidecar `<file>.style.json`:
its title, where it came from, its SHA-256, size, the model it was made for (read from the file's
header, never from its name), rank, trigger word and when it was added. The screen lists records and
sends **style ids**; the engine turns an id into the file name the workflow needs and refuses an
unknown id or a style made for another model. Only the header of a file is read, never its weights,
and only `.safetensors` is accepted (no pickled `.ckpt` or `.pt`).

    read_style_header   what a file is: a LoRA for which model, or why it is refused (S0's rules)
    StylesService       all (adopting files with no record), import, delete, resolve ids
    router              `/desktop/styles`
"""

import asyncio
import contextlib
import hashlib
import json
import re
import secrets
import struct
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from wasifyai_api.desktop_hub import HF, HubError
from wasifyai_api.desktop_models import DownloadError, ModelEntry, ModelFile
from wasifyai_api.identity import Identity, get_identity
from wasifyai_api.services import services_of

MAX_FILE_BYTES = 2 * 1024**3  # a klein 4B style is 50 to 500 MB
MAX_HEADER_BYTES = 16 * 1024 * 1024
MAX_STYLES = 8  # in one picture (decision 7)
MAX_LOOKS = 50
# the styles checked on klein 4B (spike S0, docs/spikes/styles-s0.md), pinned by file and checksum
RECOMMENDED: tuple[dict[str, Any], ...] = (
    {"title": "Anime", "repo": "Sawata97/flux2_4b_koni_animestyle",
     "file": "Flux_klein_4b_anime_Koni.safetensors", "size": 184832664,
     "sha256": "c5f8fef8610f8f7725ab4da0410ff6ffb09542e9a65676ebcf01527eb3af429f",
     "word": "anime_style", "note": "A clear anime look."},
    {"title": "Pixel art sprites", "repo": "Limbicnation/pixel-art-lora",
     "file": "pytorch_lora_weights.comfyui.safetensors", "size": 325276656,
     "sha256": "24e938f510f5dd0c890ac8b1078f4abb87a50c9c053b2e85c44821c0f30011ad",
     "word": "pixel art sprite", "note": "Game-style pixel art characters."},
    {"title": "Old gods (creatures)", "repo": "Norod78/flux2-klein-4b-lora-old-gods",
     "file": "flux2-klein-4b-lora-old-gods.safetensors", "size": 92426800,
     "sha256": "0d028797b10e46e049cf2953bf14c486cbf511c336a6d99df7848979cf90f4bd",
     "word": "old-gods", "note": "Many-eyed creatures in any scene."},
)  # fmt: skip
LOOKS = "image.looks"  # the saved looks, in the app's settings
SIDECAR = ".style.json"
Fit = Literal["fits", "other", "unsure"]

# what a LoRA tensor is called, in the four layouts ComfyUI applies (S0 (a))
LORA_PART = re.compile(r"(lora_A|lora_B|lora_down|lora_up|\.alpha$|\.dora_scale$|lora\.(up|down))")
BLOCK = re.compile(r"(?:double_blocks|(?<!single_)transformer_blocks)[._](\d+)")
SINGLE = re.compile(r"(?:single_blocks|single_transformer_blocks)[._](\d+)")
# keys ComfyUI does not apply on klein (the diffusers and unprefixed layouts, S0 (a))
UNUSED = re.compile(r"(double_stream_modulation|single_stream_modulation)")
# known model shapes: (width, double blocks, single blocks) -> name (S0 (b))
SHAPES = {(3072, 5, 20): "FLUX.2 klein 4B", (4096, 8, 24): "FLUX.2 klein 9B",
          (3072, 19, 38): "FLUX.1"}  # fmt: skip
TARGET = "FLUX.2 klein 4B"  # the model the image screens run
SAFE = re.compile(r"[^A-Za-z0-9._-]+")
TRAINED = re.compile(r"^wasify-(.*)-([0-9a-f]{8})\.safetensors$")


class StyleRefused(Exception):
    """A file or request that cannot be used; `str(e)` is a sentence for the screen."""


@dataclass
class StyleHeader:
    model: str | None  # "FLUX.2 klein 4B", "FLUX.1", ... or None when not known
    fit: Fit
    base: bool | None  # made for klein base (True), distilled (False), not said (None)
    rank: int | None
    unused_parts: int  # tensors this app does not apply (said in one line)
    trigger: str | None
    title: str | None


def _metadata_trigger(meta: dict[str, Any]) -> str | None:
    """A trigger word from the header: `trigger` (not a `[placeholder]`), else the dataset folder
    names of `ss_tag_frequency` (`1_PXART4` is the word `PXART4`; S0 (e))."""
    word = str(meta.get("trigger") or "").strip()
    if word and not (word.startswith("[") and word.endswith("]")):
        return word[:80]
    raw = meta.get("ss_tag_frequency")
    try:
        folders = json.loads(raw) if isinstance(raw, str) else {}
    except ValueError:
        folders = {}
    words = [re.sub(r"^\d+_", "", str(k)).strip() for k in folders]
    words = [w for w in words if w]
    return ", ".join(words)[:80] if words else None


def read_style_header(path: Path) -> StyleHeader:
    """Judge the header of a `.safetensors` file; StyleRefused says why it is not a style."""
    try:
        with path.open("rb") as f:
            raw = f.read(8)
            if len(raw) != 8:
                raise StyleRefused("This file is empty or cut short.")
            (n,) = struct.unpack("<Q", raw)
            if n == 0 or n > MAX_HEADER_BYTES:
                raise StyleRefused("This is not a style file this app can read.")
            head = json.loads(f.read(n))
    except (OSError, ValueError, struct.error) as e:
        raise StyleRefused("This is not a style file this app can read.") from e
    if not isinstance(head, dict):
        raise StyleRefused("This is not a style file this app can read.")
    raw_meta = head.pop("__metadata__", None)
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    tensors = head
    if not tensors or not all(
        isinstance(v, dict) and {"dtype", "shape", "data_offsets"} <= set(v)
        for v in tensors.values()
    ):
        raise StyleRefused("This file holds something other than weights.")
    names = list(tensors)
    if not all(LORA_PART.search(k) for k in names):
        if any("lora" in k for k in names):
            raise StyleRefused("This file mixes a style with other weights.")
        raise StyleRefused("This is a model, not a style (a LoRA).")
    doubles = {int(m.group(1)) for k in names if (m := BLOCK.search(k))}
    singles = {int(m.group(1)) for k in names if (m := SINGLE.search(k))}
    widths: dict[int, int] = {}
    ranks: dict[int, int] = {}
    for k, v in tensors.items():
        shape = v.get("shape") or []
        if len(shape) == 2 and re.search(r"(lora_A|lora_down)", k):
            ranks[shape[0]] = ranks.get(shape[0], 0) + 1
            widths[shape[1]] = widths.get(shape[1], 0) + 1
    width = max(widths, key=lambda w: widths[w]) if widths else None
    model, fit = _fingerprint(width, doubles, singles)
    taught = str(meta.get("taught_on") or "")
    return StyleHeader(
        model=model, fit=fit, base=("base" in taught) if taught else None,
        rank=max(ranks, key=lambda r: ranks[r]) if ranks else None,
        unused_parts=sum(1 for k in names if UNUSED.search(k)),
        trigger=_metadata_trigger(meta),
        title=str(meta.get("modelspec.title") or meta.get("ss_output_name") or "") or None,
    )  # fmt: skip


def _fingerprint(width: int | None, doubles: set[int], singles: set[int]) -> tuple[str | None, Fit]:
    """S0 (b): klein 4B is width 3072 with blocks 0..4 and 0..19; more blocks or another width is
    another model; no block names at all is "not sure"."""
    if not doubles and not singles:
        return None, "unsure"
    d, s = (max(doubles) + 1 if doubles else 0), (max(singles) + 1 if singles else 0)
    for (w, dd, ss), name in SHAPES.items():
        if width == w and d == dd and s == ss:
            return name, "fits" if name == TARGET else "other"
    if width == 3072 and d <= 5 and s <= 20:
        return TARGET, "fits"  # a style that trained only some blocks
    if width == 4096 or d > 5 or s > 20:
        return next((n for (w, dd, ss), n in SHAPES.items() if w == width and d <= dd and s <= ss),
                    None), "other"  # fmt: skip
    return None, "unsure"


# ---- records ------------------------------------------------------------------------------------


@dataclass
class Style:
    id: str
    title: str
    file: str  # the name in the `loras` folder: what the workflow is given, never shown as a path
    source: dict[str, Any]  # {"kind": "trained" | "file" | "hub" | "found", ...}
    sha256: str
    size: int
    model: str | None
    fit: Fit
    base: bool | None
    rank: int | None
    unused_parts: int
    trigger: str | None
    added_at: float
    extra: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        out = asdict(self)
        out.pop("file")
        out.pop("extra")
        out["selectable"] = self.fit != "other"
        out["made_for_base"] = bool(self.base)
        return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_stem(name: str) -> str:
    stem = SAFE.sub("-", Path(name).stem).strip("-.")[:60]
    return stem or "style"


class StylesService:
    """The records of the styles in `<models>/loras`, kept as sidecars beside the files, and the
    person's saved looks (in the app's settings)."""

    def __init__(self, loras_dir: Path, settings: Any = None):
        self.dir = loras_dir
        self._settings = settings  # a SettingsStore: the saved looks; none, they are kept in memory
        self._looks_here: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    def _sidecar(self, file: str) -> Path:
        return self.dir / f"{file}{SIDECAR}"

    def _read(self, file: str) -> Style | None:
        try:
            raw = json.loads(self._sidecar(file).read_text())
            return Style(**{k: raw[k] for k in Style.__dataclass_fields__ if k in raw})
        except (OSError, ValueError, TypeError):
            return None

    def _write(self, s: Style) -> None:
        tmp = self._sidecar(s.file).with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(s), indent=1))
        tmp.replace(self._sidecar(s.file))

    def _record(self, path: Path, source: dict[str, Any], h: StyleHeader, digest: str) -> Style:
        source = dict(source)
        named = source.pop("title", None)  # a title the source knows (Train's name), not kept in it
        title = named or h.title or path.stem.replace("-", " ").replace("_", " ")
        return Style(
            id=secrets.token_hex(6), title=str(title)[:80], file=path.name, source=source,
            sha256=digest, size=path.stat().st_size, model=h.model, fit=h.fit, base=h.base,
            rank=h.rank, unused_parts=h.unused_parts, trigger=h.trigger, added_at=time.time(),
        )  # fmt: skip

    def _list_sync(self) -> list[Style]:
        if not self.dir.is_dir():
            return []
        out: list[Style] = []
        for f in sorted(self.dir.glob("*.safetensors")):
            s = self._read(f.name)
            if s is None:  # a file with no record (Train's, or one put here by hand): adopt it
                try:
                    h = read_style_header(f)
                except StyleRefused:
                    continue
                # Train names its files `wasify-<name>-<first 8 of the run id>`
                made = TRAINED.match(f.name)
                source: dict[str, Any] = (
                    {"kind": "trained", "run": made.group(2),
                     "title": made.group(1).replace("-", " ").strip().capitalize()}
                    if made else {"kind": "found"}
                )  # fmt: skip
                s = self._record(f, source, h, _sha256(f))
                self._write(s)
            out.append(s)
        for side in self.dir.glob(f"*{SIDECAR}"):  # a record whose file went (Train removed it)
            if not (self.dir / side.name[: -len(SIDECAR)]).is_file():
                with contextlib.suppress(OSError):
                    side.unlink()
        # yours first, then by when they were added
        return sorted(out, key=lambda s: (s.source.get("kind") != "trained", -s.added_at))

    async def all(self) -> list[Style]:
        async with self._lock:
            return await asyncio.to_thread(self._list_sync)

    async def get(self, style_id: str) -> Style:
        found = next((s for s in await self.all() if s.id == style_id), None)
        if found is None:
            raise KeyError(style_id)
        return found

    async def import_file(
        self, chunks: AsyncIterator[bytes], name: str, source: dict[str, Any] | None = None
    ) -> Style:
        """Stream a file in, check its header, keep it under a safe name. The original (wherever it
        was) is not touched: this is a copy. The same file twice is the same style."""
        if not name.lower().endswith(".safetensors"):
            raise StyleRefused("Only .safetensors files can be used as styles.")
        await asyncio.to_thread(self.dir.mkdir, parents=True, exist_ok=True)
        part = self.dir / f".incoming-{secrets.token_hex(6)}.part"
        size = 0
        digest = hashlib.sha256()
        try:
            with part.open("wb") as out:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise StyleRefused("This file is too big for a style (over 2 GB).")
                    digest.update(chunk)
                    await asyncio.to_thread(out.write, chunk)
            h = await asyncio.to_thread(read_style_header, part)
            sha = digest.hexdigest()
            async with self._lock:
                existing = await asyncio.to_thread(self._list_sync)
                same = next((s for s in existing if s.sha256 == sha), None)
                if same is not None:
                    return same
                stem = _safe_stem(name)
                target = self.dir / f"{stem}.safetensors"
                n = 2
                while target.exists():
                    target = self.dir / f"{stem}-{n}.safetensors"
                    n += 1
                await asyncio.to_thread(part.replace, target)
                record = self._record(target, {"kind": "file", **(source or {})}, h, sha)
                await asyncio.to_thread(self._write, record)
                return record
        finally:
            with contextlib.suppress(OSError):
                part.unlink()

    async def describe(
        self, file: str, title: str, trigger: str | None, source: dict[str, Any],
        base: bool | None = None,
    ) -> Style | None:  # fmt: skip
        """Name a file of the folder that was put there by the app itself (Train): its record gets
        the real title, the magic word and where it came from. None when the file is not a style."""
        if "/" in file or ".." in file or not (self.dir / file).is_file():
            return None
        async with self._lock:
            s = await asyncio.to_thread(self._read, file)
            if s is None:
                try:
                    h = await asyncio.to_thread(read_style_header, self.dir / file)
                except StyleRefused:
                    return None
                digest = await asyncio.to_thread(_sha256, self.dir / file)
                s = self._record(self.dir / file, source, h, digest)
            s.title = (title.strip() or s.title)[:80]
            s.trigger = (trigger or "").strip()[:80] or s.trigger
            s.source = source
            if base is not None and s.base is None:  # what the source says, when the file does not
                s.base = base
            await asyncio.to_thread(self._write, s)
            return s

    async def import_path(self, path: Path, source: dict[str, Any]) -> Style:
        """A copy of a style another app keeps (found by discovery): read, checked, kept."""

        async def read() -> AsyncIterator[bytes]:
            with path.open("rb") as f:
                while chunk := await asyncio.to_thread(f.read, 1 << 20):
                    yield chunk

        return await self.import_file(read(), path.name, source)

    async def update(self, style_id: str, title: str | None, trigger: str | None) -> Style:
        s = await self.get(style_id)
        if title is not None and title.strip():
            s.title = title.strip()[:80]
        if trigger is not None:
            s.trigger = trigger.strip()[:80] or None
        async with self._lock:
            await asyncio.to_thread(self._write, s)
        return s

    async def delete(self, style_id: str) -> None:
        """Remove our copy and its record. Only files in our own folder are ever deleted."""
        s = await self.get(style_id)
        async with self._lock:
            for p in (self.dir / s.file, self._sidecar(s.file)):
                with contextlib.suppress(FileNotFoundError):
                    await asyncio.to_thread(p.unlink)

    async def resolve(self, wanted: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """`[{id, strength}]` from a request as the workflow's `[{name, weight}]`; StyleRefused when
        a style is unknown or made for another model."""
        if len(wanted) > MAX_STYLES:
            raise StyleRefused(f"Please use at most {MAX_STYLES} styles.")
        styles = {s.id: s for s in await self.all()}
        out = []
        for w in wanted:
            s = styles.get(str(w.get("id")))
            if s is None:
                raise StyleRefused("One of those styles is not on this computer any more.")
            if s.fit == "other":
                raise StyleRefused(
                    f"{s.title} was made for another model and would give noise here."
                )
            out.append({
                "name": s.file, "weight": w.get("strength", 1.0), "sha256": s.sha256,
                "title": s.title,
            })  # fmt: skip
        return out

    # ---- saved looks (ADR-0091 decision 11) ----------------------------------------------------

    async def looks(self) -> list[dict[str, Any]]:
        if self._settings is None:
            return list(self._looks_here)
        saved = await self._settings.get(LOOKS)
        return [dict(x) for x in saved] if isinstance(saved, list) else []

    async def _put_looks(self, looks: list[dict[str, Any]]) -> None:
        if self._settings is None:
            self._looks_here = looks
        else:
            await self._settings.put(LOOKS, looks, "desktop")

    async def save_look(self, look: dict[str, Any]) -> dict[str, Any]:
        """A name for a size, steps and styles; the styles by pointer (id, strength, checksum, title
        and where each came from), never their weights. The same name replaces the old one."""
        name = str(look.get("name") or "").strip()[:60]
        if not name:
            raise StyleRefused("Give the look a name.")
        records = {s.id: s for s in await self.all()}
        styles = []
        for w in look.get("styles") or []:
            s = records.get(str(w.get("id")))
            if s is None:
                raise StyleRefused("One of those styles is not on this computer any more.")
            styles.append({
                "id": s.id, "strength": float(w.get("strength", 1.0)), "sha256": s.sha256,
                "title": s.title, "source": s.source,
            })  # fmt: skip
        kept = {
            "name": name, "size": look.get("size"), "width": look.get("width"),
            "height": look.get("height"), "steps": look.get("steps"), "styles": styles,
            "saved_at": time.time(),
        }  # fmt: skip
        looks = [x for x in await self.looks() if x.get("name") != name]
        if len(looks) >= MAX_LOOKS:
            raise StyleRefused(f"There are {MAX_LOOKS} saved looks already. Delete one first.")
        await self._put_looks([*looks, kept])
        return kept

    async def delete_look(self, name: str) -> None:
        looks = await self.looks()
        left = [x for x in looks if x.get("name") != name]
        if len(left) == len(looks):
            raise KeyError(name)
        await self._put_looks(left)

    async def files_for(self, wanted: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
        """`resolve` for the image graph, which imports nothing from here: (loras, why refused)."""
        try:
            return await self.resolve(wanted), ""
        except StyleRefused as e:
            return [], str(e)


# ---- Hugging Face (S3) ---------------------------------------------------------------------------

REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
HF_URL = re.compile(r"^(?:https?://)?(?:www\.)?huggingface\.co/([^/?#]+/[^/?#]+)")
PICKLES = (".ckpt", ".pt", ".pth", ".bin", ".pkl")


def repo_of(text: str) -> str | None:
    """`owner/name`, or a huggingface.co address of one, as `owner/name`; None for anything else."""
    text = text.strip()
    m = HF_URL.match(text)
    repo = m.group(1) if m else text
    return repo if REPO.match(repo) else None


def card_of(data: dict[str, Any]) -> tuple[bool | None, str | None]:
    """(made for klein base?, the trigger word) from a repository's card data."""
    card = data.get("cardData") or {}
    bases = card.get("base_model") or []
    bases = [bases] if isinstance(bases, str) else [str(b) for b in bases]
    tags = [t for t in data.get("tags", []) if isinstance(t, str) and t.startswith("base_model:")]
    said = " ".join(bases + tags).lower()
    base = None
    if "klein-base" in said:
        base = True
    elif "flux.2-klein" in said:
        base = False
    word = card.get("instance_prompt")
    return base, (str(word).strip()[:80] or None) if word else None


def _style_name(repo: str, file: str) -> str:
    return _safe_stem(f"{repo.replace('/', '--')}--{Path(file).stem}") + ".safetensors"


def style_files_of(repo: str, data: dict[str, Any]) -> dict[str, Any]:
    """What a repository offers as styles, from the Hub's answer: its `.safetensors` files with
    their sizes; the others named with why not (the desktop, and the web's admin)."""
    offered, refused = [], []
    for sib in data.get("siblings", []):
        name = str(sib.get("rfilename", ""))
        size = int((sib.get("lfs") or {}).get("size") or sib.get("size") or 0)
        low = name.lower()
        if low.endswith(".safetensors"):
            if size > MAX_FILE_BYTES:
                refused.append({"name": name, "why": "too big for a style (over 2 GB)"})
            else:
                offered.append({"name": name, "size": size})
        elif low.endswith(PICKLES):
            refused.append({"name": name, "why": "not offered: it can run code"})
    base, word = card_of(data)
    return {
        "repo": repo, "commit": data.get("sha"), "gated": bool(data.get("gated")),
        "files": offered, "refused": refused, "made_for_base": base, "trigger": word,
        "stale": bool(data.get("_stale")),
    }  # fmt: skip


_FINISHING: set[asyncio.Task[None]] = set()


class HubStyles:
    """Styles from Hugging Face through the model hub (ADR-0064): nothing is asked before the
    person allowed browsing; the exact file and size are confirmed; the file comes from the commit
    that was looked at, is checked against the size and checksum the Hub gives, then its header is
    read here like any other style before it is kept."""

    def __init__(
        self, styles: StylesService, hub: Any, models: Any,
        jobs: dict[str, dict[str, Any]] | None = None,
    ):  # fmt: skip
        self.styles = styles
        self.hub = hub  # HubService: consent and the Hugging Face client
        self.models = models  # ModelsService: the download manager and the models folder
        self.jobs = {} if jobs is None else jobs  # download id -> {style | refused}

    async def _repo(self, repo: str) -> dict[str, Any]:
        self.hub.require()
        data, stale = await self.hub.client.get(
            f"/api/models/{repo}", {"blobs": "true"}, fresh=True
        )
        if not isinstance(data, dict):
            raise HubError("hub_error", "Hugging Face answered something unexpected.", 502)
        data["_stale"] = stale
        return data

    async def files(self, text: str) -> dict[str, Any]:
        """What a repository offers as styles: its `.safetensors` files with their sizes; the
        others named with why they are not offered."""
        repo = repo_of(text)
        if repo is None:
            raise HubError("bad_repo", "Write a name like owner/name, or paste its address.", 422)
        return style_files_of(repo, await self._repo(repo))

    async def download(
        self, repo: str, file: str, size: int, expect_sha256: str | None = None
    ) -> dict[str, Any]:
        """Start getting one confirmed file; when it is done it is checked and kept as a style."""
        if repo_of(repo) != repo:
            raise HubError("bad_repo", "That is not a model name.", 422)
        data = await self._repo(repo)
        commit = str(data.get("sha") or "")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise HubError("no_revision", "The model's revision could not be read.", 502)
        if data.get("gated") and not self.hub.client.has_token:
            raise HubError(
                "needs_token",
                "This style is gated: it needs a Hugging Face account that accepted its terms. "
                "Add your Hugging Face token in Settings.",
                403,
            )
        sib = next((x for x in data.get("siblings", []) if x.get("rfilename") == file), None)
        lfs = (sib or {}).get("lfs") or {}
        real = int(lfs.get("size") or (sib or {}).get("size") or 0)
        sha = str(lfs.get("sha256") or "")
        if sib is None or not file.lower().endswith(".safetensors") or real != size:
            raise HubError(
                "changed", "The files changed. Look at the style again and confirm.", 409
            )
        if size > MAX_FILE_BYTES or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise HubError("refused", "That file cannot be used as a style.", 422)
        if expect_sha256 and sha != expect_sha256:  # a recommended style that changed since
            raise HubError(
                "changed", "This style changed since we checked it, so it is not offered.", 409
            )
        name = _style_name(repo, file)
        target = ModelFile("loras", name, f"{HF}/{repo}/resolve/{commit}/{quote(file)}", size, sha)
        entry = ModelEntry(
            id=f"style:{repo}/{file}", product_id="styles", title=repo,
            source=f"huggingface.co/{repo}", note="", approx_ram_gb=0, files=(target,),
        )  # fmt: skip
        d = self.models.downloads.start(entry, [target], self.models.models_dir)
        base, word = card_of(data)
        self.jobs[d.id] = {}
        title = Path(file).stem.replace("_", " ").replace("-", " ")
        source = {"kind": "hub", "repo": repo, "file": file, "commit": commit}
        task = asyncio.get_running_loop().create_task(
            self._finish(d, name, title, word, source, base)
        )
        _FINISHING.add(task)  # held until it is done: a task nobody holds may be dropped
        task.add_done_callback(_FINISHING.discard)
        return d.public()

    async def _finish(
        self, d: Any, name: str, title: str, word: str | None, source: dict[str, Any],
        base: bool | None,
    ) -> None:  # fmt: skip
        with contextlib.suppress(asyncio.CancelledError):
            if d.task is not None:
                await asyncio.shield(d.task)
        if d.status != "done":
            return
        path = self.styles.dir / name
        try:
            await asyncio.to_thread(read_style_header, path)
        except StyleRefused as e:  # downloaded, but not a style: it goes again
            with contextlib.suppress(OSError):
                path.unlink()
            self.jobs[d.id] = {"refused": str(e)}
            return
        s = await self.styles.describe(name, title, word, source, base)
        self.jobs[d.id] = {"style": s.public() if s else None}

    def job(self, download_id: str) -> dict[str, Any] | None:
        d = self.models.downloads.get(download_id)
        if d is None or download_id not in self.jobs:
            return None
        return {"download": d.public(), **self.jobs[download_id]}


# ---- routes -------------------------------------------------------------------------------------

router = APIRouter(prefix="/desktop/styles", tags=["desktop"])


def _svc(request: Request) -> StylesService:
    svc = services_of(request).desktop_styles
    if svc is None:
        raise HTTPException(404, "not available in this deployment")
    return svc


def _refused(e: StyleRefused) -> HTTPException:
    return HTTPException(422, {"code": "style_refused", "message": str(e)})


@router.get("")
async def list_styles(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    """The styles kept here, and the ones other apps keep on this computer (found by Settings ›
    Models), which are copied in when chosen."""
    svc = _svc(request)
    discovery = services_of(request).desktop_discovery
    found = [
        {"id": i.id, "title": i.name, "tool": i.tool_title, "size": i.size}
        for i in (discovery.items if discovery else [])
        if i.kind == "lora" and i.family != "ltx-video" and str(i.path).endswith(".safetensors")
        and Path(i.path).parent.resolve() != svc.dir.resolve()
    ]  # fmt: skip
    styles = await svc.all()
    here = {s.sha256 for s in styles}
    recommended = [dict(r) for r in RECOMMENDED if r["sha256"] not in here]
    return {
        "styles": [s.public() for s in styles], "found": found, "max": MAX_STYLES,
        "recommended": recommended,
    }  # fmt: skip


@router.post("/import", status_code=201)
async def import_style(
    request: Request,
    name: str = Query(..., min_length=1, max_length=200),
    _: Identity = Depends(get_identity),
) -> dict[str, Any]:
    """A style from this computer: the file itself is the body (the window never sends a path)."""
    declared = int(request.headers.get("content-length") or 0)
    if declared > MAX_FILE_BYTES:
        raise _refused(StyleRefused("This file is too big for a style (over 2 GB)."))
    try:
        s = await _svc(request).import_file(request.stream(), name)
    except StyleRefused as e:
        raise _refused(e) from None
    return s.public()


class StyleEdit(BaseModel):
    title: str | None = Field(None, max_length=80)
    trigger: str | None = Field(None, max_length=80)


class FromFound(BaseModel):
    id: str = Field(max_length=200)


@router.post("/from-found", status_code=201)
async def style_from_found(
    body: FromFound, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    """A style another app keeps on this computer (Settings › Models found it): a checked copy."""
    discovery = services_of(request).desktop_discovery
    item = next((i for i in (discovery.items if discovery else []) if i.id == body.id), None)
    if item is None or item.kind != "lora" or not str(item.path).endswith(".safetensors"):
        raise HTTPException(404, "no such style")
    source = {"kind": "found", "tool": item.tool_title}
    try:
        s = await _svc(request).import_path(Path(item.path), source)
    except (StyleRefused, OSError) as e:
        raise _refused(e if isinstance(e, StyleRefused) else StyleRefused(
            "That file could not be read."
        )) from None  # fmt: skip
    return s.public()


_JOBS: dict[str, dict[str, Any]] = {}  # the downloads started here, across requests


def _hub_styles(request: Request) -> HubStyles:
    svc = services_of(request)
    if svc.desktop_styles is None or svc.desktop_hub is None or svc.desktop_models is None:
        raise HTTPException(404, "not available in this deployment")
    return HubStyles(svc.desktop_styles, svc.desktop_hub, svc.desktop_models, _JOBS)


class HubLook(BaseModel):
    repo: str = Field(min_length=1, max_length=300)


class HubGet(BaseModel):
    repo: str = Field(max_length=200)
    file: str = Field(min_length=1, max_length=300)
    bytes: int = Field(ge=1)
    # a recommended style: the checksum we checked; a file that differs is not fetched
    sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")


def _hub_error(e: Exception) -> HTTPException:
    return HTTPException(
        getattr(e, "status", 502),
        {"code": getattr(e, "code", "hub_error"), "message": getattr(e, "message", str(e))},
    )


@router.post("/hub/files")
async def hub_files(
    body: HubLook, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    """The style files of a Hugging Face repository (after the person allowed browsing)."""
    try:
        return await _hub_styles(request).files(body.repo)
    except HubError as e:
        raise _hub_error(e) from None


@router.post("/hub/download", status_code=202)
async def hub_download(
    body: HubGet, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    """Get one confirmed file; follow it with GET /hub/downloads/{id}."""
    hub = _hub_styles(request)
    try:
        return await hub.download(body.repo, body.file, body.bytes, body.sha256)
    except HubError as e:
        raise _hub_error(e) from None
    except DownloadError as e:
        raise HTTPException(409, {"code": "download", "message": str(e)}) from None


@router.get("/hub/downloads/{download_id}")
async def hub_download_state(
    download_id: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    """The download, and once it is done the style that was kept, or why the file was refused."""
    found = _hub_styles(request).job(download_id)
    if found is None:
        raise HTTPException(404, "unknown download")
    return found


class LookIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    size: str | None = Field(None, max_length=20)
    width: int | None = Field(None, ge=256, le=2048)
    height: int | None = Field(None, ge=256, le=2048)
    steps: int | None = Field(None, ge=1, le=50)
    styles: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_STYLES)


@router.get("/looks")
async def list_looks(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    return {"looks": await _svc(request).looks()}


@router.put("/looks")
async def save_look(
    body: LookIn, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    try:
        return await _svc(request).save_look(body.model_dump())
    except StyleRefused as e:
        raise _refused(e) from None


@router.delete("/looks/{name}", status_code=204)
async def delete_look(name: str, request: Request, _: Identity = Depends(get_identity)) -> None:
    try:
        await _svc(request).delete_look(name)
    except KeyError:
        raise HTTPException(404, "no such look") from None


@router.patch("/{style_id}")
async def edit_style(
    style_id: str, body: StyleEdit, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    """Rename a style or set its trigger word."""
    try:
        s = await _svc(request).update(style_id, body.title, body.trigger)
    except KeyError:
        raise HTTPException(404, "no such style") from None
    return s.public()


@router.delete("/{style_id}", status_code=204)
async def delete_style(
    style_id: str, request: Request, _: Identity = Depends(get_identity)
) -> None:
    try:
        await _svc(request).delete(style_id)
    except KeyError:
        raise HTTPException(404, "no such style") from None
