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
    ConvertRequest,
    LipSyncRequest,
    LipSyncResult,
    MusicEditRequest,
    MusicRequest,
    MusicResult,
    SeparateRequest,
    SeparateResult,
    SpeechResult,
    Stem,
    TranscriptResult,
    VoiceEngineError,
)
from wasifyai_platform_sdk.cloud_queues import fetch_file, queue_for
from wasifyai_platform_sdk.fal import FalError, FalQueue, data_uri
from wasifyai_platform_sdk.offers import Priced, cost_event, no_offer, order, run_cheapest
from wasifyai_platform_sdk.usage import UsageRecorder, record_safely
from wasifyai_platform_sdk.voice_models import VoiceModel

from wasifyai_api.audio_runtime import _wav_rate, _wav_seconds
from wasifyai_api.comfy_music import to_mp3, to_wav
from wasifyai_api.desktop_model3d import ATLAS, RunResult
from wasifyai_api.lipsync_runtime import _video_size
from wasifyai_api.logging import product_id as current_product
from wasifyai_api.logging import tenant_id as current_tenant
from wasifyai_api.own_keys import KeyChoice, KeyRoute, offer_of
from wasifyai_api.own_keys_music import (
    KEYED_MUSIC,
    KEYED_MUSICEDIT,
    KEYED_SFX,
    KEYED_SPLIT,
    MP3_ONLY,
    MUSIC_PRODUCTS,
    SPLIT_MODELS,
    edit_body,
    edit_job,
    model_name,
    music_body,
    music_job,
    music_model,
    music_verb,
    split_body,
    stems_in_zip,
    stems_of,
)
from wasifyai_api.own_keys_voice import (
    KEYED_CHANGE,
    KEYED_CLONE,
    KEYED_TRANSCRIBE,
    KEYED_VOICE,
    VOICE_PRODUCTS,
    change_model,
    clone_model,
    clone_request,
    convert_request,
    design_request,
    made_voice,
    new_voice_id,
    speak_request,
    speaker_model,
    transcribe_model,
    transcribe_request,
    transcript_of,
    voice_key,
)

FAL_MATTE = "fal-ai/birefnet"  # the cut-out of a picture, on the same key as the 3D model
FAL_3D_RESOLUTION = 1024  # what this computer's run uses too (`--res 1024`)
WITH_KEY = "Runs on a cloud model with your key: the picture is sent there."
BY_ADMIN = "Runs on a cloud model, chosen by your admin: the picture is sent there."


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
TOOL_PRODUCTS = ("voiceclone", "transcribe", "voicechange")  # the voice tools (CP7)


def _cloud(keys: Routes, product: str) -> KeyRoute | None:
    """The route of a product that runs on fal.ai, WaveSpeed or Runware (music, sound effects and
    lip sync); speaking and 3D are on fal.ai only (`_fal`)."""
    route = keys.known(product)
    return route if route is not None and route.provider.id in MEDIA_PROVIDERS else None


def keyed_voice_model(route: KeyRoute, admin: bool = False) -> VoiceModel:
    """The speaking model offered while Voice runs on a cloud model: its named voices."""
    name = route.title or route.model
    title = f"{name} · {route.provider.title}" if admin else f"{name} · with your key"
    return speaker_model(_model_id("voice", route), title, route.provider.id)


def keyed_tool_model(product: str, route: KeyRoute, admin: bool = False) -> VoiceModel:
    """The model offered for copying or designing a voice, writing down speech or changing a voice
    while that product runs on a cloud model; a copy model offers what its keyed offers can do."""
    name = route.title or route.model
    title = f"{name} · {route.provider.title}" if admin else f"{name} · with your key"
    if product == "voiceclone":
        can = {v for c in route.offers() for v in c.offer.can}
        tasks = tuple(t for t in ("clone", "design") if t in can)
        if not tasks:
            raise VoiceEngineError("not_with_key", f"{name} can do nothing with these keys.")
        return clone_model(tasks, title, route.provider.id, _model_id(product, route))
    if product == "transcribe":
        return transcribe_model(title, route.provider.id)
    return change_model(title, route.provider.id)


# ---- music, sound effects and lip sync on the key ------------------------------------------------

