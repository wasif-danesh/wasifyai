"""Models on the desktop (ADR-0059, docs/phase2-stage-a-plan.md, step A3): what can be used, what
is on this computer, and getting a missing one.

    load_catalogue()   the products' `models.yaml` files: id, licence, source, files (size, SHA-256)
    ModelsService      where models live (the app's folder plus read-only extra folders), what is
                       present, the memory and disk checks, removal
    DownloadManager    one download at a time: resumable, checksum verified, atomic, cancellable
    router             `/desktop/...` routes the window uses (token-protected like every route)

Nothing is downloaded by itself: a download starts only from a request that repeats the exact files
and total size the window showed the person (`Confirm`), so a stale or forged call is refused.
"""

import asyncio
import hashlib
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from wasifyai_platform_sdk import Identity, VoiceModel, parse_voice_model

from wasifyai_api.desktop_fit import (
    Machine,
    assess_fit,
    need_declared,
    physical_memory_bytes,
    process_rss_bytes,
    read_machine,
)
from wasifyai_api.identity import get_identity
from wasifyai_api.safeguards import SettingsStore

log = logging.getLogger(__name__)

FOLDERS_KEY = "desktop.model_folders"
DISK_MARGIN = 1_000_000_000  # keep this much free after a download
ALLOWED_FOLDERS = frozenset(
    {
        "checkpoints", "diffusion_models", "unet", "text_encoders", "clip", "vae", "loras",
        "controlnet", "upscale_models", "embeddings", "audio",
    }
)  # fmt: skip


# ---- the catalogue ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelFile:
    folder: str
    name: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ModelEntry:
    id: str
    product_id: str
    title: str
    licence: str
    source: str
    note: str
    approx_ram_gb: int
    files: tuple[ModelFile, ...]
    voice: VoiceModel | None = None  # the descriptor of a speech, music or avatar model (ADR-0066)

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)


def _safe_name(name: str) -> bool:
    return bool(name) and "/" not in name and "\\" not in name and name not in (".", "..")


def parse_catalogue(raw: dict[str, Any], product_id: str) -> list[ModelEntry]:
    out: list[ModelEntry] = []
    for m in raw.get("models") or []:
        files = []
        for f in m["files"]:
            if f["folder"] not in ALLOWED_FOLDERS or not _safe_name(f["name"]):
                raise ValueError(f"{m['id']}: bad folder or file name {f['folder']}/{f['name']}")
            if urlparse(f["url"]).scheme != "https":
                raise ValueError(f"{m['id']}: {f['name']} must be an https URL")
            sha = str(f["sha256"]).lower()
            if len(sha) != 64 or int(f["size"]) <= 0:
                raise ValueError(f"{m['id']}: {f['name']} needs a size and a SHA-256")
            files.append(ModelFile(f["folder"], f["name"], f["url"], int(f["size"]), sha))
        out.append(
            ModelEntry(
                id=m["id"], product_id=product_id, title=m["title"], licence=m["licence"],
                source=m["source"], note=m.get("note", ""),
                approx_ram_gb=int(m.get("approx_ram_gb", 0)), files=tuple(files),
                voice=parse_voice_model(m["id"], m["title"], m["licence"], m["voice"])
                if m.get("voice") else None,
            )
        )  # fmt: skip
    return out


def load_catalogue(products_dir: Path, product_ids: list[str]) -> list[ModelEntry]:
    out: list[ModelEntry] = []
    for pid in product_ids:
        path = products_dir / pid / "models.yaml"
        if path.is_file():
            out += parse_catalogue(yaml.safe_load(path.read_text()) or {}, pid)
    return out


# ---- the computer -----------------------------------------------------------------------------


def free_disk_bytes(path: Path) -> int:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


# ---- downloads --------------------------------------------------------------------------------


class DownloadError(Exception):
    """A message that is fit to show a person."""


@dataclass
class Download:
    id: str
    entry_id: str
    files: list[str]
    bytes_total: int
    bytes_done: int = 0
    status: str = "running"  # running | done | failed | cancelled
    current: str = ""
    error: str = ""
    started_at: float = field(default_factory=time.time)
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id, "entry_id": self.entry_id, "files": self.files,
            "bytes_total": self.bytes_total, "bytes_done": self.bytes_done,
            "status": self.status, "current": self.current, "error": self.error,
        }  # fmt: skip


