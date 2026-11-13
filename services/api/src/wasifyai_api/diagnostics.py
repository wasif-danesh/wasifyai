"""Save diagnostics (stage O2 of the 2026-10-27 plan): one zip a person can send when something
goes wrong, saved where they choose (the window's Save As box; the window cannot write a file).

What is inside, and what is not, is written in the zip's own README. In short: the app and the
computer (versions, platform, memory figures), the state of every optional part, the person's last
50 action audit entries (which action, from where, how it ended, how long; never what was asked),
and the end of the engine's and the installer's logs. No pictures, sounds, documents, prompts or
chats, and keys and tokens are blanked in the logs before anything is written.
"""

import asyncio
import io
import json
import platform
import re
import sys
import zipfile
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from wasifyai_platform_sdk.saving import SaveRefused, write_to_path

from wasifyai_api.identity import Identity, get_identity
from wasifyai_api.services import ApiServices, services_of

LOG_TAIL_BYTES = 2_000_000  # the end of each log: what happened last is what matters
AUDIT_ENTRIES = 50
LOGS = ("engine.log", "provision.log")

# what a log line may carry that must not leave the computer: a bearer token, a Hugging Face or
# other API key, a connection's secret, and `token=`, `secret:`, `password=`, `api_key=` values
_SECRETS = re.compile(
    r"(?P<bearer>Bearer\s+)\S+"
    r"|\b(?:hf|sk|wsfy|ghp|gho|xoxb|AIza)[_-][A-Za-z0-9_\-]{8,}"
    r"|(?P<name>\b(?:token|secret|password|passwd|api[_-]?key|authorization)\b[\"']?\s*[:=]\s*[\"']?)(?:Bearer\s+)?[^\s\"',}]+",
    re.IGNORECASE,
)

README = """Wasify AI diagnostics, made {when} on this computer.

Inside:
  about.json       the app's and the engine's versions, the operating system, the Python version
  machine.json     the computer's memory and accelerator, as the app measures them
  components.json  every optional part of the app (engines, trainers, the reader) and its state
  audit.json       your last {audit} actions: which one, from where, how it ended, how long it took
  logs/            the end of the engine's log and of the installer's log

Not inside: your pictures, videos, sounds, documents, notebooks, prompts, chats or settings.
Keys and tokens in the logs are replaced by [hidden]. Look through the files before you send them.
"""


def redact(text: str) -> str:
    """Blank what looks like a key, a token or a password."""

    def hide(m: re.Match[str]) -> str:
        return (m.group("bearer") or m.group("name") or "") + "[hidden]"

    return _SECRETS.sub(hide, text)


def _tail(path: Path) -> str:
    """The end of a log, from the first whole line."""
    limit = LOG_TAIL_BYTES
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > limit:
                f.seek(size - limit)
                f.readline()  # a partial line
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "unknown"


async def build(s: ApiServices, who: Identity) -> bytes:
    """The zip, in memory (a few megabytes at most)."""
    now = datetime.now(UTC)
    about = {
        "made_at": now.isoformat(timespec="seconds"),
        "engine": _version("wasifyai-api"), "sdk": _version("wasifyai-platform-sdk"),
        "os": platform.platform(), "machine": platform.machine(), "python": sys.version.split()[0],
        "profile": "desktop" if s.desktop_dir is not None else "web",
    }  # fmt: skip
    machine: dict[str, Any] = {}
    if s.desktop_models is not None:
        try:
            machine = (await s.desktop_models.machine()).public()
        except Exception as e:  # noqa: BLE001 - a figure that cannot be read is said, not raised
            machine = {"error": type(e).__name__}
    components = []
    if s.components is not None:
        for c in s.components.components.values():
            try:
                components.append({"id": c.id, "title": c.title, "status": c.status()})
            except Exception as e:  # noqa: BLE001
                components.append({"id": c.id, "title": c.title, "error": type(e).__name__})
    audit: list[dict[str, Any]] = []
    if s.actions is not None:
        entries = await s.actions.audit.recent(who.tenant_id, who.user_id, AUDIT_ENTRIES)
        audit = [e.model_dump(mode="json") for e in entries]
    logs = (s.desktop_dir / "logs") if s.desktop_dir is not None else None
    tails = (
        {name: redact(await asyncio.to_thread(_tail, logs / name)) for name in LOGS}
        if logs is not None
        else {}
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README.format(when=about["made_at"], audit=AUDIT_ENTRIES))
        z.writestr("about.json", json.dumps(about, indent=2))
        z.writestr("machine.json", json.dumps(machine, indent=2))
        z.writestr("components.json", json.dumps(components, indent=2))
        z.writestr("audit.json", json.dumps(audit, indent=2))
        for name, text in tails.items():
            z.writestr(f"logs/{name}", text)
    return buf.getvalue()


def file_name(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%d-%H%M")
    return f"wasify-diagnostics-{stamp}.zip"


router = APIRouter(prefix="/desktop/diagnostics", tags=["desktop"])


class SaveIn(BaseModel):
    path: str  # where the person chose to save it (the window's Save As box)


@router.get("/name")
async def diagnostics_name(_: Identity = Depends(get_identity)) -> dict[str, str]:
    """The name the Save As box suggests."""
    return {"name": file_name()}


@router.post("")
async def save_diagnostics(
    body: SaveIn, request: Request, who: Identity = Depends(get_identity)
) -> dict[str, Any]:
    s = services_of(request)
    data = await build(s, who)
    try:
        target = await asyncio.to_thread(write_to_path, body.path, data, s.desktop_dir)
    except SaveRefused as e:
        raise HTTPException(422, str(e)) from None
    return {"name": target.name, "path": str(target), "bytes": len(data)}
