# pyright: reportAttributeAccessIssue=false
"""Outputs a worker makes: the engine's program queues them, a worker takes and makes them."""

import json

import pytest
from test_notebooks_chat import BUDGET, PEOPLE, Rig, ctx  # noqa: F401  (ctx is a fixture)
from test_notebooks_studio import CARDS, REPORT, studio
from wasifyai_notebooks.output_job import OutputRequest, OutputWorker
from wasifyai_notebooks.store import Conflict

pytestmark = pytest.mark.usefixtures("use_backends")  # on SQLite and on Postgres

T, U = "t1", "u1"


def claim(rig):
    job = rig.store.claim_output()
    assert job is not None
    return job


async def queued_rig(tmp_path, replies, turns=None):
    rig = Rig(tmp_path, turns or [{"text": "x"}], replies=replies)
    await rig.add("budget.txt", BUDGET)
    await rig.add("hr.txt", PEOPLE)
    rig.runtime.outputs_by_worker = True  # the web: the engine's program only queues
    return rig


async def test_the_engine_queues_an_output_and_a_worker_makes_it(tmp_path, ctx):  # noqa: F811
    rig = await queued_rig(tmp_path, [REPORT])
    state, events = await studio(rig, "report", "the launch")
    assert state["status"] == "done" and state["title"] == ""  # not made yet
    aid = state["artifact_id"]
    waiting = rig.store.get_artifact(T, U, rig.nb["id"], aid)
    assert waiting["status"] == "processing" and waiting["file_name"] is None
    assert rig.model.prompts == []  # the engine's program asked the model nothing
    assert [e["node"] for e in events if e["type"] == "node"] == []

    job = claim(rig)
    assert (job["id"], job["tenant"], job["user"]) == (aid, T, U)
    request = OutputRequest.from_json(job["request"])
    assert request.format == "report" and request.prompt == "the launch"
    assert len(request.document_ids) == 2 and request.context > 0

    worker = OutputWorker(rig.runtime, rig.caps)
    await worker.run_one(job)
    art = rig.store.get_artifact(T, U, rig.nb["id"], aid, content=True)
    assert art["status"] == "ready" and art["title"] == "Launch plan"
    assert art["body"].startswith("# Launch plan") and art["file_name"] == "launch-plan.md"
    saved = rig.runtime.files_for(T, U).read_bytes(f"artifacts/{rig.nb['id']}/{aid}/launch-plan.md")
    assert saved is not None and saved.decode().startswith("# Launch plan")
    assert "$350,000" in str(rig.model.prompts[0])  # the sources, under the prompt for its tier


async def test_a_queued_output_is_taken_once_and_in_order(tmp_path, ctx):  # noqa: F811
    rig = await queued_rig(tmp_path, [json.dumps(CARDS)] * 2)
    first, _ = await studio(rig, "flashcards", "one")
    second, _ = await studio(rig, "flashcards", "two")
    a, b = claim(rig), claim(rig)
    assert [a["id"], b["id"]] == [first["artifact_id"], second["artifact_id"]]
    assert rig.store.claim_output() is None  # both are taken; none twice


async def test_a_stopped_output_is_skipped_and_a_lost_one_failed_when_stale(tmp_path, ctx):  # noqa: F811
    rig = await queued_rig(tmp_path, [REPORT] * 3)
    stopped, _ = await studio(rig, "report", "stopped")
    waiting, _ = await studio(rig, "report", "waiting")
    lost, _ = await studio(rig, "report", "lost")
    rig.store.cancel_artifact(T, U, rig.nb["id"], stopped["artifact_id"])
    with pytest.raises(Conflict):
        rig.store.cancel_artifact(T, U, rig.nb["id"], stopped["artifact_id"])
    taken = claim(rig)
    assert taken["id"] == waiting["artifact_id"]  # the stopped one was skipped
    assert rig.store.output_is_active(waiting["artifact_id"])
    assert not rig.store.output_is_active(stopped["artifact_id"])

    # a reader that took one and went away: failed once stale; a queued one nobody reached stays
    with rig.store._tx() as db:
        db.execute(
            "UPDATE artifacts SET updated_at = '2020-01-01T00:00:00.000+00:00' WHERE id IN (?, ?)",
            (waiting["artifact_id"], lost["artifact_id"]),
        )
    rig.store.reset_interrupted(1800)
    got = {
        k: rig.store.get_artifact(T, U, rig.nb["id"], v["artifact_id"])["status"]
        for k, v in (("taken", waiting), ("queued", lost))
    }
    assert got == {"taken": "failed", "queued": "processing"}
    assert claim(rig)["id"] == lost["artifact_id"]  # still there for a reader


async def test_the_worker_loop_makes_what_is_queued(tmp_path, ctx):  # noqa: F811
    rig = await queued_rig(tmp_path, [json.dumps(CARDS)])
    state, _ = await studio(rig, "flashcards")
    worker = OutputWorker(rig.runtime, rig.caps)
    worker.start()
    try:
        await worker.drain(20)
    finally:
        await worker.stop()
    art = rig.store.get_artifact(T, U, rig.nb["id"], state["artifact_id"], content=True)
    assert art["status"] == "ready" and art["data"]["cards"][0]["back"] == "$350,000."


async def test_a_failed_model_marks_the_output_failed_in_words(tmp_path, ctx):  # noqa: F811
    rig = await queued_rig(tmp_path, ["not json at all", "still not json"], [{"text": "x"}])
    state, _ = await studio(rig, "flashcards")
    job = claim(rig)
    await OutputWorker(rig.runtime, rig.caps).run_one(job)
    art = rig.store.get_artifact(T, U, rig.nb["id"], state["artifact_id"])
    assert art["status"] == "failed" and "reply could not be used" in art["error"]


async def test_a_guide_is_made_by_the_engine_even_with_a_worker_for_outputs(tmp_path, ctx):  # noqa: F811
    guide = {
        "summary": "A launch plan.",
        "topics": ["Budget"],
        "questions": ["What is the budget?"],
    }
    rig = await queued_rig(tmp_path, [json.dumps(guide)])
    state, _ = await studio(rig, "guide")
    assert state["status"] == "done"
    assert rig.store.claim_output() is None  # nothing was queued
    assert rig.store.get_guide(T, U, rig.nb["id"])["ready"] is True
