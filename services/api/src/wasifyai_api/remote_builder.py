"""Video Builder for the web, rendered by an engine worker (ADR-0087, P4).

The product asks its engine to check a composition's words, draw a still, render the video and
lint a page. Here each of those is an engine job: the composition travels as its template and
slots (the page is made on the worker, which has the library, the fonts and the sandboxed
browser) and the answers come back as numbers, a report, a picture or the video. The product
writes a stand-in folder (only `slots.json` matters) with the stand-in library and fonts this
engine hands it, so the product code is the desktop's."""

import asyncio
import json
import logging
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from openai import AsyncOpenAI
from wasifyai_platform_sdk import (
    EngineJob,
    EngineQueue,
    EngineUnavailable,
    RunError,
    builder_wire,
    require_context,
)
from wasifyai_platform_sdk.storage import object_key
from wasifyai_platform_sdk.usage import (
    LLM_INPUT_TOKENS,
    LLM_OUTPUT_TOKENS,
    UsageEvent,
    record_safely,
)

from wasifyai_api.engine_workers import WorkerDirectory

log = logging.getLogger("wasifyai_api.remote_builder")

CHAT_ALIAS = "chat"  # the gateway alias that fills a template from a description


@dataclass
class RenderResult:
    ok: bool
    reason: str | None = None  # refused | wall_time | stalled | memory | cancelled | failed
    message: str = ""
    seconds: float = 0.0
    peak_rss_bytes: int = 0
    blocked: list[str] = field(default_factory=list)
    blocked_count: int = 0
    output: Path | None = None
    log_tail: str = ""
    lines: list[str] = field(default_factory=list)


