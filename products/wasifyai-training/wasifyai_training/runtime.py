"""What the training product does, apart from HTTP and the catalogue (ADR-0073, ADR-0076, T1): the
pictures of a dataset and their checks, the captions the app writes, and the runs.

On the desktop there is one person, so one run in all; the engine behind `state.training` does the
training (today a preview, see `trainer.py`). Everything is scoped by tenant and user."""

import asyncio
import contextlib
import hashlib
import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import (
    Identity,
    RouteDeps,
    RouteGuard,
    RunContext,
    RunError,
    search_text,
    set_context,
)
from wasifyai_platform_sdk.context import reset_context

from wasifyai_training import bases, captions, evaluation, guardrail, magic, pictures, trainer
from wasifyai_training.store import NotFound, TrainingStore

log = logging.getLogger(__name__)

PRODUCT_ID = "wasifyai-training"
KIND = "lora"  # a trained model, a creation of its own kind (ADR-0041)
MIN_PICTURES = 8  # fewer teaches nothing; the screen says 15 to 25 good ones is plenty
MAX_PICTURES = 100
EV_PICTURE = "train.picture"  # the usage events the daily limits count (ADR-0047)
EV_RUN = "train.run"
STATEMENTS = {
    "mine": "It's me",
    "permission": "I have permission",
    "drawing": "It's a drawing, a character or an animal",
    "artwork": "It's my own artwork",
}


class NotAvailable(Exception):
    """This deployment has no training engine."""


