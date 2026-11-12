"""`library.keep_attachment` (docs/chat-does-everything-plan.md, CE1): a picture attached in the
chat becomes a picture of the library, through the image product's own import, so every other
action can work on it by its id. Run through the one executor with the image product's real
SQLite store."""

import io
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image
from wasifyai_assistant.actions import actions as assistant_actions
from wasifyai_image.actions import actions as image_actions
from wasifyai_image.actions import library_kinds
from wasifyai_image.images import image_store
from wasifyai_platform_sdk import (
    Identity,
    InMemoryUploadStore,
    InMemoryUsageRecorder,
    RouteDeps,
    ScopedStorage,
    memory_storage,
    new_upload,
)
from wasifyai_platform_sdk.actions import ActionExecutor, ActionRegistry, builtin_actions
from wasifyai_platform_sdk.actions.testing import FakeActionHost
from wasifyai_platform_sdk.sqlite import create_sqlite_engine

ME = Identity("t1", "u1")


def png(size=(64, 48)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (30, 120, 200)).save(out, "PNG")
    return out.getvalue()


class Rig:
    def __init__(self, engine, with_images: bool = True, kinds: list | None = None, data_dir=None):
        self.indexed: list[tuple[str, str]] = []
        rig = self

        class Index:
            async def index(self, tenant, product, user, kind, item, text) -> None:
                rig.indexed.append((kind, item))

        self.state: Any = SimpleNamespace(
            engine=engine, storage=ScopedStorage(memory_storage()), uploads=InMemoryUploadStore(),
            usage=InMemoryUsageRecorder(), creation_index=Index(), voice_store=None,
            desktop_dir=str(data_dir) if data_dir else None,
        )  # fmt: skip
        self.deps = RouteDeps(self.state, lambda: ME)
        kinds = [*(library_kinds() if with_images else []), *(kinds or [])]
        self.ex = ActionExecutor(
            ActionRegistry([*builtin_actions(), *image_actions(), *assistant_actions()]),
            FakeActionHost(self.deps),
            library={k.kind: k for k in kinds},
        )
        self.store = image_store(engine)

    async def attach(self, data: bytes, user: str = "u1", kind: str = "image") -> str:
        record = new_upload("t1", "wasifyai-assistant", user, len(data), kind)
        with self.deps.acting_as(Identity("t1", user), "wasifyai-assistant"):
            await self.state.storage.put(record.key, data)
        await self.state.uploads.add(record)
        return record.id

    async def keep(self, params: dict):
        return await self.ex.run_action("library.keep_attachment", params, "window", actor=ME)


@pytest.fixture
async def engine(tmp_path):
    e = create_sqlite_engine(tmp_path / "images.db")
    yield e
    await e.dispose()


async def test_an_attached_picture_becomes_a_picture_of_the_library_with_its_id(engine):
    rig = Rig(engine)
    upload = await rig.attach(png())
    r = await rig.keep({"attachment_id": upload, "title": "Beach"})
    assert r.status == "ok", r.text
    image_id = r.output["id"]
    assert r.output["kind"] == "image" and r.output["title"] == "Beach"
    assert image_id in r.text and "Use that id" in r.text  # the model is told the id
    kept = await rig.store.get("t1", "u1", image_id)
    assert kept is not None and kept.mode == "import" and (kept.width, kept.height) == (64, 48)
    assert ("image", image_id) in rig.indexed  # searchable at once (ADR-0041)
    with rig.deps.acting_as(ME, "wasifyai-image"):
        assert (await rig.state.storage.get(kept.image_key)).startswith(b"\x89PNG")


async def test_an_attachment_that_is_gone_or_someone_elses_is_not_found(engine):
    rig = Rig(engine)
    theirs = await rig.attach(png(), user="someone-else")
    for ident in (theirs, "00000000-0000-4000-8000-000000000000"):
        r = await rig.keep({"attachment_id": ident})
        assert r.status == "refused" and "attach the file again" in r.text
    assert await rig.store.list("t1", "u1", 10, None) == []


async def test_nothing_is_kept_when_no_product_takes_pictures(engine):
    rig = Rig(engine, with_images=False)
    upload = await rig.attach(png())
    r = await rig.keep({"attachment_id": upload})
    assert r.status == "refused" and "cannot keep an attached picture" in r.text


async def test_a_file_that_is_not_a_picture_is_refused_in_words(engine):
    rig = Rig(engine)
    upload = await rig.attach(b"not a picture at all")
    r = await rig.keep({"attachment_id": upload})
    assert r.status == "refused"
    assert await rig.store.list("t1", "u1", 10, None) == []


# ---- the chat keeps an attachment named where a library item belongs (keeping.py) ----


