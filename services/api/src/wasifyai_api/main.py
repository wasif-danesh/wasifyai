"""The engine's app (ADR-0004): its settings checks, its routes, and its lifespan, which builds the
services (`assemble.run_engine`) and closes them again."""

import logging
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.telemetry import TelemetryConfig
from pydantic import TypeAdapter
from wasifyai_contracts import SseEvent
from wasifyai_platform_sdk import RouteDeps, tracing

from wasifyai_api.admin import me_router as me_router
from wasifyai_api.admin import router as admin_router
from wasifyai_api.admin_media import router as admin_media_router
from wasifyai_api.admin_models import router as admin_models_router
from wasifyai_api.admin_safeguards import router as admin_safeguards_router
from wasifyai_api.admin_workers import router as admin_workers_router
from wasifyai_api.assemble import ApiServices, Injected, run_engine
from wasifyai_api.attachments import router as attachments_router
from wasifyai_api.auth import MIN_SECRET_BYTES
from wasifyai_api.components.routes import router as components_router
from wasifyai_api.config import get_settings
from wasifyai_api.creations import router as creations_router
from wasifyai_api.decision_setup import router as decision_setup_router
from wasifyai_api.desktop import files_router
from wasifyai_api.desktop_audio import router as desktop_audio_router
from wasifyai_api.desktop_discovery import router as desktop_discovery_router
from wasifyai_api.desktop_events import router as desktop_events_router
from wasifyai_api.desktop_hub import router as desktop_hub_router
from wasifyai_api.desktop_lipsync import router as desktop_lipsync_router
from wasifyai_api.desktop_llm import router as desktop_llm_router
from wasifyai_api.desktop_model3d import router as desktop_model3d_router
from wasifyai_api.desktop_models import router as desktop_models_router
from wasifyai_api.desktop_save import router as desktop_save_router
from wasifyai_api.desktop_video_builder import router as desktop_video_builder_router
from wasifyai_api.diagnostics import router as diagnostics_router
from wasifyai_api.graphs import default_registry
from wasifyai_api.identity import get_identity
from wasifyai_api.language_setup import router as language_setup_router
from wasifyai_api.logging import configure_logging, request_id
from wasifyai_api.mcp_client.routes import router as external_router
from wasifyai_api.mcp_server.endpoint import mount as mount_mcp
from wasifyai_api.mcp_server.routes import router as connections_router
from wasifyai_api.metrics import MetricsMiddleware
from wasifyai_api.metrics import serve as serve_metrics
from wasifyai_api.models_in_use import router as models_in_use_router
from wasifyai_api.routes import router
from wasifyai_api.run_tracing import TracingMiddleware
from wasifyai_api.training_setup import router as training_setup_router
from wasifyai_api.uploads import router as uploads_router
from wasifyai_api.video_setup import router as video_setup_router


def create_app(given: Injected | None = None) -> FastAPI:
    """App factory. Tests hand in what they fake (`Injected`: a registry, a products dir with
    `provider: fake` bindings, a checkpointer, a usage recorder, an event log, a run store, a job
    sink ...), so no GPU, network, database or Redis is needed. Without an injected log or store the
    app uses Redis (production). Passing `redis` also starts the completion consumer that resumes
    graphs paused on media jobs."""
    given = given or Injected()
    settings = get_settings()
    configure_logging(settings.log_level)
    traces = settings.wasifyai_traces_file
    if not traces and settings.deployment_profile == "desktop" and settings.desktop_data_dir:
        traces = str(settings.desktop_dir / "logs" / "traces.jsonl")
    if not given.test_app:
        env = {**os.environ, "WASIFYAI_TRACES_FILE": traces} if traces else None
        tracing.setup("wasifyai-api", env)
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
    given.registry = given.registry or default_registry()
    products_registry = given.registry
    services = ApiServices(heartbeat_s=given.heartbeat_s)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not given.test_app:  # a test app must not open a port
            serve_metrics(settings.metrics_port)
        async with run_engine(services, given, enabled):
            yield

    def enabled(product_ids: list[str]) -> list[str]:
        """The products this deployment serves (all, unless PRODUCTS_ENABLED narrows it)."""
        only = settings.enabled_product_set
        return [p for p in product_ids if not only or p in only]

    # FastAPI's own telemetry is off: it records raw paths and exception messages, which can carry
    # file names and content. `TracingMiddleware` makes the request spans by ADR-0048's rule.
    off: TelemetryConfig = {
        "tracing": False, "metrics": False, "logs": False, "auto_configure": False,
    }  # fmt: skip
    app = FastAPI(title="wasifyai API", lifespan=lifespan, telemetry=off)
    app.state.services = services  # the only attribute (stage F1)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(TracingMiddleware)  # outermost: a request's span covers everything
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
    app.include_router(admin_workers_router)
    app.include_router(admin_safeguards_router)
    app.include_router(uploads_router)
    app.include_router(connections_router)
    app.include_router(external_router)
    app.include_router(desktop_events_router)
    mount_mcp(app)
    app.include_router(attachments_router)
    app.include_router(creations_router)
    app.include_router(models_in_use_router)
    if desktop_profile:
        app.include_router(files_router)
        app.include_router(desktop_models_router)
        app.include_router(desktop_audio_router)
        app.include_router(desktop_lipsync_router)
        app.include_router(desktop_video_builder_router)
        app.include_router(desktop_model3d_router)
        app.include_router(training_setup_router)
        app.include_router(language_setup_router)
        app.include_router(decision_setup_router)
        app.include_router(video_setup_router)
        app.include_router(desktop_save_router)
        app.include_router(desktop_discovery_router)
        app.include_router(desktop_llm_router)
        app.include_router(desktop_hub_router)
        app.include_router(components_router)
        app.include_router(diagnostics_router)

    # Product-provided routes (ADR-0023): mounted now so the OpenAPI schema (and the TypeScript
    # types generated from it) include them; what they use is read from the services at request
    # time, once the lifespan has filled them in.
    route_deps = RouteDeps(services, get_identity)
    services.route_deps = route_deps
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
