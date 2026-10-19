"""The voice product's actions (ADR-0068) through the one executor, on the product's real graph, its
real store and a fake speech engine: each action gives the documented result, a sentence a model
can use, and leaves what it made in the library."""

import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from test_voice_graph import CTX, LYRICS, Rig, ctx, library_track  # noqa: F401
from wasifyai_platform_sdk import RouteDeps, RunError
from wasifyai_platform_sdk.actions import (
    ActionExecutor,
    ActionRegistry,
    LibraryItem,
    LibraryKind,
    builtin_actions,
)
from wasifyai_platform_sdk.actions.testing import FakeActionHost
from wasifyai_platform_sdk.identity import Identity
from wasifyai_voice.actions import actions, library_kinds
from wasifyai_voice.runtime import store_for

ME = Identity("t1", "u1")
needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="dubbing mixes with ffmpeg"
)


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 150, 120)).save(out, "PNG")
    return out.getvalue()


class GraphHost(FakeActionHost):
    """The engine's side: a child run is the product's real graph on the fake engine."""

    def __init__(self, rig: Rig, deps: Any):
        super().__init__(deps)
        self.rig = rig

    async def run_product(self, product_id, graph_input):  # type: ignore[override]
        self.runs.append((product_id, graph_input))
        try:
            final, events = await self.rig.run(**graph_input)
        except RunError as e:
            yield {"event": "error", "code": e.code, "message": e.message}
            return
        for ev in events:
            if ev.get("type") == "job_progress":
                yield {"event": "job_progress", **ev.get("data", {})}
        yield {"event": "done", "outputs": final}


def a_picture_kind() -> LibraryKind:
    """What the image product declares: enough for the actions that need a picture."""

    async def list_(c, n):
        return [LibraryItem(kind="image", id="img1", title="a fox")]

    async def get(c, i):
        return LibraryItem(kind="image", id=i, title="a fox") if i == "img1" else None

    async def read(c, i):
        return png() if i == "img1" else None

    async def delete(c, i):
        return False

    return LibraryKind("image", "wasifyai-image", "picture", list_, get, delete, read=read)


class Harness:
    def __init__(self, tmp_path, turns=None):
        self.rig = Rig(tmp_path, turns=turns)
        state: Any = self.rig.state
        state.storage = self.rig.caps.storage
        state.creation_index = None
        state.export_dir = tmp_path / "exports"
        deps = RouteDeps(state, lambda: ME)
        self.host = GraphHost(self.rig, deps)
        self.ex = ActionExecutor(
            ActionRegistry([*builtin_actions(), *actions()]),
            self.host,
            library={**{k.kind: k for k in library_kinds()}, "image": a_picture_kind()},
        )
        self.engine = self.rig.engine
        self.store = store_for(self.rig.state)

    async def go(self, action_id: str, params: dict | None = None, **kw):
        return await self.ex.run_action(action_id, params or {}, "window", actor=ME, **kw)


LONG = "This sentence is long enough to be a recording a voice can be copied from. " * 2


async def a_speech(h: Harness, text="Hello there, world.") -> str:
    r = await h.go("speech.speak", {"text": text})
    assert r.ok, r.text
    return r.output["speech_id"]


# ---- speech -----------------------------------------------------------------------------------


async def test_a_speech_is_made_with_the_documented_result(tmp_path, ctx):  # noqa: F811
    h = Harness(tmp_path)
    r = await h.go("speech.speak", {"text": "Hello there, world.", "voice": "am_adam"})
    assert r.status == "ok" and set(r.output) == {"speech_id", "uri", "seconds"}
    assert r.output["uri"] == f"wasify://creation/speech/{r.output['speech_id']}"
    assert r.text.startswith("The speech was made (") and "saved to the library" in r.text
    assert h.engine.spoken[0][1:3] == ("Hello there, world.", "am_adam")
    assert h.host.runs == [
        ("wasifyai-voice", {"text": "Hello there, world.", "voice": "am_adam"})
    ]  # nothing but what was asked
    listed = await h.go("library.list", {"kind": "speech"})
    assert [i["id"] for i in listed.output["items"]] == [r.output["speech_id"]]


