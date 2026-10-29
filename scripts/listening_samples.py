#!/usr/bin/env python3
"""Make the listening sample set (docs/listening/): one file for every voice, music, audio tool, lip sync,
dubbing and audiobook feature, made by the app's own engine on this computer, plus `manifest.json` that
`docs/listening/index.html` reads.

Run it from the repository root, with the app's environment, pointing at a data folder and the folders that
hold the models (anything a section needs and cannot find is skipped and said so):

    uv run python scripts/listening_samples.py --data-dir ~/Library/Application\\ Support/ai.wasifyai.desktop \\
        --models-dir /path/to/models [--models-dir ...] [--only speech,music] [--out docs/listening/samples]

Sections: speech, transcribe, music, tools, lipsync, dub, audiobook. Seeds are fixed, so a run can be repeated.
Nothing is downloaded and nothing leaves the computer. The samples are for listening, not for anyone else:
`docs/listening/samples/` is git-ignored."""

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = ("speech", "transcribe", "music", "tools", "lipsync", "dub", "audiobook")
SECRET = "listening-secret-listening-secret-1234"

SENTENCE = "The quick brown fox jumps over the lazy dog, and then it rests under a tall green tree."
HARD = (
    "On the 3rd of March 2026, Dr. Okafor paid $1,250.75 for 14 tickets to the 9:45 a.m. train from "
    "Edinburgh to Birmingham. Isn't that surprising? Yes, it is."
)
LYRICS = (
    "[verse]\nSunshine on the water\nSummer in the air\nWalking by the harbour\nWithout a single care\n"
    "[chorus]\nSing along with me\nLa la la la\nSing along with me\nUnder the summer stars"
)
BOOK = """# The Lighthouse

The sea was black that night. Waves climbed the rocks and fell back, again and again. The keeper lit the lamp, as he had done for forty years, and sat down to wait.

# The Boat

At dawn a small boat appeared at the foot of the cliff. Nobody was on board, and the oars were gone. The keeper walked down the long stairs to meet it.
"""


