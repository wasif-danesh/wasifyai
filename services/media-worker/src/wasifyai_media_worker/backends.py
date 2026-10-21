"""Media backends beyond local ComfyUI, and the router that picks one per job (ADR-0025).

A job names a capability of a product; the admin may have bound that to a backend. The router looks
the binding up for every job (cached for a few seconds), so a change applies to the next job.
Remote backends run no GPU work here: the processor skips the GPU lock for them."""

import asyncio
import base64
import logging
import mimetypes
import time
from typing import Any

import httpx
from wasifyai_platform_sdk import (
    PICTURE_SLOTS,
    JobRequest,
    MediaBinding,
    MediaBindingStore,
    SecretBox,
    SecretsUnavailable,
    input_image_name,
)

from wasifyai_media_worker.comfy import ComfyClient, ComfyError, ProgressFn, use_picture
from wasifyai_media_worker.settings import WorkerSettings

log = logging.getLogger(__name__)

Files = dict[str, tuple[bytes, str, str]]
InputFiles = dict[str, bytes]
CACHE_TTL_S = 3.0
_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "application/json": "json",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/flac": "flac",
    "audio/ogg": "ogg",
    "video/mp4": "mp4",
}


class BackendUnavailable(ConnectionError):
    """A transient failure of a remote backend (server error, rate limit): the job is retried."""


def raise_for_backend(r: httpx.Response) -> None:
    """Translate a backend's HTTP failure into something the processor understands. Messages are
    safe to show a user; details go to the log, never a key."""
    if r.status_code < 400:
        return
    if r.status_code in (401, 403):
        raise ComfyError("backend_auth", "The generation service rejected our credentials.")
    if r.status_code == 402:
        raise ComfyError("backend_credits", "The generation service has no credits left.")
    if r.status_code in (400, 422):
        log.error("backend rejected the request: %s", r.text[:300])
        raise ComfyError("invalid_workflow", "The generation request was rejected by the backend.")
    if r.status_code == 429 or r.status_code >= 500:
        raise BackendUnavailable(f"backend answered {r.status_code}")
    raise ComfyError("job_failed", "The generation failed.")