KEYED_LIPSYNC = "key:lipsync"


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
    """The music model offered while that product (songs, sound effects, splitting or editing)
    runs on a cloud model (ADR-0100, CP8)."""
    model_id = _model_id(product, route)
    name = model_name(model_id, route.model)
    try:
        return music_model(product, model_id, _title(name, route, admin), route.provider.id)
    except VoiceEngineError:
        raise VoiceEngineError(
            "not_with_key",
            f"{route.model} is not a music model this app can use on {route.provider.title}.",
        ) from None


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
    price, where = dict(m.price), route.provider.title
    for size in m.sizes:  # the cheapest offer with a key at each size (ADR-0100, CP6)
        priced = order(route.offers(), offer_of, {"seconds": 1, "resolution": f"{size}p"})
        if priced and priced[0].cost > 0:
            price[size] = priced[0].cost
            if size == m.default_size:
                where = priced[0].choice.provider.title
    return VoiceModel(
        id=KEYED_LIPSYNC, title=_title(m.name, route, admin), engine="remote",
        family=route.provider.id,
        package="", server_task="lipsync", tasks=("lipsync",), recommended=("lipsync",),
        languages=("multi",), sample_rate=0,
        lipsync={"max_voice_s": m.longest, "sizes": list(m.sizes), "default_size": m.default_size,
                 "fps": LIPSYNC_FPS, "where": where,
                 "price_per_s": {str(k): v for k, v in price.items()},
                 "work_per_s": {str(k): v for k, v in m.work.items()},
                 "frame": m.frame, "frame_short": {str(k): v for k, v in m.frame_short.items()}},
    )  # fmt: skip


