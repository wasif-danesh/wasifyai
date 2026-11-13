"""The web runs no model of its own (ADR-0099; ADR-0100, CP11): no default alias may use Ollama,
and the Helm chart has no Ollama or ComfyUI to run one."""

from pathlib import Path

import pytest
import yaml
from wasifyai_api.model_access import DEFAULTS_FILE

CHART = Path(__file__).resolve().parents[3] / "deploy" / "helm" / "wasifyai"


def test_no_default_alias_runs_on_ollama():
    for name, spec in yaml.safe_load(DEFAULTS_FILE.read_text())["aliases"].items():
        params = spec["litellm_params"]
        assert not params["model"].startswith(("ollama_chat/", "ollama/")), name
        assert "OLLAMA" not in params.get("api_base", ""), name


def test_the_chart_runs_no_ollama_and_no_comfyui():
    if not CHART.exists():
        pytest.skip("not running from the repository")
    values = yaml.safe_load((CHART / "values.yaml").read_text())
    assert "ollama" not in values and "comfyui" not in values
    assert values["mediaWorker"]["comfyuiMode"] == "cloud"
    assert not (CHART / "templates" / "ollama.yaml").exists()
    assert not (CHART / "templates" / "comfyui.yaml").exists()
