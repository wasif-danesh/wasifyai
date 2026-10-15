import asyncio
import logging
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import TypeAdapter
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from wasifyai_contracts import SseEvent
from wasifyai_platform_sdk import (
    CapabilityBinding,
    EventLog,
    GraphRegistry,
    InMemoryJobSink,
    InMemoryMediaBindingStore,
    InMemoryUploadLimiter,
    InMemoryUploadStore,
    JobSink,
    PostgresMediaBindingStore,
    PostgresUploadStore,
    PostgresUsageRecorder,
    ProviderDeps,
    RedisEventLog,
    RedisJobSink,
    RedisRunStore,
    RedisUploadLimiter,
    RouteDeps,
    RunStore,
    ScopedStorage,
    SecretBox,
    UploadLimiter,
    UploadStore,
    UsageRecorder,
    build_capabilities,
    load_product_config,
    s3_storage,
)
from wasifyai_platform_sdk.providers.litellm import LiteLLMTextProvider

from wasifyai_api.admin import AdminStore, PostgresAdminStore
from wasifyai_api.admin import me_router as me_router
from wasifyai_api.admin import router as admin_router
from wasifyai_api.admin_media import router as admin_media_router
from wasifyai_api.admin_models import router as admin_models_router
from wasifyai_api.admin_safeguards import router as admin_safeguards_router
from wasifyai_api.auth import MIN_SECRET_BYTES
from wasifyai_api.config import get_settings
from wasifyai_api.creation_index import (
    ContextIndexer,
    CreationIndex,
    Embedder,
    IndexStore,
    InMemoryIndexStore,
    PostgresIndexStore,
    reconcile_forever,
)
from wasifyai_api.creations import router as creations_router
from wasifyai_api.desktop import files_router, open_desktop
from wasifyai_api.desktop_discovery import router as desktop_discovery_router
from wasifyai_api.desktop_language import LocalTextProvider
from wasifyai_api.desktop_llm import router as desktop_llm_router
from wasifyai_api.desktop_models import router as desktop_models_router
from wasifyai_api.graphs import default_registry
from wasifyai_api.identity import get_identity
from wasifyai_api.jobs_consumer import JobCompletionConsumer
from wasifyai_api.litellm_admin import BackendError, InMemoryModelBackend, LiteLLMBackend
from wasifyai_api.local_embedder import MODEL as LOCAL_EMBEDDER_MODEL
from wasifyai_api.local_embedder import hashing_embed
from wasifyai_api.logging import configure_logging, request_id
from wasifyai_api.media_access import MediaAccess, media_capabilities_from
from wasifyai_api.metrics import MetricsMiddleware
from wasifyai_api.metrics import serve as serve_metrics
from wasifyai_api.model_access import ModelAccess, load_defaults
from wasifyai_api.model_checks import RegistryCheckRunner
from wasifyai_api.rag import DIMENSIONS, RagService
from wasifyai_api.routes import HEARTBEAT_S, router
from wasifyai_api.runs import RunManager
from wasifyai_api.safeguards import (
    KEY,
    InMemorySettingsStore,
    PostgresSettingsStore,
    Safeguards,
)
from wasifyai_api.uploads import router as uploads_router
from wasifyai_api.uploads import sweep_forever
from wasifyai_api.users import CachedUsers, PostgresUserStore, UserStore

# redis-py defaults to 5 s; stream reads block for the heartbeat interval, so allow well over it.
REDIS_SOCKET_TIMEOUT_S = 60
ENHANCES_PER_HOUR = 40  # prompt enhancements per user per hour (ADR-0038)
SEARCHES_PER_HOUR = 50  # searches of My creations per user per hour (ADR-0041)
SEARCH_ALIAS = "creation-embedder"  # the multilingual embedder behind search (ADR-0041)


async def _seed_models(models: ModelAccess) -> None:
    """Give LiteLLM its default aliases; it may still be starting, so keep trying for a while."""
    log = logging.getLogger("wasifyai_api")
    for attempt in range(1, 151):
        try:
            await models.seed()
            return
        except BackendError as exc:
            if attempt in (1, 30, 90):
                log.warning("model gateway not ready for seeding (attempt %d): %s", attempt, exc)
            await asyncio.sleep(2)
    log.error("could not seed the default model aliases; check LiteLLM and LITELLM_API_KEY")


