"""ComfyUI client: submit an API-format workflow, follow progress over the WebSocket, download
outputs. Protocol: POST /prompt, WS /ws?clientId=..., GET /history/{id}, GET /view, POST /free."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import websockets

log = logging.getLogger(__name__)

# ComfyUI history keys per output kind
_OUTPUT_KEYS = {"image": ("images",), "audio": ("audio",), "video": ("videos", "gifs", "images")}
_VIDEO_SUFFIXES = (".mp4", ".webm", ".mov", ".mkv")  # SaveVideo lists its file under "images"

ProgressFn = Callable[[float], Awaitable[None]]


class ComfyError(Exception):
    """A failure of the job itself (bad workflow, execution error), not of the infrastructure.
    `message` is safe to show users."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ComfyFile:
    filename: str
    subfolder: str
    type: str  # output | temp | input


class ComfyClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient | None = None):
        self._base = base_url.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=60)

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def _ws_url(self) -> str:
        return self._base.replace("https://", "wss://").replace("http://", "ws://")

    async def run(
        self, graph: dict[str, Any], client_id: str, on_progress: ProgressFn, timeout_s: float
    ) -> dict[str, Any]:
        """Execute `graph` and return the history outputs: {node_id: {images|audio|...: [...]}}."""
        # Connect first so no message is missed between submitting and subscribing.
        async with websockets.connect(
            f"{self._ws_url}/ws?clientId={client_id}", max_size=None
        ) as ws:
            prompt_id = await self._submit(graph, client_id)
            try:
                async with asyncio.timeout(timeout_s):
                    await self._follow(ws, prompt_id, on_progress)
            except TimeoutError:
                await self.interrupt()
                raise
        return await self._outputs(prompt_id)

    async def _submit(self, graph: dict[str, Any], client_id: str) -> str:
        r = await self._http.post(
            f"{self._base}/prompt", json={"prompt": graph, "client_id": client_id}
        )
        if r.status_code == 400:
            raise ComfyError("invalid_workflow", _validation_message(r))
        r.raise_for_status()
        return r.json()["prompt_id"]

    async def _follow(self, ws: Any, prompt_id: str, on_progress: ProgressFn) -> None:
        async for raw in ws:
            if isinstance(raw, bytes):  # preview frames
                continue
            msg = json.loads(raw)
            data = msg.get("data", {})
            if data.get("prompt_id") not in (None, prompt_id):
                continue  # another client's prompt
            match msg.get("type"):
                case "progress" if data.get("max"):
                    await on_progress(min(data["value"] / data["max"], 1.0))
                case "executing" if data.get("node") is None and data.get("prompt_id") == prompt_id:
                    return
                case "execution_error":
                    log.error("comfyui execution error: %s", data.get("exception_message"))
                    raise ComfyError("execution_failed", "The generation failed on the GPU worker.")
                case "execution_interrupted":
                    raise ComfyError("interrupted", "The generation was interrupted.")
        raise ComfyError("connection_lost", "Lost the connection to the generation backend.")

    async def _outputs(self, prompt_id: str) -> dict[str, Any]:
        r = await self._http.get(f"{self._base}/history/{prompt_id}")
        r.raise_for_status()
        entry = r.json().get(prompt_id, {})
        status = entry.get("status", {})
        if status.get("status_str") == "error":
            raise ComfyError("execution_failed", "The generation failed on the GPU worker.")
        return entry.get("outputs", {})

    @staticmethod
    def pick(outputs: dict[str, Any], node: str, kind: str) -> ComfyFile:
        """The first file of `kind` produced by `node`."""
        for key in _OUTPUT_KEYS.get(kind, ()):
            files = outputs.get(node, {}).get(key) or []
            if kind == "video" and key == "images":  # only a real video file counts there
                files = [
                    f for f in files if str(f.get("filename", "")).lower().endswith(_VIDEO_SUFFIXES)
                ]
            if files:
                f = files[0]
                return ComfyFile(f["filename"], f.get("subfolder", ""), f.get("type", "output"))
        raise ComfyError("missing_output", f"The workflow produced no {kind} output.")

    async def fetch(self, f: ComfyFile) -> bytes:
        r = await self._http.get(
            f"{self._base}/view",
            params={"filename": f.filename, "subfolder": f.subfolder, "type": f.type},
        )
        r.raise_for_status()
        return r.content

    async def upload_image(self, name: str, data: bytes) -> str:
        """Put the user's picture where `LoadImage` can read it, and return the reference to use in
        the graph. It goes to ComfyUI's temp folder, which ComfyUI empties when it restarts, not the
        permanent input folder: ComfyUI has no way to delete a file from there."""
        r = await self._http.post(
            f"{self._base}/upload/image",
            data={"type": "temp", "overwrite": "true"},
            files={"image": (name, data, "image/png")},
        )
        r.raise_for_status()
        return f"{r.json().get('name', name)} [temp]"

    async def free(self) -> None:
        """Release ComfyUI's cached models so the GPU is free for whatever runs next."""
        try:
            await self._http.post(
                f"{self._base}/free", json={"unload_models": True, "free_memory": True}
            )
        except httpx.HTTPError:
            log.warning("could not ask ComfyUI to free memory", exc_info=True)

    async def interrupt(self) -> None:
        try:
            await self._http.post(f"{self._base}/interrupt")
        except httpx.HTTPError:
            log.warning("could not interrupt ComfyUI", exc_info=True)


def use_picture(graph: dict[str, Any], placeholder: str, reference: str) -> dict[str, Any]:
    """The graph with the per-job picture name replaced by the backend's own reference to it."""
    out = json.loads(json.dumps(graph))
    for node in out.values():
        inputs = node.get("inputs", {})
        for key, value in inputs.items():
            if value == placeholder:
                inputs[key] = reference
    return out


def _validation_message(r: httpx.Response) -> str:
    """Workflow validation failures are our bug, not the user's, but the text stays generic."""
    try:
        detail = r.json().get("error", {}).get("message", "")
        log.error(
            "comfyui rejected the workflow: %s | %s",
            detail,
            json.dumps(r.json().get("node_errors", {}))[:500],
        )
    except ValueError:
        log.error("comfyui rejected the workflow: %s", r.text[:300])
    return "The generation request was rejected by the backend."
