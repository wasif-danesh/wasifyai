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
import shutil
import socket
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncEngine
from wasifyai_platform_sdk import (
    EnvSecretStore,
    FileSecretStore,
    KeychainSecretStore,
    LayeredSecretStore,
    LocalFileStorage,
    RunStore,
    ScopedStorage,
    SecretBox,
    SecretStore,
)
from wasifyai_platform_sdk.sqlite import (
    SqliteEventLog,
    SqliteJobQueue,
    SqliteRunStore,
    SqliteUploadStore,
    SqliteUsageRecorder,
    create_sqlite_engine,
)

from wasifyai_api.audio_runtime import AudioEngine, AudioInstaller, AudioServer
from wasifyai_api.comfy_music import ComfyMusic
from wasifyai_api.config import Settings
from wasifyai_api.creation_index import IndexStore
from wasifyai_api.decision_setup import LOCK_NAME as DECISION_LOCK_NAME
from wasifyai_api.decision_setup import DecisionSetup
from wasifyai_api.desktop_decision_training import LayaTrainer, make_decision_trainer
from wasifyai_api.desktop_discovery import DiscoveryService
from wasifyai_api.desktop_fit import assess_fit, need_declared, process_rss_bytes
from wasifyai_api.desktop_hub import TOKEN_ALIASES, HubService
from wasifyai_api.desktop_language import LanguageService
from wasifyai_api.desktop_language_training import MlxLmTrainer, make_language_trainer
from wasifyai_api.desktop_model3d import Model3dService
from wasifyai_api.desktop_models import ModelsService, load_catalogue
from wasifyai_api.desktop_training import make_trainer
from wasifyai_api.desktop_video_builder import VideoBuilderService
from wasifyai_api.desktop_video_training import VIDEO_MODEL, LtxTrainer, make_video_trainer
from wasifyai_api.desktop_vision import VisionService
from wasifyai_api.jobs_consumer_local import LocalCompletionConsumer
from wasifyai_api.language_setup import LOCK_NAME as LANGUAGE_LOCK_NAME
from wasifyai_api.language_setup import LanguageSetup
from wasifyai_api.lipsync_runtime import LipSyncSidecar
from wasifyai_api.llama_server import LlamaServer
from wasifyai_api.runs import RunManager
from wasifyai_api.safeguards import SettingsStore
from wasifyai_api.sqlite_stores import SqliteIndexStore, SqliteSettingsStore, SqliteUserStore
from wasifyai_api.training_setup import HUB, LOCK_NAME, TrainingSetup
from wasifyai_api.video_setup import LOCK_NAME as VIDEO_LOCK_NAME
from wasifyai_api.video_setup import VideoSetup
from wasifyai_api.web_search import WebService, load_or_create_key

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
    llama: LlamaServer | None = None
    language: LanguageService | None = None
    vision: VisionService | None = None  # the picture reader of the chosen chat model (ADR-0083)
    hub: HubService | None = None
    web: WebService | None = None  # web search: the person's choices and keys (ADR-0083)
    secrets: SecretStore | None = None  # keys and tokens: the keychain or the file (ADR-0092)
    audio: AudioEngine | None = None
    video_builder: VideoBuilderService | None = (
        None  # the render engine, installed on request (ADR-0077)
    )
    model3d: Model3dService | None = None  # the 3D engine, installed on request (ADR-0080)
    training_setup: TrainingSetup | None = None  # the trainer's component, set up on request
    language_setup: LanguageSetup | None = None  # the writing trainer's component
    writing: MlxLmTrainer | None = None  # the language trainer: mlx-lm on a Mac (ADR-0074)
    decision_setup: DecisionSetup | None = None  # the decision trainer's component
    deciding: LayaTrainer | None = None  # the decision trainer: Laya on a Mac (ADR-0075)
    video_setup: VideoSetup | None = None  # the video trainer's component
    teaching_video: LtxTrainer | None = None  # the video trainer: diffusers on a Mac (ADR-0073)
    training: Any = None  # the trainer: a preview until the real one is installed (ADR-0073)
    slot: Any = None  # the SlotManager of the running worker (set by start)

    async def start(self, runs: RunManager) -> None:
        """Start the in-process worker and the consumer that resumes graphs from its results."""
        if self.models is not None:
            await self.models.load()  # folders a person chose earlier
        if self.hub is not None:
            await self.hub.load()  # whether the person agreed to browse
        if self.language is not None:
            await self.language.load()  # the model chosen earlier, if any
        if self.discovery is not None:
            await self.discovery.load()
            self.discovery.start()  # a background scan of the known folders (ADR-0063)
        if self.training is not None and self.discovery is not None:
            # a model just taught (or removed) is a style the image engine can use: look again
            self.training.on_published = self.discovery.scan
        if self.teaching_video is not None and self.discovery is not None:
            self.teaching_video.on_published = (
                self.discovery.scan
            )  # and a look the video engine can use
        worker, self._worker_cleanup, self.slot = _build_worker(self)
        self._worker_task = asyncio.create_task(worker.run_forever())
        self._consumer = LocalCompletionConsumer(self.queue, runs, self.run_store)
        await self._consumer.start()
        await self.event_log.prune()  # events older than the retention window

    async def stop(self) -> None:
        if self.discovery is not None:
            await self.discovery.stop()
        if self.audio is not None:
            await self.audio.server.close()  # the speech models' memory goes back with the process
            if self.audio.lipsync_sidecar is not None:
                await self.audio.lipsync_sidecar.close()
        if self.llama is not None:
            await self.llama.close()  # the language model's memory goes back with its process
        if self._consumer:
            await self._consumer.stop()
        if self._worker_task:
            self._worker_task.cancel()
            await asyncio.gather(self._worker_task, return_exceptions=True)
        if self._worker_cleanup:
            await self._worker_cleanup()


