# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""What Creative Studio needs at run time: its store, and the plan being written. A person has one plan being written
at a time, and it can be stopped. The writing runs as a task that survives the request; every finished step is saved
as it is done, so stopping, a crash or closing the app loses only the step that was under way.

The product reaches the song through the `music.analyse` action (the voice product owns it) and the writer through
its text capability, so it imports neither from the API nor from another product."""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import Identity, RouteDeps, RunContext, search_text, set_context
from wasifyai_platform_sdk.context import reset_context

from wasifyai_creative.document import index_words
from wasifyai_creative.layout import lay_out
from wasifyai_creative.store import CreativeStore
from wasifyai_creative.writer import PlanWriter, WriterFailed, rewrite_part, write_plan

log = logging.getLogger(__name__)

PRODUCT_ID = "wasifyai-creative"
KIND = "creative_project"
MODEL_FAILED = "The model did not answer. Check the chat model and try again."


class NotAvailable(Exception):
    """This deployment has no Creative Studio (desktop first)."""


class Refused(Exception):
    """A request that cannot be done now, with the sentence the person is shown."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def store_for(state: Any) -> CreativeStore:
    existing = state.creative_store
    if existing is not None:
        return existing
    if not state.desktop_dir:
        raise NotAvailable("Creative Studio is on the desktop app for now.")
    state.creative_store = CreativeStore.in_folder(Path(state.desktop_dir) / "creative")
    return state.creative_store


def manager_for(deps: RouteDeps) -> "PlanJobs":
    if deps.state.creative_jobs is None:
        deps.state.creative_jobs = PlanJobs(deps)
    return deps.state.creative_jobs


def lyrics_of(row: dict[str, Any]) -> str:
    return " ".join(x["text"] for x in row["facts"].get("lines", []))


async def add_to_search(state: Any, identity: Identity, row: dict[str, Any]) -> None:
    """Make a project searchable by its words (ADR-0041): best effort, never fails the request."""
    index = state.creation_index
    if index is None:
        return
    try:
        words = index_words(row["title"], row["brief"], row["plan"], lyrics_of(row))
        await index.index(
            identity.tenant_id, PRODUCT_ID, identity.user_id, KIND, row["id"], search_text(*words)
        )
    except Exception:
        log.warning("the project could not be added to search", exc_info=True)


