"""Voice and 3D on the person's own key (ADR-0095, stage K4; music, sound effects and lip sync,
`docs/own-keys-fal-everywhere-plan.md` F2 to F4; on WaveSpeed and Runware too,
`docs/own-keys-cloud-tab-plan.md` CT3).

`KeyedSpeechEngine` stands in front of this computer's speech engine: while Voice is set to "With my
key" in Settings › Your keys, speaking runs on fal.ai (Kokoro) with that key; while Music, Sound
effects or Lip sync are, those run on fal.ai with theirs. Clone, design, transcribe and the other
tools stay here. `KeyedModel3d` does the same for 3D models (Pixal3D on
fal.ai; the cut-out with fal.ai's BiRefNet, so the 3D component need not be set up).

Both read `known`, which is kept up to date on every change, because the products ask them
synchronously (`ready()`, `models()`, `resolve()`). On the desktop that is `OwnKeysService` (the
person's key); on the web `AdminProviders` (the admin's fal.ai rows in Admin › Media, stage K5)."""

import asyncio
import io
import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import httpx
from PIL import Image, ImageOps
from wasifyai_platform_sdk import (
    LipSyncRequest,
    LipSyncResult,
    MusicRequest,
    MusicResult,
    SpeechResult,
    VoiceEngineError,
)
from wasifyai_platform_sdk.cloud_queues import queue_for
from wasifyai_platform_sdk.fal import FalError, FalQueue, data_uri
from wasifyai_platform_sdk.voice_models import OptionSpec, VoiceInfo, VoiceModel

from wasifyai_api.audio_runtime import _wav_rate, _wav_seconds
from wasifyai_api.comfy_music import to_wav
from wasifyai_api.desktop_model3d import ATLAS, RunResult
from wasifyai_api.lipsync_runtime import _video_size
from wasifyai_api.own_keys import KeyRoute

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
BY_ADMIN = "Runs on fal.ai, chosen by your admin: the picture is sent there."


class Routes(Protocol):
    """Where a product runs: `OwnKeysService` on the desktop, `AdminProviders` on the web."""

    def known(self, product: str) -> KeyRoute | None: ...

    async def route(self, product: str) -> KeyRoute | None: ...


async def _no_progress(_p: float) -> None:
    return None


def _fal(keys: Routes, product: str) -> KeyRoute | None:
    route = keys.known(product)
    return route if route is not None and route.provider.id == "fal" else None


MEDIA_PROVIDERS = ("fal", "wavespeed", "runware")


def _cloud(keys: Routes, product: str) -> KeyRoute | None:
    """The route of a product that runs on fal.ai, WaveSpeed or Runware (music, sound effects and
    lip sync); speaking and 3D are on fal.ai only (`_fal`)."""
    route = keys.known(product)
    return route if route is not None and route.provider.id in MEDIA_PROVIDERS else None


def keyed_voice_model(route: KeyRoute, admin: bool = False) -> VoiceModel:
    title = f"{route.model} · {route.provider.title}" if admin else f"{route.model} · with your key"
    return VoiceModel(
        id=KEYED_VOICE, title=title, engine="remote",
        family="kokoro_tts", package="", server_task="tts", tasks=("speak",),
        recommended=("speak",), languages=("en-us",), sample_rate=24000,
        voices=tuple(
            VoiceInfo(v, v[3:].capitalize(), "en-us", "female" if v[1] == "f" else "male")
            for v in FAL_VOICES
        ),
        default_voice="af_heart",
        options=(OptionSpec("speed", "float", "Speed", "How fast it speaks.", 1.0, 0.5, 2.0),),
    )  # fmt: skip


# ---- music, sound effects and lip sync on the key ------------------------------------------------

