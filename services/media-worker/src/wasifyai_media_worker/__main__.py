import asyncio
import logging
import os
import signal
from pathlib import Path

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine
from wasifyai_platform_sdk import (
    InMemoryUsageRecorder,
    PostgresMediaBindingStore,
    PostgresUsageRecorder,
    RedisEventLog,
    SecretBox,
    UsageRecorder,
    memory_storage,
    s3_storage,
)
from wasifyai_platform_sdk.jobqueue import RedisCancels

from wasifyai_media_worker.backends import BackendRouter
from wasifyai_media_worker.comfy import ComfyClient
from wasifyai_media_worker.consumer import Worker
from wasifyai_media_worker.gpu import RedisGpuLock
from wasifyai_media_worker.metrics import WORKER_UP, serve, watch_queue
from wasifyai_media_worker.processor import ComfyRunner, JobProcessor, StubRunner
from wasifyai_media_worker.settings import WorkerSettings
from wasifyai_media_worker.sidecar import ComfySidecar, SidecarConfig, SidecarRunner
from wasifyai_media_worker.state import RedisJobState


def build_sidecar(s: WorkerSettings) -> ComfySidecar:
    """The desktop app's ComfyUI, run by this worker (`COMFYUI_MODE=sidecar`)."""
    if not s.desktop_data_dir:
        raise SystemExit(
            "COMFYUI_MODE=sidecar needs DESKTOP_DATA_DIR (the desktop app's data folder)"
        )
    data = Path(s.desktop_data_dir).expanduser()
    models = Path(s.desktop_models_dir).expanduser() if s.desktop_models_dir else data / "models"
    extra = tuple(
        Path(p).expanduser() for p in s.desktop_extra_model_dirs.split(os.pathsep) if p.strip()
    )
    return ComfySidecar(SidecarConfig(data, models, extra))


# redis-py defaults to 5 s; blocking queue reads must not hit that.
REDIS_SOCKET_TIMEOUT_S = 60


async def main() -> None:
    s = WorkerSettings()
    logging.basicConfig(level=s.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log = logging.getLogger("wasifyai_media_worker")

    redis = Redis.from_url(
        s.redis_url, decode_responses=True, socket_timeout=REDIS_SOCKET_TIMEOUT_S
    )
    if s.storage_access_key:
        storage = s3_storage(
            bucket=s.storage_bucket,
            endpoint=s.storage_endpoint,
            access_key=s.storage_access_key,
            secret_key=s.storage_secret_key,
            region=s.storage_region,
        )
    else:
        log.warning("STORAGE_ACCESS_KEY is unset: outputs go to memory and are lost")
        storage = memory_storage()

    engine = create_async_engine(s.database_url) if s.database_url else None
    usage: UsageRecorder = PostgresUsageRecorder(engine) if engine else InMemoryUsageRecorder()
    if engine is None:
        log.warning("DATABASE_URL is unset: usage events are not persisted")

    comfy = ComfyClient(s.comfyui_base_url)
    sidecar = None
    if s.comfyui_mode == "stub":
        log.warning("COMFYUI_MODE=stub: producing placeholder files, no GPU work")
        runner = StubRunner()
    elif s.comfyui_mode == "sidecar":
        sidecar = build_sidecar(s)
        runner = SidecarRunner(sidecar, s.job_timeout_s)
        log.info(
            "COMFYUI_MODE=sidecar: ComfyUI from %s, models in %s",
            s.desktop_data_dir,
            sidecar.model_roots(),
        )
    else:
        runner = ComfyRunner(comfy, s.job_timeout_s)

    http = httpx.AsyncClient(timeout=30)
    # The admin chooses the backend per product capability (ADR-0025); `runner` is the default.
    router = BackendRouter(
        runner,
        s,
        PostgresMediaBindingStore(engine) if engine else None,
        SecretBox(s.media_secrets_key),
        http,
    )
    processor = JobProcessor(
        s,
        RedisEventLog(redis),
        storage,
        usage,
        router,
        RedisGpuLock(redis, s.gpu_id),
        RedisJobState(redis),
        http,
        cancels=RedisCancels(redis),  # a job the person stopped is not run, or stops (stage J3)
    )
    worker = Worker(redis, processor)

    serve(s.metrics_port)
    WORKER_UP.set(1)
    queue_task = asyncio.create_task(watch_queue(redis))
    task = asyncio.create_task(worker.run_forever())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        log.info("worker stopping")
    finally:
        WORKER_UP.set(0)
        queue_task.cancel()
        if sidecar is not None:  # ComfyUI is this worker's own process
            await sidecar.stop()
        await comfy.aclose()
        await router.aclose()
        await http.aclose()
        await redis.aclose()
        if engine:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
