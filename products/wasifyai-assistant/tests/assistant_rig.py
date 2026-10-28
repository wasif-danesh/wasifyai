"""A test rig: the assistant graph on scripted models, a scripted tool host, an in-memory store."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import yaml
from langgraph.checkpoint.memory import InMemorySaver
from wasifyai_assistant.graph import build_assistant_graph
from wasifyai_assistant.store import InMemoryConversationStore
from wasifyai_image.actions import actions as image_actions
from wasifyai_notebooks.actions import actions as notebook_actions
from wasifyai_platform_sdk import (
    InMemoryUploadStore,
    InMemoryUsageRecorder,
    ProviderDeps,
    ScopedStorage,
    ToolUnavailable,
    build_capabilities,
    load_product_config,
    new_upload,
)
from wasifyai_platform_sdk.actions import (
    ActionExecutor,
    ActionRegistry,
    Need,
    Readiness,
    builtin_actions,
)
from wasifyai_platform_sdk.storage import memory_storage
from wasifyai_voice.actions import actions as voice_actions


class FakeHost:
    """A `ToolHost`: scripted child-run events per product, scripted search hits."""

    def __init__(self) -> None:
        self.runs: list[tuple[str, dict[str, Any]]] = []
        self.searches: list[str] = []
        self.notebook_searches: list[str] = []
        self.notebook_error: str | None = None
        self.web_searches: list[str] = []
        self.web_reads: list[str] = []
        self.web_response: Any = None  # a `web.SearchResponse`
        self.web_page: Any = None  # a `web.WebPage`
        self.web_error: Exception | None = None
        self.external: list[dict[str, Any]] = []  # what external_tools finds (ADR-0070)
        self.external_searches: list[str] = []
        self.trusted: set[tuple[str, str]] = set()  # (server, tool) pairs that run unasked
        self.passages: list[dict[str, Any]] = [
            {"notebook_id": "nb-1", "notebook": "Budget", "document_id": "d-1",
             "title": "plan.md", "text": "The launch budget is 40,000 dollars."}
        ]  # fmt: skip
        self.child_events: list[dict[str, Any]] = [
            {"event": "job_progress", "job_id": "j1", "capability": "image.generate",
             "status": "running", "progress": 0.5},
            {"event": "done", "outputs": {"status": "done", "image_id": "img-1", "width": 1024,
                                          "height": 1024, "prompt": "a fox"}},
        ]  # fmt: skip
        self.hits: list[dict[str, Any]] = [
            {"kind": "image", "product_id": "wasifyai-image", "id": "img-9", "text": "a red teapot"}
        ]

    async def run_product(
        self, product_id: str, graph_input: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        self.runs.append((product_id, graph_input))
        for ev in self.child_events:
            yield ev

    async def run_state(self, tenant_id: str, run_id: str) -> dict[str, Any]:
        return {"status": "unknown"}  # no runs outlive a test

    async def cancel_run(self, tenant_id: str, run_id: str) -> bool:
        return False

    async def search_creations(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        self.searches.append(query)
        return self.hits

    # the rest of an `ActionHost`: everything is ready, and there are no stores to reach
    deps = None

    async def readiness(self, need: Need) -> Readiness:
        return Readiness.ready()

    def facts(self) -> dict[str, Any]:
        return {}

    async def external_tools(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        self.external_searches.append(query)
        return list(self.external)[:limit]

    async def external_servers(self) -> list[str]:
        return sorted({str(t["server"]) for t in self.external})

    async def external_trusted(self, connection: str, tool: str) -> bool:
        return (connection, tool) in self.trusted

    async def web_search(self, query: str, limit: int = 5) -> Any:
        self.web_searches.append(query)
        if self.web_error:
            raise self.web_error
        return self.web_response

    async def web_read(self, url: str) -> Any:
        self.web_reads.append(url)
        if self.web_error:
            raise self.web_error
        return self.web_page

    async def search_notebooks(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        self.notebook_searches.append(query)
        if self.notebook_error:
            raise ToolUnavailable(self.notebook_error)
        return self.passages


class Rig:
    def __init__(self, tmp_path: Path, turns: list[dict[str, Any]], host: FakeHost | None = None):
        d = tmp_path / "wasifyai-assistant"
        d.mkdir()
        (d / "product.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": "wasifyai-assistant",
                    "capabilities": {
                        "text.chat": {"provider": "fake", "defaults": {"turns": turns}},
                    },
                }
            )
        )
        self.usage = InMemoryUsageRecorder()
        config = load_product_config(tmp_path, "wasifyai-assistant")
        self.caps = build_capabilities(
            config, ProviderDeps(products_dir=tmp_path, usage=self.usage)
        )
        self.host = host
        if host is not None:
            self.caps.extras["tool_host"] = host
            # the tools run as catalogue actions (ADR-0068), through the one executor
            self.executor = ActionExecutor(
                ActionRegistry(
                    [*builtin_actions(), *image_actions(), *voice_actions(), *notebook_actions()]
                ),
                host,
                usage=self.usage,
            )
            self.caps.extras["actions"] = self.executor
        self.indexed: list[tuple[str, str, str]] = []

        class Indexer:
            async def index(_self, kind: str, item_id: str, text: str) -> None:  # noqa: N805
                self.indexed.append((kind, item_id, text))

        self.caps.indexer = Indexer()
        self.store = InMemoryConversationStore()
        self.uploads = InMemoryUploadStore()
        self.caps.storage = ScopedStorage(memory_storage())  # what was attached is kept here
        self._turns = 0
        self.graph = build_assistant_graph(self.caps, InMemorySaver(), self.store, self.uploads)

    async def attach(self, kind: str, data: bytes) -> str:
        """Put a file where an upload would have: the person's storage and the upload table.
        Returns its id, which a turn names in `attachments`."""
        record = new_upload("t1", "wasifyai-assistant", "u1", len(data), kind)
        await self.caps.storage.put(record.key, data)  # type: ignore[union-attr]
        await self.uploads.add(record)
        return record.id

    @property
    def model(self) -> Any:
        _binding, provider = self.caps.text._bound["chat"]
        return provider

    async def turn(self, text: str, conversation_id: str | None = None) -> tuple[dict, list[dict]]:
        """Run one turn in a chat where the person said the assistant may make things without a
        card (`approval: "auto"`); return the final state and the custom events the run manager
        would emit. `turn_with` is for a turn that tests the card."""
        graph_input: dict[str, Any] = {"text": text, "approval": "auto"}
        if conversation_id:
            graph_input["conversation_id"] = conversation_id
        return await self.turn_with(graph_input)

    async def turn_with(self, graph_input: dict[str, Any]) -> tuple[dict, list[dict]]:
        """Run one turn with the whole run input (the ids a client chose, for one)."""
        config = {"configurable": {"thread_id": f"th-{self._turns}"}}
        self._turns += 1
        self.config = config
        return await self._stream(graph_input, config)

    async def _stream(self, graph_input: Any, config: dict) -> tuple[dict, list[dict]]:
        graph: Any = self.graph
        final: dict[str, Any] = {}
        events: list[dict[str, Any]] = []
        async for mode, chunk in graph.astream(
            graph_input, config, stream_mode=["custom", "values"]
        ):
            if mode == "custom":
                events.append(chunk)
            else:
                final = chunk
        return final, events

    async def paused(self) -> dict[str, Any] | None:
        """What the last turn is waiting for the person to answer (the card), or None."""
        graph: Any = self.graph
        state = await graph.aget_state(self.config)
        for task in state.tasks:
            for intr in task.interrupts:
                return dict(intr.value)
        return None

    async def answer(self, value: Any) -> tuple[dict, list[dict]]:
        """The person's answer to the card; the turn goes on and the events after it come back."""
        from langgraph.types import Command

        return await self._stream(Command(resume=value), self.config)
