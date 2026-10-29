"""How the engine is put together (stage F1 of the 2026-10-27 plan).

`run_engine` builds every store and service into the app's one `ApiServices` when the app starts,
runs the background work, and closes it all when the app stops. What both deployments share is
built in `_shared`; `_web_services` and `_desktop_services` add what only one of them has, so the
differences between the web and the desktop are in two small builders, not in branches through one
function.
Tests hand in what they fake as an `Injected`; anything they do not hand in is built as usual (in
memory where an injected event log or run store says this is a test app).
"""

import asyncio
import logging
import os
import shutil
import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from wasifyai_platform_sdk import (
    CapabilityBinding,
    EngineQueue,
    EnvSecretStore,
    EventLog,
    GraphRegistry,
    InMemoryJobSink,
    InMemoryMediaBindingStore,
    InMemorySecretStore,
    InMemoryUploadLimiter,
    InMemoryUploadStore,
    JobSink,
    LayeredSecretStore,
    PostgresMediaBindingStore,
    PostgresUploadStore,
    PostgresUsageRecorder,
    ProviderDeps,
    RedisEventLog,
    RedisJobSink,
    RedisRunStore,
    RedisUploadLimiter,
    RunStore,
    ScopedStorage,
    SecretBox,
    SecretStore,
    SqlSecretStore,
    ToolUnavailable,
    UploadLimiter,
    UploadStore,
    UsageRecorder,
    build_capabilities,
    load_product_config,
    s3_storage,
    tracing,
)
from wasifyai_platform_sdk.installer import Registry
from wasifyai_platform_sdk.jobpolicy import AdmittedSink, InMemoryLeases, JobPolicy, RedisLeases
from wasifyai_platform_sdk.providers.litellm import LiteLLMTextProvider

from wasifyai_api.actions_engine import build_executor
from wasifyai_api.admin import AdminStore, PostgresAdminStore
from wasifyai_api.auth import Claims
from wasifyai_api.components.comfyui import ComfyUiComponent
from wasifyai_api.components.desktop import service_components
from wasifyai_api.components.llamacpp import LlamaCppComponent
from wasifyai_api.components.manifest import load_manifest
from wasifyai_api.config import Settings, get_settings
from wasifyai_api.creation_index import (
    ContextIndexer,
    CreationIndex,
    Embedder,
    IndexStore,
    InMemoryIndexStore,
    PostgresIndexStore,
    reconcile_forever,
)
from wasifyai_api.desktop import DesktopBackends as Desktop
from wasifyai_api.desktop import open_desktop
from wasifyai_api.desktop_events import EventBus
from wasifyai_api.desktop_language import LocalTextProvider
from wasifyai_api.engine_workers import WorkerDirectory
from wasifyai_api.identity import Identity
from wasifyai_api.jobs_consumer import JobCompletionConsumer
from wasifyai_api.litellm_admin import BackendError, InMemoryModelBackend, LiteLLMBackend
from wasifyai_api.local_embedder import MODEL as LOCAL_EMBEDDER_MODEL
from wasifyai_api.local_embedder import hashing_embed
from wasifyai_api.mcp_client.client import ExternalClient
from wasifyai_api.mcp_client.forms import FormDesk
from wasifyai_api.mcp_client.servers import InMemoryServerStore, ServersService, SqlServerStore
from wasifyai_api.mcp_server.approvals import ApprovalDesk
from wasifyai_api.mcp_server.connections import (
    ConnectionsService,
    InMemoryConnectionStore,
    SqlConnectionStore,
)
from wasifyai_api.mcp_server.endpoint import attach as attach_mcp
from wasifyai_api.mcp_server.endpoint import build_server as build_mcp_server
from wasifyai_api.mcp_server.fixed_port import FixedPort
from wasifyai_api.mcp_server.runtime_file import Launcher, remove_runtime_file
from wasifyai_api.media_access import MediaAccess, media_capabilities_from
from wasifyai_api.model_access import ModelAccess, load_defaults
from wasifyai_api.own_keys_engines import KeyedModel3d, KeyedSpeechEngine
from wasifyai_api.own_keys_text import KeyedTextProvider
from wasifyai_api.rag import DIMENSIONS, RagService
from wasifyai_api.routes import HEARTBEAT_S
from wasifyai_api.run_tracing import Langfuse
from wasifyai_api.runs import RunManager
from wasifyai_api.services import ApiServices
from wasifyai_api.settings_store import InMemorySettingsStore, PostgresSettingsStore
from wasifyai_api.tool_host import ApiToolHost
from wasifyai_api.uploads import sweep_forever
from wasifyai_api.users import CachedUsers, PostgresUserStore, UserStore
from wasifyai_api.web_search import WebService

log = logging.getLogger("wasifyai_api")

