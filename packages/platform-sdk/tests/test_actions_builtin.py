"""library.*, app.status and job.* (the actions that belong to no product)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from wasifyai_platform_sdk import InMemoryUsageRecorder
from wasifyai_platform_sdk.actions import (
    Action,
    ActionExecutor,
    ActionRegistry,
    ApprovalPolicy,
    CallBinding,
    InMemoryAuditStore,
    LibraryItem,
    LibraryKind,
    Outcome,
    Readiness,
    builtin_actions,
    need_model,
)
from wasifyai_platform_sdk.actions.testing import FakeActionHost
from wasifyai_platform_sdk.identity import Identity

ME = Identity("t1", "u1")
AUTO = ApprovalPolicy(make="auto", change="auto")


class Deps:
    def __init__(self, export_dir: Path | None):
        self.state = type("State", (), {"export_dir": export_dir})()


def songs() -> tuple[LibraryKind, dict[str, str]]:
    names = {"s1": "Rain song", "s2": "Sun song"}

    async def list_(ctx, limit):
        return [LibraryItem(kind="track", id=i, title=t) for i, t in list(names.items())[:limit]]

    async def get(ctx, item_id):
        return (
            LibraryItem(kind="track", id=item_id, title=names[item_id])
            if item_id in names
            else None
        )

    async def rename(ctx, item_id, title):
        if item_id not in names:
            return False
        names[item_id] = title
        return True

    async def delete(ctx, item_id):
        return names.pop(item_id, None) is not None

    async def export(ctx, item_id, folder):
        if item_id not in names:
            return None
        path = folder / f"{names[item_id]}.wav"
        path.write_bytes(b"RIFF")
        return path

    return LibraryKind("track", "wasifyai-voice", "song", list_, get, delete, rename, export), names


def pictures() -> LibraryKind:
    async def list_(ctx, limit):
        return [LibraryItem(kind="image", id="i1", title="a red teapot")]

    async def get(ctx, item_id):
        return None

    async def delete(ctx, item_id):
        return False

    return LibraryKind("image", "wasifyai-image", "picture", list_, get, delete)


def rig(tmp_path: Path, export: bool = True):
    host = FakeActionHost(deps=Deps(tmp_path if export else None))
    kind, names = songs()
    usage, audit = InMemoryUsageRecorder(), InMemoryAuditStore()
    ex = ActionExecutor(
        ActionRegistry(builtin_actions()),
        host,
        audit=audit,
        usage=usage,
        library={"track": kind, "image": pictures()},
    )
    return ex, host, names, audit


async def run(ex, action_id, params, origin="assistant", **kw):
    return await ex.run_action(action_id, params, origin, actor=ME, policy=AUTO, **kw)


async def test_search_returns_references_and_the_sentence_the_assistant_always_gave(tmp_path):
    ex, host, *_ = rig(tmp_path)
    host.hits = [
        {"kind": "image", "product_id": "wasifyai-image", "id": "img-9", "text": "a red teapot"}
    ]
    r = await run(ex, "library.search", {"query": "teapot"})
    assert r.ok
    assert r.text == "Found 1 in the person's library:\n- image: a red teapot"
    assert r.output["results"][0] | {"uri": "x"} == {
        "kind": "image", "product_id": "wasifyai-image", "id": "img-9", "text": "a red teapot",
        "uri": "x",
    }  # fmt: skip
    assert r.output["results"][0]["uri"] == "wasify://creation/image/img-9"
    host.hits = []
    nothing = await run(ex, "library.search", {"query": "zzz"})
    assert nothing.text == "Nothing matched in the person's library." and nothing.output == {
        "results": []
    }


async def test_list_get_rename_and_delete_go_through_the_kind(tmp_path):
    ex, _, names, _ = rig(tmp_path)
    listed = await run(ex, "library.list", {"kind": "track"})
    assert [i["id"] for i in listed.output["items"]] == ["s1", "s2"]
    assert listed.output["items"][0]["uri"] == "wasify://creation/track/s1"
    got = await run(ex, "library.get", {"kind": "track", "id": "s1"})
    assert got.output["item"]["title"] == "Rain song"
    missing = await run(ex, "library.get", {"kind": "track", "id": "nope"})
    assert (missing.status, missing.code) == ("refused", "not_found")

    renamed = await run(ex, "library.rename", {"kind": "track", "id": "s1", "title": "Storm song"})
    assert renamed.ok and names["s1"] == "Storm song"
    assert renamed.output["item"]["title"] == "Storm song"
    assert (
        await run(ex, "library.rename", {"kind": "image", "id": "i1", "title": "x"})
    ).code == "cannot_rename"

    asked = await run(
        ex, "library.delete", {"kind": "track", "id": "s2"}
    )  # AUTO does not lower the floor
    assert asked.status == "needs_approval" and "s2" in names
    done = await run(
        ex, "library.delete", {"kind": "track", "id": "s2"}, origin="window", person_approved=True
    )
    assert done.ok and done.output == {"deleted": True, "kind": "track", "id": "s2"}
    assert "s2" not in names


async def test_a_kind_the_computer_does_not_keep_is_unavailable(tmp_path):
    ex, *_ = rig(tmp_path)
    r = await run(ex, "library.list", {"kind": "notebook"})
    assert (r.status, r.code) == ("refused", "unavailable")


async def test_export_copies_into_the_export_folder_and_says_where(tmp_path):
    ex, *_ = rig(tmp_path)
    r = await run(ex, "library.export", {"kind": "track", "id": "s1"})
    assert r.ok and r.output["name"] == "Rain song.wav"
    assert (tmp_path / "Rain song.wav").read_bytes() == b"RIFF"
    assert (await run(ex, "library.export", {"kind": "track", "id": "zz"})).code == "not_found"
    assert (await run(ex, "library.export", {"kind": "image", "id": "i1"})).code == "unavailable"


async def test_export_is_unavailable_without_an_export_folder(tmp_path):
    ex, *_ = rig(tmp_path, export=False)
    assert (await run(ex, "library.export", {"kind": "track", "id": "s1"})).code == "unavailable"


async def test_app_status_says_which_actions_are_ready_and_what_is_missing(tmp_path):
    ex, host, *_ = rig(tmp_path)

    async def hello(p, ctx):
        return Outcome.ok({"echoed": "x"}, "x")

    from pydantic import BaseModel

    class Empty(BaseModel):
        pass

    ex.registry.add(
        Action(
            id="speech.speak", title="Speak", summary="s", description="d",
            input=Empty, output=Empty,
            effect="make", requires=(need_model("speak"),), bind=CallBinding(hello),
            ui="voice.speak",
        )
    )  # fmt: skip
    host.not_ready(need_model("speak"), Readiness.needs_setup("Get a speech model."))
    r = await run(ex, "app.status", {})
    states = {a["id"]: a["state"] for a in r.output["actions"]}
    assert states["speech.speak"] == "needs_setup" and states["library.search"] == "ready"
    assert "speech.speak: Get a speech model." in r.text
    assert r.output["facts"] == {"disk_free_bytes": 10_000_000_000}
    only = await run(ex, "app.status", {"domain": "speech"})
    assert [a["id"] for a in only.output["actions"]] == ["speech.speak"]


async def test_job_status_wait_and_cancel_on_a_running_job(tmp_path):
    ex, *_ = rig(tmp_path)
    gate = asyncio.Event()

    async def hold(p, ctx):
        ctx.emit({"event": "job_progress", "progress": 0.4})
        await gate.wait()
        return Outcome.ok({"echoed": "x"}, "All done.")

    from pydantic import BaseModel

    class Any_(BaseModel):
        pass

    class Out(BaseModel):
        echoed: str

    ex.registry.add(
        Action(
            id="demo.hold", title="Hold", summary="s", description="d", input=Any_, output=Out,
            effect="read", long=True, bind=CallBinding(hold), ui="chat",
        )
    )  # fmt: skip
    started = await run(ex, "demo.hold", {}, wait_seconds=0.01)
    assert started.job_id
    status = await run(ex, "job.status", {"job_id": started.job_id})
    assert status.output["status"] == "running" and "40 percent" in status.text
    waited = await run(ex, "job.wait", {"job_id": started.job_id, "seconds": 0.05})
    assert waited.output["status"] == "running"
    gate.set()
    done = await run(ex, "job.wait", {"job_id": started.job_id, "seconds": 5})
    assert done.output["status"] == "ok" and done.text == "All done."
    assert done.output["result"]["output"] == {"echoed": "x"}

    gate.clear()
    second = await run(ex, "demo.hold", {}, wait_seconds=0.01)
    gone = await run(ex, "job.cancel", {"job_id": second.job_id})
    assert gone.output["status"] == "cancelled"


async def test_job_cancel_on_a_child_run_says_it_cannot_be_stopped(tmp_path):
    ex, host, *_ = rig(tmp_path)
    from pydantic import BaseModel
    from wasifyai_platform_sdk.actions import RunBinding

    class Any_(BaseModel):
        pass

    class Out(BaseModel):
        pass

    class Never:
        async def __aiter__(self):
            await asyncio.Event().wait()
            yield {}

    host.run_product = lambda pid, gi: Never()  # type: ignore[method-assign]
    ex.registry.add(
        Action(
            id="demo.child", title="Child", summary="s", description="d", input=Any_, output=Out,
            effect="make", long=True, ui="chat",
            bind=RunBinding("p", "thing", lambda p, c: {}, lambda o, p: None),
        )
    )  # fmt: skip
    started = await run(ex, "demo.child", {}, wait_seconds=0.01)
    r = await run(ex, "job.cancel", {"job_id": started.job_id})
    assert (r.status, r.code) == ("refused", "not_cancellable")
    assert "saved to the library" in r.text
    job = ex.jobs.get("t1", "u1", started.job_id or "")
    assert job and job.task
    job.task.cancel()
    await asyncio.gather(job.task, return_exceptions=True)


async def test_an_unknown_job_is_not_a_leak(tmp_path):
    ex, *_ = rig(tmp_path)
    for action in ("job.status", "job.wait", "job.cancel"):
        r = await run(ex, action, {"job_id": "nope"})
        assert (r.status, r.code) == ("refused", "unknown_job"), action


async def test_a_job_from_before_a_restart_is_answered_from_the_audit_log(tmp_path):
    from wasifyai_platform_sdk.actions import AuditEntry

    ex, _, _, audit = rig(tmp_path)
    await audit.record(
        AuditEntry(
            tenant_id="t1", product_id="demo", user_id="u1", action_id="video.generate",
            origin="assistant", status="running", job_id="oldjob",
        )
    )  # fmt: skip
    r = await run(ex, "job.status", {"job_id": "oldjob"})
    assert r.ok and r.output["status"] == "unknown" and "Look in the library" in r.text
    await audit.record(
        AuditEntry(
            tenant_id="t1", product_id="demo", user_id="u1", action_id="video.generate",
            origin="assistant", status="ok", job_id="oldjob",
        )
    )  # fmt: skip
    ended = await run(ex, "job.status", {"job_id": "oldjob"})
    assert ended.output["status"] == "ok"
    other = await ex.run_action(
        "job.status", {"job_id": "oldjob"}, "assistant", actor=Identity("t1", "u2"), policy=AUTO
    )
    assert other.code == "unknown_job"


def test_the_builtin_catalogue():
    ids = [a.id for a in builtin_actions()]
    assert ids == sorted(set(ids)) or len(ids) == len(set(ids))
    assert {a.id: a.effect for a in builtin_actions()}["library.delete"] == "destroy"
    assert {a.id for a in builtin_actions() if a.effect == "destroy"} == {"library.delete"}


@pytest.mark.parametrize("bad", [{}, {"kind": "image"}, {"kind": "banana", "id": "x"}])
async def test_library_ids_and_kinds_are_checked(tmp_path, bad):
    ex, *_ = rig(tmp_path)
    r = await run(ex, "library.get", bad)
    assert (r.status, r.code) == ("refused", "invalid_input")


_: Any = None
