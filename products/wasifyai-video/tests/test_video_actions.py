"""The video product's actions (ADR-0068) through the one executor, with the product's real
SQLite store and a scripted child run."""

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from video_rig import png
from wasifyai_platform_sdk import (
    Identity,
    InMemoryUploadStore,
    InMemoryUsageRecorder,
    RouteDeps,
    RunContext,
    ScopedStorage,
    memory_storage,
    reset_context,
    set_context,
)
from wasifyai_platform_sdk.actions import (
    ActionExecutor,
    ActionRegistry,
    LibraryItem,
    LibraryKind,
    builtin_actions,
)
from wasifyai_platform_sdk.actions.testing import FakeActionHost
from wasifyai_platform_sdk.sqlite import create_sqlite_engine
from wasifyai_video.actions import actions, library_kinds
from wasifyai_video.videos import VideoRecord, video_store

ME = Identity("t1", "u1")
VIDEO_ID = "00000000-0000-0000-0000-000000000009"


def a_picture_kind() -> LibraryKind:
    """What the image product declares: enough for animating a picture of the library."""

    async def list_(c, n):
        return []

    async def get(c, i):
        return LibraryItem(kind="image", id=i, title="a fox") if i == "img1" else None

    async def read(c, i):
        return png((64, 48)) if i == "img1" else None

    async def delete(c, i):
        return False

    return LibraryKind("image", "wasifyai-image", "picture", list_, get, delete, read=read)


class Rig:
    def __init__(self, tmp_path: Path, engine):
        self.unindexed: list[str] = []
        rig = self

        class Index:
            async def remove(self, tenant: str, product: str, item: str) -> None:
                rig.unindexed.append(item)

        self.state: Any = SimpleNamespace(
            engine=engine, storage=ScopedStorage(memory_storage()), uploads=InMemoryUploadStore(),
            usage=InMemoryUsageRecorder(), export_dir=tmp_path / "exports", creation_index=Index(),
        )  # fmt: skip
        self.host = FakeActionHost(RouteDeps(self.state, lambda: ME))
        self.ex = ActionExecutor(
            ActionRegistry([*builtin_actions(), *actions()]),
            self.host,
            library={**{k.kind: k for k in library_kinds()}, "image": a_picture_kind()},
        )
        self.store = video_store(engine)

    @asynccontextmanager
    async def as_user(self):
        token = set_context(RunContext("t1", "wasifyai-video", "u1"))
        try:
            yield
        finally:
            reset_context(token)

    async def keep(self, status="done", prompt="waves on a beach") -> None:
        async with self.as_user():
            await self.state.storage.put(f"{VIDEO_ID}/video.mp4", b"mp4-bytes", "video/mp4")
            await self.state.storage.put(f"{VIDEO_ID}/poster.jpg", b"jpeg", "image/jpeg")
        await self.store.add(
            VideoRecord(
                id=VIDEO_ID, tenant_id="t1", product_id="wasifyai-video", user_id="u1",
                thread_id=None, run_id=None, mode="text", status=status, prompt=prompt,
                seconds=2, frames=49, fps=24, width=768, height=512,
                video_key=f"{VIDEO_ID}/video.mp4", poster_key=f"{VIDEO_ID}/poster.jpg",
            )
        )  # fmt: skip
        if status == "done":  # a row starts as "working" and is finished when the clip is kept
            await self.store.finish(
                "t1", VIDEO_ID, 768, 512, f"{VIDEO_ID}/video.mp4", f"{VIDEO_ID}/poster.jpg"
            )

    async def go(self, action_id: str, params: dict, origin="window", **kw):
        return await self.ex.run_action(action_id, params, origin, actor=ME, **kw)


@pytest.fixture
async def rig(tmp_path):
    engine = create_sqlite_engine(tmp_path / "videos.db")
    yield Rig(tmp_path, engine)
    await engine.dispose()


def finished(**out: Any) -> list[dict]:
    done = {"status": "done", "seconds": 2, "width": 768, "height": 512} | out
    return [{"event": "done", "outputs": done}]


