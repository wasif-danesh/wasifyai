"""wasifyai-voice: speak and transcribe on this computer, with the model the person picks
(ADR-0066).
The engine owns the speech runtime and the model descriptors; this product keeps what was made."""

from wasifyai_platform_sdk import GraphRegistry

PRODUCT_ID = "wasifyai-voice"


def register(registry: GraphRegistry) -> None:
    from wasifyai_voice.canary import picture_check, words_check
    from wasifyai_voice.graph import build_speak
    from wasifyai_voice.index import voice_index_source
    from wasifyai_voice.routes import build_routes

    registry.register(PRODUCT_ID, build_speak)  # one speech per run (ADR-0066)
    registry.add_routes(PRODUCT_ID, build_routes)
    # speeches and transcripts are creations: searchable in My creations (ADR-0041)
    registry.add_index_source(PRODUCT_ID, voice_index_source)
    # whatever models serve the guardrails must pass these first (ADR-0025)
    registry.add_check(PRODUCT_ID, "text.moderate", words_check)
    registry.add_check(PRODUCT_ID, "text.moderate_image", picture_check)
