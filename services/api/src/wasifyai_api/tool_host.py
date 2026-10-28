"""What the assistant's tools reach (ADR-0057): the `ToolHost` the API gives a tool-using product.

It acts for the user of the current run (the tenant and user come from the run context), so a tool
can only ever touch that user's own creations, and a child run is a normal run: its own events,
guardrails, quotas and job queue, saved to the same library."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from wasifyai_platform_sdk import ToolUnavailable, VoiceEngineError, require_context
from wasifyai_platform_sdk.actions import Need, Readiness
from wasifyai_platform_sdk.web import WebError

log = logging.getLogger(__name__)

Describer = Callable[[str, str, str], Awaitable[str]]  # (tenant, user, item_id) -> a short text
NotebookSearch = Callable[[str, str, str, int], Awaitable[list[dict[str, Any]]]]
# (tenant, user, query, limit) -> passages; raises ToolUnavailable


class ApiToolHost:
    def __init__(
        self,
        runs: Callable[[], Any],
        index: Callable[[], Any],
        describers: dict[str, Describer] | None = None,
        notebook_search: NotebookSearch | None = None,
        available: Callable[[], set[str]] | None = None,
        state: Callable[[], Any] | None = None,
        served: Callable[[], set[str]] | None = None,
        route_deps: Callable[[], Any] | None = None,
    ):
        self._runs = runs
        self._index = index
        self._describers = describers or {}
        self._notebook_search = notebook_search
        self._available = available
        self._state = state
        self._served = served
        self._route_deps = route_deps

    def available_tools(self) -> set[str] | None:
        """The tools this deployment can run (the assistant offers the model only these); `None`
        when it was not told, which means all of them."""
        return self._available() if self._available else None

    def run_product(
        self, product_id: str, graph_input: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        ctx = require_context()
        return self._runs().run_child(product_id, ctx.tenant_id, ctx.user_id, graph_input)

    async def run_state(self, tenant_id: str, run_id: str) -> dict[str, Any]:
        runs = self._runs()
        state = await runs.state_of(tenant_id, run_id)
        # The desktop engine is one process: a run it holds as running or waiting for an answer,
        # and is not executing, ended when the engine last closed. (A run waiting for a media job
        # is resumed by the worker's result; on the web another replica may hold the run.)
        single = self._app_state().desktop_dir is not None
        if single and state["status"] in ("running", "waiting_input") and not runs.live(run_id):
            return {"status": "unknown"}
        return state

    async def cancel_run(self, tenant_id: str, run_id: str) -> bool:
        runs = self._runs()
        rec = await runs.store.get(tenant_id, run_id)
        if rec is None:
            return False
        return await runs.cancel(rec) == "cancelled"

    async def search_creations(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        ctx = require_context()
        hits, _degraded = await self._index().search(
            ctx.tenant_id, ctx.user_id, query.strip()[:200], None, max(1, min(limit, 12))
        )
        out: list[dict[str, Any]] = []
        for h in hits:
            if h.kind == "conversation":
                continue  # the assistant finds creations, not its own chats
            row: dict[str, Any] = {"kind": h.kind, "product_id": h.product_id, "id": h.item_id}
            describe = self._describers.get(h.kind)
            if describe is not None:
                try:
                    row["text"] = (await describe(ctx.tenant_id, ctx.user_id, h.item_id))[:200]
                except Exception:
                    log.warning("could not describe %s %s", h.kind, h.item_id)
            out.append(row)
        return out

    async def search_notebooks(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if self._notebook_search is None:
            raise ToolUnavailable("Notebooks are not available here.")
        ctx = require_context()
        return await self._notebook_search(
            ctx.tenant_id, ctx.user_id, query.strip()[:300], max(1, min(limit, 8))
        )

    def can_see(self) -> bool:
        """Can the chat model in use read a picture? (False only when it is known it cannot: a
        model whose abilities are not known is given the picture to try.)"""
        language = self._app_state().desktop_language
        if language is None:
            return True  # the hosted model decides; the provider says if it cannot
        chosen = language.selected
        return chosen is not None and chosen.vision is not False

    async def web_search(self, query: str, limit: int = 5) -> Any:
        web = self._app_state().web
        if web is None:
            raise WebError("search_off", "Web search is not available here.")
        return await web.search(query, limit)

    async def external_tools(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """The tools of the servers the person connected (ADR-0070 decision 8), best matches
        first; [] where the client is not part of this deployment. The person is the one of the
        current run, as every tool's."""
        client = self._app_state().mcp_client
        if client is None:
            return []
        ctx = require_context()
        return [t.public() for t in await client.search(ctx.tenant_id, ctx.user_id, query, limit)]

    async def external_servers(self) -> list[str]:
        """The names of the outside servers the person can use now (ADR-0070 decision 8: the
        model is told they exist); none where the client is not part of this deployment."""
        client = self._app_state().mcp_client
        if client is None:
            return []
        ctx = require_context()
        rows = await client.servers.store.for_person(ctx.tenant_id, ctx.user_id)
        return [s.name for s in rows if s.trust != "blocked" and not s.unhealthy]

    async def external_trusted(self, connection: str, tool: str) -> bool:
        """Whether a tool of an outside server runs without a card (ADR-0070 decision 4)."""
        client = self._app_state().mcp_client
        if client is None:
            return False
        ctx = require_context()
        return await client.trusted_read_only(ctx.tenant_id, ctx.user_id, connection, tool)

    async def web_read(self, url: str) -> Any:
        web = self._app_state().web
        if web is None:
            raise WebError("search_off", "Web search is not available here.")
        return await web.read(url)

    # ---- what the action executor asks (ADR-0068) --------------------------------------------

    @property
    def deps(self) -> Any:
        """The route deps product code reaches its stores through (app state, storage, search)."""
        return self._route_deps() if self._route_deps else None

    def _app_state(self) -> Any:
        return self._state() if self._state else None

    async def readiness(self, need: Need) -> Readiness:
        """Whether one thing an action requires is ready on this computer, and if not, the step
        that fixes it or the reason it cannot be here."""
        state = self._app_state()
        if need.kind == "product":
            served = self._served() if self._served else None
            if served is not None and need.name not in served:
                return Readiness.unavailable(f"{need.name} is not part of this build.")
            return Readiness.ready()
        if need.kind == "model":
            audio = state.audio
            if audio is None:
                return Readiness.unavailable("Speech and music are not available here yet.")
            try:
                audio.resolve(need.name, None)
            except VoiceEngineError as e:
                if e.code in ("runtime_missing", "model_missing", "no_model"):
                    return Readiness.needs_setup(e.message, ui="models")
                return Readiness.unavailable(e.message)
            return Readiness.ready()
        if need.kind == "runtime" and need.name == "models":
            if state.desktop_models is None:
                return Readiness.unavailable("Models are managed in the desktop app.")
            return Readiness.ready()
        if need.kind == "runtime" and need.name == "video-builder":
            builder = state.video_builder
            if builder is None or not builder.installer.supported:
                return Readiness.unavailable(
                    "Motion graphics is not available on this kind of computer yet."
                )
            if not builder.ready():
                why = builder.media_problem() if builder.install() is not None else None
                return Readiness.needs_setup(
                    why or "Set up Motion graphics first (a download of a few hundred megabytes).",
                    ui="motion",
                )
            return Readiness.ready()
        if need.kind == "runtime" and need.name == "training":
            trainer = state.training
            if trainer is None:
                return Readiness.unavailable("Training is not available here.")
            if not trainer.ready():
                return Readiness.needs_setup(
                    trainer.problem() or "Set up training first.", ui="train"
                )
            return Readiness.ready()
        if need.kind == "runtime" and need.name == "model3d":
            engine = state.model3d
            if engine is None or not engine.installer.supported:
                return Readiness.unavailable(
                    "3D models are not available on this kind of computer yet."
                )
            if not engine.ready():
                return Readiness.needs_setup(
                    "Set up 3D first (a download of about 9 GB, shown before it starts).",
                    ui="model3d",
                )
            return Readiness.ready()
        if need.kind == "notebooks":
            here = state.desktop_dir or state.notebooks_web
            if not here:
                return Readiness.unavailable("Notebooks are not available here.")
            return Readiness.ready()
        if need.kind == "web":
            web = state.web
            if web is None:
                return Readiness.unavailable("Web search is not available here.")
            return await web.readiness()
        if need.kind == "chat":
            return Readiness.ready()  # a missing chat model is reported by the run itself
        return Readiness.unavailable(f"This computer cannot check {need}.")

    def facts(self) -> dict[str, Any]:
        """Small facts for `app.status`: nothing private, no paths of the person's files."""
        state = self._app_state()
        facts: dict[str, Any] = {}
        svc = state.desktop_models
        if svc is not None:
            from wasifyai_api.desktop_models import free_disk_bytes

            facts["disk_free_bytes"] = free_disk_bytes(svc.models_dir)
            facts["models_ready"] = sum(
                1 for e in svc.catalogue.values() if all(svc.locate(f) is not None for f in e.files)
            )
        facts["export_folder_set"] = state.export_dir is not None
        # the desktop runs models in one memory slot (ADR-0056): an action that needs a model of its
        # own pauses the chat model while it runs; the card says so
        facts["one_slot"] = svc is not None
        return facts
