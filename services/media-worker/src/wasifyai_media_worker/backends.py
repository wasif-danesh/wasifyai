"""Media backends beyond local ComfyUI, and the router that picks one per job (ADR-0025).

A job names a capability of a product; the admin may have bound that to a backend. The router looks
the binding up for every job (cached for a few seconds), so a change applies to the next job.
Remote backends run no GPU work here: the processor skips the GPU lock for them."""

import asyncio
import base64
import logging
import mimetypes
import time
from collections.abc import Sequence
from dataclasses import dataclass
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
from wasifyai_platform_sdk.cloud_queues import RunwareTasks, WaveSpeedQueue, queue_for
from wasifyai_platform_sdk.fal import FAL_QUEUE, FalError, FalQueue
from wasifyai_platform_sdk.offers import Offer, Priced, no_offer, order, run_cheapest

from wasifyai_media_worker.cloud_recipes import RECIPES, ask_of, runware_send
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

# the endpoint a capability uses, from the model the person chose for the product (its text-to-X
# endpoint). A capability with no entry for that model cannot run on the key.
FAL_EDIT = {"fal-ai/flux-2": "fal-ai/flux-2/edit"}
FAL_ANIMATE = {"fal-ai/ltx-2/text-to-video/fast": "fal-ai/ltx-2/image-to-video/fast"}
FAL_VIDEO_SECONDS = (6, 8, 10)  # what LTX-2 on fal.ai makes at 1080p
NOT_WITH_KEY = {
    "image.inpaint": "Painting over part of a picture",
    "video.extend": "Making a clip longer",
}


def _fal_failed(e: FalError) -> Exception:
    """The worker's own error for a fal.ai failure: a busy service is retried. A refusal before
    running stays marked, so the router can send the job to the next offer (`OfferRunner`)."""
    err: Exception = (
        BackendUnavailable(e.message) if e.code == "unavailable" else ComfyError(e.code, e.message)
    )
    err.before_running = e.before_running  # type: ignore[attr-defined]
    return err


def _not_here(message: str) -> ComfyError:
    """A job this offer cannot take, found before anything was sent: the next offer may."""
    err = ComfyError("not_with_key", message)
    err.before_running = True  # type: ignore[attr-defined]
    return err


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
        endpoints: dict[str, str] | None = None,
    ):
        self._queue = FalQueue(key, http, timeout_s, poll_s, base_url)
        self._headers = self._queue._headers
        self._model = model
        self._endpoints = endpoints or {}  # the offer's endpoint for a verb ("edit", "animate")

    async def _request(
        self, job: JobRequest, files: InputFiles | None
    ) -> tuple[str, dict[str, Any]]:
        """The endpoint and the body for this job, from what was asked (`job.inputs`). A picture
        goes up to fal.ai's file store first and the body names its address: one sent inside the
        request can be refused as too long (a voice was, in the owner's real run of 2026-11-12)."""
        what = NOT_WITH_KEY.get(job.capability)
        if what:
            raise _not_here(
                f"{what} is not done with your key yet. Run it on this computer: Settings › "
                "Your keys."
            )
        if job.inputs.get("loras"):
            raise _not_here("Styles and looks made on this computer cannot be used with your key.")
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
            endpoint = self._endpoint("edit", FAL_EDIT, "Changing a picture")  # nothing goes up
            body["image_urls"] = [
                await self._queue.upload(p, f"picture{i}.png") for i, p in enumerate(pictures)
            ]
            return endpoint, body
        if cap in ("video.generate", "video.animate"):
            frames = job.inputs.get("length")
            want = round(frames / 24) if isinstance(frames, int) else 6
            body["duration"] = next((s for s in FAL_VIDEO_SECONDS if s >= want), 10)
            body["generate_audio"] = False
            if cap == "video.generate":
                return self._model, body
            if not files or "image" not in files:
                raise ComfyError("invalid_input", "The picture for this job is missing.")
            endpoint = self._endpoint("animate", FAL_ANIMATE, "Animating a picture")
            body["image_url"] = await self._queue.upload(files["image"], "picture.png")
            return endpoint, body
        raise _not_here("This is not done with your key.")

    def _endpoint(self, verb: str, table: dict[str, str], what: str) -> str:
        # the offer's own endpoint for the verb; else a model named for the job itself (an admin's
        # row for Change a picture: fal-ai/flux-2/edit)
        found = (
            self._endpoints.get(verb)
            or table.get(self._model)
            or (self._model if self._model in table.values() else None)
        )
        if found is None:
            raise _not_here(
                f"{what} needs a model fal.ai can do it with; {self._model} cannot. Choose "
                "another model, or run it on this computer: Settings › Your keys."
            )
        return found

    async def run(
        self, job: JobRequest, on_progress: ProgressFn, files: InputFiles | None = None
    ) -> Files:
        name, kind = next(
            ((n, s.get("type", "image")) for n, s in job.outputs.items()), ("output", "image")
        )
        try:
            endpoint, body = await self._request(job, files)
            result = await self._queue.call(endpoint, body, on_progress)
            item = (
                (result.get("images") or [{}])[0] if kind == "image" else result.get("video") or {}
            )
            await on_progress(0.9)
            fallback = "video/mp4" if kind == "video" else "image/png"
            data, ctype = await self._queue.fetch(item, fallback)
        except FalError as e:
            raise _fal_failed(e) from None
        await on_progress(1.0)
        return {name: (data, ctype, _EXT.get(ctype, "mp4" if kind == "video" else "png"))}


