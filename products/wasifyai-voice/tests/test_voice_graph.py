"""The Speak graph on a fake engine: refusals in words, errors with codes, the speech kept."""

import json
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

pytestmark = pytest.mark.usefixtures("use_backends")  # on SQLite and on Postgres

CTX = RunContext("t1", "wasifyai-voice", "u1", run_id="r1", thread_id="th1")


@pytest.fixture
def ctx():
    token = set_context(CTX)
    yield CTX
    reset_context(token)


def verdict(allowed: bool = True, category: str = "ok") -> str:
    return json.dumps({"allowed": allowed, "category": category, "reason": ""})


class Rig:
    """The graph over a fake engine. The safeguards are off unless asked for (the desktop's
    default); with them on, `moderate` and `picture` script the two moderators and `used` the
    day's count."""

    def __init__(
        self,
        tmp_path,
        engine: FakeEngine | None = None,
        turns=None,
        safeguards: bool = False,
        moderate: list[str] | None = None,
        picture: list[str] | None = None,
        quotas: dict[str, int] | None = None,
        used: int = 0,
    ):
        d = tmp_path / "products" / "wasifyai-voice"
        d.mkdir(parents=True)
        caps = {"text.chat": {"provider": "fake", "defaults": {"turns": turns}}} if turns else {}
        caps["text.moderate"] = {
            "provider": "fake",
            "defaults": {"replies": moderate or [verdict()]},
        }
        caps["text.moderate_image"] = {
            "provider": "fake",
            "inputs": ["text", "image"],
            "defaults": {"replies": picture or [verdict()]},
        }
        (d / "product.yaml").write_text(
            yaml.safe_dump({"id": "wasifyai-voice", "capabilities": caps, "quotas": quotas or {}})
        )
        config = load_product_config(tmp_path / "products", "wasifyai-voice")
        self.usage = InMemoryUsageRecorder()

        async def on() -> bool:
            return safeguards

        self.caps = build_capabilities(
            config,
            ProviderDeps(products_dir=tmp_path / "products", usage=self.usage, safeguards=on),
        )

        async def used_today(meter: Any) -> int:
            return used

        self.caps.extras["quota_used"] = used_today
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
    def moderator_prompts(self) -> list[Any]:  # what the words moderator was asked to judge
        return self.caps.text._bound["moderate"][1].prompts  # pyright: ignore[reportAttributeAccessIssue]

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
    assert [(u.kind, u.unit) for u in rig.usage.events][-1] == ("voice.music", "tracks")
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
    assert [(u.kind, u.unit) for u in rig.usage.events][-1] == ("voice.music", "tracks")


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


# ---- audio tools (V4) -----------------------------------------------------------------------


async def library_track(rig, track_id="song", title="Summer", rate=44100, channels=2, seconds=2.0):
    from voice_rig import wav

    key = f"music/{track_id}.wav"
    await rig.caps.storage.put(key, wav(seconds, rate, channels), "audio/wav")
    return store_for(rig.state).add_track(
        "t1", "u1", title=title, mode="song", description="pop", lyrics="", instrumental=False,
        model_id="ace-step-1.5-turbo", options={}, seed=1, seconds=seconds, sample_rate=rate,
        audio_key=key, load_s=0, elapsed_s=1, track_id=track_id,
    )  # fmt: skip


async def test_a_song_is_split_into_stems_that_are_kept_and_remember_their_source(tmp_path, ctx):
    rig = Rig(tmp_path)
    await library_track(rig)
    final, events = await rig.run(task="separate", source_track="song")
    assert final["status"] == "done"
    names = [t["stem"] for t in final["tracks"]]
    assert names == ["drums", "bass", "other", "vocals"]
    model_id, req, seen = rig.engine.separated[0]
    assert model_id == "htdemucs" and seen == (44100, 2) and req.source_seconds == 2.0
    store = store_for(rig.state)
    saved = store.get_track("t1", "u1", final["tracks"][3]["track_id"])
    assert saved["mode"] == "stem" and saved["parent_id"] == "song"
    assert saved["title"] == "Summer (vocals)" and saved["edit"]["stem"] == "vocals"
    assert len(store.list_tracks("t1", "u1")) == 5 and len(rig.indexed) == 4
    assert not list((store.root / "tmp").glob("*.wav"))  # the scratch copy is gone
    assert [e["node"] for e in events if e["type"] == "node"] == ["check_request", "separate"]
    assert [u.unit for u in rig.usage.events].count("tracks") == 4