# redis-py defaults to 5 s; stream reads block for the heartbeat interval, so allow well over it.
REDIS_SOCKET_TIMEOUT_S = 60
ENHANCES_PER_HOUR = 40  # prompt enhancements per user per hour (ADR-0038)
SEARCHES_PER_HOUR = 50  # searches of My creations per user per hour (ADR-0041)
SEARCH_ALIAS = "creation-embedder"  # the multilingual embedder behind search (ADR-0041)


@dataclass
class Injected:
    """What a test app hands in instead of the real thing. An event log or a run store marks a test
    app: no metrics port, in-memory stores for what is not handed in, no background work."""

    registry: GraphRegistry | None = None
    products_dir: Path | None = None
    checkpointer: Any = None
    usage: UsageRecorder | None = None
    storage: ScopedStorage | None = None
    engine: AsyncEngine | None = None
    heartbeat_s: float = HEARTBEAT_S
    event_log: EventLog | None = None
    run_store: RunStore | None = None
    job_sink: JobSink | None = None
    redis: Redis | None = None
    users: UserStore | None = None
    admin_store: AdminStore | None = None
    model_access: ModelAccess | None = None
    media_access: MediaAccess | None = None
    uploads: UploadStore | None = None
    upload_limiter: UploadLimiter | None = None
    enhance_limiter: UploadLimiter | None = None
    search_limiter: UploadLimiter | None = None
    creation_embedder: Embedder | None = None
    index_store: IndexStore | None = None

    @property
    def test_app(self) -> bool:
        return self.event_log is not None or self.run_store is not None


@dataclass
class _Running:
    """What the engine started and must stop, beside the services."""

    db: AsyncEngine
    conn: Redis | None
    owns_conn: bool
    log: EventLog
    run_store: RunStore
    sink: Any
    deps: ProviderDeps
    desktop: bool
    tool_host: Any = None
    configs: dict[str, Any] = field(default_factory=dict)
    background: list[asyncio.Task[Any]] = field(default_factory=list)


async def _seed_models(models: ModelAccess) -> None:
    """Give LiteLLM its default aliases; it may still be starting, so keep trying for a while."""
    for attempt in range(1, 151):
        try:
            await models.seed()
            return
        except BackendError as exc:
            if attempt in (1, 30, 90):
                log.warning("model gateway not ready for seeding (attempt %d): %s", attempt, exc)
            await asyncio.sleep(2)
    log.error("could not seed the default model aliases; check LiteLLM and LITELLM_API_KEY")


@asynccontextmanager
async def run_engine(
    s: ApiServices,
    given: Injected,
    enabled: Callable[[list[str]], list[str]],
) -> AsyncIterator[None]:
    """Build the services into `s`, run the engine while the app runs, then close everything."""
    settings = get_settings()
    reg = given.registry
    assert reg is not None
    desktop = (
        open_desktop(settings)
        if settings.deployment_profile == "desktop" and not given.test_app
        else None
    )
    r = await _shared(s, given, settings, desktop, enabled)
    if desktop is None:
        await _web_services(s, settings, r, given)
    else:
        _desktop_services(s, desktop)
        if desktop.own_keys is not None:  # where voice and 3D run, known before the first ask
            await desktop.own_keys.warm()
    consumer: JobCompletionConsumer | None = None
    try:
        async with AsyncExitStack() as stack:
            saver = given.checkpointer
            if saver is None and desktop:
                from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

                saver = await stack.enter_async_context(
                    AsyncSqliteSaver.from_conn_string(str(settings.desktop_dir / "checkpoints.db"))
                )
                await saver.setup()
            elif saver is None:
                saver = await stack.enter_async_context(
                    AsyncPostgresSaver.from_conn_string(settings.checkpoint_url)
                )
                await saver.setup()
            s.runs = RunManager(r.log, r.run_store, _build_graphs(s, settings, r, saver, enabled))
            s.runs.job_policy = s.job_policy  # a stopped run frees its job's place
            s.runs.media_cancel = getattr(r.sink, "cancel", None)  # and stops its job
            s.runs.langfuse = Langfuse(
                settings.langfuse_public_key, settings.langfuse_secret_key,
                settings.langfuse_base_url, settings.langfuse_capture_content,
            )  # fmt: skip
            if r.conn is not None:  # resume graphs when workers report results
                consumer = JobCompletionConsumer(r.conn, s.runs, r.run_store)
                await consumer.start()
            if desktop:  # the worker runs in this process
                await desktop.start(s.runs)
                # the person this desktop belongs to: the launcher's connection is theirs
                me = await s.users.resolve(
                    settings.default_tenant_id,
                    Claims("desktop", "local", None, False, None, None),
                    settings.admin_email_set,
                )
                assert s.launcher is not None
                await s.launcher.write_if_enabled(
                    Identity(settings.default_tenant_id, me.id, me.role)
                )
            if desktop is None:
                await _resume_web_jobs(s)
            # the SDK's session manager lives as long as the engine (spike S1)
            async with s.mcp.session_manager.run():
                # the opt-in fixed port is the desktop's (ADR-0069, M3); a service listens on
                # its own port, and its database may not be migrated yet when it starts
                assert s.fixed_port is not None
                if desktop:
                    await s.fixed_port.start_if_saved()
                try:
                    yield
                finally:
                    await s.fixed_port.stop(forget=False)
                    if s.mcp_client is not None:
                        await s.mcp_client.close_all()
                    if desktop and s.launcher is not None:
                        remove_runtime_file(s.launcher.path)
    finally:
        if s.runs is not None:
            s.runs.langfuse.flush()
        tracing.flush()  # send the spans still waiting
        await _close(s, r, given, desktop, consumer)


