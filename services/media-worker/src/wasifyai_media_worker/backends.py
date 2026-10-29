"""Media backends beyond local ComfyUI, and the router that picks one per job (ADR-0025).

A job names a capability of a product; the admin may have bound that to a backend. The router looks
the binding up for every job (cached for a few seconds), so a change applies to the next job.
Remote backends run no GPU work here: the processor skips the GPU lock for them."""

import asyncio
import base64
import contextlib
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


# ---- fal.ai, on the person's own key (ADR-0095, stage K3) -------------------------------------

FAL_QUEUE = "https://queue.fal.run"
# the endpoint a capability uses, from the model the person chose for the product (its text-to-X
# endpoint). A capability with no entry for that model cannot run on the key.
FAL_EDIT = {"fal-ai/flux-2": "fal-ai/flux-2/edit"}
FAL_ANIMATE = {"fal-ai/ltx-2/text-to-video/fast": "fal-ai/ltx-2/image-to-video/fast"}
FAL_VIDEO_SECONDS = (6, 8, 10)  # what LTX-2 on fal.ai makes at 1080p
NOT_WITH_KEY = {
    "image.inpaint": "Painting over part of a picture",
    "video.extend": "Making a clip longer",
}


def data_uri(data: bytes) -> str:
    kind = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    return f"data:{kind};base64,{base64.b64encode(data).decode()}"


def _fal_said(r: httpx.Response) -> str:
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
    (ADR-0095, K3 and K4) go through it. Every failure is a `ComfyError` in fal.ai's words."""

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

    def _refused(self, r: httpx.Response) -> ComfyError:
        if r.status_code in (401, 403):
            return ComfyError("provider_refused", "fal.ai did not accept the key.")
        if r.status_code == 429:
            return ComfyError("provider_refused", "fal.ai says too many requests. Try again soon.")
        said = _fal_said(r)
        return ComfyError(
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
            raise ComfyError("connection_lost", "fal.ai could not be reached.") from None
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
            raise ComfyError(
                "provider_refused", f"fal.ai could not make it: {state['error']}"[:400]
            )
        res = await self._http.get(sub["response_url"], headers=self._headers, timeout=60)
        if res.status_code >= 400:
            raise self._refused(res)
        return res.json()

    async def fetch(self, item: Any, fallback_type: str) -> tuple[bytes, str]:
        """The file of a result's `{url, content_type}`, and its type. No key goes to its host."""
        url = item.get("url") if isinstance(item, dict) else None
        if not url:
            raise ComfyError("missing_output", "fal.ai returned nothing to keep.")
        got = await self._http.get(url, follow_redirects=True, timeout=self._timeout)
        raise_for_backend(got)
        ctype = (item.get("content_type") or got.headers.get("content-type") or "").split(";")[0]
        return got.content, ctype.strip() or fallback_type


class FalRunner:
    """One picture or clip on fal.ai with the person's key, through `FalQueue`."""

    backend = "fal"
    local_gpu = False

    def __init__(
        self,
        key: str,
        model: str,
        http: httpx.AsyncClient,
        timeout_s: float,
        poll_s: float = 2.0,
        base_url: str = FAL_QUEUE,
    ):
        self._queue = FalQueue(key, http, timeout_s, poll_s, base_url)
        self._headers = self._queue._headers
        self._model = model

    def _request(self, job: JobRequest, files: InputFiles | None) -> tuple[str, dict[str, Any]]:
        """The endpoint and the body for this job, from what was asked (`job.inputs`)."""
        what = NOT_WITH_KEY.get(job.capability)
        if what:
            raise ComfyError(
                "not_with_key",
                f"{what} is not done with your key yet. Run it on this computer: Settings › "
                "Your keys.",
            )
        if job.inputs.get("loras"):
            raise ComfyError(
                "not_with_key",
                "Styles and looks made on this computer cannot be used with your key.",
            )
        prompt = job.inputs.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ComfyError("invalid_input", "The request has no description.")
        body: dict[str, Any] = {"prompt": prompt}
        seed = job.inputs.get("seed")
        cap = job.capability
        if cap in ("image.generate", "image.edit", "image.reference"):
            w, h = job.inputs.get("width"), job.inputs.get("height")
            if isinstance(w, int) and isinstance(h, int):
                body["image_size"] = {"width": w, "height": h}
            if isinstance(seed, int):
                body["seed"] = seed
            if cap == "image.generate":
                return self._model, body
            pictures = [files[n] for n in ("image", "image2") if files and n in files]
            if not pictures:
                raise ComfyError("invalid_input", "The picture for this job is missing.")
            body["image_urls"] = [data_uri(p) for p in pictures]
            return self._endpoint(FAL_EDIT, "Changing a picture"), body
        if cap in ("video.generate", "video.animate"):
            frames = job.inputs.get("length")
            want = round(frames / 24) if isinstance(frames, int) else 6
            body["duration"] = next((s for s in FAL_VIDEO_SECONDS if s >= want), 10)
            body["generate_audio"] = False
            if cap == "video.generate":
                return self._model, body
            if not files or "image" not in files:
                raise ComfyError("invalid_input", "The picture for this job is missing.")
            body["image_url"] = data_uri(files["image"])
            return self._endpoint(FAL_ANIMATE, "Animating a picture"), body
        raise ComfyError("not_with_key", "This is not done with your key.")

    def _endpoint(self, table: dict[str, str], what: str) -> str:
        found = table.get(self._model)
        if found is None:
            raise ComfyError(
                "not_with_key",
                f"{what} needs a model fal.ai can do it with; {self._model} cannot. Choose "
                "another model, or run it on this computer: Settings › Your keys.",
            )
        return found

    async def run(
        self, job: JobRequest, on_progress: ProgressFn, files: InputFiles | None = None
    ) -> Files:
        name, kind = next(
            ((n, s.get("type", "image")) for n, s in job.outputs.items()), ("output", "image")
        )
        endpoint, body = self._request(job, files)
        result = await self._queue.call(endpoint, body, on_progress)
        item = (result.get("images") or [{}])[0] if kind == "image" else result.get("video") or {}
        await on_progress(0.9)
        fallback = "video/mp4" if kind == "video" else "image/png"
        data, ctype = await self._queue.fetch(item, fallback)
        await on_progress(1.0)
        return {name: (data, ctype, _EXT.get(ctype, "mp4" if kind == "video" else "png"))}


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
        """The separate ComfyUI for video jobs, if set (never in stub mode, and never when this
        worker runs the desktop's own ComfyUI: that one serves video too)."""
        own = self._s.comfyui_mode in ("stub", "sidecar")
        if job.capability.startswith("video.") and not own:
            return self._s.comfyui_video_base_url
        return ""

    def _local_runner(self, url: str, runner_class: Any) -> Any:
        if url not in self._comfy:
            self._comfy[url] = ComfyClient(url)
        return runner_class(self._comfy[url], self._s.job_timeout_s)

    async def aclose(self) -> None:
        for client in self._comfy.values():
            await client.aclose()