class DownloadManager:
    """One download at a time. Files go to `<models dir>/<folder>/<name>`, written as
    `<name>.part` and renamed when the size and checksum match; a partial file is continued with a
    Range request."""

    def __init__(self, client_factory=None, chunk: int = 1 << 20, token: str | None = None):
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(
                follow_redirects=True, timeout=httpx.Timeout(30, read=60), http2=False
            )
        )
        self._chunk = chunk
        self._token = token  # a Hugging Face token, sent only to huggingface.co
        self._downloads: dict[str, Download] = {}
        self._active: Download | None = None

    @property
    def active(self) -> Download | None:
        a = self._active
        return a if a and a.status == "running" else None

    def get(self, download_id: str) -> Download | None:
        return self._downloads.get(download_id)

    def latest(self) -> Download | None:
        return max(self._downloads.values(), key=lambda d: d.started_at, default=None)

    def start(self, entry: ModelEntry, files: list[ModelFile], models_dir: Path) -> Download:
        if self.active:
            raise DownloadError("A download is already running. Wait for it, or cancel it.")
        needed = sum(f.size for f in files) - sum(_part_size(models_dir, f) for f in files)
        free = free_disk_bytes(models_dir)
        if free < needed + DISK_MARGIN:
            raise DownloadError(
                f"There is not enough free space: {needed / 1e9:.1f} GB is needed and "
                f"{free / 1e9:.1f} GB is free on that drive. Free some space or choose another "
                "models folder."
            )
        d = Download(
            id=str(uuid4()), entry_id=entry.id, files=[f.name for f in files],
            bytes_total=sum(f.size for f in files),
        )  # fmt: skip
        self._downloads[d.id] = d
        self._active = d
        d.task = asyncio.get_running_loop().create_task(self._run(d, files, models_dir))
        return d

    def cancel(self, download_id: str) -> bool:
        d = self._downloads.get(download_id)
        if d is None or d.status != "running" or d.task is None:
            return False
        d.task.cancel()
        return True

    async def _run(self, d: Download, files: list[ModelFile], models_dir: Path) -> None:
        try:
            async with self._client_factory() as client:
                for f in files:
                    d.current = f.name
                    await self._one(client, d, f, models_dir)
            d.status, d.current = "done", ""
        except asyncio.CancelledError:
            d.status = "cancelled"  # the partial file is kept: a later start continues it
        except DownloadError as e:
            d.status, d.error = "failed", str(e)
        except (httpx.HTTPError, OSError) as e:
            log.warning("model download failed: %s", e)
            d.status = "failed"
            d.error = (
                "The download was interrupted. Check the connection and try again: it continues "
                "where it stopped."
            )
        finally:
            if self._active is d:
                self._active = None

    async def _one(
        self, client: httpx.AsyncClient, d: Download, f: ModelFile, models_dir: Path
    ) -> None:
        final = models_dir / f.folder / f.name
        part = final.with_name(f.name + ".part")
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.is_file() and final.stat().st_size == f.size:
            d.bytes_done += f.size
            return
        have = part.stat().st_size if part.is_file() else 0
        if have > f.size:
            part.unlink()
            have = 0
        digest = hashlib.sha256()
        if have:
            digest = await asyncio.to_thread(_hash_prefix, part, digest)
        headers = {"Range": f"bytes={have}-"} if have else {}
        if self._token and urlparse(f.url).hostname == "huggingface.co":
            headers["Authorization"] = f"Bearer {self._token}"
        async with client.stream("GET", f.url, headers=headers) as r:
            if r.status_code == 416 and have == f.size:
                pass  # the whole file is already here
            elif r.status_code not in (200, 206):
                raise DownloadError(f"The download server answered {r.status_code}.")
            elif r.status_code == 200 and have:
                have, digest = 0, hashlib.sha256()  # the server ignored Range: start again
                part.unlink(missing_ok=True)
            if r.status_code in (200, 206):
                mode = "ab" if have else "wb"
                with part.open(mode) as out:
                    d.bytes_done += have
                    async for chunk in r.aiter_bytes():
                        out.write(chunk)
                        digest.update(chunk)
                        d.bytes_done += len(chunk)
                        await asyncio.sleep(0)
                have = part.stat().st_size
            else:
                d.bytes_done += have
        if have != f.size or digest.hexdigest() != f.sha256:
            part.unlink(missing_ok=True)
            d.bytes_done -= min(d.bytes_done, have)
            raise DownloadError(
                f"{f.name} did not match its published checksum, so it was not kept. Try again."
            )
        os.replace(part, final)


def _part_size(models_dir: Path, f: ModelFile) -> int:
    part = models_dir / f.folder / (f.name + ".part")
    return part.stat().st_size if part.is_file() else 0


def _hash_prefix(path: Path, digest: Any) -> Any:
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 22):
            digest.update(chunk)
    return digest


