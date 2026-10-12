"""wasifyai-image: text to image and image to image (ADR-0036)."""

from wasifyai_platform_sdk import GraphRegistry


def register(registry: GraphRegistry) -> None:
    from wasifyai_image.canary import moderation_check, picture_check
    from wasifyai_image.graphs.image import build_image
    from wasifyai_image.index import ImageIndexSource
    from wasifyai_image.routes import build_routes

    registry.register("wasifyai-image", build_image)
    registry.add_routes("wasifyai-image", build_routes)
    registry.add_index_source("wasifyai-image", ImageIndexSource)  # searchable in My creations
    # whatever models serve the guardrail must pass these first (ADR-0025)
    registry.add_check("wasifyai-image", "text.moderate", moderation_check)
    registry.add_check("wasifyai-image", "text.moderate_image", picture_check)
