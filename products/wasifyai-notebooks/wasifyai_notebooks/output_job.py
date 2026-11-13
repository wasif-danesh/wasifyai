# SPDX-License-Identifier: Apache-2.0
"""Making a Studio output (ADR-0065 decision 11), apart from the conversation that asked for it.

`make_output` reads the ticked sources, asks the chat model for the content, builds the file and
saves the result on the output's row. A run of the notebooks graph calls it (the desktop, and a
guide or an infographic anywhere); on the web the engine's program only queues an output and a
worker calls it (`OutputWorker`), so a long output is not held by the engine's program and does
not stop with it.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from wasifyai_platform_sdk import Capabilities, RunContext, RunError, reset_context, set_context

from wasifyai_notebooks.components import Unavailable
from wasifyai_notebooks.files import artifact_key
from wasifyai_notebooks.grounding import Tier
from wasifyai_notebooks.runtime import Runtime
from wasifyai_notebooks.store import NotebookStore
from wasifyai_notebooks.studio.context import budget_chars, gather, grounding
from wasifyai_notebooks.studio.formats import FORMATS, BadReply, build, prompt_for, slug

log = logging.getLogger(__name__)

PRODUCT_ID = "wasifyai-notebooks"
POLL_S = 1.0

Progress = Callable[[str, str], None]  # (step, what a person reads)
Painter = Callable[
    [Any, Progress, Callable[[str], Awaitable[None]]], Awaitable[dict[str, Any] | None]
]


@dataclass(frozen=True)
class OutputRequest:
    """Everything a worker needs to make an output: it is kept on the output's row as JSON."""

    format: str
    prompt: str
    document_ids: list[str]
    context: int  # the chat model's window, in tokens
    tier: Tier  # which prompt the model gets

    def to_json(self) -> dict[str, Any]:
        return {
            "format": self.format, "prompt": self.prompt, "document_ids": self.document_ids,
            "context": self.context, "tier": self.tier,
        }  # fmt: skip

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "OutputRequest":
        return cls(
            format=str(raw["format"]),
            prompt=str(raw.get("prompt", "")),
            document_ids=list(raw.get("document_ids") or []),
            context=int(raw["context"]),
            tier=raw["tier"],
        )


