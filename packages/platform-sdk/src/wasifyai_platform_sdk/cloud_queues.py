"""WaveSpeed and Runware with the person's key (ADR-0095, amendment of 2026-11-11), beside fal.ai's
queue (`fal.py`). Each has `make(endpoint, body, field, fallback_type, on_progress)`, which answers
the file made, its type and the provider's whole result, so the code that calls them does not care
which provider runs it. Every failure is a `FalError` (the shared provider error) in words for the
screen; the key goes only to the provider, never to the file's host.

    WaveSpeedQueue   POST /api/v3/<model>, then GET /api/v3/predictions/<id>/result until done
    RunwareTasks     POST a task (async), then `getResponse` until its URL is there

`queue_for(provider_id, ...)` gives the right one for a route."""

import asyncio
import time
import uuid
from typing import Any

import httpx

from wasifyai_platform_sdk.fal import FAL_QUEUE, FalError, FalQueue, ProgressFn

WAVESPEED_API = "https://api.wavespeed.ai/api/v3"
RUNWARE_API = "https://api.runware.ai/v1"
WAVESPEED_FAILED = ("failed", "cancelled", "timeout", "deleted")
RUNWARE_URLS = ("imageURL", "videoURL", "audioURL")


def _said(r: httpx.Response) -> str:
    """A provider's own words for a refusal, from the usual places."""
    try:
        j = r.json()
    except ValueError:
        return ""
    if not isinstance(j, dict):
        return ""
    errors = j.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return str(errors[0].get("message") or "")[:300]
    for k in ("message", "error", "detail"):
        if isinstance(j.get(k), str) and j[k]:
            return str(j[k])[:300]
    return ""


def _refused(title: str, r: httpx.Response) -> FalError:
    if r.status_code in (401, 403):
        return FalError("provider_refused", f"{title} did not accept the key.")
    if r.status_code == 429:
        return FalError("provider_refused", f"{title} says too many requests. Try again soon.")
    said = _said(r)
    return FalError(
        "provider_refused",
        f"{title} could not make it: {said}" if said else f"{title} answered {r.status_code}.",
    )


async def _fetch(
    http: httpx.AsyncClient, title: str, url: Any, fallback_type: str, wait_s: float
) -> tuple[bytes, str]:
    """The file at `url`, fetched without the key, and its type."""
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise FalError("missing_output", f"{title} returned nothing to keep.")
    got = await http.get(url, follow_redirects=True, timeout=wait_s)
    if got.status_code == 429 or got.status_code >= 500:
        raise FalError("unavailable", f"{title}'s file answered {got.status_code}.")
    if got.status_code >= 400:
        raise FalError("missing_output", f"The file {title} made could not be fetched.")
    ctype = (got.headers.get("content-type") or "").split(";")[0].strip()
    if not ctype or ctype in ("application/octet-stream", "binary/octet-stream"):
        ctype = fallback_type
    return got.content, ctype


class WaveSpeedQueue:
    title = "WaveSpeed"

    def __init__(
        self,
        key: str,
        http: httpx.AsyncClient,
        timeout_s: float,
        poll_s: float = 2.0,
        base_url: str = WAVESPEED_API,
    ):
        self._headers = {"Authorization": f"Bearer {key}"}
        self._http = http
        self._timeout = timeout_s
        self._poll = poll_s
        self._base = base_url.rstrip("/")

    async def call(
        self, endpoint: str, body: dict[str, Any], on_progress: ProgressFn
    ) -> dict[str, Any]:
        """The finished prediction (`data`: `status`, `outputs`, …)."""
        await on_progress(0.02)
        try:
            r = await self._http.post(
                f"{self._base}/{endpoint}", json=body, headers=self._headers, timeout=60
            )
        except httpx.HTTPError:
            raise FalError("connection_lost", f"{self.title} could not be reached.") from None
        if r.status_code >= 400:
            raise _refused(self.title, r)
        pid = (r.json().get("data") or {}).get("id")
        if not pid:
            raise FalError("missing_output", f"{self.title} did not take the request.")
        started = time.monotonic()
        while True:
            if time.monotonic() - started > self._timeout:
                raise TimeoutError
            try:
                st = await self._http.get(
                    f"{self._base}/predictions/{pid}/result", headers=self._headers, timeout=30
                )
            except httpx.HTTPError:  # the result is safe to ask for again (WaveSpeed's docs)
                await asyncio.sleep(self._poll)
                continue
            if st.status_code >= 400:
                raise _refused(self.title, st)
            data = st.json().get("data") or {}
            status = data.get("status")
            if status == "completed":
                return dict(data)
            if status in WAVESPEED_FAILED:
                said = str(data.get("error") or status)
                raise FalError("provider_refused", f"{self.title} could not make it: {said}"[:400])
            await on_progress(0.05 if status in ("created", "queued") else 0.4)
            await asyncio.sleep(self._poll)

    async def make(
        self, endpoint: str, body: dict[str, Any], field: str, fallback_type: str,
        on_progress: ProgressFn,
    ) -> tuple[bytes, str, dict[str, Any]]:  # fmt: skip
        result = await self.call(endpoint, body, on_progress)
        outputs = result.get("outputs") or []
        first = outputs[0] if isinstance(outputs, list) and outputs else None
        data, ctype = await _fetch(self._http, self.title, first, fallback_type, self._timeout)
        return data, ctype, result


