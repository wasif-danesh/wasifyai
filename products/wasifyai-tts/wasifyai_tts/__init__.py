"""wasifyai-tts: text to speech (ADR-0042)."""

from wasifyai_platform_sdk import GraphRegistry


def register(registry: GraphRegistry) -> None:
    from wasifyai_tts.canary import moderation_check
    from wasifyai_tts.graphs.speech import build_speech
    from wasifyai_tts.index import SpeechIndexSource
    from wasifyai_tts.routes import build_routes

    registry.register("wasifyai-tts", build_speech)
    registry.add_routes("wasifyai-tts", build_routes)
    registry.add_index_source("wasifyai-tts", SpeechIndexSource)  # searchable in My creations
    # whatever model serves the moderator must pass the canary first (ADR-0025)
    registry.add_check("wasifyai-tts", "text.moderate", moderation_check)
