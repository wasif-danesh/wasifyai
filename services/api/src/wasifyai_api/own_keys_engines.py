"""Voice and 3D on the person's own key (ADR-0095, stage K4).

`KeyedSpeechEngine` stands in front of this computer's speech engine: while Voice is set to "With my
key" in Settings › Your keys, speaking runs on fal.ai (Kokoro) with that key; clone, design, music,
transcribe and the other tools stay here. `KeyedModel3d` does the same for 3D models (Pixal3D on
fal.ai; the cut-out with fal.ai's BiRefNet, so the 3D component need not be set up).

Both read `OwnKeysService.known`, which is kept up to date on every change in Settings, because the
products ask them synchronously (`ready()`, `models()`, `resolve()`)."""

import asyncio
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from wasifyai_media_worker.backends import FalQueue, data_uri
from wasifyai_media_worker.comfy import ComfyError
from wasifyai_platform_sdk import SpeechResult, VoiceEngineError
from wasifyai_platform_sdk.voice_models import OptionSpec, VoiceInfo, VoiceModel

from wasifyai_api.audio_runtime import _wav_rate, _wav_seconds
from wasifyai_api.desktop_model3d import ATLAS, RunResult
from wasifyai_api.own_keys import KeyRoute, OwnKeysService

# the voice model's id while Voice runs on the key: the one model offered for speaking
KEYED_VOICE = "key:voice"
# the voices fal.ai's Kokoro offers (its page lists the American ones only)
FAL_VOICES = (
    "af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica", "af_kore", "af_nicole",
    "af_nova", "af_river", "af_sarah", "af_sky", "am_adam", "am_echo", "am_eric", "am_fenrir",
    "am_liam", "am_michael", "am_onyx", "am_puck", "am_santa",
)  # fmt: skip
FAL_MATTE = "fal-ai/birefnet"  # the cut-out of a picture, on the same key as the 3D model
FAL_3D_RESOLUTION = 1024  # what this computer's run uses too (`--res 1024`)
WITH_KEY = "Runs on fal.ai with your key: the picture is sent there."


async def _no_progress(_p: float) -> None:
    return None


def _fal(keys: OwnKeysService, product: str) -> KeyRoute | None:
    route = keys.known(product)
    return route if route is not None and route.provider.id == "fal" else None


def keyed_voice_model(route: KeyRoute) -> VoiceModel:
    return VoiceModel(
        id=KEYED_VOICE, title=f"{route.model} · with your key", engine="remote",
        family="kokoro_tts", package="", server_task="tts", tasks=("speak",),
        recommended=("speak",), languages=("en-us",), sample_rate=24000,
        voices=tuple(
            VoiceInfo(v, v[3:].capitalize(), "en-us", "female" if v[1] == "f" else "male")
            for v in FAL_VOICES
        ),
        default_voice="af_heart",
        options=(OptionSpec("speed", "float", "Speed", "How fast it speaks.", 1.0, 0.5, 2.0),),
    )  # fmt: skip


class KeyedSpeechEngine:
    """The speech engine, with speaking on fal.ai while Voice runs on the person's key. Everything
    it does not say otherwise is the engine of this computer's."""

    def __init__(
        self,
        local: Any,
        keys: OwnKeysService,
        client: Callable[[], httpx.AsyncClient] = httpx.AsyncClient,
        timeout_s: float = 300,
        poll_s: float = 1.0,
    ):
        self._local = local
        self._keys = keys
        self._client = client
        self._timeout = timeout_s
        self._poll = poll_s

    def __getattr__(self, name: str) -> Any:
        return getattr(self._local, name)

    def models(self, task: str | None = None) -> list[dict[str, Any]]:
        local = self._local.models(task)
        route = _fal(self._keys, "voice")
        if route is None:
            return local
        keyed = {
            **keyed_voice_model(route).public(), "state": "ready", "files_ready": True,
            "runtime_ready": True, "bytes_missing": 0, "source": route.provider.host,
        }  # fmt: skip
        if task == "speak":  # the one model for speaking while it runs on the key
            return [keyed]
        return [keyed, *local] if task is None else local

    def resolve(self, task: str, model_id: str | None) -> VoiceModel:
        route = _fal(self._keys, "voice")
        if route is not None and task == "speak":
            return keyed_voice_model(route)
        return self._local.resolve(task, None if model_id == KEYED_VOICE else model_id)

    async def speak(
        self,
        model: VoiceModel,
        text: str,
        voice: str | None,
        options: dict[str, Any],
        *,
        beside: bool = False,
    ) -> SpeechResult:
        if model.id != KEYED_VOICE:
            return await self._local.speak(model, text, voice, options, beside=beside)
        route = await self._keys.route("voice")
        if route is None or route.provider.id != "fal":
            raise VoiceEngineError(
                "not_with_key", "Voice runs on this computer now. Choose a model and try again."
            )
        body: dict[str, Any] = {"prompt": text, "voice": voice or model.default_voice}
        speed = options.get("speed")
        if isinstance(speed, int | float):
            body["speed"] = float(speed)
        t0 = time.monotonic()
        async with self._client() as http:
            fal = FalQueue(route.key, http, self._timeout, self._poll, route.base_url)
            try:
                result = await fal.call(route.model, body, _no_progress)
                wav, _ = await fal.fetch(result.get("audio"), "audio/wav")
            except ComfyError as e:
                raise VoiceEngineError(e.code, e.message) from None
            except TimeoutError:
                raise VoiceEngineError("provider_refused", "fal.ai took too long.") from None
        seconds = _wav_seconds(wav)
        if seconds <= 0:
            raise VoiceEngineError(
                "engine_failed", "fal.ai sent the speech in a form this app cannot read."
            )
        return SpeechResult(
            wav, _wav_rate(wav) or model.sample_rate, seconds, route.model, body["voice"], 0.0,
            time.monotonic() - t0,
        )  # fmt: skip