async def test_only_the_parts_asked_for_are_kept_and_an_unknown_part_is_refused(tmp_path, ctx):
    rig = Rig(tmp_path)
    await library_track(rig)
    final, _ = await rig.run(task="separate", source_track="song", stems=["vocals"])
    assert [t["stem"] for t in final["tracks"]] == ["vocals"]
    assert len(store_for(rig.state).list_tracks("t1", "u1")) == 2
    final, _ = await rig.run(task="separate", source_track="song", stems=["tuba"])
    assert final["refusal"]["code"] == "unknown_stem" and "tuba" in final["refusal"]["message"]
    final, _ = await rig.run(
        task="separate", source_track="song", model="mel-band-roformer", stems=["drums"]
    )
    assert final["refusal"]["code"] == "unknown_stem"


async def test_a_speech_can_be_a_source_and_a_missing_source_is_refused(tmp_path, ctx):
    from voice_rig import wav

    rig = Rig(tmp_path)
    assert rig.caps.storage is not None
    await rig.caps.storage.put("speech/s1.wav", wav(2.0, 44100, 2), "audio/wav")
    store_for(rig.state).add_speech(
        "t1", "u1", text="Hello world", model_id="kokoro-82m", voice=None, options={},
        seconds=2.0, sample_rate=44100, audio_key="speech/s1.wav", load_s=0, elapsed_s=0.3,
        speech_id="s1",
    )  # fmt: skip
    final, _ = await rig.run(task="separate", source_speech="s1", model="htdemucs-6stems")
    assert final["status"] == "done" and len(final["tracks"]) == 6
    saved = store_for(rig.state).get_track("t1", "u1", final["track_id"])
    assert saved["parent_id"] is None and saved["title"] == "Hello world (drums)"
    for graph_input in ({"source_track": "nope"}, {"source_speech": "nope"}, {}):
        final, _ = await rig.run(task="separate", **graph_input)
        assert final["refusal"]["code"] == "unknown_source"


async def a_clone(rig, name="Ann", kind="clone"):
    store = store_for(rig.state)
    v = store.add_voice(
        "t1", "u1", kind=kind, name=name, description="warm" if kind == "design" else "",
        reference_key="voice/v1.wav" if kind == "clone" else None, reference_text="hi there",
        reference_seconds=4.0, consent={"basis": "own", "statement": "mine"}, voice_id="v1",
    )  # fmt: skip
    if kind == "clone":
        from voice_rig import wav

        path = store.reference_path("v1")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(wav(4.0, 24000))
    return v


async def test_a_recording_is_changed_to_a_saved_voice_and_the_consent_travels(tmp_path, ctx):
    rig = Rig(tmp_path)
    await library_track(rig, rate=22050, channels=1)
    await a_clone(rig)
    final, _ = await rig.run(
        task="convert", source_track="song", saved_voice="v1", model="tone-color-vc", seed=5
    )
    assert final["status"] == "done" and final["title"] == "Summer (as Ann)"
    model_id, req, source_facts, ref_facts = rig.engine.converted[0]
    assert model_id == "tone-color-vc" and req.seed == 5
    assert source_facts == (22050, 1) and ref_facts == (22050, 1)
    saved = store_for(rig.state).get_track("t1", "u1", final["track_id"])
    assert saved["mode"] == "converted" and saved["parent_id"] == "song"
    assert saved["edit"] == {
        "action": "convert", "voice_id": "v1", "voice": "Ann", "consent": "own", "from": "track",
    }  # fmt: skip
    assert rig.indexed[-1][0] == "track" and "Ann" in rig.indexed[-1][2]


async def test_a_voice_without_a_recording_or_a_missing_voice_cannot_be_the_target(tmp_path, ctx):
    rig = Rig(tmp_path)
    await library_track(rig, rate=22050, channels=1)
    final, _ = await rig.run(task="convert", source_track="song", saved_voice="ghost")
    assert final["refusal"]["code"] == "unknown_voice"
    await a_clone(rig, kind="design")
    final, _ = await rig.run(task="convert", source_track="song", saved_voice="v1")
    assert final["refusal"]["code"] == "voice_needs_recording"
    assert rig.engine.converted == []