async def _shared(
    s: ApiServices,
    given: Injected,
    settings: Settings,
    desktop: Desktop | None,
    enabled: Callable[[list[str]], list[str]],
) -> _Running:
    """What every deployment has: the database, the lines and their policy, storage,
    secrets, models, the catalogue and its MCP server, search and the stores of people's files."""
    reg = given.registry
    assert reg is not None
    injected = given.test_app
    pdir = given.products_dir or Path(settings.products_dir)
    db = given.engine or (desktop.engine if desktop else create_async_engine(settings.database_url))
    recorder = given.usage or (desktop.usage if desktop else PostgresUsageRecorder(db))
    owns_conn = given.redis is None and not injected and desktop is None
    conn: Redis | None = given.redis or (
        Redis.from_url(
            settings.redis_url, decode_responses=True, socket_timeout=REDIS_SOCKET_TIMEOUT_S
        )
        if owns_conn
        else None
    )
    log_ = given.event_log or (desktop.event_log if desktop else RedisEventLog(conn))  # type: ignore[arg-type]
    store_ = given.run_store or (desktop.run_store if desktop else RedisRunStore(conn))  # type: ignore[arg-type]
    # ADR-0088 (stage J4): one policy decides whether a job may enter a line, counted with a
    # lease per job in Redis (in memory without one); the desktop is never limited
    policy = JobPolicy(
        RedisLeases(conn) if conn is not None else InMemoryLeases(),
        (lambda: 0) if desktop else (lambda: get_settings().max_jobs_per_user),
    )
    s.job_policy = policy
    sink = AdmittedSink(
        given.job_sink
        or (
            desktop.queue if desktop else (RedisJobSink(conn, log_) if conn else InMemoryJobSink())
        ),
        policy,
    )
    store = given.storage or (desktop.storage if desktop else None)
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
    settings_store = (
        InMemorySettingsStore()
        if injected
        else (desktop.settings_store if desktop else PostgresSettingsStore(db))
    )
    # keys and tokens (ADR-0092): the desktop's keychain or file; on the web the `secrets`
    # table under MEDIA_SECRETS_KEY, with what External Secrets put in the environment behind
    secrets: SecretStore
    if desktop is not None and desktop.secrets is not None:
        secrets = desktop.secrets
    elif injected:
        secrets = InMemorySecretStore()
    else:
        secrets = LayeredSecretStore(
            SqlSecretStore(db, SecretBox(settings.media_secrets_key)), EnvSecretStore()
        )
    s.secrets = secrets
    deps = ProviderDeps(
        products_dir=pdir,
        usage=recorder,
        job_sink=sink,
        litellm_base_url=settings.litellm_base_url,
        litellm_api_key=settings.litellm_api_key,
        text_provider=_desktop_text(desktop, recorder),
        storage=store,
        db=db,
        embedding_dims=DIMENSIONS,
    )
    r = _Running(db, conn, owns_conn, log_, store_, sink, deps, desktop is not None)

    models = given.model_access
    if models is None:
        base = settings.ollama_base_url.rstrip("/")
        defaults = load_defaults({"OLLAMA_BASE_URL": base, "OLLAMA_OPENAI_BASE_URL": f"{base}/v1"})
        if injected or desktop:  # tests, desktop: no gateway to seed
            models = ModelAccess(InMemoryModelBackend(), defaults)
        else:
            models = ModelAccess(
                LiteLLMBackend(settings.litellm_base_url, settings.litellm_api_key), defaults
            )
            r.background.append(asyncio.create_task(_seed_models(models)))
    s.models = models
    s.products_dir = pdir  # the picker names the models a product ships (models_in_use)
    s.media = given.media_access or MediaAccess(
        InMemoryMediaBindingStore() if injected or desktop else PostgresMediaBindingStore(db),
        SecretBox(settings.media_secrets_key),
        lambda: media_capabilities_from(reg, pdir, settings.product_env),
        settings.comfyui_base_url,
        video_local_url=settings.comfyui_video_base_url,
    )
    s.caps = {}
    configs = r.configs
    s.upload_rules = lambda pid, kind="image": (
        configs[pid].uploads.get(kind) if pid in configs else None
    )

    # The action catalogue and its one executor (ADR-0068): the assistant runs its tools
    # through it, and so does MCP. Audit and approvals live in the database the engine has.
    r.tool_host = _tool_host(s, desktop is not None, enabled)
    s.actions = build_executor(
        reg,
        r.tool_host,
        served=enabled(reg.products()),
        db=None if injected else db,
        usage=recorder,
    )
    # the MCP server (ADR-0069): connections, the approval desk the window answers, the
    # events the window listens to, and the SDK's server over the same executor
    s.events = EventBus()
    s.connections = ConnectionsService(
        InMemoryConnectionStore() if injected else SqlConnectionStore(db)
    )
    s.approval_desk = ApprovalDesk(s.actions)
    attach_mcp(
        s, build_mcp_server(s.actions, s.approval_desk, s.events, s.connections), s.connections
    )
    if desktop is not None:
        port = urlparse(settings.desktop_public_url).port
        s.launcher = Launcher(Path(settings.desktop_data_dir), secrets, s.connections, port)
    # the MCP client (ADR-0070, stage C1): the servers the person added, one session each
    # (desktop only: ADR-0070 keeps the web deployment out; tests get an in-memory store)
    if desktop is not None or injected:
        s.mcp_client = ExternalClient(
            ServersService(InMemoryServerStore() if injected else SqlServerStore(db), secrets),
            Path(settings.desktop_data_dir) if desktop else None,
            FormDesk(s.events),  # a server's question becomes a card (C3)
        )
    # the opt-in fixed port for HTTP clients (stage M3), remembered in the settings store
    s.fixed_port = FixedPort(s.mcp_gate, settings_store)

    s.users = given.users or CachedUsers(desktop.users if desktop else PostgresUserStore(db))
    s.admin = given.admin_store or PostgresAdminStore(db)
    s.registry = reg
    s.usage = recorder
    s.uploads = given.uploads or (
        InMemoryUploadStore()
        if injected
        else (desktop.uploads if desktop else PostgresUploadStore(db))
    )
    s.upload_limiter = given.upload_limiter or (
        RedisUploadLimiter(conn) if conn is not None else InMemoryUploadLimiter()
    )
    s.enhance_limiter = given.enhance_limiter or (
        RedisUploadLimiter(conn, per_hour=ENHANCES_PER_HOUR, name="enhance")
        if conn is not None
        else InMemoryUploadLimiter(ENHANCES_PER_HOUR)
    )
    s.search_limiter = given.search_limiter or (
        RedisUploadLimiter(conn, per_hour=SEARCHES_PER_HOUR, name="search")
        if conn is not None
        else InMemoryUploadLimiter(SEARCHES_PER_HOUR)
    )
    s.creation_index = _creation_index(given, settings, desktop, db, recorder)
    index_sources = {
        pid: make
        for pid, make in reg.index_sources().items()
        if pid in enabled(list(reg.products()))
    }
    if not injected and index_sources:
        r.background.append(
            asyncio.create_task(
                reconcile_forever(
                    s.creation_index,
                    lambda: [make(db) for make in index_sources.values()],
                    settings.search_reconcile_every_s,
                    settings.search_reconcile_batch,
                )
            )
        )
    if store is not None and not injected:
        r.background.append(asyncio.create_task(sweep_forever(s.uploads, store)))
    s.engine = db
    s.storage = store
    s.heartbeat_s = given.heartbeat_s
    return r


