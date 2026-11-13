"""wasifyai-training: teach the app something of the person's own (ADR-0073, ADR-0076)."""

from wasifyai_platform_sdk import GraphRegistry


def build_none(caps, checkpointer):  # type: ignore[no-untyped-def]
    """The product has no conversation of its own: a graph that ends at once, so that the product is
    served (actions and routes check that) and a stray run finishes instead of failing."""
    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

    class State(TypedDict, total=False):
        status: str

    graph = StateGraph(State)
    graph.add_node("finish", lambda state: {"status": "done"})
    graph.add_edge(START, "finish")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)


def register(registry: GraphRegistry) -> None:
    from wasifyai_training.actions import actions, library_kinds
    from wasifyai_training.index import training_index_source
    from wasifyai_training.routes import build_routes

    registry.register("wasifyai-training", build_none)
    registry.add_routes("wasifyai-training", build_routes)
    registry.add_actions("wasifyai-training", actions)  # what agents may ask (ADR-0068)
    registry.add_library_kinds("wasifyai-training", library_kinds)
    registry.add_index_source(
        "wasifyai-training", training_index_source
    )  # searchable in My creations