# ---- the service ------------------------------------------------------------------------------


class ModelsService:
    def __init__(
        self,
        catalogue: list[ModelEntry],
        default_models_dir: Path,
        default_extra_dirs: tuple[Path, ...],
        store: SettingsStore,
        downloads: DownloadManager | None = None,
    ):
        self.catalogue = {e.id: e for e in catalogue}
        self._default_models = default_models_dir
        self._default_extra = default_extra_dirs
        self._store = store
        self.downloads = downloads or DownloadManager()
        self.models_dir = default_models_dir
        self.extra_dirs = default_extra_dirs
        self.sidecar: Any = None  # set when the worker is built; told about folder changes
        self.llama: Any = None  # the LlamaServer, when the language engine is there
        self.audio: Any = None  # the AudioEngine (ADR-0066)
        self.slot: Any = None

    async def load(self) -> None:
        """Take the folders a person chose earlier, if any."""
        saved = await self._store.get(FOLDERS_KEY)
        if isinstance(saved, dict):
            if saved.get("models_dir"):
                self.models_dir = Path(str(saved["models_dir"]))
            extra = saved.get("extra_dirs")
            if isinstance(extra, list):
                self.extra_dirs = tuple(Path(str(p)) for p in extra)
        self._tell_sidecar()

    async def set_folders(self, models_dir: str | None, extra_dirs: list[str]) -> None:
        def resolve() -> tuple[Path, tuple[Path, ...]]:
            chosen = Path(models_dir).expanduser() if models_dir else self._default_models
            chosen.mkdir(parents=True, exist_ok=True)
            extra = tuple(Path(p).expanduser() for p in extra_dirs if p.strip())
            return chosen, extra

        self.models_dir, self.extra_dirs = await asyncio.to_thread(resolve)
        await self._store.put(
            FOLDERS_KEY,
            {"models_dir": str(self.models_dir), "extra_dirs": [str(p) for p in self.extra_dirs]},
            "window",
        )
        self._tell_sidecar()

    def _tell_sidecar(self) -> None:
        if self.sidecar is not None:
            self.sidecar.set_model_dirs(self.models_dir, self.extra_dirs)

    def roots(self) -> list[Path]:
        return [self.models_dir, *self.extra_dirs]

    def locate(self, f: ModelFile) -> Path | None:
        for root in self.roots():
            p = root / f.folder / f.name
            if p.is_file() and p.stat().st_size == f.size:
                return p
        return None

    def reclaimable_bytes(self) -> int:
        """Memory the app's own resident model holds: free to whatever is loaded next."""
        slot = self.slot
        if slot is None or not slot.resident_owner:
            return 0
        owner = {"image": self.sidecar, "chat": self.llama, "audio": self.audio}.get(
            slot.resident_owner
        )
        if owner is self.audio and owner is not None:
            owner = owner.server
        return process_rss_bytes(getattr(owner, "pid", None)) if owner is not None else 0

    async def machine(self) -> Machine:
        """The computer's memory now (a few commands are run: not on the event loop)."""
        return await asyncio.to_thread(lambda: read_machine(self.reclaimable_bytes()))

    def entry_state(self, e: ModelEntry, machine: Machine | None = None) -> dict[str, Any]:
        files = []
        for f in e.files:
            found = self.locate(f)
            files.append(
                {
                    "folder": f.folder, "name": f.name, "size": f.size,
                    "present": found is not None,
                    "location": str(found.parent.parent) if found else None,
                    "removable": bool(found and found.is_relative_to(self.models_dir)),
                    "partial_bytes": _part_size(self.models_dir, f),
                }
            )  # fmt: skip
        missing = [f for f in files if not f["present"]]
        status = "ready" if not missing else ("partial" if len(missing) < len(files) else "missing")
        fit = None
        if e.approx_ram_gb:
            fit = assess_fit(need_declared(e.approx_ram_gb), machine or read_machine())
        gate = fit.reason if fit and fit.verdict != "fits" else None
        return {
            "id": e.id, "product_id": e.product_id, "title": e.title, "licence": e.licence,
            "source": e.source, "note": e.note, "approx_ram_gb": e.approx_ram_gb,
            "status": status,
            "files": files, "bytes_total": e.total_bytes,
            "bytes_missing": sum(f["size"] for f in missing),
            "memory_warning": gate,
            "fit": fit.public() if fit else None,
            "voice": e.voice.public() if e.voice else None,
        }  # fmt: skip

    def remove(self, e: ModelEntry) -> int:
        """Delete this entry's files from the app's own folder. Files in extra folders are never
        touched. Returns the number removed."""
        n = 0
        for f in e.files:
            p = self.models_dir / f.folder / f.name
            for target in (p, p.with_name(p.name + ".part")):
                if target.is_file():
                    target.unlink()
                    n += 1
        return n


