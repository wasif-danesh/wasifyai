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
person's key); on the web `AdminProviders` (the admin's fal.ai rows in Admin › Media, stage K5).

Each job is priced on every offer of the route that can do it and runs on the cheapest; a provider
that refuses before running hands it to the next (`on_cheapest`, ADR-0100 stage CP3). What it cost
is written as a `cloud.cost` usage event."""

import asyncio
import io
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
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
from wasifyai_platform_sdk.fal import FalError, FalQueue
from wasifyai_platform_sdk.offers import Priced, cost_event, no_offer, order, run_cheapest
from wasifyai_platform_sdk.usage import UsageRecorder, record_safely
from wasifyai_platform_sdk.voice_models import OptionSpec, VoiceInfo, VoiceModel

from wasifyai_api.audio_runtime import _wav_rate, _wav_seconds
from wasifyai_api.comfy_music import to_wav
from wasifyai_api.desktop_model3d import ATLAS, RunResult
from wasifyai_api.lipsync_runtime import _video_size
from wasifyai_api.logging import product_id as current_product
from wasifyai_api.logging import tenant_id as current_tenant
from wasifyai_api.own_keys import KeyChoice, KeyRoute, offer_of

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
    """The route of a product whose model has a fal.ai offer with a key (speaking and 3D)."""
    route = keys.known(product)
    if route is None or not any(c.provider.id == "fal" for c in route.offers()):
        return None
    return route


async def on_cheapest[T](
    route: KeyRoute,
    product: str,
    job: dict[str, Any],
    attempt: Callable[[KeyChoice], Awaitable[T]],
    usage: UsageRecorder | None = None,
    needs: tuple[str, ...] = (),
    only: str | None = None,
) -> tuple[T, Priced[KeyChoice]]:
    """Run a job on the cheapest offer of `route` that can do it, the next on a refusal before
    running, and write what it cost. `attempt(choice)` sends the job to that offer."""
    ordered = order(route.offers(), offer_of, job, needs, only)
    if not ordered:
        raise no_offer(route.title or route.model, [c.offer for c in route.offers()], needs, only)

    async def one(p: Priced[KeyChoice]) -> T:
        return await attempt(p.choice)

    made, used = await run_cheapest(ordered, one)
    if usage is not None and used.cost > 0:
        tenant = current_tenant.get()
        pid = current_product.get()
        await record_safely(
            usage,
            cost_event(
                used, route.model, "default" if tenant in ("", "-") else tenant,
                pid if pid not in ("", "-") else f"keys:{product}",
            ),
        )  # fmt: skip
    return made, used


MEDIA_PROVIDERS = ("fal", "wavespeed", "runware")


def _cloud(keys: Routes, product: str) -> KeyRoute | None:
    """The route of a product that runs on fal.ai, WaveSpeed or Runware (music, sound effects and
    lip sync); speaking and 3D are on fal.ai only (`_fal`)."""
    route = keys.known(product)
    return route if route is not None and route.provider.id in MEDIA_PROVIDERS else None


def keyed_voice_model(route: KeyRoute, admin: bool = False) -> VoiceModel:
    name = route.title or route.model
    title = f"{name} · {route.provider.title}" if admin else f"{name} · with your key"
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
MINIMAX = ("fal-ai/minimax-music/v2.6", "minimax/music-2.6", "minimax:music@2.6")  # its endpoints
# by the catalogue's id for the model (`own_keys_catalogue.py`); an admin's row on the web names
# fal.ai's endpoint, so that is found too (`_music_of`)
MUSIC_MODELS: dict[str, tuple[str, dict[str, Any]]] = {
    "minimax-music-2.6": ("MiniMax Music 2.6", MINIMAX_MODES),
    "elevenlabs-music": (
        "ElevenLabs Music",
        {"song": {"lyrics": "unused", "instrumental": "toggle", "duration": [3, 30, 600]}},
    ),
    "elevenlabs-sfx-v2": (
        "ElevenLabs Sound Effects",
        {"sfx": {"duration": [0.5, 5, 22]}},
    ),
}  # fmt: skip
MINIMAX_MIN_PROMPT = 10  # fal.ai's MiniMax refuses a shorter description


@dataclass(frozen=True)
class CloudLipSync:
    """A lip sync model on a provider: the longest voice one request takes, the sizes it makes
    (short side; 480 is 480p), what it costs per video second at each size (dollars, as listed)
    and how many seconds of work each video second took when measured
    (`docs/spikes/lipsync-cloud-race.md`; a size not measured is left out), and what else its
    request carries."""

    name: str
    longest: float
    sizes: tuple[int, ...]
    default_size: int
    price: dict[int, float] = field(default_factory=dict)
    work: dict[int, float] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    sends_size: bool = True  # Kling takes no size: it makes the picture's own
    # the video's frame as the model makes it, measured: "square" whatever the picture sent, or
    # "shape" (the picture's own shape at a size the model picks); and its short side by size
    frame: str = "shape"
    frame_short: dict[int, int] = field(default_factory=dict)


LIPSYNC_MODELS: dict[str, CloudLipSync] = {  # by the catalogue's id, as MUSIC_MODELS
    # Fabric's time: 4.8 s per video second for a 3 s clip in the race, 25 s for a 5.6 s clip from
    # the app; the slower one is shown so the screen does not promise too little
    "fabric-1.0": CloudLipSync(
        "Fabric 1.0 Fast", 60.0, (480, 720), 480, {480: 0.10, 720: 0.20}, {480: 25.0},
        frame="square", frame_short={480: 640},
    ),
    "kling-avatar-v2": CloudLipSync(
        "Kling Avatar v2", 60.0, (720,), 720, {720: 0.0562}, {720: 40.0}, sends_size=False,
        frame_short={720: 912},
    ),
    # 720p: fal.ai says it is quicker and better than 1080p, and takes up to 60 s of voice
    "omnihuman-1.5": CloudLipSync(
        "OmniHuman 1.5", 60.0, (720,), 720, {720: 0.16}, {720: 43.0}, {"turbo_mode": True},
        frame="square", frame_short={720: 960},
    ),
    "infinitalk": CloudLipSync(
        "InfiniteTalk", 28.0, (480, 720), 480, {480: 0.20, 720: 0.40}, {480: 52.0},
        {"acceleration": "high"}, frame_short={480: 576},
    ),
}  # fmt: skip
LIPSYNC_FPS = 25
INFINITALK_FRAMES = (41, 721)
LIPSYNC_PROMPT = "A person talks naturally to the camera, with natural expressions and movements."
CROP_CENTRE = (0.5, 0.4)  # as the lip sync engine on this computer crops (`lipsync_server`)


def _model_id(product: str, route: KeyRoute) -> str:
    """The catalogue's id of the route's model (an admin's row names fal.ai's endpoint)."""
    from wasifyai_api.own_keys_catalogue import media_model

    m = media_model(product, route.model)
    return m.model if m else route.model


def _title(name: str, route: KeyRoute, admin: bool) -> str:
    return f"{name} · {route.provider.title}" if admin else f"{name} · with your key"


def keyed_music_model(product: str, route: KeyRoute, admin: bool = False) -> VoiceModel:
    """The music (or sound effects) model offered while that product runs on the key."""
    name, modes = MUSIC_MODELS.get(_model_id(product, route), (route.model, {}))
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
    """The lip sync model offered while Lip sync runs on the key: its sizes, 25 frames each second,
    and, for the screen, its price and measured time per video second at each size and the frame
    it makes (square, or the picture's shape) with its measured short side."""
    m = LIPSYNC_MODELS.get(_model_id("lipsync", route))
    if m is None:
        raise VoiceEngineError(
            "not_with_key",
            f"{route.model} is not a lip sync model this app can use on {route.provider.title}.",
        )
    return VoiceModel(
        id=KEYED_LIPSYNC, title=_title(m.name, route, admin), engine="remote",
        family=route.provider.id,
        package="", server_task="lipsync", tasks=("lipsync",), recommended=("lipsync",),
        languages=("multi",), sample_rate=0,
        lipsync={"max_voice_s": m.longest, "sizes": list(m.sizes), "default_size": m.default_size,
                 "fps": LIPSYNC_FPS, "where": route.provider.title,
                 "price_per_s": {str(k): v for k, v in m.price.items()},
                 "work_per_s": {str(k): v for k, v in m.work.items()},
                 "frame": m.frame, "frame_short": {str(k): v for k, v in m.frame_short.items()}},
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


def lipsync_body(
    model_id: str, endpoint: str, image: str, audio: str, req: LipSyncRequest
) -> dict[str, Any]:
    """What the model is sent: the picture already cut to the video's shape, the size as the
    provider names it, the model's own speed setting, and on fal.ai the length where the model asks
    for it (InfiniteTalk, in frames); the others take the voice's own length."""
    model = LIPSYNC_MODELS.get(model_id)
    short = min(req.width, req.height)
    size = "720p" if short >= 720 else "480p"
    body: dict[str, Any] = {"image_url": image, "audio_url": audio}
    if endpoint != "veed/fabric-1.0/fast":  # Fabric takes the picture, the voice and the size only
        body["prompt"] = LIPSYNC_PROMPT
    if model is None or model.sends_size:
        body["resolution"] = size
    body.update(model.extra if model else {})
    if endpoint == "fal-ai/infinitalk":
        lo, hi = INFINITALK_FRAMES
        # 4k+1, as Wan makes them, and never longer than the voice: fal.ai refuses 77 frames for a
        # 3.00 s voice ("must be at least 3.08 s"; real run of 2026-11-12), so round down
        frames = math.floor((req.voice_seconds * LIPSYNC_FPS - 1) / 4) * 4 + 1
        body["num_frames"] = max(lo, min(hi, frames))
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
        usage: UsageRecorder | None = None,
    ):
        self._admin = admin
        self._usage = usage
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
        if route is None:
            raise VoiceEngineError(
                "not_with_key", "Voice runs on this computer now. Choose a model and try again."
            )
        body: dict[str, Any] = {"prompt": text, "voice": voice or model.default_voice}
        speed = options.get("speed")
        if isinstance(speed, int | float):
            body["speed"] = float(speed)
        t0 = time.monotonic()

        async def attempt(c: KeyChoice) -> bytes:
            async with self._client() as http:
                fal = FalQueue(c.key, http, self._timeout, self._poll, c.base_url)
                result = await fal.call(c.offer.endpoint, body, _no_progress)
                wav, _ = await fal.fetch(result.get("audio"), "audio/wav")
                return wav

        try:
            # Kokoro is on fal.ai only; more speaking models and providers come in CP7
            wav, _used = await on_cheapest(
                route, "voice", {"characters": len(text)}, attempt, self._usage, only="fal"
            )
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
            wav, _wav_rate(wav) or model.sample_rate, seconds, _used.offer.endpoint, body["voice"],
            0.0,
            time.monotonic() - t0,
        )  # fmt: skip

    async def _route(self, product: str) -> KeyRoute:
        route = await self._keys.route(product)
        if route is None or not any(c.provider.id in MEDIA_PROVIDERS for c in route.offers()):
            raise VoiceEngineError(
                "not_with_key", "That runs on this computer now. Choose a model and try again."
            )
        return route

    async def music(self, model: VoiceModel, req: MusicRequest) -> MusicResult:
        if model.id not in (KEYED_MUSIC, KEYED_SFX):
            return await self._local.music(model, req)  # type: ignore[no-any-return]
        product = "sfx" if model.id == KEYED_SFX else "music"
        route = await self._route(product)
        t0 = time.monotonic()

        async def attempt(c: KeyChoice) -> tuple[bytes, str, dict[str, Any]]:
            body = music_body(c.offer.endpoint, req)
            async with self._client() as http:
                queue = queue_for(c.provider.id, c.key, http, self._timeout, self._poll, c.base_url)
                return await queue.make(c.offer.endpoint, body, "audio", "audio/mpeg", _no_progress)

        name = route.provider.title
        try:
            (data, ctype, result), used = await on_cheapest(
                route, product, {"seconds": req.duration}, attempt, self._usage
            )
            name = used.choice.provider.title
        except FalError as e:
            raise VoiceEngineError(e.code, e.message) from None
        except TimeoutError:
            raise VoiceEngineError("provider_refused", f"{name} took too long.") from None
        wav = await to_wav(data, ".wav" if "wav" in ctype else ".mp3")
        seconds = _wav_seconds(wav)
        if seconds <= 0:
            raise VoiceEngineError("engine_failed", f"{name} sent audio this app cannot read.")
        return MusicResult(
            wav, _wav_rate(wav) or model.sample_rate, seconds, used.offer.endpoint,
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
        t0 = time.monotonic()
        model_id = _model_id("lipsync", route)
        size = "720p" if min(req.width, req.height) >= 720 else "480p"

        async def attempt(c: KeyChoice) -> bytes:
            if c.provider.id != "fal":  # the other providers' lip sync comes in CP6
                raise FalError("not_with_key", f"Lip sync is not sent to {c.provider.title} yet.",
                               before_running=True)  # fmt: skip
            async with self._client() as http:
                queue = FalQueue(c.key, http, max(self._timeout, 3600.0), self._poll, c.base_url)
                # fal.ai refuses a voice inside the request ("URL too long"): upload both first
                face, said = (
                    await queue.upload(image, "face.png"),
                    await queue.upload(audio, voice.name),
                )
                body = lipsync_body(model_id, c.offer.endpoint, face, said, req)
                mp4, _, _ = await queue.make(
                    c.offer.endpoint, body, "video", "video/mp4", _no_progress
                )
                return mp4

        name = route.provider.title
        try:
            mp4, used = await on_cheapest(
                route, "lipsync", {"seconds": req.voice_seconds, "resolution": size}, attempt,
                self._usage,
            )  # fmt: skip
            name = used.choice.provider.title
        except FalError as e:
            raise VoiceEngineError(e.code, e.message) from None
        except TimeoutError:
            raise VoiceEngineError("provider_refused", f"{name} took too long.") from None
        width, height = _video_size(mp4)
        if not (width and height):
            raise VoiceEngineError("engine_failed", f"{name} sent a video this app cannot read.")
        return LipSyncResult(
            mp4, req.voice_seconds, LIPSYNC_FPS, width, height, used.offer.endpoint, 0.0,
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
        usage: UsageRecorder | None = None,
    ):
        self._where = BY_ADMIN if admin else WITH_KEY
        self._usage = usage
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
        self, route: KeyRoute, picture: bytes, body: dict[str, Any], endpoint: str | None,
        field: str, out: Path, on_progress: Callable[[float], Any] = _no_progress,
    ) -> RunResult:  # fmt: skip
        """`body` on fal.ai with `picture` as its `image_url`, uploaded to fal.ai's file store first
        (a picture inside the request can be refused as too long, as a voice was). `endpoint` None
        is the route's model, on its cheapest offer (3D on more providers comes in CP9)."""
        t0 = time.monotonic()

        async def attempt(c: KeyChoice) -> bytes:
            async with self._client() as http:
                fal = FalQueue(c.key, http, self._timeout, self._poll, c.base_url)
                sent = {"image_url": await fal.upload(picture, "picture.png"), **body}
                result = await fal.call(endpoint or c.offer.endpoint, sent, on_progress)
                data, _ = await fal.fetch(result.get(field), "application/octet-stream")
                return data

        try:
            if endpoint is None:
                data, _ = await on_cheapest(route, "model3d", {}, attempt, self._usage, only="fal")
            else:  # a helper on the same key (the cut-out): not the model, not priced
                fal = next(c for c in route.offers() if c.provider.id == "fal")
                data = await attempt(fal)
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
        body = {"output_format": "png"}
        return await self._run(route, data, body, FAL_MATTE, "image", out_dir / "keyed_cutout.png")

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
            "seed": seed, "resolution": FAL_3D_RESOLUTION, "texture_size": ATLAS.get(detail, 2048),
        }  # fmt: skip

        async def told(p: float) -> None:
            if on_progress is not None:
                on_progress(p, "Waiting for fal.ai" if p < 0.1 else "Making it on fal.ai")

        return await self._run(route, data, body, None, "model_glb", out_glb, told)
