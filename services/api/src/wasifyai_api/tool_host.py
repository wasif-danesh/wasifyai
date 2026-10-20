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
        language = getattr(self._app_state(), "desktop_language", None)
        if language is None:
            return True  # the hosted model decides; the provider says if it cannot
        chosen = language.selected
        return chosen is not None and chosen.vision is not False

    async def web_search(self, query: str, limit: int = 5) -> Any:
        web = getattr(self._app_state(), "web", None)
        if web is None:
            raise WebError("search_off", "Web search is not available here.")
        return await web.search(query, limit)

    async def web_read(self, url: str) -> Any:
        web = getattr(self._app_state(), "web", None)
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
            audio = getattr(state, "audio", None)
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
            if getattr(state, "desktop_models", None) is None:
                return Readiness.unavailable("Models are managed in the desktop app.")
            return Readiness.ready()
        if need.kind == "runtime" and need.name == "video-builder":
            builder = getattr(state, "video_builder", None)
            if builder is None or not builder.installer.supported:
                return Readiness.unavailable(
                    "Video Builder is not available on this kind of computer yet."
                )
            if not builder.ready():
                why = builder.media_problem() if builder.install() is not None else None
                return Readiness.needs_setup(
                    why
                    or "Set up Video Builder first (it is a download of a few hundred megabytes).",
                    ui="video.builder",
                )
            return Readiness.ready()
        if need.kind == "notebooks":
            here = getattr(state, "desktop_dir", None) or getattr(state, "notebooks_web", None)
            if not here:
                return Readiness.unavailable("Notebooks are not available here.")
            return Readiness.ready()
        if need.kind == "web":
            web = getattr(state, "web", None)
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
        svc = getattr(state, "desktop_models", None)
        if svc is not None:
            from wasifyai_api.desktop_models import free_disk_bytes

            facts["disk_free_bytes"] = free_disk_bytes(svc.models_dir)
            facts["models_ready"] = sum(
                1 for e in svc.catalogue.values() if all(svc.locate(f) is not None for f in e.files)
            )
        facts["export_folder_set"] = getattr(state, "export_dir", None) is not None
        return facts