# ---- routes -----------------------------------------------------------------------------------

router = APIRouter(prefix="/desktop", tags=["desktop"])


def _svc(request: Request) -> ModelsService:
    svc = getattr(request.app.state, "desktop_models", None)
    if svc is None:
        raise HTTPException(404, "not available in this deployment")
    return svc


def _entry(svc: ModelsService, entry_id: str) -> ModelEntry:
    e = svc.catalogue.get(entry_id)
    if e is None:
        raise HTTPException(404, "unknown model")
    return e


class Confirm(BaseModel):
    """What the person was shown and agreed to: the files that will be fetched and their size."""

    files: list[str]
    bytes: int
    # the person was told the model will not fit and still wants the files (for another machine)
    accept_memory: bool = False


class Folders(BaseModel):
    models_dir: str | None = None
    extra_dirs: list[str] = []


@router.get("/models")
async def list_models(
    request: Request, task: str | None = None, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    svc = _svc(request)
    ram = physical_memory_bytes()
    machine = await svc.machine()
    active = svc.downloads.active or svc.downloads.latest()
    return {
        "models": [
            svc.entry_state(e, machine)
            for e in svc.catalogue.values()
            if task is None or (e.voice is not None and task in e.voice.tasks)
        ],
        "machine": machine.public(),
        "folders": {
            "models_dir": str(svc.models_dir),
            "extra_dirs": [str(p) for p in svc.extra_dirs],
        },
        "memory_bytes": ram,
        "disk_free_bytes": free_disk_bytes(svc.models_dir),
        "download": active.public() if active else None,
    }


@router.post("/models/{entry_id}/download")
async def start_download(
    entry_id: str, body: Confirm, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    svc = _svc(request)
    e = _entry(svc, entry_id)
    missing = [f for f in e.files if svc.locate(f) is None]
    if not missing:
        raise HTTPException(409, "Everything this model needs is already on this computer.")
    if sorted(body.files) != sorted(f.name for f in missing) or body.bytes != sum(
        f.size for f in missing
    ):
        raise HTTPException(409, "The list of files changed. Review it and confirm again.")
    if e.approx_ram_gb and not body.accept_memory:
        fit = assess_fit(need_declared(e.approx_ram_gb), await svc.machine())
        if fit.verdict == "too_big":
            raise HTTPException(409, f"This model will not fit on this computer. {fit.reason}")
    try:
        d = svc.downloads.start(e, missing, svc.models_dir)
    except DownloadError as exc:
        raise HTTPException(409, str(exc)) from None
    return d.public()


@router.get("/downloads/{download_id}")
async def get_download(
    download_id: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    d = _svc(request).downloads.get(download_id)
    if d is None:
        raise HTTPException(404, "unknown download")
    return d.public()


@router.post("/downloads/{download_id}/cancel")
async def cancel_download(
    download_id: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, bool]:
    return {"cancelled": _svc(request).downloads.cancel(download_id)}


@router.delete("/models/{entry_id}")
async def remove_model(
    entry_id: str, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, int]:
    svc = _svc(request)
    if svc.downloads.active:
        raise HTTPException(409, "Wait for the download to finish first.")
    return {"removed": svc.remove(_entry(svc, entry_id))}


@router.put("/models/folders")
async def set_folders(
    body: Folders, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    svc = _svc(request)
    try:
        await svc.set_folders(body.models_dir, body.extra_dirs)
    except OSError as exc:
        raise HTTPException(422, f"That folder cannot be used: {exc.strerror or exc}") from None
    return {"models_dir": str(svc.models_dir), "extra_dirs": [str(p) for p in svc.extra_dirs]}


@router.get("/engine")
async def engine_state(request: Request, _: Identity = Depends(get_identity)) -> dict[str, Any]:
    svc = _svc(request)
    side, slot = svc.sidecar, svc.slot
    return {
        "image_engine_installed": bool(side and side.installed),
        "image_engine_running": bool(side and side.running),
        "model_loaded": bool(slot and slot.resident_owner),
        "busy": bool(slot and slot.holding),
    }


@router.post("/engine/unload")
async def unload_engine(request: Request, _: Identity = Depends(get_identity)) -> dict[str, bool]:
    svc = _svc(request)
    if svc.slot is None:
        return {"unloaded": False}
    return {"unloaded": await svc.slot.unload_now()}


__all__ = ["router", "ModelsService", "DownloadManager", "load_catalogue"]
