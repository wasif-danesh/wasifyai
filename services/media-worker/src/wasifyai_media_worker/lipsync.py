"""Lip sync on the talking-head server (ADR-0044, `services/lipsync-musetalk`).

The picture and the voice are the files the worker read from the user's uploads; the server answers
with an MP4 of the same length as the voice."""

import logging
from typing import Any

import httpx
from wasifyai_platform_sdk import JobRequest

from wasifyai_media_worker.backends import raise_for_backend
from wasifyai_media_worker.comfy import ComfyError, ProgressFn

log = logging.getLogger(__name__)


class LipSyncRunner:
    backend = "lipsync-server"
    local_gpu = True  # on a Mac the server uses this machine's GPU: take the GPU turn

    def __init__(self, base_url: str, timeout_s: float, http: httpx.AsyncClient):
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s
        self._http = http

    async def run(
        self, job: JobRequest, on_progress: ProgressFn, files: Any = None
    ) -> dict[str, tuple[bytes, str, str]]:
        image, audio = (files or {}).get("image"), (files or {}).get("audio")
        if not image or not audio:
            raise ComfyError("invalid_workflow", "The request is missing the picture or the voice.")
        await on_progress(0.05)
        r = await self._http.post(
            f"{self._base}/v1/lipsync",
            data={"fps": "25"},
            files={
                "image": ("face.png", image, "image/png"),
                "audio": ("voice.wav", audio, "audio/wav"),
            },
            timeout=self._timeout,
        )
        if r.status_code == 422:  # the server could not use the picture: say so plainly
            log.warning("lip sync server refused the picture: %s", r.text[:200])
            raise ComfyError(
                "invalid_input", "No clear face was found in the picture. Try a front-facing one."
            )
        if r.status_code == 500:  # the server tried and failed: another try would fail the same way
            log.error("lip sync server failed: %s", r.text[:200])
            raise ComfyError("job_failed", "The lip sync could not be made. Please try again.")
        raise_for_backend(r)
        await on_progress(1.0)
        return {"video": (r.content, "video/mp4", "mp4")}