KEYED_MUSIC = "key:music"
KEYED_SFX = "key:sfx"
KEYED_LIPSYNC = "key:lipsync"
# what each cloud model can do, in the shape the music screen and `check_music` read. MiniMax
# chooses the length itself (it takes no duration), so its one length is only what is shown.
MINIMAX_MODES = {
    "song": {"lyrics": "optional", "instrumental": "toggle", "duration": [120, 120, 120]}
}
MINIMAX = ("fal-ai/minimax-music/v2.6", "minimax/music-2.6", "minimax:music@2.6")
MUSIC_MODELS: dict[str, tuple[str, dict[str, Any]]] = {
    **{m: ("MiniMax Music 2.6", MINIMAX_MODES) for m in MINIMAX},
    "fal-ai/elevenlabs/music": (
        "ElevenLabs Music",
        {"song": {"lyrics": "unused", "instrumental": "toggle", "duration": [3, 30, 600]}},
    ),
    "fal-ai/elevenlabs/sound-effects/v2": (
        "ElevenLabs Sound Effects",
        {"sfx": {"duration": [0.5, 5, 22]}},
    ),
}  # fmt: skip
MINIMAX_MIN_PROMPT = 10  # fal.ai's MiniMax refuses a shorter description
# the lip sync models: the longest voice one request takes, and the frame rate (25 for all)
LIPSYNC_MODELS: dict[str, tuple[str, float]] = {
    "fal-ai/longcat-single-avatar/image-audio-to-video": ("LongCat Avatar", 50.0),
    "fal-ai/infinitalk": ("InfiniteTalk", 28.0),
    # WaveSpeed bills up to 2 minutes of LongCat but says past a minute is unsteady
    "wavespeed-ai/longcat-avatar": ("LongCat Avatar", 60.0),
    "wavespeed-ai/infinitetalk": ("InfiniteTalk", 600.0),
    "wavespeed-ai/infinitetalk-fast": ("InfiniteTalk Fast", 600.0),
}
LIPSYNC_FPS = 25
LONGCAT_FIRST_S, LONGCAT_MORE_S, LONGCAT_MAX_SEGMENTS = 5.8, 5.0, 10
INFINITALK_FRAMES = (41, 721)
LIPSYNC_PROMPT = "A person talks naturally to the camera, with natural expressions and movements."
CROP_CENTRE = (0.5, 0.4)  # as the lip sync engine on this computer crops (`lipsync_server`)


def _title(name: str, route: KeyRoute, admin: bool) -> str:
    return f"{name} · {route.provider.title}" if admin else f"{name} · with your key"


def keyed_music_model(product: str, route: KeyRoute, admin: bool = False) -> VoiceModel:
    """The music (or sound effects) model offered while that product runs on the key."""
    name, modes = MUSIC_MODELS.get(route.model, (route.model, {}))
    if not modes:
        raise VoiceEngineError(
            "not_with_key",
            f"{route.model} is not a music model this app can use on {route.provider.title}.",
        )
    return VoiceModel(
        id=KEYED_SFX if product == "sfx" else KEYED_MUSIC, title=_title(name, route, admin),
        engine="remote", family=route.provider.id, package="", server_task="music",
        tasks=("music",), recommended=(), languages=("multi",), sample_rate=44100,
        music={"modes": modes, "request": {"duration": "top", "lyrics_option": "lyrics"}},
    )  # fmt: skip


def keyed_lipsync_model(route: KeyRoute, admin: bool = False) -> VoiceModel:
    """The lip sync model offered while Lip sync runs on the key: 480p or 720p, 25 frames each
    second."""
    name, longest = LIPSYNC_MODELS.get(route.model, (route.model, 0.0))
    if not longest:
        raise VoiceEngineError(
            "not_with_key",
            f"{route.model} is not a lip sync model this app can use on {route.provider.title}.",
        )
    return VoiceModel(
        id=KEYED_LIPSYNC, title=_title(name, route, admin), engine="remote",
        family=route.provider.id,
        package="", server_task="lipsync", tasks=("lipsync",), recommended=("lipsync",),
        languages=("multi",), sample_rate=0,
        lipsync={"max_voice_s": longest, "sizes": [480, 720], "default_size": 720,
                 "fps": LIPSYNC_FPS},
    )  # fmt: skip


