# ruff: noqa: E501  (the sentences shown to people are easier to read on one line)
"""Teach the video model: the runs of a set of pictures and clips (ADR-0073, video amendment).

A set is the same thing as for pictures (pictures, descriptions written by the app, a magic word, a
statement of whose it is) and may also hold short clips; a set made for video (`family` "video") is
taught to the video model, LTX-Video 2B, by a LoRA. A run turns the set into a job (`VideoJob`) for the
engine behind `state.video_training`, keeps the adapter as a model with its card, and **publishes** it to
where the video engine reads it: the key names ComfyUI's LTXV loader uses, in the models' `loras` folder
(spike TV0: with the names the trainer writes it is silently ignored). One run at a time on this
computer, and not while another model is being taught: all hold the one big-model slot (ADR-0056).

What a run takes was measured (docs/spikes/video-training-tv0.md): 0.5 s a step and 7.4 GB for pictures
at 640x576, 7.7 s a step and 9.8 GB for clips of 25 frames at 768x512 with gradient checkpointing, which is
never optional there (49.6 GB without it)."""

import asyncio
import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import Identity, RouteDeps, RouteGuard, RunContext, set_context
from wasifyai_platform_sdk.context import reset_context

from wasifyai_training import bases, captions
from wasifyai_training.runtime import (
    EV_RUN,
    MAX_PICTURES,
    PRODUCT_ID,
    STATEMENTS,
    NotAvailable,
    Refused,
    add_to_search,
    folder_ready,
    folder_saved,
    item_folder,
    model_folder,
    run_folder,
    run_manager_for,
    store_for,
    words_of,
)
from wasifyai_training.trainer import Stopped

log = logging.getLogger(__name__)

FAMILY = "video"
BASE = "ltx-video-2b"
MIN_ITEMS = 8  # pictures and clips together; 15 to 30 is what the screen suggests
WINDOW_FRAMES = 25  # a clip is learnt in windows of 25 frames (about a second)
MAX_WINDOWS = 3  # per clip
RANK = 32
LEARNING_RATE = 2e-4
# a size is a name for the shape of what was added; each is a multiple of 32 as the model needs
SIZES = {"wide": (768, 512), "tall": (512, 768), "square": (704, 704)}
PER_SAMPLE = 60  # steps for each picture or window
MIN_STEPS, MAX_STEPS = 600, 2400
BUDGET_S = 2 * 3600  # a run is planned to take about this long at most
CHECKPOINT_ABOVE = (
    800  # tokens: above this gradient checkpointing is used (7.7 s a step at 2,688 tokens measured)
)


@dataclass
class VideoMedia:
    path: Path
    kind: str  # "picture" or "clip"
    caption: str
    seconds: float = 0.0


@dataclass
class VideoJob:
    word: str
    media: list[VideoMedia]
    width: int
    height: int
    window_frames: int
    steps: int
    checkpointing: bool
    rank: int = RANK
    lr: float = LEARNING_RATE
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoResult:
    adapter: Path  # the adapter as the trainer wrote it (names `transformer.transformer_blocks...`)
    seconds: float
    engine: str
    peak_bytes: int = 0
    loss_first: float | None = None
    loss_last: float | None = None
    note: str = ""


def engine_for(state: Any) -> Any:
    engine = getattr(state, "video_training", None)
    if engine is None:
        raise NotAvailable("Teaching the video model is not available here.")
    return engine