class ComfyApiRunner:
    """Comfy Cloud, a serverless deployment or comfy-api-proxy, over API v2 (poll-first)."""

    backend = "comfy-api"
    local_gpu = False

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        timeout_s: float,
        http: httpx.AsyncClient,
        poll_s: float = 2.0,
    ):
        self._base = base_url.rstrip("/")
        self._headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout_s
        self._http = http
        self._poll = poll_s

    async def run(
        self, job: JobRequest, on_progress: ProgressFn, files: InputFiles | None = None
    ) -> Files:
        graph = job.prompt
        for slot in PICTURE_SLOTS:
            if files and slot in files:
                name = input_image_name(job.job_id, slot)
                graph = use_picture(graph, name, await self._upload(name, files[slot]))
        r = await self._http.post(
            f"{self._base}/api/v2/jobs", json={"workflow": graph}, headers=self._headers
        )
        raise_for_backend(r)
        remote_id = r.json()["id"]
        try:
            async with asyncio.timeout(self._timeout):
                data = await self._wait(remote_id, on_progress)
        except TimeoutError:
            await self._cancel(remote_id)
            raise
        return await self._download(job, data.get("outputs") or [])

    async def _upload(self, name: str, data: bytes) -> str:
        """The user's picture, sent to the backend's input storage. Comfy Cloud documents this
        upload route; it is not verified against the real service."""
        r = await self._http.post(
            f"{self._base}/api/upload/image",
            headers={
                **self._headers,
                "x-api-key": self._headers["authorization"].removeprefix("Bearer "),
            }
            if self._headers
            else {},
            data={"type": "input", "overwrite": "true"},
            files={"image": (name, data, mimetypes.guess_type(name)[0] or "image/png")},
        )
        raise_for_backend(r)
        return str(r.json().get("name", name))

    async def _wait(self, remote_id: str, on_progress: ProgressFn) -> dict[str, Any]:
        while True:
            r = await self._http.get(f"{self._base}/api/v2/jobs/{remote_id}", headers=self._headers)
            raise_for_backend(r)
            data = r.json()
            status = data.get("status")
            if status == "succeeded":
                await on_progress(1.0)
                return data
            if status in ("failed", "expired"):
                err = data.get("error") or {}
                log.error(
                    "comfy api job %s %s: %s %s",
                    remote_id,
                    status,
                    err.get("code"),
                    err.get("message"),
                )
                raise ComfyError("execution_failed", "The generation failed on the backend.")
            if status in ("canceled", "canceling"):
                raise ComfyError("interrupted", "The generation was interrupted.")
            value = (data.get("progress") or {}).get("value")
            if isinstance(value, int | float):
                await on_progress(max(0.0, min(float(value), 1.0)))
            await asyncio.sleep(self._poll)

    async def _cancel(self, remote_id: str) -> None:
        try:
            await self._http.post(
                f"{self._base}/api/v2/jobs/{remote_id}/cancel", headers=self._headers
            )
        except httpx.HTTPError:
            log.warning("could not cancel remote job %s", remote_id)

    async def _download(self, job: JobRequest, outputs: list[dict[str, Any]]) -> Files:
        files: Files = {}
        for name, spec in job.outputs.items():
            kind, node = spec.get("type", "image"), str(spec["node"])
            of_kind = [o for o in outputs if o.get("type") == kind]
            match = [o for o in of_kind if str(o.get("node_id")) == node] or (
                of_kind if len(of_kind) == 1 else []
            )
            if not match:
                raise ComfyError("missing_output", f"The workflow produced no {kind} output.")
            item = match[0]
            files[name] = await self._fetch(item)
        return files

    async def _fetch(self, item: dict[str, Any]) -> tuple[bytes, str, str]:
        url = f"{self._base}/api/v2/assets/{item['id']}/content"
        r = await self._http.get(url, headers=self._headers, follow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            # The signed storage URL must not receive our key.
            r = await self._http.get(r.headers["location"], follow_redirects=True)
        raise_for_backend(r)
        ctype = item.get("content_type") or r.headers.get(
            "content-type", "application/octet-stream"
        )
        ctype = ctype.split(";")[0].strip()
        return r.content, ctype, _EXT.get(ctype, ctype.rsplit("/", 1)[-1] or "bin")


class OpenAIImagesRunner:
    """Any server with an OpenAI-style POST /images/generations."""

    backend = "openai-images"
    local_gpu = False

    def __init__(
        self,
        base_url: str,
        model: str,
        size: str | None,
        api_key: str | None,
        timeout_s: float,
        http: httpx.AsyncClient,
    ):
        self._base = base_url.rstrip("/")
        self._model = model
        self._size = size
        self._headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout_s
        self._http = http

    def _size_for(self, job: JobRequest) -> str | None:
        if self._size:
            return self._size
        w, h = job.inputs.get("width"), job.inputs.get("height")
        return f"{w}x{h}" if isinstance(w, int) and isinstance(h, int) else None

    async def run(
        self, job: JobRequest, on_progress: ProgressFn, files: InputFiles | None = None
    ) -> Files:
        prompt = job.inputs.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ComfyError("invalid_workflow", "The request has no image description.")
        name = next((n for n, s in job.outputs.items() if s.get("type", "image") == "image"), None)
        if name is None:
            raise ComfyError("invalid_workflow", "The request asks for no image output.")
        body: dict[str, Any] = {"model": self._model, "prompt": prompt, "n": 1}
        if size := self._size_for(job):
            body["size"] = size
        await on_progress(0.1)
        if job.capability.endswith(".edit"):
            if not files or "image" not in files:
                raise ComfyError("invalid_input", "The picture for this job is missing.")
            # an edit is a multipart form with the picture; its size follows the picture unless
            # the admin set one
            if not self._size:
                body.pop("size", None)
            r = await self._http.post(
                f"{self._base}/images/edits",
                data={k: str(v) for k, v in body.items()},
                files={"image": ("image.png", files["image"], "image/png")},
                headers=self._headers,
                timeout=self._timeout,
            )
        else:
            r = await self._http.post(
                f"{self._base}/images/generations", json=body, headers=self._headers,
                timeout=self._timeout,
            )  # fmt: skip
        raise_for_backend(r)
        item = ((r.json().get("data")) or [{}])[0]
        if item.get("b64_json"):
            data, ctype = base64.b64decode(item["b64_json"]), "image/png"
        elif item.get("url"):
            got = await self._http.get(item["url"], follow_redirects=True, timeout=self._timeout)
            raise_for_backend(got)
            data = got.content
            ctype = got.headers.get("content-type", "image/png").split(";")[0].strip()
        else:
            raise ComfyError("missing_output", "The image service returned no image.")
        await on_progress(1.0)
        return {name: (data, ctype, _EXT.get(ctype, "png"))}


class BackendRouter:
    """Chooses the runner for each job: the admin's binding if there is one, else the default."""

    def __init__(
        self,
        default: Any,
        settings: WorkerSettings,
        bindings: MediaBindingStore | None,
        box: SecretBox,
        http: httpx.AsyncClient,
        poll_s: float = 2.0,
    ):
        self._default = default
        self._s = settings
        self._bindings = bindings
        self._box = box
        self._http = http
        self._poll = poll_s
        self._cache: dict[tuple[str, str, str], tuple[float, MediaBinding | None]] = {}
        self._comfy: dict[str, Any] = {}

    async def _binding(self, job: JobRequest) -> MediaBinding | None:
        if self._bindings is None:
            return None
        key = (job.tenant_id, job.product_id, job.capability)
        hit = self._cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        try:
            found = await self._bindings.get(*key)
        except Exception as exc:  # database trouble must not silently pick another backend
            log.exception("could not read the media binding for %s", key)
            raise ConnectionError("media binding lookup failed") from exc
        self._cache[key] = (time.monotonic() + CACHE_TTL_S, found)
        return found

    def _secret(self, b: MediaBinding) -> str | None:
        if b.secret_enc is None:
            return None
        try:
            return self._box.decrypt(b.secret_enc)
        except SecretsUnavailable as exc:
            log.error("media secret for %s/%s is unreadable: %s", b.product_id, b.capability, exc)
            raise ComfyError(
                "backend_misconfigured", "The generation backend is not set up correctly."
            ) from exc

    async def resolve(self, job: JobRequest) -> Any:
        b = await self._binding(job)
        from wasifyai_media_worker.processor import ComfyRunner  # circular at import time

        if b is None:
            video_url = self._video_url(job)
            return self._local_runner(video_url, ComfyRunner) if video_url else self._default

        cfg = b.config
        match b.backend:
            case "comfyui-local":
                url = cfg.get("base_url") or self._video_url(job) or self._s.comfyui_base_url
                return self._local_runner(url, ComfyRunner)
            case "comfy-api":
                return ComfyApiRunner(
                    cfg.get("base_url") or "https://cloud.comfy.org", self._secret(b),
                    self._s.job_timeout_s, self._http, self._poll,
                )  # fmt: skip
            case "openai-images":
                return OpenAIImagesRunner(
                    cfg.get("base_url") or "https://api.openai.com/v1", cfg.get("model", ""),
                    cfg.get("size"), self._secret(b), self._s.job_timeout_s, self._http,
                )  # fmt: skip
            case other:
                log.error("unknown media backend %r in a binding", other)
                raise ComfyError(
                    "backend_misconfigured", "The generation backend is not set up correctly."
                )

    def _video_url(self, job: JobRequest) -> str:
        """The separate ComfyUI for video jobs, if set (never in stub mode)."""
        if job.capability.startswith("video.") and self._s.comfyui_mode != "stub":
            return self._s.comfyui_video_base_url
        return ""

    def _local_runner(self, url: str, runner_class: Any) -> Any:
        if url not in self._comfy:
            self._comfy[url] = ComfyClient(url)
        return runner_class(self._comfy[url], self._s.job_timeout_s)

    async def aclose(self) -> None:
        for client in self._comfy.values():
            await client.aclose()
