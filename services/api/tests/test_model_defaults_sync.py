"""The Helm chart's Ollama pull list must match the models the defaults use (ADR-0025)."""

from pathlib import Path

import pytest
import yaml
from wasifyai_api.model_access import DEFAULTS_FILE

VALUES = Path(__file__).resolve().parents[3] / "deploy" / "helm" / "wasifyai" / "values.yaml"


def test_helm_pulls_exactly_the_ollama_models_the_defaults_use():
    if not VALUES.exists():
        pytest.skip("not running from the repository")
    wanted = set()
    for spec in yaml.safe_load(DEFAULTS_FILE.read_text())["aliases"].values():
        model = spec["litellm_params"]["model"]
        for prefix in ("ollama_chat/", "ollama/"):
            if model.startswith(prefix):
                wanted.add(model.removeprefix(prefix))
        if model.startswith("openai/") and "OLLAMA" in spec["litellm_params"].get("api_base", ""):
            wanted.add(model.removeprefix("openai/"))
    pulled = set(yaml.safe_load(VALUES.read_text())["ollama"]["models"])
    assert pulled == wanted
