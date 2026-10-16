"""The Speak graph on a fake engine: refusals in words, errors with codes, the speech kept."""

from typing import Any

import pytest
import yaml
from langgraph.checkpoint.memory import InMemorySaver
from voice_rig import FakeEngine, app_state
from wasifyai_platform_sdk import (
    InMemoryUsageRecorder,
    LocalFileStorage,
    ProviderDeps,
    RunContext,
    RunError,
    ScopedStorage,
    build_capabilities,
    load_product_config,
    reset_context,
    set_context,
)
from wasifyai_platform_sdk.storage import object_key
from wasifyai_voice.graph import build_speak
from wasifyai_voice.runtime import store_for

CTX = RunContext("t1", "wasifyai-voice", "u1", run_id="r1", thread_id="th1")


@pytest.fixture
def ctx():
    token = set_context(CTX)
    yield CTX
    reset_context(token)


class Rig:
    def __init__(self, tmp_path, engine: FakeEngine | None = None, turns=None):
        d = tmp_path / "products" / "wasifyai-voice"
        d.mkdir(parents=True)
        caps = {"text.chat": {"provider": "fake", "defaults": {"turns": turns}}} if turns else {}
        (d / "product.yaml").write_text(
            yaml.safe_dump({"id": "wasifyai-voice", "capabilities": caps})
        )
        config = load_product_config(tmp_path / "products", "wasifyai-voice")
        self.usage = InMemoryUsageRecorder()
        self.caps = build_capabilities(
            config, ProviderDeps(products_dir=tmp_path / "products", usage=self.usage)
        )
        self.engine = engine or FakeEngine()
        self.state = app_state(tmp_path, self.engine)
        self.caps.extras["app_state"] = self.state
        self.files = LocalFileStorage(
            tmp_path / "files", "http://127.0.0.1:1", "secret-secret-secret"
        )
        self.caps.storage = ScopedStorage(self.files)
        self.indexed: list[tuple[str, str, str]] = []

        class Indexer:
            async def index(_self, kind: str, item_id: str, text: str) -> None:  # noqa: N805
                self.indexed.append((kind, item_id, text))

        self.caps.indexer = Indexer()
        self.graph: Any = build_speak(self.caps, InMemorySaver())
        self._n = 0

    @property
    def model(self) -> Any:  # the scripted text provider keeps what it was sent in `chats`
        _binding, provider = self.caps.text._bound["chat"]
        return provider

    async def run(self, **graph_input) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        config = {"configurable": {"thread_id": f"th-{self._n}"}}
        self._n += 1
        final: dict[str, Any] = {}
        events: list[dict[str, Any]] = []
        async for mode, chunk in self.graph.astream(
            graph_input, config, stream_mode=["custom", "values"]
        ):
            if mode == "custom":
                events.append(chunk)
            else:
                final = chunk
        return final, events


async def test_a_speech_is_made_kept_indexed_and_counted(tmp_path, ctx):
    rig = Rig(tmp_path)
    final, events = await rig.run(
        text="  Hello there, world.  ", voice="am_adam", options={"speed": 1.2}
    )
    assert final["status"] == "done" and final["seconds"] > 0.4
    assert final["audio_url"].startswith("http://127.0.0.1:1/files/")
    assert rig.engine.spoken == [("kokoro-82m", "Hello there, world.", "am_adam", {"speed": 1.2})]
    saved = store_for(rig.state).get_speech("t1", "u1", final["speech_id"])
    assert saved["model_id"] == "kokoro-82m" and saved["voice"] == "am_adam"
    key = object_key("t1", "wasifyai-voice", "u1", saved["audio_key"])
    assert saved["audio_key"] == f"speech/{final['speech_id']}.wav"
    assert await rig.files.exists(key)
    assert rig.indexed == [("speech", final["speech_id"], "Hello there, world.")]
    assert [e["node"] for e in events if e["type"] == "node"] == ["check_request", "speak"]
    assert [(u.kind, u.unit) for u in rig.usage.events][-1] == ("voice.speech", "speeches")


