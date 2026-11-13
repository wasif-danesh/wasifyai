"""How a Laya model answers a question about some texts.

Run by the decision trainer with the trainer's own Python (`python -I decision_answer.py <json>`),
never imported by the engine: it needs `laya` and PyTorch, which only that environment has. It reads
one JSON object on the command line, `{model, question, texts}` (the question in Laya's own format),
loads the model once, answers every text and prints one JSON object on the last line:
`{answers: [<raw answer>...]}`. The answers are the model's own (`choice`, `noul` or `probabilities`
with how sure it is); the engine turns them into the product's words."""

import json
import os
import sys

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def main() -> None:
    spec = json.loads(sys.argv[1])
    import laya  # type: ignore[import-not-found]
    from laya.train import resolve_device  # type: ignore[import-not-found]

    agent = laya.load(spec["model"], device=resolve_device("auto").type)
    texts, out = spec["texts"], []
    for i in range(0, len(texts), 32):
        for r in agent.predict_batch(texts[i : i + 32], {"answer": spec["question"]}):
            out.append(r["answers"]["answer"])
    print(json.dumps({"answers": out}, ensure_ascii=False))


if __name__ == "__main__":
    main()