class Refused(Exception):
    """A request that cannot be done now, with the sentence the person is shown."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def engine_for(state: Any) -> Any:
    engine = getattr(state, "training", None)
    if engine is None:
        raise NotAvailable("Training is not available here.")
    return engine


def root_for(state: Any) -> Path:
    data = getattr(state, "desktop_dir", None)
    if not data:
        raise NotAvailable("Training is not available here.")
    return Path(data) / "training"


def store_for(state: Any) -> TrainingStore:
    existing = getattr(state, "training_store", None)
    if existing is None:
        existing = TrainingStore(root_for(state))
        state.training_store = existing
    return existing


def not_ready(engine: Any) -> str:
    return getattr(engine, "problem", lambda: None)() or "Training is not set up yet."


# ---- files ----------------------------------------------------------------------------------


def item_folder(store: TrainingStore, identity: Identity, item_id: str) -> Path:
    return store.folder_of(identity.tenant_id, identity.user_id, "items", item_id)


def run_folder(store: TrainingStore, identity: Identity, run_id: str) -> Path:
    return store.folder_of(identity.tenant_id, identity.user_id, "runs", run_id)


def model_folder(store: TrainingStore, identity: Identity, model_id: str) -> Path:
    return store.folder_of(identity.tenant_id, identity.user_id, "models", model_id)


# ---- search ---------------------------------------------------------------------------------


def words_of(row: dict[str, Any]) -> str:
    return ". ".join(x for x in (row["name"], row["trigger_word"], row["kind"]) if x and x.strip())


async def add_to_search(state: Any, identity: Identity, item_id: str, text: str) -> None:
    """Make a trained model searchable by its name and magic word (ADR-0041): best effort."""
    index = getattr(state, "creation_index", None)
    if index is None:
        return
    try:
        await index.index(
            identity.tenant_id, PRODUCT_ID, identity.user_id, KIND, item_id, search_text(text)
        )
    except Exception:
        log.warning("the trained model could not be added to search", exc_info=True)


# ---- the safeguards (ADR-0047), the same as the 3D pictures ---------------------------------


async def allowed_picture(deps: RouteDeps, identity: Identity, png: bytes) -> None:
    """The day's limit, then the picture check: both only while the safeguards are on. The check
    fails closed, and the picture is not kept when it is refused."""
    guard = RouteGuard(deps.state, PRODUCT_ID)
    if refusal := await guard.over_quota(
        identity, EV_PICTURE, "train_pictures_per_user_per_day", "pictures"
    ):
        raise Refused(*refusal)
    if await guard.on():
        unavailable = Refused(
            "moderation_unavailable", "We couldn't check your picture right now. Please try again."
        )
        caps = guard.caps
        if caps is None:
            raise unavailable
        token = set_context(RunContext(identity.tenant_id, PRODUCT_ID, identity.user_id))
        try:
            verdict = await guardrail.judge_picture(caps, png)
        except RunError as e:
            raise Refused(e.code, e.message) from None
        except Exception:  # no moderator bound, or the gateway is down: nothing is let through
            log.exception("the training picture check failed")
            raise unavailable from None
        finally:
            reset_context(token)
        if not verdict.allowed:
            raise Refused(verdict.category, guardrail.refusal_message(verdict.category))
    await guard.record(identity, EV_PICTURE, 1, "pictures")


# ---- the pictures of a dataset --------------------------------------------------------------


async def add_picture(
    deps: RouteDeps, identity: Identity, dataset_id: str, name: str, data: bytes
) -> dict[str, Any]:
    """Look at a picture, say what is wrong with it in words, keep it. Raises `Refused`."""
    store = store_for(deps.state)
    store.get_dataset(identity.tenant_id, identity.user_id, dataset_id)  # the owner only
    have = store.list_items(identity.tenant_id, identity.user_id, dataset_id)
    if len(have) >= MAX_PICTURES:
        raise Refused("too_many", f"A set can hold {MAX_PICTURES} pictures. Remove some first.")
    try:
        img = await asyncio.to_thread(pictures.open_picture, data)
    except pictures.BadPicture as e:
        raise Refused("bad_picture", str(e)) from None
    png = await asyncio.to_thread(pictures.to_png, img)
    await allowed_picture(deps, identity, png)
    others = [int(i["dhash"], 16) for i in have]
    checks = await asyncio.to_thread(pictures.check, img, others)
    row = store.add_item(
        identity.tenant_id, identity.user_id, dataset_id,
        name=name or "picture", width=img.width, height=img.height,
        sha256=pictures.content_hash(png), dhash=pictures.dhash(img), checks=checks,
    )  # fmt: skip
    folder = item_folder(store, identity, row["id"])
    await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread((folder / "picture.png").write_bytes, png)
    await asyncio.to_thread((folder / "thumb.jpg").write_bytes, pictures.thumbnail(img))
    return row


async def remove_picture(deps: RouteDeps, identity: Identity, item_id: str) -> bool:
    store = store_for(deps.state)
    if not store.delete_item(identity.tenant_id, identity.user_id, item_id):
        return False
    await asyncio.to_thread(shutil.rmtree, item_folder(store, identity, item_id), True)
    return True


async def word_problem(engine: Any, word: str) -> str | None:
    """Why the model's own tokenizer finds this a poor magic word, in words, or None (also None
    where the engine cannot read the tokenizer: the sound rules of `magic.valid` still apply)."""
    tokenize = getattr(engine, "tokenize", None)
    if tokenize is None:
        return None
    try:
        found = (await tokenize([word]) or {}).get(word)
    except Exception:
        log.exception("the tokenizer could not be read")
        return None
    return magic.judge(word, found["pieces"], found["known"]) if found else None


async def suggestions(
    store: TrainingStore, identity: Identity, dataset: dict[str, Any], engine: Any = None
) -> list[str]:
    """Three magic words, avoiding the ones this person already uses, and (where the engine can
    read the model's tokenizer) the ones it finds a poor fit."""
    taken = {
        d["trigger_word"]
        for d in store.list_datasets(identity.tenant_id, identity.user_id, 200)
        if d["id"] != dataset["id"] and d["trigger_word"]
    }
    tokenize = getattr(engine, "tokenize", None)
    if tokenize is None:
        return magic.suggest(dataset["name"], dataset["kind"], taken)
    pool = magic.candidates(dataset["name"], dataset["kind"], taken)
    try:
        found = await tokenize(pool) or {}
    except Exception:
        log.exception("the tokenizer could not be read")
        return pool[:3]
    good = [
        w for w in pool if w in found and not magic.judge(w, found[w]["pieces"], found[w]["known"])
    ]
    return (good or pool)[:3]


# ---- the descriptions the app writes --------------------------------------------------------


class CaptionManager:
    """Writes the caption of each picture of a dataset, one at a time (a vision model reads one
    picture in a few seconds), in the background; the screen reads each item's state as it goes."""

    def __init__(self, deps: RouteDeps):
        self._deps = deps
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def busy(self, dataset_id: str) -> bool:
        task = self._tasks.get(dataset_id)
        return task is not None and not task.done()

    async def start(
        self,
        identity: Identity,
        dataset_id: str,
        *,
        again: bool = False,
        only: list[str] | None = None,
    ) -> int:
        """Start writing; returns how many pictures will be described. Raises `Refused`."""
        store = store_for(self._deps.state)
        dataset = store.get_dataset(identity.tenant_id, identity.user_id, dataset_id)
        if self.busy(dataset_id):
            raise Refused("busy", "The descriptions are being written. Wait for them to finish.")
        items = store.list_items(identity.tenant_id, identity.user_id, dataset_id)
        wanted = [
            i for i in items
            if (only is None or i["id"] in only)
            and (again or i["caption_state"] in ("none", "failed"))
        ]  # fmt: skip
        if not wanted:
            return 0
        caps = RouteGuard(self._deps.state, PRODUCT_ID).caps
        if caps is None:
            raise Refused(
                "no_vision_model",
                "Choose a model that can read pictures first (in the Model hub), then try again.",
            )
        for i in wanted:
            store.mark_writing(i["id"])
        self._tasks[dataset_id] = asyncio.create_task(
            self._write(identity, dataset, [i["id"] for i in wanted], caps)
        )
        return len(wanted)

    async def _write(
        self, identity: Identity, dataset: dict[str, Any], ids: list[str], caps: Any
    ) -> None:
        store = store_for(self._deps.state)
        token = set_context(RunContext(identity.tenant_id, PRODUCT_ID, identity.user_id))
        try:
            for item_id in ids:
                try:
                    png = await asyncio.to_thread(
                        (item_folder(store, identity, item_id) / "picture.png").read_bytes
                    )
                    text = await captions.describe(caps, png, dataset["kind"], "")
                    store.set_caption(item_id, text, "done")
                except RunError as e:
                    store.set_caption(item_id, "", "failed", e.message)
                except Exception:
                    log.exception("a caption could not be written")
                    store.set_caption(item_id, "", "failed", "The picture could not be described.")
        except asyncio.CancelledError:
            for item_id in ids:
                try:
                    if (
                        store.get_item(identity.tenant_id, identity.user_id, item_id)[
                            "caption_state"
                        ]
                        == "writing"
                    ):
                        store.set_caption(item_id, "", "none")
                except NotFound:
                    pass
            raise
        finally:
            reset_context(token)

    async def wait(self, dataset_id: str) -> None:
        task = self._tasks.get(dataset_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def stop_all(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)


def caption_manager_for(deps: RouteDeps) -> CaptionManager:
    existing = getattr(deps.state, "training_captions", None)
    if existing is None:
        existing = CaptionManager(deps)
        deps.state.training_captions = existing
    return existing


# ---- the runs -------------------------------------------------------------------------------


def dataset_hash(items: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for i in sorted(items, key=lambda x: x["sha256"]):
        h.update(i["sha256"].encode())
        h.update(i["caption"].encode())
    return h.hexdigest()[:16]


def ready_to_train(dataset: dict[str, Any], items: list[dict[str, Any]]) -> str | None:
    """What is missing before a run, in the sentence the person is shown; None when nothing is."""
    if len(items) < MIN_PICTURES:
        return f"Add at least {MIN_PICTURES} pictures. 15 to 25 good ones is plenty."
    if not dataset["rights"]:
        return "Say whose it is first."
    if not dataset["trigger_word"]:
        return "Choose the magic word first."
    if any(i["caption_state"] not in ("done", "edited") for i in items):
        return "Write the descriptions first."
    return None


class RunManager:
    """Starts, follows and cancels training runs. One at a time on this computer: a run holds the
    one big-model slot (ADR-0056) and most of the GPU."""

    def __init__(self, deps: RouteDeps):
        self._deps = deps
        self._task: asyncio.Task[None] | None = None
        self._run_id: str | None = None
        self._pausing = False

    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def active(self) -> str | None:
        return self._run_id if self.busy() else None

    async def start(
        self,
        identity: Identity,
        dataset_id: str,
        base: str | None = None,
        method: str | None = None,
    ) -> dict[str, Any]:
        """Start teaching. `base` and `method` are the person's choice (`bases`); absent means the
        recommendation, so a caller that does not know about the choice keeps working."""
        state = self._deps.state
        engine, store = engine_for(state), store_for(state)
        if not engine.ready():
            raise Refused("not_ready", not_ready(engine))
        if self.busy():
            raise Refused("busy", "A model is being taught. Wait for it to finish.")
        dataset = store.get_dataset(identity.tenant_id, identity.user_id, dataset_id)
        items = store.list_items(identity.tenant_id, identity.user_id, dataset_id)
        if why := ready_to_train(dataset, items):
            raise Refused("not_ready_to_train", why)
        guard = RouteGuard(state, PRODUCT_ID)
        if refusal := await guard.over_quota(
            identity, EV_RUN, "train_runs_per_user_per_day", "training runs"
        ):
            raise Refused(*refusal)
        fit = engine.fit()
        if fit["verdict"] == "too_big":
            raise Refused("too_big", fit["reason"])
        check = getattr(engine, "preflight", None)
        if check is not None and (blockers := check()["blockers"]):
            raise Refused("not_now", blockers[0])  # not enough disk, a flat battery
        try:
            chosen, how = bases.resolve(dataset["kind"], base, method)
        except bases.Unavailable as e:
            raise Refused("cannot_teach", str(e)) from None
        steps = trainer.steps_for(dataset["kind"], len(items))
        row = store.add_run(
            identity.tenant_id, identity.user_id, dataset_id,
            base=getattr(engine, "base", chosen.id), steps=steps,
            settings={"steps": steps, "kind": dataset["kind"], "method": how,
                      "engine": chosen.engine, "side": trainer.side_for(dataset["kind"])},
            preview=bool(getattr(engine, "preview", False)),
        )  # fmt: skip
        self._run_id = row["id"]
        self._task = asyncio.create_task(self._run(identity, dataset, items, row, engine))
        return row

    async def pause(self, identity: Identity, run_id: str) -> bool:
        """Stop for now and keep the last checkpoint; `resume` picks it up where it stopped."""
        store_for(self._deps.state).get_run(identity.tenant_id, identity.user_id, run_id)  # owner
        if self._task is None or self._task.done() or self._run_id != run_id:
            return False
        engine = engine_for(self._deps.state)
        pause = getattr(engine, "pause", None)
        if pause is None:
            return False
        self._pausing = True
        await pause()
        await asyncio.gather(self._task, return_exceptions=True)
        return True

    async def resume(self, identity: Identity, run_id: str) -> dict[str, Any]:
        state = self._deps.state
        engine, store = engine_for(state), store_for(state)
        row = store.get_run(identity.tenant_id, identity.user_id, run_id)
        if row["status"] != "paused":
            raise Refused("not_paused", "That run is not paused.")
        if not engine.ready():
            raise Refused("not_ready", not_ready(engine))
        if self.busy():
            raise Refused("busy", "A model is being taught. Wait for it to finish.")
        fit = engine.fit()
        if fit["verdict"] == "too_big":
            raise Refused("too_big", fit["reason"])
        check = getattr(engine, "preflight", None)
        if check is not None and (blockers := check()["blockers"]):
            raise Refused("not_now", blockers[0])
        try:
            dataset = store.get_dataset(identity.tenant_id, identity.user_id, row["dataset_id"])
        except NotFound:
            raise Refused(
                "gone", "The pictures of this run were removed, so it cannot go on."
            ) from None
        items = store.list_items(identity.tenant_id, identity.user_id, dataset["id"])
        store.resume_run(run_id)
        row = store.get_run(identity.tenant_id, identity.user_id, run_id)
        self._run_id = run_id
        self._task = asyncio.create_task(
            self._run(identity, dataset, items, row, engine, resume=True)
        )
        return row

    async def _run(
        self, identity: Identity, dataset: dict[str, Any], items: list[dict[str, Any]],
        row: dict[str, Any], engine: Any, resume: bool = False,
    ) -> None:  # fmt: skip
        store = store_for(self._deps.state)
        run_id = row["id"]
        token = set_context(RunContext(identity.tenant_id, PRODUCT_ID, identity.user_id))
        folder = run_folder(store, identity, run_id)
        try:
            await asyncio.to_thread((folder / "samples").mkdir, parents=True, exist_ok=True)
            job = trainer.TrainJob(
                kind=dataset["kind"], word=dataset["trigger_word"], steps=row["steps"],
                pictures=[item_folder(store, identity, i["id"]) / "picture.png" for i in items],
                captions=[captions.with_word(i["caption"], dataset["trigger_word"]) for i in items],
                samples=folder / "samples", settings=row["settings"],
            )  # fmt: skip
            result = await engine.train(
                job,
                lambda step, stage: store.set_progress(run_id, step, stage),
                lambda name: store.add_sample(run_id, name),
                **({"resume": True} if resume else {}),
            )
            model = await self._keep(identity, dataset, items, row, result)
            store.finish_run(run_id, "done", elapsed_s=result.seconds, model_id=model["id"])
            await RouteGuard(self._deps.state, PRODUCT_ID).record(
                identity, EV_RUN, 1, "runs", steps=row["steps"], seconds=result.seconds,
                preview=bool(row["preview"]),
            )  # fmt: skip
            await add_to_search(self._deps.state, identity, model["id"], words_of(model))
        except trainer.Paused as p:
            store.pause_run(run_id, f"Paused at step {p.step} of {row['steps']}")
        except trainer.Stopped as e:
            store.finish_run(run_id, "cancelled", error=str(e))
        except asyncio.CancelledError:
            store.finish_run(run_id, "cancelled", error="Stopped.")
            raise
        except Exception:
            log.exception("a training run failed")
            store.finish_run(run_id, "failed", error="The model could not be taught. Try again.")
        finally:
            self._pausing = False
            reset_context(token)

    async def _keep(
        self, identity: Identity, dataset: dict[str, Any], items: list[dict[str, Any]],
        row: dict[str, Any], result: trainer.TrainResult,
    ) -> dict[str, Any]:  # fmt: skip
        """The adapter becomes a model with its card (ADR-0073 decision 9)."""
        store = store_for(self._deps.state)
        card = {
            "base": row["base"], "base_title": trainer.BASE_TITLE, "licence": trainer.BASE_LICENCE,
            "engine": result.engine, "preview": bool(row["preview"]), "note": result.note,
            "dataset": {"name": dataset["name"], "kind": dataset["kind"], "pictures": len(items),
                        "hash": dataset_hash(items)},
            "settings": row["settings"], "steps": row["steps"], "seconds": round(result.seconds, 1),
            "peak_memory_gb": round(result.peak_bytes / 1024**3, 1) if result.peak_bytes else None,
            "trigger_word": dataset["trigger_word"],
            "statement": STATEMENTS.get(dataset["rights"], ""),
            "evaluation": {"passed": None, "note": "Not evaluated yet."},
            "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }  # fmt: skip
        size = (await asyncio.to_thread(result.adapter.stat)).st_size
        card["published"] = await self._publish(dataset, row, result)
        model = store.add_model(
            identity.tenant_id, identity.user_id, run_id=row["id"], dataset_id=dataset["id"],
            name=dataset["name"] or dataset["trigger_word"], trigger_word=dataset["trigger_word"],
            kind=dataset["kind"], base=row["base"], card=card, preview=bool(row["preview"]),
            adapter_bytes=size,
        )  # fmt: skip
        folder = model_folder(store, identity, model["id"])
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, result.adapter, folder / "adapter.safetensors")
        # a few of the pictures it learnt from, small: what a check compares what it draws with
        refs = [item_folder(store, identity, i["id"]) / "picture.png" for i in items]
        await asyncio.to_thread(evaluation.save_refs, refs, folder / "refs")
        await asyncio.to_thread((folder / "card.json").write_text, json.dumps(card, indent=2))
        return model

    async def _publish(
        self, dataset: dict[str, Any], row: dict[str, Any], result: trainer.TrainResult
    ) -> dict[str, str] | None:
        """Where the image engine reads it: the engine converts the adapter to the names its model
        uses and puts it with its other styles. A failure leaves the model kept, unpublished."""
        publish = getattr(engine_for(self._deps.state), "publish", None)
        if publish is None or result.engine == "preview":
            return None
        try:
            name = await publish(
                result.adapter, dataset["name"] or dataset["trigger_word"], row["id"]
            )
        except Exception:
            log.exception("a trained model could not be published to the image engine")
            return None
        return {"lora_name": name} if name else None

    async def cancel(self, identity: Identity, run_id: str) -> bool:
        """Stop a run that is going, or discard one that is paused (its kept files go)."""
        store = store_for(self._deps.state)
        row = store.get_run(identity.tenant_id, identity.user_id, run_id)  # owner
        if row["status"] == "paused" and not (self.busy() and self._run_id == run_id):
            store.finish_run(run_id, "cancelled", error="Discarded.")
            folder = run_folder(store, identity, run_id)
            for part in ("work", "out"):
                await asyncio.to_thread(shutil.rmtree, folder / part, True)
            return True
        if self._task is None or self._task.done() or self._run_id != run_id:
            return False
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        return True

    async def wait(self, run_id: str) -> None:
        if self._task is not None and self._run_id == run_id:
            await asyncio.gather(self._task, return_exceptions=True)

    async def stop_all(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)


def model_or_none(deps: RouteDeps, identity: Identity, model_id: str) -> dict[str, Any] | None:
    try:
        return store_for(deps.state).get_model(identity.tenant_id, identity.user_id, model_id)
    except NotFound:
        return None


def run_manager_for(deps: RouteDeps) -> RunManager:
    existing = getattr(deps.state, "training_runs", None)
    if existing is None:
        existing = RunManager(deps)
        deps.state.training_runs = existing
    return existing


# ---- deleting -------------------------------------------------------------------------------


async def delete_model(deps: RouteDeps, identity: Identity, model_id: str) -> bool:
    store = store_for(deps.state)
    try:
        published = (
            store.get_model(identity.tenant_id, identity.user_id, model_id)["card"] or {}
        ).get("published")
    except NotFound:
        published = None
    if not store.delete_model(identity.tenant_id, identity.user_id, model_id):
        return False
    lang = getattr(deps.state, "desktop_language", None)
    chosen = getattr(getattr(lang, "selected", None), "style", None)
    if lang is not None and chosen == model_id:
        with contextlib.suppress(Exception):
            await lang.end_style()  # a model that is gone is not the one chat answers with
    unpublish = getattr(engine_for(deps.state), "unpublish", None)
    if published and unpublish is not None:
        with contextlib.suppress(Exception):
            await unpublish(published["lora_name"])  # the image engine no longer offers it
    await asyncio.to_thread(shutil.rmtree, model_folder(store, identity, model_id), True)
    await deps.unindex(identity, PRODUCT_ID, model_id)
    return True


async def delete_dataset(deps: RouteDeps, identity: Identity, dataset_id: str) -> bool:
    store = store_for(deps.state)
    items = store.list_items(identity.tenant_id, identity.user_id, dataset_id)
    if not store.delete_dataset(identity.tenant_id, identity.user_id, dataset_id):
        return False
    for i in items:
        await asyncio.to_thread(shutil.rmtree, item_folder(store, identity, i["id"]), True)
    return True
