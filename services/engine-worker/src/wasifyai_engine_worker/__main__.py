import asyncio
import logging
import signal
from pathlib import Path

from redis.asyncio import Redis
from wasifyai_api.config import get_settings
from wasifyai_api.desktop_model3d import Model3dService
from wasifyai_api.desktop_video_builder import VideoBuilderService
from wasifyai_api.local_speech import build_local_engine
from wasifyai_platform_sdk import EngineQueue, memory_storage, s3_storage

from wasifyai_engine_worker.admin import AdminComponent
from wasifyai_engine_worker.settings import WorkerSettings
from wasifyai_engine_worker.worker import Worker

# redis-py defaults to 5 s; blocking queue reads must not hit that
REDIS_SOCKET_TIMEOUT_S = 60


async def main() -> None:
    s = WorkerSettings()
    logging.basicConfig(level=s.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log = logging.getLogger("wasifyai_engine_worker")

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
        log.warning("STORAGE_ACCESS_KEY is unset: files go to memory and the API cannot read them")
        storage = memory_storage()

    api = get_settings()
    products = Path(api.products_dir)
    engine = build_local_engine(api, products)
    model3d = Model3dService(api.desktop_dir)
    builder = VideoBuilderService(api.desktop_dir)
    worker = Worker(
        EngineQueue(redis),
        {
            "speech": engine,
            "model3d": model3d,
            "builder": builder,
            "admin": AdminComponent(engine),
        },
        storage,
        s.name,
        s.job_timeout_s,
        s.heartbeat_s,
    )
    ready = [m["id"] for m in engine.models(None) if m["state"] == "ready"]
    log.info("worker %s: data in %s, ready models: %s", s.name, api.desktop_dir, ready or "none")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop.set)
    try:
        await worker.run()
    finally:
        await engine.stop()
        await model3d.stop()
        if engine.lipsync_sidecar is not None:  # its server is a process of its own
            await engine.lipsync_sidecar.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
