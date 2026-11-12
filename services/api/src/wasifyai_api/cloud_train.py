"""Picture looks taught on a cloud model (ADR-0100, stage CP10).

While Train runs on a cloud model (Settings › Your keys, product `train`), a picture set is taught
by that model's trainer on the cheapest offer with a key, instead of AI Toolkit on this computer.
The pictures and their captions go up as one zip; the trainer answers the look's file, which is
kept with the run like a look taught here, and its address, which is what the cloud image model is
given when the look is used (fal.ai loads a look by its address: `loras: [{path, scale}]`).

A cloud trainer teaches one picture model: FLUX.3 klein on fal.ai, Z-Image on Runware (style looks
only) or fal.ai. The other picture models are refused in words while Train is on the cloud. The
field names not on the providers' pages are marked "(CP13)" and checked in the real run."""

import asyncio
import io
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from wasifyai_platform_sdk.cloud_queues import queue_for
from wasifyai_platform_sdk.fal import FalError
from wasifyai_platform_sdk.usage import UsageRecorder

from wasifyai_api.own_keys import KeyChoice, KeyRoute
from wasifyai_api.own_keys_engines import Routes, _cloud, _model_id, on_cheapest


@dataclass(frozen=True)
class CloudLook:
    """A cloud trainer: Train's picture model it teaches, the cloud image model that uses its looks,
    and how each provider is asked."""

    base: str  # Train's id for the picture model (`picture_bases`)
    images_model: str  # the catalogue's images model that uses the look
    title: str


TRAINERS: dict[str, CloudLook] = {  # by the catalogue's id for the trainer
    "flux3-klein-look": CloudLook("flux3-image-klein", "flux-3-klein", "FLUX.3 klein"),
    "z-image-look": CloudLook("z-image", "z-image-turbo", "Z-Image"),
}
RUNWARE_TRAIN = "modelTraining"  # Runware's task (CP13: its name and answer field)


def training_type(kind: str) -> str:
    """What the trainer is told it learns: a style, or a person or thing (content)."""
    return "style" if kind == "style" else "content"


