"""wasifyai-lipsync: a character picture and a voice become a talking or singing clip (ADR-0044)."""

from wasifyai_platform_sdk import GraphRegistry


def register(registry: GraphRegistry) -> None:
    from wasifyai_lipsync.canary import picture_check, words_check
    from wasifyai_lipsync.graphs.lipsync import build_lipsync
    from wasifyai_lipsync.index import LipSyncIndexSource
    from wasifyai_lipsync.routes import build_routes

    registry.register("wasifyai-lipsync", build_lipsync)
    registry.add_routes("wasifyai-lipsync", build_routes)
    registry.add_index_source("wasifyai-lipsync", LipSyncIndexSource)  # searchable in My creations
    # whatever models serve the guardrails must pass these first (ADR-0025)
    registry.add_check("wasifyai-lipsync", "text.moderate", words_check)
    registry.add_check("wasifyai-lipsync", "text.moderate_image", picture_check)