class PlanJobs:
    """One plan being written at a time for a person; the desktop has one person."""

    def __init__(self, deps: RouteDeps):
        self._deps = deps
        self._jobs: dict[str, tuple[str, asyncio.Task[None]]] = {}

    @staticmethod
    def _who(identity: Identity) -> str:
        return f"{identity.tenant_id}/{identity.user_id}"

    def active(self, identity: Identity) -> str | None:
        job = self._jobs.get(self._who(identity))
        return job[0] if job and not job[1].done() else None

    async def wait(self, identity: Identity, project_id: str) -> None:
        job = self._jobs.get(self._who(identity))
        if job and job[0] == project_id and not job[1].done():
            await asyncio.shield(job[1])

    def stop(self, identity: Identity, project_id: str) -> bool:
        job = self._jobs.get(self._who(identity))
        if job and job[0] == project_id and not job[1].done():
            job[1].cancel()
            return True
        return False

    async def stop_and_wait(self, identity: Identity, project_id: str) -> None:
        job = self._jobs.get(self._who(identity))
        if job and job[0] == project_id and not job[1].done():
            job[1].cancel()
            await asyncio.gather(job[1], return_exceptions=True)

    def _begin(self, identity: Identity, project_id: str, stage: str, work: Any) -> None:
        if self.active(identity) is not None:
            raise Refused("busy", "A plan is being written. Wait for it, or stop it first.")
        store_for(self._deps.state).begin(project_id, stage)

        async def run() -> None:
            token = set_context(RunContext(identity.tenant_id, PRODUCT_ID, identity.user_id))
            try:
                await work()
            finally:
                reset_context(token)

        self._jobs[self._who(identity)] = (project_id, asyncio.create_task(run()))

    def _writer(self, project_id: str) -> PlanWriter:
        store = store_for(self._deps.state)
        caps = self._deps.state.caps[PRODUCT_ID]

        async def ask(system: str, prompt: str, schema: dict[str, Any]) -> str:
            return await caps.text.complete("chat", system, prompt, schema)

        return PlanWriter(
            ask,
            store.checkpoints(project_id),
            lambda step, data: store.keep_checkpoint(project_id, step, data),
            lambda step, asked, said: store.add_log(project_id, step, asked, said),
        )

    async def _facts(self, identity: Identity, row: dict[str, Any]) -> dict[str, Any]:
        """What was found in the song, through the action the voice product owns."""
        executor = self._deps.state.actions
        if executor is None:
            raise WriterFailed("The song cannot be read here.")
        params: dict[str, Any] = {"track_id": row["brief"]["track_id"]}
        if row["brief"].get("lyrics") is not None:
            params["lyrics"] = row["brief"]["lyrics"]
        result = await executor.run_action("music.analyse", params, "window", actor=identity)
        if result.status != "ok":
            raise WriterFailed(result.text or "The beats of the song could not be found.")
        return result.output

    def start(self, identity: Identity, project_id: str, *, again: bool = False) -> None:
        """Write the plan. `again` starts afresh; otherwise it goes on from the finished steps."""
        store = store_for(self._deps.state)
        row = store.get(identity.tenant_id, identity.user_id, project_id)
        if again:
            store.clear_checkpoints(project_id)
        self._begin(identity, project_id, "Finding the beats", lambda: self._plan(identity, row))

    def rewrite(self, identity: Identity, project_id: str, beat: int) -> None:
        """Try another idea for one part of the plan; only its shots change."""
        store = store_for(self._deps.state)
        row = store.get(identity.tenant_id, identity.user_id, project_id)
        if not row["plan"]:
            raise Refused("no_plan", "There is no plan yet.")
        self._begin(
            identity, project_id, f"Writing part {beat + 1} again",
            lambda: self._rewrite(identity, row, beat),
        )  # fmt: skip

    async def _guarded(self, identity: Identity, row: dict[str, Any], work: Any) -> None:
        store = store_for(self._deps.state)
        item = row["id"]
        try:
            await work()
        except asyncio.CancelledError:
            if not getattr(self._deps.state, "closing", False):
                store.finish(item, "stopped", "Stopped. Go on, and it picks up where it stopped.")
            raise
        except WriterFailed as e:
            store.finish(item, "failed", str(e))
        except Exception:
            log.exception("a plan could not be written")
            store.finish(item, "failed", MODEL_FAILED)

    async def _plan(self, identity: Identity, row: dict[str, Any]) -> None:
        store = store_for(self._deps.state)
        item = row["id"]

        async def work() -> None:
            started = time.monotonic()
            facts = await self._facts(identity, row)
            store.set_facts(item, facts)
            brief = row["brief"]
            slots = lay_out(
                facts["beats"], facts["downbeats"], facts["seconds"],
                [s["start"] for s in facts["sections"]], brief.get("cut_speed", 0),
            )  # fmt: skip
            plan = await write_plan(
                self._writer(item),
                brief,
                slots,
                facts["lines"] if facts["lines_timed"] else [],
                lambda stage, share: store.set_progress(item, stage, share),
            )
            store.save_plan(item, plan, "The plan was written")
            store.clear_checkpoints(item)
            store.finish(item, "planned", None, round(time.monotonic() - started, 1))
            fresh = store.get(identity.tenant_id, identity.user_id, item)
            await add_to_search(self._deps.state, identity, fresh)

        await self._guarded(identity, row, work)

    async def _rewrite(self, identity: Identity, row: dict[str, Any], beat: int) -> None:
        store = store_for(self._deps.state)
        item = row["id"]

        async def work() -> None:
            key = f"rewrite-{beat}-{row['revision']}"
            writer = self._writer(item)
            plan = await rewrite_part(writer, row["brief"], row["plan"], beat, key)
            store.save_plan(item, plan, f"Part {beat + 1} was written again")
            store.clear_checkpoints(item)
            store.finish(item, "planned", None)
            fresh = store.get(identity.tenant_id, identity.user_id, item)
            await add_to_search(self._deps.state, identity, fresh)

        await self._guarded(identity, row, work)


async def delete_project(deps: RouteDeps, identity: Identity, project_id: str) -> bool:
    """Stops what is being written, removes the project and takes it out of search. The song stays."""
    await manager_for(deps).stop_and_wait(identity, project_id)
    gone = store_for(deps.state).delete(identity.tenant_id, identity.user_id, project_id)
    if gone:
        await deps.unindex(identity, PRODUCT_ID, project_id)
    return gone
