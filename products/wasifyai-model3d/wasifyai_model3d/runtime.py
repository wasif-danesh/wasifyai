"""What the 3D product needs at run time: its store, its files, the engine's 3D component, and the
jobs that run (the cut-out of a picture, or a model being made).

The engine (`state.model3d`) comes from the app state, as the Motion graphics' does, so this package
imports nothing from the API. On the desktop it is the component on this computer; on the web it
is a client of an engine worker (ADR-0087, P3), the store is Postgres and the files are in object
storage (`state.model3d_store`, `state.model3d_blobs`). A 3D run holds about 19 GB and takes 5 to
25 minutes, so a person has one at a time (the desktop has one in all), it shows its progress, and
it can be cancelled: the process is killed and its memory is free again at once."""

import asyncio
import logging
import shutil
from datetime import UTC, datetime, timedelta
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

from wasifyai_model3d import guardrail, pictures
from wasifyai_model3d.blobs import LocalBlobs
from wasifyai_model3d.store import Model3dStore, NotFound

log = logging.getLogger(__name__)

PRODUCT_ID = "wasifyai-model3d"
KIND = "model3d"
DETAILS = ("light", "standard", "detailed")
MAX_SEED = 2**31 - 1
STALE_AFTER = timedelta(hours=3)  # a model "working" for longer than this has no one working on it
STOPPED = "It was stopped before it finished. Make it again."
EV_PICTURE = "model3d.picture"  # usage events that the daily limits count (ADR-0047)
EV_MODEL = "model3d.model"


class NotAvailable(Exception):
    """This deployment has no 3D engine (no desktop component, and no worker that has one)."""


class Refused(Exception):
    """A request that cannot be done now, with the sentence the person is shown."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def engine_for(state: Any) -> Any:
    engine = state.model3d
    if engine is None:
        raise NotAvailable("3D models are not available in this deployment.")
    return engine


def root_for(state: Any) -> Path:
    data = state.desktop_dir
    if not data:
        raise NotAvailable("3D models are not available in this deployment.")
    return Path(data) / "model3d"


def _remove_leftovers(folder: Path) -> None:
    for leftover in folder.glob("unused*"):
        leftover.unlink(missing_ok=True)


KEEP_PICTURES_DAYS = 14  # a picture nobody made a model from


def store_for(state: Any) -> Model3dStore:
    existing = state.model3d_store
    if existing is None:  # the desktop: a file beside the app's other data
        existing = Model3dStore(root_for(state))
        state.model3d_store = existing
        state.model3d_blobs = LocalBlobs(existing)
        old = (datetime.now(UTC) - timedelta(days=KEEP_PICTURES_DAYS)).isoformat()
        for tenant, user, item in existing.purge_inputs(old):
            shutil.rmtree(existing.folder_of(tenant, user, "inputs", item), ignore_errors=True)
    return existing


def blobs_for(state: Any) -> Any:
    store_for(state)  # the desktop makes its files' home with its store
    return state.model3d_blobs


async def sweep(state: Any) -> None:
    """The web's start-up tidy: pictures nobody used and work whose owner is gone."""
    store, blobs = store_for(state), blobs_for(state)
    old = (datetime.now(UTC) - timedelta(days=KEEP_PICTURES_DAYS)).isoformat()
    for tenant, user, item in await asyncio.to_thread(store.purge_inputs, old):
        await blobs.remove((tenant, user), "inputs", item)
    stale = (datetime.now(UTC) - STALE_AFTER).isoformat()
    await asyncio.to_thread(store.fail_stale, stale, STOPPED)


async def resume(deps: RouteDeps) -> int:
    """After `sweep`: go on waiting for what the workers were still making when this service
    stopped. The manager is the one the routes use, so a person sees it as it was."""
    return await manager_for(deps).resume_all()


def not_ready(engine: Any) -> str:
    why = getattr(engine, "problem", lambda: None)()
    return why or "The 3D component is not set up yet. Set it up first."


async def add_to_search(state: Any, identity: Identity, item_id: str, text: str) -> None:
    """Make a model searchable by its words (ADR-0041): best effort, never fails the request."""
    index = state.creation_index
    if index is None:
        return
    try:
        await index.index(
            identity.tenant_id, PRODUCT_ID, identity.user_id, KIND, item_id, search_text(text)
        )
    except Exception:
        log.warning("the 3D model could not be added to search", exc_info=True)


def words_of(row: dict[str, Any]) -> str:
    return ". ".join(x for x in (row["title"], row["prompt"]) if x and x.strip())


