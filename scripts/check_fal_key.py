"""One small thing per product on fal.ai with the person's key
(`docs/own-keys-fal-everywhere-plan.md`, stage F5). Without `--real` it runs against a fake
fal.ai, so it can be checked with no key and no cost.

Speech, music, sound effects and lip sync go through the app's own `KeyedSpeechEngine`; text through
the app's own `text_client` (fal.ai's OpenAI-compatible route); pictures, video and 3D through
fal.ai's queue with the endpoints the app uses.

    uv run --package wasifyai-api python scripts/check_fal_key.py --out /tmp/fal-check
    uv run --package wasifyai-api python scripts/check_fal_key.py --real --out /tmp/fal-check \\
        --picture face.png --voice voice.wav [--only text music ...]

With `--real` the key is read from the app's keychain (the first fal.ai key saved in Settings ›
Your keys: `keys.<product>.fal`), else from `FAL_KEY`. It is never printed. Results go to
`<out>/check.json` and the files beside it. About $5 with `--real` and everything (see the plan).
"""

import argparse
import asyncio
import io
import json
import os
import sys
import time
import wave
from pathlib import Path
from typing import Any

import httpx
from PIL import Image
from wasifyai_api.own_keys import PROVIDERS, OwnKeysService, Provider, Tried, text_client
from wasifyai_api.own_keys_engines import KeyedSpeechEngine
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_platform_sdk import InMemorySecretStore, check_lipsync, check_music
from wasifyai_platform_sdk.fal import FalError, FalQueue, data_uri

PRODUCTS = ("text", "images", "video", "speech", "music", "song", "sfx", "model3d", "lipsync")
TEXT_MODEL = "google/gemini-2.5-flash"
LIPSYNC_MODEL = "veed/fabric-1.0/fast"
KEYCHAIN = "Wasify AI"
KEY_NAMES = ("voice", "music", "sfx", "lipsync", "images", "video", "model3d", "chat")


def a_wav(seconds: float, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def a_png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (512, 512), (120, 90, 80)).save(out, "PNG")
    return out.getvalue()


def an_mp4(w: int, h: int) -> bytes:
    tkhd = bytes([0]) + b"\0\0\0" + b"\0" * 20 + b"\0" * 52
    tkhd += (w << 16).to_bytes(4, "big") + (h << 16).to_bytes(4, "big")
    return b"\x00\x00\x00\x18ftypmp42" + b"\x00\x00\x00\x5ctkhd" + tkhd + b"\0" * 8


class FakeFal:
    """fal.ai's queue and its file host: every endpoint answers something of the right kind."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if req.method == "POST" and "/chat/completions" in url:
            return httpx.Response(200, json={
                "id": "c", "object": "chat.completion", "created": 0, "model": TEXT_MODEL,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "Blue."}}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 1, "total_tokens": 10},
            })  # fmt: skip
        if "/storage/auth/token" in url:
            return httpx.Response(200, json={"token": "t", "token_type": "Bearer"})
        if url.endswith("/files/upload"):
            return httpx.Response(200, json={"access_url": "https://v3.fal.media/files/in"})
        if req.method == "POST":
            endpoint = url.split("queue.fal.run/", 1)[1]
            self.asked.append(endpoint)
            q = f"https://queue.fal.run/{endpoint}/requests/r{len(self.asked)}"
            return httpx.Response(200, json={"status_url": f"{q}/status", "response_url": q})
        if url.endswith("/status"):
            return httpx.Response(200, json={"status": "COMPLETED"})
        if url.startswith("https://queue.fal.run"):
            endpoint = url.split("queue.fal.run/", 1)[1].split("/requests/", 1)[0]
            return httpx.Response(200, json=self._result(endpoint))
        name = url.rsplit("/", 1)[1]
        body = {
            "wav": a_wav(2.0, 44100),
            "png": a_png(),
            "glb": b"glTF\x02\x00\x00\x00MODEL",
            "mp4": an_mp4(720, 720),
        }[name.rsplit(".", 1)[1]]
        return httpx.Response(200, content=body)

    @staticmethod
    def _result(endpoint: str) -> dict[str, Any]:
        f = "https://v3.fal.media/files/out"
        if "flux" in endpoint or "birefnet" in endpoint:
            return {
                "images": [{"url": f"{f}.png", "content_type": "image/png"}],
                "image": {"url": f"{f}.png", "content_type": "image/png"},
            }
        if "ltx" in endpoint or "fabric" in endpoint or "infinitalk" in endpoint:
            return {"video": {"url": f"{f}.mp4", "content_type": "video/mp4"}}
        if "pixal3d" in endpoint:
            return {"model_glb": {"url": f"{f}.glb"}, "model_mesh": {"url": f"{f}.glb"}}
        return {"audio": {"url": f"{f}.wav", "content_type": "audio/wav"}}

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


def the_key(real: bool) -> str:
    if not real:
        return "fake-fal-key"
    if sys.platform == "darwin":
        from wasifyai_platform_sdk.keychain_macos import Keychain

        chain = Keychain(KEYCHAIN)
        for name in KEY_NAMES:
            if key := chain.get(f"keys.{name}.fal"):
                return key
    key = os.environ.get("FAL_KEY", "")
    if not key:
        sys.exit("No fal.ai key: save one in Settings > Your keys, or set FAL_KEY.")
    return key


class NotHere:
    """This computer's speech engine, which the check never uses."""

    def models(self, task: Any = None) -> list[dict[str, Any]]:
        return []

    def resolve(self, task: str, model_id: str | None) -> Any:
        raise RuntimeError(f"{task} was asked of this computer")