async def test_the_default_voice_and_the_named_model_are_used(tmp_path, ctx):
    rig = Rig(tmp_path)
    await rig.run(text="Hi")
    assert rig.engine.spoken[0][2] == "af_heart"
    await rig.run(text="Hi again", model="voxcpm2")
    assert rig.engine.spoken[1][0] == "voxcpm2" and rig.engine.spoken[1][2] is None


@pytest.mark.parametrize(
    "graph_input, code",
    [
        ({"text": "   "}, "empty_text"),
        ({"text": "hi", "voice": "nope"}, "unknown_voice"),
        ({"text": "hi", "options": {"bogus": 1}}, "unknown_option"),
        ({"text": "hi", "options": {"speed": "fast"}}, "bad_option"),
        ({"text": "hi", "model": "voxcpm2", "voice": "af_heart"}, "unknown_voice"),
    ],
)
async def test_a_request_the_model_cannot_take_is_refused_before_it_is_loaded(
    tmp_path, ctx, graph_input, code
):
    rig = Rig(tmp_path)
    final, _ = await rig.run(**graph_input)
    assert final["status"] == "refused" and final["refusal"]["code"] == code
    assert final["refusal"]["message"] and rig.engine.spoken == []
    assert store_for(rig.state).list_speeches("t1", "u1") == []


@pytest.mark.parametrize(
    "model, ready, code",
    [("ghost", None, "unknown_model"), (None, set(), "model_missing"),
     ("parakeet-tdt-0.6b-v3", None, "unknown_model")],
)  # fmt: skip
async def test_a_model_that_is_not_there_ends_the_run_with_a_code(
    tmp_path, ctx, model, ready, code
):
    rig = Rig(tmp_path, FakeEngine(ready))
    with pytest.raises(RunError) as e:
        await rig.run(text="hello", **({"model": model} if model else {}))
    assert e.value.code == code


async def test_an_engine_failure_ends_the_run_and_a_busy_one_may_be_retried(tmp_path, ctx):
    from wasifyai_platform_sdk import VoiceEngineError

    rig = Rig(tmp_path)
    rig.engine.fail_with = VoiceEngineError("busy", "Busy.")
    with pytest.raises(RunError) as e:
        await rig.run(text="hello")
    assert e.value.code == "busy" and e.value.retryable
    rig.engine.fail_with = VoiceEngineError("out_of_memory", "No memory.")
    with pytest.raises(RunError) as e:
        await rig.run(text="hello")
    assert e.value.code == "out_of_memory" and not e.value.retryable
    assert store_for(rig.state).list_speeches("t1", "u1") == []


async def test_without_an_engine_the_run_says_so(tmp_path, ctx):
    rig = Rig(tmp_path)
    rig.state.audio = None
    with pytest.raises(RunError) as e:
        await rig.run(text="hello")
    assert e.value.code == "not_available"


def saved_design(rig, description="a deep, calm man"):
    return store_for(rig.state).add_voice(
        "t1", "u1", kind="design", name="Calm", description=description
    )


def saved_clone(rig, text="the words said", seconds=5.0):
    store = store_for(rig.state)
    v = store.add_voice(
        "t1", "u1", kind="clone", name="Me", reference_key="voice/x.wav", reference_text=text,
        reference_seconds=seconds, consent={"basis": "own"}, voice_id="c1",
    )  # fmt: skip
    path = store.reference_path("c1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFFxxxx")
    return v