class Rig:
    def __init__(self, args: argparse.Namespace):
        import jwt  # noqa: F401  (the engine's own dependency)

        self.out = Path(args.out).resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        extra = os.pathsep.join(str(Path(p).expanduser().resolve()) for p in args.models_dir)
        env = {
            "DEPLOYMENT_PROFILE": "desktop", "DESKTOP_DATA_DIR": str(Path(args.data_dir).expanduser()),
            "DESKTOP_PUBLIC_URL": "http://127.0.0.1:48199", "API_AUTH_SECRET": SECRET, "AUTH_MODE": "jwt",
            "PRODUCTS_DIR": str(ROOT / "products"), "PRODUCTS_ENABLED": "wasifyai-voice",
            "DESKTOP_IMAGE_ENGINE": args.image_engine, "LITELLM_BASE_URL": "", "METRICS_PORT": "0",
            "DESKTOP_EXTRA_MODEL_DIRS": extra,
        }  # fmt: skip
        if args.musetalk_home:
            env["WASIFYAI_MUSETALK_HOME"] = str(Path(args.musetalk_home).expanduser())
        os.environ.update(env)
        os.environ.pop("WASIFYAI_AUDIOCPP", None)
        from fastapi.testclient import TestClient
        from wasifyai_api.config import get_settings
        from wasifyai_api.main import create_app

        get_settings.cache_clear()
        self.client = TestClient(create_app())
        self.client.__enter__()
        self.items: list[dict[str, Any]] = []
        self.skipped: list[str] = []

    def close(self) -> None:
        self.client.__exit__(None, None, None)

    # ---- the engine ----------------------------------------------------------------------

    @property
    def headers(self) -> dict[str, str]:
        import jwt

        now = int(time.time())
        token = jwt.encode(
            {"iss": "wasifyai-web", "aud": "wasifyai-api", "iat": now, "exp": now + 3600, "sub": "desktop:local"},
            SECRET, algorithm="HS256",
        )  # fmt: skip
        return {"authorization": f"Bearer {token}"}

    def get(self, path: str, **kw: Any):
        return self.client.get(path, headers=self.headers, **kw)

    def post(self, path: str, **kw: Any):
        return self.client.post(path, headers=self.headers, **kw)

    def ready(self, task: str, model_id: str) -> bool:
        ms = self.get(f"/desktop/audio/models?task={task}").json()["models"]
        return any(m["id"] == model_id and m["state"] == "ready" for m in ms)

    def run(self, **inp: Any) -> tuple[dict[str, Any], float]:
        t0 = time.time()
        r = self.post("/products/wasifyai-voice/runs", json={"input": inp})
        events = []
        for block in r.text.strip().split("\n\n"):
            lines = [ln for ln in block.split("\n") if not ln.startswith(":")]
            if len(lines) >= 3:
                events.append(
                    (lines[1].removeprefix("event: "), json.loads(lines[2].removeprefix("data: ")))
                )
        if not events:
            raise RuntimeError(f"the run answered {r.status_code}: {r.text[:200]}")
        kind, data = events[-1]
        if kind == "error":
            raise RuntimeError(f"{data.get('code')}: {data.get('message')}")
        out = data.get("outputs", {})
        if out.get("status") == "refused":
            raise RuntimeError(f"refused: {out['refusal']['message']}")
        return out, time.time() - t0

    # ---- keeping samples -----------------------------------------------------------------

    def save(self, name: str, data: bytes) -> str:
        (self.out / name).write_bytes(data)
        return name

    def add(self, section: str, id_: str, title: str, file: str, listen: str, **extra: Any) -> None:
        kind = "video" if file.endswith(".mp4") else "audio"
        self.items.append(
            {
                "section": section,
                "id": id_,
                "title": title,
                "file": file,
                "kind": kind,
                "listen": listen,
            }
            | extra
        )
        print(f"  made {file}", flush=True)

    def skip(self, why: str) -> None:
        self.skipped.append(why)
        print(f"  skipped: {why}", flush=True)

    def track_wav(self, track_id: str) -> bytes:
        return self.get(f"/products/wasifyai-voice/tracks/{track_id}/download").content

    def speech_wav(self, speech_id: str) -> bytes:
        return self.get(f"/products/wasifyai-voice/speeches/{speech_id}/download").content


class guard:
    """Skip a step that the engine refuses or that fails, and carry on with the next."""

    def __init__(self, rig: "Rig", what: str):
        self.rig, self.what = rig, what

    def __enter__(self) -> "guard":
        return self

    def __exit__(self, kind, err, tb) -> bool:
        if err is not None and isinstance(err, RuntimeError | KeyError):
            self.rig.skip(f"{self.what}: {err}")
            return True
        return False