def size_name(items: list[dict[str, Any]]) -> str:
    """The shape of what was added: the middle of the ratios of width to height."""
    ratios = sorted(i["width"] / max(1, i["height"]) for i in items) or [1.0]
    mid = ratios[len(ratios) // 2]
    return "wide" if mid > 1.25 else "tall" if mid < 0.8 else "square"


def windows_of(
    seconds: float, frames: int = WINDOW_FRAMES, fps: int = 24, most: int = MAX_WINDOWS
) -> int:
    room = seconds - frames / fps
    if room <= 0.05:
        return 1
    return min(most, 1 + int(room / (frames / fps)))


def tokens_of(width: int, height: int, frames: int) -> int:
    """What the transformer reads for one sample: 32 by 32 pixels by 8 frames to a token."""
    return (width // 32) * (height // 32) * ((frames - 1) // 8 + 1)


def seconds_per_step(tokens: int, mean: float | None = None) -> float:
    """Measured on a 64 GB M5 Pro: 0.50 s at 360 tokens and 0.73 s at 528 (pictures, no checkpointing); 7.7 s at 2,688 with it.
    `tokens` (the largest sample) says whether the run checkpoints; `mean` is the average sample."""
    return (tokens if mean is None else mean) * (0.0014 if tokens <= CHECKPOINT_ABOVE else 0.0029)


def plan_of(items: list[dict[str, Any]], quality: str = "quick") -> dict[str, Any]:
    """What a run of these items would be: the size, the samples, the steps and the time."""
    name = size_name(items)
    width, height = SIZES[name]
    pictures = sum(i.get("media", "picture") == "picture" for i in items)
    clips = [i for i in items if i.get("media") == "clip"]
    windows = sum(windows_of(float(i.get("seconds") or 0)) for i in clips)
    samples = pictures + windows
    frames = WINDOW_FRAMES if clips else 1
    tokens = tokens_of(width, height, frames)
    # a step is one sample: a picture (one frame) or a window of a clip, so the time follows the mix
    # (measured 2026-10-26: 12 pictures and 3 clips of 4 seconds took about 2.2 s a step, which the
    # mean of 384 and 1,536 tokens at the checkpointing rate gives within a tenth)
    each = [tokens_of(width, height, 1)] * pictures + [tokens] * windows
    mean = sum(each) / len(each) if each else tokens
    per = seconds_per_step(tokens, mean)
    steps = max(MIN_STEPS, min(MAX_STEPS, PER_SAMPLE * samples))
    steps = max(300, min(steps, int(BUDGET_S / per))) if per else steps
    if quality == "better":
        steps = min(steps * 3 // 2, int(BUDGET_S * 1.5 / per)) if per else steps
    return {
        "size": name, "width": width, "height": height, "pictures": pictures, "clips": len(clips),
        "samples": samples, "frames": frames, "tokens": tokens, "steps": steps,
        "checkpointing": tokens > CHECKPOINT_ABOVE, "seconds": round(steps * per + 60),
        "seconds_per_step": round(per, 3),
    }  # fmt: skip


def estimate_words(seconds: float) -> str:
    if seconds < 90:
        return "About a minute"
    if seconds < 5400:
        return f"About {round(seconds / 60)} minutes"
    return f"About {seconds / 3600:.1f} hours"


def ready_to_teach(dataset: dict[str, Any], items: list[dict[str, Any]]) -> str | None:
    """What is missing before a run, in the sentence the person is shown; None when nothing is."""
    if len(items) < MIN_ITEMS:
        return f"Add at least {MIN_ITEMS} pictures or clips. 15 to 30 good ones is plenty."
    if not dataset["rights"]:
        return "Say whose it is first."
    if not dataset["trigger_word"]:
        return "Choose the magic word first."
    if any(i["caption_state"] not in ("done", "edited") for i in items):
        return "Write the descriptions first."
    return None


def dataset_hash(items: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for sha in sorted(i["sha256"] for i in items):
        h.update(sha.encode())
    return h.hexdigest()[:16]


class VideoRunManager:
    """Starts and cancels the runs of video sets."""

    def __init__(self, deps: RouteDeps):
        self._deps = deps
        self._task: asyncio.Task[None] | None = None
        self._run_id: str | None = None
        self._teaching = False

    def busy(self) -> bool:
        return self._teaching

    def active(self) -> str | None:
        return self._run_id if self._teaching else None

    def others_busy(self) -> bool:
        state = self._deps.state
        others = (getattr(state, name, None) for name in ("writing_runs", "decision_runs"))
        return run_manager_for(self._deps).busy() or any(o is not None and o.busy() for o in others)

    async def start(
        self,
        identity: Identity,
        dataset_id: str,
        base: str | None = None,
        method: str | None = None,
    ) -> dict[str, Any]:
        state = self._deps.state
        engine, store = engine_for(state), store_for(state)
        dataset = store.get_dataset(identity.tenant_id, identity.user_id, dataset_id)
        if dataset["family"] != FAMILY:
            raise Refused("not_video", "This set is for teaching pictures. Make a set for video.")
        try:
            chosen, how = bases.resolve(dataset["kind"], base, method, family=FAMILY)
        except bases.Unavailable as e:
            raise Refused("cannot_teach", str(e)) from None
        if why := engine.problem():
            raise Refused("not_ready", why)
        if self.busy() or self.others_busy():
            raise Refused("busy", "A model is being taught. Wait for it to finish.")
        items = store.list_items(identity.tenant_id, identity.user_id, dataset_id)
        if why := ready_to_teach(dataset, items):
            raise Refused("not_ready_to_train", why)
        guard = RouteGuard(state, PRODUCT_ID)
        if refusal := await guard.over_quota(
            identity, EV_RUN, "train_runs_per_user_per_day", "training runs"
        ):
            raise Refused(*refusal)
        plan = plan_of(items)
        fit = engine.fit(chosen.need_gb)
        if fit["verdict"] == "too_big":
            raise Refused("too_big", fit["reason"])
        if blockers := engine.preflight_blockers():
            raise Refused("not_now", blockers[0])
        run = store.add_run(
            identity.tenant_id, identity.user_id, dataset_id, base=chosen.id, steps=plan["steps"],
            settings={"family": FAMILY, "kind": dataset["kind"], "steps": plan["steps"], "method": how,
                      "engine": chosen.engine, "size": plan["size"], "pictures": plan["pictures"],
                      "clips": plan["clips"], "frames": plan["frames"],
                      "seconds_per_step": plan["seconds_per_step"]},
            preview=False,
        )  # fmt: skip
        self._run_id = run["id"]
        self._teaching = True
        self._task = asyncio.create_task(self._run(identity, dataset, items, run, plan, engine))
        return run

    async def cancel(self, identity: Identity, run_id: str) -> bool:
        store_for(self._deps.state).get_run(identity.tenant_id, identity.user_id, run_id)
        if self._task is None or self._task.done() or self._run_id != run_id or not self._teaching:
            return False
        await engine_for(self._deps.state).stop()
        await asyncio.gather(self._task, return_exceptions=True)
        return True

    async def wait(self, run_id: str) -> None:
        if self._task is not None and self._run_id == run_id:
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(
        self, identity: Identity, dataset: dict[str, Any], items: list[dict[str, Any]],
        run: dict[str, Any], plan: dict[str, Any], engine: Any,
    ) -> None:  # fmt: skip
        store = store_for(self._deps.state)
        run_id = run["id"]
        token = set_context(RunContext(identity.tenant_id, PRODUCT_ID, identity.user_id))
        folder = run_folder(store, identity, run_id)
        try:
            await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
            media = []
            for i in items:
                where = await folder_ready(self._deps.state, identity, "items", i["id"])
                cap = captions.with_word(i["caption"], dataset["trigger_word"])
                if i.get("media") == "clip":
                    media.append(
                        VideoMedia(where / "clip.mp4", "clip", cap, float(i["seconds"] or 0))
                    )
                else:
                    media.append(VideoMedia(where / "picture.png", "picture", cap))
            job = VideoJob(
                dataset["trigger_word"], media, plan["width"], plan["height"], WINDOW_FRAMES,
                plan["steps"], plan["checkpointing"], settings=run["settings"],
            )  # fmt: skip
            result = await engine.train(
                job, folder, lambda step, stage: store.set_progress(run_id, step, stage)
            )
            model = await self._keep(identity, dataset, items, run, plan, result)
            store.finish_run(run_id, "done", elapsed_s=result.seconds, model_id=model["id"])
            self._teaching = False
            await RouteGuard(self._deps.state, PRODUCT_ID).record(
                identity, EV_RUN, 1, "runs", steps=run["steps"], seconds=result.seconds, preview=False,
            )  # fmt: skip
            await add_to_search(self._deps.state, identity, model["id"], words_of(model))
        except Stopped as e:
            store.finish_run(run_id, "cancelled", error=str(e))
        except asyncio.CancelledError:
            store.finish_run(run_id, "cancelled", error="Stopped.")
            raise
        except Exception:
            log.exception("a video run failed")
            store.finish_run(run_id, "failed", error="The model could not be taught. Try again.")
        finally:
            self._teaching = False
            reset_context(token)

    async def _keep(
        self, identity: Identity, dataset: dict[str, Any], items: list[dict[str, Any]],
        run: dict[str, Any], plan: dict[str, Any], result: VideoResult,
    ) -> dict[str, Any]:  # fmt: skip
        store = store_for(self._deps.state)
        engine = engine_for(self._deps.state)
        d = bases.descriptor(run["base"])
        card = {
            "family": FAMILY, "base": run["base"], "base_title": d.title if d else run["base"],
            "licence": d.licence if d else "", "engine": result.engine, "preview": False, "note": result.note,
            "dataset": {"name": dataset["name"], "kind": dataset["kind"], "pictures": plan["pictures"],
                        "clips": plan["clips"], "hash": dataset_hash(items)},
            "settings": run["settings"], "steps": run["steps"], "seconds": round(result.seconds, 1),
            "size": [plan["width"], plan["height"]],
            "peak_memory_gb": round(result.peak_bytes / 1024**3, 1) if result.peak_bytes else None,
            "loss": {"first": result.loss_first, "last": result.loss_last},
            "trigger_word": dataset["trigger_word"], "statement": STATEMENTS.get(dataset["rights"], ""),
            "evaluation": {"passed": None, "note": "Not checked yet: make a video with it and look at it."},
            "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }  # fmt: skip
        published = None
        try:
            name = await engine.publish(
                result.adapter, dataset["name"] or dataset["trigger_word"], run["id"]
            )
            published = {"lora_name": name} if name else None
        except Exception:
            log.exception("a taught video model could not be published to the video engine")
        card["published"] = published
        size = (await asyncio.to_thread(result.adapter.stat)).st_size
        model = store.add_model(
            identity.tenant_id, identity.user_id, run_id=run["id"], dataset_id=dataset["id"],
            name=dataset["name"] or dataset["trigger_word"], trigger_word=dataset["trigger_word"],
            kind=dataset["kind"], base=run["base"], card=card, preview=False, adapter_bytes=size,
        )  # fmt: skip
        folder = model_folder(store, identity, model["id"])
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, result.adapter, folder / "adapter.safetensors")
        await asyncio.to_thread((folder / "card.json").write_text, json.dumps(card, indent=2))
        await folder_saved(self._deps.state, identity, "models", model["id"])
        return model


def manager_for(deps: RouteDeps) -> VideoRunManager:
    existing = getattr(deps.state, "video_runs", None)
    if existing is None:
        existing = VideoRunManager(deps)
        deps.state.video_runs = existing
    return existing


__all__ = [
    "BASE",
    "FAMILY",
    "MAX_PICTURES",
    "VideoJob",
    "VideoMedia",
    "VideoResult",
    "manager_for",
    "plan_of",
]


# ---- the clips of a set -------------------------------------------------------------------------


async def add_clip(
    deps: RouteDeps, identity: Identity, dataset_id: str, name: str, data: bytes
) -> dict[str, Any]:
    """Look at a clip, say what is wrong with it in words, keep it. Raises `Refused`."""
    from wasifyai_training import clips, pictures
    from wasifyai_training.runtime import allowed_picture

    store = store_for(deps.state)
    dataset = store.get_dataset(identity.tenant_id, identity.user_id, dataset_id)  # the owner only
    if dataset["family"] != FAMILY:
        raise Refused("bad_picture", "Clips can be added to a set made for video.")
    have = store.list_items(identity.tenant_id, identity.user_id, dataset_id)
    if len(have) >= MAX_PICTURES:
        raise Refused(
            "too_many", f"A set can hold {MAX_PICTURES} pictures and clips. Remove some first."
        )
    if not data:
        raise Refused("bad_picture", "That clip is empty.")
    if len(data) > clips.MAX_BYTES:
        raise Refused("bad_picture", "That clip is too big. Use one under 300 MB.")
    scratch = store.folder / "tmp"
    await asyncio.to_thread(scratch.mkdir, parents=True, exist_ok=True)
    temp = (
        scratch
        / f"upload-{hashlib.sha256(data[:4096] + str(len(data)).encode()).hexdigest()[:16]}.mp4"
    )
    await asyncio.to_thread(temp.write_bytes, data)
    try:
        try:
            info = await clips.probe(temp)
            middle = await clips.frame_at(temp, info.seconds * 0.5)
            others_in_clip = [await clips.frame_at(temp, info.seconds * f) for f in (0.15, 0.85)]
        except clips.BadClip as e:
            raise Refused("bad_picture", str(e)) from None
        png = await asyncio.to_thread(pictures.to_png, middle)
        await allowed_picture(deps, identity, png)
        others = [int(i["dhash"], 16) for i in have]
        checks = await asyncio.to_thread(clips.check, info, middle, others_in_clip, others)
        row = store.add_item(
            identity.tenant_id, identity.user_id, dataset_id, name=name or "clip", width=info.width,
            height=info.height, sha256=hashlib.sha256(data).hexdigest(), dhash=pictures.dhash(middle),
            checks=checks, media="clip", seconds=round(info.seconds, 2), frames=info.frames,
        )  # fmt: skip
        folder = item_folder(store, identity, row["id"])
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(temp), str(folder / "clip.mp4"))
        await asyncio.to_thread((folder / "picture.png").write_bytes, png)
        await asyncio.to_thread((folder / "thumb.jpg").write_bytes, pictures.thumbnail(middle))
        await folder_saved(deps.state, identity, "items", row["id"])
        return row
    finally:
        await asyncio.to_thread(temp.unlink, True)
