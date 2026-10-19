"""The image product's actions (ADR-0068) through the one executor, with the product's real
SQLite store and a scripted child run: the documented result, the files and the search kept in
step, a picture of the library made ready for editing."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from image_rig import png
from wasifyai_image.actions import actions, library_kinds
from wasifyai_image.images import ImageRecord, image_store
from wasifyai_platform_sdk import (
    Identity,
    InMemoryUploadStore,
    InMemoryUsageRecorder,
    RouteDeps,
    ScopedStorage,
    memory_storage,
)
from wasifyai_platform_sdk.actions import (
    ActionExecutor,
    ActionRegistry,
    ApprovalPolicy,
    builtin_actions,
)
from wasifyai_platform_sdk.actions.testing import FakeActionHost
from wasifyai_platform_sdk.sqlite import create_sqlite_engine

ME = Identity("t1", "u1")
OTHER = Identity("t1", "someone-else")
IMAGE_ID = "00000000-0000-0000-0000-000000000001"


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
            library={k.kind: k for k in library_kinds()},
        )
        self.store = image_store(engine)

    async def keep(self, image_id=IMAGE_ID, user="u1", prompt="a red teapot") -> None:
        async with self._as(user):
            await self.state.storage.put(f"{image_id}/image.png", png((64, 48)), "image/png")
            await self.state.storage.put(f"{image_id}/thumb.jpg", b"jpeg", "image/jpeg")
        await self.store.add(
            ImageRecord(
                id=image_id, tenant_id="t1", product_id="wasifyai-image", user_id=user,
                thread_id=None, run_id=None, mode="text", prompt=prompt, width=64, height=48,
                image_key=f"{image_id}/image.png", thumb_key=f"{image_id}/thumb.jpg",
            )
        )  # fmt: skip

    def _as(self, user: str):
        from contextlib import asynccontextmanager

        from wasifyai_platform_sdk import RunContext, reset_context, set_context

        @asynccontextmanager
        async def scope():
            token = set_context(RunContext("t1", "wasifyai-image", user))
            try:
                yield
            finally:
                reset_context(token)

        return scope()

    async def go(self, action_id: str, params: dict, origin="window", **kw):
        return await self.ex.run_action(action_id, params, origin, actor=ME, **kw)


@pytest.fixture
async def rig(tmp_path):
    engine = create_sqlite_engine(tmp_path / "images.db")
    yield Rig(tmp_path, engine)
    await engine.dispose()


def done(**out: Any) -> list[dict]:
    return [
        {"event": "job_progress", "job_id": "j1", "progress": 0.5},
        {"event": "done", "outputs": {"status": "done", "width": 1024, "height": 1024} | out},
    ]


async def test_a_picture_is_made(rig):
    rig.host.script("wasifyai-image", done(image_id="img-1"))
    seen: list[dict] = []
    r = await rig.go(
        "image.generate", {"prompt": "a red teapot", "size": "wide"}, on_event=seen.append
    )
    assert r.status == "ok" and set(r.output) == {
        "image_id", "product_id", "uri", "prompt", "width", "height",
    }  # fmt: skip
    assert r.output["uri"] == "wasify://creation/image/img-1"
    assert r.text == 'The image was made (1024x1024) from "a red teapot" and saved to the library.'
    assert rig.host.runs == [
        ("wasifyai-image", {"mode": "text", "prompt": "a red teapot", "size": "wide"})
    ]
    assert seen[0]["job_id"] == "j1"


async def test_a_bad_request_never_reaches_the_graph(rig):
    for params in ({"prompt": ""}, {"prompt": "x" * 501}, {"prompt": "a fox", "size": "huge"}, {}):
        r = await rig.go("image.generate", params)
        assert (r.status, r.code) == ("refused", "invalid_input"), params
    assert rig.host.runs == []


async def test_the_product_refusing_is_a_refusal_with_its_sentence(rig):
    rig.host.script(
        "wasifyai-image",
        [{"event": "done", "outputs": {"status": "refused",
                                       "refusal": {"code": "sexual_content", "message": "No."}}}],
    )  # fmt: skip
    r = await rig.go("image.generate", {"prompt": "something"})
    assert (r.status, r.code, r.text) == (
        "refused",
        "sexual_content",
        "The image was not made: No.",
    )


async def test_a_picture_of_the_library_is_made_ready_and_changed(rig):
    await rig.keep()
    rig.host.script("wasifyai-image", done(image_id="img-2"))
    r = await rig.go("image.edit", {"image_id": IMAGE_ID, "prompt": "make the sky a sunset"})
    assert r.ok and r.text.startswith("The image was changed (1024x1024)")
    [(_, graph_input)] = rig.host.runs
    assert graph_input["mode"] == "image" and graph_input["prompt"] == "make the sky a sunset"
    key = graph_input["image_key"]
    record = await rig.state.uploads.find("t1", "wasifyai-image", "u1", key)
    assert record is not None  # an upload the graph can find, and delete when it is done
    async with rig._as("u1"):
        stored = await rig.state.storage.get(key)
    assert stored[:4] == b"\x89PNG"
    assert [e.kind for e in rig.state.usage.events] == ["upload.created"]


async def test_a_picture_that_is_not_yours_or_not_there_cannot_be_edited(rig):
    await rig.keep(user="someone-else")
    for image_id in (IMAGE_ID, "ghost"):
        r = await rig.go("image.edit", {"image_id": image_id, "prompt": "x"})
        assert (r.status, r.code) == ("refused", "not_found")
    assert rig.host.runs == []


async def test_the_library_lists_gets_exports_and_deletes_pictures(rig, tmp_path):
    await rig.keep()
    listed = await rig.go("library.list", {"kind": "image"})
    [item] = listed.output["items"]
    assert (item["id"], item["title"], item["detail"]["width"]) == (IMAGE_ID, "a red teapot", 64)
    assert item["uri"] == f"wasify://creation/image/{IMAGE_ID}"
    assert (await rig.go("library.get", {"kind": "image", "id": IMAGE_ID})).ok
    assert (
        await rig.go("library.rename", {"kind": "image", "id": IMAGE_ID, "title": "x"})
    ).code == "cannot_rename"

    exported = await rig.go("library.export", {"kind": "image", "id": IMAGE_ID})
    assert exported.output["name"] == "a-red-teapot.png"
    assert (tmp_path / "exports" / "a-red-teapot.png").read_bytes()[:4] == b"\x89PNG"

    mine_only = await rig.ex.run_action(
        "library.get", {"kind": "image", "id": IMAGE_ID}, "window", actor=OTHER
    )
    assert mine_only.code == "not_found"  # another person's picture looks like no picture

    asked = await rig.go("library.delete", {"kind": "image", "id": IMAGE_ID})
    assert asked.status == "needs_approval"
    assert (await rig.store.get("t1", "u1", IMAGE_ID)) is not None
    done_ = await rig.go("library.delete", {"kind": "image", "id": IMAGE_ID}, person_approved=True)
    assert done_.ok and await rig.store.get("t1", "u1", IMAGE_ID) is None
    assert rig.unindexed == [IMAGE_ID]  # out of search too (ADR-0041)
    async with rig._as("u1"):
        with pytest.raises(FileNotFoundError):
            await rig.state.storage.get(f"{IMAGE_ID}/image.png")


async def test_the_assistants_setting_does_not_let_it_delete(rig):
    await rig.keep()
    r = await rig.ex.run_action(
        "library.delete", {"kind": "image", "id": IMAGE_ID}, "assistant", actor=ME,
        policy=ApprovalPolicy(make="auto", change="auto"),
    )  # fmt: skip
    assert r.status == "needs_approval" and await rig.store.get("t1", "u1", IMAGE_ID) is not None


def test_every_image_action_is_run_in_this_file():
    source = Path(__file__).read_text()
    missing = [a.id for a in actions() if f'"{a.id}"' not in source]
    assert not missing, f"no test runs {missing}"