class KeyedModel3d:
    """The 3D engine, on fal.ai while 3D runs on the person's key: nothing to set up, no memory
    of this computer's used. Everything else is the engine of this computer's."""

    def __init__(
        self,
        local: Any,
        keys: OwnKeysService,
        client: Callable[[], httpx.AsyncClient] = httpx.AsyncClient,
        timeout_s: float = 900,
        poll_s: float = 2.0,
    ):
        self._local = local
        self._keys = keys
        self._client = client
        self._timeout = timeout_s
        self._poll = poll_s

    def __getattr__(self, name: str) -> Any:
        return getattr(self._local, name)

    @property
    def keyed(self) -> bool:
        return _fal(self._keys, "model3d") is not None

    def state(self) -> dict[str, Any]:
        local = self._local.state()
        if not self.keyed:
            return local
        # the screen asks `installed` to show the 3D maker; the picker asks `here` (installed here)
        return {**local, "installed": True, "here": local["installed"], "fit": self.fit(),
                "keyed": True, "about": {**local.get("about", {}), "where": WITH_KEY}}  # fmt: skip

    def ready(self) -> bool:
        return self.keyed or self._local.ready()

    def problem(self) -> str | None:
        return None if self.keyed else self._local.problem()

    def fit(self) -> dict[str, Any]:
        if not self.keyed:
            return self._local.fit()
        return {
            "verdict": "fits", "reason": WITH_KEY, "needed_bytes": 0, "budget_bytes": None,
            "capacity_bytes": None, "estimate": False, "partly_on_cpu": False,
        }  # fmt: skip

    async def _run(
        self, route: KeyRoute, body: dict[str, Any], endpoint: str, field: str, out: Path,
        on_progress: Callable[[float], Any] = _no_progress,
    ) -> RunResult:  # fmt: skip
        t0 = time.monotonic()
        try:
            async with self._client() as http:
                fal = FalQueue(route.key, http, self._timeout, self._poll, route.base_url)
                result = await fal.call(endpoint, body, on_progress)
                data, _ = await fal.fetch(result.get(field), "application/octet-stream")
        except ComfyError as e:
            return RunResult(False, "failed", e.message, time.monotonic() - t0)
        except TimeoutError:
            return RunResult(False, "wall_time", "fal.ai took too long.", time.monotonic() - t0)
        await asyncio.to_thread(out.write_bytes, data)
        return RunResult(True, None, "", time.monotonic() - t0, output=out)

    async def matte(
        self, picture: Path, out_dir: Path, on_line: Callable[[str], None] | None = None
    ) -> RunResult:
        route = _fal(self._keys, "model3d")
        if route is None:
            return await self._local.matte(picture, out_dir, on_line)
        data = await asyncio.to_thread(picture.read_bytes)
        body = {"image_url": data_uri(data), "output_format": "png"}
        return await self._run(route, body, FAL_MATTE, "image", out_dir / "keyed_cutout.png")

    async def generate(
        self,
        cutout: Path,
        out_glb: Path,
        *,
        seed: int = 42,
        detail: str = "standard",
        on_line: Callable[[str], None] | None = None,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> RunResult:
        route = _fal(self._keys, "model3d")
        if route is None:
            return await self._local.generate(
                cutout, out_glb, seed=seed, detail=detail, on_line=on_line,
                on_progress=on_progress,
            )  # fmt: skip
        data = await asyncio.to_thread(cutout.read_bytes)
        body = {
            "image_url": data_uri(data), "seed": seed, "resolution": FAL_3D_RESOLUTION,
            "texture_size": ATLAS.get(detail, 2048),
        }  # fmt: skip

        async def told(p: float) -> None:
            if on_progress is not None:
                on_progress(p, "Waiting for fal.ai" if p < 0.1 else "Making it on fal.ai")

        return await self._run(route, body, route.model, "model_glb", out_glb, told)
