"""The Motion graphics component's routes for the window (ADR-0077, stage V1a): is it set up, what
would setting it up fetch, set it up (after the person saw the size), remove it. The render itself
comes in V1c; the sandbox it will run in is `video_builder_sandbox.py`."""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from openai import AsyncOpenAI
from pydantic import BaseModel
from wasifyai_platform_sdk import Identity, RunError
from wasifyai_platform_sdk.context import require_context
from wasifyai_platform_sdk.usage import (
    LLM_INPUT_TOKENS,
    LLM_OUTPUT_TOKENS,
    UsageEvent,
    record_safely,
)

from wasifyai_api import video_builder_runtime as vb
from wasifyai_api import video_builder_sandbox as sandbox
from wasifyai_api.audio_runtime import InstallError
from wasifyai_api.desktop_fit import GB, assess_fit, need_declared, read_machine
from wasifyai_api.desktop_language import thinking_fields
from wasifyai_api.identity import get_identity
from wasifyai_api.services import services_of

# what a render holds, measured on the owner's Mac (docs/spikes/video-builder-v1.md): 0.6 GB for a
# plain composition by `ps`, 1.8 to 3 GB by V0's sampler; the fit check uses the larger figure
RENDER_NEED_GB = 3.0


class VideoBuilderService:
    """What the engine holds for Motion graphics: the installer, and what is installed."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.installer = vb.VideoBuilderInstaller(data_dir)
        self.language: Any = None  # the chosen chat model (set by the app); `complete` asks it
        self.usage: Any = None  # records the tokens it used
        self._kit: dict[str, bytes] | None = None

    async def live_kit(self) -> dict[str, bytes]:
        """What the player's page loads besides itself (`live.py`), read once."""
        if self._kit is None:
            from wasifyai_video.builder.live import RUNTIME, kit_files
            from wasifyai_video.builder.templates import FONT_FILES

            found, gsap = self.install(), self.gsap()
            if found is None or gsap is None:
                raise RuntimeError("Motion graphics needs to be set up again.")
            runtime = found.app / "node_modules" / "hyperframes" / "dist" / RUNTIME
            self._kit = await asyncio.to_thread(kit_files, gsap, runtime, self.fonts(FONT_FILES))
        return self._kit

    def install(self) -> vb.VideoBuilderInstall | None:
        return vb.find_install(self.data_dir, self.installer.pins)

    def media_problem(self) -> str | None:
        """What is missing outside the component (FFmpeg and ffprobe), in words, or None."""
        found = self.install()
        return None if len(vb.find_media_tools(found)) == len(vb.MEDIA_TOOLS) else vb.MEDIA_HINT

    def problem(self) -> str | None:
        """Why a video cannot be drawn now, in words, or None when it can."""
        if not self.installer.supported:
            return "Motion graphics is not available on this kind of computer yet."
        if self.install() is None:
            return "Motion graphics is not set up yet. Set it up first."
        return self.media_problem()

    def state(self) -> dict[str, Any]:
        found = self.install()
        problem = self.media_problem()
        return {
            "installed": found is not None,
            "tools": {"ready": problem is None, "message": problem or ""},
            "source": found.source if found is not None else None,
            "plan": self.installer.plan(),
            "progress": self.installer.progress.public(),
            # said in words on the setup card: what a render is and is not allowed to do
            "sandbox": {
                "network": "A video can reach nothing outside its own folder.",
                "telemetry": "Nothing is sent anywhere while it runs.",
            },
        }

    # ---- what the Motion graphics product calls (it imports nothing from this package) ----------

    def ready(self) -> bool:
        return self.problem() is None

    def fit(self) -> dict[str, Any]:
        """Whether a render fits in the memory this computer has now (ADR-0063)."""
        return assess_fit(need_declared(RENDER_NEED_GB), read_machine()).public()

    def limits(self) -> sandbox.RenderLimits:
        machine = read_machine()
        total = machine.total_bytes or 16 * GB
        # a render holds 2 to 3 GB: allow half the memory, between 3 GB and 8 GB
        return sandbox.RenderLimits(rss_bytes=int(max(3 * GB, min(8 * GB, total // 2))))

    def gsap(self) -> Path | None:
        found = self.install()
        path = found.app / "node_modules" / "gsap" / "dist" / "gsap.min.js" if found else None
        return path if path is not None and path.is_file() else None

    def fonts(self, wanted: dict[str, str]) -> dict[str, Path]:
        """The open fonts the templates use: `wanted` maps the name a font is copied under to its
        place in the component's npm packages; the ones that are there are returned."""
        found = self.install()
        if found is None:
            return {}
        out = {}
        for name, rel in wanted.items():
            path = found.app / "node_modules" / rel
            if path.is_file():
                out[name] = path
        return out

    async def complete(
        self, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 800
    ) -> str:
        """Ask the chosen chat model once for an answer that follows `schema` (the product turns a
        description into the fields of a template with it). Thinking is off: the answer is short and
        the person is waiting. Raises `RunError` with words for the person."""
        language = self.language
        if language is None:
            raise RunError("no_language_model", "There is no language model to ask.")
        ctx = require_context()
        in_tokens = out_tokens = 0
        label = ""
        try:
            async with language.session() as route:
                label = language.selected.name if language.selected else ""
                client = AsyncOpenAI(base_url=route.base_url, api_key="none", max_retries=0)
                reply = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=route.model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0,
                        max_tokens=max_tokens,
                        response_format={
                            "type": "json_schema",
                            "json_schema": {"name": "reply", "schema": schema, "strict": True},
                        },
                        extra_body=thinking_fields(language.selected, route.external, False),
                    ),
                    timeout=180,
                )
        except RunError:
            raise
        except TimeoutError:
            raise RunError("language_timeout", "The model took too long. Try again.") from None
        except Exception:
            raise RunError(
                "language_failed", "The model did not answer. Try again, or choose another."
            ) from None
        if reply.usage:
            in_tokens, out_tokens = reply.usage.prompt_tokens, reply.usage.completion_tokens
        meta: dict[str, Any] = {"capability": "video_builder.draft", "alias": label}
        for name, count in ((LLM_INPUT_TOKENS, in_tokens), (LLM_OUTPUT_TOKENS, out_tokens)):
            if count:
                event = UsageEvent.for_context(ctx, name, count, "tokens", **meta)
                await record_safely(self.usage, event)
        return reply.choices[0].message.content or ""

    async def inspect(self, project: Path, spec: dict[str, Any]) -> dict[str, Any]:
        """What is drawn at the moments in `spec`, seen by the sandboxed browser (the product
        compares it with the words that were typed)."""
        found = self.install()
        if found is None:
            return {"ok": False, "message": "Motion graphics is not set up yet.", "items": []}
        result, report = await sandbox.run_check(found, project, spec)
        if report is None:
            why = result.message or "The check could not be run."
            return {"ok": False, "message": why, "items": [], "log": result.log_tail[-400:]}
        return {
            "ok": True,
            "message": "",
            "items": report["items"],
            "fonts": report.get("fonts", []),
        }

    def lint(self, project: Path) -> list[dict[str, Any]]:
        return [
            {"file": f.file, "line": f.line, "code": f.code, "message": f.message}
            for f in sandbox.lint_project(project)
        ]

    async def render(
        self,
        project: Path,
        output: Path,
        on_progress: Callable[[str], None] | None = None,
        extra_args: tuple[str, ...] = (),
    ) -> sandbox.RenderResult:
        found = self.install()
        if found is None:
            return sandbox.RenderResult(False, "unavailable", "Motion graphics is not set up yet.")
        return await sandbox.run_render(
            found, project, output, limits=self.limits(), on_progress=on_progress,
            extra_args=extra_args,
        )  # fmt: skip

    async def snapshot(self, project: Path, folder: Path, at: float) -> sandbox.RenderResult:
        found = self.install()
        if found is None:
            return sandbox.RenderResult(False, "unavailable", "Motion graphics is not set up yet.")
        return await sandbox.run_snapshot(found, project, folder, at, limits=None)

    def remove(self) -> int:
        if self.installer.running:
            raise InstallError("Motion graphics is being set up. Wait for it to finish.")
        return vb.uninstall(self.data_dir)


router = APIRouter(prefix="/desktop/video-builder", tags=["desktop"])


def _service(request: Request) -> VideoBuilderService:
    service: VideoBuilderService | None = services_of(request).video_builder
    if service is None:
        raise HTTPException(404, "not available in this deployment")
    return service


class ConfirmInstall(BaseModel):
    """What the person was shown and agreed to: the size of the download."""

    confirm_bytes: int


@router.get("")
async def video_builder_state(
    request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    return _service(request).state()


@router.post("/install", status_code=202)
async def install_video_builder(
    body: ConfirmInstall, request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    service = _service(request)
    try:
        service.installer.start(body.confirm_bytes)
    except InstallError as e:
        raise HTTPException(409, str(e)) from None
    return service.state()


@router.post("/uninstall")
async def uninstall_video_builder(
    request: Request, _: Identity = Depends(get_identity)
) -> dict[str, Any]:
    service = _service(request)
    try:
        freed = service.remove()
    except InstallError as e:
        raise HTTPException(409, str(e)) from None
    return {"freed_bytes": freed, **service.state()}
