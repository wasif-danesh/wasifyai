# SPDX-License-Identifier: Apache-2.0
"""The program that reads sources on the web: `python -m wasifyai_notebooks.worker`.

The engine's own program only serves requests. A source a person adds waits in the database
(`documents.status = 'pending'`, which is the queue); this program takes the next one, fetches its
file from object storage, reads it (the document reader runs as a program of its own), cuts,
embeds and indexes it, and writes the result. Any number can run: a source is taken by one of them
(`begin` is one atomic update), and one that a reader lost is failed after `STALE_AFTER_S` so that
Retry offers it. It needs the same settings as the engine (the database and the object storage)
and, on its own machine, the search model and the reader:

    DATABASE_URL, STORAGE_ENDPOINT, STORAGE_BUCKET, STORAGE_ACCESS_KEY, STORAGE_SECRET_KEY
    NOTEBOOKS_READER_DIR     the document reader's environment (`venv/`, `models/`, ...)
    NOTEBOOKS_SCHEMA         the database schema (default `notebooks`)
    LITELLM_BASE_URL, LITELLM_API_KEY      the gateway that serves the search model
    NOTEBOOKS_EMBED_MODEL    its alias (default `creation-embedder`); NOTEBOOKS_EMBED_DIMENSION
    PRODUCTS_DIR, PRODUCT_ENV  the product configuration (`product.yaml`: which model writes)

With a gateway the worker also makes the Studio outputs the engine queued. With no gateway the
search model is read from `NOTEBOOKS_MODELS_DIR` (the folder holding `embeddings/`) instead.
"""

import asyncio
import logging
import os
import signal
import tempfile
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import s3_storage

from wasifyai_notebooks.embedding import GATEWAY_ALIAS
from wasifyai_notebooks.output_job import OutputWorker
from wasifyai_notebooks.runtime import WebSetup

log = logging.getLogger("wasifyai_notebooks.worker")
PRODUCT_ID = "wasifyai-notebooks"


def setup_from_environment(env: dict[str, str] | None = None) -> WebSetup:
    env = dict(os.environ if env is None else env)

    def need(name: str) -> str:
        if not env.get(name):
            raise SystemExit(f"{name} is not set")
        return env[name]

    models = env.get("NOTEBOOKS_MODELS_DIR", "")
    if not models and not env.get("LITELLM_BASE_URL"):
        raise SystemExit("set LITELLM_BASE_URL (the gateway) or NOTEBOOKS_MODELS_DIR (model files)")
    storage = s3_storage(
        bucket=env.get("STORAGE_BUCKET", "wasifyai"),
        endpoint=need("STORAGE_ENDPOINT"),
        access_key=need("STORAGE_ACCESS_KEY"),
        secret_key=need("STORAGE_SECRET_KEY"),
        region=env.get("STORAGE_REGION", "us-east-1"),
    )
    return WebSetup(
        dsn=need("DATABASE_URL"),
        storage=storage,
        models_dir=Path(models),
        reader_dir=Path(need("NOTEBOOKS_READER_DIR")),
        tmp_dir=Path(env.get("NOTEBOOKS_TMP_DIR") or tempfile.gettempdir()) / "notebooks-worker",
        schema=env.get("NOTEBOOKS_SCHEMA", "notebooks"),
        gateway_url=env.get("LITELLM_BASE_URL", ""),
        gateway_key=env.get("LITELLM_API_KEY", ""),
        embed_model=env.get("NOTEBOOKS_EMBED_MODEL", GATEWAY_ALIAS),
        embed_dimension=int(env.get("NOTEBOOKS_EMBED_DIMENSION", "1024")),
    )


def capabilities_for(setup: WebSetup, env: dict[str, str] | None = None) -> Any:
    """What a Studio output needs: the chat model through the gateway, by the product's own
    bindings (`product.yaml`), with the usage it spends noted for the person."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from wasifyai_platform_sdk import ProviderDeps, build_capabilities, load_product_config
    from wasifyai_platform_sdk.usage_postgres import PostgresUsageRecorder

    env = dict(os.environ if env is None else env)
    products = Path(env.get("PRODUCTS_DIR", "products"))
    config = load_product_config(products, PRODUCT_ID, env=env.get("PRODUCT_ENV", ""))
    dsn = setup.dsn
    if "+" not in dsn.split("://", 1)[0]:
        dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(dsn)
    deps = ProviderDeps(
        products_dir=products,
        usage=PostgresUsageRecorder(engine),
        litellm_base_url=setup.gateway_url,
        litellm_api_key=setup.gateway_key,
        db=engine,
    )
    return build_capabilities(config, deps)


async def run(setup: WebSetup) -> None:
    runtime = await asyncio.to_thread(setup.build, reads_sources=True)
    outputs = OutputWorker(runtime, capabilities_for(setup)) if setup.gateway_url else None
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    runtime.worker.start()
    if outputs is not None:
        outputs.start()
    log.info("reading sources%s", " and making outputs" if outputs else "")
    try:
        await stop.wait()
    finally:
        if outputs is not None:
            await outputs.stop()
        await runtime.worker.stop()
        close = getattr(runtime.store, "close", None)
        if close is not None:
            close()


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    asyncio.run(run(setup_from_environment()))


if __name__ == "__main__":
    main()
