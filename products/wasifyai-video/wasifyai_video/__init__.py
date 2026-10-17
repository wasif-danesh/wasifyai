"""wasifyai-video: text to video and image to video (ADR-0037)."""

from wasifyai_platform_sdk import GraphRegistry


def register(registry: GraphRegistry) -> None:
    from wasifyai_video.canary import moderation_check, picture_check
    from wasifyai_video.graphs.video import build_video
    from wasifyai_video.index import video_index_source
    from wasifyai_video.routes import build_routes

    registry.register("wasifyai-video", build_video)
    registry.add_routes("wasifyai-video", build_routes)
    registry.add_index_source("wasifyai-video", video_index_source)  # searchable in My creations
    # whatever models serve the guardrail must pass these first (ADR-0025)
    registry.add_check("wasifyai-video", "text.moderate", moderation_check)
    registry.add_check("wasifyai-video", "text.moderate_image", picture_check)