async def test_a_video_is_made_and_it_may_take_a_while(rig):
    rig.host.script("wasifyai-video", finished(video_id="vid-1"))
    r = await rig.go("video.generate", {"prompt": "waves on a beach", "shape": "portrait"})
    assert r.status == "ok" and set(r.output) == {
        "video_id", "product_id", "uri", "prompt", "seconds", "width", "height",
    }  # fmt: skip
    assert r.text == (
        'The video was made (2 seconds, 768x512) from "waves on a beach" and saved to the library.'
    )
    assert rig.host.runs == [
        ("wasifyai-video", {"mode": "text", "prompt": "waves on a beach", "shape": "portrait",
                            "seconds": 2})
    ]  # fmt: skip
    action = rig.ex.registry.get("video.generate")
    assert action and action.long and "costly" in action.flags


async def test_the_second_asks_before_a_costly_make_when_the_person_chose_to_be_asked(rig):
    r = await rig.go("video.generate", {"prompt": "waves"}, origin="assistant")
    assert r.status == "needs_approval" and rig.host.runs == []


async def test_a_request_the_product_cannot_take_is_refused_in_words(rig):
    for params in ({"prompt": "x", "seconds": 7}, {"prompt": "x", "shape": "wide"}, {"prompt": ""}):
        r = await rig.go("video.generate", params)
        assert (r.status, r.code) == ("refused", "invalid_input"), params
    assert rig.host.runs == []


async def test_a_busy_gpu_is_a_refusal_with_the_products_sentence(rig):
    rig.host.script(
        "wasifyai-video",
        [{"event": "done", "outputs": {"status": "refused", "refusal": {
            "code": "busy", "message": "You already have a video being made."}}}],
    )  # fmt: skip
    r = await rig.go("video.generate", {"prompt": "waves"})
    assert (r.status, r.code) == ("refused", "busy") and "already have a video" in r.text


async def test_a_picture_of_the_library_is_set_moving(rig):
    rig.host.script("wasifyai-video", finished(video_id="vid-2"))
    r = await rig.go(
        "video.animate", {"image_id": "img1", "prompt": "the clouds drift", "seconds": 5}
    )
    assert r.ok
    [(_, graph_input)] = rig.host.runs
    assert graph_input["mode"] == "image" and graph_input["seconds"] == 5
    assert await rig.state.uploads.find("t1", "wasifyai-video", "u1", graph_input["image_key"])
    ghost = await rig.go("video.animate", {"image_id": "ghost", "prompt": "x"})
    assert (ghost.status, ghost.code) == ("refused", "not_found")


async def test_clips_are_listed_exported_and_deleted_but_not_while_being_made(rig, tmp_path):
    await rig.keep()
    [item] = (await rig.go("library.list", {"kind": "video"})).output["items"]
    assert item["id"] == VIDEO_ID and item["detail"]["seconds"] == 2
    exported = await rig.go("library.export", {"kind": "video", "id": VIDEO_ID})
    assert exported.ok, exported.text
    assert exported.output["name"] == "waves-on-a-beach.mp4"
    assert (tmp_path / "exports" / "waves-on-a-beach.mp4").read_bytes() == b"mp4-bytes"
    done = await rig.go("library.delete", {"kind": "video", "id": VIDEO_ID}, person_approved=True)
    assert done.ok and await rig.store.get("t1", "u1", VIDEO_ID) is None
    assert rig.unindexed == [VIDEO_ID]


async def test_a_clip_still_being_made_is_not_deleted(rig):
    await rig.keep(status="working")
    r = await rig.go("library.delete", {"kind": "video", "id": VIDEO_ID}, person_approved=True)
    assert (r.status, r.code, r.text) == ("refused", "busy", "That video is still being made.")
    assert await rig.store.get("t1", "u1", VIDEO_ID) is not None
    export = await rig.go("library.export", {"kind": "video", "id": VIDEO_ID})
    assert export.code == "not_found"  # nothing to copy yet


def test_every_video_action_is_run_in_this_file():
    # Video Builder's actions are run in test_builder.py, which has its own rig and stand-in engine
    source = Path(__file__).read_text() + (Path(__file__).parent / "test_builder.py").read_text()
    missing = [a.id for a in actions() if f'"{a.id}"' not in source]
    assert not missing, f"no test runs {missing}"
