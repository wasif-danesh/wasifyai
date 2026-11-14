"""wasifyai-code: the coding agent's product (ADR-0101 to ADR-0105).

    place       the interface to where a session runs, and a pretended place for tests
    client      the one real place: this computer (OpenHands' Agent Server in its sandbox). The
                only file that knows the Agent Server's API
    events      the Agent Server's events in the place's own words
    runtime     the sessions in flight, their turns and the relay inside the engine
    actions     code.session.start, code.session.send, code.session.stop
    routes      /products/wasifyai-code/code/...
    index       sessions in My creations search
    store       the rows
    checks, loop, checkpoints, schedules    library code for the stages that edit, run and
                schedule; not used by a session that only reads

Stage C1b wires in a session that only reads. `docs/desktop/coding.md` says what is built."""

from typing import Any

PRODUCT_ID = "wasifyai-code"


def build_none(caps: Any, checkpointer: Any) -> Any:
    """The product has no graph of its own: a coding session is driven by the coding engine, not
    by a graph run. A graph that ends at once, so that the product is served (actions and routes
    check that) and a stray run finishes instead of failing."""
    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

    class State(TypedDict, total=False):
        status: str

    graph = StateGraph(State)
    graph.add_node("finish", lambda state: {"status": "done"})
    graph.add_edge(START, "finish")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)


def register(registry: Any) -> None:
    from wasifyai_code.actions import actions
    from wasifyai_code.index import code_index_source
    from wasifyai_code.routes import build_routes

    registry.register(PRODUCT_ID, build_none)
    registry.add_routes(PRODUCT_ID, build_routes)
    registry.add_actions(PRODUCT_ID, actions)  # what agents may ask (ADR-0068)
    registry.add_index_source(PRODUCT_ID, code_index_source)  # searchable in My creations
