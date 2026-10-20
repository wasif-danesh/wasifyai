"""wasifyai-model3d: make a 3D model from a picture, or from words through a picture (ADR-0080)."""

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
    from wasifyai_model3d.actions import actions, library_kinds
    from wasifyai_model3d.index import model3d_index_source
    from wasifyai_model3d.routes import build_routes

    registry.register("wasifyai-model3d", build_none)
    registry.add_routes("wasifyai-model3d", build_routes)
    registry.add_actions("wasifyai-model3d", actions)  # what agents may ask (ADR-0068)
    registry.add_library_kinds("wasifyai-model3d", library_kinds)
    registry.add_index_source(
        "wasifyai-model3d", model3d_index_source
    )  # searchable in My creations
