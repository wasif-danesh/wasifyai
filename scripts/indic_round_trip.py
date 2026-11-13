"""The Indian-language speech engine, checked by hand (docs/voice-languages-plan.md, L8): every
language Indic Parler-TTS and IndicConformer claim is spoken by each of its speakers, written back,
and compared with what was asked (word error rate). Real models through the real engine; nothing is
faked. The WAVs are kept for a listener.

    uv run python -I scripts/indic_round_trip.py DATA_DIR MODELS_DIR [OUT_DIR]

DATA_DIR holds the engine (set up here if it is not, after the size is shown); MODELS_DIR holds the
models' files as Models lays them out (`indic/<name>`), for example the app's own models folder."""

import asyncio
import json
import sys
import unicodedata
from pathlib import Path

from wasifyai_api.audio_runtime import AudioEngine, AudioInstaller, AudioServer
from wasifyai_api.desktop_models import ModelsService, load_catalogue
from wasifyai_api.indic_runtime import IndicSidecar
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_platform_sdk import languages

ROOT = Path(__file__).resolve().parents[1]
LINES = {
    "bn": "আজ আবহাওয়া খুব সুন্দর, তাই আমরা পার্কে হাঁটতে যাব।",
    "hi": "आज मौसम बहुत अच्छा है, इसलिए हम पार्क में टहलने जाएंगे।",
    "mr": "आज हवामान खूप छान आहे, म्हणून आम्ही बागेत फिरायला जाणार आहोत.",
    "te": "ఈ రోజు వాతావరణం చాలా బాగుంది, కాబట్టి మేము పార్కులో నడవడానికి వెళ్తాము.",
    "ta": "இன்று வானிலை மிகவும் நன்றாக இருக்கிறது, அதனால் நாங்கள் பூங்காவில் நடக்கப் போகிறோம்.",
    "gu": "આજે હવામાન ખૂબ સરસ છે, તેથી અમે બગીચામાં ફરવા જઈશું.",
}
MAX_WER = 0.35  # a line written back worse than this is reported as a failure


def words(s: str) -> list[str]:
    s = unicodedata.normalize("NFC", s)
    keep = (c if unicodedata.category(c)[0] in "LM" or c.isspace() else " " for c in s)
    return "".join(keep).split()


def wer(ref: str, hyp: str) -> float:
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
    return d[len(h)] / max(1, len(r))


async def main(data: Path, models_dir: Path, out: Path) -> int:
    side = IndicSidecar(data)
    if not side.installed:
        plan = side.installer.plan()
        print(f"setting up the engine: {plan['bytes'] / 1e9:.1f} GB of packages", flush=True)
        side.installer.start(side.installer.total_bytes)
        await side.installer.wait()
        if not side.installed:
            print("the engine did not install:", side.installer.progress.public())
            return 1
    catalogue = load_catalogue(ROOT / "products", ["wasifyai-voice"])
    models = ModelsService(catalogue, models_dir, [], InMemorySettingsStore())
    engine = AudioEngine(data, models, AudioInstaller(data), AudioServer(data), indic=side)
    rows, failed = [], 0
    try:
        speaker = engine.resolve("speak", "indic-parler-tts")
        writer = engine.resolve("transcribe", "indic-conformer-600m")
        for code, text in LINES.items():
            for voice in languages.voices_for(speaker, code):
                said = await engine.speak(speaker, text, voice, {"seed": 7})
                name = f"{code}-{voice.lower()}.wav"
                (out / name).write_bytes(said.wav)
                heard = await engine.transcribe(writer, said.wav, {"language": code})
                score = round(wer(text, heard.text), 2)
                failed += score > MAX_WER
                row = {"language": code, "voice": voice, "file": name, "wer": score,
                       "seconds": round(said.seconds, 1), "took_s": round(said.elapsed_s, 1),
                       "heard": heard.text}  # fmt: skip
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        await side.close()
    (out / "round-trip.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"{len(rows) - failed} of {len(rows)} lines came back within {MAX_WER:.0%} word error")
    return 1 if failed else 0


if __name__ == "__main__":
    args = [Path(a) for a in sys.argv[1:]]
    if len(args) < 2:
        print(__doc__)
        sys.exit(2)
    out_dir = args[2] if len(args) > 2 else Path("indic-out")
    out_dir.mkdir(parents=True, exist_ok=True)
    sys.exit(asyncio.run(main(args[0], args[1], out_dir)))
