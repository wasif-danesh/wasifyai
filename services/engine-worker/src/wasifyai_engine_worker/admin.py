"""What an admin can ask a worker to do to itself (ADR-0087, P5): fetch a model's files and set up
a component (the lip sync engine, a trainer) through the one installer (stage F2). The same code
serves `models_cli` (the command line) and the `admin.*` jobs the web's Workers page starts. A fetch
reports how far it is and continues a partial file."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from wasifyai_api.components.desktop import lipsync_part, trainer_part
from wasifyai_platform_sdk.installer import InstallError, install_and_wait

from wasifyai_engine_worker.handlers import Failed

Report = Callable[[float, str], Awaitable[None]]
# the names `admin.fetch_engine` takes (admin_wire.ENGINES) for the trainers, and their components
TRAINERS = {
    "image-trainer": "trainer-pictures",
    "writing-trainer": "trainer-writing",
    "decision-trainer": "trainer-deciding",
    "video-trainer": "trainer-video",
}
POLL_S = 1.0


def _gb(n: int | float) -> str:
    return f"{n / 1e9:.1f} GB"


class AdminComponent:
    def __init__(self, speech: Any, poll_s: float = POLL_S, setups: dict[str, Any] | None = None):
        self._speech = speech
        self._poll = poll_s
        self._setups = setups or {}  # trainer components that are set up like the lip sync engine

    async def fetch_model(self, model_id: str, report: Report) -> dict[str, Any]:
        service = self._speech.models_service
        entry = service.catalogue.get(model_id)
        if entry is None or getattr(entry, "voice", None) is None:
            raise Failed("unknown_model", "That is not a model this worker can fetch.")
        missing = [f for f in entry.files if service.locate(f) is None]
        if not missing:
            return {"model_id": model_id, "already": True, "bytes": 0}
        total = sum(f.size for f in missing)
        try:
            d = service.downloads.start(entry, missing, service.models_dir)
        except Exception as e:  # not enough space, or one download is running: words, no trace
            raise Failed("download_not_started", str(e)) from None
        try:
            while d.status == "running":
                done = d.bytes_done / max(1, d.bytes_total)
                await report(done, f"Downloading {d.current}" if d.current else "Downloading")
                await asyncio.sleep(self._poll)
        except asyncio.CancelledError:
            service.downloads.cancel(d.id)  # the partial file is kept for the next try
            raise
        if d.status != "done":
            raise Failed("download_failed", d.error or "The download did not finish.")
        return {"model_id": model_id, "already": False, "bytes": total, "source": entry.source}

    def _component(self, name: str) -> Any:
        """The component an `admin.fetch_engine` names, as the desktop engine lists it."""
        if name in self._setups:
            return trainer_part(TRAINERS[name], self._setups[name])
        if name != "lipsync-engine":
            raise Failed("unknown_engine", "That is not something this worker can set up.")
        sidecar = self._speech.lipsync_sidecar
        if sidecar is None:
            raise Failed("not_here", "This worker has no lip sync component.")
        return lipsync_part(sidecar)

    async def fetch_engine(self, name: str, report: Report) -> dict[str, Any]:
        """Set a component up through the one installer's components (stage F2), the same ones
        the desktop's Settings lists, following its progress to the end."""
        component = self._component(name)
        status = component.status()
        if status["state"] == "unsupported":
            raise Failed("not_supported", str(status["reason"]))
        try:
            done = await install_and_wait(component, report, self._poll)
        except InstallError as e:
            raise Failed("install_failed", str(e) or "The setup did not finish.") from None
        return {"name": name, "already": done["already"]}