def wav_seconds(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as w:
        return round(w.getnframes() / w.getframerate(), 1)


# ---- sections ---------------------------------------------------------------------------------


def speech(rig: Rig, ctx: dict[str, Any]) -> None:
    P = "speech"
    if not rig.ready("speak", "kokoro-82m"):
        return rig.skip("Kokoro is not on this computer")
    for voice in ("af_heart", "am_adam"):
        out, dt = rig.run(task="speak", text=SENTENCE, voice=voice, options={"seed": 1})
        wav = rig.speech_wav(out["speech_id"])
        rig.add(P, f"kokoro-{voice}", f"Kokoro, voice {voice}", rig.save(f"speech-kokoro-{voice}.wav", wav),
                "Natural pace and stress; no clipped words; no metallic or buzzing sound; the voice is the same all through.",
                model="kokoro-82m", seconds=wav_seconds(wav), work_s=round(dt, 1))  # fmt: skip
        ctx[f"speech_{voice}"] = out["speech_id"]
    out, dt = rig.run(task="speak", text=HARD, voice="af_heart", options={"seed": 1})
    rig.add(P, "kokoro-hard", "Kokoro, numbers, dates and a name", rig.save("speech-kokoro-hard.wav", rig.speech_wav(out["speech_id"])),
            "Says 'third of March twenty twenty-six', 'one thousand two hundred fifty dollars and seventy-five cents', 'nine forty-five a.m.', 'Doctor Okafor' correctly. Questions rise at the end.",
            model="kokoro-82m")  # fmt: skip
    for speed in (0.8, 1.25):
        out, _ = rig.run(
            task="speak", text=SENTENCE, voice="af_heart", options={"speed": speed, "seed": 1}
        )
        rig.add(P, f"kokoro-speed-{speed}", f"Kokoro, speed {speed}", rig.save(f"speech-kokoro-speed-{speed}.wav", rig.speech_wav(out["speech_id"])),
                "Slower or faster without sounding like a pitch-shifted recording; words stay clear.", model="kokoro-82m")  # fmt: skip
    if rig.ready("speak", "voxcpm2"):
        out, dt = rig.run(task="speak", model="voxcpm2", text=SENTENCE)
        wav = rig.speech_wav(out["speech_id"])
        rig.add(P, "voxcpm2", "VoxCPM2 (48 kHz)", rig.save("speech-voxcpm2.wav", wav),
                "Richer, fuller sound than Kokoro at 48 kHz; no breathing or gasping artefacts; no skipped words.",
                model="voxcpm2", seconds=wav_seconds(wav), work_s=round(dt, 1))  # fmt: skip
    else:
        rig.skip("VoxCPM2 is not on this computer")
    if rig.ready("design", "qwen3-tts-1.7b-voicedesign"):
        with guard(rig, "the designed voice"):
            d = rig.post(
                "/products/wasifyai-voice/voices/design",
                json={
                    "name": "Old storyteller",
                    "description": "A warm, slow, gravelly older man, like a grandfather reading a bedtime story",
                },
            ).json()
            out, dt = rig.run(
                task="speak",
                saved_voice=d["id"],
                text="Once upon a time, in a village by the sea, there lived an old lighthouse keeper.",
            )
            rig.add(P, "design-storyteller", "A voice made from words: warm, slow, gravelly older man",
                rig.save("speech-design-storyteller.wav", rig.speech_wav(out["speech_id"])),
                "Does it sound like the description (older, male, warm, slow, a little rough)? Is it the same voice through the whole sentence?",
                model="qwen3-tts-1.7b-voicedesign", description=d["description"])  # fmt: skip
    else:
        rig.skip("Qwen3-TTS VoiceDesign is not on this computer")
    if rig.ready("clone", "qwen3-tts-0.6b-base") and ctx.get("speech_am_adam"):
        with guard(rig, "the copied voice"):
            ref = rig.speech_wav(ctx["speech_am_adam"])
            rig.save("speech-clone-reference.wav", ref)
            v = rig.post(
                "/products/wasifyai-voice/voices/clone",
                files={"file": ("ref.wav", ref, "audio/wav")},
                data={"name": "Adam copy", "consent": "own", "reference_text": SENTENCE},
            ).json()
            out, dt = rig.run(
                task="speak",
                saved_voice=v["id"],
                text="This is the same voice, saying a completely different sentence about the weather tomorrow.",
            )
            rig.add(P, "clone", "A voice copied from a recording (Qwen3-TTS)", rig.save("speech-clone-result.wav", rig.speech_wav(out["speech_id"])),
                "Compare with the reference: is it recognisably the same speaker? (The reference here is a synthetic voice; try your own 10-second recording in the app for a real test.)",
                model="qwen3-tts-0.6b-base", reference="speech-clone-reference.wav")  # fmt: skip
    else:
        rig.skip("Qwen3-TTS Base (voice copying) is not on this computer")


def transcribe(rig: Rig, ctx: dict[str, Any]) -> None:
    P = "transcribe"
    if not rig.ready("transcribe", "parakeet-tdt-0.6b-v3") or not ctx.get("speech_af_heart"):
        return rig.skip("Parakeet or the speech sample is not available")
    for sid, label in ((ctx["speech_af_heart"], "the fox sentence"),):
        wav = rig.speech_wav(sid)
        r = rig.post(
            "/products/wasifyai-voice/transcripts", files={"file": ("sample.wav", wav, "audio/wav")}
        ).json()
        rig.add(P, "parakeet-fox", f"Speech to text on {label}", rig.save("transcribe-fox.wav", wav),
                f"The words the app wrote down should match what you hear. It wrote: “{r['text']}”. Expected: “{SENTENCE}”.",
                model="parakeet-tdt-0.6b-v3", expected=SENTENCE, heard=r["text"])  # fmt: skip


def music(rig: Rig, ctx: dict[str, Any]) -> None:
    P = "music"
    if rig.ready("music", "ace-step-1.5-turbo"):
        out, dt = rig.run(
            task="music",
            model="ace-step-1.5-turbo",
            text="upbeat acoustic pop, female vocals, summer, guitar and light drums",
            lyrics=LYRICS,
            duration=30,
            seed=7,
        )
        wav = rig.track_wav(out["track_id"])
        rig.add(P, "ace-song", "ACE-Step 1.5 Turbo, a song with lyrics (30 s)", rig.save("music-ace-song.wav", wav),
                "Are the lyrics sung in the right order and are the words understandable? Does the style match (pop, female vocal, guitar)? Any glitches, drifting key, or the vocal dropping out?",
                model="ace-step-1.5-turbo", seconds=wav_seconds(wav), work_s=round(dt, 1), lyrics=LYRICS)  # fmt: skip
        ctx["song"] = out["track_id"]
        out, _ = rig.run(
            task="music",
            model="ace-step-1.5-turbo",
            text="calm lo-fi piano, slow, warm vinyl crackle",
            instrumental=True,
            duration=20,
            seed=3,
        )
        rig.add(P, "ace-instrumental", "ACE-Step, an instrumental (20 s)", rig.save("music-ace-instrumental.wav", rig.track_wav(out["track_id"])),
                "Musical and pleasant to the end, no random vocal sounds, a steady tempo.", model="ace-step-1.5-turbo")  # fmt: skip
        out, _ = rig.run(
            task="music",
            model="ace-step-1.5-turbo",
            text="pop con guitarra, voz de mujer",
            lyrics="[verse]\nEl sol sobre el mar\nUn día de verano\n[chorus]\nCanta conmigo\nLa la la la",
            duration=20,
            seed=4,
        )
        rig.add(P, "ace-spanish", "ACE-Step, Spanish lyrics (audio.cpp ignores the language option)", rig.save("music-ace-spanish.wav", rig.track_wav(out["track_id"])),
                "Is the Spanish sung clearly? The audio.cpp build cannot be told the language; compare with the image-engine sample below.", model="ace-step-1.5-turbo", lyrics="El sol sobre el mar...")  # fmt: skip
        for action, desc, kw in (
            (
                "repaint",
                "a drum fill and a brighter guitar",
                {"edit_ranges": [[10, 15]], "strength": 0.7},
            ),
            ("cover", "as slow lo-fi hip hop", {"strength": 0.5}),
        ):
            try:
                out, _ = rig.run(
                    task="music_edit",
                    model="ace-step-1.5-turbo",
                    source_track=ctx["song"],
                    edit_action=action,
                    text=desc,
                    seed=3,
                    **kw,
                )
                rig.add(P, f"ace-{action}", f"ACE-Step edit: {action} ({desc})", rig.save(f"music-ace-{action}.wav", rig.track_wav(out["track_id"])),
                        "Repaint: only 10 to 15 seconds change, and the join at both ends is smooth. Cover: the same song in a new style, same lyrics and melody outline." if action == "repaint" else "The same song in a new style; the melody is still recognisable.",
                        model="ace-step-1.5-turbo", compare="music-ace-song.wav")  # fmt: skip
            except RuntimeError as e:
                rig.skip(f"ACE edit {action}: {e}")
    else:
        rig.skip("ACE-Step (audio.cpp) is not on this computer")
    if rig.ready("music", "ace-step-1.5-turbo-comfyui"):
        try:
            out, dt = rig.run(
                task="music",
                model="ace-step-1.5-turbo-comfyui",
                text="pop con guitarra, voz de mujer",
                lyrics="[verse]\nEl sol sobre el mar\nUn día de verano\n[chorus]\nCanta conmigo\nLa la la la",
                duration=20,
                seed=4,
                options={"language": "es", "bpm": 110},
            )
            rig.add(P, "ace-comfy-spanish", "ACE-Step on the image engine, Spanish lyrics with the language set", rig.save("music-ace-comfyui-spanish.wav", rig.track_wav(out["track_id"])),
                    "The same song model; here the language is set to Spanish. Is the Spanish more natural than the audio.cpp sample?", model="ace-step-1.5-turbo-comfyui", work_s=round(dt, 1))  # fmt: skip
        except RuntimeError as e:
            rig.skip(f"ACE on the image engine: {e}")
    else:
        rig.skip("ACE-Step on the image engine is not ready (the image engine or its 10 GB file)")
    if rig.ready("music", "stable-audio-3-small-music"):
        out, dt = rig.run(
            task="music",
            model="stable-audio-3-small-music",
            text="warm ambient pad, slow, dreamy, synthesizers",
            duration=20,
            seed=1,
        )
        rig.add(P, "stable-ambient", "Stable Audio 3 Small, ambient music (20 s)", rig.save("music-stable-ambient.wav", rig.track_wav(out["track_id"])),
                "Smooth, evolving, no harsh digital noise or sudden jumps. (Instrumental only.)", model="stable-audio-3-small-music", work_s=round(dt, 1))  # fmt: skip
        ctx["ambient"] = out["track_id"]
        try:
            out, _ = rig.run(
                task="music_edit",
                model="stable-audio-3-small-music",
                source_track=ctx["ambient"],
                edit_action="restyle",
                text="as bright chiptune",
                strength=0.6,
                seed=3,
            )
            rig.add(P, "stable-restyle", "Stable Audio edit: restyle as bright chiptune", rig.save("music-stable-restyle.wav", rig.track_wav(out["track_id"])),
                    "Is it recognisably the ambient piece, played as chiptune?", model="stable-audio-3-small-music", compare="music-stable-ambient.wav")  # fmt: skip
        except RuntimeError as e:
            rig.skip(f"Stable Audio restyle: {e}")
    else:
        rig.skip("Stable Audio 3 Small (music) is not on this computer")
    if rig.ready("music", "stable-audio-3-small-sfx"):
        for sid, text in (
            ("rain", "rain on a tin roof with distant thunder"),
            ("door", "a heavy wooden door slams in an empty hall"),
        ):
            out, _ = rig.run(
                task="music",
                model="stable-audio-3-small-sfx",
                music_mode="sfx",
                text=text,
                duration=6,
                seed=2,
            )
            rig.add(P, f"sfx-{sid}", f"Sound effect: {text}", rig.save(f"sfx-{sid}.wav", rig.track_wav(out["track_id"])),
                    "Does it sound like what was asked? Clean start and end, no clicks.", model="stable-audio-3-small-sfx")  # fmt: skip
    else:
        rig.skip("Stable Audio 3 Small (sound effects) is not on this computer")


def tools(rig: Rig, ctx: dict[str, Any]) -> None:
    P = "tools"
    song = ctx.get("song")
    if song is None:
        # a song is needed to split: import the ACE sample if it was made in an earlier run
        f = rig.out / "music-ace-song.wav"
        if f.is_file():
            song = rig.post(
                "/products/wasifyai-voice/tracks/import",
                files={"file": ("song.wav", f.read_bytes(), "audio/wav")},
                data={"title": "ACE sample song"},
            ).json()["id"]
    if song and rig.ready("separate", "htdemucs"):
        original = "music-ace-song.wav"
        for model, stems in (
            ("htdemucs", ("vocals", "drums", "bass", "other")),
            ("mel-band-roformer", ("vocals", "instrumental")),
        ):
            if not rig.ready("separate", model):
                rig.skip(f"{model} is not on this computer")
                continue
            out, dt = rig.run(task="separate", source_track=song, model=model)
            for t in out["tracks"]:
                if t["stem"] in stems:
                    rig.add(P, f"sep-{model}-{t['stem']}", f"Split into parts ({model}): {t['stem']}", rig.save(f"tools-sep-{model}-{t['stem']}.wav", rig.track_wav(t["track_id"])),
                            {"vocals": "Only the singing: little or no drums and guitar left in it, and the voice itself not thin or watery.", "drums": "Only drums; no voice.", "bass": "Bass only (this song may have very little).", "other": "Guitar and everything else, without voice or drums.", "instrumental": "Everything except the voice: is there singing left over (bleed)?"}[t["stem"]],
                            model=model, compare=original, work_s=round(dt, 1))  # fmt: skip
    else:
        rig.skip(
            "no song to split, or HTDemucs is not on this computer (run the music section first)"
        )
    if ctx.get("speech_af_heart") and ctx.get("speech_am_adam"):
        for model in ("tone-color-vc", "meanvc2"):
            if not rig.ready("convert", model):
                rig.skip(f"{model} is not on this computer")
                continue
            ref = rig.speech_wav(ctx["speech_am_adam"])
            v = rig.post(
                "/products/wasifyai-voice/voices/clone",
                files={"file": ("ref.wav", ref, "audio/wav")},
                data={"name": f"Target for {model}", "consent": "own", "reference_text": SENTENCE},
            ).json()
            out, dt = rig.run(
                task="convert",
                source_speech=ctx["speech_af_heart"],
                saved_voice=v["id"],
                model=model,
                seed=1,
            )
            rig.add(P, f"convert-{model}", f"Change a voice ({model}): the woman's voice made to sound like the man", rig.save(f"tools-convert-{model}.wav", rig.track_wav(out["track_id"])),
                    "Same words and timing as the source; does it sound like the target speaker (lower, male)? Any robotic or underwater sound?",
                    model=model, source="speech-kokoro-af_heart.wav", reference="speech-kokoro-am_adam.wav", work_s=round(dt, 1))  # fmt: skip
    else:
        rig.skip("the speech samples are needed for Change a voice (run the speech section first)")
    if rig.ready("edit", "dots-tts-edit") and ctx.get("speech_af_heart"):
        text = "Hello brave world. Today we will walk along the quiet river and talk about the weather."
        out, _ = rig.run(task="speak", text=text, voice="af_heart", options={"seed": 1})
        src = out["speech_id"]
        rig.save("tools-edit-source.wav", rig.speech_wav(src))
        for label, new in (
            ("replace", text.replace("brave", "small")),
            ("delete", text.replace("quiet ", "")),
            ("insert", text.replace("river", "river slowly")),
        ):
            try:
                o, dt = rig.run(
                    task="speech_edit",
                    source_speech=src,
                    model="dots-tts-edit",
                    old_text=text,
                    text=new,
                    seed=1,
                )
                rig.add(P, f"edit-{label}", f"Edit speech ({label}): “{new}”", rig.save(f"tools-edit-{label}.wav", rig.track_wav(o["track_id"])),
                        "Only the changed words differ; the rest sounds untouched; the voice stays the same; no click or jump at the edit.",
                        model="dots-tts-edit", source="tools-edit-source.wav", expected=new, work_s=round(dt, 1))  # fmt: skip
            except RuntimeError as e:
                rig.skip(f"Edit speech {label}: {e}")
    else:
        rig.skip("dots.tts Edit is not on this computer")


def lipsync(rig: Rig, ctx: dict[str, Any], face: Path | None) -> None:
    P = "lipsync"
    if not rig.get("/desktop/lipsync").json()["installed"] or not rig.ready(
        "lipsync", "musetalk-v15"
    ):
        return rig.skip("the lip sync engine or MuseTalk's files are not ready")
    if face is None or not face.is_file():
        return rig.skip("no picture given (--face); a painting or a drawing is a good test")
    pic = rig.post(
        "/products/wasifyai-voice/pictures",
        files={"file": (face.name, face.read_bytes(), "image/png")},
    ).json()
    out, dt = rig.run(
        task="lipsync",
        picture=pic["id"],
        text="Good evening, everyone. Thank you for coming tonight. It is a pleasure to be here.",
        title="Lip sync sample",
    )
    clip = rig.get(f"/products/wasifyai-voice/clips/{out['clip_id']}/download").content
    rig.add(P, "lipsync", "Lip sync: a picture says a sentence", rig.save("lipsync-sample.mp4", clip),
            "Does the mouth move with the words (not early, not late)? Is the rest of the face stable? The head stays still: that is how this model works.",
            model="musetalk-v15", seconds=out["seconds"], work_s=round(dt, 1))  # fmt: skip
    rig.post("/desktop/lipsync/stop")


def dub(rig: Rig, ctx: dict[str, Any]) -> None:
    P = "dub"
    if not (
        rig.ready("clone", "qwen3-tts-0.6b-base")
        and rig.ready("separate", "mel-band-roformer")
        and rig.ready("transcribe", "parakeet-tdt-0.6b-v3")
    ):
        return rig.skip("dubbing needs Qwen3-TTS Base, Mel-Band RoFormer and Parakeet")
    if shutil.which("ffmpeg") is None:
        return rig.skip("dubbing needs ffmpeg")
    chat_ready(rig)
    text = "Good evening everyone. Thank you for coming tonight, it means a great deal to all of us. We have a wonderful show planned, and I hope that you enjoy every minute of it."
    out, _ = rig.run(task="speak", text=text, voice="am_adam", options={"seed": 1})
    sid = out["speech_id"]
    rig.save("dub-source-english.wav", rig.speech_wav(sid))
    for lang, name in (("es", "Spanish"), ("de", "German")):
        try:
            sc, dt1 = rig.run(task="dub_script", source_speech=sid, language=lang, background=True)
            d, dt2 = rig.run(
                task="dub",
                source_speech=sid,
                language=lang,
                segments=sc["segments"],
                voice_from="speaker",
                speaker_basis="own",
                vocals_track=sc["vocals_track"],
                background_track=sc["background_track"],
            )
            script = " / ".join(s["text"] for s in sc["segments"])
            rig.add(P, f"dub-{lang}", f"Dub into {name}, in the speaker's own copied voice", rig.save(f"dub-{lang}.wav", rig.track_wav(d["track_id"])),
                    f"Is the {name} correct and natural? Does the voice still sound like the English speaker (with an accent is expected)? Does each line fit its time, with no cut-off ending? Script: {script}",
                    model="qwen3-tts-0.6b-base", source="dub-source-english.wav", script=sc["segments"], fit=d["fit"], work_s=round(dt1 + dt2, 1))  # fmt: skip
        except RuntimeError as e:
            rig.skip(f"dub into {name}: {e}")


def chat_ready(rig: Rig) -> None:
    rig.post("/desktop/discovery/scan")
    for _ in range(300):
        d = rig.get("/desktop/discovery").json()
        if d["scanned_at"] and not d["running"]:
            break
        time.sleep(0.1)
    item = next(
        (i for i in d["items"] if i["kind"] == "language" and "Qwen3-4B" in i["path"]), None
    )
    if item:
        rig.client.put(
            "/desktop/language", json={"item_id": item["id"], "context": 8192}, headers=rig.headers
        )


def audiobook(rig: Rig, ctx: dict[str, Any]) -> None:
    P = "audiobook"
    if not rig.ready("speak", "kokoro-82m"):
        return rig.skip("Kokoro is not on this computer")
    plan = rig.post("/products/wasifyai-voice/audiobook/plan", json={"text": BOOK}).json()
    chapters = [{"title": c["title"], "text": c["text"]} for c in plan["chapters"]]
    out, dt = rig.run(
        task="audiobook",
        title="The Lighthouse",
        chapters=chapters,
        voice="af_heart",
        whole=True,
        options={"seed": 1},
    )
    wav = rig.track_wav(out["book"]["track_id"])
    rig.add(P, "book", "Audiobook: two chapters read in one track", rig.save("audiobook-lighthouse.wav", wav),
            "Pace and pauses between sentences, paragraphs and chapters feel natural; the chapter title is read; no changes of voice or volume between pieces.",
            model="kokoro-82m", seconds=wav_seconds(wav), work_s=round(dt, 1))  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--data-dir", required=True)
    ap.add_argument(
        "--models-dir",
        action="append",
        default=[],
        help="a folder with audio/ and checkpoints/ inside (repeat)",
    )
    ap.add_argument("--out", default=str(ROOT / "docs/listening/samples"))
    ap.add_argument("--only", default=",".join(SECTIONS))
    ap.add_argument("--face", help="a picture of a drawing or painting, for the lip sync sample")
    ap.add_argument(
        "--musetalk-home",
        help="a MuseTalk set up by hand (src/ and venv/), if not installed by the app",
    )
    ap.add_argument("--image-engine", default="comfyui", choices=["stub", "comfyui", "auto"])
    args = ap.parse_args()
    wanted = [s for s in args.only.split(",") if s]
    unknown = set(wanted) - set(SECTIONS)
    if unknown:
        sys.exit(f"unknown section: {sorted(unknown)}; choose from {SECTIONS}")
    rig = Rig(args)
    manifest_path = rig.out / "manifest.json"
    old = (
        json.loads(manifest_path.read_text())
        if manifest_path.is_file()
        else {"items": [], "skipped": {}}
    )
    ctx_path = rig.out / "ctx.json"
    ctx: dict[str, Any] = json.loads(ctx_path.read_text()) if ctx_path.is_file() else {}
    try:
        for name in SECTIONS:
            if name not in wanted:
                continue
            print(f"== {name}", flush=True)
            rig.items, rig.skipped = [], []
            try:
                if name == "lipsync":
                    lipsync(rig, ctx, Path(args.face).expanduser() if args.face else None)
                else:
                    {
                        "speech": speech,
                        "transcribe": transcribe,
                        "music": music,
                        "tools": tools,
                        "dub": dub,
                        "audiobook": audiobook,
                    }[name](rig, ctx)
            except Exception as e:  # one section failing must not lose the others
                rig.skip(f"the section stopped: {e}")
            old["items"] = [i for i in old["items"] if i["section"] != name] + rig.items
            old["skipped"][name] = rig.skipped
            # later sections reuse what earlier ones made, as far as it is in the library
            if name == "speech":
                for s in rig.get("/products/wasifyai-voice/speeches?limit=50").json()["items"]:
                    if (
                        s["voice"] in ("af_heart", "am_adam")
                        and s["options"] == {"seed": 1}
                        and s["text"] == SENTENCE
                    ):
                        ctx.setdefault(f"speech_{s['voice']}", s["id"])
    finally:
        rig.close()
        ctx_path.write_text(json.dumps(ctx))
        order = {n: i for i, n in enumerate(SECTIONS)}
        old["items"].sort(key=lambda i: order[i["section"]])
        old["made"] = time.strftime("%Y-%m-%d %H:%M")
        manifest_path.write_text(json.dumps(old, indent=2, ensure_ascii=False))
        subprocess.run(["ls", "-la", str(rig.out)], check=False, stdout=subprocess.DEVNULL)
    print(f"\n{len(old['items'])} samples in {rig.out}")
    for name, why in old["skipped"].items():
        for w in why:
            print(f"  skipped ({name}): {w}")


if __name__ == "__main__":
    main()