def _creation_index(
    given: Injected,
    settings: Settings,
    desktop: Desktop | None,
    db: AsyncEngine,
    recorder: UsageRecorder,
) -> CreationIndex:
    """Search of My creations (ADR-0041). A desktop engine without a gateway still indexes, with a
    small local embedder; its rows are replaced by real embeddings when a gateway is configured
    (the model name differs)."""
    search_provider = LiteLLMTextProvider(
        settings.litellm_base_url, settings.litellm_api_key, recorder
    )
    search_binding = CapabilityBinding(provider="litellm", model=SEARCH_ALIAS)

    async def litellm_embed(texts: list[str]) -> list[list[float]]:
        return await search_provider.embed("search.embed", search_binding, texts)

    local_only = desktop is not None and not settings.litellm_base_url
    embed: Embedder = given.creation_embedder or (hashing_embed if local_only else litellm_embed)
    return CreationIndex(
        given.index_store
        or (
            InMemoryIndexStore()
            if given.test_app
            else (desktop.index_store if desktop else PostgresIndexStore(db))
        ),
        embed,
        LOCAL_EMBEDDER_MODEL
        if local_only and not given.creation_embedder
        else settings.search_index_model,
        settings.search_min_similarity,
    )


def _tool_host(
    s: ApiServices, desktop: bool, enabled: Callable[[list[str]], list[str]]
) -> ApiToolHost:
    """The assistant's view of the engine (ADR-0057): its tools, what it may offer the model, and
    the words that describe a creation it found."""

    def served() -> list[str]:
        assert s.registry is not None
        return enabled(s.registry.products())

    async def describe_image(tenant: str, user: str, item_id: str) -> str:
        # the words an image was made from: what the assistant tells the model it found
        from wasifyai_image.images import image_store

        assert s.engine is not None
        found = await image_store(s.engine).get(tenant, user, item_id)
        return found.prompt if found else ""

    async def describe_voice_item(tenant: str, user: str, item_id: str) -> str:
        # the title of a track (or the words of a speech, a transcript or a voice's name)
        from wasifyai_voice.runtime import store_for

        store = store_for(s)
        for get, field_ in (
            (store.get_track, "title"),
            (store.get_speech, "text"),
            (store.get_transcript, "title"),
            (store.get_voice, "name"),
            (store.get_clip, "title"),
        ):
            try:
                return str(get(tenant, user, item_id)[field_])
            except Exception:  # not this table
                continue
        return ""

    async def describe_notebook(tenant: str, user: str, item_id: str) -> str:
        # the title of a notebook, so a search of My creations names it rather than its id
        from wasifyai_notebooks.runtime import runtime_for

        return runtime_for(s).store.get_notebook(tenant, user, item_id)["title"]

    async def search_notebooks(
        tenant: str, user: str, query: str, limit: int
    ) -> list[dict[str, Any]]:
        # the passages of the person's notebooks (stage E6); only where notebooks are served
        try:
            from wasifyai_notebooks.across import search_across
            from wasifyai_notebooks.runtime import NotAvailable, runtime_for
        except ImportError:
            raise ToolUnavailable("Notebooks are not part of this build.") from None
        try:
            rt = runtime_for(s)
        except NotAvailable:
            raise ToolUnavailable("Notebooks are not available here.") from None
        return await search_across(rt, tenant, user, query, limit)

    def available_tools() -> set[str]:
        """What the assistant may offer the model here: a tool is offered only where what it
        needs is served (images by the image product, music by the speech runtime, notebooks by
        the desktop's library), so the model is never told about something that cannot run."""
        # the meta-tools of ADR-0071: what an action needs is checked when it is proposed
        tools = {"how_to", "app_status", "propose_action", "open_screen", "search_creations"}
        if (desktop or s.notebooks_web) and "wasifyai-notebooks" in served():
            tools.add("search_notebooks")
        if s.web is not None:
            tools.update({"web_search", "web_read"})
        if s.mcp_client is not None:  # ADR-0070 decision 8
            tools.update({"external_tools", "call_external"})
        return tools

    describe = describe_voice_item
    return ApiToolHost(
        lambda: s.runs,
        lambda: s.creation_index,
        {
            "image": describe_image,
            "notebook": describe_notebook,
            "track": describe,
            "speech": describe,
            "transcript": describe,
            "voice": describe,
            "lipsync": describe,
        },
        search_notebooks,
        available_tools,
        lambda: s,
        lambda: set(served()),
        lambda: s.route_deps,
    )


