"""wasifyai-stt: speech to text (ADR-0043)."""

from wasifyai_platform_sdk import GraphRegistry


def register(registry: GraphRegistry) -> None:
    from wasifyai_stt.graphs.transcribe import build_transcribe
    from wasifyai_stt.index import TranscriptIndexSource
    from wasifyai_stt.routes import build_routes

    registry.register("wasifyai-stt", build_transcribe)
    registry.add_routes("wasifyai-stt", build_routes)
    registry.add_index_source("wasifyai-stt", TranscriptIndexSource)  # searchable in My creations