async def test_an_attachment_named_in_an_id_field_is_kept_once_and_replaced():
    from wasifyai_assistant.keeping import kept_in_place

    names = {"a1": "a1", "beach.png": "a1", "b2": "b2"}
    calls: list[str] = []

    async def keep(ident: str, as_kind: str) -> str | None:
        calls.append(ident)
        return f"lib-{ident}"

    done: dict[tuple[str, str], str] = {}
    out = await kept_in_place(
        "image.reference",
        {"image_ids": ["beach.png", "b2"], "prompt": "beach.png", "seed": 3},
        names, keep, done,
    )  # fmt: skip
    assert out == {"image_ids": ["lib-a1", "lib-b2"], "prompt": "beach.png", "seed": 3}
    again = await kept_in_place("video.animate", {"image_id": "a1"}, names, keep, done)
    assert again == {"image_id": "lib-a1"} and calls == ["a1", "b2"]  # kept once per file
    # a field that takes an attachment gets its id for a file name, and nothing is kept for it
    keep_it = await kept_in_place(
        "library.keep_attachment", {"attachment_id": "beach.png"}, names, keep, {}
    )
    assert keep_it == {"attachment_id": "a1"}
    notebook = await kept_in_place(
        "notebook.create", {"title": "T", "attachment_ids": ["beach.png", "b2"]}, names, keep, {}
    )
    assert notebook == {"title": "T", "attachment_ids": ["a1", "b2"]} and calls == ["a1", "b2"]
    # a value that is no attachment is left alone
    assert await kept_in_place("image.edit", {"image_id": "lib-9"}, names, keep, {}) == {
        "image_id": "lib-9"
    }


async def test_a_file_name_two_attachments_share_names_neither():
    from wasifyai_assistant.keeping import attachment_names
    from wasifyai_assistant.store import Message

    def said(*parts):
        return Message(id="m", conversation_id="c", seq=0, role="user", parts=list(parts))

    a = {"type": "attachment", "kind": "image", "id": "a1", "key": "", "name": "IMG.jpg"}
    b = {"type": "attachment", "kind": "image", "id": "b2", "key": "", "name": "IMG.jpg"}
    c = {"type": "attachment", "kind": "image", "id": "c3", "key": "", "name": "dir/../cat.png"}
    assert attachment_names([said(a, b, c)]) == {
        "a1": "a1",
        "b2": "b2",
        "c3": "c3",
        "cat.png": "c3",
    }


async def test_a_clip_is_kept_as_what_the_field_takes():
    from wasifyai_assistant.keeping import kept_in_place

    asked: list[tuple[str, str]] = []

    async def keep(ident: str, as_kind: str) -> str | None:
        asked.append((ident, as_kind))
        return f"{as_kind}-{ident}"

    names, done = {"talk.mp4": "c1"}, {}
    dub = await kept_in_place("dub.script", {"source_id": "talk.mp4"}, names, keep, done)
    extend = await kept_in_place("video.extend", {"video_id": "talk.mp4"}, names, keep, done)
    assert dub == {"source_id": "track-c1"} and extend == {"video_id": "video-c1"}
    assert asked == [("c1", "track"), ("c1", "video")]


def clip_with_sound(seconds: float = 2) -> bytes:
    """A real small clip with a tone, made with the ffmpeg the products use."""
    import subprocess
    import tempfile
    from pathlib import Path

    from wasifyai_video.videos import ffmpeg_path

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "clip.mp4"
        subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", f"testsrc=size=160x96:rate=24:duration={seconds}",
             "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)],
            check=True,
        )  # fmt: skip
        return out.read_bytes()


async def test_an_attached_clip_is_kept_as_a_video_or_as_the_sound_of_it(engine, tmp_path):
    from wasifyai_video.actions import library_kinds as video_kinds
    from wasifyai_video.videos import video_store
    from wasifyai_voice.actions import library_kinds as voice_kinds

    rig = Rig(engine, with_images=False, kinds=[*video_kinds(), *voice_kinds()], data_dir=tmp_path)
    upload = await rig.attach(clip_with_sound(), kind="video")
    as_video = await rig.keep({"attachment_id": upload, "title": "Talk"})
    assert as_video.status == "ok", as_video.text
    assert as_video.output["kind"] == "video"
    clip = await video_store(engine).get("t1", "u1", as_video.output["id"])
    assert clip is not None and clip.status == "done" and clip.mode == "import"
    as_sound = await rig.keep({"attachment_id": upload, "title": "Talk", "as_kind": "track"})
    assert as_sound.status == "ok", as_sound.text
    assert as_sound.output["kind"] == "track" and as_sound.output["title"] == "Talk"
    assert {k for k, _ in rig.indexed} == {"video", "track"}  # both searchable


async def test_an_attached_recording_is_kept_as_a_song(engine, tmp_path):
    import struct

    from wasifyai_voice.actions import library_kinds as voice_kinds

    rate, frames = 44100, 44100
    pcm = b"".join(struct.pack("<hh", 0, 0) for _ in range(frames))
    wav = (
        b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 2, rate, rate * 4, 4, 16) + b"data"
        + struct.pack("<I", len(pcm)) + pcm
    )  # fmt: skip
    rig = Rig(engine, with_images=False, kinds=voice_kinds(), data_dir=tmp_path)
    upload = await rig.attach(wav, kind="audio")
    r = await rig.keep({"attachment_id": upload})
    assert r.status == "ok", r.text
    assert r.output["kind"] == "track" and "track id" in r.text
    wrong = await rig.keep({"attachment_id": upload, "as_kind": "video"})
    assert wrong.status == "refused" and "as a video" in wrong.text
