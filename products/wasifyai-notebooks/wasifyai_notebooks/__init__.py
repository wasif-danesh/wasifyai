"""wasifyai-notebooks: a NotebookLM-style, source-grounded workspace (ADR-0065). A notebook holds
the person's documents; they are read, cut into passages, indexed on this computer, and questions
are answered from them with citations."""

from wasifyai_platform_sdk import GraphRegistry

PRODUCT_ID = "wasifyai-notebooks"


def register(registry: GraphRegistry) -> None:
    from wasifyai_notebooks.graph import build_notebook_chat
    from wasifyai_notebooks.index import notebook_index_source
    from wasifyai_notebooks.routes import build_routes

    registry.register(PRODUCT_ID, build_notebook_chat)  # one grounded turn (ADR-0065 decision 10)
    registry.add_routes(PRODUCT_ID, build_routes)
    # a notebook is a creation: searchable in My creations (ADR-0041, ADR-0065 decision 12)
    registry.add_index_source(PRODUCT_ID, notebook_index_source)
