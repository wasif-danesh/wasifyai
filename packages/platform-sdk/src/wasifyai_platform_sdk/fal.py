"""fal.ai's queue API (ADR-0095): submit a request, follow its `status_url`, read its
`response_url`, and fetch the file it names. Shared by the media worker (pictures and clips) and
the API (speech and 3D models, on a person's key on the desktop or the admin's on the web), so
neither needs the other. The key goes to fal.ai's queue only, never to the file's host. Every
failure is a `FalError` in fal.ai's words; a caller turns it into its own kind of error."""

import asyncio
import base64
import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

FAL_QUEUE = "https://queue.fal.run"
FAL_REST = "https://rest.fal.ai"
FAL_CDN = "https://v3.fal.media"
ProgressFn = Callable[[float], Awaitable[None]]


class FalError(Exception):
    """`code`: provider_refused, connection_lost, missing_output or unavailable (worth a retry);
    `message` is a sentence for the screen and never holds the key. `before_running`: the
    provider refused before the job could run (a 4xx answer to the upload or the request, or no
    connection at all), so nothing was charged and another provider may take it (ADR-0100)."""

    def __init__(self, code: str, message: str, before_running: bool = False):
        super().__init__(message)
        self.code, self.message = code, message
        self.before_running = before_running


def not_sent(e: httpx.HTTPError) -> bool:
    """The request never reached the provider (no connection was made)."""
    return isinstance(e, httpx.ConnectError | httpx.ConnectTimeout)


def refused_before(r: httpx.Response) -> bool:
    """A refusal of a request before it ran: a 4xx answer (a 5xx may come after it started)."""
    return 400 <= r.status_code < 500


def media_type(data: bytes) -> str:
    """The type of a picture, a voice, a clip or a training set from its first bytes (PNG, WAV,
    MP3, MP4, ZIP, else JPEG)."""
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:4] == b"PK\x03\x04":
        return "application/zip"
    if data[4:8] == b"ftyp":
        return "video/mp4"
    if data[:4] == b"RIFF":
        return "audio/wav"
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    return "image/jpeg"


def data_uri(data: bytes) -> str:
    return f"data:{media_type(data)};base64,{base64.b64encode(data).decode()}"


def _kind(r: httpx.Response) -> str:
    try:
        kind = r.json().get("type")
    except (ValueError, AttributeError):
        return ""
    return kind if isinstance(kind, str) else ""


def fal_said(r: httpx.Response) -> str:
    """fal.ai's own words for a refusal (its `detail`: a sentence or a list of them)."""
    try:
        detail = r.json().get("detail")
    except ValueError:
        return ""
    if isinstance(detail, str):
        return detail[:300]
    if isinstance(detail, list):
        words = [str(d.get("msg", "")) for d in detail if isinstance(d, dict)]
        return "; ".join(w for w in words if w)[:300]
    return ""