def music_body(endpoint: str, req: MusicRequest) -> dict[str, Any]:
    """What the model is sent for a checked music request (fal.ai's fields, WaveSpeed's or a
    Runware task)."""
    if endpoint in MINIMAX and len(req.description) < MINIMAX_MIN_PROMPT:
        raise VoiceEngineError(
            "description_too_short", "Describe the music in at least ten letters for MiniMax."
        )
    if endpoint == "minimax:music@2.6":  # Runware: an `audioInference` task
        settings: dict[str, Any] = {"instrumental": req.instrumental}
        if req.lyrics:
            settings["lyrics"] = req.lyrics
        elif not req.instrumental:
            settings["lyricsOptimizer"] = True
        return {
            "taskType": "audioInference", "positivePrompt": req.description,
            "outputFormat": "WAV", "settings": settings,
        }  # fmt: skip
    if endpoint == "minimax/music-2.6":  # WaveSpeed: no lyrics writes them from the description
        ws: dict[str, Any] = {"prompt": req.description, "is_instrumental": req.instrumental}
        if req.lyrics:
            ws["lyrics"] = req.lyrics
        return ws
    if endpoint == "fal-ai/minimax-music/v2.6":
        body: dict[str, Any] = {"prompt": req.description, "is_instrumental": req.instrumental}
        if req.lyrics:
            body["lyrics"] = req.lyrics
        elif not req.instrumental:
            body["lyrics_optimizer"] = True  # MiniMax writes the words from the description
        return body
    if endpoint == "fal-ai/elevenlabs/music":
        return {
            "prompt": req.description, "music_length_ms": round(req.duration * 1000),
            "force_instrumental": req.instrumental,
        }  # fmt: skip
    return {"text": req.description, "duration_seconds": req.duration}


def lipsync_body(endpoint: str, image: str, audio: str, req: LipSyncRequest) -> dict[str, Any]:
    """What the model is sent: the picture already cut to the video's shape, the size as the
    provider names it, and on fal.ai the length (LongCat in segments, InfiniteTalk in frames);
    WaveSpeed takes the voice's own length."""
    size = "720p" if min(req.width, req.height) >= 720 else "480p"
    if endpoint.startswith("wavespeed-ai/"):
        return {"image": image, "audio": audio, "prompt": LIPSYNC_PROMPT, "resolution": size}
    body: dict[str, Any] = {
        "image_url": image, "audio_url": audio, "prompt": LIPSYNC_PROMPT,
        "resolution": size,
    }  # fmt: skip
    if endpoint == "fal-ai/infinitalk":
        lo, hi = INFINITALK_FRAMES
        frames = math.ceil(req.voice_seconds * LIPSYNC_FPS / 4) * 4 + 1  # 4k+1, as Wan makes them
        body["num_frames"] = max(lo, min(hi, frames))
    else:
        more = max(0.0, req.voice_seconds - LONGCAT_FIRST_S)
        body["num_segments"] = min(LONGCAT_MAX_SEGMENTS, 1 + math.ceil(more / LONGCAT_MORE_S))
    return body


def cut_picture(picture: bytes, width: int, height: int) -> bytes:
    """The picture cropped to the video's shape, as this computer's lip sync engine does it."""
    with Image.open(io.BytesIO(picture)) as im:
        fitted = ImageOps.fit(
            im.convert("RGB"), (width, height), Image.Resampling.LANCZOS, centering=CROP_CENTRE
        )
    out = io.BytesIO()
    fitted.save(out, "PNG")
    return out.getvalue()


