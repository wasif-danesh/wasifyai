"""The writing trainer's engine: the config it builds, what it reads from the tool's output, and a
run through a stand-in for the trainer's Python (the real run is by hand: ADR-0074)."""

import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import pytest
from wasifyai_api import desktop_language_training as dl
from wasifyai_api import training_setup as ts
from wasifyai_training.language import LanguageJob, Stopped

# the trainer's Python, as a script: the launcher in, a few `mlx_lm` lines and an adapter out
FAKE = f"""#!{sys.executable}
import json, os, sys, time
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
script = args[1] if len(args) > 1 else ""
mode = os.environ.get("FAKE_MODE", "ok")
if script.endswith("language_answer.py"):
    spec = json.loads(args[2])
    if mode == "answer_fails":
        sys.stderr.write("no such model"); sys.exit(1)
    tag = "mine" if spec["adapter"] else "original"
    print("a stray line")
    print(json.dumps({{"answers": [tag + ": " + q for q in spec["questions"]]}}))
elif script.endswith("language_train.py"):
    cfg = json.load(open(args[3]))
    print("Loading pretrained model", flush=True)
    print("Iter 1: Val loss 5.000, Val took 0.1s", flush=True)
    for i in range(1, cfg["iters"] + 1):
        if mode == "slow": time.sleep(5)
        loss = 3.0 / i
        line = f"Iter {{i}}: Train loss {{loss:.3f}}, Learning Rate 2e-04, Peak mem 1.2 GB"
        print(line, flush=True)
    print(f"Iter {{cfg['iters']}}: Val loss 2.500, Val took 0.1s", flush=True)
    if mode == "crash":
        print("ValueError: something broke", flush=True); sys.exit(2)
    if mode != "no_adapter":
        os.makedirs(cfg["adapter_path"], exist_ok=True)
        open(cfg["adapter_path"] + "/adapters.safetensors", "wb").write(b"x")
else:
    sys.exit(3)
"""


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    py = tmp_path / "venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text(FAKE)
    py.chmod(py.stat().st_mode | stat.S_IXUSR)
    base = tmp_path / "models" / "qwen3-0.6b-4bit"
    base.mkdir(parents=True)
    (base / "config.json").write_text(json.dumps({"num_hidden_layers": 4}))
    monkeypatch.setenv("WASIFYAI_MLXLM_DIR", str(tmp_path / "venv"))
    monkeypatch.setenv("WASIFYAI_LANGUAGE_BASE_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "calls.log"))
    monkeypatch.delenv("FAKE_MODE", raising=False)
    monkeypatch.setattr(ts, "apple_silicon", lambda: True)
    monkeypatch.setattr(dl, "apple_silicon", lambda: True)
    return tmp_path


def job(steps: int = 3) -> LanguageJob:
    rows = [
        {"messages": [{"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": "a"}]}
        for i in range(4)
    ]
    return LanguageJob(rows[:3], rows[3:], steps, ["q0", "q1"])


def calls(home: Path) -> list[list[str]]:
    return [json.loads(line) for line in (home / "calls.log").read_text().splitlines()]


def test_the_config_teaches_every_projection_of_every_layer_and_checks_on_what_was_kept_back(home):
    base = home / "models" / "qwen3-0.6b-4bit"
    c = dl.config_for(job(40), base, home / "data", home / "adapter")
    assert c["model"] == str(base) and c["data"] == str(home / "data")
    assert c["num_layers"] == 4 and c["iters"] == 40 and c["batch_size"] == 2
    assert c["fine_tune_type"] == "lora" and c["mask_prompt"] is True
    assert c["lora_parameters"]["rank"] == 16 and len(c["lora_parameters"]["keys"]) == 7
    assert c["learning_rate"] == 2e-4 and c["steps_per_eval"] == 10 and c["val_batches"] == -1
    assert c["adapter_path"] == str(home / "adapter") and "resume_adapter_file" not in c
    again = dl.config_for(
        job(40), base, home / "data", home / "adapter", resume=home / "a.safetensors"
    )
    assert again["resume_adapter_file"] == str(home / "a.safetensors")


def test_the_examples_are_written_as_chat_records_for_learning_and_for_checking(home):
    dl.write_data(job(), home / "data")
    train = (home / "data" / "train.jsonl").read_text().splitlines()
    valid = (home / "data" / "valid.jsonl").read_text().splitlines()
    assert len(train) == 3 and len(valid) == 1
    assert json.loads(valid[0])["messages"][0] == {"role": "user", "content": "q3"}


def test_what_the_tool_says_is_read_as_progress_and_loss():
    line = "Iter 10: Train loss 2.345, Learning Rate 2.000e-04, It/sec 3.1, Peak mem 1.234 GB"
    assert dl.parse_line(line) == {
        "step": 10, "train": 2.345, "peak_gb": 1.234,
    }  # fmt: skip
    assert dl.parse_line("Iter 25: Val loss 1.250, Val took 0.5s") == {"step": 25, "val": 1.25}
    assert dl.parse_line("Iter 25: Saved adapter weights to x.") is None
    assert dl.parse_line("Loading pretrained model") is None


def test_it_says_in_words_why_it_cannot_run(home, monkeypatch: pytest.MonkeyPatch):
    eng = dl.MlxLmTrainer(home)
    assert eng.problem("qwen3-0.6b-4bit") is None and eng.ready("qwen3-0.6b-4bit")
    assert "not on this computer" in (eng.problem("another") or "")
    monkeypatch.setenv("WASIFYAI_MLXLM_DIR", str(home / "nowhere"))
    assert "not set up" in (eng.problem() or "")
    monkeypatch.setattr(dl, "apple_silicon", lambda: False)
    assert "Apple silicon" in (eng.problem() or "") and "NVIDIA" in (eng.problem() or "")


@pytest.mark.asyncio
async def test_a_run_goes_through_the_launcher_and_leaves_an_adapter_and_the_losses(home):
    eng = dl.MlxLmTrainer(home)
    seen: list[tuple[int, str]] = []
    result = await eng.train(
        job(3), "qwen3-0.6b-4bit", home / "run", lambda s, m: seen.append((s, m))
    )
    assert (result.adapter / "adapters.safetensors").is_file()
    assert result.first_val == 5.0 and result.last_val == 2.5 and result.last_train == 1.0
    assert [s for s, _ in seen][-1] == 3 and seen[0] == (0, "Loading the model")
    assert "Learning, step 3 of 3" in [m for _, m in seen]
    (call,) = calls(home)
    assert call[0] == "-I" and call[1].endswith("language_train.py") and call[2] == "-c"
    assert json.loads(await asyncio.to_thread(Path(call[3]).read_text))["iters"] == 3
    assert (home / "run" / "data" / "valid.jsonl").is_file()


@pytest.mark.asyncio
async def test_a_tool_that_fails_or_leaves_nothing_says_so(home, monkeypatch: pytest.MonkeyPatch):
    eng = dl.MlxLmTrainer(home)
    monkeypatch.setenv("FAKE_MODE", "crash")
    with pytest.raises(RuntimeError, match="something broke"):
        await eng.train(job(2), "qwen3-0.6b-4bit", home / "run", lambda s, m: None)
    monkeypatch.setenv("FAKE_MODE", "no_adapter")
    with pytest.raises(RuntimeError, match="without an adapter"):
        await eng.train(job(2), "qwen3-0.6b-4bit", home / "run2", lambda s, m: None)


@pytest.mark.asyncio
async def test_stopping_a_run_ends_it_and_keeps_nothing(home, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FAKE_MODE", "slow")
    eng = dl.MlxLmTrainer(home)
    running = asyncio.create_task(
        eng.train(job(3), "qwen3-0.6b-4bit", home / "run", lambda s, m: None)
    )
    for _ in range(100):
        if eng.busy:
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.5)
    await eng.stop()
    with pytest.raises(Stopped):
        await running
    assert not (home / "run" / "adapter").exists()


@pytest.mark.asyncio
async def test_the_model_is_asked_with_or_without_the_adapter(
    home, monkeypatch: pytest.MonkeyPatch
):
    eng = dl.MlxLmTrainer(home)
    assert await eng.answer("qwen3-0.6b-4bit", ["a?", "b?"]) == ["original: a?", "original: b?"]
    assert await eng.answer("qwen3-0.6b-4bit", ["a?"], home / "adapter") == ["mine: a?"]
    first, second = calls(home)
    assert first[1].endswith("language_answer.py")
    assert json.loads(second[2])["adapter"] == str(home / "adapter")
    assert os.environ.get("HF_HUB_OFFLINE") is None  # the engine's own environment is left alone
    monkeypatch.setenv("FAKE_MODE", "answer_fails")
    with pytest.raises(RuntimeError, match="no such model"):
        await eng.answer("qwen3-0.6b-4bit", ["a?"])
