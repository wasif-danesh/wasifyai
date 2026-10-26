# ruff: noqa: E501  (prose in the docstrings and a script in a string are easier to read on one line)
"""Teach a Laya model to answer one question about texts, and say how it did before and after.

Run by the decision trainer with the trainer's own Python (`python -I decision_train.py -c <job.json>`),
never imported by the engine: it needs `laya` and PyTorch, which only that environment has. It prints
one JSON object per line on stdout, and nothing else the engine reads:

    {"event": "status", "message": ...}
    {"event": "before", "held": [<raw answer>...], "peek": [...]}    the base model, on the texts kept back
    {"event": "progress", "step": n, "total": m, "loss": x}
    {"event": "epoch", "epoch": e, "loss": mean}
    {"event": "after", "held": [...], "peek": [...]}                 the taught model, on the same texts
    {"event": "done", "seconds": s}

The job file is `{base, out, question, train: [{text, expected}], held: [text], peek: [text],
epochs, batch, seed}`. The finished model is written to `out` in the layout `laya.load` reads (the
per-pass copy the trainer keeps is removed: it is as large as the model itself). Stopping is killing
the process: nothing is kept."""

import contextlib
import gc
import io
import json
import os
import re
import shutil
import sys
import time

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

QID = "answer"
_STEP = re.compile(r"epoch (\d+)/(\d+) step (\d+) loss (-?[\d.]+)")
_EPOCH = re.compile(r"epoch (\d+)/(\d+) mean loss (-?[\d.]+)")


def emit(**event: object) -> None:
    sys.__stdout__.write(json.dumps(event, ensure_ascii=False) + "\n")  # type: ignore[union-attr]
    sys.__stdout__.flush()  # type: ignore[union-attr]


class Lines(io.TextIOBase):
    """Turns the trainer's own progress lines into events; every other line is dropped."""

    def __init__(self, per_epoch: int, total: int):
        self.per_epoch, self.total, self.buf = per_epoch, total, ""

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self.buf += text
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if m := _STEP.search(line):
                step = (int(m.group(1)) - 1) * self.per_epoch + int(m.group(3))
                emit(
                    event="progress",
                    step=min(step, self.total),
                    total=self.total,
                    loss=float(m.group(4)),
                )
            elif m := _EPOCH.search(line):
                emit(event="epoch", epoch=int(m.group(1)), loss=float(m.group(3)))
        return len(text)


def answers(agent, texts: list[str], question: dict) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(texts), 32):
        for r in agent.predict_batch(texts[i : i + 32], {QID: question}):
            out.append(r["answers"][QID])
    return out


def release() -> None:
    import torch  # type: ignore[import-not-found]

    gc.collect()
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()


def main() -> None:
    job = json.load(open(sys.argv[sys.argv.index("-c") + 1], encoding="utf-8"))
    started = time.time()
    import laya  # type: ignore[import-not-found]
    from laya.train import TrainConfig, finetune, resolve_device  # type: ignore[import-not-found]

    device = resolve_device("auto").type
    q = job["question"]
    held, peek = job["held"], job["peek"]
    emit(event="status", message="Loading the model")
    agent = laya.load(job["base"], device=device)
    emit(event="status", message="Asking the model first")
    emit(event="before", held=answers(agent, held, q), peek=answers(agent, peek, q))
    del agent
    release()
    out = job["out"]
    shutil.rmtree(out, ignore_errors=True)
    data = out + ".train.jsonl"
    with open(data, "w", encoding="utf-8") as f:
        for r in job["train"]:
            f.write(
                json.dumps(
                    {"state": r["text"], "questions": {QID: q}, "expected": {QID: r["expected"]}},
                    ensure_ascii=False,
                )
                + "\n"
            )
    config = TrainConfig(
        epochs=int(job["epochs"]),
        micro_batch=int(job["batch"]),
        grad_accum=1,
        log_every=1,
        seed=int(job.get("seed", 3407)),
    )
    # a tenth of the examples is kept back by the trainer to fit how sure the model should be
    n = len(job["train"])
    per_epoch = max(1, -(-(n - min(400, int(n * 0.1))) // int(job["batch"])))
    emit(event="status", message="Learning")
    with contextlib.redirect_stdout(Lines(per_epoch, int(job["steps"]))):
        finetune(data, job["base"], out, config, device=device)
    os.remove(data)
    shutil.rmtree(os.path.join(out, "checkpoint_latest"), ignore_errors=True)
    release()
    emit(event="status", message="Asking it again")
    agent = laya.load(out, device=device)
    emit(event="after", held=answers(agent, held, q), peek=answers(agent, peek, q))
    emit(event="done", seconds=round(time.time() - started, 1))


if __name__ == "__main__":
    main()
