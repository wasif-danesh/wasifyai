"""What Motion graphics needs at run time: its store, the engine's render component, and the one
render that may run at a time.

The component (`state.video_builder`) comes from the engine's app state, as the voice product's
speech runtime does, so this package imports nothing from the API. A finished render becomes a clip
of the video product (a row of `videos` with `mode = "composition"`, its files in the same storage
layout), so Your videos, search, export and delete already work on it."""

import asyncio
import logging
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import Identity, RouteDeps, RouteUsage, RunError, search_text

from wasifyai_video.builder import check, draft, media, projects, templates
from wasifyai_video.builder.store import BuilderStore, NotFound
from wasifyai_video.index import index_text
from wasifyai_video.videos import PosterError, VideoRecord, poster_of, video_store

log = logging.getLogger(__name__)

PRODUCT_ID = "wasifyai-video"  # the library the renders go to
PROGRESS = re.compile(r"(\d{1,3})\s*%")
MIME = {"mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime"}


QUALITIES = ("draft", "standard", "high")  # HyperFrames' own words for them


class NotAvailable(Exception):
    """Motion graphics is not served by this deployment (no desktop engine)."""


class Refused(Exception):
    """A request that cannot be done now, with the sentence the person is shown."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def not_ready(engine: Any) -> str:
    """Why the engine cannot draw now, in words (its own sentence when it has one)."""
    why = getattr(engine, "problem", lambda: None)()
    return why or "Motion graphics is not set up yet. Set it up first."


def engine_for(state: Any) -> Any:
    engine = state.video_builder
    if engine is None:
        raise NotAvailable("Motion graphics is not available in this deployment.")
    return engine


async def make_draft(
    deps: RouteDeps,
    identity: Identity,
    prompt: str,
    attachment: dict[str, str] | None = None,
    shape: str | None = None,
) -> dict[str, Any]:
    """The template and fields a description means (`draft.draft`), asked of the chosen chat
    model; nothing is saved. Raises `Refused` with the sentence the person is shown."""
    try:
        with deps.acting_as(identity, "wasifyai-video"):
            return await draft.draft(engine_for(deps.state), prompt, attachment, shape)
    except draft.DraftError as e:
        raise Refused(e.code, e.message) from None
    except RunError as e:
        raise Refused(e.code, e.message) from None


def root_for(state: Any) -> Path:
    scratch = state.builder_scratch  # the web: a folder for stand-in projects
    if scratch is not None:
        return Path(scratch)
    data = state.desktop_dir
    if not data:
        raise NotAvailable("Motion graphics is not available in this deployment.")
    return Path(data) / "video-builder"


def store_for(state: Any) -> BuilderStore:
    existing = state.builder_store
    if existing is not None:
        return existing  # type: ignore[no-any-return]
    store = BuilderStore.in_folder(root_for(state))
    state.builder_store = store
    return store


async def add_to_search(state: Any, identity: Identity, kind: str, item_id: str, text: str) -> None:
    """Make a creation searchable by its words (ADR-0041): best effort, never fails the request."""
    index = state.creation_index
    if index is None:
        return
    try:
        await index.index(
            identity.tenant_id, PRODUCT_ID, identity.user_id, kind, item_id, search_text(text)
        )
    except Exception:
        log.warning("the creation could not be added to search", exc_info=True)


def manager_for(deps: RouteDeps) -> "RenderManager":
    existing = deps.state.builder_renders
    if existing is None:
        existing = RenderManager(deps)
        deps.state.builder_renders = existing
    return existing  # type: ignore[no-any-return]


STOPPED = "It was stopped before it finished. Make it again."
EV_RENDER = "builder.render"  # the usage event a finished video records


async def put_files_beside(
    deps: RouteDeps, identity: Identity, found: dict[str, Any], folder: Path, engine: Any
) -> None:
    """A project's files, next to its page, for what opens it on this machine. A worker's engine
    gets them with the job (`remote_builder`)."""
    if getattr(engine, "carries_files", False) or deps.storage is None:
        return
    owner = (identity.tenant_id, PRODUCT_ID, identity.user_id)
    for asset in found["slots"].get("assets") or []:
        target = folder / "assets" / asset["file"]
        if await asyncio.to_thread(target.exists):
            continue
        data = await deps.storage.get_for(owner, media.rel_path(found["id"], asset["file"]))
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, data)


def _in_shape(found: dict[str, Any], shape: str) -> dict[str, Any]:
    """The project as it is in another shape, for one video: nothing of it is saved."""
    return {**found, "slots": {**found["slots"], "shape": shape}}


class RenderManager:
    """Starts, follows and cancels renders. One at a time on this computer: a render holds a
    browser and a few gigabytes, and the person's models need the memory too."""

    def __init__(self, deps: RouteDeps):
        self._deps = deps
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._owners: dict[str, str] = {}
        self._progress: dict[str, float] = {}
        self._stage: dict[str, str] = {}

    def _who(self, identity: Identity) -> str:
        """The desktop has one person, so one render in all; the web has one per person."""
        if self._deps.state.builder_scratch is None:
            return "-"
        return f"{identity.tenant_id}/{identity.user_id}"

    def busy(self, identity: Identity) -> bool:
        who = self._who(identity)
        return any(not t.done() and self._owners.get(rid) == who for rid, t in self._jobs.items())

    def progress(self, rid: str) -> float | None:
        return self._progress.get(rid)

    def stage(self, rid: str) -> str | None:
        """What a render is doing: `checking` the words, then `drawing` the video."""
        return self._stage.get(rid)

    async def start(
        self, identity: Identity, cid: str, fmt: str = "mp4", quality: str | None = None
    ) -> dict[str, Any]:
        state = self._deps.state
        engine = engine_for(state)
        store = store_for(state)
        found, fit = self._may_start(identity, cid, fmt, quality, engine, store)
        folder = await self._write_all(identity, found, engine)
        row = store.add_render(
            identity.tenant_id, identity.user_id, cid,
            {"fps": templates.FPS, "seconds": found["slots"]["seconds"], "fit": fit["verdict"],
             "format": fmt, **({"quality": quality} if quality else {})},
        )  # fmt: skip
        self._progress[row["id"]] = 0.0
        self._owners[row["id"]] = self._who(identity)
        self._stage[row["id"]] = "checking"
        self._jobs[row["id"]] = asyncio.create_task(
            self._acting(
                identity,
                self._run(identity, found, folder, row["id"], engine, fmt, quality=quality),
            )
        )
        return row

    async def start_shapes(
        self,
        identity: Identity,
        cid: str,
        shapes: list[str],
        fmt: str = "mp4",
        quality: str | None = None,
    ) -> list[dict[str, Any]]:
        """One project as several videos, one for each shape (ADR-0096 MX7), made one after another
        as anything is. Each has its own check of the words, because a line that fits one shape can
        be too wide for another; one that fails does not stop the rest. Stopping stops them all."""
        state = self._deps.state
        engine = engine_for(state)
        store = store_for(state)
        unknown = [s for s in shapes if s not in templates.SHAPES]
        if unknown or not shapes:
            raise Refused("bad_shape", f"The shape must be one of: {', '.join(templates.SHAPES)}.")
        wanted = list(dict.fromkeys(shapes))
        found, fit = self._may_start(identity, cid, fmt, quality, engine, store)
        rows = [
            store.add_render(
                identity.tenant_id, identity.user_id, cid,
                {"fps": templates.FPS, "seconds": found["slots"]["seconds"], "shape": shape,
                 "fit": fit["verdict"], "format": fmt, **({"quality": quality} if quality else {})},
            )
            for shape in wanted
        ]  # fmt: skip
        for row in rows:
            self._progress[row["id"]] = 0.0
            self._owners[row["id"]] = self._who(identity)
            self._stage[row["id"]] = "waiting"
        task = asyncio.create_task(
            self._acting(identity, self._run_shapes(identity, found, rows, engine, fmt, quality))
        )
        for row in rows:
            self._jobs[row["id"]] = task
        return rows

    async def _run_shapes(
        self,
        identity: Identity,
        found: dict[str, Any],
        rows: list[dict[str, Any]],
        engine: Any,
        fmt: str,
        quality: str | None,
    ) -> None:
        store = store_for(self._deps.state)
        left = [row["id"] for row in rows]
        try:
            for row in rows:
                rid, shape = row["id"], row["settings"]["shape"]
                this = _in_shape(found, shape)
                folder = await self._write_all(identity, this, engine, shape)
                try:
                    self._stage[rid] = "checking"
                    await self._run(identity, this, folder, rid, engine, fmt, quality=quality)
                    left.remove(rid)
                finally:
                    await asyncio.to_thread(shutil.rmtree, folder, ignore_errors=True)
        except asyncio.CancelledError:
            if not getattr(engine, "closing", False):
                for rid in left:
                    # the one being drawn was marked by `_run`, and marking is first come
                    if store.get_status(rid) == "working":
                        store.finish_render(rid, "cancelled", error="The video was cancelled.")
            raise
        except Exception:
            log.exception("a set of Motion graphics renders failed")
            for rid in left:
                store.finish_render(rid, "failed", error="The video could not be made.")
        finally:
            for rid in left:
                self._progress.pop(rid, None)
                self._stage.pop(rid, None)

    def _may_start(
        self, identity: Identity, cid: str, fmt: str, quality: str | None, engine: Any, store: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """The project and how it fits here, or why a video cannot be started now."""
        if not engine.ready():
            raise Refused("not_ready", not_ready(engine))
        if self.busy(identity):
            raise Refused("busy", "A video is already being made. Wait for it to finish.")
        fit = engine.fit()
        if fit["verdict"] == "too_big":
            raise Refused("too_big", fit["reason"])
        found = store.get_composition(identity.tenant_id, identity.user_id, cid)
        template = templates.get(found["template"])
        formats = templates.formats_of(found["template"], found["slots"])
        if quality is not None and quality not in QUALITIES:
            raise Refused("bad_quality", f"The quality must be one of: {', '.join(QUALITIES)}.")
        if fmt not in formats:
            raise Refused(
                "bad_format",
                f"{template.title} can be made as {', '.join(formats)}, not {fmt}.",
            )
        return found, fit

    async def _acting(self, identity: Identity, work: Any) -> None:
        """Run a render as this person: the engine reads whose it is from the context."""
        with self._deps.acting_as(identity, PRODUCT_ID):
            await work

    def _write(
        self, identity: Identity, found: dict[str, Any], engine: Any, variant: str = ""
    ) -> Path:
        gsap = engine.gsap()
        if gsap is None:
            raise Refused("not_ready", "Motion graphics is not set up yet. Set it up first.")
        # a shape of a set has its own folder: the editor's still can write the project's meanwhile
        folder = projects.project_dir(
            root_for(self._deps.state), identity.tenant_id, identity.user_id, found["id"], variant
        )
        fonts = engine.fonts(templates.FONT_FILES)
        family = templates.FONTS[found["slots"]["font"]][1]
        if family not in fonts:
            raise Refused(
                "not_ready",
                "Motion graphics needs to be set up again: it has new fonts.",
            )
        projects.write_project(folder, found["template"], found["slots"], gsap, fonts)
        return folder

    async def _write_all(
        self, identity: Identity, found: dict[str, Any], engine: Any, variant: str = ""
    ) -> Path:
        folder = self._write(identity, found, engine, variant)
        await put_files_beside(self._deps, identity, found, folder, engine)
        return folder

    async def cancel(self, identity: Identity, rid: str) -> bool:
        store_for(self._deps.state).get_render(identity.tenant_id, identity.user_id, rid)  # owner
        task = self._jobs.get(rid)
        if task is None or task.done():
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return True

    async def resume_all(self) -> int:
        """Go on waiting for the renders the worker was drawing when this service stopped. One
        that never got to drawing (it was still checking the words) or whose composition is gone
        is failed in words. Returns how many were picked up."""
        state = self._deps.state
        engine, store = engine_for(state), store_for(state)
        if not getattr(engine, "resumable", False):
            return 0
        picked = 0
        for row in store.working_renders():
            who = Identity(row["tenant_id"], row["user_id"])
            rid = row["id"]
            try:
                found = store.get_composition(who.tenant_id, who.user_id, row["composition_id"])
                if row["check"] is None:
                    raise NotFound(rid)
                shape = row["settings"].get("shape")
                if shape:
                    found = _in_shape(found, shape)
                folder = await self._write_all(who, found, engine, shape or "")
            except (NotFound, Refused):
                store.finish_render(rid, "failed", error=STOPPED)
                continue
            self._progress[rid] = row.get("progress") or 0.0
            self._owners[rid] = self._who(who)
            self._stage[rid] = "drawing"
            fmt = row["settings"].get("format", "mp4")
            quality = row["settings"].get("quality")
            self._jobs[rid] = asyncio.create_task(
                self._acting(
                    who,
                    self._run(who, found, folder, rid, engine, fmt, resume=True, quality=quality),
                )
            )
            picked += 1
        return picked

    async def wait(self, rid: str) -> None:
        task = self._jobs.get(rid)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def stop_all(self) -> None:
        for task in self._jobs.values():
            task.cancel()
        await asyncio.gather(*self._jobs.values(), return_exceptions=True)

    # ---- one render ------------------------------------------------------------------------

    async def _run(
        self,
        identity: Identity,
        found: dict[str, Any],
        folder: Path,
        rid: str,
        engine: Any,
        fmt: str,
        resume: bool = False,
        quality: str | None = None,
    ) -> None:
        store = store_for(self._deps.state)
        # a worker's engine finds the drawing again by the render's id: a restart does not lose it
        again = {"job_key": rid, "resume": resume} if getattr(engine, "resumable", False) else {}
        out = folder / "renders" / f"{rid}.{fmt}"
        last = 0.0

        def on_progress(line: str) -> None:
            nonlocal last
            hits = PROGRESS.findall(line)
            if hits:
                value = min(int(hits[-1]), 100) / 100
                if value >= last + 0.01:
                    last = value
                    self._progress[rid] = value
                    store.set_progress(rid, value)

        try:
            if not resume:  # picked up again: the words were checked before the restart
                report = await check.run_check(engine, folder, found["template"], found["slots"])
                store.set_check(rid, report)
                if not report["ok"]:  # the page does not say what was typed: nothing is drawn
                    store.finish_render(rid, "failed", error=report["message"])
                    return
            self._stage[rid] = "drawing"
            args = ("--format", fmt, *(("--quality", quality) if quality else ()))
            result = await engine.render(folder, out, on_progress, args, **again)
            if not result.ok and result.reason == "failed":
                # the browser's own worker gave up (seen once under load, never when idle): one
                # more try; a limit, a refusal or a cancel is never tried again
                log.warning("a render failed, trying again: %s", getattr(result, "log_tail", ""))
                self._progress.pop(rid, None)
                last = 0.0
                result = await engine.render(folder, out, on_progress, args)
            if not result.ok:
                status = "cancelled" if result.reason == "cancelled" else "failed"
                store.finish_render(
                    rid, status, error=result.message, elapsed_s=result.seconds,
                    peak_mb=result.peak_rss_bytes // 2**20, blocked=result.blocked_count,
                )  # fmt: skip
                return
            video_id = await self._save(identity, found, out, fmt)
            store.finish_render(
                rid, "done", video_id=video_id, elapsed_s=result.seconds,
                peak_mb=result.peak_rss_bytes // 2**20, blocked=result.blocked_count,
            )  # fmt: skip
            await RouteUsage(self._deps.state, PRODUCT_ID).record(
                identity, EV_RENDER, 1, "videos", seconds=result.seconds, format=fmt
            )
        except asyncio.CancelledError:
            if not getattr(engine, "closing", False):  # not just this service stopping
                store.finish_render(rid, "cancelled", error="The video was cancelled.")
            raise
        except Exception:
            log.exception("a Motion graphics render failed")
            store.finish_render(rid, "failed", error="The video could not be saved.")
        finally:
            out.unlink(missing_ok=True)
            self._progress.pop(rid, None)
            self._stage.pop(rid, None)

    async def _save(self, identity: Identity, found: dict[str, Any], mp4: Path, fmt: str) -> str:
        """The finished file becomes a clip of the library, laid out as the video product's graph
        does."""
        deps = self._deps
        assert deps.storage is not None, "storage is required"
        slots = found["slots"]
        data = await asyncio.to_thread(mp4.read_bytes)
        try:
            width, height, poster = await poster_of(
                data, templates.poster_time(found["template"], slots)
            )
        except PosterError:  # that moment could not be read: the first frame will do
            width, height, poster = await poster_of(data)
        video_id = str(uuid.uuid4())
        seconds = int(slots["seconds"])
        prompt = templates.describe(found["template"], slots)
        store = video_store(deps.engine)
        await store.add(
            VideoRecord(
                id=video_id, tenant_id=identity.tenant_id, product_id=PRODUCT_ID,
                user_id=identity.user_id, thread_id=None, run_id=None, mode="composition",
                status="working", prompt=prompt, seconds=seconds, frames=seconds * templates.FPS,
                fps=templates.FPS, created_at=datetime.now(UTC),
            )
        )  # fmt: skip
        try:
            with deps.acting_as(identity, PRODUCT_ID):
                video_key, poster_key = f"{video_id}/video.{fmt}", f"{video_id}/poster.jpg"
                await deps.storage.put(video_key, data, MIME[fmt])
                await deps.storage.put(poster_key, poster, "image/jpeg")
            await store.finish(identity.tenant_id, video_id, width, height, video_key, poster_key)
        except Exception:
            await store.fail(identity.tenant_id, video_id, "The video could not be saved.")
            raise
        await add_to_search(deps.state, identity, "video", video_id, index_text(prompt))
        return video_id


async def index_composition(deps: RouteDeps, identity: Identity, found: dict[str, Any]) -> None:
    await add_to_search(
        deps.state,
        identity,
        "composition",
        found["id"],
        templates.describe(found["template"], found["slots"]),
    )


__all__ = [
    "PRODUCT_ID", "NotAvailable", "NotFound", "Refused", "RenderManager", "add_to_search",
    "engine_for", "index_composition", "manager_for", "root_for", "store_for",
]  # fmt: skip