def lipsync_body(
    model_id: str, endpoint: str, image: str, audio: str, req: LipSyncRequest,
    provider: str = "fal",
) -> dict[str, Any]:  # fmt: skip
    """What the model is sent: the picture already cut to the video's shape, the size as the
    provider names it, the model's own speed setting, and on fal.ai the length where the model asks
    for it (InfiniteTalk, in frames); the others take the voice's own length. On Runware it is a
    `videoInference` task with the picture and the voice in `inputs`; on WaveSpeed the fields are
    `image` and `audio` (ADR-0100, CP6, the fields read in `docs/spikes/cloud-v1-cp0.md`)."""
    model = LIPSYNC_MODELS.get(model_id)
    short = min(req.width, req.height)
    size = "720p" if short >= 720 else "480p"
    if provider == "runware":  # Kling and OmniHuman: the picture's own size, a prompt
        return {
            "taskType": "videoInference", "positivePrompt": LIPSYNC_PROMPT,
            "inputs": {"image": image, "audio": audio}, "outputFormat": "MP4",
            "includeCost": True,
        }  # fmt: skip
    if provider == "wavespeed":  # Fabric and InfiniteTalk: a size; InfiniteTalk a prompt
        ws: dict[str, Any] = {"image": image, "audio": audio, "resolution": size}
        if endpoint == "wavespeed-ai/infinitetalk":
            ws["prompt"] = LIPSYNC_PROMPT
        return ws
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
        for product in ("voice", *TOOL_PRODUCTS, *MUSIC_PRODUCTS.values(), "lipsync"):
            route = self._where(product)
            if route is None:
                continue
            try:
                model = (
                    keyed_voice_model(route, self._admin) if product == "voice"
                    else keyed_tool_model(product, route, self._admin)
                    if product in TOOL_PRODUCTS
                    else keyed_lipsync_model(route, self._admin) if product == "lipsync"
                    else keyed_music_model(product, route, self._admin)
                )  # fmt: skip
            except VoiceEngineError:
                continue  # a model this app cannot use: the row's Test says so
            out[model.id] = model
        return out

    def _where(self, product: str) -> KeyRoute | None:
        return _cloud(self._keys, product)

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
        product = {**VOICE_PRODUCTS, **MUSIC_PRODUCTS, KEYED_LIPSYNC: "lipsync"}
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
        route = await self._route("voice")
        model_id = _model_id("voice", route)
        chosen = voice or model.default_voice
        speed = options.get("speed")
        speed = float(speed) if isinstance(speed, int | float) else None
        t0 = time.monotonic()

        async def attempt(c: KeyChoice) -> tuple[bytes, str]:
            body = speak_request(model_id, c.provider.id, c.offer.endpoint, text, chosen, speed)
            return await self._audio(c, c.offer.endpoint, body)

        (data, ext), used = await self._cheapest(route, "voice", {"characters": len(text)}, attempt)
        wav = await self._wav(data, ext, used)
        return SpeechResult(
            wav, _wav_rate(wav) or model.sample_rate, _wav_seconds(wav), used.offer.endpoint,
            chosen, 0.0, time.monotonic() - t0,
        )  # fmt: skip

    # ---- the voice tools on a cloud model (ADR-0100, CP7) --------------------------------------

    async def _audio(
        self, c: KeyChoice, endpoint: str, body: dict[str, Any], hold: Any = None
    ) -> tuple[bytes, str]:
        """The audio a provider makes for `body`: its bytes and their kind (wav or mp3)."""
        async with self._client() as http:
            queue = queue_for(c.provider.id, c.key, http, self._timeout, self._poll, c.base_url)
            data, ctype, result = await queue.make(
                endpoint, body, "audio", "audio/mpeg", _no_progress
            )
            if hold is not None:
                hold.update(result)
            return data, ".wav" if "wav" in ctype else ".mp3"

    async def _cheapest[T](
        self, route: KeyRoute, product: str, job: dict[str, Any],
        attempt: Callable[[KeyChoice], Awaitable[T]], needs: tuple[str, ...] = (),
        only: str | None = None,
    ) -> tuple[T, Priced[KeyChoice]]:  # fmt: skip
        try:
            return await on_cheapest(route, product, job, attempt, self._usage, needs, only)
        except FalError as e:
            raise VoiceEngineError(e.code, e.message) from None
        except TimeoutError:
            raise VoiceEngineError(
                "provider_refused", f"{route.provider.title} took too long."
            ) from None

    async def _wav(self, data: bytes, ext: str, used: Priced[KeyChoice]) -> bytes:
        unread = VoiceEngineError(
            "engine_failed",
            f"{used.choice.provider.title} sent the speech in a form this app cannot read.",
        )
        try:
            wav = data if ext == ".wav" and data[:4] == b"RIFF" else await to_wav(data, ext)
        except VoiceEngineError:
            raise unread from None
        if _wav_seconds(wav) <= 0:
            raise unread
        return wav

    async def _send(self, c: KeyChoice, data: bytes, name: str) -> str:
        """A recording up to the provider first: its address, or Runware's upload id."""
        async with self._client() as http:
            queue = queue_for(c.provider.id, c.key, http, self._timeout, self._poll, c.base_url)
            return await queue.upload(data, name)

    def _kept(self) -> Any:
        """Where MiniMax's voices are remembered (the person's settings; none on the web)."""
        return self._keys if hasattr(self._keys, "kept_voice") else None

    async def _kept_route(
        self, route: KeyRoute, kind: str, made_from: bytes
    ) -> tuple[KeyRoute, str] | None:
        """A MiniMax voice made before from the same recording or words, on a provider with a key:
        a route to MiniMax Speech there (priced per character) and the voice's id; else None."""
        from wasifyai_api.own_keys_catalogue import media_model

        kept, key = self._kept(), voice_key(kind, made_from)
        speech = media_model("voice", "minimax-speech-2.8-hd")
        if kept is None or speech is None:
            return None
        for c in route.offers():
            voice_id = await kept.kept_voice(key, c.provider.id)
            there = speech.offer_of(c.provider.id)
            if voice_id and there is not None:
                choice = KeyChoice(c.provider, c.key, c.base_url, there)
                again = KeyRoute(
                    c.provider, speech.model, c.key, c.base_url, (choice,), speech.title
                )
                return again, voice_id
        return None

    async def _made_voice(
        self, route: KeyRoute, kind: str, made_from: bytes, text: str,
        make: Callable[[KeyChoice, str], Awaitable[dict[str, Any]]],
    ) -> tuple[tuple[bytes, str], Priced[KeyChoice]]:  # fmt: skip
        """A MiniMax voice: one made before speaks again where it was made, priced per character;
        otherwise it is made now (which says `text` too) and remembered by what made it."""
        again = await self._kept_route(route, kind, made_from)
        if again is not None:
            speech_route, voice_id = again

            async def speak(c: KeyChoice) -> tuple[bytes, str]:
                body = speak_request(
                    "minimax-speech-2.8-hd", c.provider.id, c.offer.endpoint, text, voice_id, None
                )
                return await self._audio(c, c.offer.endpoint, body)

            return await self._cheapest(
                speech_route, "voiceclone", {"characters": len(text)}, speak
            )
        kept = self._kept()

        async def attempt(c: KeyChoice) -> tuple[bytes, str]:
            asked, result = new_voice_id(), {}
            body = await make(c, asked)
            made = await self._audio(c, c.offer.endpoint_for(kind), body, hold=result)
            if kept is not None:
                await kept.keep_voice(
                    voice_key(kind, made_from), c.provider.id, made_voice(result, asked)
                )
            return made

        job = {"characters": len(text), "task": kind}
        return await self._cheapest(route, "voiceclone", job, attempt, (kind,))

    async def clone(
        self, model: VoiceModel, text: str, reference: Path, reference_text: str | None,
        options: dict[str, Any],
    ) -> SpeechResult:  # fmt: skip
        if model.id != KEYED_CLONE:
            return await self._local.clone(model, text, reference, reference_text, options)  # type: ignore[no-any-return]
        route = await self._route("voiceclone")
        model_id = _model_id("voiceclone", route)
        recording = await asyncio.to_thread(reference.read_bytes)
        t0 = time.monotonic()

        async def make(c: KeyChoice, voice_id: str) -> dict[str, Any]:
            sent = await self._send(c, recording, reference.name)
            endpoint = c.offer.endpoint_for("clone")
            return clone_request(
                model_id, c.provider.id, endpoint, text, sent, reference_text, voice_id
            )

        async def attempt(c: KeyChoice) -> tuple[bytes, str]:
            return await self._audio(c, c.offer.endpoint_for("clone"), await make(c, ""))

        if model_id == "minimax-voice":
            (data, ext), used = await self._made_voice(route, "clone", recording, text, make)
        else:
            job = {"characters": len(text), "task": "clone"}
            (data, ext), used = await self._cheapest(route, "voiceclone", job, attempt, ("clone",))
        wav = await self._wav(data, ext, used)
        return SpeechResult(
            wav, _wav_rate(wav) or model.sample_rate, _wav_seconds(wav), used.offer.endpoint,
            None, 0.0, time.monotonic() - t0,
        )  # fmt: skip

    async def design(
        self, model: VoiceModel, text: str, description: str, options: dict[str, Any]
    ) -> SpeechResult:
        if model.id != KEYED_CLONE:
            return await self._local.design(model, text, description, options)  # type: ignore[no-any-return]
        route = await self._route("voiceclone")
        model_id = _model_id("voiceclone", route)
        t0 = time.monotonic()

        async def make(c: KeyChoice, voice_id: str) -> dict[str, Any]:
            return design_request(model_id, c.provider.id, text, description, voice_id)

        async def attempt(c: KeyChoice) -> tuple[bytes, str]:
            return await self._audio(c, c.offer.endpoint_for("design"), await make(c, ""))

        if model_id == "minimax-voice":
            (data, ext), used = await self._made_voice(
                route, "design", description.encode(), text, make
            )
        else:
            job = {"characters": len(text), "task": "design"}
            (data, ext), used = await self._cheapest(route, "voiceclone", job, attempt, ("design",))
        wav = await self._wav(data, ext, used)
        return SpeechResult(
            wav, _wav_rate(wav) or model.sample_rate, _wav_seconds(wav), used.offer.endpoint,
            None, 0.0, time.monotonic() - t0,
        )  # fmt: skip

    async def transcribe(
        self, model: VoiceModel, wav: bytes, options: dict[str, Any], *, beside: bool = False
    ) -> TranscriptResult:
        if model.id != KEYED_TRANSCRIBE:
            return await self._local.transcribe(model, wav, options, beside=beside)  # type: ignore[no-any-return]
        route = await self._route("transcribe")
        model_id = _model_id("transcribe", route)
        language = options.get("language")
        language = str(language) if language else None
        t0 = time.monotonic()

        async def attempt(c: KeyChoice) -> dict[str, Any]:
            sent = await self._send(c, wav, "speech.wav")
            body = transcribe_request(model_id, c.provider.id, sent, language)
            async with self._client() as http:
                queue = queue_for(c.provider.id, c.key, http, self._timeout, self._poll, c.base_url)
                return await queue.call(c.offer.endpoint, body, _no_progress)

        result, used = await self._cheapest(
            route, "transcribe", {"seconds": max(_wav_seconds(wav), 1.0)}, attempt
        )
        text, segments, seconds = transcript_of(result)
        return TranscriptResult(
            text,
            segments,
            seconds or _wav_seconds(wav),
            used.offer.endpoint,
            time.monotonic() - t0,
        )

    async def convert(
        self, model: VoiceModel, req: ConvertRequest, source: Path, reference: Path
    ) -> SpeechResult:
        if model.id != KEYED_CHANGE:
            return await self._local.convert(model, req, source, reference)  # type: ignore[no-any-return]
        route = await self._route("voicechange")
        said, voice = (
            await asyncio.to_thread(source.read_bytes),
            await asyncio.to_thread(reference.read_bytes),
        )
        t0 = time.monotonic()

        async def attempt(c: KeyChoice) -> tuple[bytes, str]:
            body = convert_request(
                c.provider.id,
                await self._send(c, said, source.name),
                await self._send(c, voice, reference.name),
            )
            return await self._audio(c, c.offer.endpoint, body)

        (data, ext), used = await self._cheapest(
            route, "voicechange", {"seconds": req.source_seconds}, attempt
        )
        wav = await self._wav(data, ext, used)
        return SpeechResult(
            wav, _wav_rate(wav) or model.sample_rate, _wav_seconds(wav), used.offer.endpoint,
            None, 0.0, time.monotonic() - t0,
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
        product = MUSIC_PRODUCTS[model.id]
        route = await self._route(product)
        model_id = _model_id(product, route)
        verb = music_verb(model_id, req)
        t0 = time.monotonic()

        async def attempt(c: KeyChoice) -> tuple[bytes, str, dict[str, Any]]:
            endpoint = c.offer.endpoint_for(verb)
            body = music_body(endpoint, req)
            async with self._client() as http:
                queue = queue_for(c.provider.id, c.key, http, self._timeout, self._poll, c.base_url)
                return await queue.make(endpoint, body, "audio", "audio/mpeg", _no_progress)

        (data, ctype, result), used = await self._cheapest(route, product, music_job(req), attempt)
        wav = await self._wav(data, ".wav" if "wav" in ctype else ".mp3", used)
        return MusicResult(
            wav, _wav_rate(wav) or model.sample_rate, _wav_seconds(wav),
            used.offer.endpoint_for(verb),
            result.get("seed") if isinstance(result.get("seed"), int) else None, 0.0,
            time.monotonic() - t0,
        )  # fmt: skip

    async def music_edit(
        self, model: VoiceModel, req: MusicEditRequest, source: Path
    ) -> MusicResult:
        """A stretch of a clip written again on a cloud model (ADR-0100, CP8): the clip goes up the
        provider's way first."""
        if model.id != KEYED_MUSICEDIT:
            return await self._local.music_edit(model, req, source)  # type: ignore[no-any-return]
        route = await self._route("musicedit")
        clip = await asyncio.to_thread(source.read_bytes)
        t0 = time.monotonic()

        async def attempt(c: KeyChoice) -> tuple[bytes, str]:
            sent = await self._send(c, clip, source.name)
            body = edit_body(c.offer.endpoint, c.provider.id, sent, req)
            return await self._audio(c, c.offer.endpoint, body)

        (data, ext), used = await self._cheapest(route, "musicedit", edit_job(req), attempt)
        wav = await self._wav(data, ext, used)
        return MusicResult(
            wav, _wav_rate(wav) or model.sample_rate, _wav_seconds(wav), used.offer.endpoint,
            None, 0.0, time.monotonic() - t0,
        )  # fmt: skip

    async def separate(
        self, model: VoiceModel, req: SeparateRequest, source: Path
    ) -> SeparateResult:
        """A recording taken apart into stems on a cloud model (ADR-0100, CP8): each stem the
        provider answers is fetched and read as a WAV."""
        if model.id != KEYED_SPLIT:
            return await self._local.separate(model, req, source)  # type: ignore[no-any-return]
        route = await self._route("split")
        model_id = _model_id("split", route)
        if model_id not in SPLIT_MODELS:
            raise VoiceEngineError("not_with_key", f"{route.model} does not split music here.")
        recording = await asyncio.to_thread(source.read_bytes)
        t0 = time.monotonic()

        async def attempt(c: KeyChoice) -> list[tuple[str, bytes, str]]:
            if (model_id, c.provider.id) in MP3_ONLY:  # it cannot read a WAV (CP13)
                sent = await self._send(c, await to_mp3(recording, source.suffix), "song.mp3")
            else:
                sent = await self._send(c, recording, source.name)
            body = split_body(model_id, c.provider.id, sent)
            async with self._client() as http:
                queue = queue_for(c.provider.id, c.key, http, self._timeout, self._poll, c.base_url)
                result = await queue.call(c.offer.endpoint, body, _no_progress)
                files = []
                if isinstance(result.get("zip_url"), str):  # Mureka on fal.ai: one zip (CP13)
                    data, _ = await fetch_file(http, c.provider.title, result["zip_url"],
                                               "application/zip", self._timeout)  # fmt: skip
                    return stems_in_zip(model_id, data)
                for name, where in stems_of(model_id, result):
                    url = where.get("url") if isinstance(where, dict) else where
                    data, ctype = await fetch_file(http, c.provider.title, url, "audio/wav",
                                                   self._timeout)  # fmt: skip
                    files.append((name, data, ".wav" if "wav" in ctype else ".mp3"))
                return files

        job = {"seconds": req.source_seconds}
        files, used = await self._cheapest(route, "split", job, attempt)
        stems = []
        for name, data, ext in files:
            wav = await self._wav(data, ext, used)
            stems.append(Stem(name, wav, _wav_rate(wav) or model.sample_rate, _wav_seconds(wav)))
        if not stems:
            raise VoiceEngineError(
                "engine_failed", f"{used.choice.provider.title} sent no parts back."
            )
        return SeparateResult(tuple(stems), used.offer.endpoint, 0.0, time.monotonic() - t0)

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
            async with self._client() as http:
                queue = queue_for(
                    c.provider.id, c.key, http, max(self._timeout, 3600.0), self._poll, c.base_url
                )
                # the picture and the voice go up first (fal.ai refuses a voice inside the request,
                # "URL too long"; WaveSpeed takes addresses; Runware a voice by its upload id)
                face, said = (
                    await queue.upload(image, "face.png"),
                    await queue.upload(audio, voice.name),
                )
                body = lipsync_body(model_id, c.offer.endpoint, face, said, req, c.provider.id)
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


RUNWARE_3D = "3dInference"  # Runware's task for a model from pictures (CP13: its name)
GLB = "model/gltf-binary"


def model3d_body(
    model_id: str, provider: str, picture: str, seed: int, detail: str
) -> tuple[dict[str, Any], str]:
    """What a 3D model is sent for a picture (an address, an upload id, or a data URI on Runware)
    and the field of the answer that holds the model (ADR-0100, CP9; CP0 for Runware's and
    WaveSpeed's fields; the ones marked CP13 are checked in the real run)."""
    texture = ATLAS.get(detail, 2048)
    if provider == "runware":
        task: dict[str, Any] = {
            "taskType": RUNWARE_3D, "inputs": {"images": [picture]}, "outputFormat": "GLB",
            "includeCost": True,
        }  # fmt: skip
        if model_id == "trellis-2":  # one picture, and a seed (CP13)
            task["inputs"] = {"image": picture}
            task["seed"] = seed
            task["settings"] = {"resolution": FAL_3D_RESOLUTION}
        return task, ""  # Hunyuan3D takes no seed on Runware (CP13)
    if provider == "wavespeed":  # TRELLIS 2: it cuts the picture out itself
        return {
            "image": picture, "resolution": FAL_3D_RESOLUTION, "texture_size": texture,
            "remove_background": True, "seed": seed,
        }, ""  # fmt: skip
    # fal.ai: Hunyuan3D, the one 3D model it has here (Pixal3D's address there has no model, CP13)
    return {"input_image_url": picture, "seed": seed}, "model_glb"


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
        return _cloud(self._keys, "model3d") is not None

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

    async def _fal_run(
        self, c: KeyChoice, picture: bytes, body: dict[str, Any], endpoint: str, field: str,
        on_progress: Callable[[float], Any] = _no_progress,
    ) -> bytes:  # fmt: skip
        """`body` on fal.ai with `picture` as its `image_url`, uploaded to fal.ai's file store first
        (a picture inside the request can be refused as too long, as a voice was)."""
        async with self._client() as http:
            fal = FalQueue(c.key, http, self._timeout, self._poll, c.base_url)
            sent = {"image_url": await fal.upload(picture, "picture.png"), **body}
            result = await fal.call(endpoint, sent, on_progress)
            data, _ = await fal.fetch(result.get(field), "application/octet-stream")
            return data

    async def _done(self, run: Awaitable[bytes], out: Path, t0: float, title: str) -> RunResult:
        try:
            data = await run
        except FalError as e:
            return RunResult(False, "failed", e.message, time.monotonic() - t0)
        except TimeoutError:
            return RunResult(False, "wall_time", f"{title} took too long.", time.monotonic() - t0)
        await asyncio.to_thread(out.write_bytes, data)
        return RunResult(True, None, "", time.monotonic() - t0, output=out)

    async def matte(
        self,
        picture: Path,
        out_dir: Path,
        on_line: Callable[[str], None] | None = None,
        **again: Any,  # job_key, resume: the web's engine workers pick a job up again
    ) -> RunResult:
        route = _cloud(self._keys, "model3d")
        if route is None:
            return await self._local.matte(picture, out_dir, on_line, **again)
        t0, out = time.monotonic(), out_dir / "keyed_cutout.png"
        data = await asyncio.to_thread(picture.read_bytes)
        fal = next((c for c in route.offers() if c.provider.id == "fal"), None)
        if fal is None:  # the cloud models cut the picture out themselves: it goes as it is
            await asyncio.to_thread(out.write_bytes, data)
            return RunResult(True, None, "", time.monotonic() - t0, output=out)
        # a helper on the same key: not the model, not priced
        body = {"output_format": "png"}
        return await self._done(
            self._fal_run(fal, data, body, FAL_MATTE, "image"), out, t0, "fal.ai"
        )

    async def generate(
        self,
        cutout: Path,
        out_glb: Path,
        *,
        seed: int = 42,
        detail: str = "standard",
        on_line: Callable[[str], None] | None = None,
        on_progress: Callable[[float, str], None] | None = None,
        **again: Any,  # job_key, resume: on a cloud model a run picked up again is made again
    ) -> RunResult:
        route = _cloud(self._keys, "model3d")
        if route is None:
            return await self._local.generate(
                cutout, out_glb, seed=seed, detail=detail, on_line=on_line,
                on_progress=on_progress, **again,
            )  # fmt: skip
        data = await asyncio.to_thread(cutout.read_bytes)
        model_id = _model_id("model3d", route)
        t0 = time.monotonic()

        async def attempt(c: KeyChoice) -> bytes:
            title = c.provider.title

            async def told(p: float) -> None:
                if on_progress is not None:
                    on_progress(p, f"Waiting for {title}" if p < 0.1 else f"Making it on {title}")

            if c.provider.id == "fal":
                body, field = model3d_body(model_id, "fal", "", seed, detail)
                async with self._client() as http:
                    fal = FalQueue(c.key, http, self._timeout, self._poll, c.base_url)
                    body["input_image_url"] = await fal.upload(data, "picture.png")
                    result = await fal.call(c.offer.endpoint, body, told)
                    got, _ = await fal.fetch(result.get(field), GLB)
                    return got
            async with self._client() as http:
                queue = queue_for(c.provider.id, c.key, http, self._timeout, self._poll, c.base_url)
                sent = data_uri(data) if c.provider.id == "runware" else (
                    await queue.upload(data, "picture.png")
                )  # fmt: skip
                body, field = model3d_body(model_id, c.provider.id, sent, seed, detail)
                got, _, _ = await queue.make(c.offer.endpoint, body, field, GLB, told)
                return got

        async def run() -> bytes:
            got, _ = await on_cheapest(route, "model3d", {}, attempt, self._usage)
            return got

        return await self._done(run(), out_glb, t0, route.provider.title)
