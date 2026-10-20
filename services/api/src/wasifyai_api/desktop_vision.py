"""Getting the picture reader for the chosen chat model (ADR-0083, stage CO2).

A chat model reads pictures only with its vision projector, a small file llama.cpp loads beside
it. A person who has the file next to their model (Hugging Face and LM Studio keep it there)
needs nothing. For the models on the shelf (`projector-shelf.yaml`: the exact file, its size and
SHA-256) the app can fetch it, but only after the person agreed with the size shown, through the
same download manager as every model (checksum, resume, one at a time). The file is kept under
the app's models folder, not inside another tool's folder.

    VisionService.status()  what the chat box says: ready, can be fetched (what), downloading, or
                            not available
    VisionService.start()   fetch it, after the person confirmed the size
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from wasifyai_api.desktop_language import LanguageService
from wasifyai_api.desktop_models import DownloadError, ModelEntry, ModelFile, ModelsService

log = logging.getLogger(__name__)

SHELF = Path(__file__).with_name("projector-shelf.yaml")
FOLDER = "projectors"
PRODUCT_ID = "wasifyai-assistant"


@dataclass(frozen=True)
class ProjectorEntry:
    id: str
    match: tuple[str, ...]
    title: str
    licence: str
    source: str
    url: str
    name: str
    size: int
    sha256: str


def load_shelf(path: Path = SHELF) -> list[ProjectorEntry]:
    raw = yaml.safe_load(path.read_text()) or {}
    out: list[ProjectorEntry] = []
    for p in raw.get("projectors") or []:
        sha = str(p["sha256"]).lower()
        if not str(p["url"]).startswith("https://") or len(sha) != 64 or int(p["size"]) <= 0:
            raise ValueError(f"{p['id']}: needs an https URL, a size and a SHA-256")
        if "/" in p["name"] or "\\" in p["name"] or "/" in p["id"] or ".." in p["id"]:
            raise ValueError(f"{p['id']}: bad name")
        out.append(
            ProjectorEntry(
                id=p["id"], match=tuple(str(m).lower() for m in p["match"]), title=p["title"],
                licence=p["licence"], source=p["source"], url=p["url"], name=p["name"],
                size=int(p["size"]), sha256=sha,
            )
        )  # fmt: skip
    return out


class VisionService:
    def __init__(
        self,
        language: LanguageService,
        models: ModelsService,
        shelf: list[ProjectorEntry] | None = None,
    ) -> None:
        self.language = language
        self.models = models
        self.shelf = load_shelf() if shelf is None else shelf
        language.shelf_projector = self.fetched_for  # the language service looks here too

    def entry_for(self, model: Path) -> ProjectorEntry | None:
        name = model.name.lower()
        return next((e for e in self.shelf if any(m in name for m in e.match)), None)

    def path_of(self, entry: ProjectorEntry) -> Path:
        return self.models.models_dir / FOLDER / entry.id / entry.name

    def fetched_for(self, model: Path) -> Path | None:
        """The projector the app fetched for this model, when it is there and whole."""
        entry = self.entry_for(model)
        if entry is None:
            return None
        path = self.path_of(entry)
        try:
            return path if path.is_file() and path.stat().st_size == entry.size else None
        except OSError:
            return None

    def _download_entry(self, entry: ProjectorEntry) -> tuple[ModelEntry, ModelFile]:
        f = ModelFile(f"{FOLDER}/{entry.id}", entry.name, entry.url, entry.size, entry.sha256)
        model = ModelEntry(
            id=f"projector:{entry.id}", product_id=PRODUCT_ID, title=entry.title,
            licence=entry.licence, source=entry.source, note="", approx_ram_gb=0, files=(f,),
        )  # fmt: skip
        return model, f

    async def status(self) -> dict[str, Any] | None:
        """None when the chosen model is not a file the app runs (a tool's model decides itself)."""
        sel = self.language.selected
        if sel is None or sel.kind != "file" or not sel.path:
            return None
        if sel.vision:
            return {"state": "ready"}
        entry = self.entry_for(Path(sel.path))
        if entry is None:
            return {"state": "unavailable"}
        if self.fetched_for(Path(sel.path)) is not None:
            await self.language.refresh_projector()  # fetched earlier or just now: pick it up
            return {"state": "ready"}
        d = self.models.downloads.active or self.models.downloads.latest()
        model, _ = self._download_entry(entry)
        if d is not None and d.entry_id == model.id and d.status in ("running", "failed"):
            return {"state": "downloading", **self._about(entry), "download": d.public()}
        return {"state": "available", **self._about(entry)}

    @staticmethod
    def _about(entry: ProjectorEntry) -> dict[str, Any]:
        return {
            "title": entry.title, "licence": entry.licence, "from": entry.source,
            "bytes": entry.size,
        }  # fmt: skip

    async def start(self, confirmed_bytes: int) -> dict[str, Any]:
        """Fetch the chosen model's projector. `confirmed_bytes` is what the person was shown."""
        sel = self.language.selected
        if sel is None or sel.kind != "file" or not sel.path:
            raise DownloadError("Choose a chat model that runs in this app first.")
        entry = self.entry_for(Path(sel.path))
        if entry is None:
            raise DownloadError("This model has no picture reader the app knows how to get.")
        if confirmed_bytes != entry.size:
            raise DownloadError("The size changed. Review it and confirm again.")
        model, f = self._download_entry(entry)
        return self.models.downloads.start(model, [f], self.models.models_dir).public()
