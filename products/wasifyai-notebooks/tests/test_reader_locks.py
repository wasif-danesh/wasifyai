"""The document reader's lock files are committed (scripts/lock-reader.sh), so a development
checkout can set the reader up the same way the engine bundle does. A checkout without them said
"The reader is not part of this build" and Notebooks could not read a PDF, a Word file or a picture
of text."""

import re
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from wasifyai_notebooks.reader_install import uv_target
from wasifyai_notebooks.runtime import _installer

REPO = Path(__file__).resolve().parents[3]
READER = REPO / "products" / "wasifyai-notebooks" / "reader"
TARGETS = (
    "aarch64-apple-darwin",
    "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu",
    "x86_64-pc-windows-msvc",
)


@pytest.mark.parametrize("target", TARGETS)
def test_every_platform_has_a_hashed_lock(target):
    lock = READER / f"requirements-{target}.lock"
    assert lock.is_file(), f"run scripts/lock-reader.sh and commit {lock.name}"
    text = lock.read_text()
    pinned = re.findall(r"^[A-Za-z0-9_.\-\[\]]+==", text, flags=re.MULTILINE)
    assert pinned, "the lock has no pinned packages"
    assert text.count("--hash=sha256:") >= len(pinned), "every package needs a hash"
    assert re.search(r"^docling==", text, flags=re.MULTILINE)


def test_a_development_checkout_finds_the_lock_for_its_platform(tmp_path):
    if uv_target() not in TARGETS:
        pytest.skip("no reader lock for this platform")
    if not shutil.which("uv"):
        pytest.skip("uv is needed to set the reader up")
    components = cast(Any, SimpleNamespace(reader_dir=tmp_path / "reader"))
    installer, why = _installer(tmp_path, components, REPO / "products")
    assert installer is not None and why == ""


def test_the_bundle_copies_the_committed_locks():
    script = (REPO / "scripts" / "build-engine-bundle.sh").read_text()
    assert "requirements-*.lock" in script and "lock-reader.sh" in script