async def test_a_speech_the_model_cannot_say_is_refused_before_anything_runs(tmp_path, ctx):  # noqa: F811
    h = Harness(tmp_path)
    r = await h.go("speech.speak", {"text": "Hi", "voice": "no-such-voice"})
    assert r.status == "refused" and h.engine.spoken == [] and h.host.runs == []
    both = await h.go("speech.speak", {"text": "Hi", "voice": "am_adam", "saved_voice": "v"})
    assert (both.status, both.code) == ("refused", "invalid_input")
    ghost = await h.go("speech.speak", {"text": "Hi", "saved_voice": "ghost"})
    assert (ghost.status, ghost.code) == ("refused", "unknown_voice")
    long = await h.go("speech.speak", {"text": "x" * 6000})
    assert (long.status, long.code) == ("refused", "invalid_input")


async def test_a_recording_is_written_down_and_kept_as_a_transcript(tmp_path, ctx):  # noqa: F811
    h = Harness(tmp_path)
    sid = await a_speech(h)
    r = await h.go("speech.transcribe", {"source_kind": "speech", "source_id": sid})
    assert r.status == "ok" and r.output["text"] == "Hello there. Second sentence."
    assert r.output["uri"].startswith("wasify://creation/transcript/")
    assert (
        h.engine.transcribed
        and h.store.list_transcripts("t1", "u1")[0]["id"] == r.output["transcript_id"]
    )
    gone = await h.go("speech.transcribe", {"source_kind": "track", "source_id": "nope"})
    assert (gone.status, gone.code) == ("refused", "unknown_source")


# ---- voices -----------------------------------------------------------------------------------


async def test_voices_are_described_listed_cloned_and_used(tmp_path, ctx):  # noqa: F811
    h = Harness(tmp_path)
    d = await h.go("voice.design", {"name": "Calm", "description": "a calm woman, slow and warm"})
    assert d.ok and d.output["kind"] == "design"
    bad = await h.go("voice.design", {"name": "X", "description": "a (bad) voice"})
    assert (bad.status, bad.code) == ("refused", "bad_description")

    sid = await a_speech(h, LONG)
    params = {"source_kind": "speech", "source_id": sid, "name": "Me", "voice_is": "own"}
    needs = await h.go("voice.clone", params)  # a person's word comes first, every time
    assert needs.status == "needs_approval" and "my own voice" in needs.text
    assert h.store.list_voices("t1", "u1", "clone") == []
    cloned = await h.go("voice.clone", params, person_approved=True)
    assert cloned.ok and cloned.output["kind"] == "clone"
    saved = h.store.get_voice("t1", "u1", cloned.output["voice_id"])
    assert saved["consent"]["basis"] == "own"  # the record travels with the voice

    listed = await h.go("voice.list", {})
    assert {v["kind"] for v in listed.output["voices"]} == {"design", "clone"}
    only = await h.go("voice.list", {"kind": "clone"})
    assert [v["name"] for v in only.output["voices"]] == ["Me"]

    spoken = await h.go(
        "speech.speak", {"text": "In a designed voice.", "saved_voice": d.output["voice_id"]}
    )
    assert spoken.ok and h.engine.designed

    renamed = await h.go(
        "library.rename", {"kind": "voice", "id": cloned.output["voice_id"], "title": "Mine"}
    )
    assert renamed.ok and h.store.get_voice("t1", "u1", cloned.output["voice_id"])["name"] == "Mine"
    asked = await h.go("library.delete", {"kind": "voice", "id": cloned.output["voice_id"]})
    assert asked.status == "needs_approval"
    gone = await h.go(
        "library.delete", {"kind": "voice", "id": cloned.output["voice_id"]}, person_approved=True
    )
    assert gone.ok and not h.store.reference_path(cloned.output["voice_id"]).exists()


async def test_a_voice_is_changed_and_words_are_edited(tmp_path, ctx):  # noqa: F811
    h = Harness(tmp_path)
    await library_track(h.rig, rate=22050, channels=1)
    sid = await a_speech(h, LONG)
    params = {"source_kind": "speech", "source_id": sid, "name": "Ann", "voice_is": "permission"}
    voice = (await h.go("voice.clone", params, person_approved=True)).output["voice_id"]

    r = await h.go(
        "voice.convert",
        {"source_kind": "track", "source_id": "song", "saved_voice": voice,
         "model": "tone-color-vc"},
    )  # fmt: skip
    assert r.status == "ok" and r.output["title"] == "Summer (as Ann)", r.text
    assert set(r.output) == {"track_id", "product_id", "title", "seconds", "uri"}
    ghost = await h.go(
        "voice.convert", {"source_kind": "track", "source_id": "song", "saved_voice": "ghost"}
    )
    assert (ghost.status, ghost.code) == ("refused", "unknown_voice")

    edited = await h.go(
        "voice.edit_speech",
        {"source_kind": "track", "source_id": "song", "model": "dots-tts-edit",
         "old_text": "Hello brave world.", "text": "Hello small world."},
    )  # fmt: skip
    assert edited.ok and h.engine.speech_edited, edited.text
    assert edited.output["title"] == "Summer (edited)"


