"""Asking (MT5): a meeting goes into a notebook through the notebooks' own actions; a question on
its page goes to a notebook it is in, limited to its source, after the source is read; failures in
words; one question at a time for each person."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from wasifyai_meetings import asking
from wasifyai_meetings.asking import AskJobs, add_to_notebook, note_of
from wasifyai_meetings.store import MeetingStore
from wasifyai_platform_sdk import Identity

ME = Identity("t", "u")


class FakeExecutor:
    """The notebooks' actions as the executor runs them, kept in memory."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.notebooks: dict[str, str] = {"nb-acme": "Acme"}
        self.sources: dict[str, str] = {}
        self.answer = "Asha will check the roof [1]."

    async def run_action(self, action: str, params: dict[str, Any], origin: str, *, actor: Any):
        self.calls.append((action, params))
        assert origin == "window" and actor == ME
        if action == "notebook.list":
            out = {"notebooks": [{"notebook_id": k, "title": v} for k, v in self.notebooks.items()]}
        elif action == "notebook.create":
            nid = f"nb-{len(self.notebooks)}"
            self.notebooks[nid] = params["title"]
            out = {"notebook_id": nid, "title": params["title"]}
        elif action == "notebook.add_source":
            did = f"doc-{len(self.sources)}"
            self.sources[did] = params["content"]
            out = {"document_id": did, "notebook_id": params["notebook_id"]}
        elif action == "notebook.ask":
            cite = {"n": 1, "document_id": params["document_ids"][0],
                    "title": "Meeting: Budget call", "text": "Asha: I'll check it"}  # fmt: skip
            out = {"reply": self.answer, "conversation_id": "c1", "citations": [cite]}
        else:
            raise AssertionError(action)
        return SimpleNamespace(status="ok", output=out, text="", code="")


def setup(tmp_path, states: list[str] | None = None):  # noqa: ANN201
    store = MeetingStore.in_folder(tmp_path)
    row = store.add("t", "u", title="Budget call")
    store.finish(
        row["id"], seconds=120.0, model_id="m",
        speakers=[{"key": "S1", "default": "Speaker 1", "name": "Asha", "seconds": 60.0},
                  {"key": "S2", "default": "Speaker 2", "name": "Speaker 2", "seconds": 40.0}],
        lines=[{"start": 3.0, "end": 6.0, "speaker": "S1", "text": "The roof costs 400 pounds."},
               {"start": 7.0, "end": 9.0, "speaker": "S2", "text": "Can you check it?"},
               {"start": 65.0, "end": 67.0, "speaker": "S1", "text": "I'll check it Friday."}],
        text="", timings={}, elapsed_s=1.0,
    )  # fmt: skip
    ex = FakeExecutor()
    deps = SimpleNamespace(state=SimpleNamespace(actions=ex))
    told = list(states or [])

    def source_state(_deps, _who, _nid, _did):  # noqa: ANN001, ANN202
        return told.pop(0) if told else "ready"

    async def no_wait(_s: float) -> None:
        return None

    jobs = AskJobs(deps, "wasifyai-meetings", lambda _s: store, source_state, no_wait)  # type: ignore[arg-type]
    return store, store.get("t", "u", row["id"]), ex, deps, jobs


def test_the_note_has_the_speakers_the_transcript_and_the_reports(tmp_path):
    store, row, *_ = setup(tmp_path)
    r = store.add_report("t", "u", row["id"], "summary", "Summary")
    store.finish_report(r["id"], "# Summary\n- The roof.")
    note = note_of(row, store.reports_of("t", "u", row["id"]))
    assert note.startswith("Meeting: Budget call\n")
    assert "Speakers: Asha (1 min), Speaker 2 (1 min)" in note and "Length: 2 minutes" in note
    assert "[0:03] Asha: The roof costs 400 pounds." in note
    assert "[1:05] Asha: I'll check it Friday." in note
    assert "Summary (a report written from the transcript)" in note and "- The roof." in note


