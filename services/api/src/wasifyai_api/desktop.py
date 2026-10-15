"""The desktop profile of the engine (ADR-0056): the adapters the web profile serves from Postgres,
Redis and S3, served from one SQLite file and a folder on this machine, in one process.

    DesktopBackends     what `create_app` uses in place of Postgres, Redis and object storage
    files_router        `GET /files/{key}`: serves a stored file for a signed link
    main()              the entry point the shell starts: `python -m wasifyai_api.desktop`

The shell passes its needs through the environment (DESKTOP_DATA_DIR, API_AUTH_SECRET,
WASIFYAI_PORT) and reads one line from stdout when the engine is ready. Nothing here is imported
by product code."""

import asyncio
import json
import logging
import mimetypes
import os
import socket
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import LocalFileStorage, RunStore, ScopedStorage
from wasifyai_platform_sdk.sqlite import (
    SqliteEventLog,
    SqliteJobQueue,
    SqliteRunStore,
    SqliteUploadStore,
    SqliteUsageRecorder,
    create_sqlite_engine,
)

from wasifyai_api.config import Settings
from wasifyai_api.creation_index import IndexStore
from wasifyai_api.desktop_discovery import DiscoveryService
from wasifyai_api.desktop_models import ModelsService, load_catalogue
from wasifyai_api.jobs_consumer_local import LocalCompletionConsumer
from wasifyai_api.runs import RunManager
from wasifyai_api.safeguards import SettingsStore
from wasifyai_api.sqlite_stores import SqliteIndexStore, SqliteSettingsStore, SqliteUserStore

log = logging.getLogger("wasifyai_api.desktop")

DB_NAME = "wasifyai.db"
FILES_DIR = "files"
READY_EVENT = "wasifyai.engine.ready"


@dataclass
class DesktopBackends:
    engine: AsyncEngine
    event_log: SqliteEventLog
    run_store: RunStore
    queue: SqliteJobQueue
    usage: SqliteUsageRecorder
    uploads: SqliteUploadStore
    users: SqliteUserStore
    settings_store: SettingsStore
    index_store: IndexStore
    local_files: LocalFileStorage
    storage: ScopedStorage
    settings: Settings
    _worker_task: asyncio.Task | None = None
    _consumer: LocalCompletionConsumer | None = None
    _worker_cleanup: Any = None
    models: ModelsService | None = None
    discovery: DiscoveryService | None = None
    slot: Any = None  # the SlotManager of the running worker (set by start)

    async def start(self, runs: RunManager) -> None:
        """Start the in-process worker and the consumer that resumes graphs from its results."""
        if self.models is not None:
            await self.models.load()  # folders a person chose earlier
        if self.discovery is not None:
            await self.discovery.load()
            self.discovery.start()  # a background scan of the known folders (ADR-0063)
        worker, self._worker_cleanup, self.slot = _build_worker(self)
        self._worker_task = asyncio.create_task(worker.run_forever())
        self._consumer = LocalCompletionConsumer(self.queue, runs, self.run_store)
        await self._consumer.start()
        await self.event_log.prune()  # events older than the retention window

    async def stop(self) -> None:
        if self.discovery is not None:
            await self.discovery.stop()
        if self._consumer:
            await self._consumer.stop()
        if self._worker_task:
            self._worker_task.cancel()
            await asyncio.gather(self._worker_task, return_exceptions=True)
        if self._worker_cleanup:
            await self._worker_cleanup()


def open_desktop(settings: Settings) -> DesktopBackends:
    if not settings.desktop_data_dir:
        raise RuntimeError(
            "DEPLOYMENT_PROFILE=desktop needs DESKTOP_DATA_DIR (the app data folder)"
        )
    if not settings.desktop_public_url:
        raise RuntimeError(
            "DEPLOYMENT_PROFILE=desktop needs DESKTOP_PUBLIC_URL (this engine's URL)"
        )
    root = settings.desktop_dir
    engine = create_sqlite_engine(root / DB_NAME)
    log_ = SqliteEventLog(engine)
    local_files = LocalFileStorage(
        root / FILES_DIR, settings.desktop_public_url, settings.api_auth_secret
    )
    products = Path(settings.products_dir)
    models = ModelsService(
        load_catalogue(products, sorted(settings.enabled_product_set)),
        settings.models_dir,
        settings.extra_model_dirs,
        SqliteSettingsStore(engine),
    )
    return DesktopBackends(
        models=models,
        discovery=DiscoveryService(SqliteSettingsStore(engine), models),
        engine=engine,
        event_log=log_,
        run_store=SqliteRunStore(engine),
        queue=SqliteJobQueue(engine, log_),
        usage=SqliteUsageRecorder(engine),
        uploads=SqliteUploadStore(engine),
        users=SqliteUserStore(engine),
        settings_store=SqliteSettingsStore(engine),
        index_store=SqliteIndexStore(engine),
        local_files=local_files,
        storage=ScopedStorage(local_files),
        settings=settings,
    )