# ---- WaveSpeed and Runware, on the person's own key (ADR-0095, amendment of 2026-11-11) ----------


def _sixty_four(side: Any) -> int:
    """Runware's sides: a multiple of 64 from 128 to 2048."""
    n = side if isinstance(side, int) else 1024
    return min(2048, max(128, round(n / 64) * 64))


class CloudImageRunner:
    """A picture made from a description on WaveSpeed or Runware with the person's key. Only
    making is offered there in this app; changing and combining pictures, and video, run on fal.ai
    or on this computer (`docs/own-keys-cloud-tab-plan.md`)."""

    local_gpu = False

    def __init__(
        self,
        provider: str,
        key: str,
        model: str,
        http: httpx.AsyncClient,
        timeout_s: float,
        poll_s: float = 2.0,
        base_url: str = "",
    ):
        self.backend = provider
        self._model = model
        queue = WaveSpeedQueue if provider == "wavespeed" else RunwareTasks
        self._queue = queue(key, http, timeout_s, poll_s, *([base_url] if base_url else []))

    def _body(self, job: JobRequest) -> dict[str, Any]:
        if job.capability != "image.generate":
            raise _not_here(
                f"Only making a picture runs on {self._queue.title} in this app. Choose a fal.ai "
                "or a computer model in the picker for this."
            )
        if job.inputs.get("loras"):
            raise _not_here("Styles and looks made on this computer cannot be used with a key.")
        prompt = job.inputs.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ComfyError("invalid_input", "The request has no description.")
        w, h = job.inputs.get("width"), job.inputs.get("height")
        seed = job.inputs.get("seed")
        if self.backend == "wavespeed":
            body: dict[str, Any] = {"prompt": prompt, "output_format": "png"}
            if isinstance(w, int) and isinstance(h, int):  # WaveSpeed takes 256 to 1536 a side
                body["size"] = f"{min(1536, max(256, w))}*{min(1536, max(256, h))}"
            if isinstance(seed, int):
                body["seed"] = seed
            return body
        task: dict[str, Any] = {
            "taskType": "imageInference", "positivePrompt": prompt, "numberResults": 1,
            "outputFormat": "PNG",
            "width": _sixty_four(w), "height": _sixty_four(h),
        }  # fmt: skip
        if isinstance(seed, int):
            task["seed"] = seed
        return task

    async def run(
        self, job: JobRequest, on_progress: ProgressFn, files: InputFiles | None = None
    ) -> Files:
        name = next(iter(job.outputs), "output")
        body = self._body(job)
        try:
            data, ctype, _ = await self._queue.make(
                self._model, body, "images", "image/png", on_progress
            )
        except FalError as e:
            raise _fal_failed(e) from None
        await on_progress(1.0)
        return {name: (data, ctype, _EXT.get(ctype, "png"))}


# ---- the cheapest offer for each job (ADR-0100, stage CP3) --------------------------------------


@dataclass(frozen=True)
class CloudChoice:
    """An offer of the job's model that a key can run."""

    provider: str
    key: str
    base_url: str
    offer: Offer


# what a job needs from an offer beyond making, by capability
NEEDS: dict[str, tuple[str, ...]] = {
    "image.edit": ("edit",),
    "image.reference": ("edit",),
    "image.inpaint": ("mask",),
    "video.animate": ("animate",),
    "video.extend": ("extend",),
}