async def test_a_designed_voice_speaks_with_the_model_that_designs(tmp_path, ctx):
    rig = Rig(tmp_path)
    v = saved_design(rig)
    final, _ = await rig.run(text="Hello", saved_voice=v["id"])
    assert final["status"] == "done"
    assert rig.engine.designed == [("qwen3-tts-1.7b-voicedesign", "Hello", "a deep, calm man", {})]
    saved = store_for(rig.state).get_speech("t1", "u1", final["speech_id"])
    assert (saved["mode"], saved["saved_voice_id"], saved["voice"]) == ("design", v["id"], None)
    await rig.run(text="Hello", saved_voice=v["id"], model="voxcpm2")
    assert rig.engine.designed[1][0] == "voxcpm2"


async def test_a_cloned_voice_speaks_from_its_recording_and_the_words_it_says(tmp_path, ctx):
    rig = Rig(tmp_path)
    v = saved_clone(rig)
    final, _ = await rig.run(text="Say this", saved_voice=v["id"])
    assert final["status"] == "done"
    assert rig.engine.cloned == [
        ("qwen3-tts-0.6b-base", "Say this", "c1.wav", "the words said", {})
    ]
    saved = store_for(rig.state).get_speech("t1", "u1", final["speech_id"])
    assert (saved["mode"], saved["saved_voice_id"]) == ("clone", "c1")


@pytest.mark.parametrize(
    "build, graph_input, code",
    [
        (lambda r: saved_clone(r, text=""), {"text": "Hi"}, "reference_text_required"),
        (lambda r: saved_clone(r, seconds=1.0), {"text": "Hi"}, "reference_length"),
        (lambda r: saved_design(r), {"text": " "}, "empty_text"),
        (lambda r: saved_design(r), {"text": "Hi", "options": {"speed": 1}}, "unknown_option"),
        (lambda r: None, {"text": "Hi", "saved_voice": "nope"}, "unknown_voice"),
    ],
)
async def test_a_saved_voice_that_cannot_be_used_is_refused_in_words(
    tmp_path, ctx, build, graph_input, code
):
    rig = Rig(tmp_path)
    v = build(rig)
    if v:
        graph_input = {**graph_input, "saved_voice": v["id"]}
    final, _ = await rig.run(**graph_input)
    assert final["status"] == "refused" and final["refusal"]["code"] == code
    assert not (rig.engine.designed or rig.engine.cloned or rig.engine.spoken)


async def test_a_clone_whose_recording_file_is_gone_is_refused(tmp_path, ctx):
    rig = Rig(tmp_path)
    v = saved_clone(rig)
    store_for(rig.state).reference_path(v["id"]).unlink()
    final, _ = await rig.run(text="Hi", saved_voice=v["id"])
    assert final["refusal"]["code"] == "reference_missing"


async def test_another_persons_saved_voice_is_not_found(tmp_path, ctx):
    rig = Rig(tmp_path)
    other = store_for(rig.state).add_voice(
        "t1", "someone", kind="design", name="x", description="a man"
    )
    final, _ = await rig.run(text="Hi", saved_voice=other["id"])
    assert final["refusal"]["code"] == "unknown_voice"


async def test_a_song_is_made_kept_titled_indexed_and_counted(tmp_path, ctx):
    rig = Rig(tmp_path)
    final, events = await rig.run(
        task="music",
        text="Pop, upbeat, female vocals, summer",
        lyrics="la la la",
        duration=45,
        seed=11,
    )
    assert final["status"] == "done" and final["title"] == "Pop, upbeat, female vocals, summer"
    model_id, req = rig.engine.made[0]
    assert model_id == "ace-step-1.5-turbo" and (req.mode, req.duration, req.seed) == (
        "song",
        45.0,
        11,
    )
    assert req.lyrics == "la la la" and not req.instrumental
    saved = store_for(rig.state).get_track("t1", "u1", final["track_id"])
    assert saved["seed"] == 11 and saved["audio_key"] == f"music/{final['track_id']}.wav"
    assert rig.indexed[-1][0] == "track" and "la la la" in rig.indexed[-1][2]
    assert [e["node"] for e in events if e["type"] == "node"] == ["check_request", "make_music"]
    assert [(u.kind, u.unit) for u in rig.usage.events][-1] == ("voice.track", "tracks")
    key = object_key("t1", "wasifyai-voice", "u1", saved["audio_key"])
    assert await rig.files.exists(key)


