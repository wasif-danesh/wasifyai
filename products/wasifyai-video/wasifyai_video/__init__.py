"""wasifyai-video: text to video and image to video (ADR-0037)."""

from wasifyai_platform_sdk import GraphRegistry


def register(registry: GraphRegistry) -> None:
    from wasifyai_video.actions import actions, library_kinds
    from wasifyai_video.graphs.video import build_video
    from wasifyai_video.index import video_index_source
    from wasifyai_video.routes import build_routes

    registry.register("wasifyai-video", build_video)
    registry.add_routes("wasifyai-video", build_routes)
    registry.add_actions("wasifyai-video", actions)  # what agents may ask (ADR-0068)
    registry.add_library_kinds("wasifyai-video", library_kinds)
    registry.add_index_source("wasifyai-video", video_index_source)  # searchable in My creations
