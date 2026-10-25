"""Music made by the image engine's ComfyUI (V3b), on a stand-in sidecar and client."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from wasifyai_api import audio_runtime as ar
from wasifyai_api.comfy_music import ComfyMusic
from wasifyai_platform_sdk import VoiceEngineError, check_music
from wasifyai_platform_sdk.workflows import Workflow

from tests.fake_audiocpp import wav_bytes
from tests.test_audio_runtime import ALL, Models, make_engine

WORKFLOWS = Path(__file__).parents[3] / "products" / "wasifyai-voice" / "workflows"
CHECKPOINT = "ace_step_1.5_turbo_aio.safetensors"


class FakeClient:
    def __init__(self, url):
        self.url, self.graphs, self.interrupted = url, [], 0
        self.fail: Exception | None = None
        self.block: asyncio.Event | None = None

    async def run(self, graph, client_id, on_progress, timeout_s):
        self.graphs.append((graph, timeout_s))
        if self.block is not None:
            await self.block.wait()
        if self.fail:
            raise self.fail
        return {
            "8": {"audio": [{"filename": "ComfyUI_temp_x.flac", "subfolder": "", "type": "temp"}]}
        }

    @staticmethod
    def pick(outputs, node, kind):
        f = outputs[node]["audio"][0]
        return SimpleNamespace(filename=f["filename"], subfolder="", type="temp")

    async def fetch(self, f):
        return wav_bytes(2.0, 48000, 2)

    async def interrupt(self):
        self.interrupted += 1


class FakeSidecar:
    def __init__(self, installed=True, missing=()):
        self.installed, self.missing, self.started = installed, list(missing), 0

    def missing_models(self, graph):
        return self.missing

    async def ensure_running(self):
        self.started += 1
        return "http://127.0.0.1:1"


def comfy_engine(tmp_path, monkeypatch, sidecar, present=ALL | {CHECKPOINT}):
    eng, server = make_engine(tmp_path, monkeypatch, present=present)
    client = FakeClient("http://127.0.0.1:1")
    eng.comfy = ComfyMusic(WORKFLOWS, lambda: sidecar, lambda url: client)
    return eng, server, client


def test_the_workflow_and_every_option_of_the_descriptor_agree():
    wf = Workflow.load(WORKFLOWS, "ace-step-1.5-turbo")
    assert wf.problems() == []
    model = Models(Path("/nonexistent"), set()).catalogue["ace-step-1.5-turbo-comfyui"].voice
    assert model is not None
    for o in model.options:
        assert o.name in wf.map.inputs, o.name
    assert wf.graph[wf.map.outputs["audio"].node]["class_type"] == "PreviewAudio"
    assert wf.map.models == [f"checkpoints/{CHECKPOINT}"]


def test_a_comfyui_model_is_ready_only_when_the_image_engine_and_its_file_are_there(
    tmp_path, monkeypatch
):
    def state(sidecar, present):
        eng, _, _ = comfy_engine(tmp_path, monkeypatch, sidecar, present)
        got = {m["id"]: m for m in eng.models("music")}
        return got["ace-step-1.5-turbo-comfyui"]

    ready = state(FakeSidecar(), ALL | {CHECKPOINT})
    assert ready["state"] == "ready" and ready["engine"] == "comfyui" and ready["recommended"] == []
    assert state(FakeSidecar(installed=False), ALL | {CHECKPOINT})["state"] == "needs_runtime"
    gone = state(FakeSidecar(), ALL)
    assert gone["state"] == "can_install" and gone["bytes_missing"] == 10025478736
    # audio.cpp being there or not does not decide it
    eng, _, _ = comfy_engine(tmp_path, monkeypatch, FakeSidecar(), ALL | {CHECKPOINT})
    eng2, _ = make_engine(tmp_path, monkeypatch, present=ALL | {CHECKPOINT}, install=False)
    eng2.comfy = eng.comfy
    got = {m["id"]: m["state"] for m in eng2.models("music")}
    assert (
        got["ace-step-1.5-turbo-comfyui"] == "ready"
        and got["ace-step-1.5-turbo"] == "needs_runtime"
    )


def test_resolve_says_what_a_comfyui_model_needs(tmp_path, monkeypatch):
    eng, _, _ = comfy_engine(tmp_path, monkeypatch, FakeSidecar(installed=False))
    with pytest.raises(VoiceEngineError) as e:
        eng.resolve("music", "ace-step-1.5-turbo-comfyui")
    assert e.value.code == "runtime_missing" and "image generation" in e.value.message
    eng, _, _ = comfy_engine(tmp_path, monkeypatch, FakeSidecar(), present=ALL)
    with pytest.raises(VoiceEngineError) as e:
        eng.resolve("music", "ace-step-1.5-turbo-comfyui")
    assert e.value.code == "model_missing" and "Model hub" in e.value.message
    eng, _, _ = comfy_engine(tmp_path, monkeypatch, FakeSidecar())
    assert eng.resolve("music", None).id == "ace-step-1.5-turbo"


async def test_a_song_is_made_by_filling_the_workflow_from_the_descriptor(tmp_path, monkeypatch):
    sidecar = FakeSidecar()
    eng, server, client = comfy_engine(tmp_path, monkeypatch, sidecar)
    try:
        model = eng.resolve("music", "ace-step-1.5-turbo-comfyui")
        req = check_music(
            model, "song", "pop, upbeat", "[verse]\nla la", False, 20,
            {"bpm": 100, "keyscale": "G major", "language": "es", "timesignature": "3"}, 5,
        )  # fmt: skip
        out = await eng.music(model, req)
        graph, timeout = client.graphs[0]
        enc = graph["3"]["inputs"]
        assert (enc["tags"], enc["lyrics"], enc["duration"], enc["seed"]) == (
            "pop, upbeat", "[verse]\nla la", 20.0, 5,
        )  # fmt: skip
        assert (enc["bpm"], enc["keyscale"], enc["language"], enc["timesignature"]) == (
            100, "G major", "es", "3",
        )  # fmt: skip
        assert graph["5"]["inputs"]["seconds"] == 20.0 and graph["6"]["inputs"]["seed"] == 5
        assert out.wav[:4] == b"RIFF" and out.sample_rate == 48000 and out.seed == 5
        assert out.seconds == pytest.approx(2.0, abs=0.01) and timeout >= 600
        assert sidecar.started == 1 and not server.running  # audio.cpp was not started
        # an instrumental names itself, and a seed is chosen when none is asked for
        req = check_music(model, "song", "calm piano", None, True, 15, None, None)
        out = await eng.music(model, req)
        assert client.graphs[1][0]["3"]["inputs"]["lyrics"] == "[Instrumental]"
        assert out.seed is not None and client.graphs[1][0]["3"]["inputs"]["seed"] == out.seed
    finally:
        await server.close()


async def test_comfyui_failures_are_told_in_words(tmp_path, monkeypatch):
    from wasifyai_media_worker.comfy import ComfyError

    eng, server, client = comfy_engine(tmp_path, monkeypatch, FakeSidecar())
    try:
        model = eng.resolve("music", "ace-step-1.5-turbo-comfyui")
        req = check_music(model, "song", "pop", None, True, 10, None, 1)
        client.fail = ComfyError("execution_failed", "The generation failed on the GPU worker.")
        with pytest.raises(VoiceEngineError) as e:
            await eng.music(model, req)
        assert e.value.code == "engine_failed" and "GPU worker" in e.value.message
        client.fail = ComfyError("connection_lost", "Lost the connection.")
        with pytest.raises(VoiceEngineError) as e:
            await eng.music(model, req)
        assert e.value.code == "engine_stopped"
        client.fail = TimeoutError()
        with pytest.raises(VoiceEngineError) as e:
            await eng.music(model, req)
        assert e.value.code == "engine_failed" and "took too long" in e.value.message
        eng.comfy = ComfyMusic(
            WORKFLOWS, lambda: FakeSidecar(missing=[CHECKPOINT]), lambda u: client
        )
        with pytest.raises(VoiceEngineError) as e:
            await eng.music(model, req)
        assert e.value.code == "model_missing"
    finally:
        await server.close()


async def test_cancelling_asks_comfyui_to_stop(tmp_path, monkeypatch):
    eng, server, client = comfy_engine(tmp_path, monkeypatch, FakeSidecar())
    client.block = asyncio.Event()
    try:
        model = eng.resolve("music", "ace-step-1.5-turbo-comfyui")
        req = check_music(model, "song", "pop", None, True, 10, None, 1)
        task = asyncio.create_task(eng.music(model, req))
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client.interrupted == 1
    finally:
        await server.close()


async def test_the_image_slot_is_held_while_comfyui_works(tmp_path, monkeypatch):
    held = []

    class Slot:
        def hold(self, owner):
            held.append(owner)

            class Ctx:
                async def __aenter__(_self):  # noqa: N805
                    return None

                async def __aexit__(_self, *a):  # noqa: N805
                    return None

            return Ctx()

    eng, server, _ = comfy_engine(tmp_path, monkeypatch, FakeSidecar())
    eng.slot = Slot()
    try:
        model = eng.resolve("music", "ace-step-1.5-turbo-comfyui")
        await eng.music(model, check_music(model, "song", "pop", None, True, 10, None, 1))
        assert held == ["image"]
    finally:
        await server.close()


async def test_an_engine_with_no_image_engine_says_so(tmp_path, monkeypatch):
    eng, server, _ = comfy_engine(tmp_path, monkeypatch, FakeSidecar(installed=False))
    try:
        model = ar.AudioEngine._entries(eng)[0].voice  # any model; the call is what is tested
        del model
        comfy_model = Models(tmp_path, set()).catalogue["ace-step-1.5-turbo-comfyui"].voice
        assert comfy_model is not None
        req = check_music(comfy_model, "song", "pop", None, True, 10, None, 1)
        with pytest.raises(VoiceEngineError) as e:
            await eng.music(comfy_model, req)
        assert e.value.code == "runtime_missing"
    finally:
        await server.close()
