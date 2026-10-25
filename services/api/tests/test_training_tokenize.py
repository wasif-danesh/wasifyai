"""How the picture model's tokenizer splits a magic word, read in the trainer's own environment
(here the engine's, through a stand-in for its `python`)."""

import stat
import sys
from pathlib import Path

import pytest
from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
from wasifyai_api import desktop_training as dt
from wasifyai_api import training_tokenize as tt


def tiny_tokenizer(path: Path) -> Tokenizer:
    """A byte-level BPE like Qwen's, taught a few real words so some are whole tokens."""
    tok = Tokenizer(models.BPE())
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    corpus = ["a sunrise over the brain of a dog", "the sunrise and the brain and the dog"] * 50
    tok.train_from_iterator(
        corpus,
        trainers.BpeTrainer(
            vocab_size=400, initial_alphabet=pre_tokenizers.ByteLevel.alphabet(), min_frequency=2
        ),
    )
    tok.save(str(path))
    return tok


def test_a_word_is_split_as_it_appears_in_a_caption_and_its_known_pieces_are_named(tmp_path: Path):
    tok = tiny_tokenizer(tmp_path / "tokenizer.json")
    common = tt.split(tok, "sunrise")
    assert common["pieces"] == ["sunrise"] and common["known"] == ["sunrise"]
    made_up = tt.split(tok, "zqxvk")
    assert len(made_up["pieces"]) > 1 and made_up["known"] == []
    # a short fragment that happens to be a token is not "a word the model knows"
    assert all(len(p) >= tt.MIN_KNOWN for p in tt.split(tok, "dogzq")["known"])


@pytest.mark.asyncio
async def test_the_engine_reads_it_once_and_remembers(tmp_path: Path, monkeypatch):
    base = tmp_path / "base"
    (base / "tokenizer").mkdir(parents=True)
    tiny_tokenizer(base / "tokenizer" / "tokenizer.json")
    tool = tmp_path / "tool"
    (tool / "bin").mkdir(parents=True)
    runner = tool / "bin" / "python"
    runner.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(dt, "find_tool", lambda *_: (tool, "env"))
    monkeypatch.setattr(dt, "find_base", lambda *_: (base, "cache"))
    trainer = dt.MfluxTrainer(None)
    first = await trainer.tokenize(["sunrise", "zqxvk"])
    assert first is not None and first["sunrise"]["known"] == ["sunrise"]
    assert len(first["zqxvk"]["pieces"]) > 1
    monkeypatch.setattr(
        dt, "TOKENIZE_SCRIPT", tmp_path / "gone.py"
    )  # a second ask needs no process
    again = await trainer.tokenize(["zqxvk"])
    assert again == {"zqxvk": first["zqxvk"]}
    monkeypatch.setattr(dt, "find_base", lambda *_: None)
    assert await dt.MfluxTrainer(None).tokenize(["x"]) is None
