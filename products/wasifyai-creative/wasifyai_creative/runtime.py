# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""What Creative Studio needs at run time: its store, and the plan being written. A person has one plan being written
at a time, and it can be stopped. The writing runs as a task that survives the request; every finished step is saved
as it is done, so stopping, a crash or closing the app loses only the step that was under way.

The product reaches the song through the `music.analyse` action (the voice product owns it) and the writer through
its text capability, so it imports neither from the API nor from another product."""

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from wasifyai_platform_sdk import Identity, RouteDeps, RunContext, search_text, set_context
from wasifyai_platform_sdk.context import reset_context

from wasifyai_creative import story as stories
from wasifyai_creative.cut import captions_of
from wasifyai_creative.document import index_words
from wasifyai_creative.layout import lay_out, lay_out_story
from wasifyai_creative.shots import Refused, ShotJobs
from wasifyai_creative.store import CreativeStore
from wasifyai_creative.writer import PlanWriter, WriterFailed, rewrite_part, write_plan

log = logging.getLogger(__name__)

PRODUCT_ID = "wasifyai-creative"
KIND = "creative_project"
NARRATION = (
    "say-",
    "joined-",
)  # spoken parts of a story, kept across plans: they are saved recordings
MODEL_FAILED = "The model did not answer. Check the chat model and try again."


class NotAvailable(Exception):
    """This deployment has no Creative Studio (desktop first)."""


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
        found = store_for(state).cut_of(row["id"])
        lyrics = f"{lyrics_of(row)} {captions_of(found['cut'] if found else None)}".strip()
        words = index_words(row["title"], row["brief"], row["plan"], lyrics)
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
        self.shots = ShotJobs(deps, lambda: store_for(deps.state), self.active)

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
        if self.shots.active(identity) is not None:
            raise Refused("busy", "Pictures are being made. Wait for them, or stop them first.")
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

    async def _narrate(self, identity: Identity, row: dict[str, Any]) -> dict[str, Any]:
        """A story read aloud: each part spoken in its voice (kept as soon as it is made, so a stop loses one part at
        most), then joined into one recording in Your music. Returns what a song's analysis would, with exact times."""
        executor = self._deps.state.actions
        if executor is None:
            raise WriterFailed("The story cannot be read aloud here.")
        store = store_for(self._deps.state)
        item, brief = row["id"], row["brief"]
        voices = {p["name"]: p.get("voice") for p in brief.get("cast", [])}
        parts = stories.parts_of(str(brief.get("story") or ""), brief.get("cast", []))
        if not parts:
            raise WriterFailed("The story has nothing to read.")
        saved = store.checkpoints(item)
        spoken: list[dict[str, Any]] = []
        for n, part in enumerate(parts):
            voice = (voices.get(part["who"]) if part["who"] else None) or brief.get("narrator")
            key = "say-" + hashlib.sha256(f"{part['text']}|{voice or ''}".encode()).hexdigest()[:16]
            if key not in saved:
                store.set_progress(
                    item,
                    f"Reading the story aloud, part {n + 1} of {len(parts)}",
                    0.02 + 0.5 * n / len(parts),
                )
                params = {"text": part["text"], **({"saved_voice": voice} if voice else {})}
                done = await executor.run_action(
                    "speech.speak", params, "window", actor=identity, person_approved=True
                )
                if done.status != "ok":
                    raise WriterFailed(done.text or "The story could not be read aloud.")
                saved[key] = {
                    "speech_id": done.output["speech_id"],
                    "seconds": done.output["seconds"],
                }
                store.keep_checkpoint(item, key, saved[key])
                store.add_media(item, "speech", saved[key]["speech_id"], None, made=True)
            spoken.append({"speech_id": saved[key]["speech_id"], "pause": part["pause"]})
        joined = "joined-" + hashlib.sha256(repr(spoken).encode()).hexdigest()[:16]
        if joined not in saved:
            store.set_progress(item, "Joining the narration", 0.53)
            done = await executor.run_action(
                "speech.join",
                {"parts": spoken, "title": row["title"][:120], "text": str(brief.get("story") or "")},
                "window", actor=identity, person_approved=True,
            )  # fmt: skip
            if done.status != "ok":
                if done.code == "not_found":  # a part was deleted: the next try speaks again
                    store.drop_checkpoints(item, *NARRATION)
                raise WriterFailed(done.text or "The narration could not be joined.")
            saved[joined] = done.output
            store.keep_checkpoint(item, joined, done.output)
            store.add_media(item, "track", done.output["track_id"], None, made=True)
        made = saved[joined]
        fresh = store.get(identity.tenant_id, identity.user_id, item)
        store.set_brief(item, fresh["title"], {**fresh["brief"], "track_id": made["track_id"]})
        return {
            "track_id": made["track_id"],
            "title": made["title"],
            **stories.facts_of(parts, made["times"], made["seconds"]),
        }

    def start(self, identity: Identity, project_id: str, *, again: bool = False) -> None:
        """Write the plan. `again` starts afresh; otherwise it goes on from the finished steps."""
        store = store_for(self._deps.state)
        row = store.get(identity.tenant_id, identity.user_id, project_id)
        if again:
            store.clear_checkpoints(project_id, NARRATION)
        stage = "Reading the story" if row["brief"].get("skill") == "story" else "Finding the beats"
        self._begin(identity, project_id, stage, lambda: self._plan(identity, row))

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
            story = row["brief"].get("skill") == "story"
            facts = await (self._narrate(identity, row) if story else self._facts(identity, row))
            store.set_facts(item, facts)
            brief = store.get(identity.tenant_id, identity.user_id, item)["brief"]
            slots = (
                lay_out_story(facts["beats"], facts["seconds"], brief.get("cut_speed", 0))
                if story
                else lay_out(
                    facts["beats"], facts["downbeats"], facts["seconds"],
                    [s["start"] for s in facts["sections"]], brief.get("cut_speed", 0),
                )
            )  # fmt: skip
            share = (0.55, 0.45) if story else (0.0, 1.0)
            plan = await write_plan(
                self._writer(item),
                brief,
                slots,
                facts["lines"] if facts["lines_timed"] else [],
                lambda stage, part: store.set_progress(item, stage, share[0] + share[1] * part),
            )
            store.save_plan(item, plan, "The plan was written")
            store.clear_checkpoints(item, NARRATION)
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
            store.clear_checkpoints(item, NARRATION)
            store.finish(item, "planned", None)
            fresh = store.get(identity.tenant_id, identity.user_id, item)
            await add_to_search(self._deps.state, identity, fresh)

        await self._guarded(identity, row, work)


async def delete_project(
    deps: RouteDeps, identity: Identity, project_id: str, *, with_media: bool = False
) -> bool:
    """Stops what is being made, removes the project and takes it out of search. The song stays, and so does
    what was made for it unless `with_media` says the person asked for that to go too."""
    jobs = manager_for(deps)
    await jobs.stop_and_wait(identity, project_id)
    await jobs.shots.stop_and_wait(identity, project_id)
    store = store_for(deps.state)
    media = store.media_of(project_id)
    preview = store.preview_of(project_id)
    gone = store.delete(identity.tenant_id, identity.user_id, project_id)
    if not gone:
        return False
    await deps.unindex(identity, PRODUCT_ID, project_id)
    if preview and deps.storage is not None:
        owner = (identity.tenant_id, PRODUCT_ID, identity.user_id)
        await deps.storage.delete_for(owner, preview["rel"])
    executor = deps.state.actions
    if with_media and executor is not None:
        ctx = SimpleNamespace(deps=deps, actor=identity, executor=executor)
        for m in media:
            kind = executor.library.get(m["kind"])
            if m["made"] and kind is not None:
                await kind.delete(ctx, m["item_id"])
    return True
