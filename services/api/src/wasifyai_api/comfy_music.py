"""Music made by the image engine's ComfyUI (ADR-0066, stage V3b): a second engine for the same list
of music models.

`AudioEngine` hands a checked `MusicRequest` to `ComfyMusic` when the model's descriptor says
`engine: comfyui`. The descriptor names a workflow (`music.request.workflow`); its map file says
which node takes which input, so this module has no node ids. The sidecar is the one the images use
(ADR-0059): it is started on demand, keeps the model loaded, and the slot manager unloads it when
something else needs the memory.

The workflow ends in `PreviewAudio`, so ComfyUI keeps the result in its temporary folder; it comes
back as FLAC and is turned into WAV here, because a track is a WAV (ffmpeg, or macOS's own
`afconvert`)."""

import asyncio
import contextlib
import logging
import secrets
import shutil
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import MusicRequest, MusicResult, VoiceEngineError, VoiceModel
from wasifyai_platform_sdk.workflows import Workflow

log = logging.getLogger(__name__)

_EXTRA_FFMPEG = ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg")


def _find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg") or next((p for p in _EXTRA_FFMPEG if Path(p).is_file()), None)


async def to_wav(data: bytes, suffix: str) -> bytes:
    """`data` (FLAC, MP3 ...) as WAV; WAV stays as it is. Needs ffmpeg, or macOS's `afconvert`."""
    if data[:4] == b"RIFF":
        return data
    ffmpeg = await asyncio.to_thread(_find_ffmpeg)
    afconvert = shutil.which("afconvert") if sys.platform == "darwin" else None
    if not (ffmpeg or afconvert):
        raise VoiceEngineError(
            "needs_converter", "Turning the music into a WAV needs ffmpeg on this computer."
        )
    with tempfile.TemporaryDirectory(prefix="comfy-music-") as tmp:
        src, dst = Path(tmp) / f"in{suffix}", Path(tmp) / "out.wav"
        await asyncio.to_thread(src.write_bytes, data)
        args = (
            [
                ffmpeg,
                "-nostdin",
                "-loglevel",
                "error",
                "-i",
                str(src),
                "-c:a",
                "pcm_s16le",
                str(dst),
            ]
            if ffmpeg
            else [str(afconvert), "-f", "WAVE", "-d", "LEI16", str(src), str(dst)]
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )  # fmt: skip
            await asyncio.wait_for(proc.wait(), timeout=300)
        except (OSError, TimeoutError):
            raise VoiceEngineError("engine_failed", "The music could not be converted.") from None
        if proc.returncode != 0 or not dst.is_file():
            raise VoiceEngineError("engine_failed", "The music could not be converted.")
        return await asyncio.to_thread(dst.read_bytes)


def _wav_facts(wav: bytes) -> tuple[int, float]:
    import io
    import wave

    try:
        with wave.open(io.BytesIO(wav)) as w:
            return w.getframerate(), w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, ZeroDivisionError):
        return 0, 0.0


class ComfyMusic:
    """Runs a music workflow on the app's ComfyUI sidecar."""

    def __init__(
        self,
        workflows_dir: Path,
        sidecar: Callable[[], Any],
        client_factory: Callable[[str], Any] | None = None,
    ):
        self._dir = workflows_dir
        self._sidecar = sidecar  # the ModelsService's, set when the worker is built
        self._client_factory = client_factory
        self._clients: dict[str, Any] = {}

    @property
    def installed(self) -> bool:
        sidecar = self._sidecar()
        return bool(sidecar is not None and sidecar.installed)

    def _client(self, url: str) -> Any:
        if url not in self._clients:
            if self._client_factory is not None:
                self._clients[url] = self._client_factory(url)
            else:
                from wasifyai_media_worker.comfy import ComfyClient

                self._clients[url] = ComfyClient(url)
        return self._clients[url]

    def _graph(self, model: VoiceModel, req: MusicRequest, seed: int) -> tuple[Workflow, dict]:
        rules = model.music["request"]
        try:
            wf = Workflow.load(self._dir, rules["workflow"])
        except (OSError, ValueError):
            log.exception("the music workflow %s could not be loaded", rules.get("workflow"))
            raise VoiceEngineError(
                "engine_failed", "The music workflow is missing from this install."
            ) from None
        lyrics = req.lyrics
        if req.instrumental and rules.get("instrumental_lyrics"):
            lyrics = rules["instrumental_lyrics"]
        values: dict[str, Any] = {
            "style": req.description, "lyrics": lyrics, "duration_s": req.duration, "seed": seed,
            **req.options,
        }  # fmt: skip
        unknown = set(values) - set(wf.map.inputs)
        if unknown:  # an option the workflow cannot take is our bug, not the person's
            raise VoiceEngineError(
                "engine_failed", f"{model.title} cannot take {sorted(unknown)[0]} yet."
            )
        return wf, wf.fill(values)

    async def music(self, model: VoiceModel, req: MusicRequest) -> MusicResult:
        sidecar = self._sidecar()
        if sidecar is None or not sidecar.installed:
            raise VoiceEngineError(
                "runtime_missing",
                "The image engine is not set up yet. Set up image generation first; "
                f"{model.title} runs on it.",
            )
        from wasifyai_media_worker.comfy import ComfyError

        seed = req.seed if req.seed is not None else secrets.randbelow(2**31 - 1)
        wf, graph = self._graph(model, req, seed)
        if sidecar.missing_models(graph):
            raise VoiceEngineError(
                "model_missing", f"{model.title} is not on this computer yet. Get it in Models."
            )
        t0 = time.monotonic()
        client: Any = None
        try:
            url = await sidecar.ensure_running()
            client = self._client(url)
            outputs = await client.run(
                graph, uuid.uuid4().hex, _ignore, max(600.0, min(7200.0, req.duration * 30))
            )
            out = wf.map.outputs["audio"]
            produced = client.pick(outputs, out.node, "audio")
            data = await client.fetch(produced)
        except asyncio.CancelledError:
            if client is not None:  # the model keeps working on what was asked; stop it
                with contextlib.suppress(Exception):
                    await asyncio.shield(client.interrupt())
            raise
        except ComfyError as e:
            log.warning("comfyui music failed: %s", e)
            raise VoiceEngineError(
                "engine_stopped"
                if e.code in ("connection_lost", "start_failed")
                else "engine_failed",
                e.message,
            ) from None
        except TimeoutError:
            raise VoiceEngineError(
                "engine_failed", "The music took too long. Try a shorter one."
            ) from None
        except OSError as e:
            raise VoiceEngineError("engine_stopped", "The image engine stopped. Try again.") from e
        wav = await to_wav(data, "." + produced.filename.rsplit(".", 1)[-1])
        rate, seconds = _wav_facts(wav)
        if seconds <= 0:
            raise VoiceEngineError("engine_failed", "The music model returned no audio.")
        return MusicResult(
            wav, rate or model.sample_rate, seconds, model.id, seed, 0.0, time.monotonic() - t0
        )


async def _ignore(_fraction: float) -> None:
    return None