# ---- music ------------------------------------------------------------------------------------


async def test_music_is_made_with_the_documented_result(tmp_path, ctx):  # noqa: F811
    h = Harness(tmp_path)
    r = await h.go(
        "music.generate",
        {"description": "Pop, upbeat", "lyrics": "la la la", "seconds": 45, "seed": 11},
    )
    assert (
        r.ok and r.output["title"] == "Pop, upbeat" and r.output["product_id"] == "wasifyai-voice"
    )
    assert r.text.startswith('The music "Pop, upbeat" was made (')
    model_id, req = h.engine.made[0]
    assert req.lyrics == "la la la" and req.duration == 45 and req.seed == 11
    sfx = await h.go(
        "music.generate",
        {"description": "rain on a tin roof", "mode": "sfx", "model": "stable-audio-3-small-sfx"},
    )
    assert sfx.ok and h.engine.made[1][1].mode == "sfx"
    too_long = await h.go("music.generate", {"description": "x", "seconds": 999})
    assert (too_long.status, too_long.code) == ("refused", "invalid_input")


async def test_lyrics_are_written_and_nothing_is_kept(tmp_path, ctx):  # noqa: F811
    h = Harness(tmp_path, turns=[{"text": LYRICS}])
    r = await h.go("music.lyrics", {"idea": "a summer day by the sea", "style": "upbeat pop"})
    assert r.ok and r.output["lyrics"].startswith("[verse]") and "Sunshine" in r.text
    assert h.store.list_tracks("t1", "u1") == []


async def test_a_song_is_split_into_parts_that_are_kept(tmp_path, ctx):  # noqa: F811
    h = Harness(tmp_path)
    await library_track(h.rig)
    r = await h.go(
        "music.separate", {"source_kind": "track", "source_id": "song", "stems": ["vocals"]}
    )
    assert r.ok and [t["stem"] for t in r.output["tracks"]] == ["vocals"]
    assert r.output["track_id"] == r.output["tracks"][0]["track_id"]
    assert h.store.get_track("t1", "u1", r.output["track_id"])["parent_id"] == "song"
    missing = await h.go("music.separate", {"source_kind": "track", "source_id": "nope"})
    assert (missing.status, missing.code) == ("refused", "unknown_source")


# ---- dubbing and audiobooks -------------------------------------------------------------------


@needs_ffmpeg
async def test_a_recording_is_dubbed_in_two_steps(tmp_path, ctx):  # noqa: F811
    lines = json.dumps(["Hello.", "Second line."])
    h = Harness(tmp_path, turns=[{"text": lines}])
    await library_track(h.rig, rate=16000, channels=1, seconds=3.0)
    script = await h.go(
        "dub.script", {"source_kind": "track", "source_id": "song", "language": "en"}
    )
    assert script.ok and script.output["language"] == "en"
    assert [s["text"] for s in script.output["segments"]] == ["Hello.", "Second line."]
    assert "Hello." in script.text

    dub = await h.go(
        "dub.make",
        {"source_kind": "track", "source_id": "song", "language": "en",
         "segments": script.output["segments"], "voice_from": "builtin", "voice": "am_adam"},
    )  # fmt: skip
    assert dub.ok, dub.text
    assert h.store.get_track("t1", "u1", dub.output["track_id"])["mode"] == "dubbed"
    saved = await h.go(
        "dub.make",
        {"source_kind": "track", "source_id": "song", "language": "en",
         "segments": script.output["segments"], "voice_from": "saved"},
    )  # fmt: skip
    assert (saved.status, saved.code) == ("refused", "invalid_input")  # which saved voice?


async def test_a_dub_of_nothing_is_refused_in_words(tmp_path, ctx):  # noqa: F811
    h = Harness(tmp_path)
    r = await h.go(
        "dub.make",
        {"source_kind": "track", "source_id": "nope", "language": "es",
         "segments": [{"start": 0, "end": 1, "text": "Hola."}]},
    )  # fmt: skip
    assert (r.status, r.code) == ("refused", "unknown_source")


