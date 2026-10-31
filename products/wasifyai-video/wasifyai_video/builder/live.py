"""The live preview's address and files (ADR-0096 decision 3, spike MX0).

The player in the editor is a frame, and a frame cannot send the person's token in a header. So the
address holds a short-lived signed token, given only to the project's owner, and the route serves
only that project's page and the few files every page loads. The key is kept in the store
(`BuilderStore.live_key`). The token is one path segment the web's proxy lets through (80 characters
of letters, digits and `.`). The page comes from our generator with the words escaped, and the
content policy keeps it from reaching anything but this address."""

import hashlib
import hmac
import re
from collections.abc import Mapping
from pathlib import Path

LIFETIME_S = 3600
RUNTIME = "hyperframe.runtime.iife.js"
CONTENT_POLICY = (
    "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; media-src 'self'; font-src 'self'; connect-src 'self'"
)
NO_SNIFF = {"X-Content-Type-Options": "nosniff"}
_GSAP_TAG = '<script src="vendor/gsap.min.js"></script>'
_MEDIA = {".js": "text/javascript", ".woff2": "font/woff2"}
_TOKEN = re.compile(r"([0-9a-f]{32})\.(\d{1,10})\.([0-9a-f]{32})")


def _signature(key: str, cid: str, expires: int) -> str:
    message = f"{cid}.{expires}".encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()[:32]


def sign(key: str, cid: str, expires: int) -> str:
    return f"{cid}.{expires}.{_signature(key, cid, expires)}"


def verify(key: str, token: str, now: float) -> str | None:
    """The project of a token that is ours and has not run out; else None."""
    m = _TOKEN.fullmatch(token)
    if m is None:
        return None
    cid, expires = m.group(1), int(m.group(2))
    if not hmac.compare_digest(m.group(3), _signature(key, cid, expires)) or now >= expires:
        return None
    return cid


def with_runtime(page: str) -> str:
    """The page as the player needs it: the same page, plus the script the player talks to."""
    return page.replace(_GSAP_TAG, f'{_GSAP_TAG}\n<script src="vendor/{RUNTIME}"></script>', 1)


def media_type(name: str) -> str:
    return _MEDIA.get(Path(name).suffix, "application/octet-stream")


def kit_files(gsap: Path, runtime: Path, fonts: Mapping[str, Path]) -> dict[str, bytes]:
    """The files under `vendor/` of the player's page, by their path there."""
    return {
        gsap.name: gsap.read_bytes(),
        RUNTIME: runtime.read_bytes(),
        **{f"fonts/{name}": path.read_bytes() for name, path in fonts.items()},
    }
