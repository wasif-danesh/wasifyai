"""A test rig: the assistant graph on scripted models, a scripted tool host, an in-memory store."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import yaml
from langgraph.checkpoint.memory import InMemorySaver
from wasifyai_assistant.graph import build_assistant_graph
from wasifyai_assistant.store import InMemoryConversationStore
from wasifyai_platform_sdk import (
    InMemoryUsageRecorder,
    ProviderDeps,
    build_capabilities,
    load_product_config,
)


class FakeHost:
    """A `ToolHost`: scripted child-run events per product, scripted search hits."""

    def __init__(self) -> None:
        self.runs: list[tuple[str, dict[str, Any]]] = []
        self.searches: list[str] = []
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

    async def search_creations(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        self.searches.append(query)
        return self.hits


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
        self.indexed: list[tuple[str, str, str]] = []

        class Indexer:
            async def index(_self, kind: str, item_id: str, text: str) -> None:  # noqa: N805
                self.indexed.append((kind, item_id, text))

        self.caps.indexer = Indexer()
        self.store = InMemoryConversationStore()
        self._turns = 0
        self.graph = build_assistant_graph(self.caps, InMemorySaver(), self.store)

    @property
    def model(self) -> Any:
        _binding, provider = self.caps.text._bound["chat"]
        return provider

    async def turn(self, text: str, conversation_id: str | None = None) -> tuple[dict, list[dict]]:
        """Run one turn; return the final state and the custom events the run manager would emit."""
        graph: Any = self.graph
        graph_input: dict[str, Any] = {"text": text}
        if conversation_id:
            graph_input["conversation_id"] = conversation_id
        config = {"configurable": {"thread_id": f"th-{self._turns}"}}
        self._turns += 1
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