class KeyedSpeechEngine:
    """The speech engine, with speaking on fal.ai while Voice runs on the person's key (or, on the
    web, the admin's row). Everything else is the engine it stands in front of."""

    def __init__(
        self,
        local: Any,
        keys: Routes,
        client: Callable[[], httpx.AsyncClient] = httpx.AsyncClient,
        timeout_s: float = 300,
        poll_s: float = 1.0,
        admin: bool = False,
    ):
        self._admin = admin
        self._local = local
        self._keys = keys
        self._client = client
        self._timeout = timeout_s
        self._poll = poll_s

    def __getattr__(self, name: str) -> Any:
        return getattr(self._local, name)

    def _keyed(self) -> dict[str, VoiceModel]:
        """The models on the key now, by their id (music, sound effects and lip sync are offered
        before this computer's models; speaking replaces them)."""
        out: dict[str, VoiceModel] = {}
        for product in ("voice", "music", "sfx", "lipsync"):
            route = self._where(product)
            if route is None:
                continue
            try:
                model = (
                    keyed_voice_model(route, self._admin) if product == "voice"
                    else keyed_lipsync_model(route, self._admin) if product == "lipsync"
                    else keyed_music_model(product, route, self._admin)
                )  # fmt: skip
            except VoiceEngineError:
                continue  # a model this app cannot use: the row's Test says so
            out[model.id] = model
        return out

    def _where(self, product: str) -> KeyRoute | None:
        return _fal(self._keys, product) if product == "voice" else _cloud(self._keys, product)

    def _row(self, model: VoiceModel, route: KeyRoute) -> dict[str, Any]:
        return {
            **model.public(), "state": "ready", "files_ready": True, "runtime_ready": True,
            "bytes_missing": 0, "source": route.provider.host,
        }  # fmt: skip

    def models(self, task: str | None = None) -> list[dict[str, Any]]:
        local = self._local.models(task)
        keyed = self._keyed()
        if not keyed:
            return local
        product = {KEYED_VOICE: "voice", KEYED_MUSIC: "music", KEYED_SFX: "sfx",
                   KEYED_LIPSYNC: "lipsync"}  # fmt: skip
        rows = [
            self._row(m, route)
            for m in keyed.values()
            if (task is None or task in m.tasks)
            and (route := self._where(product[m.id])) is not None
        ]
        if task == "speak" and rows:  # the one model for speaking while it runs on the key
            return rows
        return [*rows, *local]

    def resolve(self, task: str, model_id: str | None) -> VoiceModel:
        keyed = self._keyed()
        if task == "speak" and KEYED_VOICE in keyed:
            return keyed[KEYED_VOICE]
        if model_id in keyed and task in keyed[model_id].tasks:
            return keyed[model_id]
        if model_id is None:  # the default: what runs on the key, first
            first = next((m for m in keyed.values() if task in m.tasks), None)
            if first is not None:
                return first
        if model_id is not None and model_id.startswith("key:"):
            model_id = None  # a keyed model remembered from before: this computer's default now
        return self._local.resolve(task, model_id)

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
            except FalError as e:
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

    async def _route(self, product: str) -> KeyRoute:
        route = await self._keys.route(product)
        if route is None or route.provider.id not in MEDIA_PROVIDERS:
            raise VoiceEngineError(
                "not_with_key", "That runs on this computer now. Choose a model and try again."
            )
        return route

    async def music(self, model: VoiceModel, req: MusicRequest) -> MusicResult:
        if model.id not in (KEYED_MUSIC, KEYED_SFX):
            return await self._local.music(model, req)  # type: ignore[no-any-return]
        route = await self._route("sfx" if model.id == KEYED_SFX else "music")
        body = music_body(route.model, req)
        t0 = time.monotonic()
        name = route.provider.title
        async with self._client() as http:
            queue = queue_for(
                route.provider.id, route.key, http, self._timeout, self._poll, route.base_url
            )
            try:
                data, ctype, result = await queue.make(
                    route.model, body, "audio", "audio/mpeg", _no_progress
                )
            except FalError as e:
                raise VoiceEngineError(e.code, e.message) from None
            except TimeoutError:
                raise VoiceEngineError("provider_refused", f"{name} took too long.") from None
        wav = await to_wav(data, ".wav" if "wav" in ctype else ".mp3")
        seconds = _wav_seconds(wav)
        if seconds <= 0:
            raise VoiceEngineError("engine_failed", f"{name} sent audio this app cannot read.")
        return MusicResult(
            wav, _wav_rate(wav) or model.sample_rate, seconds, route.model,
            result.get("seed") if isinstance(result.get("seed"), int) else None, 0.0,
            time.monotonic() - t0,
        )  # fmt: skip

    async def lipsync(
        self, model: VoiceModel, req: LipSyncRequest, picture: Path, voice: Path
    ) -> LipSyncResult:
        if model.id != KEYED_LIPSYNC:
            return await self._local.lipsync(model, req, picture, voice)  # type: ignore[no-any-return]
        route = await self._route("lipsync")
        image = await asyncio.to_thread(
            cut_picture, await asyncio.to_thread(picture.read_bytes), req.width, req.height
        )
        audio = await asyncio.to_thread(voice.read_bytes)
        body = lipsync_body(route.model, data_uri(image), data_uri(audio), req)
        t0 = time.monotonic()
        name = route.provider.title
        async with self._client() as http:
            queue = queue_for(
                route.provider.id, route.key, http, max(self._timeout, 3600.0), self._poll,
                route.base_url,
            )  # fmt: skip
            try:
                mp4, _, _ = await queue.make(route.model, body, "video", "video/mp4", _no_progress)
            except FalError as e:
                raise VoiceEngineError(e.code, e.message) from None
            except TimeoutError:
                raise VoiceEngineError("provider_refused", f"{name} took too long.") from None
        width, height = _video_size(mp4)
        if not (width and height):
            raise VoiceEngineError("engine_failed", f"{name} sent a video this app cannot read.")
        return LipSyncResult(
            mp4, req.voice_seconds, LIPSYNC_FPS, width, height, route.model, 0.0,
            time.monotonic() - t0,
        )  # fmt: skip


