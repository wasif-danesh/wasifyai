import asyncio
import logging
import os
import shutil
import signal
from pathlib import Path

from redis.asyncio import Redis
from wasifyai_api.config import get_settings
from wasifyai_api.decision_setup import LOCK_NAME as DECISION_LOCK_NAME
from wasifyai_api.decision_setup import DecisionSetup
from wasifyai_api.desktop_decision_training import make_decision_trainer
from wasifyai_api.desktop_language_training import make_language_trainer
from wasifyai_api.desktop_model3d import Model3dService
from wasifyai_api.desktop_models import FolderModels, load_catalogue
from wasifyai_api.desktop_training import make_trainer
from wasifyai_api.desktop_video_builder import VideoBuilderService
from wasifyai_api.desktop_video_training import make_video_trainer
from wasifyai_api.language_setup import LOCK_NAME as LANGUAGE_LOCK_NAME
from wasifyai_api.language_setup import LanguageSetup
from wasifyai_api.local_speech import build_local_engine
from wasifyai_api.training_setup import HUB, TrainingSetup
from wasifyai_api.training_setup import LOCK_NAME as IMAGE_LOCK_NAME
from wasifyai_api.video_setup import LOCK_NAME as VIDEO_LOCK_NAME
from wasifyai_api.video_setup import VideoSetup
from wasifyai_platform_sdk import EngineQueue, admin_wire, memory_storage, s3_storage

from wasifyai_engine_worker.admin import AdminComponent
from wasifyai_engine_worker.settings import WorkerSettings
from wasifyai_engine_worker.train import ModelCache, TrainComponents
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
    # the trainers (ADR-0073, 2026-10-27): the desktop's engine classes on this worker's data folder
    models = FolderModels(
        load_catalogue(
            products,
            sorted(api.enabled_product_set)
            or sorted(p.name for p in products.iterdir() if p.is_dir()),  # noqa: ASYNC240
        ),
        api.models_dir,
        api.extra_model_dirs,
    )
    video_trainer = make_video_trainer(api.desktop_dir, models)
    video_setup = VideoSetup(
        api.desktop_dir,
        lock=products / "wasifyai-training" / "trainer" / VIDEO_LOCK_NAME,
        uv=os.environ.get("WASIFYAI_UV") or shutil.which("uv"),
        base_url=(os.environ.get("HF_ENDPOINT") or HUB).rstrip("/"),
    )
    if video_trainer is not None:
        video_setup.video_model = video_trainer.model_files
    image_setup = TrainingSetup(
        api.desktop_dir,
        lock=products / "wasifyai-training" / "trainer" / IMAGE_LOCK_NAME,
        uv=os.environ.get("WASIFYAI_UV") or shutil.which("uv"),
        base_url=(os.environ.get("HF_ENDPOINT") or HUB).rstrip("/"),
    )
    image_trainer = make_trainer(api.desktop_dir, api.models_dir, image_setup)
    decision_setup = DecisionSetup(
        api.desktop_dir,
        lock=products / "wasifyai-training" / "trainer" / DECISION_LOCK_NAME,
        uv=os.environ.get("WASIFYAI_UV") or shutil.which("uv"),
        base_url=(os.environ.get("HF_ENDPOINT") or HUB).rstrip("/"),
    )
    decision_trainer = make_decision_trainer(api.desktop_dir)
    writing_setup = LanguageSetup(
        api.desktop_dir,
        lock=products / "wasifyai-training" / "trainer" / LANGUAGE_LOCK_NAME,
        uv=os.environ.get("WASIFYAI_UV") or shutil.which("uv"),
        base_url=(os.environ.get("HF_ENDPOINT") or HUB).rstrip("/"),
    )
    writing_trainer = make_language_trainer(api.desktop_dir)
    setups = {
        admin_wire.VIDEO_TRAINER: video_setup,
        admin_wire.IMAGE_TRAINER: image_setup,
        admin_wire.DECISION_TRAINER: decision_setup,
        admin_wire.WRITING_TRAINER: writing_setup,
    }
    worker = Worker(
        EngineQueue(redis),
        {
            "speech": engine,
            "model3d": model3d,
            "builder": builder,
            "train": TrainComponents(
                video=video_trainer,
                image=image_trainer,
                decision=decision_trainer,
                writing=writing_trainer,
                setups=setups,
                cache=ModelCache(api.desktop_dir / "cache" / "train-models"),
            ),
            "admin": AdminComponent(engine, setups=setups),
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
