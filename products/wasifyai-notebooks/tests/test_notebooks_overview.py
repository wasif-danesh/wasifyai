"""The audio overview given its voices: the hosts' turns spoken by the person's speech model."""

import asyncio
import io
import wave

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from test_notebooks_routes import make_app
from wasifyai_notebooks import overview
from wasifyai_notebooks.routes import build_routes
from wasifyai_platform_sdk import (
    EngineServices,
    Identity,
    RouteDeps,
    SpeechResult,
    VoiceEngineError,
    parse_voice_model,
)


def model(**over):
    raw = {
        "engine": "audiocpp", "family": "kokoro_tts", "package": "p", "server_task": "tts",
        "tasks": ["speak"], "recommended": ["speak"], "languages": ["en-us"], "sample_rate": 24000,
        "commercial_use": "yes", "licence_evidence": "https://x.example/m",
        "reviewed": "2026-10-16",
        "voices": [
            {"id": "af_heart", "label": "Heart", "language": "en-us", "gender": "female"},
            {"id": "af_nova", "label": "Nova", "language": "en-us", "gender": "female"},
            {"id": "am_adam", "label": "Adam", "language": "en-us", "gender": "male"},
        ],
        "default_voice": "af_heart",
    }  # fmt: skip
    raw.update(over)
    return parse_voice_model("kokoro-82m", "Kokoro 82M", "Apache-2.0", raw)


