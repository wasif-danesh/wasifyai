"""What each optional component fetches on this platform: `manifests/<platform>.yaml` (stage F2).

One file per platform, so a build carries only what its computer can use and every pin is in one
place a reviewer can read. The files are data, shipped inside the engine, which the shell checks
against the bundle's hashes before it runs it.
"""

import platform as _platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from wasifyai_api.components.core import Archive

MANIFESTS = Path(__file__).with_name("manifests")


def platform_key() -> str:
    arm = _platform.machine().lower() in ("arm64", "aarch64")
    if sys.platform == "darwin":
        return "darwin-arm64" if arm else "darwin-x64"
    if sys.platform == "win32":
        return "windows-x64"
    return "linux-arm64" if arm else "linux-x64"


@dataclass(frozen=True)
class Pins:
    """One component's pins on this platform."""

    id: str
    title: str
    version: str
    licence: str
    source: str
    min_free_bytes: int
    archive: Archive | None
    extra: dict[str, Any]  # what only this component reads (its backend, its lock)


@dataclass(frozen=True)
class Manifest:
    platform: str
    python: str
    components: dict[str, Pins]

    def get(self, component: str) -> Pins | None:
        return self.components.get(component)


def _archive(raw: Any) -> Archive | None:
    if not raw:
        return None
    sha = str(raw["sha256"]).lower()
    if len(sha) != 64:
        raise ValueError(f"{raw.get('url')}: a pin needs a SHA-256")
    return Archive(
        str(raw["url"]), int(raw["size"]), sha, str(raw["kind"]), int(raw.get("strip", 0))
    )


def load_manifest(platform: str | None = None, folder: Path = MANIFESTS) -> Manifest:
    """The manifest of `platform` (this computer's by default); an empty one where there is none."""
    key = platform or platform_key()
    path = folder / f"{key}.yaml"
    if not path.is_file():
        return Manifest(key, "", {})
    raw = yaml.safe_load(path.read_text()) or {}
    if raw.get("schema") != 1:
        raise ValueError(f"{path.name}: unknown schema")
    known = {"title", "version", "licence", "source", "min_free_bytes", "archive"}
    components = {
        cid: Pins(
            cid,
            str(c["title"]),
            str(c["version"]),
            str(c.get("licence", "")),
            str(c.get("source", "")),
            int(c.get("min_free_bytes", 0)),
            _archive(c.get("archive")),
            {k: v for k, v in c.items() if k not in known},
        )  # fmt: skip
        for cid, c in (raw.get("components") or {}).items()
    }
    return Manifest(key, str(raw.get("python", "")), components)