async def accept(provider: Provider, model: str, key: str, base: str) -> Tried:
    return Tried(True, 1)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--real", action="store_true", help="call fal.ai itself (costs money)")
    ap.add_argument("--picture", type=Path, help="a face for lip sync (a plain square otherwise)")
    ap.add_argument("--voice", type=Path, help="a WAV voice for lip sync (silence otherwise)")
    ap.add_argument("--only", nargs="+", choices=PRODUCTS)
    ap.add_argument("--lipsync-model", default=LIPSYNC_MODEL, help="the fal.ai lip sync endpoint")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    key = the_key(a.real)
    fake = None if a.real else FakeFal()
    client = httpx.AsyncClient if fake is None else fake.client
    keys = OwnKeysService(
        InMemorySettingsStore(), InMemorySecretStore(), {"text": accept, "media": accept}
    )
    engine = KeyedSpeechEngine(NotHere(), keys, client, timeout_s=1800, poll_s=2 if a.real else 0)
    picture = a.picture.read_bytes() if a.picture else a_png()
    voice = a.voice.read_bytes() if a.voice else a_wav(5.0)
    report: list[dict[str, Any]] = []

    async def fal_call(endpoint: str, body: dict[str, Any], field: str, ext: str) -> bytes:
        async with client() as http:
            queue = FalQueue(key, http, 1800, 2 if a.real else 0)
            res = await queue.call(endpoint, body, lambda _p: asyncio.sleep(0))
            item = res.get(field)
            item = item[0] if isinstance(item, list) else item
            data, _ = await queue.fetch(item, ext)
            return data

    async def text() -> tuple[str, bytes]:
        v = PROVIDERS["fal"]
        kw: dict[str, Any] = {"max_retries": 0}
        if fake is not None:
            kw["http_client"] = fake.client()
        chat = text_client(v, v.text_url, key, **kw)
        r = await chat.chat.completions.create(
            model=TEXT_MODEL, max_tokens=20,
            messages=[{"role": "user", "content": "What colour is a clear daytime sky? One word."}],
        )  # fmt: skip
        return "txt", (r.choices[0].message.content or "").encode()

    async def images() -> tuple[str, bytes]:
        body = {"prompt": "A red apple on a wooden table, soft daylight", "num_images": 1}
        return "png", await fal_call("fal-ai/flux-2", body, "images", "image/png")

    async def video() -> tuple[str, bytes]:
        body = {"prompt": "Waves rolling onto a sandy beach at sunset", "duration": 6}
        return "mp4", await fal_call("fal-ai/ltx-2/text-to-video/fast", body, "video", "video/mp4")

    async def model3d() -> tuple[str, bytes]:
        body = {"image_url": data_uri(a_png()), "resolution": 1024}
        return "glb", await fal_call("fal-ai/pixal3d", body, "model_glb", "model/gltf-binary")

    async def speech() -> tuple[str, bytes]:
        await keys.save_key("voice", "fal", key)
        await keys.use("voice", "fal", "fal-ai/kokoro")
        model = engine.resolve("speak", None)
        res = await engine.speak(model, "Hello from Wasify AI.", None, {})
        return "wav", res.wav

    async def music_on(product: str, endpoint: str, *ask: Any) -> tuple[str, bytes]:
        await keys.save_key(product, "fal", key)
        await keys.use(product, "fal", endpoint)
        model = engine.resolve("music", f"key:{product}")
        res = await engine.music(model, check_music(model, *ask))
        return "wav", res.wav

    async def lipsync() -> tuple[str, bytes]:
        await keys.save_key("lipsync", "fal", key)
        await keys.use("lipsync", "fal", a.lipsync_model)
        model = engine.resolve("lipsync", None)
        with Image.open(io.BytesIO(picture)) as im:
            size = im.size
        with wave.open(io.BytesIO(voice)) as w:
            seconds = min(5.0, w.getnframes() / w.getframerate())
        req = check_lipsync(model, seconds, picture=size, size=720)
        (a.out / "in-face.png").write_bytes(picture)
        (a.out / "in-voice.wav").write_bytes(voice)
        res = await engine.lipsync(model, req, a.out / "in-face.png", a.out / "in-voice.wav")
        return "mp4", res.mp4

    jobs = {
        "text": text, "images": images, "video": video, "speech": speech,
        "music": lambda: music_on("music", "fal-ai/elevenlabs/music", "song", "Calm piano",
                                  None, True, 30, None, None),
        "song": lambda: music_on("music", "fal-ai/minimax-music/v2.6", "song",
                                 "Warm city pop, female vocal, 100 BPM", None, False, None, None,
                                 None),
        "sfx": lambda: music_on("sfx", "fal-ai/elevenlabs/sound-effects/v2", "sfx",
                                "A wooden door creaks open", None, False, 5, None, None),
        "model3d": model3d, "lipsync": lipsync,
    }  # fmt: skip
    for name in a.only or PRODUCTS:
        t0 = time.monotonic()
        try:
            ext, data = await jobs[name]()
        except (FalError, Exception) as e:  # noqa: BLE001 - every failure is written down
            said = str(e).replace(key, "<key>")
            report.append({"product": name, "ok": False, "said": said[:300]})
            print(f"{name:8} failed: {said[:120]}", flush=True)
            continue
        path = a.out / f"{name}.{ext}"
        path.write_bytes(data)
        took = round(time.monotonic() - t0, 1)
        report.append(
            {"product": name, "ok": True, "s": took, "bytes": len(data), "file": str(path)}
        )
        print(f"{name:8} ok in {took} s, {len(data)} bytes", flush=True)
    (a.out / "check.json").write_text(json.dumps({"real": a.real, "results": report}, indent=2))
    return 0 if all(r["ok"] for r in report) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
