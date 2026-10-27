"""What an admin can ask a worker to do to itself (ADR-0087, P5): fetch a model's files and set up
the lip sync engine. The same code serves `models_cli` (the command line) and the `admin.*` jobs
the web's Workers page starts. A fetch reports how far it is and continues a partial file."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from wasifyai_engine_worker.handlers import Failed

Report = Callable[[float, str], Awaitable[None]]
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

    async def _setup(self, name: str, setup: Any, report: Report) -> dict[str, Any]:
        """A trainer's component: the same plan, consent size and progress as the desktop's card."""
        if setup.problem() and not setup.supported:
            raise Failed("not_supported", setup.problem())
        if setup.state()["installed"]:
            return {"name": name, "already": True}
        try:
            setup.start(setup.missing_bytes())
        except Exception as e:
            raise Failed("install_not_started", str(e)) from None
        while setup.running:
            p = setup.progress
            total = getattr(p, "total_bytes", 0) or 1
            await report(min(1.0, getattr(p, "done_bytes", 0) / total), p.message or "")
            await asyncio.sleep(self._poll)
        if setup.progress.state != "ready":
            raise Failed("install_failed", setup.progress.message or "The setup did not finish.")
        return {"name": name, "already": False}

    async def fetch_engine(self, name: str, report: Report) -> dict[str, Any]:
        if name in self._setups:
            return await self._setup(name, self._setups[name], report)
        if name != "lipsync-engine":
            raise Failed("unknown_engine", "That is not something this worker can set up.")
        sidecar = self._speech.lipsync_sidecar
        if sidecar is None:
            raise Failed("not_here", "This worker has no lip sync component.")
        if sidecar.installed:
            return {"name": name, "already": True}
        installer = sidecar.installer
        plan = installer.plan()
        if not plan["supported"]:
            raise Failed("not_supported", "There is no lip sync engine for this kind of computer.")
        try:
            installer.start(plan["bytes"])
        except Exception as e:
            raise Failed("install_not_started", str(e)) from None
        while installer.running:
            p = installer.progress
            total = getattr(p, "total_bytes", 0) or plan["bytes"]
            await report(min(1.0, getattr(p, "done_bytes", 0) / max(1, total)), p.message or "")
            await asyncio.sleep(self._poll)
        if installer.progress.state != "ready":
            raise Failed(
                "install_failed", installer.progress.message or "The setup did not finish."
            )
        return {"name": name, "already": False}