def dataset_zip(pictures: list[Path], captions: list[str]) -> bytes:
    """The pictures and their captions as the trainers take them: 001.png beside 001.txt."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n, (picture, caption) in enumerate(zip(pictures, captions, strict=True), 1):
            z.writestr(f"{n:03d}.png", picture.read_bytes())
            z.writestr(f"{n:03d}.txt", caption)
    return out.getvalue()


def train_body(
    trainer: str, provider: str, dataset: str, word: str, steps: int, kind: str
) -> tuple[dict[str, Any], str]:
    """What a trainer is sent for a zip at `dataset` (an address, or Runware's upload id), and the
    field of its answer that holds the look."""
    if provider == "runware":  # Z-Image's style trainer: `inputs.dataset`, steps, word (CP0)
        return {
            "taskType": RUNWARE_TRAIN, "inputs": {"dataset": dataset},
            "settings": {"trainingSteps": steps, "triggerWord": word}, "includeCost": True,
        }, ""  # fmt: skip
    body: dict[str, Any] = {"images_data_url": dataset, "trigger_word": word, "steps": steps}
    if trainer == "z-image-look":  # content, style or balanced (CP13)
        body["training_type"] = training_type(kind)
    return body, "diffusers_lora_file"


def address_of(provider: str, result: dict[str, Any], field: str) -> str:
    """Where the provider keeps the look it made: what the image model is given to load it."""
    if provider == "runware":
        return str(result.get("modelURL") or "")  # (CP13)
    item = result.get(field)
    return str(item.get("url") or "") if isinstance(item, dict) else ""


class CloudLookTrainer:
    """The picture trainer, on a cloud model while Train runs on one. Everything else is the
    trainer it stands in front of (AI Toolkit on this computer)."""

    preview = False

    def __init__(
        self,
        local: Any,
        keys: Routes,
        client: Callable[[], httpx.AsyncClient] = httpx.AsyncClient,
        timeout_s: float = 3 * 3600,
        poll_s: float = 10.0,
        usage: UsageRecorder | None = None,
    ):
        self._local = local
        self._keys = keys
        self._client = client
        self._timeout = timeout_s
        self._poll = poll_s
        self._usage = usage
        self._made: dict[Path, dict[str, str]] = {}  # adapter -> where it is kept in the cloud
        self._published: dict[str, dict[str, str]] = {}  # a published name -> the same

    def __getattr__(self, name: str) -> Any:
        if name == "pause" and self._cloud() is not None:
            raise AttributeError(name)  # a run on a cloud model cannot be paused
        return getattr(self._local, name)

    # ---- where it runs ------------------------------------------------------------------------

    def _route(self) -> KeyRoute | None:
        return _cloud(self._keys, "train")

    def _cloud(self) -> tuple[KeyRoute, str, CloudLook] | None:
        route = self._route()
        if route is None:
            return None
        trainer = _model_id("train", route)
        look = TRAINERS.get(trainer)
        return (route, trainer, look) if look is not None else None

    def problem(self, base: str | None = None) -> str | None:
        on = self._cloud()
        if on is None:
            return self._local.problem(base) if base is not None else self._local.problem()  # type: ignore[no-any-return]
        _, _, look = on
        if base is None or base == look.base:
            return None
        return (
            f"With your key, Train teaches looks for {look.title}. Choose {look.title}, or run "
            "Train on this computer again in Settings › Your keys."
        )

    def ready(self, *a: Any) -> bool:
        return True if self._cloud() is not None else bool(self._local.ready(*a))

    def fit(self, base: str | None = None) -> dict[str, Any]:
        if self._cloud() is None:
            return self._local.fit(base) if base is not None else self._local.fit()  # type: ignore[no-any-return]
        return {
            "verdict": "fits", "reason": "Taught on a cloud model with your key.",
            "needed_bytes": 0, "budget_bytes": None, "capacity_bytes": None, "estimate": False,
            "partly_on_cpu": False,
        }  # fmt: skip

    def hub_missing(self, base: str) -> list[Any]:
        on = self._cloud()
        if on is not None and on[2].base == base:
            return []  # nothing to fetch: the cloud model has its files
        return list(self._local.hub_missing(base))

    def preflight(self) -> dict[str, Any]:
        if self._cloud() is None:
            return self._local.preflight()  # type: ignore[no-any-return]
        return {
            "ok": True, "blockers": [], "warnings": [],
            "pauses": "The pictures and their captions are sent to the cloud model.",
        }  # fmt: skip

    def state(self) -> dict[str, Any]:
        local = dict(self._local.state())
        on = self._cloud()
        if on is None:
            return local
        return {**local, "cloud": on[2].title, "preview": False}

    # ---- the work -----------------------------------------------------------------------------

    async def train(
        self,
        job: Any,
        report: Callable[[int, str], None],
        sample: Callable[[str], None],
        resume: bool = False,
    ) -> Any:
        on = self._cloud()
        if on is None:
            return await self._local.train(job, report, sample, resume=resume)
        from wasifyai_training.trainer import TrainResult

        route, trainer, look = on
        if getattr(job, "base", look.base) != look.base:
            raise RuntimeError(self.problem(job.base) or "That model is not taught on the cloud.")
        data = await asyncio.to_thread(dataset_zip, job.pictures, job.captions)
        out = job.samples.parent / "out" / "cloud_look.safetensors"
        t0 = time.monotonic()
        steps = int(job.steps)

        async def attempt(c: KeyChoice) -> tuple[bytes, str]:
            title = c.provider.title
            report(0, f"Sending the pictures to {title}")

            async def told(fraction: float) -> None:
                report(max(0, min(steps, round(fraction * steps))), f"Learning on {title}")

            async with self._client() as http:
                queue = queue_for(c.provider.id, c.key, http, self._timeout, self._poll, c.base_url)
                sent = await queue.upload(data, "pictures.zip")
                body, field = train_body(trainer, c.provider.id, sent, job.word, steps, job.kind)
                got, _, result = await queue.make(
                    c.offer.endpoint, body, field, "application/octet-stream", told
                )
                return got, address_of(c.provider.id, result, field)

        needs = (training_type(job.kind),)
        try:
            (got, url), used = await on_cheapest(
                route, "train", {"steps": steps}, attempt, self._usage, needs
            )
        except FalError as e:
            raise RuntimeError(e.message) from None
        except TimeoutError:
            raise RuntimeError(f"{route.provider.title} took too long to teach it.") from None
        if not got or not url:
            raise RuntimeError(f"{used.choice.provider.title} sent no look back.")
        await asyncio.to_thread(out.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(out.write_bytes, got)
        self._made[out] = {
            "provider": used.choice.provider.id, "url": url, "model": look.images_model,
        }  # fmt: skip
        report(steps, f"Taught on {used.choice.provider.title}")
        return TrainResult(
            out, time.monotonic() - t0, "cloud",
            note=f"Taught on {used.choice.provider.title} for {look.title} (cloud models only).",
        )  # fmt: skip

    async def stop(self) -> None:
        if self._cloud() is None:  # a cloud run ends when its task is cancelled
            await self._local.stop()

    async def publish(self, adapter: Path, title: str, run_id: str, **kw: Any) -> str | None:
        """A look taught on a cloud model is kept beside the other styles under its own name, with
        where it is kept in the cloud (`cloud_of`); one taught here is the trainer's to publish."""
        cloud = self._made.pop(adapter, None)
        if cloud is None:
            return await self._local.publish(adapter, title, run_id, **kw)  # type: ignore[no-any-return]
        folder = getattr(self._local, "models_dir", None)
        if folder is None:
            return None
        import re
        import shutil

        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "look"
        name = f"wasify-cloud-{slug}-{run_id[:8]}.safetensors"
        target = Path(folder) / "loras" / name
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, adapter, target)
        self._published[name] = cloud
        return name

    def cloud_of(self, name: str) -> dict[str, str] | None:
        """Where a look published by the last cloud run is kept: {provider, url, model}."""
        return self._published.get(name)