class FalQueue:
    """fal.ai's queue with the person's key: submit, follow `status_url`, read `response_url`; and
    the file it names, fetched without the key. Images and video (`FalRunner`), speech and 3D
    (ADR-0095, K3 to K5) go through it."""

    def __init__(
        self,
        key: str,
        http: httpx.AsyncClient,
        timeout_s: float,
        poll_s: float = 2.0,
        base_url: str = FAL_QUEUE,
        rest_url: str = FAL_REST,
        cdn_url: str = FAL_CDN,
    ):
        self._headers = {"Authorization": f"Key {key}"}
        self._http = http
        self._timeout = timeout_s
        self._poll = poll_s
        self._base = base_url.rstrip("/")
        self._rest = rest_url.rstrip("/")
        self._cdn = cdn_url.rstrip("/")

    async def upload(self, data: bytes, name: str) -> str:
        """Put a picture or a voice in fal.ai's file store and answer its address. fal.ai refuses
        a voice sent inside the request ("URL too long", the owner's real run of 2026-11-12), so
        inputs go up first, the way fal.ai's own client does it: a short-lived upload token from
        `storage/auth/token`, then the bytes to the CDN's `files/upload`, whose `access_url` is
        the file. The key goes to fal.ai's REST host only; the CDN gets the token."""
        ctype = media_type(data)
        try:
            tok = await self._http.post(
                f"{self._rest}/storage/auth/token?storage_type=fal-cdn-v3",
                json={}, headers=self._headers, timeout=30,
            )  # fmt: skip
            if tok.status_code >= 400:
                raise self._refused(tok, before=True)
            t = tok.json()
            base = str(t.get("base_url") or self._cdn).rstrip("/")
            up = await self._http.post(
                f"{base}/files/upload", content=data, timeout=max(60.0, self._timeout),
                headers={
                    "Authorization": f"{t.get('token_type', 'Bearer')} {t['token']}",
                    "Content-Type": ctype, "X-Fal-File-Name": name,
                },
            )  # fmt: skip
        except httpx.HTTPError:
            raise FalError("connection_lost", "fal.ai could not be reached.", True) from None
        except (KeyError, ValueError):
            raise FalError(
                "provider_refused", "fal.ai did not give a place to upload.", True
            ) from None
        if up.status_code >= 400:
            raise FalError(
                "provider_refused", f"fal.ai did not take the file ({up.status_code}).", True
            )
        url = (
            up.json().get("access_url")
            if up.headers.get("content-type", "").startswith("application/json")
            else None
        )
        if not url:
            raise FalError("provider_refused", "fal.ai did not say where the file went.", True)
        return str(url)

    def _refused(self, r: httpx.Response, before: bool = False) -> FalError:
        if r.status_code == 403 and _kind(r) == "endpoint_not_priced":
            # a name fal.ai has no model at: its queue takes the job, then refuses it (CP13)
            return FalError("provider_refused", f"fal.ai has no such model: {fal_said(r)}", before)
        if r.status_code in (401, 403):
            return FalError("provider_refused", "fal.ai did not accept the key.", before)
        if r.status_code == 429:
            return FalError(
                "provider_refused", "fal.ai says too many requests. Try again soon.", before
            )
        said = fal_said(r)
        return FalError(
            "provider_refused",
            f"fal.ai could not make it: {said}" if said else f"fal.ai answered {r.status_code}.",
            before,
        )

    async def call(
        self, endpoint: str, body: dict[str, Any], on_progress: ProgressFn
    ) -> dict[str, Any]:
        """What `endpoint` made for `body` (its result object), once the queue has finished it."""
        await on_progress(0.02)
        try:
            r = await self._http.post(
                f"{self._base}/{endpoint}", json=body, headers=self._headers, timeout=60
            )
        except httpx.HTTPError as e:
            raise FalError("connection_lost", "fal.ai could not be reached.", not_sent(e)) from None
        if r.status_code >= 400:
            raise self._refused(r, before=refused_before(r))
        sub = r.json()
        started = time.monotonic()
        try:
            while True:
                if time.monotonic() - started > self._timeout:
                    raise TimeoutError
                st = await self._http.get(sub["status_url"], headers=self._headers, timeout=30)
                if st.status_code >= 400:
                    raise self._refused(st)
                state = st.json()
                status = state.get("status")
                if status == "COMPLETED":
                    break
                await on_progress(0.05 if status == "IN_QUEUE" else 0.4)
                await asyncio.sleep(self._poll)
        except asyncio.CancelledError:
            # the person stopped it: ask fal.ai to stop too, without waiting on the answer
            if sub.get("cancel_url"):
                with contextlib.suppress(httpx.HTTPError):
                    await self._http.put(sub["cancel_url"], headers=self._headers, timeout=5)
            raise
        if state.get("error"):
            raise FalError("provider_refused", f"fal.ai could not make it: {state['error']}"[:400])
        res = await self._http.get(sub["response_url"], headers=self._headers, timeout=60)
        if res.status_code >= 400:
            raise self._refused(res)
        return res.json()

    async def fetch(self, item: Any, fallback_type: str) -> tuple[bytes, str]:
        """The file of a result's `{url, content_type}`, and its type. No key goes to its host."""
        url = item.get("url") if isinstance(item, dict) else None
        if not url:
            raise FalError("missing_output", "fal.ai returned nothing to keep.")
        got = await self._http.get(url, follow_redirects=True, timeout=self._timeout)
        if got.status_code == 429 or got.status_code >= 500:
            raise FalError("unavailable", f"fal.ai's file answered {got.status_code}.")
        if got.status_code >= 400:
            raise FalError("missing_output", "The file fal.ai made could not be fetched.")
        ctype = (item.get("content_type") or got.headers.get("content-type") or "").split(";")[0]
        return got.content, ctype.strip() or fallback_type

    async def make(
        self, endpoint: str, body: dict[str, Any], field: str, fallback_type: str,
        on_progress: ProgressFn,
    ) -> tuple[bytes, str, dict[str, Any]]:  # fmt: skip
        """`call`, then the file in the result's `field` (the first, for a list): the bytes, their
        type and the whole result. The same shape as the other providers' `make`
        (`cloud_queues.py`)."""
        result = await self.call(endpoint, body, on_progress)
        item = result.get(field)
        item = item[0] if isinstance(item, list) and item else item
        data, ctype = await self.fetch(item, fallback_type)
        return data, ctype, result