async def make_output(
    rt: Runtime,
    caps: Capabilities,
    *,
    tenant: str,
    user: str,
    nid: str,
    aid: str,
    request: OutputRequest,
    progress: Progress,
    paint: Painter | None = None,
) -> dict[str, Any]:
    """Make one output and save it on its row. Returns the run's result (`status`, `format`,
    `artifact_id`, `title`, or a refusal). An output that cannot be made is marked failed with a
    sentence, and a `RunError` carries the same to a run."""
    t, u = tenant, user
    fmt = FORMATS[request.format]
    prompt = request.prompt

    async def fail(message: str, error: RunError | None = None) -> None:
        if aid:
            await asyncio.to_thread(rt.store.fail_artifact, t, u, nid, aid, message)
        if error is not None:
            raise error

    try:
        progress("read", "Reading your sources")
        try:
            embedder = rt.components.embedder()
        except Unavailable:
            embedder = None

        def collect() -> list[Any]:
            def embed(text: str) -> list[float]:
                assert embedder is not None
                return rt.query_vector(embedder, t, u, text, "studio")

            with rt.store.connect() as db:
                return gather(
                    db, nid, request.document_ids, budget=budget_chars(request.context),
                    query=prompt or None, embed=embed if embedder else None,
                    weight=embedder.spec.semantic_weight if embedder else 0.65,
                )  # fmt: skip

        sources = await asyncio.to_thread(collect)
        if not sources:
            await fail("The ticked sources have no text to work from.")
            return {
                "status": "refused",
                "refusal": {"code": "no_text", "message": "The ticked sources have no text."},
            }
        system = prompt_for(fmt, request.tier, prompt)
        material = grounding(sources)
        progress("write", f"Writing the {fmt.label.lower()}")
        built = None
        problem = ""
        for attempt in range(2):
            user_text = material
            if problem:
                user_text += (
                    f"\n\nYour previous reply could not be used: {problem}. "
                    "Write it again, following the format exactly."
                )
            try:
                reply = await caps.text.complete("chat", system, user_text, fmt.schema)
            except RunError as e:
                await fail(e.message, e)
                raise
            except Exception:
                log.exception("the language model failed")
                await fail(
                    "The language model did not answer.",
                    RunError(
                        "language_failed",
                        "The language model did not answer. "
                        "Check it in the Model hub and try again.",
                        retryable=True,
                    ),
                )
                raise
            try:
                built = await asyncio.to_thread(build, fmt, reply)
                break
            except BadReply as e:
                problem = str(e)
                log.info("studio reply refused (attempt %d): %s", attempt + 1, problem)
        if built is None:
            await fail(
                f"The model's reply could not be used ({problem}). Try again, or choose a "
                "larger model."
            )
            return {"status": "done", "format": fmt.key, "artifact_id": aid, "title": ""}

        if fmt.key == "guide":
            key = await asyncio.to_thread(rt.store.sources_key, t, u, nid)
            await asyncio.to_thread(rt.store.save_guide, t, u, nid, built.data or {}, key)
            return {"status": "done", "format": "guide", "title": ""}

        if fmt.key == "infographic":
            if paint is None:
                await fail("Making pictures is not available here.")
                return {"status": "done", "format": fmt.key, "artifact_id": aid, "title": ""}
            painted = await paint(built, progress, fail)
            if painted is None:
                return {"status": "done", "format": fmt.key, "artifact_id": aid, "title": ""}
            built.data = {**(built.data or {}), **painted}

        file_name = file_mime = None
        if built.file is not None and built.file_ext:
            file_name = f"{slug(built.title, fmt.key)}.{built.file_ext}"
            file_mime = built.file_mime
            await asyncio.to_thread(
                rt.files_for(t, u).put_bytes,
                artifact_key(nid, aid, file_name),
                built.file,
                file_mime,
            )
        kept = await asyncio.to_thread(
            rt.store.finish_artifact, t, u, nid, aid, title=built.title, body=built.markdown,
            data=built.data, file_name=file_name, file_mime=file_mime,
        )  # fmt: skip
        if not kept and file_name:  # stopped or deleted while it was being made
            await asyncio.to_thread(rt.files_for(t, u).delete_prefix, artifact_key(nid, aid))
        await caps.record_usage("notebooks.artifact", 1, "outputs", format=fmt.key)
        return {"status": "done", "format": fmt.key, "artifact_id": aid, "title": built.title}
    except RunError:
        raise
    except Exception:
        log.exception("making an output failed")
        await fail("Something went wrong making this.")
        raise RunError("run_failed", "Something went wrong making this.", retryable=True) from None


class OutputWorker:
    """The background loop of a worker: takes the next queued output and makes it."""

    def __init__(self, rt: Runtime, caps: Capabilities):
        self._rt = rt
        self._caps = caps
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()

    @property
    def store(self) -> NotebookStore:
        return self._rt.store

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    def wake(self) -> None:
        self._wake.set()

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def drain(self, timeout: float = 60) -> None:  # noqa: ASYNC109
        """Wait until nothing is queued or being made (tests, and a clean shutdown)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not await asyncio.to_thread(self._waiting):
                return
            await asyncio.sleep(0.02)
        raise TimeoutError("outputs were still being made")

    def _waiting(self) -> bool:
        with self.store.connect() as db:
            return (
                db.execute(
                    "SELECT 1 FROM artifacts WHERE status = 'processing' AND request IS NOT NULL "
                    "LIMIT 1"
                ).fetchone()
                is not None
            )

    async def run_one(self, job: dict[str, Any]) -> None:
        """Make a claimed output, for the person it belongs to."""
        ctx = RunContext(job["tenant"], PRODUCT_ID, job["user"], run_id=job["id"])
        token = set_context(ctx)
        try:

            def progress(step: str, label: str) -> None:
                log.debug("output %s: %s", job["id"], label)

            await make_output(
                self._rt, self._caps, tenant=job["tenant"], user=job["user"],
                nid=job["notebook_id"], aid=job["id"],
                request=OutputRequest.from_json(job["request"]), progress=progress,
            )  # fmt: skip
        except RunError:
            pass  # the output's row already says what went wrong
        except Exception:
            log.exception("an output failed")
            await asyncio.to_thread(
                self._rt.store.fail_artifact, job["tenant"], job["user"], job["notebook_id"],
                job["id"], "Something went wrong making this.",
            )  # fmt: skip
        finally:
            reset_context(token)

    async def _loop(self) -> None:
        while True:
            try:
                job = await asyncio.to_thread(self.store.claim_output)
                if job is None:
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), POLL_S)
                    except TimeoutError:
                        pass
                    continue
                await self.run_one(job)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("output loop error")
                await asyncio.sleep(1)