async def test_a_clone_whose_recording_is_gone_is_refused_in_a_convert(tmp_path, ctx):
    rig = Rig(tmp_path)
    await library_track(rig, rate=22050, channels=1)
    await a_clone(rig)
    store_for(rig.state).reference_path("v1").unlink()
    final, _ = await rig.run(
        task="convert", source_track="song", saved_voice="v1", model="tone-color-vc"
    )
    assert final["refusal"]["code"] == "reference_missing"


async def test_words_in_a_recording_are_changed_and_the_result_is_kept(tmp_path, ctx):
    rig = Rig(tmp_path)
    await library_track(rig, rate=24000, channels=1)
    final, events = await rig.run(
        task="speech_edit", source_track="song", model="dots-tts-edit",
        old_text="Hello brave world.", text="Hello small world.", seed=9,
    )  # fmt: skip
    assert final["status"] == "done" and final["title"] == "Summer (edited)"
    model_id, req, seen = rig.engine.speech_edited[0]
    assert model_id == "dots-tts-edit" and seen == (24000, 1) and req.seed == 9
    assert req.instruction == 'Hello <sub targ="small">brave</sub> world.'
    saved = store_for(rig.state).get_track("t1", "u1", final["track_id"])
    assert saved["mode"] == "edited" and saved["description"] == "Hello small world."
    assert saved["edit"]["instruction"] == req.instruction and saved["parent_id"] == "song"
    assert [e["node"] for e in events if e["type"] == "node"] == ["check_request", "speech_edit"]


async def test_an_edit_with_nothing_to_change_or_no_model_chosen_is_refused(tmp_path, ctx):
    from wasifyai_platform_sdk import RunError

    rig = Rig(tmp_path)
    await library_track(rig, rate=24000, channels=1)
    final, _ = await rig.run(
        task="speech_edit", source_track="song", model="dots-tts-edit",
        old_text="Same words", text="same words",
    )  # fmt: skip
    assert final["refusal"]["code"] == "no_change" and rig.engine.speech_edited == []
    # the only editing model is not commercially clear, so it is never chosen for the person
    with pytest.raises(RunError) as e:
        await rig.run(task="speech_edit", source_track="song", old_text="a b", text="a c")
    assert e.value.code == "no_model"


async def test_engine_failures_in_the_tools_end_the_run_with_a_code(tmp_path, ctx):
    from wasifyai_platform_sdk import RunError, VoiceEngineError

    rig = Rig(tmp_path)
    await library_track(rig)
    rig.engine.fail_with = VoiceEngineError("busy", "The speech runtime is busy.")
    with pytest.raises(RunError) as e:
        await rig.run(task="separate", source_track="song")
    assert e.value.code == "busy" and e.value.retryable
    assert not list((store_for(rig.state).root / "tmp").glob("*.wav"))


# ---- lip sync (V5) --------------------------------------------------------------------------


def png_bytes() -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 150, 120)).save(out, "PNG")
    return out.getvalue()


async def a_picture(rig, picture_id="pic1"):
    key = f"lipsync/pictures/{picture_id}.png"
    await rig.caps.storage.put(key, png_bytes(), "image/png")
    return store_for(rig.state).add_picture(
        "t1", "u1", key=key, width=64, height=48, picture_id=picture_id
    )


async def test_a_picture_and_a_recording_make_a_clip_that_remembers_what_was_agreed(tmp_path, ctx):
    rig = Rig(tmp_path)
    await library_track(rig, rate=16000, channels=1, seconds=3.0)
    await a_picture(rig)
    final, events = await rig.run(
        task="lipsync", picture="pic1", source_track="song", picture_basis="drawn",
        voice_basis="own", title="Hello",
    )  # fmt: skip
    assert final["status"] == "done" and final["title"] == "Hello" and final["seconds"] == 3.0
    model_id, req, voice_facts, _ = rig.engine.lipsynced[0]
    assert model_id == "musetalk-v15" and voice_facts == (16000, 1)
    assert req.fps == 25 and req.mark == "AI-generated" and req.consent == {
        "picture": "drawn", "voice": "own",
    }  # fmt: skip
    store = store_for(rig.state)
    clip = store.get_clip("t1", "u1", final["clip_id"])
    assert clip["consent"]["picture"] == "drawn" and clip["consent"]["mark"] == "AI-generated"
    assert "drawing" in clip["consent"]["picture_statement"]
    assert clip["voice"] == {"kind": "track", "id": "song"} and clip["picture_key"].endswith(
        "pic1.png"
    )
    assert (clip["width"], clip["height"], clip["fps"]) == (640, 480, 25)
    with pytest.raises(Exception, match="picture not found"):
        store.get_picture("t1", "u1", "pic1")  # it belongs to the clip now
    assert await rig.files.exists(object_key("t1", "wasifyai-voice", "u1", clip["video_key"]))
    assert await rig.files.exists(object_key("t1", "wasifyai-voice", "u1", clip["picture_key"]))
    assert [i[0] for i in rig.indexed] == ["lipsync"]
    assert [e["node"] for e in events if e["type"] == "node"] == ["check_request", "lipsync"]
    assert [(u.kind, u.unit) for u in rig.usage.events][-1] == ("voice.lipsync", "clips")
    assert not list((store.root / "tmp").glob("*"))  # the scratch copies are gone


