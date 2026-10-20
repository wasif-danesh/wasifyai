"""The shelf of picture readers (ADR-0083, CO2): data checked like the model catalogue."""

from pathlib import Path

import pytest
from wasifyai_api.desktop_vision import SHELF, load_shelf


def test_the_shelf_names_an_exact_file_with_a_checksum_for_the_default_model():
    shelf = load_shelf()
    (entry,) = [e for e in shelf if e.id == "qwen3.5-9b"]
    assert entry.size == 918_166_080 and len(entry.sha256) == 64
    assert entry.url.startswith("https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/")
    assert entry.licence == "Apache-2.0"
    assert any(m in "qwen3.5-9b-q4_k_m.gguf" for m in entry.match)


GOOD = (
    "{id: a, match: [x], title: t, licence: l, source: s, url: %s, name: %s, size: 1, sha256: %s}"
)
SHA = "a" * 64


@pytest.mark.parametrize(
    "bad",
    [
        GOOD % ("http://x/y", "f", SHA),  # not https
        GOOD % ("https://x/y", "f", "abc"),  # not a SHA-256
        GOOD % ("https://x/y", "../f", SHA),  # a name that leaves its folder
        GOOD.replace("id: a", "id: ../a") % ("https://x/y", "f", SHA),
    ],
)
def test_a_bad_entry_is_refused_when_the_shelf_loads(tmp_path: Path, bad: str):
    path = tmp_path / "shelf.yaml"
    path.write_text(f"version: 1\nprojectors:\n  - {bad}\n")
    with pytest.raises(ValueError):
        load_shelf(path)


def test_the_shelf_file_is_where_the_loader_looks():
    assert SHELF.is_file()