def _build_worker(d: DesktopBackends):
    """The media worker of this process. Imported here, not at the top: the web API image does not
    carry the worker package, and the desktop engine does (`wasifyai-api[desktop]`)."""
    import httpx
    from wasifyai_media_worker.comfy import ComfyClient
    from wasifyai_media_worker.local import LocalWorker
    from wasifyai_media_worker.processor import ComfyRunner, JobProcessor, StubRunner
    from wasifyai_media_worker.settings import WorkerSettings
    from wasifyai_media_worker.sidecar import (
        AutoRunner,
        ComfySidecar,
        SidecarConfig,
        SidecarRunner,
    )
    from wasifyai_media_worker.state import InMemoryJobState
    from wasifyai_platform_sdk import SlotManager

    s = d.settings
    models = d.models
    mode = s.desktop_image_engine  # stub | comfyui | auto | external
    ws = WorkerSettings(
        comfyui_mode="stub" if mode == "stub" else "real",
        comfyui_base_url=s.comfyui_base_url,
        database_url="",
        metrics_port=0,
        ollama_base_url="",
        unload_llm=False,
    )
    http = httpx.AsyncClient(timeout=30)
    sidecar = ComfySidecar(SidecarConfig(s.desktop_dir, s.models_dir, s.extra_model_dirs))
    placeholder = StubRunner()
    real = SidecarRunner(sidecar, ws.job_timeout_s)
    runner: Any
    if mode == "stub":
        runner = placeholder
    elif mode == "comfyui":
        runner = real
    elif mode == "auto":
        runner = AutoRunner(sidecar, real, placeholder)
    elif mode == "external":  # a ComfyUI someone else runs, at COMFYUI_BASE_URL (development)
        client = ComfyClient(ws.comfyui_base_url)
        runner = ComfyRunner(client, ws.job_timeout_s)
    else:
        raise RuntimeError(
            f"DESKTOP_IMAGE_ENGINE must be stub, comfyui, auto or external: {mode!r}"
        )

    # one big model in memory at a time; the image engine unloads through ComfyUI's /free
    slot = SlotManager({"image": sidecar.unload_models}, idle_unload_s=s.desktop_idle_unload_s)
    if models is not None:
        models.sidecar, models.slot = sidecar, slot
    processor = JobProcessor(
        ws,
        d.event_log,
        d.local_files,
        d.usage,
        runner,
        slot.lock_for("image"),
        InMemoryJobState(),
        http,
    )

    async def cleanup() -> None:
        await sidecar.stop()
        await http.aclose()

    return LocalWorker(d.queue, processor), cleanup, slot


# ---- files ----------------------------------------------------------------------------------

files_router = APIRouter(tags=["files"])


@files_router.get("/files/{key:path}")
async def get_file(key: str, e: int, s: str, request: Request) -> Response:
    """A stored file for a link signed by this engine. The signature is the authorisation, the way
    a presigned S3 link is, so an `<img>` can use it."""
    files: LocalFileStorage = request.app.state.local_files
    if not files.verify(key, e, s):
        raise HTTPException(403, "this link is not valid or has expired")
    try:
        data = await files.get(key)
    except FileNotFoundError:
        raise HTTPException(404, "file not found") from None
    ctype = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return Response(
        data,
        media_type=ctype,
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


# ---- entry point ----------------------------------------------------------------------------


def _bind(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))  # loopback only: nothing else on the network can reach it
    return sock


async def _serve() -> None:
    import uvicorn

    sock = _bind(int(os.environ.get("WASIFYAI_PORT", "0")))
    port = sock.getsockname()[1]
    os.environ["DEPLOYMENT_PROFILE"] = "desktop"
    os.environ["DESKTOP_PUBLIC_URL"] = f"http://127.0.0.1:{port}"

    from wasifyai_api.config import get_settings

    get_settings.cache_clear()  # the environment above is what the engine runs with
    from wasifyai_api.main import create_app

    server = uvicorn.Server(
        uvicorn.Config(create_app(), log_level=os.environ.get("LOG_LEVEL", "info").lower())
    )

    async def announce() -> None:
        while not server.started:  # noqa: ASYNC110 - uvicorn offers no event for this
            await asyncio.sleep(0.05)
        line = {"event": READY_EVENT, "port": port, "pid": os.getpid()}
        print(json.dumps(line), flush=True)

    def exit_when_shell_goes(loop: asyncio.AbstractEventLoop) -> None:
        """The shell keeps our stdin open; if it ends, the shell is gone and so are we."""
        sys.stdin.buffer.read()
        loop.call_soon_threadsafe(setattr, server, "should_exit", True)

    tasks = [asyncio.create_task(announce())]
    if os.environ.get("WASIFYAI_EXIT_ON_STDIN_EOF") == "1":
        # a daemon thread: a blocked read must not keep the process alive at shutdown
        threading.Thread(
            target=exit_when_shell_goes, args=(asyncio.get_running_loop(),), daemon=True
        ).start()
    try:
        await server.serve(sockets=[sock])
    finally:
        for t in tasks:
            t.cancel()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