def test_adding_to_a_notebook_of_theirs_or_a_new_one(tmp_path):
    store, row, ex, deps, _ = setup(tmp_path)

    async def go():  # noqa: ANN202
        mine = await add_to_notebook(deps, store, ME, row["id"], notebook_id="nb-acme")  # type: ignore[arg-type]
        new = await add_to_notebook(deps, store, ME, row["id"])  # type: ignore[arg-type]
        with pytest.raises(asking.Refused, match="not there"):
            await add_to_notebook(deps, store, ME, row["id"], notebook_id="nb-gone")  # type: ignore[arg-type]
        return mine, new

    mine, new = asyncio.run(go())
    assert mine["notebook_title"] == "Acme" and new["notebook_title"] == "Budget call"
    assert [c[0] for c in ex.calls].count("notebook.add_source") == 2
    links = store.in_notebooks("t", "u", row["id"])
    assert {x["notebook_id"] for x in links} == {"nb-acme", new["notebook_id"]}
    # deleting the meeting forgets where it was (the notebook keeps its source)
    store.delete("t", "u", row["id"])
    assert store.in_notebooks("t", "u", row["id"]) == []


def test_a_question_adds_the_meeting_first_waits_for_it_to_be_read_and_cites_it(tmp_path):
    store, row, ex, _, jobs = setup(tmp_path, ["pending", "processing", "ready"])

    async def go():  # noqa: ANN202
        q = jobs.start(ME, row["id"], "What will Asha do?")
        await jobs.wait(q["id"])
        return store.question("t", "u", q["id"])

    got = asyncio.run(go())
    assert got["status"] == "done" and got["reply"] == "Asha will check the roof [1]."
    assert got["citations"][0]["text"] == "Asha: I'll check it"
    assert [c[0] for c in ex.calls] == [
        "notebook.create", "notebook.add_source", "notebook.ask"
    ]  # fmt: skip
    ask = ex.calls[-1][1]
    assert ask["document_ids"] == ["doc-0"] and ask["question"] == "What will Asha do?"
    assert store.questions_of("t", "u", row["id"])[0]["notebook_id"] == got["notebook_id"]


def test_a_later_question_uses_the_notebook_it_is_in_and_one_deleted_there_is_added_again(
    tmp_path,
):
    store, row, ex, deps, jobs = setup(tmp_path, ["ready", "missing", "ready"])
    asyncio.run(add_to_notebook(deps, store, ME, row["id"], notebook_id="nb-acme"))  # type: ignore[arg-type]
    ex.calls.clear()

    async def ask():  # noqa: ANN202
        q = jobs.start(ME, row["id"], "Who spoke first?")
        await jobs.wait(q["id"])
        return store.question("t", "u", q["id"])

    assert asyncio.run(ask())["notebook_id"] == "nb-acme"
    assert [c[0] for c in ex.calls] == ["notebook.ask"]
    ex.calls.clear()
    # the source was deleted in the notebook: a new notebook is made for it
    assert asyncio.run(ask())["status"] == "done"
    assert [c[0] for c in ex.calls] == ["notebook.create", "notebook.add_source", "notebook.ask"]


def test_a_source_the_notebook_could_not_read_says_so(tmp_path):
    store, row, _, _, jobs = setup(tmp_path, ["failed"])

    async def go():  # noqa: ANN202
        q = jobs.start(ME, row["id"], "Anything?")
        await jobs.wait(q["id"])
        return store.question("t", "u", q["id"])

    got = asyncio.run(go())
    assert got["status"] == "failed" and "could not read the meeting" in got["error"]


def test_one_question_at_a_time_for_each_person(tmp_path):
    store, row, _, _, jobs = setup(tmp_path)
    working = store.add("t", "u", title="Still going")

    async def go():  # noqa: ANN202
        with pytest.raises(asking.Refused, match="not made yet"):
            jobs.start(ME, working["id"], "Hello?")
        q = jobs.start(ME, row["id"], "One")
        with pytest.raises(asking.Refused, match="being answered"):
            jobs.start(ME, row["id"], "Two")
        assert not jobs.busy(Identity("t", "someone else"))
        await jobs.wait(q["id"])

    asyncio.run(go())
