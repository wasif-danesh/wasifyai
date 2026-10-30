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
ProgressFn = Callable[[float], Awaitable[None]]


class FalError(Exception):
    """`code`: provider_refused, connection_lost, missing_output or unavailable (worth a retry);
    `message` is a sentence for the screen and never holds the key."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def data_uri(data: bytes) -> str:
    kind = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    return f"data:{kind};base64,{base64.b64encode(data).decode()}"


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
    ):
        self._headers = {"Authorization": f"Key {key}"}
        self._http = http
        self._timeout = timeout_s
        self._poll = poll_s
        self._base = base_url.rstrip("/")

    def _refused(self, r: httpx.Response) -> FalError:
        if r.status_code in (401, 403):
            return FalError("provider_refused", "fal.ai did not accept the key.")
        if r.status_code == 429:
            return FalError("provider_refused", "fal.ai says too many requests. Try again soon.")
        said = fal_said(r)
        return FalError(
            "provider_refused",
            f"fal.ai could not make it: {said}" if said else f"fal.ai answered {r.status_code}.",
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
        except httpx.HTTPError:
            raise FalError("connection_lost", "fal.ai could not be reached.") from None
        if r.status_code >= 400:
            raise self._refused(r)
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
