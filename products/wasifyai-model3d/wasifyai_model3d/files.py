"""Saving a copy of a model into the person's export folder: never replaces a file."""

import re
import shutil
from pathlib import Path


def file_stem(title: str) -> str:
    """A safe, readable file name from the title: letters, digits and hyphens only."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48].strip("-") or "model"


def save_copy(folder: Path, stem: str, source: Path, ext: str = "glb") -> Path:
    """Copy `source` to `stem.ext` in `folder`, or `stem-2.ext` and so on if that name is taken."""
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / f"{stem}.{ext}", 1
    while True:
        try:
            with path.open("xb") as out, source.open("rb") as src:  # exclusive: never replaces
                shutil.copyfileobj(src, out, 1 << 20)
            return path
        except FileExistsError:
            n += 1
            path = folder / f"{stem}-{n}.{ext}"