def _build_graphs(
    s: ApiServices,
    settings: Settings,
    r: _Running,
    saver: Any,
    enabled: Callable[[list[str]], list[str]],
) -> dict[str, Any]:
    reg, pdir = s.registry, s.products_dir
    assert reg is not None and pdir is not None
    graphs: dict[str, Any] = {}
    for product_id in enabled(reg.products()):
        # Fails at startup, with every problem listed, if the product config is bad.
        config = load_product_config(pdir, product_id, env=settings.product_env)
        r.configs[product_id] = config
        caps = build_capabilities(config, r.deps)
        if "text.embed" in config.capabilities:
            caps.rag = RagService(r.db, lambda texts, c=caps: c.text.embed("embed", texts))
        caps.indexer = ContextIndexer(s.creation_index)
        caps.extras["tool_host"] = r.tool_host  # the assistant's tools (ADR-0057)
        caps.extras["actions"] = s.actions  # ...which run as actions (ADR-0068)
        caps.extras["app_state"] = s  # notebooks reach their library through it
        if not r.desktop and product_id in ("wasifyai-video", "wasifyai-image"):
            # the web: a look or a style is the person's own file in storage
            from wasifyai_api.person_looks import person_looks

            caps.extras["person_looks"] = person_looks(s, video=product_id == "wasifyai-video")
        s.caps[product_id] = caps
        graphs[product_id] = reg.build(product_id, caps, saver)
    return graphs


