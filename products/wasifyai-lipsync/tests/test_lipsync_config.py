"""The product's config binds everything the graph asks for."""

from pathlib import Path

from wasifyai_platform_sdk import load_product_config

PRODUCTS = Path(__file__).resolve().parents[2]


def test_the_product_config_loads_and_binds_everything_the_graph_asks_for():
    cfg = load_product_config(PRODUCTS, "wasifyai-lipsync", environ={})
    assert cfg.capabilities["video.lipsync"].provider == "lipsync"  # MuseTalk, on its own server
    assert cfg.capabilities["speech.synthesize"].provider == "speech"
    assert cfg.capabilities["speech.transcribe"].provider == "speech"
    assert cfg.capabilities["text.moderate"].model == "moderator"
    assert cfg.capabilities["text.moderate_image"].model == "multimodal"
    assert cfg.quotas == {"lipsyncs_per_user_per_day": 3}
    assert cfg.uploads["image"].max_bytes == 10 * 1024 * 1024
    assert cfg.uploads["audio"].max_seconds == 300  # a song: at most 5 minutes