def job_settings(job: JobRequest) -> dict[str, Any]:
    """What a job's price is counted in: one picture, or the clip's seconds (24 frames each)."""
    frames = job.inputs.get("length")
    out: dict[str, Any] = {"count": 1}
    if isinstance(frames, int) and frames > 0:
        out["seconds"] = frames / 24
    for k in ("resolution",):
        if isinstance(job.inputs.get(k), str):
            out[k] = job.inputs[k]
    return out


class RecipeRunner:
    """A picture or clip of a catalogue model on one offer, sent as that model's recipe for the
    provider says (`cloud_recipes.py`, stages CP4 and CP5): inputs uploaded the provider's way."""

    local_gpu = False

    def __init__(
        self, model: str, c: CloudChoice, http: httpx.AsyncClient, timeout_s: float, poll_s: float
    ):
        self.backend = c.provider
        self._recipe = RECIPES[(c.provider, model)]
        self._offer = c.offer
        self._queue = queue_for(c.provider, c.key, http, timeout_s, poll_s, c.base_url)

    async def run(
        self, job: JobRequest, on_progress: ProgressFn, files: InputFiles | None = None
    ) -> Files:
        name, kind = next(
            ((n, s.get("type", "image")) for n, s in job.outputs.items()), ("output", "image")
        )
        video = kind == "video"
        send = runware_send if isinstance(self._queue, RunwareTasks) else self._queue.upload
        try:
            endpoint, body = await self._recipe(ask_of(job, files), self._offer, send)
            data, ctype, _ = await self._queue.make(
                endpoint, body, "video" if video else "images",
                "video/mp4" if video else "image/png", on_progress,
            )  # fmt: skip
        except FalError as e:
            raise _fal_failed(e) from None
        await on_progress(1.0)
        return {name: (data, ctype, _EXT.get(ctype, "mp4" if video else "png"))}


class OfferRunner:
    """A picture or clip of a cloud model on the cheapest of its offers with a key: priced for the
    job, the next offer when one refuses before running, never resent once it may have run. After a
    run, `cost` is the offer it ran on and its price, for the `cloud.cost` usage event."""

    local_gpu = False

    def __init__(
        self,
        model: str,
        title: str,
        choices: Sequence[CloudChoice],
        http: httpx.AsyncClient,
        timeout_s: float,
        poll_s: float = 2.0,
    ):
        self.model = model
        self._title = title
        self._choices = list(choices)
        self._http = http
        self._timeout = timeout_s
        self._poll = poll_s
        self.backend = self._choices[0].provider if self._choices else "cloud"
        self.cost: Priced[CloudChoice] | None = None

    def _runner(self, c: CloudChoice) -> Any:
        if (c.provider, self.model) in RECIPES:
            return RecipeRunner(self.model, c, self._http, self._timeout, self._poll)
        if c.provider == "fal":
            return FalRunner(
                c.key, c.offer.endpoint, self._http, self._timeout, self._poll, c.base_url,
                dict(c.offer.endpoints),
            )  # fmt: skip
        return CloudImageRunner(
            c.provider, c.key, c.offer.endpoint, self._http, self._timeout, self._poll, c.base_url
        )

    async def run(
        self, job: JobRequest, on_progress: ProgressFn, files: InputFiles | None = None
    ) -> Files:
        needs = NEEDS.get(job.capability, ())
        ordered = order(self._choices, lambda c: c.offer, job_settings(job), needs)
        if not ordered:
            e = no_offer(self._title, [c.offer for c in self._choices], needs, None)
            raise ComfyError(e.code, e.message)

        async def attempt(p: Priced[CloudChoice]) -> Files:
            self.backend = p.choice.provider
            return await self._runner(p.choice).run(job, on_progress, files)  # type: ignore[no-any-return]

        made, used = await run_cheapest(ordered, attempt)
        self.cost = used
        return made


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
            case "fal":  # ADR-0095 K5: the admin's fal.ai key and model for this capability
                key = self._secret(b)
                if not key:
                    raise ComfyError(
                        "backend_misconfigured", "The generation backend is not set up correctly."
                    )
                return FalRunner(
                    key, cfg.get("model", ""), self._http, self._s.job_timeout_s, self._poll
                )
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