async def _web_services(s: ApiServices, settings: Settings, r: _Running, given: Injected) -> None:
    """What only the web has: web search on a service, the engine workers, and the products that
    keep their records in Postgres and their work on workers. A product is served when its folder
    is in the products directory and its package is part of the build."""
    if settings.web_search_enabled:
        # web search on a service (ADR-0083): an admin chooses the search service and keeps the
        # keys, and each person allows it for themself; nothing is sent before that
        assert s.secrets is not None and s.usage is not None
        s.web = WebService(
            InMemorySettingsStore() if given.test_app else PostgresSettingsStore(r.db),
            s.secrets,
            s.usage,
            per_person=True,
            legacy_box=SecretBox(settings.media_secrets_key),
        )
    store, conn, pdir = s.storage, r.conn, s.products_dir
    assert pdir is not None
    if store is None:
        return
    queue = (lambda: EngineQueue(conn, policy=s.job_policy)) if conn is not None else None
    # the engine workers that run the desktop's heavy capabilities for the web (ADR-0087):
    # speech and 3D read what they have from one list
    if queue is not None:
        s.engine_workers = WorkerDirectory(queue())
        s.engine_workers.start()
    if (pdir / "wasifyai-voice").is_dir():
        await _web_voice(s, settings, queue)
    if (pdir / "wasifyai-notebooks").is_dir():
        _web_notebooks(s, settings)
    if queue is None:
        return
    if (pdir / "wasifyai-model3d").is_dir():
        await _web_model3d(s, settings, queue)
    if (pdir / "wasifyai-video").is_dir():
        await _web_builder(s, settings, queue)
    if (pdir / "wasifyai-training").is_dir():
        await _web_training(s, settings, queue)


async def _web_voice(s: ApiServices, settings: Settings, queue: Callable[[], EngineQueue] | None):
    try:
        from wasifyai_voice.store import VoiceStore

        from wasifyai_api.hosted_speech import HostedSpeechEngine, load_hosted_models
    except ImportError:  # the voice product is not part of this build
        log.warning("the voice product is not installed: no speech on the web")
        return
    assert s.products_dir is not None and s.storage is not None
    pdir = s.products_dir
    s.voice_store = await asyncio.to_thread(
        VoiceStore.on_postgres, settings.database_url, schema=settings.voice_schema
    )
    hosted = None
    if settings.voice_engine in ("hosted", "both", "worker"):
        models_file = Path(
            settings.voice_models_file or pdir / "wasifyai-voice" / "hosted-models.yaml"
        )
        hosted = HostedSpeechEngine(
            load_hosted_models(models_file), settings.litellm_base_url, settings.litellm_api_key
        )
    if settings.voice_engine == "hosted" or (settings.voice_engine == "worker" and queue is None):
        s.audio = hosted
    elif settings.voice_engine == "worker" and queue is not None:
        # the desktop's capabilities run on engine workers (ADR-0087); the hosted models
        # answer too. Nothing is offered from a worker until one is running.
        from wasifyai_api.desktop_models import load_catalogue
        from wasifyai_api.local_speech import CombinedSpeechEngine
        from wasifyai_api.remote_speech import RemoteSpeechEngine

        voice_models = {
            e.id: e.voice
            for e in load_catalogue(Path(pdir), ["wasifyai-voice"])
            if e.voice is not None
        }
        remote = RemoteSpeechEngine(
            queue(), s.storage.backing, voice_models, directory=s.engine_workers, usage=s.usage
        )
        s.audio = CombinedSpeechEngine(remote, hosted)
    else:
        from wasifyai_api.local_speech import CombinedSpeechEngine, build_local_engine

        local = build_local_engine(settings, Path(pdir))
        s.audio = CombinedSpeechEngine(local, hosted) if hosted is not None else local


def _web_notebooks(s: ApiServices, settings: Settings) -> None:
    try:
        from wasifyai_notebooks.runtime import WebSetup
    except ImportError:  # notebooks are not part of this build
        log.warning("the notebooks product is not installed: no notebooks on the web")
        return
    assert s.storage is not None
    s.notebooks_web = WebSetup(
        dsn=settings.database_url,
        storage=s.storage.backing,
        models_dir=Path(settings.notebooks_models_dir or "/models"),
        reader_dir=Path(settings.notebooks_reader_dir or "/reader"),
        tmp_dir=Path(tempfile.gettempdir()) / "notebooks",
        schema=settings.notebooks_schema,
        loop=asyncio.get_running_loop(),
        gateway_url=settings.litellm_base_url,
        gateway_key=settings.litellm_api_key,
        embed_model=settings.notebooks_embed_model,
        embed_dimension=settings.notebooks_embed_dimension,
    )


async def _web_model3d(s: ApiServices, settings: Settings, queue: Callable[[], EngineQueue]):
    try:
        from wasifyai_model3d.blobs import StorageBlobs
        from wasifyai_model3d.runtime import sweep as sweep_model3d
        from wasifyai_model3d.store import Model3dStore

        from wasifyai_api.remote_model3d import RemoteModel3dEngine
    except ImportError:  # the 3D product is not part of this build
        log.warning("the 3D product is not installed: no 3D models on the web")
        return
    assert s.storage is not None
    # 3D models on engine workers (ADR-0087, P3): Postgres for the rows, object storage for the
    # files, a worker that has the component for the work
    s.model3d_store = await asyncio.to_thread(Model3dStore.on_postgres, settings.database_url)
    s.model3d_blobs = StorageBlobs(s.storage)
    s.model3d = RemoteModel3dEngine(queue(), s.storage.backing, s.engine_workers, usage=s.usage)
    await sweep_model3d(s)


