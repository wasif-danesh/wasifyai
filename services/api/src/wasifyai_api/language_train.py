"""Run `mlx_lm lora` with the chat template as the chat engine will use it: thinking off.

Run by the language trainer with the trainer's own Python
(`python -I language_train.py -c <config>`), never imported by the engine. The chat template of
Qwen3 models writes an empty `<think></think>` block in front of an answer when thinking is off,
and the chat engine puts that block in the prompt (ADR-0074: the served prompt equals the trained
one only with thinking off). `mlx-lm` renders the training text with the template's default,
which is thinking on: the block then sits in the *answer*, is learnt as something to write, and
an adapter taught that way writes it again after the prompt that already has it, so answers
start with a stray `</think>` (measured: 6 of 6 after 30 steps). With thinking off for every
template call (`mlx-lm`'s tokenizer wrapper asks for thinking whenever the model has the tokens
for it) the block is part of the masked prompt and the loss covers only the answer, which is
exactly what is served (0 of 6 stray, 6 of 6 in the taught style, at 30 and at 69 steps)."""

import sys


def main() -> None:
    # the trainer's own environment, not the engine's
    from mlx_lm.lora import main as lora_main  # type: ignore[import-not-found]
    from mlx_lm.tokenizer_utils import TokenizerWrapper  # type: ignore[import-not-found]

    # the wrapper asks the template for thinking whenever the model has the tokens for it
    TokenizerWrapper.has_thinking = property(lambda self: False)  # type: ignore[method-assign,assignment]
    sys.argv = ["mlx_lm.lora", *sys.argv[1:]]
    lora_main()


if __name__ == "__main__":
    main()
