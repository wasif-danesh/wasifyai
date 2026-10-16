"""The shipped catalogue: each descriptor agrees with the audio.cpp spec it was made from."""

import json

import pytest
import yaml
from voice_rig import PRODUCT, catalogue

SPECS = {p.stem: json.loads(p.read_text()) for p in (PRODUCT / "specs").glob("*.json")}
RAW = {m["id"]: m for m in yaml.safe_load((PRODUCT / "models.yaml").read_text())["models"]}


def test_every_model_has_a_descriptor_and_a_pinned_file():
    assert (
        set(catalogue())
        == set(RAW)
        == {
            "kokoro-82m",
            "qwen3-tts-0.6b-base",
            "qwen3-tts-1.7b-voicedesign",
            "voxcpm2",
            "parakeet-tdt-0.6b-v3",
            "ace-step-1.5-turbo",
            "stable-audio-3-small-music",
            "stable-audio-3-small-sfx",
        }
    )
    for m in RAW.values():
        for f in m["files"]:
            assert f["folder"] == "audio" and f["url"].startswith("https://huggingface.co/")
            assert "/resolve/" in f["url"] and "/main/" not in f["url"]  # pinned to a commit
            assert len(f["sha256"]) == 64 and f["size"] > 0


@pytest.mark.parametrize("model_id", sorted(RAW))
def test_a_descriptor_agrees_with_its_spec(model_id):
    m, raw = catalogue()[model_id], RAW[model_id]["voice"]
    if m.family not in SPECS:
        pytest.skip(f"the spec of {m.family} is not in specs/ yet")
    spec = SPECS[m.family]
    assert spec["family"] == m.family
    package = next((p for p in spec["packages"] if p["id"] == m.package), None)
    assert package is not None, "the descriptor names a package the spec does not have"
    # the package's file is the file we download
    assert package["files"][0].rsplit("/", 1)[-1] == RAW[model_id]["files"][0]["name"]
    wanted = {"speak": "tts", "transcribe": "asr", "clone": "clone", "design": "design"}
    needs = {wanted[t] for t in m.tasks if t in wanted}
    if "music" in m.tasks:  # a sound-effects model is the spec's `sfx`, the others its `music`
        needs.add("sfx" if set(m.music["modes"]) == {"sfx"} else "music")
    assert needs <= set(spec["tasks"])
    offered = set(spec["ui"].get("builtin_voices", []))
    assert {v.id for v in m.voices} <= offered
    if m.default_voice:
        assert m.default_voice == spec["ui"]["default_voice"]
    for o in m.options:
        declared = {r["name"] for r in spec.get("options", {}).get("request", [])}
        assert o.name in declared, f"{o.name} is not an option of {m.family}"
    assert raw["languages"], "languages are declared"


def test_recommendations_are_commercially_usable_and_unique_per_task():
    models = catalogue().values()
    for task in ("speak", "transcribe", "clone", "design", "music"):
        recommended = [m for m in models if task in m.recommended]
        assert len(recommended) == 1 and recommended[0].commercial_use == "yes"


def test_the_english_voices_are_the_twenty_eight_kokoro_ones():
    kokoro = catalogue()["kokoro-82m"]
    assert len(kokoro.voices) == 28
    assert {v.language for v in kokoro.voices} == {"en-us", "en-gb"}
    assert {v.gender for v in kokoro.voices} == {"female", "male"}