class _Failed(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class RemoteBuilderEngine:
    # a render can be picked up again after an API restart: its job has the render row's id
    resumable = True
    closing = False  # set when this service is stopping: the jobs go on, nobody is told to stop

    def __init__(
        self,
        queue: EngineQueue,
        storage: Any,
        directory: WorkerDirectory,
        *,
        gateway_url: str = "",
        gateway_key: str = "",
        usage: Any = None,
        timeout_s: float = 1800,
    ):
        self._queue = queue
        self._storage = storage  # the raw `Storage` (keys carry the tenant prefix)
        self._directory = directory
        self._gateway = (gateway_url, gateway_key)
        self._usage = usage
        self._timeout = timeout_s
        self._standin: Path | None = None

    # ---- what the product asks before it starts ---------------------------------------------

    def _component(self) -> dict[str, Any] | None:
        return self._directory.component(builder_wire.COMPONENT)

    def ready(self) -> bool:
        return self.problem() is None

    def problem(self) -> str | None:
        if not self._directory.workers:
            return "The video worker is not running. Try again in a moment."
        c = self._component()
        if c is None:
            return "No worker here can make these videos."
        if c.get("ready"):
            return None
        return str(c.get("problem") or "Video Builder is not set up on the worker.")

    def fit(self) -> dict[str, Any]:
        c = self._component() or {}
        return c.get("fit") or {"verdict": "fits", "reason": ""}  # type: ignore[no-any-return]

    def state(self) -> dict[str, Any]:
        c = self._component() or {}
        return c.get("state") or {}  # type: ignore[no-any-return]

    # the product copies these into the stand-in folder it writes; only `slots.json` is read back
    def _dir(self) -> Path:
        if self._standin is None:
            self._standin = Path(tempfile.mkdtemp(prefix="wasifyai-builder-standin-"))
        return self._standin

    def gsap(self) -> Path:
        path = self._dir() / "gsap.min.js"
        path.touch()
        return path

    def fonts(self, wanted: dict[str, str]) -> dict[str, Path]:
        out = {}
        for name in wanted:
            path = self._dir() / name
            path.touch()
            out[name] = path
        return out

    # ---- the work ---------------------------------------------------------------------------

    @staticmethod
    def _composition(folder: Path) -> tuple[str, dict[str, Any]]:
        raw = json.loads((folder / "slots.json").read_text())
        template = raw.pop("template")
        return template, raw

    async def _run(
        self, kind: str, params: dict[str, Any],
        on_progress: Callable[[float, str], None] | None = None,
        job_key: str | None = None, resume: bool = False,
    ) -> tuple[dict[str, bytes], dict[str, Any]]:  # fmt: skip
        ctx = require_context()
        job_id = job_key or str(uuid4())
        prefix = object_key(ctx.tenant_id, ctx.product_id, ctx.user_id, "engine", job_id)
        outputs: list[str] = []
        try:
            if resume:  # sent before a restart: only its outcome is awaited
                if await self._queue.status(job_id) == "lost":
                    raise _Failed("lost", "It was stopped before it finished. Make it again.")
            else:
                await self._queue.submit(
                    EngineJob(
                        id=job_id,
                        kind=kind,
                        tenant_id=ctx.tenant_id,
                        product_id=ctx.product_id,
                        user_id=ctx.user_id,
                        prefix=prefix,
                        params=params,
                    )  # fmt: skip
                )

            async def told(fraction: float, label: str) -> None:
                if on_progress is not None:
                    on_progress(fraction, label)

            try:
                outcome = await self._queue.wait(job_id, self._timeout, told)
            except asyncio.CancelledError:
                if not self.closing:  # Stop was pressed, not a restart
                    await asyncio.shield(self._queue.cancel(job_id))
                raise
            except EngineUnavailable:
                await asyncio.shield(self._queue.cancel(job_id))
                raise _Failed("wall_time", "The video worker took too long. Try again.") from None
            if not outcome.ok:
                err = outcome.error
                raise _Failed(
                    "cancelled" if err and err.code == "cancelled" else "failed",
                    err.message if err else "The video worker could not do that.",
                )
            outputs = list(outcome.outputs.values())
            files = {name: await self._storage.get(key) for name, key in outcome.outputs.items()}
            return files, outcome.meta
        finally:
            for key in outputs:
                try:
                    await self._storage.delete(key)
                except Exception:
                    log.warning("could not remove %s", key)

    async def inspect(self, project: Path, spec: dict[str, Any]) -> dict[str, Any]:
        template, slots = self._composition(project)
        try:
            _, meta = await self._run(
                builder_wire.INSPECT, {"template": template, "slots": slots, "spec": spec}
            )
        except _Failed as e:
            return {"ok": False, "message": e.message, "items": []}
        return meta["report"]  # type: ignore[no-any-return]

    async def lint(self, project: Path) -> list[dict[str, Any]]:
        html = (project / "index.html").read_text()
        _, meta = await self._run(builder_wire.LINT, {"html": html})
        return meta["findings"]  # type: ignore[no-any-return]

    async def snapshot(self, project: Path, folder: Path, at: float) -> RenderResult:
        template, slots = self._composition(project)
        try:
            files, meta = await self._run(
                builder_wire.SNAPSHOT, {"template": template, "slots": slots, "at": at}
            )
        except _Failed as e:
            return RenderResult(False, e.code, e.message)
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread((folder / "still.png").write_bytes, files["still"])
        return RenderResult(True, seconds=float(meta.get("seconds", 0)))

    async def render(
        self,
        project: Path,
        output: Path,
        on_progress: Callable[[str], None] | None = None,
        extra_args: tuple[str, ...] = (),
        *,
        job_key: str | None = None,
        resume: bool = False,
    ) -> RenderResult:
        template, slots = self._composition(project)
        fmt = extra_args[extra_args.index("--format") + 1] if "--format" in extra_args else "mp4"

        def told(fraction: float, label: str) -> None:
            if on_progress is not None:
                on_progress(f"{round(fraction * 100)}%")

        try:
            files, meta = await self._run(
                builder_wire.RENDER,
                {"template": template, "slots": slots, "format": fmt},
                told,
                job_key,
                resume,
            )
        except _Failed as e:
            return RenderResult(False, e.code, e.message)
        if not meta.get("ok") or "video" not in files:
            return RenderResult(
                False, meta.get("reason") or "failed", str(meta.get("message") or "No video."),
                float(meta.get("seconds", 0)), int(meta.get("peak_rss_bytes", 0)),
                blocked_count=int(meta.get("blocked_count", 0)),
            )  # fmt: skip
        await asyncio.to_thread(output.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(output.write_bytes, files["video"])
        return RenderResult(
            True, seconds=float(meta.get("seconds", 0)),
            peak_rss_bytes=int(meta.get("peak_rss_bytes", 0)),
            blocked_count=int(meta.get("blocked_count", 0)), output=output,
        )  # fmt: skip

    # ---- the chat model fills a template from a description -------------------------------------

    async def complete(
        self, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 800
    ) -> str:
        """Ask the chat model once for an answer that follows `schema` (`RunError` with words)."""
        ctx = require_context()
        url, key = self._gateway
        if not url:
            raise RunError("no_language_model", "There is no language model to ask.")
        try:
            client = AsyncOpenAI(
                base_url=url.rstrip("/") + "/v1", api_key=key or "none", max_retries=0
            )
            reply = await asyncio.wait_for(
                client.chat.completions.create(
                    model=CHAT_ALIAS,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=max_tokens,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": "reply", "schema": schema, "strict": True},
                    },
                ),
                timeout=180,
            )  # fmt: skip
        except TimeoutError:
            raise RunError("language_timeout", "The model took too long. Try again.") from None
        except Exception:
            raise RunError(
                "language_failed", "The model did not answer. Try again, or choose another."
            ) from None
        if reply.usage and self._usage is not None:
            meta = {"capability": "video_builder.draft", "alias": CHAT_ALIAS}
            for name, count in (
                (LLM_INPUT_TOKENS, reply.usage.prompt_tokens),
                (LLM_OUTPUT_TOKENS, reply.usage.completion_tokens),
            ):
                if count:
                    await record_safely(
                        self._usage, UsageEvent.for_context(ctx, name, count, "tokens", **meta)
                    )
        return reply.choices[0].message.content or ""
