import json
from pathlib import Path

import pytest
from wasifyai_platform_sdk import ConfigError, load_product_config

REPO_PRODUCTS = Path(__file__).resolve().parents[3] / "products"


def test_loads_and_validates(products):
    cfg = load_product_config(products, "demo", environ={})
    assert cfg.capabilities["music.generate"].workflow == "tiny"
    assert cfg.quotas == {"songs_per_user_per_day": 10}
    assert cfg.settings["audio_format"] == "mp3"


def test_env_file_overlay_wins_over_base(products):
    (products / "demo" / "product.dev.yaml").write_text(
        "capabilities:\n"
        "  music.generate: { provider: comfyui, workflow: tiny, defaults: { duration_s: 10 } }\n"
    )
    cfg = load_product_config(products, "demo", env="dev", environ={})
    assert cfg.capabilities["music.generate"].defaults["duration_s"] == 10
    assert "text.chat" in cfg.capabilities  # untouched keys survive the merge


def test_env_var_overrides_win_over_files(products):
    env = {
        "DEMO__CAPABILITIES__MUSIC_GENERATE__DEFAULTS__DURATION_S": "15",
        "DEMO__QUOTAS__SONGS_PER_USER_PER_DAY": "3",
    }
    cfg = load_product_config(products, "demo", environ=env)
    assert cfg.capabilities["music.generate"].defaults["duration_s"] == 15
    assert cfg.quotas["songs_per_user_per_day"] == 3


def test_reports_every_problem_at_once(products):
    (products / "demo" / "product.yaml").write_text(
        """
id: demo
capabilities:
  text.chat: { provider: litellm }
  bogus: { provider: fake }
  music.generate: { provider: comfyui, workflow: missing }
"""
    )
    with pytest.raises(ConfigError) as e:
        load_product_config(products, "demo", environ={})
    text = str(e.value)
    assert "requires 'model'" in text and "invalid capability name" in text


def test_missing_workflow_file_is_reported(products):
    (products / "demo" / "product.yaml").write_text(
        "id: demo\ncapabilities:\n  music.generate: { provider: comfyui, workflow: missing }\n"
    )
    with pytest.raises(ConfigError, match="workflow map not found"):
        load_product_config(products, "demo", environ={})


def test_mapped_node_must_exist_in_workflow(products):
    (products / "demo" / "workflows" / "tiny.json").write_text(json.dumps({"3": {"inputs": {}}}))
    with pytest.raises(ConfigError, match="missing node '14'"):
        load_product_config(products, "demo", environ={})


def test_id_must_match_folder(products):
    (products / "demo" / "product.yaml").write_text("id: other\n")
    with pytest.raises(ConfigError, match="does not match folder"):
        load_product_config(products, "demo", environ={})


def test_unknown_keys_are_rejected(products):
    (products / "demo" / "product.yaml").write_text("id: demo\naudio_format: mp3\n")
    with pytest.raises(ConfigError, match="audio_format"):
        load_product_config(products, "demo", environ={})


@pytest.mark.parametrize("product", ["hello", "media-demo", "wasifyai-music"])
def test_committed_product_configs_are_valid(product):
    """Every shipped product loads, its workflows and map files exist, and every mapped node ID
    is present in the workflow JSON."""
    load_product_config(REPO_PRODUCTS, product, environ={}, check_files=True)