class RunwareTasks:
    title = "Runware"

    def __init__(
        self,
        key: str,
        http: httpx.AsyncClient,
        timeout_s: float,
        poll_s: float = 2.0,
        base_url: str = RUNWARE_API,
    ):
        self._headers = {"Authorization": f"Bearer {key}"}
        self._http = http
        self._timeout = timeout_s
        self._poll = poll_s
        self._base = base_url.rstrip("/")

    async def _post(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            r = await self._http.post(self._base, json=tasks, headers=self._headers, timeout=60)
        except httpx.HTTPError:
            raise FalError("connection_lost", f"{self.title} could not be reached.") from None
        if r.status_code >= 400:
            raise _refused(self.title, r)
        j = r.json()
        errors = j.get("errors") or j.get("error")
        if errors:
            said = _said(r) or str(errors)[:300]
            raise FalError("provider_refused", f"{self.title} could not make it: {said}")
        data = j.get("data") or []
        return [d for d in data if isinstance(d, dict)]

    async def call(
        self, endpoint: str, body: dict[str, Any], on_progress: ProgressFn
    ) -> dict[str, Any]:
        """The finished task: `body` holds `taskType` and its fields; `endpoint` is the model."""
        await on_progress(0.02)
        task_id = str(uuid.uuid4())
        task = {**body, "taskUUID": task_id, "model": endpoint, "deliveryMethod": "async"}
        started = time.monotonic()
        rows = await self._post([task])
        while True:
            done = next(
                (d for d in rows if d.get("taskUUID") == task_id
                 and any(d.get(u) for u in RUNWARE_URLS)),
                None,
            )  # fmt: skip
            if done is not None:
                return done
            failed = next(
                (d for d in rows if d.get("taskUUID") == task_id
                 and d.get("status") in ("error", "failed")),
                None,
            )  # fmt: skip
            if failed is not None:
                said = str(failed.get("message") or failed.get("status"))
                raise FalError("provider_refused", f"{self.title} could not make it: {said}")
            if time.monotonic() - started > self._timeout:
                raise TimeoutError
            await on_progress(0.4)
            await asyncio.sleep(self._poll)
            rows = await self._post([{"taskType": "getResponse", "taskUUID": task_id}])

    async def make(
        self, endpoint: str, body: dict[str, Any], field: str, fallback_type: str,
        on_progress: ProgressFn,
    ) -> tuple[bytes, str, dict[str, Any]]:  # fmt: skip
        result = await self.call(endpoint, body, on_progress)
        url = next((result[u] for u in RUNWARE_URLS if result.get(u)), None)
        data, ctype = await _fetch(self._http, self.title, url, fallback_type, self._timeout)
        return data, ctype, result


def queue_for(
    provider_id: str,
    key: str,
    http: httpx.AsyncClient,
    timeout_s: float,
    poll_s: float = 2.0,
    base_url: str = "",
) -> FalQueue | WaveSpeedQueue | RunwareTasks:
    """The provider's client for a route (`provider_id` is fal, wavespeed or runware)."""
    if provider_id == "wavespeed":
        return WaveSpeedQueue(key, http, timeout_s, poll_s, base_url or WAVESPEED_API)
    if provider_id == "runware":
        return RunwareTasks(key, http, timeout_s, poll_s, base_url or RUNWARE_API)
    if provider_id == "fal":
        return FalQueue(key, http, timeout_s, poll_s, base_url or FAL_QUEUE)
    raise FalError("provider_refused", "This provider makes no media in this app.")