def manager_for(deps: RouteDeps) -> "JobManager":
    existing = deps.state.model3d_jobs
    if existing is None:
        existing = JobManager(deps)
        deps.state.model3d_jobs = existing
    return existing


class JobManager:
    """One job at a time for a person: the cut-out of a picture, or a model being made. On the
    desktop there is one person, so one job in all."""

    def __init__(self, deps: RouteDeps):
        self._deps = deps
        # who -> (what, id, task); the desktop's one person is "-"
        self._jobs: dict[str, tuple[str, str, asyncio.Task[None]]] = {}

    def _who(self, identity: Identity) -> str:
        local = getattr(blobs_for(self._deps.state), "local", True)
        return "-" if local else f"{identity.tenant_id}/{identity.user_id}"

    def busy(self, identity: Identity) -> bool:
        job = self._jobs.get(self._who(identity))
        return job is not None and not job[2].done()

    def active(self, identity: Identity) -> dict[str, str] | None:
        job = self._jobs.get(self._who(identity))
        return {"kind": job[0], "id": job[1]} if job and not job[2].done() else None

    def _task_of(self, identity: Identity, item_id: str) -> asyncio.Task[None] | None:
        job = self._jobs.get(self._who(identity))
        return job[2] if job and job[1] == item_id and not job[2].done() else None

    async def wait(self, identity: Identity, item_id: str) -> None:
        task = self._task_of(identity, item_id)
        if task is not None:
            await asyncio.shield(task)

    def _begin(self, identity: Identity, kind: str, item_id: str, coro: Any) -> None:
        async def run() -> None:
            # the engine reads whose job this is from the context (the web keeps files per person)
            token = set_context(RunContext(identity.tenant_id, PRODUCT_ID, identity.user_id))
            try:
                await coro
            finally:
                reset_context(token)

        self._jobs[self._who(identity)] = (kind, item_id, asyncio.create_task(run()))

    # ---- a picture: its cut-out and its checks ---------------------------------------------

    async def prepare(self, identity: Identity, input_id: str, picture: bytes) -> dict[str, Any]:
        """Save the picture and start looking at it. The cut-out takes under two minutes."""
        state = self._deps.state
        engine, store, blobs = engine_for(state), store_for(state), blobs_for(state)
        if not engine.ready():
            raise Refused("not_ready", not_ready(engine))
        if self.busy(identity):
            raise Refused("busy", "A 3D model is being worked on. Wait for it to finish.")
        await self._allowed_picture(identity, picture)
        row = store.get_input(identity.tenant_id, identity.user_id, input_id)
        await blobs.put(identity, "inputs", input_id, "picture.png", picture)
        self._begin(identity, "input", input_id, self._prepare(identity, row, engine, store, blobs))
        return row

    async def _allowed_picture(self, identity: Identity, picture: bytes) -> None:
        """The day's limit, then the picture check: both only while the safeguards are on (P6).
        The check fails closed, and the picture is not kept when it is refused."""
        guard = RouteGuard(self._deps.state, PRODUCT_ID)
        if refusal := await guard.over_quota(
            identity, EV_PICTURE, "pictures_per_user_per_day", "pictures"
        ):
            raise Refused(*refusal)
        if await guard.on():
            caps = guard.caps
            unavailable = Refused(
                "moderation_unavailable",
                "We couldn't check your picture right now. Please try again.",
            )
            if caps is None:
                raise unavailable
            token = set_context(RunContext(identity.tenant_id, PRODUCT_ID, identity.user_id))
            try:
                verdict = await guardrail.judge_picture(caps, picture)
            except RunError as e:
                raise Refused(e.code, e.message) from None
            except Exception:  # no moderator bound, or the gateway is down: nothing is let through
                log.exception("the 3D picture check failed")
                raise unavailable from None
            finally:
                reset_context(token)
            if not verdict.allowed:
                raise Refused(verdict.category, guardrail.refusal_message(verdict.category))
        await guard.record(identity, EV_PICTURE, 1, "pictures")

    async def _prepare(
        self,
        identity: Identity,
        row: dict[str, Any],
        engine: Any,
        store: Model3dStore,
        blobs: Any,
        resume: bool = False,
    ) -> None:
        item = row["id"]
        # a worker's engine finds its job again by the row's id, so a restart does not lose it
        again = {"job_key": item, "resume": resume} if getattr(engine, "resumable", False) else {}
        try:
            from PIL import Image

            async with blobs.workspace(
                identity, "inputs", item, pull=("picture.png",), push=("cutout.png",)
            ) as folder:
                picture = await asyncio.to_thread(Image.open, folder / "picture.png")
                picture.load()
                if pictures.has_real_alpha(picture):  # already cut out: nothing to cut
                    await asyncio.to_thread(
                        shutil.copyfile, folder / "picture.png", folder / "cutout.png"
                    )
                else:
                    store.set_input_stage(item, "Cutting out the object")
                    res = await engine.matte(folder / "picture.png", folder, **again)
                    if not res.ok or res.output is None:
                        store.set_input(
                            item, status="failed", error=res.message or "The cut-out did not work."
                        )
                        return
                    await asyncio.to_thread(res.output.replace, folder / "cutout.png")
                    await asyncio.to_thread(_remove_leftovers, folder)
                cut = await asyncio.to_thread(Image.open, folder / "cutout.png")
                cut.load()
                checks = await asyncio.to_thread(pictures.check_cutout, cut.convert("RGBA"))
            store.set_input(item, status="ready", checks=checks, stage="")
        except asyncio.CancelledError:
            if not getattr(engine, "closing", False):  # not just this service stopping
                store.set_input(item, status="failed", error="Stopped.")
            raise
        except Exception:
            log.exception("a 3D picture could not be prepared")
            store.set_input(item, status="failed", error="The picture could not be looked at.")

    # ---- a model --------------------------------------------------------------------------------

    async def start(
        self,
        identity: Identity,
        input_id: str,
        *,
        title: str = "",
        prompt: str = "",
        detail: str = "standard",
        seed: int = 42,
    ) -> dict[str, Any]:
        state = self._deps.state
        engine, store, blobs = engine_for(state), store_for(state), blobs_for(state)
        if not engine.ready():
            raise Refused("not_ready", not_ready(engine))
        if detail not in DETAILS:
            raise Refused("bad_detail", "Choose Light, Standard or Detailed.")
        if not 0 <= seed <= MAX_SEED:
            raise Refused("bad_seed", "The seed must be a whole number.")
        if self.busy(identity):
            raise Refused("busy", "A 3D model is already being made. Wait for it to finish.")
        fit = engine.fit()
        if fit["verdict"] == "too_big":
            raise Refused("too_big", fit["reason"])
        try:
            source = store.get_input(identity.tenant_id, identity.user_id, input_id)
        except NotFound:
            raise Refused(
                "no_picture", "That picture is not here any more. Add it again."
            ) from None
        if source["status"] != "ready":
            raise Refused("not_checked", "The picture is still being looked at.")
        if any(c["level"] == "stop" for c in source["checks"]):
            raise Refused("unusable", "That picture cannot be made into a model. Try another.")
        recipe = {"detail": detail, "seed": seed, "engine": "pixal3d-cpp-sv", "resolution": 1024,
                  "licence": "conditional: Built with DINOv3"}  # fmt: skip
        if refusal := await RouteGuard(state, PRODUCT_ID).over_quota(
            identity, EV_MODEL, "models_per_user_per_day", "3D models"
        ):
            raise Refused(*refusal)
        row = store.add_model(
            identity.tenant_id, identity.user_id, title=title.strip() or "3D model",
            prompt=prompt.strip(), input_id=input_id, detail=detail, seed=seed, recipe=recipe,
        )  # fmt: skip
        try:
            copied = await blobs.copy(
                identity, "inputs", input_id, "picture.png", row["id"], "source.png"
            ) and await blobs.copy(
                identity, "inputs", input_id, "cutout.png", row["id"], "cutout.png"
            )
            if not copied:
                raise OSError("the picture is gone")
        except (OSError, FileNotFoundError):
            store.finish_model(row["id"], "failed", error="The picture could not be copied.")
            raise Refused(
                "no_picture", "That picture is not here any more. Add it again."
            ) from None
        await add_to_search(state, identity, row["id"], words_of(row))
        self._begin(identity, "model", row["id"], self._make(identity, row, engine, store, blobs))
        return row

    async def start_again(self, identity: Identity, row: dict[str, Any]) -> dict[str, Any]:
        """The same picture, seed and detail: the same model, as a new one."""
        return await self.start(
            identity, row["input_id"], title=row["title"], prompt=row["prompt"],
            detail=row["detail"], seed=row["seed"],
        )  # fmt: skip

    async def _make(
        self,
        identity: Identity,
        row: dict[str, Any],
        engine: Any,
        store: Model3dStore,
        blobs: Any,
        resume: bool = False,
    ) -> None:
        item = row["id"]
        again = {"job_key": item, "resume": resume} if getattr(engine, "resumable", False) else {}
        try:
            async with blobs.workspace(
                identity, "models", item, pull=("cutout.png",), push=("model.glb", "thumb.jpg")
            ) as folder:
                glb = folder / "model.glb"
                res = await engine.generate(
                    folder / "cutout.png", glb, seed=row["seed"], detail=row["detail"],
                    on_progress=lambda fraction, words: store.set_progress(item, fraction, words),
                    **again,
                )  # fmt: skip
                if not res.ok or not glb.is_file():
                    store.finish_model(
                        item, "failed", error=res.message or "The 3D run did not finish.",
                        elapsed_s=res.seconds, peak_gb=res.peak_gb,
                    )  # fmt: skip
                    return
                from PIL import Image

                cut = await asyncio.to_thread(Image.open, folder / "cutout.png")
                cut.load()
                thumb = await asyncio.to_thread(pictures.thumbnail, cut.convert("RGBA"))
                await asyncio.to_thread((folder / "thumb.jpg").write_bytes, thumb)
                size = (await asyncio.to_thread(glb.stat)).st_size
            # the files are in their home now: only then is the model done
            store.finish_model(
                item, "done", elapsed_s=res.seconds, peak_gb=res.peak_gb, glb_bytes=size
            )
            await RouteGuard(self._deps.state, PRODUCT_ID).record(
                identity, EV_MODEL, 1, "models", detail=row["detail"], seconds=res.seconds
            )
        except asyncio.CancelledError:
            if not getattr(engine, "closing", False):
                store.finish_model(item, "cancelled", error="Stopped.")
            raise
        except Exception:
            log.exception("a 3D model failed")
            store.finish_model(item, "failed", error="The 3D model could not be saved.")

    async def resume_all(self) -> int:
        """Pick up what was being worked on when this service stopped: the worker went on with it,
        and its outcome is waiting. What the worker no longer has is failed in words. Returns how
        many were picked up."""
        state = self._deps.state
        engine, store, blobs = engine_for(state), store_for(state), blobs_for(state)
        if not getattr(engine, "resumable", False):
            return 0
        picked = 0
        for row in store.working_inputs():
            who = Identity(row["tenant_id"], row["user_id"])
            if self.busy(who):
                continue
            self._begin(
                who, "input", row["id"], self._prepare(who, row, engine, store, blobs, resume=True)
            )
            picked += 1
        for row in store.working_models():
            who = Identity(row["tenant_id"], row["user_id"])
            if self.busy(who):
                continue
            self._begin(
                who, "model", row["id"], self._make(who, row, engine, store, blobs, resume=True)
            )
            picked += 1
        return picked

    async def cancel(self, identity: Identity, model_id: str) -> bool:
        """Stop the model being made, or the picture being cut out. False if there was nothing."""
        store = store_for(self._deps.state)
        store.get_model(identity.tenant_id, identity.user_id, model_id)  # the owner only
        task = self._task_of(identity, model_id)
        if task is None:
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return True

    async def cancel_input(self, identity: Identity, input_id: str) -> bool:
        store = store_for(self._deps.state)
        store.get_input(identity.tenant_id, identity.user_id, input_id)
        task = self._task_of(identity, input_id)
        if task is None:
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return True

    async def stop_all(self) -> None:
        tasks = [t for _, _, t in self._jobs.values() if not t.done()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def delete_model(deps: RouteDeps, identity: Identity, model_id: str) -> bool:
    """Delete a model with its files and its search entry; a run in progress is stopped first."""
    state = deps.state
    store = store_for(state)
    try:
        store.get_model(identity.tenant_id, identity.user_id, model_id)
    except NotFound:
        return False
    jobs = manager_for(deps)
    await jobs.cancel(identity, model_id)
    store.delete_model(identity.tenant_id, identity.user_id, model_id)
    await blobs_for(state).remove(identity, "models", model_id)
    await deps.unindex(identity, PRODUCT_ID, model_id)
    return True


__all__ = [
    "DETAILS", "KIND", "PRODUCT_ID", "JobManager", "NotAvailable", "Refused", "add_to_search",
    "blobs_for", "delete_model", "engine_for", "manager_for", "not_ready", "root_for", "store_for",
    "sweep", "words_of",
]  # fmt: skip
