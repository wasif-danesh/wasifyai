"""wasifyai-music: turns a song idea into lyrics, a track and cover art."""

from wasifyai_platform_sdk import GraphRegistry


def register(registry: GraphRegistry) -> None:
    from wasifyai_music.canary import moderation_check
    from wasifyai_music.graphs.song import build_song
    from wasifyai_music.index import SongIndexSource
    from wasifyai_music.routes import build_routes

    registry.register("wasifyai-music", build_song)
    registry.add_routes("wasifyai-music", build_routes)
    registry.add_index_source("wasifyai-music", SongIndexSource)  # searchable in My creations
    # whatever model serves the moderator must pass the canary first (ADR-0025)
    registry.add_check("wasifyai-music", "text.moderate", moderation_check)