async def _web_builder(s: ApiServices, settings: Settings, queue: Callable[[], EngineQueue]):
    try:
        from wasifyai_video.builder.store import BuilderStore

        from wasifyai_api.remote_builder import RemoteBuilderEngine
    except ImportError:  # the video product is not part of this build
        log.warning("the video product is not installed: no Motion graphics on the web")
        return
    assert s.storage is not None
    # Motion graphics on engine workers (ADR-0087, P4): Postgres for the compositions, a worker
    # with the sandboxed browser for the drawing; videos are library clips
    s.builder_store = await asyncio.to_thread(BuilderStore.on_postgres, settings.database_url)
    s.builder_scratch = Path(tempfile.mkdtemp(prefix="wasifyai-builder-"))
    s.video_builder = RemoteBuilderEngine(
        queue(),
        s.storage.backing,
        s.engine_workers,
        gateway_url=settings.litellm_base_url,
        gateway_key=settings.litellm_api_key,
        usage=s.usage,
    )
    stale = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    await asyncio.to_thread(s.builder_store.fail_stale, stale, "It was stopped before it finished.")


async def _web_training(s: ApiServices, settings: Settings, queue: Callable[[], EngineQueue]):
    try:
        from wasifyai_training.files import StorageFiles
        from wasifyai_training.store import TrainingStore

        from wasifyai_api.remote_train import (
            RemoteDecisionTrainer,
            RemoteImageTrainer,
            RemoteVideoTrainer,
            RemoteWritingTrainer,
        )
    except ImportError:  # the training product is not part of this build
        log.warning("the training product is not installed: no Train on the web")
        return
    assert s.storage is not None
    # Train on engine workers (ADR-0073, docs/train-web-plan.md): Postgres for the rows, object
    # storage for the files, a worker that has the trainer for the work
    tstore = await asyncio.to_thread(
        TrainingStore.on_postgres,
        settings.database_url,
        cache=Path(tempfile.mkdtemp(prefix="wasifyai-training-")),
    )
    s.training_store = tstore
    s.training_files = StorageFiles(s.storage.backing)
    tq, tdir, backing = queue(), s.engine_workers, s.storage.backing
    s.video_training = RemoteVideoTrainer(tq, backing, tdir, usage=s.usage)
    s.training = RemoteImageTrainer(tq, backing, tdir, usage=s.usage)
    s.language_training = RemoteWritingTrainer(tq, backing, tdir, usage=s.usage)
    s.decision_training = RemoteDecisionTrainer(tq, backing, tdir, usage=s.usage)
    # a run a gone service left going is failed, and its worker job stopped
    for run in await asyncio.to_thread(tstore.runs_left_working):
        await tq.cancel(run["id"])


async def _resume_web_jobs(s: ApiServices) -> None:
    """3D models and Motion graphics a worker was still making when this service stopped are
    followed again (one replica each, stage J3)."""
    assert s.route_deps is not None
    if s.model3d_store is not None:
        from wasifyai_model3d.runtime import resume as resume_model3d

        await resume_model3d(s.route_deps)
    if s.builder_store is not None:
        from wasifyai_video.builder.runtime import manager_for as renders_for

        await renders_for(s.route_deps).resume_all()


def _desktop_text(desktop: Desktop | None, recorder: Any) -> Any:
    """The text provider of the desktop: the model chosen on this computer, or the person's own
    provider while Chat and writing runs with their key (ADR-0095, K2)."""
    if desktop is None or desktop.language is None:
        return None
    local = LocalTextProvider(desktop.language, recorder)
    if desktop.own_keys is None:
        return local
    return KeyedTextProvider(local, desktop.own_keys, recorder)


