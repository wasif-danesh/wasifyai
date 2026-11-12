"""`train.make_set` (docs/chat-does-everything-plan.md, CE5): the chat makes the set the Train
screen makes, from pictures of the library or an attached table, and `train.start` teaches from
it. Run through the one executor with the preview trainer and the fake vision model."""

from datetime import UTC, datetime
from typing import Any

from training_rig import BASE, noise, png, user_of
from wasifyai_platform_sdk import (
    Identity,
    InMemoryUploadStore,
    RouteDeps,
    ScopedStorage,
    memory_storage,
    new_upload,
)
from wasifyai_platform_sdk.actions import ActionExecutor, ActionRegistry, builtin_actions
from wasifyai_platform_sdk.actions.library import LibraryItem, LibraryKind
from wasifyai_platform_sdk.actions.testing import FakeActionHost
from wasifyai_training.actions import actions, library_kinds
from wasifyai_training.sets import rows_of

ME = Identity("t1", "u1")


class Pictures:
    """The image product's library kind, as far as a set needs it: a picture's file and title."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def add(self, data: bytes) -> str:
        ident = f"img{len(self.files):029d}"
        self.files[ident] = data
        return ident

    def kind(self) -> LibraryKind:
        async def get(ctx: Any, ident: str) -> LibraryItem | None:
            if ident not in self.files:
                return None
            return LibraryItem(
                kind="image",
                id=ident,
                title=f"photo {ident[-2:]}",
                created_at=datetime.now(UTC).isoformat(),
            )

        async def read(ctx: Any, ident: str) -> bytes | None:
            return self.files.get(ident)

        async def nothing(*a: Any) -> Any:
            return []

        return LibraryKind("image", "wasifyai-image", "picture", nothing, get, nothing, read=read)


class Harness:
    def __init__(self, rig) -> None:
        self.rig = rig
        state = rig.app_state
        state.creation_index = None
        state.storage = ScopedStorage(memory_storage())
        state.uploads = InMemoryUploadStore()
        self.deps = RouteDeps(state, user_of)
        self.pictures = Pictures()
        self.ex = ActionExecutor(
            ActionRegistry([*builtin_actions(), *actions()]),
            FakeActionHost(self.deps),
            library={"image": self.pictures.kind(), **{k.kind: k for k in library_kinds()}},
        )

    async def go(self, action: str, params: dict):
        return await self.ex.run_action(action, params, "window", actor=ME)

    async def attach(self, text: str) -> str:
        state = self.rig.app_state
        data = text.encode()
        record = new_upload("t1", "wasifyai-assistant", "u1", len(data), "text")
        await state.storage.put_for(record.owner, record.key, data, "text/plain")
        await state.uploads.add(record)
        return record.id


async def test_a_set_of_library_pictures_is_checked_described_and_taught(rig):
    h = Harness(rig)
    ids = [h.pictures.add(png(noise((60 + n * 20, 90, 200 - n * 10)))) for n in range(8)]
    r = await h.go("train.make_set", {"name": "Marlo", "kind": "character", "image_ids": ids})
    assert r.status == "ok", r.text
    out = r.output
    assert out["count"] == 8 and out["described"] == 8 and out.get("missing") is None
    assert out["magic_word"] == "marlo" and out["set_id"] in r.text and "ready" in r.text
    ds = rig.get(f"{BASE}/datasets/{out['set_id']}").json()
    assert ds["trigger_word"] == "marlo" and ds["pictures"] == 8 and ds["missing"] is None
    assert all(i["caption_state"] == "done" for i in ds["items"])
    taught = await h.go("train.start", {"dataset_id": out["set_id"]})
    assert taught.status == "ok", taught.text
    assert "marlo" in taught.text


async def test_too_few_or_unknown_pictures_say_what_is_missing(rig):
    h = Harness(rig)
    ids = [h.pictures.add(png(noise((40 * n, 90, 90)))) for n in range(3)]
    r = await h.go(
        "train.make_set", {"name": "Ink", "kind": "style", "image_ids": [*ids, "x" * 32]}
    )
    assert r.status == "ok", r.text
    assert r.output["count"] == 3 and "at least 8" in r.output["missing"]
    assert any("not a picture of the library" in s for s in r.output["skipped"])
    ghost = await h.go("train.make_set", {"name": "Ghost", "image_ids": ["y" * 32]})
    assert ghost.status == "refused" and "None of those pictures" in ghost.text
    bad = await h.go("train.make_set", {"name": "No pictures"})
    assert (bad.status, bad.code) == ("refused", "invalid_input")


async def test_a_poor_magic_word_is_replaced_and_said(rig):
    h = Harness(rig)
    ids = [h.pictures.add(png(noise((60 + n * 20, 90, 90)))) for n in range(8)]
    r = await h.go("train.make_set", {"name": "Marlo", "image_ids": ids, "magic_word": "dog"})
    assert r.status == "ok", r.text
    assert r.output["magic_word"] == "marlo" and "poor one" in r.text


async def test_an_attached_table_becomes_a_writing_set(rig):
    h = Harness(rig)
    table = "question,answer\n" + "\n".join(
        f"Where is order {n}?,It ships on day {n}." for n in range(12)
    )
    r = await h.go(
        "train.make_set",
        {"what": "writing", "name": "Replies", "attachment_id": await h.attach(table)},
    )
    assert r.status == "ok", r.text
    assert r.output["count"] == 12 and r.output.get("missing") is None and "set_id" in r.text
    got = rig.get(f"{BASE}/writing/sets/{r.output['set_id']}").json()
    assert got["rows"][0] == {"ask": "Where is order 0?", "answer": "It ships on day 0."}


async def test_an_attached_table_becomes_a_decision_set_of_the_right_kind(rig):
    h = Harness(rig)
    rows = "\n".join(f"Review number {n} text\t{'yes' if n % 2 else 'no'}" for n in range(24))
    r = await h.go(
        "train.make_set",
        {
            "what": "decision", "name": "Reviews", "question": "Is this review positive?",
            "attachment_id": await h.attach(rows),
        },
    )  # fmt: skip
    assert r.status == "ok", r.text
    got = rig.get(f"{BASE}/decision/sets/{r.output['set_id']}").json()
    assert got["kind"] == "yes_no" and got["question"] == "Is this review positive?"
    assert r.output["count"] == 24 and got["problem"] is None
    gone = await h.go(
        "train.make_set",
        {"what": "writing", "name": "X", "attachment_id": "00000000-0000-4000-8000-000000000000"},
    )
    assert gone.status == "refused" and "attach it again" in gone.text


def test_tables_are_read_as_the_screen_reads_them():
    assert rows_of('text;label\n"a; b";yes\nc;no\n') == [["a; b", "yes"], ["c", "no"]]
    assert rows_of("\ufeffquestion\tanswer\nhi\tthere\n\nonly one\n") == [["hi", "there"]]
    assert rows_of("one,two,three\n") == [["one", "two", "three"]]
