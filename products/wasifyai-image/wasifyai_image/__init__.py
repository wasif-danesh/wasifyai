"""wasifyai-image: text to image and image to image (ADR-0036)."""

from wasifyai_platform_sdk import GraphRegistry


def register(registry: GraphRegistry) -> None:
    from wasifyai_image.actions import actions, library_kinds
    from wasifyai_image.graphs.image import build_image
    from wasifyai_image.index import image_index_source
    from wasifyai_image.routes import build_routes

    registry.register("wasifyai-image", build_image)
    registry.add_routes("wasifyai-image", build_routes)
    registry.add_actions(
        "wasifyai-image", actions
    )  # what the assistant and agents may ask (ADR-0068)
    registry.add_library_kinds("wasifyai-image", library_kinds)
    registry.add_index_source("wasifyai-image", image_index_source)  # searchable in My creations