async def test_the_named_music_model_and_mode_are_used(tmp_path, ctx):
    rig = Rig(tmp_path)
    await rig.run(
        task="music", text="rain on a tin roof", music_mode="sfx", model="stable-audio-3-small-sfx"
    )
    model_id, req = rig.engine.made[0]
    assert model_id == "stable-audio-3-small-sfx" and req.mode == "sfx" and req.duration == 8.0


@pytest.mark.parametrize(
    "graph_input, code",
    [
        ({"text": "po", "lyrics": "x"}, "description_too_short"),
        (
            {"text": "a calm piece", "model": "stable-audio-3-small-music", "lyrics": "words"},
            "no_lyrics",
        ),
        ({"text": "a calm piece", "music_mode": "sfx"}, "wrong_mode"),
        (
            {"text": "a calm piece", "lyrics": "words", "instrumental": True},
            "lyrics_and_instrumental",
        ),
    ],
)
async def test_a_music_request_the_model_cannot_take_is_refused_before_it_is_loaded(
    tmp_path, ctx, graph_input, code
):
    rig = Rig(tmp_path)
    final, _ = await rig.run(task="music", **graph_input)
    assert final["status"] == "refused" and final["refusal"]["code"] == code
    assert rig.engine.made == [] and store_for(rig.state).list_tracks("t1", "u1") == []


async def test_music_errors_end_the_run_with_a_code(tmp_path, ctx):
    from wasifyai_platform_sdk import VoiceEngineError

    rig = Rig(tmp_path, FakeEngine(set()))
    with pytest.raises(RunError) as e:
        await rig.run(task="music", text="a calm piece")
    assert e.value.code == "model_missing"
    rig2 = Rig(tmp_path / "b")
    rig2.engine.fail_with = VoiceEngineError("out_of_memory", "No memory.")
    with pytest.raises(RunError) as e:
        await rig2.run(task="music", text="a calm piece")
    assert e.value.code == "out_of_memory"


def a_track(rig, seconds=40.0, title="Summer", lyrics="la la"):
    store = store_for(rig.state)
    return store.add_track(
        "t1", "u1", title=title, mode="song", description="pop, upbeat", lyrics=lyrics,
        instrumental=False, model_id="ace-step-1.5-turbo", options={}, seed=3, seconds=seconds,
        sample_rate=24000, audio_key="music/src.wav", load_s=0, elapsed_s=1, track_id="src",
    )  # fmt: skip


async def put_source(rig):
    from voice_rig import wav

    await rig.caps.storage.put("music/src.wav", wav(1.0), "audio/wav")


async def test_a_track_is_changed_and_kept_as_a_new_one_that_remembers_its_source(tmp_path, ctx):
    rig = Rig(tmp_path)
    src = a_track(rig)
    await put_source(rig)
    final, events = await rig.run(
        task="music_edit", source_track=src["id"], edit_action="repaint", text="a drum fill",
        edit_ranges=[[10, 15]], strength=0.5, seed=21,
    )  # fmt: skip
    assert final["status"] == "done" and final["title"] == "Summer (repaint)"
    model_id, req, clip = rig.engine.edited[0]
    assert model_id == "ace-step-1.5-turbo" and req.ranges == ((10.0, 15.0),) and req.seed == 21
    saved = store_for(rig.state).get_track("t1", "u1", final["track_id"])
    assert saved["parent_id"] == "src" and saved["mode"] == "edit" and saved["lyrics"] == "la la"
    assert saved["edit"] == {
        "action": "repaint", "ranges": [[10.0, 15.0]], "strength": 0.5, "extend_s": None,
    }  # fmt: skip
    assert not (store_for(rig.state).root / "tmp" / clip).exists()  # the scratch copy is gone
    assert [e["node"] for e in events if e["type"] == "node"] == ["edit_music"]
    assert [(u.kind, u.unit) for u in rig.usage.events][-1] == ("voice.track", "tracks")


