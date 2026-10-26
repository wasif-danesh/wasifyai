# ruff: noqa: E501  (prose in the docstrings and a script in a string are easier to read on one line)
"""The decision trainer's engine: the job it builds, what it reads from the tool's output, and a run
through a stand-in for the trainer's Python (the real run is by hand: ADR-0075)."""

import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import pytest
from wasifyai_api import desktop_decision_training as dd
from wasifyai_api import training_setup as ts
from wasifyai_training.decision import DecisionJob, Option, Question, Row
from wasifyai_training.language import Stopped

# the trainer's Python, as a script: the job in, a few events out
FAKE = f"""#!{sys.executable}
import json, os, shutil, sys, time
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
script = args[1] if len(args) > 1 else ""
mode = os.environ.get("FAKE_MODE", "ok")

def raw(pick, n):
    other = [a for a in ("billing", "bug") if a != pick][0]
    return {{"type": "choice", "choice": pick, "probabilities": {{pick: 0.9, other: 0.1}}}}

def emit(**e):
    print(json.dumps(e), flush=True)

if script.endswith("decision_answer.py"):
    spec = json.loads(args[2])
    if mode == "answer_fails":
        sys.stderr.write("no such model"); sys.exit(1)
    print("a stray line")
    print(json.dumps({{"answers": [raw("bug" if "crash" in t else "billing", 0) for t in spec["texts"]]}}))
elif script.endswith("decision_train.py"):
    job = json.load(open(args[3]))
    print("a line from a library", flush=True)
    emit(event="status", message="Loading the model")
    emit(event="before", held=[raw("billing", 0) for _ in job["held"]], peek=[raw("billing", 0) for _ in job["peek"]])
    for i in range(1, job["steps"] + 1):
        if mode == "slow": time.sleep(5)
        emit(event="progress", step=i, total=job["steps"], loss=1.0 / i)
    emit(event="epoch", epoch=1, loss=0.5)
    emit(event="epoch", epoch=2, loss=0.1)
    if mode == "crash":
        print("ValueError: something broke", flush=True); sys.exit(2)
    if mode != "no_model":
        os.makedirs(job["out"], exist_ok=True)
        open(job["out"] + "/model.safetensors", "wb").write(b"x" * 10)
    emit(event="after", held=[raw("bug", 0) for _ in job["held"]], peek=[raw("bug", 0) for _ in job["peek"]])
    emit(event="done", seconds=1.0)
else:
    sys.exit(3)
"""


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    py = tmp_path / "venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text(FAKE)
    py.chmod(py.stat().st_mode | stat.S_IXUSR)
    base = tmp_path / "models" / "laya-english"
    base.mkdir(parents=True)
    (base / "rl_agent_config.json").write_text("{}")
    monkeypatch.setenv("WASIFYAI_LAYA_DIR", str(tmp_path / "venv"))
    monkeypatch.setenv("WASIFYAI_DECISION_BASE_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "calls.log"))
    monkeypatch.delenv("FAKE_MODE", raising=False)
    monkeypatch.setattr(ts, "apple_silicon", lambda: True)
    monkeypatch.setattr(dd, "apple_silicon", lambda: True)
    return tmp_path


def question() -> Question:
    return Question(
        "category", "Which team?", (Option("billing", "money"), Option("bug", "broken"))
    )


def job(steps: int = 3) -> DecisionJob:
    train = [Row(f"billing {i}", "billing") for i in range(3)] + [Row("crash", "bug")]
    return DecisionJob(
        question(),
        train,
        [Row("a crash", "bug"), Row("a refund", "billing")],
        2,
        steps,
        ["a crash"],
    )


def calls(home: Path) -> list[list[str]]:
    return [json.loads(line) for line in (home / "calls.log").read_text().splitlines()]


def test_the_job_names_the_question_in_the_models_format_and_the_right_answers(home):
    j = dd.to_job(job(), home / "models" / "laya-english", home / "out")
    assert j["question"] == question().laya() and j["epochs"] == 2 and j["batch"] == 8
    assert j["train"][-1] == {"text": "crash", "expected": "bug"}
    assert j["held"] == ["a crash", "a refund"] and j["peek"] == ["a crash"]
    yes = DecisionJob(
        Question("yes_no", "Good?"), [Row("fine", "yes"), Row("bad", "no")], [], 1, 2, []
    )
    assert [r["expected"] for r in dd.to_job(yes, home, home)["train"]] == [True, False]


def test_it_says_in_words_why_it_cannot_run(home, monkeypatch: pytest.MonkeyPatch):
    eng = dd.LayaTrainer(home)
    assert eng.problem("laya-english") is None and eng.ready("laya-english")
    assert "not on this computer" in (eng.problem("another") or "")
    assert eng.base_folder("laya-english") == home / "models" / "laya-english"
    monkeypatch.setenv("WASIFYAI_LAYA_DIR", str(home / "nowhere"))
    assert "not set up" in (eng.problem() or "")
    monkeypatch.setattr(dd, "apple_silicon", lambda: False)
    assert "Apple silicon" in (eng.problem() or "") and "NVIDIA" in (eng.problem() or "")


@pytest.mark.asyncio
async def test_a_run_goes_through_the_script_and_leaves_a_model_with_the_answers_before_and_after(
    home,
):
    eng = dd.LayaTrainer(home)
    seen: list[tuple[int, str]] = []
    result = await eng.train(job(3), "laya-english", home / "run", lambda s, m: seen.append((s, m)))
    assert (result.folder / "model.safetensors").is_file() and result.bytes == 10
    assert [s.answer for s in result.before] == ["billing", "billing"]
    assert [s.answer for s in result.after] == ["bug", "bug"] and result.after[0].confidence == 0.9
    assert [s.answer for s in result.peek_after] == ["bug"] and result.loss == [0.5, 0.1]
    assert seen[0] == (0, "Loading the model") and seen[-1] == (3, "Learning, step 3 of 3")
    (call,) = calls(home)
    assert call[0] == "-I" and call[1].endswith("decision_train.py") and call[2] == "-c"
    assert not (home / "run" / "job.json").exists()  # the job file is not kept


@pytest.mark.asyncio
async def test_a_tool_that_fails_or_leaves_nothing_says_so(home, monkeypatch: pytest.MonkeyPatch):
    eng = dd.LayaTrainer(home)
    monkeypatch.setenv("FAKE_MODE", "crash")
    with pytest.raises(RuntimeError, match="something broke"):
        await eng.train(job(2), "laya-english", home / "run", lambda s, m: None)
    monkeypatch.setenv("FAKE_MODE", "no_model")
    with pytest.raises(RuntimeError, match="without a model"):
        await eng.train(job(2), "laya-english", home / "run2", lambda s, m: None)


@pytest.mark.asyncio
async def test_stopping_a_run_ends_it_and_keeps_nothing(home, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FAKE_MODE", "slow")
    eng = dd.LayaTrainer(home)
    running = asyncio.create_task(
        eng.train(job(3), "laya-english", home / "run", lambda s, m: None)
    )
    for _ in range(100):
        if eng.busy:
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.5)
    await eng.stop()
    with pytest.raises(Stopped):
        await running
    assert not (home / "run" / "model").exists()


@pytest.mark.asyncio
async def test_the_model_is_asked_about_texts_and_its_answers_are_read(
    home, monkeypatch: pytest.MonkeyPatch
):
    eng = dd.LayaTrainer(home)
    got = await eng.answer(
        home / "models" / "laya-english", question(), ["it will crash", "a refund"]
    )
    assert [(s.answer, s.confidence) for s in got] == [("bug", 0.9), ("billing", 0.9)]
    assert await eng.answer(home, question(), []) == []
    (call,) = calls(home)
    spec = json.loads(call[2])
    assert call[1].endswith("decision_answer.py") and spec["question"] == question().laya()
    assert spec["texts"] == ["it will crash", "a refund"]
    assert os.environ.get("HF_HUB_OFFLINE") is None  # the engine's own environment is left alone
    monkeypatch.setenv("FAKE_MODE", "answer_fails")
    with pytest.raises(RuntimeError, match="no such model"):
        await eng.answer(home, question(), ["x"])
