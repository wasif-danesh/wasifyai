"""Every speech capability once, through the whole web path: the API's `RemoteSpeechEngine`, Redis,
an engine worker, its models, storage and back (ADR-0087). Run it with the stack up (`make dev`) and
a worker running:

    uv run python scripts/worker_smoke.py             # every capability with a ready model
    uv run python scripts/worker_smoke.py speak music   # only these

Capabilities with no ready model are skipped and said so. Nothing is kept."""

import asyncio
import io
import os
import sys
import time
import wave
from pathlib import Path

from redis.asyncio import Redis
from wasifyai_api.desktop_models import load_catalogue
from wasifyai_api.remote_speech import RemoteSpeechEngine
from wasifyai_platform_sdk import EngineQueue, RunContext, s3_storage, set_context
from wasifyai_platform_sdk.uploads import process_image
from wasifyai_platform_sdk.voice_models import (
    check_convert,
    check_lipsync,
    check_music,
    check_music_edit,
    check_separate,
    check_speech_edit,
)
from wasifyai_voice import audio_input

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "docs" / "listening" / "samples"
PICTURE = ROOT / "products" / "wasifyai-voice" / "wasifyai_voice" / "fixtures" / "person.jpg"
SENTENCE = "The quick brown fox jumps over the lazy dog."


def seconds(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


def env(key: str, default: str = "") -> str:
    if not os.environ.get(key) and (ROOT / ".env").is_file():
        for line in (ROOT / ".env").read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return os.environ.get(key, default)


async def main(only: set[str]) -> int:
    redis = Redis.from_url(
        os.environ.get("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
    )
    storage = s3_storage(
        bucket=env("STORAGE_BUCKET", "wasifyai"),
        endpoint=os.environ.get("STORAGE_ENDPOINT", "http://localhost:8333"),
        access_key=env("STORAGE_ACCESS_KEY"),
        secret_key=env("STORAGE_SECRET_KEY"),
    )
    catalogue = {
        e.id: e.voice for e in load_catalogue(ROOT / "products", ["wasifyai-voice"]) if e.voice
    }
    engine = RemoteSpeechEngine(EngineQueue(redis), storage, catalogue)
    await engine.refresh()
    if not engine._workers:  # noqa: SLF001
        print("no engine worker is running (scripts/worker.sh start)")
        return 2
    set_context(RunContext("smoke-tenant", "wasifyai-voice", "smoke-user"))
    ready = {m["id"] for m in engine.models() if m["state"] == "ready"}
    results: list[tuple[str, str, str]] = []
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "worker-smoke"
    tmp.mkdir(exist_ok=True)

    async def step(name: str, model_id: str, run):
        if only and name not in only:
            return None
        if model_id not in ready:
            results.append((name, "skipped", f"{model_id} is not ready on a worker"))
            return None
        t0 = time.monotonic()
        try:
            out = await run(catalogue[model_id])
            results.append((name, "ok", f"{model_id}, {time.monotonic() - t0:.1f} s"))
            return out
        except Exception as e:  # report and go on
            results.append((name, "FAILED", f"{model_id}: {e}"))
            return None

    speech = await step("speak", "kokoro-82m", lambda m: engine.speak(m, SENTENCE, None, {}))
    wav = speech.wav if speech else (SAMPLES / "dub-source-english.wav").read_bytes()
    source = tmp / "source.wav"
    source.write_bytes(wav)
    reference = SAMPLES / "speech-clone-reference.wav"

    heard = await step(
        "transcribe", "parakeet-tdt-0.6b-v3", lambda m: engine.transcribe(m, wav, {})
    )
    if heard:
        results[-1] = (*results[-1][:2], results[-1][2] + f", heard: {heard.text!r}")

    async def convert(m):
        rate = int(m.convert["input_rate"])  # the product prepares recordings like this
        clip, secs = await audio_input.at_rate(wav, "a.wav", rate, 1)
        ref, ref_secs = await audio_input.at_rate(reference.read_bytes(), "r.wav", rate, 1)
        (tmp / "c.wav").write_bytes(clip)
        (tmp / "r.wav").write_bytes(ref)
        req = check_convert(m, secs, ref_secs, None)
        return await engine.convert(m, req, tmp / "c.wav", tmp / "r.wav")

    await step("convert", "tone-color-vc", convert)

    async def edit(m):
        clip, secs = await audio_input.at_rate(wav, "a.wav", int(m.speech_edit["input_rate"]), 1)
        (tmp / "e.wav").write_bytes(clip)
        req = check_speech_edit(m, secs, SENTENCE, SENTENCE.replace("lazy", "sleepy"), None)
        return await engine.speech_edit(m, req, tmp / "e.wav")

    await step("speech_edit", "dots-tts-edit", edit)

    async def split(m):
        data = (SAMPLES / "music-ace-instrumental.wav").read_bytes()
        clip, secs = await audio_input.at_rate(data, "m.wav", int(m.separate["input_rate"]), 2)
        (tmp / "m.wav").write_bytes(clip)
        return await engine.separate(m, check_separate(m, secs, None), tmp / "m.wav")

    stems = await step("separate", "htdemucs", split)
    if stems:
        results[-1] = (
            *results[-1][:2],
            results[-1][2] + f", stems: {[s.name for s in stems.stems]}",
        )

    async def song(m):
        req = check_music(m, "song", "a calm piano melody", None, True, 15.0, None, 1)
        return await engine.music(m, req)

    made = await step("music", "ace-step-1.5-turbo", song)
    if made:
        clip = tmp / "song.wav"
        clip.write_bytes(made.wav)

        async def music_edit(m):
            req = check_music_edit(
                m, "repaint", "a brighter piano", made.seconds, [(3.0, 8.0)], None, None, None, 2
            )
            return await engine.music_edit(m, req, clip)

        await step("music_edit", "ace-step-1.5-turbo", music_edit)

    async def design(m):
        return await engine.design(m, SENTENCE, "a warm, slow older man", {})

    await step("design", "voxcpm2", design)

    async def clone(m):
        return await engine.clone(m, "Same voice, other words.", reference, SENTENCE, {})

    await step("clone", "voxcpm2", clone)

    async def lipsync(m):
        voice, secs = await audio_input.at_rate(wav, "v.wav", 16000, 1)
        (tmp / "v.wav").write_bytes(voice)
        (tmp / "p.png").write_bytes(process_image(PICTURE.read_bytes(), 1024).png)
        req = check_lipsync(m, secs, "drawn", "generated")
        return await engine.lipsync(m, req, tmp / "p.png", tmp / "v.wav")

    video = await step("lipsync", "musetalk-v15", lipsync)
    if video:
        results[-1] = (
            *results[-1][:2],
            results[-1][2] + f", {video.width}x{video.height}, {video.seconds:.1f} s",
        )

    await redis.aclose()
    width = max(len(n) for n, _, _ in results)
    for name, state, detail in results:
        print(f"{name:<{width}}  {state:<8} {detail}")
    return 1 if any(s == "FAILED" for _, s, _ in results) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(set(sys.argv[1:]))))
