"""What the 3D product needs at run time: its store, the engine's 3D component, and the one job that
may run at a time (the cut-out of a picture, or a model being made).

The engine (`state.model3d`) comes from the app state, as the Video Builder's does, so this package
imports nothing from the API. A 3D run holds about 19 GB and takes 5 to 25 minutes, so there is one
at a time, it shows its progress, and it can be cancelled: the process is killed and its memory is
free again at once."""

import asyncio
import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import Identity, RouteDeps, search_text

from wasifyai_model3d import pictures
from wasifyai_model3d.store import Model3dStore, NotFound

log = logging.getLogger(__name__)

PRODUCT_ID = "wasifyai-model3d"
KIND = "model3d"
DETAILS = ("light", "standard", "detailed")
MAX_SEED = 2**31 - 1


class NotAvailable(Exception):
    """This deployment has no 3D engine (the web deployment, for now)."""


class Refused(Exception):
    """A request that cannot be done now, with the sentence the person is shown."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def engine_for(state: Any) -> Any:
    engine = getattr(state, "model3d", None)
    if engine is None:
        raise NotAvailable("3D models are not available in this deployment.")
    return engine


def root_for(state: Any) -> Path:
    data = getattr(state, "desktop_dir", None)
    if not data:
        raise NotAvailable("3D models are not available in this deployment.")
    return Path(data) / "model3d"


def _remove_leftovers(folder: Path) -> None:
    for leftover in folder.glob("unused*"):
        leftover.unlink(missing_ok=True)


KEEP_PICTURES_DAYS = 14  # a picture nobody made a model from


def store_for(state: Any) -> Model3dStore:
    existing = getattr(state, "model3d_store", None)
    if existing is None:
        existing = Model3dStore(root_for(state))
        state.model3d_store = existing
        old = (datetime.now(UTC) - timedelta(days=KEEP_PICTURES_DAYS)).isoformat()
        for tenant, user, item in existing.purge_inputs(old):
            shutil.rmtree(existing.folder_of(tenant, user, "inputs", item), ignore_errors=True)
    return existing


def not_ready(engine: Any) -> str:
    why = getattr(engine, "problem", lambda: None)()
    return why or "The 3D component is not set up yet. Set it up first."


async def add_to_search(state: Any, identity: Identity, item_id: str, text: str) -> None:
    """Make a model searchable by its words (ADR-0041): best effort, never fails the request."""
    index = getattr(state, "creation_index", None)
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
    existing = getattr(deps.state, "model3d_jobs", None)
    if existing is None:
        existing = JobManager(deps)
        deps.state.model3d_jobs = existing
    return existing


class JobManager:
    """One job at a time: the cut-out of a picture, or a model being made."""

    def __init__(self, deps: RouteDeps):
        self._deps = deps
        self._task: asyncio.Task[None] | None = None
        self._what: tuple[str, str] | None = None  # ("input" | "model", id)
        self._cancelled: set[str] = set()

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def active(self) -> dict[str, str] | None:
        return {"kind": self._what[0], "id": self._what[1]} if self.busy and self._what else None

    async def wait(self, item_id: str) -> None:
        if self._what and self._what[1] == item_id and self._task is not None:
            await asyncio.shield(self._task)

    def _begin(self, kind: str, item_id: str, coro: Any) -> None:
        self._what = (kind, item_id)
        self._task = asyncio.create_task(coro)

    # ---- a picture: its cut-out and its checks ---------------------------------------------

    async def prepare(self, identity: Identity, input_id: str, picture: bytes) -> dict[str, Any]:
        """Save the picture and start looking at it. The cut-out takes under two minutes."""
        state = self._deps.state
        engine, store = engine_for(state), store_for(state)
        if not engine.ready():
            raise Refused("not_ready", not_ready(engine))
        if self.busy:
            raise Refused("busy", "A 3D model is being worked on. Wait for it to finish.")
        row = store.get_input(identity.tenant_id, identity.user_id, input_id)
        folder = store.folder_of(identity.tenant_id, identity.user_id, "inputs", input_id)
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread((folder / "picture.png").write_bytes, picture)
        self._begin("input", input_id, self._prepare(identity, row, folder, engine, store))
        return row

    async def _prepare(
        self,
        identity: Identity,
        row: dict[str, Any],
        folder: Path,
        engine: Any,
        store: Model3dStore,
    ) -> None:
        item = row["id"]
        try:
            from PIL import Image

            picture = await asyncio.to_thread(Image.open, folder / "picture.png")
            picture.load()
            if pictures.has_real_alpha(picture):  # already cut out: nothing to cut
                await asyncio.to_thread(
                    shutil.copyfile, folder / "picture.png", folder / "cutout.png"
                )
            else:
                store.set_input_stage(item, "Cutting out the object")
                res = await engine.matte(folder / "picture.png", folder)
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
        engine, store = engine_for(state), store_for(state)
        if not engine.ready():
            raise Refused("not_ready", not_ready(engine))
        if detail not in DETAILS:
            raise Refused("bad_detail", "Choose Light, Standard or Detailed.")
        if not 0 <= seed <= MAX_SEED:
            raise Refused("bad_seed", "The seed must be a whole number.")
        if self.busy:
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
        row = store.add_model(
            identity.tenant_id, identity.user_id, title=title.strip() or "3D model",
            prompt=prompt.strip(), input_id=input_id, detail=detail, seed=seed, recipe=recipe,
        )  # fmt: skip
        try:
            src = store.folder_of(identity.tenant_id, identity.user_id, "inputs", input_id)
            dst = store.folder_of(identity.tenant_id, identity.user_id, "models", row["id"])
            await asyncio.to_thread(dst.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copyfile, src / "picture.png", dst / "source.png")
            await asyncio.to_thread(shutil.copyfile, src / "cutout.png", dst / "cutout.png")
        except OSError:
            store.finish_model(row["id"], "failed", error="The picture could not be copied.")
            raise Refused(
                "no_picture", "That picture is not here any more. Add it again."
            ) from None
        await add_to_search(state, identity, row["id"], words_of(row))
        self._begin("model", row["id"], self._make(identity, row, dst, engine, store))
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
        folder: Path,
        engine: Any,
        store: Model3dStore,
    ) -> None:
        item = row["id"]
        glb = folder / "model.glb"
        try:
            res = await engine.generate(
                folder / "cutout.png", glb, seed=row["seed"], detail=row["detail"],
                on_progress=lambda fraction, words: store.set_progress(item, fraction, words),
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
            store.finish_model(
                item, "done", elapsed_s=res.seconds, peak_gb=res.peak_gb, glb_bytes=size
            )
        except asyncio.CancelledError:
            store.finish_model(item, "cancelled", error="Stopped.")
            await asyncio.to_thread(shutil.rmtree, folder / "work-model", True)
            raise
        except Exception:
            log.exception("a 3D model failed")
            store.finish_model(item, "failed", error="The 3D model could not be saved.")

    async def cancel(self, identity: Identity, model_id: str) -> bool:
        """Stop the model being made, or the picture being cut out. False if there was nothing."""
        store = store_for(self._deps.state)
        store.get_model(identity.tenant_id, identity.user_id, model_id)  # the owner only
        if self._what and self._what[1] == model_id and self.busy and self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            return True
        return False

    async def cancel_input(self, identity: Identity, input_id: str) -> bool:
        store = store_for(self._deps.state)
        store.get_input(identity.tenant_id, identity.user_id, input_id)
        if self._what and self._what[1] == input_id and self.busy and self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            return True
        return False

    async def stop_all(self) -> None:
        if self.busy and self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)


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
    folder = store.folder_of(identity.tenant_id, identity.user_id, "models", model_id)
    store.delete_model(identity.tenant_id, identity.user_id, model_id)
    await asyncio.to_thread(shutil.rmtree, folder, True)
    await deps.unindex(identity, PRODUCT_ID, model_id)
    return True


__all__ = [
    "DETAILS", "KIND", "PRODUCT_ID", "JobManager", "NotAvailable", "Refused", "add_to_search",
    "delete_model", "engine_for", "manager_for", "not_ready", "root_for", "store_for", "words_of",
]  # fmt: skip