KEYCHAIN_SERVICE = "Wasify AI"


def make_secret_store(root: Path, settings: Settings, box: SecretBox) -> SecretStore:
    """Where the desktop keeps keys and tokens (ADR-0092): the macOS keychain when the shell asks
    for it (`DESKTOP_SECRET_STORE=keychain`), else one encrypted file under `secrets.key`. The
    environment answers behind either, so a developer's `HF_TOKEN` still counts."""
    env = EnvSecretStore(TOKEN_ALIASES)
    if settings.desktop_secret_store == "keychain" and KeychainSecretStore.available():
        return LayeredSecretStore(
            KeychainSecretStore(KEYCHAIN_SERVICE, root / "secrets.names.json"), env
        )
    return LayeredSecretStore(FileSecretStore(root / "secrets.json", box), env)


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
    llama = LlamaServer(settings.desktop_dir)
    models.llama = llama
    audio = AudioEngine(
        settings.desktop_dir,
        models,
        AudioInstaller(settings.desktop_dir),
        AudioServer(settings.desktop_dir),
        ComfyMusic(products / "wasifyai-voice" / "workflows", lambda: models.sidecar),
        LipSyncSidecar(settings.desktop_dir),
    )
    models.audio = audio
    discovery = DiscoveryService(SqliteSettingsStore(engine), models)
    language = LanguageService(SqliteSettingsStore(engine), llama, models, discovery)
    discovery.language = language
    vision = VisionService(language, models)
    box = SecretBox(load_or_create_key(root / "secrets.key"))
    secrets = make_secret_store(root, settings, box)
    hub = HubService(SqliteSettingsStore(engine), secrets=secrets)
    hub.models, hub.language = models, language
    web = WebService(SqliteSettingsStore(engine), secrets, legacy_box=box)
    cache = root / "engine" / "cache"
    setup = TrainingSetup(
        root,
        lock=products / "wasifyai-training" / "trainer" / LOCK_NAME,
        uv=os.environ.get("WASIFYAI_UV") or shutil.which("uv"),
        cache_dir=cache if cache.is_dir() else None,
        base_url=(os.environ.get("HF_ENDPOINT") or HUB).rstrip("/"),
    )
    language_setup = LanguageSetup(
        root,
        lock=products / "wasifyai-training" / "trainer" / LANGUAGE_LOCK_NAME,
        uv=os.environ.get("WASIFYAI_UV") or shutil.which("uv"),
        cache_dir=cache if cache.is_dir() else None,
        base_url=(os.environ.get("HF_ENDPOINT") or HUB).rstrip("/"),
    )
    decision_setup = DecisionSetup(
        root,
        lock=products / "wasifyai-training" / "trainer" / DECISION_LOCK_NAME,
        uv=os.environ.get("WASIFYAI_UV") or shutil.which("uv"),
        cache_dir=cache if cache.is_dir() else None,
        base_url=(os.environ.get("HF_ENDPOINT") or HUB).rstrip("/"),
    )
    video_setup = VideoSetup(
        root,
        lock=products / "wasifyai-training" / "trainer" / VIDEO_LOCK_NAME,
        uv=os.environ.get("WASIFYAI_UV") or shutil.which("uv"),
        cache_dir=cache if cache.is_dir() else None,
        base_url=(os.environ.get("HF_ENDPOINT") or HUB).rstrip("/"),
    )
    video_entry = models.catalogue.get(VIDEO_MODEL)
    video_setup.video_model_bytes = video_entry.total_bytes if video_entry is not None else 0
    teaching_video = make_video_trainer(settings.desktop_dir, models)
    if teaching_video is not None:
        video_setup.video_model = teaching_video.model_files
    return DesktopBackends(
        web=web,
        secrets=secrets,
        models=models,
        discovery=discovery,
        llama=llama,
        audio=audio,
        video_builder=VideoBuilderService(settings.desktop_dir),
        model3d=Model3dService(settings.desktop_dir),
        training_setup=setup,
        training=make_trainer(settings.desktop_dir, settings.models_dir, setup),
        language_setup=language_setup,
        writing=make_language_trainer(settings.desktop_dir),
        decision_setup=decision_setup,
        deciding=make_decision_trainer(settings.desktop_dir),
        video_setup=video_setup,
        teaching_video=teaching_video,
        language=language,
        vision=vision,
        hub=hub,
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


class FitGuardRunner:
    """Refuses a real image or video job when its model cannot fit this computer, before anything
    is loaded: the person gets the reason in plain words instead of a stalled or crashed engine. The
    placeholder engine is never blocked, and `tight` is allowed (the window asked first)."""

    local_gpu = True

    def __init__(self, inner: Any, sidecar: Any, models: Any, error: type[Exception]):
        self._inner, self._sidecar, self._models, self._error = inner, sidecar, models, error

    @property
    def backend(self) -> str:
        return self._inner.backend

    async def run(self, job: Any, on_progress: Any, files: Any = None) -> Any:
        if self._sidecar.installed:
            reason = await self._too_big(job)
            if reason:
                raise self._error("model_too_big", reason)  # type: ignore[call-arg]
        if files:
            return await self._inner.run(job, on_progress, files=files)
        return await self._inner.run(job, on_progress)

    async def _too_big(self, job: Any) -> str | None:
        machine = await self._models.machine()
        # a video job is judged by the video models, an image job by the image models
        product = (
            "wasifyai-video"
            if str(getattr(job, "capability", "")).startswith("video.")
            else "wasifyai-image"
        )
        for entry in self._models.catalogue.values():
            if entry.approx_ram_gb and entry.product_id == product:
                fit = assess_fit(need_declared(entry.approx_ram_gb), machine)
                if fit.verdict == "too_big":
                    return f"{entry.title} will not fit on this computer. {fit.reason}"
        return None


def _build_worker(d: DesktopBackends):
    """The media worker of this process. Imported here, not at the top: the web API image does not
    carry the worker package, and the desktop engine does (`wasifyai-api[desktop]`)."""
    import httpx
    from wasifyai_media_worker.comfy import ComfyClient, ComfyError
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
        # on this computer a long clip may take most of an hour; the person can stop it (the web
        # keeps the shorter limit of a shared GPU)
        job_timeout_s=3600,
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

    if mode != "stub" and models is not None:
        runner = FitGuardRunner(runner, sidecar, models, ComfyError)

    # one big model in memory at a time; the image engine unloads through ComfyUI's /free
    owners: dict[str, Any] = {"image": sidecar.unload_models}
    if d.llama is not None:
        llama = d.llama

        async def unload_chat() -> None:
            await llama.stop()

        owners["chat"] = unload_chat
    if d.model3d is not None:
        owners["model3d"] = d.model3d.stop  # a 3D run holds about 19 GB: the biggest owner
    if d.training is not None:
        owners["training"] = d.training.stop  # a training run holds most of the GPU
    if d.writing is not None:
        owners["writing"] = d.writing.stop  # so does teaching a writing model
    if d.deciding is not None:
        owners["deciding"] = d.deciding.stop  # and teaching it to decide
    if d.teaching_video is not None:
        owners["teaching_video"] = d.teaching_video.stop  # and teaching the video model
    if d.audio is not None:
        owners["audio"] = d.audio.stop  # the speech runtime is another owner of the one slot
        if d.audio.lipsync_sidecar is not None:
            owners["lipsync"] = d.audio.lipsync_sidecar.stop

    async def can_share(small: str, need: int, resident: str) -> bool:
        """A speech model may stay in memory beside the chat model when the two fit (ADR-0083,
        decision 5). Only that pair was measured (docs/spikes/composer-co0.md, section 4)."""
        if (small, resident) != ("audio", "chat") or models is None or d.llama is None:
            return False
        held = await asyncio.to_thread(process_rss_bytes, d.llama.pid)
        return await models.fits_beside(need, held)

    slot = SlotManager(owners, idle_unload_s=s.desktop_idle_unload_s, can_share=can_share)
    if models is not None:
        models.attach(sidecar, slot)
    if d.language is not None:
        d.language.slot = slot
    if d.audio is not None:
        d.audio.slot = slot
    if d.model3d is not None:
        d.model3d.slot = slot
    if d.training is not None:
        d.training.slot = slot
    if d.writing is not None:
        d.writing.slot = slot
    if d.deciding is not None:
        d.deciding.slot = slot
    if d.teaching_video is not None:
        d.teaching_video.slot = slot
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