def _desktop_services(s: ApiServices, desktop: Desktop) -> None:
    """What only the desktop has: the runtimes and components of this computer (ADR-0056)."""
    s.local_files = desktop.local_files
    s.desktop_models = desktop.models
    s.desktop_discovery = desktop.discovery
    s.llama_server = desktop.llama
    s.audio = desktop.audio  # the speech runtime (ADR-0066); products reach it here
    s.video_builder = desktop.video_builder  # the render engine (ADR-0077)
    s.model3d = desktop.model3d  # the 3D engine (ADR-0080)
    s.training_setup = desktop.training_setup  # the trainer, set up on request
    s.training = desktop.training  # the trainer: mflux on a Mac (ADR-0073)
    s.language_training = desktop.writing  # mlx-lm on a Mac (ADR-0074)
    s.language_setup = desktop.language_setup  # its component, set up on request
    s.decision_training = desktop.deciding  # Laya on a Mac (ADR-0075)
    s.decision_setup = desktop.decision_setup  # its component, set up on request
    s.video_training = desktop.teaching_video  # diffusers on a Mac (ADR-0073)
    s.video_setup = desktop.video_setup  # its component, set up on request
    if desktop.video_builder is not None:  # and the model it asks to fill a template
        desktop.video_builder.language = desktop.language
        desktop.video_builder.usage = s.usage
    s.desktop_language = desktop.language
    s.desktop_vision = desktop.vision
    s.desktop_hub = desktop.hub
    s.own_keys = desktop.own_keys  # the person's own provider keys (ADR-0095)
    if desktop.own_keys is not None:  # speaking and 3D follow theirs too (K4)
        if desktop.audio is not None:
            s.audio = KeyedSpeechEngine(desktop.audio, desktop.own_keys)
        if desktop.model3d is not None:
            s.model3d = KeyedModel3d(desktop.model3d, desktop.own_keys)
    if desktop.web is not None:  # web search: off until the person allows it (ADR-0083)
        desktop.web.usage = s.usage
        s.web = desktop.web
    # notebooks keep their library under the app's data folder
    s.desktop_dir = desktop.settings.desktop_dir
    s.products_dir = Path(desktop.settings.products_dir)
    # "Save" in the window copies a picture here (the product's export route)
    s.export_dir = Path(os.environ.get("WASIFYAI_EXPORT_DIR") or Path.home() / "Downloads")
    # the optional components, on the one installer (stage F2)
    s.components = _desktop_components(s, desktop)


def engine_bundle(products_dir: Path | None) -> Path | None:
    """The engine files this app was installed from (the locks of its components): where the shell
    says (`WASIFYAI_ENGINE_BUNDLE`), else beside the products a packaged app runs, else a
    checkout's `apps/desktop/engine-bundle`."""
    given = os.environ.get("WASIFYAI_ENGINE_BUNDLE")
    candidates = [Path(given)] if given else []
    if products_dir is not None:
        candidates += [products_dir.parent, products_dir.parent / "apps/desktop/engine-bundle"]
    return next((c for c in candidates if (c / "bundle.json").is_file()), None)


def _desktop_components(s: ApiServices, desktop: Desktop) -> Registry:
    """The optional components of this computer, on the one installer (stage F2); their status
    changes go to the window as `component` events."""
    data_dir = Path(desktop.settings.desktop_data_dir)
    manifest = load_manifest()
    registry = Registry()
    llama = LlamaCppComponent(data_dir, manifest)
    registry.add(llama, llama.installer)
    uv = os.environ.get("WASIFYAI_UV") or shutil.which("uv")
    comfy = ComfyUiComponent(data_dir, manifest, engine_bundle(s.products_dir), uv)
    registry.add(comfy, comfy.installer)
    for part in service_components(s, desktop):
        registry.add(part)
    events = s.events
    if events is not None:
        registry.listeners.append(
            lambda cid, status: events.publish("component", id=cid, status=status)
        )
    return registry


async def _close(
    s: ApiServices,
    r: _Running,
    given: Injected,
    desktop: Desktop | None,
    consumer: JobCompletionConsumer | None,
) -> None:
    """Stop the background tasks and wait for them before the database goes: a task that is
    cancelled in the middle of a query rolls back through its connection, and a connection that is
    already closed never answers, which left the task (and the event loop's own shutdown) waiting
    forever."""
    # the jobs on engine workers go on while this service restarts: stopping is not Stop
    for engine in (s.model3d, s.video_builder):
        if not desktop and getattr(engine, "resumable", False):
            engine.closing = True
    for t in r.background:
        t.cancel()
    await asyncio.gather(*r.background, return_exceptions=True)
    if consumer:
        await consumer.stop()
    if desktop:
        await desktop.stop()
    elif s.voice_store is not None:
        web_audio: Any = s.audio
        if web_audio is not None:  # the hosted client, and the local models' memory
            close = getattr(web_audio, "close", None)
            await (close() if close is not None else web_audio.stop())
        await asyncio.to_thread(s.voice_store.close)
    if s.engine_workers is not None:
        await s.engine_workers.close()
    if not desktop:
        for kept in (s.model3d_store, s.training_store, s.builder_store):
            close_kept = getattr(kept, "close", None)
            if close_kept is not None:
                await asyncio.to_thread(close_kept)
    if s.builder_scratch is not None:
        shutil.rmtree(s.builder_scratch, ignore_errors=True)
    if s.runs is not None:
        await s.runs.aclose()
    if r.owns_conn and r.conn is not None:
        await r.conn.aclose()
    if given.engine is None:
        await r.db.dispose()
