"""wasifyai-assistant: the chat-first assistant (ADR-0057). A conversation with a model that can use
the other products as tools: make an image, find an earlier creation."""

from wasifyai_platform_sdk import GraphRegistry

PRODUCT_ID = "wasifyai-assistant"


def register(registry: GraphRegistry) -> None:
    from wasifyai_assistant.graph import build_assistant
    from wasifyai_assistant.index import conversation_index_source
    from wasifyai_assistant.routes import build_routes

    registry.register(PRODUCT_ID, build_assistant)
    registry.add_routes(PRODUCT_ID, build_routes)
    # conversations are creations: searchable in My creations (ADR-0041, ADR-0057 decision 3)
    registry.add_index_source(PRODUCT_ID, conversation_index_source)
