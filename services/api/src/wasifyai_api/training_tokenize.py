"""How the picture model's tokenizer splits magic words (ADR-0076 decision 3).

Run by the engine in the trainer's own environment (the only place `tokenizers` is installed):

    python -I training_tokenize.py <tokenizer.json> '["marlo", "zebrik"]'

and prints `{"marlo": {"pieces": ["mar", "lo"], "known": []}, ...}`. A word is read the way it
appears inside a caption (after a space). `known` lists the pieces of four letters or more that the
tokenizer also has as a word of their own: a word made of those would mix with what the model
already means by them. This module imports nothing of the app, so it runs anywhere `tokenizers`
does."""

import json
import sys

MIN_KNOWN = 4  # a shorter piece is a fragment, not a word


def split(tok, word: str) -> dict:
    pieces = [p.lstrip("Ġ") for p in tok.encode(" " + word).tokens]
    known = [
        p for p in pieces if len(p) >= MIN_KNOWN and tok.token_to_id("Ġ" + p.lower()) is not None
    ]
    return {"pieces": pieces, "known": known}


def main(argv: list[str]) -> int:
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(argv[1])
    words = [str(w) for w in json.loads(argv[2])][:64]
    print(json.dumps({w: split(tok, w) for w in words}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