async def test_a_script_is_spoken_here_so_the_voice_is_never_somebody_elses(tmp_path, ctx):
    rig = Rig(tmp_path)
    await a_picture(rig)
    final, events = await rig.run(
        task="lipsync", picture="pic1", text="Welcome to the show, everybody.",
        picture_basis="own", voice_basis="permission",
    )  # fmt: skip
    assert final["status"] == "done"
    assert rig.engine.spoken[0][1] == "Welcome to the show, everybody."
    store = store_for(rig.state)
    clip = store.get_clip("t1", "u1", final["clip_id"])
    assert clip["consent"]["voice"] == "generated"  # whatever was ticked, words are made here
    assert clip["script"] == "Welcome to the show, everybody."
    assert clip["voice"]["kind"] == "speech"
    assert store.get_speech("t1", "u1", clip["voice"]["id"])["text"].startswith("Welcome")
    assert {i[0] for i in rig.indexed} == {"speech", "lipsync"}
    assert [e["node"] for e in events if e["type"] == "node"] == [
        "check_request", "speak", "lipsync",
    ]  # fmt: skip


@pytest.mark.parametrize(
    "extra, code",
    [
        ({}, "consent_required"),
        ({"picture_basis": "drawn"}, "consent_required"),
        ({"picture_basis": "stolen", "voice_basis": "own"}, "consent_required"),
        ({"picture_basis": "drawn", "voice_basis": "generated"}, "consent_required"),
    ],
)
async def test_without_the_persons_word_about_the_picture_and_voice_nothing_is_made(
    tmp_path, ctx, extra, code
):
    rig = Rig(tmp_path)
    await library_track(rig, rate=16000, channels=1)
    await a_picture(rig)
    final, _ = await rig.run(task="lipsync", picture="pic1", source_track="song", **extra)
    # a track was not made from words here, so "generated" is not something to claim for it
    assert final["refusal"]["code"] == code and rig.engine.lipsynced == []


async def test_a_missing_picture_or_voice_or_a_voice_that_is_too_long_is_refused(tmp_path, ctx):
    rig = Rig(tmp_path)
    final, _ = await rig.run(
        task="lipsync", picture="nope", source_track="song", picture_basis="drawn",
        voice_basis="own",
    )  # fmt: skip
    assert final["refusal"]["code"] == "unknown_picture"
    await a_picture(rig)
    final, _ = await rig.run(
        task="lipsync", picture="pic1", source_track="nope", picture_basis="drawn",
        voice_basis="own",
    )  # fmt: skip
    assert final["refusal"]["code"] == "unknown_source"
    final, _ = await rig.run(
        task="lipsync", picture="pic1", picture_basis="drawn", voice_basis="own"
    )  # no voice at all
    assert final["refusal"]["code"] == "unknown_source"
    assert rig.engine.lipsynced == []


async def test_the_engine_failing_ends_the_run_and_keeps_the_picture_for_another_try(tmp_path, ctx):
    from wasifyai_platform_sdk import RunError, VoiceEngineError

    rig = Rig(tmp_path)
    await library_track(rig, rate=16000, channels=1)
    await a_picture(rig)
    rig.engine.fail_with = VoiceEngineError("no_face", "No clear face was found in the picture.")
    with pytest.raises(RunError) as e:
        await rig.run(
            task="lipsync", picture="pic1", source_track="song", picture_basis="drawn",
            voice_basis="own",
        )  # fmt: skip
    assert e.value.code == "no_face"
    assert store_for(rig.state).get_picture("t1", "u1", "pic1")["id"] == "pic1"
    assert not list((store_for(rig.state).root / "tmp").glob("*"))
