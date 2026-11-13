"""The files of a composition: a folder with `index.html` (written from the template and the
slots), a vendored GSAP, and a copy of the slots. The folder is rewritten whenever the slots change,
so what is on disk is always what the template makes of them."""

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from wasifyai_video.builder.templates import render_html

GSAP_NAME = "gsap.min.js"


def _slug(text: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:24] or "x"
    return f"{safe}-{hashlib.sha256(text.encode()).hexdigest()[:8]}"


def project_dir(root: Path, tenant: str, user: str, cid: str, variant: str = "") -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", cid):
        raise ValueError("not a composition id")
    folder = root / "projects" / _slug(tenant) / _slug(user) / cid
    if not variant:
        return folder
    if not variant.isalnum():
        raise ValueError("not a shape")
    return folder.with_name(f"{folder.name}-{variant}")


def write_project(
    folder: Path,
    template: str,
    slots: dict[str, Any],
    gsap: Path,
    fonts: dict[str, Path] | None = None,
) -> None:
    """(Re)write the composition's files. The page is written last, so a folder that was cut
    short is never a page without its library or its fonts."""
    (folder / "vendor" / "fonts").mkdir(parents=True, exist_ok=True)
    vendored = folder / "vendor" / GSAP_NAME
    if not vendored.is_file() or vendored.stat().st_size != gsap.stat().st_size:
        shutil.copyfile(gsap, vendored)
    for name, source in (fonts or {}).items():
        target = folder / "vendor" / "fonts" / name
        if not target.is_file() or target.stat().st_size != source.stat().st_size:
            shutil.copyfile(source, target)
    (folder / "slots.json").write_text(json.dumps({"template": template, **slots}, indent=2))
    page = folder / "index.html.part"
    page.write_text(render_html(template, slots))
    page.replace(folder / "index.html")


def read_page(folder: Path) -> str:
    return (folder / "index.html").read_text()


def remove_project(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)