def wav(seconds: float, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x01" * int(rate * seconds))
    return buf.getvalue()


def seconds_of(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes() / w.getframerate()


class Engine:
    def __init__(self, voiced=True):
        self.m = model() if voiced else model(voices=[], default_voice=None)
        self.spoken: list[tuple[str, str | None]] = []
        self.fail_at: int | None = None
        self.gate: asyncio.Event | None = None

    def resolve(self, task, model_id):
        if model_id and model_id != "kokoro-82m":
            raise VoiceEngineError("unknown_model", "That model is not one this app knows.")
        return self.m

    async def speak(self, m, text, voice, options):
        if self.gate:
            await self.gate.wait()
        if self.fail_at is not None and len(self.spoken) == self.fail_at:
            raise VoiceEngineError("out_of_memory", "No memory.")
        self.spoken.append((text, voice))
        return SpeechResult(wav(0.5), 24000, 0.5, m.id, voice, 0.0, 0.1)


def test_two_voices_are_chosen_that_tell_the_hosts_apart():
    m = model()
    assert overview.choose_voices(m, None) == {1: "af_heart", 2: "am_adam"}
    assert overview.choose_voices(m, {"2": "af_nova"}) == {1: "af_heart", 2: "af_nova"}
    with pytest.raises(overview.NotPossible, match="no voice 'zz'"):
        overview.choose_voices(m, {"1": "zz"})
    with pytest.raises(overview.NotPossible, match="no voices"):
        overview.choose_voices(model(voices=[], default_voice=None), None)


def test_pieces_are_joined_with_their_pauses_and_must_share_a_rate():
    out = overview.join_wavs([(wav(1.0), 0.5), (wav(1.0), 0.0)])
    assert seconds_of(out) == pytest.approx(2.5, abs=0.01)
    with pytest.raises(ValueError, match="one rate"):
        overview.join_wavs([(wav(1.0), 0.0), (wav(1.0, 16000), 0.0)])
    with pytest.raises(ValueError):
        overview.join_wavs([])


@pytest.fixture
def api(tmp_path):
    app, runtime, comps, reader = make_app(tmp_path)
    engine = Engine()
    state = EngineServices(audio=engine)

    async def identity(x_user: str = Header("u1"), x_tenant: str = Header("t1")) -> Identity:
        return Identity(x_tenant, x_user)

    app2 = FastAPI()
    app2.include_router(
        build_routes(RouteDeps(state, identity), runtime), prefix="/products/wasifyai-notebooks"
    )
    with TestClient(app2) as c:
        c.base_url = c.base_url.join("/products/wasifyai-notebooks/")
        yield c, runtime, engine, state


def ready_overview(runtime, turns=4):
    nb = runtime.store.create_notebook("t1", "u1", "N")
    art = runtime.store.create_artifact("t1", "u1", nb["id"], fmt="audio", prompt="", source_ids=[])
    script = [
        {"speaker": 1 + i % 2, "host": ("Alex", "Sam")[i % 2], "text": f"Turn number {i}."}
        for i in range(turns)
    ]
    runtime.store.finish_artifact(
        "t1", "u1", nb["id"], art["id"], title="Overview", body="# x",
        data={"title": "Overview", "hosts": ["Alex", "Sam"], "turns": script, "audio": False},
        file_name="overview.md", file_mime="text/markdown",
    )  # fmt: skip
    return nb["id"], art["id"]


def wait_state(c, nid, aid, want, timeout=10):
    import time

    end = time.time() + timeout
    s: dict = {}
    while time.time() < end:
        s = c.get(f"notebooks/{nid}/artifacts/{aid}/voices").json()
        if s["state"] == want:
            return s
        time.sleep(0.05)
    raise AssertionError(s)


def test_an_overview_is_spoken_turn_by_turn_and_kept_with_the_output(api):
    c, runtime, engine, _ = api
    nid, aid = ready_overview(runtime)
    assert c.get(f"notebooks/{nid}/artifacts/{aid}/voices").json()["state"] == "idle"
    assert c.get(f"notebooks/{nid}/artifacts/{aid}/audio").status_code == 404
    r = c.post(f"notebooks/{nid}/artifacts/{aid}/voices", json={})
    assert r.status_code == 202 and r.json()["total"] == 4
    done = wait_state(c, nid, aid, "ready")
    assert done["done"] == 4
    assert engine.spoken == [
        ("Turn number 0.", "af_heart"), ("Turn number 1.", "am_adam"),
        ("Turn number 2.", "af_heart"), ("Turn number 3.", "am_adam"),
    ]  # fmt: skip
    audio = c.get(f"notebooks/{nid}/artifacts/{aid}/audio")
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"
    assert seconds_of(audio.content) > 4 * 0.5  # four turns plus the pauses
    data = c.get(f"notebooks/{nid}/artifacts/{aid}").json()["data"]
    assert data["audio"] is True and data["audio_voices"] == {"1": "af_heart", "2": "am_adam"}
    assert data["audio_model"] == "kokoro-82m" and data["turns"][0]["text"] == "Turn number 0."


def test_a_failure_in_the_middle_says_why_and_keeps_no_half_audio(api):
    c, runtime, engine, _ = api
    nid, aid = ready_overview(runtime)
    engine.fail_at = 2
    c.post(f"notebooks/{nid}/artifacts/{aid}/voices", json={})
    s = wait_state(c, nid, aid, "failed")
    assert s["message"] == "No memory." and s["done"] == 2
    assert c.get(f"notebooks/{nid}/artifacts/{aid}/audio").status_code == 404
    assert c.get(f"notebooks/{nid}/artifacts/{aid}").json()["data"]["audio"] is False
    engine.fail_at = None
    engine.spoken.clear()
    c.post(f"notebooks/{nid}/artifacts/{aid}/voices", json={"voices": {"2": "af_nova"}})
    wait_state(c, nid, aid, "ready")
    assert {v for _, v in engine.spoken} == {"af_heart", "af_nova"}


def test_it_will_not_start_twice_or_for_what_is_not_an_overview(api):
    c, runtime, engine, _ = api
    nid, aid = ready_overview(runtime)
    engine.gate = asyncio.Event()
    assert c.post(f"notebooks/{nid}/artifacts/{aid}/voices", json={}).status_code == 202
    again = c.post(f"notebooks/{nid}/artifacts/{aid}/voices", json={})
    assert again.status_code == 409 and "already" in again.json()["detail"]
    report = runtime.store.create_artifact("t1", "u1", nid, fmt="report", prompt="", source_ids=[])
    r = c.post(f"notebooks/{nid}/artifacts/{report['id']}/voices", json={})
    assert r.status_code == 409 and "audio overview" in r.json()["detail"]


def test_a_model_without_voices_or_an_unknown_one_is_refused_before_anything_starts(api):
    c, runtime, engine, state = api
    nid, aid = ready_overview(runtime)
    r = c.post(f"notebooks/{nid}/artifacts/{aid}/voices", json={"model": "ghost"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "unknown_model"
    state.audio = Engine(voiced=False)
    r = c.post(f"notebooks/{nid}/artifacts/{aid}/voices", json={})
    assert r.status_code == 409 and "no voices" in r.json()["detail"]
    state.audio = None
    assert c.post(f"notebooks/{nid}/artifacts/{aid}/voices", json={}).status_code == 503