def create_app(
    registry: GraphRegistry | None = None,
    products_dir: Path | None = None,
    checkpointer: Any = None,
    usage: UsageRecorder | None = None,
    storage: ScopedStorage | None = None,
    engine: AsyncEngine | None = None,
    heartbeat_s: float = HEARTBEAT_S,
    event_log: EventLog | None = None,
    run_store: RunStore | None = None,
    job_sink: JobSink | None = None,
    redis: Redis | None = None,
    users: UserStore | None = None,
    admin_store: AdminStore | None = None,
    model_access: ModelAccess | None = None,
    media_access: MediaAccess | None = None,
    uploads: UploadStore | None = None,
    upload_limiter: UploadLimiter | None = None,
    enhance_limiter: UploadLimiter | None = None,
    search_limiter: UploadLimiter | None = None,
    creation_embedder: Embedder | None = None,
    index_store: IndexStore | None = None,
    safeguards: Safeguards | None = None,
) -> FastAPI:
    """App factory. Tests inject a registry, products dir (with `provider: fake` bindings),
    checkpointer, usage recorder, event log, run store and job sink, so no GPU, network, database
    or Redis is needed. Without injected log/store the app uses Redis (production). Passing `redis`
    also starts the completion consumer that resumes graphs paused on media jobs."""
    settings = get_settings()
    configure_logging(settings.log_level)
    desktop_profile = settings.deployment_profile == "desktop"
    if desktop_profile and settings.auth_mode != "jwt":
        raise RuntimeError("the desktop profile signs in with the shell's token: AUTH_MODE=jwt")
    if settings.auth_mode not in ("jwt", "stub"):
        raise RuntimeError(f"AUTH_MODE must be 'jwt' or 'stub', not {settings.auth_mode!r}")
    if settings.auth_mode == "jwt" and len(settings.api_auth_secret.encode()) < MIN_SECRET_BYTES:
        raise RuntimeError(
            "AUTH_MODE=jwt needs API_AUTH_SECRET (at least 32 bytes, the same value as the web "
            "app). For local work without sign-in set AUTH_MODE=stub."
        )
    if settings.auth_mode == "stub":
        logging.getLogger("wasifyai_api").warning("AUTH_MODE=stub: every request is the dev user")
    products_registry = registry or default_registry()
    injected_for_metrics = event_log is not None or run_store is not None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not injected_for_metrics:  # a test app must not open a port
            serve_metrics(settings.metrics_port)
        reg = products_registry
        pdir = products_dir or Path(settings.products_dir)
        injected = event_log is not None or run_store is not None
        # The desktop profile (ADR-0056) serves the same interfaces from SQLite and local files.
        desktop = open_desktop(settings) if desktop_profile and not injected else None
        db = engine or (desktop.engine if desktop else create_async_engine(settings.database_url))
        recorder = usage or (desktop.usage if desktop else PostgresUsageRecorder(db))
        owns_conn = redis is None and not injected and desktop is None
        conn: Redis | None = redis or (
            Redis.from_url(
                settings.redis_url, decode_responses=True, socket_timeout=REDIS_SOCKET_TIMEOUT_S
            )
            if owns_conn
            else None
        )
        log_ = event_log or (desktop.event_log if desktop else RedisEventLog(conn))  # type: ignore[arg-type]
        store_ = run_store or (desktop.run_store if desktop else RedisRunStore(conn))  # type: ignore[arg-type]
        sink = job_sink or (
            desktop.queue if desktop else (RedisJobSink(conn, log_) if conn else InMemoryJobSink())
        )
        store = storage or (desktop.storage if desktop else None)
        if store is None and settings.storage_access_key:
            store = ScopedStorage(
                s3_storage(
                    bucket=settings.storage_bucket,
                    endpoint=settings.storage_endpoint,
                    access_key=settings.storage_access_key,
                    secret_key=settings.storage_secret_key,
                    region=settings.storage_region,
                    public_endpoint=settings.storage_public_endpoint,
                )
            )
        # ADR-0047: off by default, forced on by SAFEGUARDS_FORCE_ON. Tests start with it on.
        guard = safeguards or Safeguards(
            InMemorySettingsStore({KEY: True})
            if injected
            else (desktop.settings_store if desktop else PostgresSettingsStore(db)),
            settings.safeguards_force_on,
        )
        app.state.safeguards = guard
        deps = ProviderDeps(
            safeguards=guard.enabled,
            products_dir=pdir,
            usage=recorder,
            job_sink=sink,
            litellm_base_url=settings.litellm_base_url,
            litellm_api_key=settings.litellm_api_key,
            text_provider=(
                LocalTextProvider(desktop.language, recorder)
                if desktop is not None and desktop.language is not None
                else None
            ),
            storage=store,
            db=db,
            embedding_dims=DIMENSIONS,
        )

        models = model_access
        if models is None:
            base = settings.ollama_base_url.rstrip("/")
            defaults = load_defaults(
                {"OLLAMA_BASE_URL": base, "OLLAMA_OPENAI_BASE_URL": f"{base}/v1"}
            )
            if injected or desktop:  # tests, desktop: no gateway to seed
                models = ModelAccess(InMemoryModelBackend(), defaults)
            else:
                models = ModelAccess(
                    LiteLLMBackend(settings.litellm_base_url, settings.litellm_api_key),
                    defaults,
                    RegistryCheckRunner(reg, pdir, deps, settings.product_env),
                )
                seeder = asyncio.create_task(_seed_models(models))
        app.state.models = models
        app.state.media = media_access or MediaAccess(
            InMemoryMediaBindingStore() if injected or desktop else PostgresMediaBindingStore(db),
            SecretBox(settings.media_secrets_key),
            lambda: media_capabilities_from(reg, pdir, settings.product_env),
            settings.comfyui_base_url,
            video_local_url=settings.comfyui_video_base_url,
        )

        configs: dict[str, Any] = {}
        app.state.caps = {}  # product id -> its capabilities, for product routes (prompt enhancing)
        # what each product accepts as an upload (ADR-0035): None for a product that accepts none
        app.state.upload_rules = lambda pid, kind="image": (
            configs[pid].uploads.get(kind) if pid in configs else None
        )

        def build_graphs(saver: Any) -> dict[str, Any]:
            graphs: dict[str, Any] = {}
            for product_id in enabled(reg.products()):
                # Fails at startup, with every problem listed, if the product config is bad.
                config = load_product_config(pdir, product_id, env=settings.product_env)
                configs[product_id] = config
                caps = build_capabilities(config, deps)
                if "text.embed" in config.capabilities:
                    caps.rag = RagService(db, lambda texts, c=caps: c.text.embed("embed", texts))
                caps.indexer = ContextIndexer(app.state.creation_index)
                app.state.caps[product_id] = caps
                graphs[product_id] = reg.build(product_id, caps, saver)
            return graphs

        app.state.users = users or CachedUsers(desktop.users if desktop else PostgresUserStore(db))
        app.state.admin = admin_store or PostgresAdminStore(db)
        seeder: asyncio.Task | None = None
        app.state.registry = reg
        app.state.usage = recorder
        app.state.uploads = uploads or (
            InMemoryUploadStore()
            if injected
            else (desktop.uploads if desktop else PostgresUploadStore(db))
        )
        app.state.upload_limiter = upload_limiter or (
            RedisUploadLimiter(conn) if conn is not None else InMemoryUploadLimiter()
        )
        app.state.enhance_limiter = enhance_limiter or (
            RedisUploadLimiter(conn, per_hour=ENHANCES_PER_HOUR, name="enhance")
            if conn is not None
            else InMemoryUploadLimiter(ENHANCES_PER_HOUR)
        )
        app.state.search_limiter = search_limiter or (
            RedisUploadLimiter(conn, per_hour=SEARCHES_PER_HOUR, name="search")
            if conn is not None
            else InMemoryUploadLimiter(SEARCHES_PER_HOUR)
        )
        search_provider = LiteLLMTextProvider(
            settings.litellm_base_url, settings.litellm_api_key, recorder
        )
        search_binding = CapabilityBinding(provider="litellm", model=SEARCH_ALIAS)

        async def litellm_embed(texts: list[str]) -> list[list[float]]:
            return await search_provider.embed("search.embed", search_binding, texts)

        # A desktop engine without a gateway still indexes, with a small local embedder; its rows
        # are replaced by real embeddings when a gateway is configured (the model name differs).
        local_only = desktop is not None and not settings.litellm_base_url
        embed: Embedder = creation_embedder or (hashing_embed if local_only else litellm_embed)

        app.state.creation_index = CreationIndex(
            index_store
            or (
                InMemoryIndexStore()
                if injected
                else (desktop.index_store if desktop else PostgresIndexStore(db))
            ),
            embed,
            LOCAL_EMBEDDER_MODEL
            if local_only and not creation_embedder
            else settings.search_index_model,
            settings.search_min_similarity,
        )
        index_sources = {
            pid: make
            for pid, make in reg.index_sources().items()
            if pid in enabled(list(reg.products()))
        }
        reconciler = (
            asyncio.create_task(
                reconcile_forever(
                    app.state.creation_index,
                    lambda: [make(db) for make in index_sources.values()],
                    settings.search_reconcile_every_s,
                    settings.search_reconcile_batch,
                )
            )
            if not injected and index_sources
            else None
        )
        sweeper = (
            asyncio.create_task(sweep_forever(app.state.uploads, store))
            if store is not None and not injected
            else None
        )
        app.state.engine = db
        app.state.storage = store
        if desktop:
            app.state.local_files = desktop.local_files
            app.state.desktop_models = desktop.models
            app.state.desktop_discovery = desktop.discovery
            app.state.llama_server = desktop.llama
            app.state.desktop_language = desktop.language
            # "Save" in the window copies a picture here (the product's export route)
            app.state.export_dir = Path(
                os.environ.get("WASIFYAI_EXPORT_DIR") or Path.home() / "Downloads"
            )
        app.state.heartbeat_s = heartbeat_s
        consumer: JobCompletionConsumer | None = None
        try:
            async with AsyncExitStack() as stack:
                saver = checkpointer
                if saver is None and desktop:
                    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

                    saver = await stack.enter_async_context(
                        AsyncSqliteSaver.from_conn_string(
                            str(settings.desktop_dir / "checkpoints.db")
                        )
                    )
                    await saver.setup()
                elif saver is None:
                    saver = await stack.enter_async_context(
                        AsyncPostgresSaver.from_conn_string(settings.checkpoint_url)
                    )
                    await saver.setup()
                graphs = build_graphs(saver)
                app.state.runs = RunManager(log_, store_, graphs)
                if conn is not None:  # resume graphs when workers report results
                    consumer = JobCompletionConsumer(conn, app.state.runs, store_)
                    await consumer.start()
                if desktop:  # the worker runs in this process
                    await desktop.start(app.state.runs)
                yield
        finally:
            # Stop the background tasks and wait for them before the database goes: a task that is
            # cancelled in the middle of a query rolls back through its connection, and a connection
            # that is already closed never answers, which left the task (and the event loop's own
            # shutdown) waiting forever.
            background = [t for t in (seeder, sweeper, reconciler) if t]
            for t in background:
                t.cancel()
            await asyncio.gather(*background, return_exceptions=True)
            if consumer:
                await consumer.stop()
            if desktop:
                await desktop.stop()
            if getattr(app.state, "runs", None):
                await app.state.runs.aclose()
            if owns_conn and conn is not None:
                await conn.aclose()
            if engine is None:
                await db.dispose()

    def enabled(product_ids: list[str]) -> list[str]:
        """The products this deployment serves (all, unless PRODUCTS_ENABLED narrows it)."""
        only = settings.enabled_product_set
        return [p for p in product_ids if not only or p in only]

    app = FastAPI(title="wasifyai API", lifespan=lifespan)
    app.add_middleware(MetricsMiddleware)
    if desktop_profile:
        # The window is another origin (tauri://localhost) than this loopback engine.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                o.strip() for o in settings.desktop_allowed_origins.split(",") if o.strip()
            ],
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["authorization", "content-type", "last-event-id", "x-request-id"],
            expose_headers=["x-request-id"],
        )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id", str(uuid.uuid4()))
        request_id.set(rid)
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)
    app.include_router(me_router)
    app.include_router(admin_router)
    app.include_router(admin_models_router)
    app.include_router(admin_media_router)
    app.include_router(admin_safeguards_router)
    app.include_router(uploads_router)
    app.include_router(creations_router)
    if desktop_profile:
        app.include_router(files_router)
        app.include_router(desktop_models_router)
        app.include_router(desktop_discovery_router)
        app.include_router(desktop_llm_router)

    # Product-provided routes (ADR-0023): mounted now so the OpenAPI schema (and the TypeScript
    # types generated from it) include them; the database and storage they use are read from
    # app.state at request time.
    route_deps = RouteDeps(app.state, get_identity)
    for product_id, factory in products_registry.route_factories().items():
        if product_id in enabled([product_id]):
            app.include_router(factory(route_deps), prefix=f"/products/{product_id}")

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version="0.0.0", routes=app.routes)
        events = TypeAdapter(SseEvent).json_schema(ref_template="#/components/schemas/{model}")
        defs = events.pop("$defs", {})
        schemas = schema.setdefault("components", {}).setdefault("schemas", {})
        schemas.update(defs)
        schemas["SseEvent"] = events
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
    return app


app = create_app()
