"""How a language model answers some questions, with or without a taught adapter.

Run by the language trainer with the trainer's own Python (`python -I language_answer.py <json>`),
never imported by the engine: it needs `mlx_lm`, which only that environment has. It reads one JSON
object on the command line, `{model, adapter, questions, max_tokens}`, loads the model once, applies
the model's own chat template with thinking switched off (the served prompt equals the trained
prompt only that way, ADR-0074) and prints one JSON object on the last line: `{answers: [...]}`.
Greedy decoding, so the same adapter answers the same way twice."""

import json
import sys


def main() -> None:
    spec = json.loads(sys.argv[1])
    from mlx_lm import (  # type: ignore[import-not-found]  # the trainer's own environment
        generate,
        load,
    )

    model, tokenizer = load(spec["model"], adapter_path=spec.get("adapter") or None)
    answers = []
    for question in spec["questions"]:
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": question}],
            add_generation_prompt=True,
            tokenize=False,
            enable_thinking=False,
        )
        text = generate(
            model, tokenizer, prompt=prompt, max_tokens=int(spec.get("max_tokens", 120))
        )
        answers.append(text.strip())
    print(json.dumps({"answers": answers}, ensure_ascii=False))


if __name__ == "__main__":
    main()
