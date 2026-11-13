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
            "ace-step-1.5-turbo-comfyui",
            "stable-audio-3-small-music",
            "stable-audio-3-small-sfx",
            "htdemucs",
            "htdemucs-6stems",
            "mel-band-roformer",
            "tone-color-vc",
            "meanvc2",
            "dots-tts-edit",
            "musetalk-v15",
            "indic-parler-tts",
            "indic-conformer-600m",
        }
    )
    for m in RAW.values():
        for f in m["files"]:
            folders = {"comfyui": "checkpoints", "sidecar": "lipsync", "indic": "indic"}
            assert f["folder"] == folders.get(m["voice"]["engine"], "audio")
            assert f["url"].startswith("https://")
            if f["url"].startswith("https://huggingface.co/"):
                assert "/resolve/" in f["url"] and "/main/" not in f["url"]  # pinned to a commit
            else:  # the two small face models and a torchvision file, each pinned by SHA-256
                assert m["voice"]["engine"] == "sidecar"
            assert len(f["sha256"]) == 64 and f["size"] > 0


@pytest.mark.parametrize("model_id", sorted(RAW))
def test_a_descriptor_agrees_with_its_spec(model_id):
    m, raw = catalogue()[model_id], RAW[model_id]["voice"]
    if m.engine != "audiocpp":
        pytest.skip(f"{model_id} runs on {m.engine}: its workflow map is tested with the engine")
    if m.family not in SPECS:
        pytest.skip(f"the spec of {m.family} is not in specs/ yet")
    spec = SPECS[m.family]
    assert spec["family"] == m.family
    package = next((p for p in spec["packages"] if p["id"] == m.package), None)
    assert package is not None, "the descriptor names a package the spec does not have"
    # the package's file is the file we download
    assert package["files"][0].rsplit("/", 1)[-1] == RAW[model_id]["files"][0]["name"]
    wanted = {
        "speak": "tts", "transcribe": "asr", "clone": "clone", "design": "design",
        "separate": "sep", "convert": "vc", "edit": "tts",
    }  # fmt: skip
    needs = {wanted[t] for t in m.tasks if t in wanted}
    if "music" in m.tasks:  # a sound-effects model is the spec's `sfx`, the others its `music`
        needs.add("sfx" if set(m.music["modes"]) == {"sfx"} else "music")
    assert needs <= set(spec["tasks"])
    offered = set(spec["ui"].get("builtin_voices", []))
    assert {v.id for v in m.voices} <= offered
    if m.default_voice:
        assert m.default_voice == spec["ui"]["default_voice"]
    declared = {r["name"] for r in spec.get("options", {}).get("request", [])}
    for o in m.options:
        if "options" not in spec:
            # a spec with no option list (ACE-Step's): its options were found by running the
            # runtime, which accepts and silently ignores unknown ones (docs/phase2-voice-plan.md)
            continue
        assert o.name in declared, f"{o.name} is not an option of {m.family}"
    assert raw["languages"] or spec.get("languages") == ["language_agnostic"], (
        "languages are declared"
    )


def test_recommendations_are_unique_per_task():
    models = catalogue().values()
    for task in ("speak", "transcribe", "clone", "design", "music", "separate", "convert"):
        recommended = [m for m in models if task in m.recommended]
        assert len(recommended) == 1


def test_kokoro_lists_only_the_voices_that_passed_their_language_check():
    # docs/spikes/voice-languages-l0.md: 28 English voices, and the other languages' voices that a
    # transcription model wrote back word for word; Japanese (the GGUF lacks its dictionary),
    # Chinese (not scored) and pf_dora (a stray word) are not listed
    from wasifyai_platform_sdk import languages

    kokoro = catalogue()["kokoro-82m"]
    english = [v for v in kokoro.voices if v.language in {"en-us", "en-gb"}]
    assert len(english) == 28 and len(kokoro.voices) == 40
    by_language = {languages.base(v.language) for v in kokoro.voices}
    assert by_language == {"en", "es", "fr", "hi", "it", "pt"}
    assert by_language == languages.spoken(kokoro.languages)
    assert not {"pf_dora", "jf_alpha", "zf_xiaobei"} & {v.id for v in kokoro.voices}
    assert {v.gender for v in kokoro.voices} == {"female", "male"}
    assert languages.voices_for(kokoro, "hi") == ["hf_alpha", "hf_beta", "hm_omega", "hm_psi"]