@pytest.mark.parametrize(
    "graph_input, code",
    [
        ({"source_track": "nope", "edit_action": "cover", "text": "as jazz"}, "unknown_track"),
        ({"source_track": "src", "edit_action": "cover", "text": ""}, "empty_text"),
        ({"source_track": "src", "edit_action": "repaint", "text": "fix it"}, "ranges_required"),
        (
            {
                "source_track": "src",
                "edit_action": "cover",
                "text": "as jazz",
                "edit_ranges": [[1, 5]],
            },
            "no_ranges",
        ),
        (
            {
                "source_track": "src",
                "edit_action": "inpaint",
                "text": "fix it",
                "edit_ranges": [[1, 5]],
            },
            "wrong_action",
        ),
    ],
)
async def test_an_edit_that_cannot_be_done_is_refused_before_anything_runs(
    tmp_path, ctx, graph_input, code
):
    rig = Rig(tmp_path)
    a_track(rig)
    await put_source(rig)
    final, _ = await rig.run(task="music_edit", **graph_input)
    assert final["refusal"]["code"] == code and rig.engine.edited == []
    assert [t["id"] for t in store_for(rig.state).list_tracks("t1", "u1")] == ["src"]


async def test_another_persons_music_cannot_be_changed(tmp_path, ctx):
    rig = Rig(tmp_path)
    store_for(rig.state).add_track(
        "t1", "someone", title="x", mode="song", description="pop", lyrics="", instrumental=False,
        model_id="m", options={}, seed=1, seconds=10, sample_rate=1, audio_key="k", load_s=0,
        elapsed_s=0, track_id="theirs",
    )  # fmt: skip
    final, _ = await rig.run(
        task="music_edit", source_track="theirs", edit_action="cover", text="as jazz"
    )
    assert final["refusal"]["code"] == "unknown_track"


LYRICS = (
    "Here are the lyrics:\n[Verse]\nSunshine on the water\nSummer in the air\n[Chorus]\n"
    "Sing along with me\nLa la la la"
)


async def test_lyrics_are_written_cleaned_and_streamed(tmp_path, ctx):
    rig = Rig(tmp_path, turns=[{"text": LYRICS}])
    final, events = await rig.run(
        task="lyrics", text="a summer day by the sea", style="upbeat pop", duration=60
    )
    assert final["status"] == "done"
    assert final["lyrics"] == (
        "[verse]\nSunshine on the water\nSummer in the air\n"
        "[chorus]\nSing along with me\nLa la la la"
    )
    assert "".join(e["text"] for e in events if e["type"] == "token").startswith("Here")
    sent = rig.model.chats[0]["messages"]
    assert "about 15 lines" in sent[0]["content"] and "upbeat pop" in sent[1]["content"]


async def test_too_short_lyrics_are_asked_for_again_once_then_given_up(tmp_path, ctx):
    rig = Rig(tmp_path, turns=[{"text": "Sure!"}, {"text": "[verse]\none\ntwo\nthree\nfour"}])
    final, _ = await rig.run(task="lyrics", text="a short song")
    assert final["lyrics"].count("\n") == 4
    again = Rig(tmp_path / "b", turns=[{"text": "No."}])
    with pytest.raises(RunError) as e:
        await again.run(task="lyrics", text="a short song")
    assert e.value.code == "lyrics_failed" and e.value.retryable


async def test_lyrics_need_an_idea(tmp_path, ctx):
    rig = Rig(tmp_path, turns=[{"text": LYRICS}])
    final, _ = await rig.run(task="lyrics", text="hi")
    assert final["refusal"]["code"] == "description_too_short"
    assert rig.model.chats == []
