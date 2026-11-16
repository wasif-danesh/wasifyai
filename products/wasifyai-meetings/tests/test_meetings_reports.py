"""Reports (MT4): a template's report written by the chat model; a long meeting read in overlapping
parts first; failures in words; one at a time; usage recorded."""

import asyncio
from types import SimpleNamespace

import pytest
from wasifyai_meetings import reports
from wasifyai_meetings.reports import ReportJobs, parts_of, transcript_of
from wasifyai_meetings.store import MeetingStore
from wasifyai_platform_sdk import Identity, RunError

ME = Identity("t", "u")


class FakeText:
    def __init__(self, fail: Exception | None = None):
        self.asked: list[tuple[str, str]] = []
        self.fail = fail

    async def complete(self, name, system, prompt, schema=None):  # noqa: ANN001, ANN201
        self.asked.append((system, prompt))
        if self.fail:
            raise self.fail
        return f"# Report {len(self.asked)}\n- a point"


class FakeCaps:
    def __init__(self, text: FakeText):
        self.text = text
        self.used: list[tuple] = []

    async def record_usage(self, kind, quantity, unit, **meta):  # noqa: ANN001, ANN201
        self.used.append((kind, quantity, unit, meta))


def setup(tmp_path, n_lines: int, fail: Exception | None = None):  # noqa: ANN201
    store = MeetingStore.in_folder(tmp_path)
    row = store.add("t", "u", title="Budget call")
    lines = [
        {"start": 7.0 * i, "end": 7.0 * i + 6, "speaker": f"S{i % 2 + 1}",
         "text": f"Point number {i}: the roof costs {i * 100} pounds and Asha will check it."}
        for i in range(n_lines)
    ]  # fmt: skip
    speakers = [
        {"key": "S1", "default": "Speaker 1", "name": "Asha", "seconds": 1.0},
        {"key": "S2", "default": "Speaker 2", "name": "Speaker 2", "seconds": 1.0},
    ]
    store.finish(
        row["id"], seconds=7.0 * n_lines, model_id="m", speakers=speakers, lines=lines, text="",
        timings={}, elapsed_s=1.0,
    )  # fmt: skip
    text = FakeText(fail)
    caps = FakeCaps(text)
    state = SimpleNamespace(caps={"wasifyai-meetings": caps})
    deps = SimpleNamespace(state=state)
    done: list[str] = []

    async def on_done(identity, item):  # noqa: ANN001, ANN202
        done.append(item)

    jobs = ReportJobs(deps, "wasifyai-meetings", lambda _s: store, on_done)  # type: ignore[arg-type]
    return store, row, jobs, text, caps, done


def test_a_short_meeting_is_written_in_one_go(tmp_path):
    store, row, jobs, text, caps, done = setup(tmp_path, 20)

    async def go():  # noqa: ANN202
        r = jobs.start(ME, row["id"], reports.BY_ID["actions"])
        await jobs.wait(r["id"])
        return store.report("t", "u", r["id"])

    got = asyncio.run(go())
    assert got["status"] == "done" and got["title"] == "Action items"
    assert got["text"].startswith("# Report 1")
    assert len(text.asked) == 1
    system, prompt = text.asked[0]
    assert "never make up" in system and "language the meeting was held in" in system
    assert "[0:07] Speaker 2: Point number 1" in prompt and "Asha:" in prompt
    assert reports.BY_ID["actions"].instructions in prompt
    assert caps.used == [("meetings.report", 1, "reports", {"template": "actions"})]
    assert done == [row["id"]]


def test_a_long_meeting_is_read_in_overlapping_parts_then_written_from_the_notes(tmp_path):
    store, row, jobs, text, _, _ = setup(tmp_path, 600)
    full = transcript_of(store.get("t", "u", row["id"]))
    parts = parts_of(full)
    assert len(parts) >= 4

    async def go():  # noqa: ANN202
        r = jobs.start(ME, row["id"], reports.BY_ID["summary"])
        await jobs.wait(r["id"])
        return store.report("t", "u", r["id"])

    got = asyncio.run(go())
    assert got["status"] == "done"
    assert len(text.asked) == len(parts) + 1
    assert "part 1 of" in text.asked[0][1] and "from these notes" in text.asked[-1][1]


def test_parts_overlap_cut_at_lines_and_cover_everything():
    text = "\n".join(f"line {i:04d} " + "x" * 80 for i in range(400))
    parts = parts_of(text, 5000, 600)
    assert all(len(p) <= 5000 for p in parts)
    assert all(p.endswith("\n") for p in parts[:-1])
    for a, b in zip(parts, parts[1:], strict=False):
        assert b.split("\n")[0] in a  # the next part starts inside the last one
    assert parts[0].startswith("line 0000") and parts[-1].endswith("line 0399 " + "x" * 80)
    joined = set("\n".join(parts).split("\n"))
    assert all(line in joined for line in text.split("\n"))


def test_a_chat_model_that_fails_says_so(tmp_path):
    store, row, jobs, _, _, _ = setup(
        tmp_path, 5, RunError("model_missing", "Choose a chat model in Models first.")
    )

    async def go():  # noqa: ANN202
        r = jobs.start(ME, row["id"], reports.BY_ID["summary"])
        await jobs.wait(r["id"])
        return store.report("t", "u", r["id"])

    got = asyncio.run(go())
    assert got["status"] == "failed" and got["error"] == "Choose a chat model in Models first."


def test_one_report_at_a_time_and_none_for_a_meeting_not_made(tmp_path):
    store, row, jobs, _, _, _ = setup(tmp_path, 5)
    working = store.add("t", "u", title="Still going")

    async def go():  # noqa: ANN202
        with pytest.raises(reports.Refused, match="not made yet"):
            jobs.start(ME, working["id"], reports.BY_ID["summary"])
        r = jobs.start(ME, row["id"], reports.BY_ID["summary"])
        with pytest.raises(reports.Refused, match="being written"):
            jobs.start(ME, row["id"], reports.BY_ID["minutes"])
        await jobs.wait(r["id"])

    asyncio.run(go())


def test_own_templates_are_kept_per_person(tmp_path):
    store = MeetingStore.in_folder(tmp_path)
    t = store.add_template("t", "u", "Client update", "What the client asked for.")
    got = reports.template_for(store, ME, t["id"])
    assert got.title == "Client update" and got.id.startswith("own-")
    titles = [x["title"] for x in reports.all_templates(store, ME)]
    assert titles[:6] == ["Summary", "Minutes", "Action items", "Decisions", "Stand-up",
                          "Sales call"] and titles[-1] == "Client update"  # fmt: skip
    assert store.templates("t", "other") == []