class KeyedModel3d:
    """The 3D engine, on fal.ai while 3D runs on the person's key (or, on the web, the admin's
    row): nothing to set up, no memory used. Everything else is the engine it stands in front of."""

    def __init__(
        self,
        local: Any,
        keys: Routes,
        client: Callable[[], httpx.AsyncClient] = httpx.AsyncClient,
        timeout_s: float = 900,
        poll_s: float = 2.0,
        admin: bool = False,
    ):
        self._where = BY_ADMIN if admin else WITH_KEY
        self._local = local
        self._keys = keys
        self._client = client
        self._timeout = timeout_s
        self._poll = poll_s

    def __getattr__(self, name: str) -> Any:
        return getattr(self._local, name)

    @property
    def closing(self) -> bool:
        return bool(getattr(self._local, "closing", False))

    @closing.setter
    def closing(self, value: bool) -> None:  # the service is stopping: the web's jobs go on
        self._local.closing = value

    @property
    def keyed(self) -> bool:
        return _fal(self._keys, "model3d") is not None

    def state(self) -> dict[str, Any]:
        local = self._local.state()
        if not self.keyed:
            return local
        # the screen asks `installed` to show the 3D maker; the picker asks `here` (installed here)
        return {
            **local, "installed": True, "here": bool(local.get("installed")), "fit": self.fit(),
            "keyed": True, "about": {**local.get("about", {}), "where": self._where},
        }  # fmt: skip

    def ready(self) -> bool:
        return self.keyed or self._local.ready()

    def problem(self) -> str | None:
        return None if self.keyed else self._local.problem()

    def fit(self) -> dict[str, Any]:
        if not self.keyed:
            return self._local.fit()
        return {
            "verdict": "fits", "reason": self._where, "needed_bytes": 0, "budget_bytes": None,
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
        except FalError as e:
            return RunResult(False, "failed", e.message, time.monotonic() - t0)
        except TimeoutError:
            return RunResult(False, "wall_time", "fal.ai took too long.", time.monotonic() - t0)
        await asyncio.to_thread(out.write_bytes, data)
        return RunResult(True, None, "", time.monotonic() - t0, output=out)

    async def matte(
        self,
        picture: Path,
        out_dir: Path,
        on_line: Callable[[str], None] | None = None,
        **again: Any,  # job_key, resume: the web's engine workers pick a job up again
    ) -> RunResult:
        route = _fal(self._keys, "model3d")
        if route is None:
            return await self._local.matte(picture, out_dir, on_line, **again)
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
        **again: Any,  # job_key, resume: on fal.ai a run picked up again is made again
    ) -> RunResult:
        route = _fal(self._keys, "model3d")
        if route is None:
            return await self._local.generate(
                cutout, out_glb, seed=seed, detail=detail, on_line=on_line,
                on_progress=on_progress, **again,
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