async def test_a_book_is_planned_then_read_one_track_per_chapter(tmp_path, ctx):  # noqa: F811
    from test_voice_book import BOOK

    h = Harness(tmp_path)
    plan = await h.go("audiobook.plan", {"text": BOOK})
    assert plan.ok and len(plan.output["chapters"]) >= 3
    assert set(plan.output["chapters"][0]) == {"title", "chars", "estimated_seconds"}
    assert "Nothing was made yet" in plan.text and h.engine.spoken == []
    book = await h.go("audiobook.make", {"text": BOOK, "title": "The Lighthouse"})
    assert book.ok, book.text
    assert len(book.output["tracks"]) == len(plan.output["chapters"])
    assert book.output["track_id"] == book.output["tracks"][0]["track_id"]
    empty = await h.go("audiobook.plan", {"text": "   "})
    assert (empty.status, empty.code) == ("refused", "invalid_input")


# ---- lip sync ---------------------------------------------------------------------------------


async def test_a_picture_talks_only_after_the_person_gives_their_word(tmp_path, ctx):  # noqa: F811
    h = Harness(tmp_path)
    params = {"image_id": "img1", "text": "Welcome to the show, everybody.", "picture_is": "drawn"}
    asked = await h.go("lipsync.make", params)
    assert asked.status == "needs_approval" and "AI-generated" in asked.text
    assert h.engine.lipsynced == [] and h.host.runs == []

    r = await h.go("lipsync.make", params, person_approved=True)
    assert r.ok, r.text
    assert set(r.output) == {"clip_id", "title", "seconds", "uri"}
    clip = h.store.get_clip("t1", "u1", r.output["clip_id"])
    assert clip["consent"]["picture"] == "drawn" and clip["consent"]["voice"] == "generated"
    assert clip["consent"]["mark"] == "AI-generated"

    for bad in (
        {"image_id": "img1", "picture_is": "drawn"},  # neither words nor a recording
        {"image_id": "img1", "text": "x", "source_id": "s", "source_kind": "track",
         "picture_is": "drawn"},  # both
        {"image_id": "img1", "source_id": "s", "source_kind": "track", "picture_is": "drawn"},
    ):  # fmt: skip
        again = await h.go("lipsync.make", bad, person_approved=True)
        assert (again.status, again.code) == ("refused", "invalid_input"), bad
    ghost = await h.go("lipsync.make", params | {"image_id": "ghost"}, person_approved=True)
    assert (ghost.status, ghost.code) == ("refused", "not_found")


# ---- the library ------------------------------------------------------------------------------


async def test_what_the_product_keeps_can_be_listed_renamed_exported_and_deleted(tmp_path, ctx):  # noqa: F811
    h = Harness(tmp_path)
    await library_track(h.rig, title="Summer")
    got = await h.go("library.get", {"kind": "track", "id": "song"})
    assert (
        got.output["item"]["title"] == "Summer" and got.output["item"]["detail"]["seconds"] == 2.0
    )
    renamed = await h.go("library.rename", {"kind": "track", "id": "song", "title": "Winter"})
    assert renamed.ok and h.store.get_track("t1", "u1", "song")["title"] == "Winter"
    exported = await h.go("library.export", {"kind": "track", "id": "song"})
    assert (
        exported.ok and (tmp_path / "exports" / exported.output["name"]).read_bytes()[:4] == b"RIFF"
    )
    again = await h.go("library.export", {"kind": "track", "id": "song"})
    assert again.output["name"] != exported.output["name"]  # a copy never replaces a file

    sid = await a_speech(h)
    t = await h.go("speech.transcribe", {"source_kind": "speech", "source_id": sid})
    text = await h.go("library.export", {"kind": "transcript", "id": t.output["transcript_id"]})
    assert text.output["name"].endswith(".txt")
    assert (
        await h.go("library.rename", {"kind": "speech", "id": sid, "title": "x"})
    ).code == "cannot_rename"

    for kind, item in (
        ("track", "song"),
        ("speech", sid),
        ("transcript", t.output["transcript_id"]),
    ):
        ask = await h.go("library.delete", {"kind": kind, "id": item})
        assert ask.status == "needs_approval", kind
        done = await h.go("library.delete", {"kind": kind, "id": item}, person_approved=True)
        assert done.ok, kind
        assert (await h.go("library.get", {"kind": kind, "id": item})).code == "not_found"
    assert h.store.list_tracks("t1", "u1") == []


def test_every_voice_action_is_run_in_this_file():
    source = Path(__file__).read_text()
    missing = [a.id for a in actions() if f'"{a.id}"' not in source]
    assert not missing, f"no test runs {missing}"
