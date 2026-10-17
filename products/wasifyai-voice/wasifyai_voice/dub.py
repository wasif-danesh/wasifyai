# SPDX-License-Identifier: Apache-2.0
"""Dubbing as graph tasks (ADR-0066, stage V6): `dub_script` writes the script of a recording in
another language, `dub` speaks it and mixes it. Every model is the engine's to choose or the
person's to pick; nothing here names one except the separator that gives a clean background
(`DEFAULT_SEPARATOR`).

    dub_script:  [separate the voice from the background] -> write down what is said, with times ->
                 translate each line
    dub:         the person's script -> speak each line (in the speaker's own voice, a saved
                 voice, or a built-in one) -> fit each line to its time -> mix over the
                 background -> a track

Copying the speaker's voice needs the person's word that it is theirs or that they have permission
(the same consent as a saved cloned voice); that word is kept with the dub."""

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from langgraph.config import get_stream_writer
from wasifyai_platform_sdk import (
    Capabilities,
    RunError,
    VoiceEngineError,
    VoiceRequestError,
    check_clone,
    check_design,
    check_separate,
    check_speak,
    check_transcribe,
    require_context,
)

from wasifyai_voice import audio_input, consent, dubbing
from wasifyai_voice.runtime import store_for
from wasifyai_voice.store import NotFound
from wasifyai_voice.tools import Kit, Refuse, Source, SourceMissing

log = logging.getLogger(__name__)

DEFAULT_SEPARATOR = "mel-band-roformer"  # makes a vocals and an instrumental stem
BATCH = 40  # lines translated in one request
REFERENCE_MIN_WORDS = 3


def build_dub(caps: Capabilities, app_state: Any, engine: Any, refuse_with: Refuse, kit: Kit):
    store = lambda: store_for(app_state)  # noqa: E731

    def say(label: str, node: str = "dub") -> None:
        get_stream_writer()({"type": "node", "node": node, "status": "started", "label": label})

    def ready_models(task: str, language: str) -> list[dict[str, Any]]:
        """Ready models of the engine for a task that speak the language, recommended first."""
        ms = [
            m for m in engine().models(task)
            if m["state"] == "ready" and dubbing.base(language) in _langs(m)
        ]  # fmt: skip
        return sorted(ms, key=lambda m: task not in m["recommended"])

    def _langs(m: dict[str, Any]) -> set[str]:
        langs = {dubbing.base(x) for x in m["languages"]}
        return set(dubbing.LANGUAGES) if "multi" in langs else langs

    # ---- the script -------------------------------------------------------------------------

    async def translate(segments: list[dubbing.Segment], language: str) -> list[str]:
        """Each line in `language`: the script in batches, a line at a time where a batch did
        not come back as the right number of lines."""
        out: list[str] = []
        for i in range(0, len(segments), BATCH):
            batch = segments[i : i + BATCH]
            answer = await _chat(dubbing.translation_messages(batch, language))
            lines = dubbing.parse_translation(answer, len(batch))
            if lines is None:
                lines = []
                for seg in batch:
                    one = dubbing.clean_line(await _chat(dubbing.single_message(seg, language)))
                    if not one:
                        raise RunError(
                            "translation_failed",
                            "The translation could not be written. Try again.",
                            retryable=True,
                        )  # fmt: skip
                    lines.append(one)
            out += lines
        return out

    async def _chat(messages: list[dict[str, str]]) -> str:
        text = ""
        try:
            async for chunk in caps.text.chat("chat", messages, None):
                if chunk.text:
                    text += chunk.text
        except RunError:
            raise
        except Exception:
            log.exception("the language model failed")
            raise RunError(
                "language_failed",
                "The language model did not answer. Check it in Models and try again.",
                retryable=True,
            ) from None
        return text

    async def dub_script(state: dict[str, Any]) -> dict[str, Any]:
        say("Checking", "check_request")
        eng = engine()
        language = str(state.get("language", ""))
        if dubbing.base(language) not in dubbing.LANGUAGES:
            return refuse_with("unknown_language", "Choose the language to dub into.")
        if not (ready_models("speak", language) or ready_models("clone", language)):
            return refuse_with(
                "no_voice_for_language",
                f"No voice model on this computer speaks {dubbing.language_name(language)}. "
                "Get one in Models.",
            )
        try:
            source = await kit.load_source(state)
            transcriber = eng.resolve("transcribe", state.get("transcribe_model") or None)
            check_transcribe(transcriber, None)
        except VoiceEngineError as e:
            raise kit.failed(e) from None
        except SourceMissing as e:
            return refuse_with("unknown_source", e.message)
        except VoiceRequestError as e:
            return refuse_with(e.code, e.message)
        scratch: list[Path] = []
        out: dict[str, Any] = {}
        try:
            heard = source
            if state.get("background"):
                say("Separating the voice from the background", "separate")
                vocals, background = await _separate(source, state, scratch)
                out["vocals_track"], out["background_track"] = (
                    vocals["track_id"],
                    background["track_id"],
                )
                heard = Source(
                    "track",
                    vocals["track_id"],
                    await _bytes(vocals),
                    source.title,
                    vocals["track_id"],
                )
            say("Writing down what is said", "transcribe")
            wav, seconds = await audio_input.at_rate(heard.wav, "voice.wav", 16000, 1)
            result = await eng.transcribe(transcriber, wav, {})
            raw = [s for s in result.segments if s.text.strip() and s.end > s.start]
            if not raw:
                return refuse_with("no_speech", "No speech was found in that recording.")
            segments = [dubbing.Segment(s.start, s.end, s.text.strip(), "") for s in raw]
            say("Translating", "translate")
            lines = await translate(segments, language)
        except audio_input.AudioInputError as e:
            return refuse_with(e.code, str(e))
        except SourceMissing as e:
            return refuse_with("unreadable_audio", e.message)
        except VoiceRequestError as e:
            return refuse_with(e.code, e.message)
        except VoiceEngineError as e:
            raise kit.failed(e) from None
        finally:
            for p in scratch:
                await asyncio.to_thread(p.unlink, True)
        script = [
            dubbing.Segment(s.start, s.end, s.source, line).public()
            for s, line in zip(segments, lines, strict=True)
        ]
        return {
            "segments": script, "language": dubbing.base(language), "seconds": round(seconds, 2),
            "transcriber": transcriber.id, **out, "status": "done",
        }  # fmt: skip

    async def _bytes(stem: dict[str, Any]) -> bytes:
        assert caps.storage is not None
        ctx = require_context()
        t = store().get_track(ctx.tenant_id, ctx.user_id, stem["track_id"])
        return await caps.storage.get(t["audio_key"])

    async def _separate(
        source: Source, state: dict[str, Any], scratch: list[Path]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """The voice and the background of a recording, both kept as tracks."""
        eng = engine()
        model = eng.resolve("separate", state.get("separate_model") or DEFAULT_SEPARATOR)
        clip, seconds = await kit.at_rate(source, int(model.separate["input_rate"]), 2)
        scratch.append(clip)
        req = check_separate(model, seconds, None)
        result = await eng.separate(model, req, clip)
        stems = {s.name: s for s in result.stems}
        if "vocals" not in stems:
            raise VoiceEngineError("engine_failed", "The model did not find the voice.")
        background = stems.get("instrumental")
        wav_bg = (
            background.wav
            if background
            else await _sum([s for n, s in stems.items() if n != "vocals"])
        )
        rate = background.sample_rate if background else stems["vocals"].sample_rate

        async def keep(name: str, wav: bytes, sec: float) -> dict[str, Any]:
            return await kit.keep(
                wav=wav, rate=rate, seconds=sec, title=f"{source.title} ({name})", mode="stem",
                description=f"The {name} of {source.title}", model_id=model.id, options={},
                seed=None, parent=source.track_id,
                edit={"action": "separate", "stem": name, "from": source.kind},
                load_s=result.load_s, elapsed_s=result.elapsed_s,
            )  # fmt: skip

        v = await keep("vocals", stems["vocals"].wav, stems["vocals"].seconds)
        b = await keep(
            "background", wav_bg, background.seconds if background else stems["vocals"].seconds
        )
        return v, b

    async def _sum(stems: list[Any]) -> bytes:
        """The parts that are not the voice, as one recording."""
        with tempfile.TemporaryDirectory(prefix="dub-sum-") as tmp:
            paths = []
            for i, s in enumerate(stems):
                p = Path(tmp) / f"{i}.wav"
                await asyncio.to_thread(p.write_bytes, s.wav)
                paths.append(p)
            out = Path(tmp) / "sum.wav"
            args: list[str] = []
            for p in paths:
                args += ["-i", str(p)]
            await dubbing._ffmpeg(  # noqa: SLF001
                [
                    *args,
                    "-filter_complex",
                    f"amix=inputs={len(paths)}:normalize=0",
                    "-c:a",
                    "pcm_s16le",
                    str(out),
                ]
            )
            return await asyncio.to_thread(out.read_bytes)

    # ---- the dub ----------------------------------------------------------------------------

    async def dub(state: dict[str, Any]) -> dict[str, Any]:
        say("Checking", "check_request")
        assert caps.storage is not None, "storage is required"
        ctx = require_context()
        language = str(state.get("language", ""))
        if dubbing.base(language) not in dubbing.LANGUAGES:
            return refuse_with("unknown_language", "Choose the language to dub into.")
        try:
            dubbing.ffmpeg_path()
            source = await kit.load_source(state)
            total = await _seconds(source)
            lines = dubbing.clean_segments(state.get("segments"), total)
        except dubbing.DubError as e:
            return refuse_with(e.code, str(e))
        except SourceMissing as e:
            return refuse_with("unknown_source", e.message)
        voice_from = str(state.get("voice_from") or "builtin")
        basis = state.get("speaker_basis")
        if voice_from == "speaker" and basis not in consent.STATEMENTS:
            return refuse_with(
                "consent_required",
                "Copying the speaker's voice needs your word that it is your own voice, or that "
                "you have permission to use it.",
            )
        work = Path(tempfile.mkdtemp(prefix="dub-", dir=await _scratch_root()))
        try:
            speak = await _voice(voice_from, state, language, lines, work)
            if isinstance(speak, dict):
                return speak  # a refusal
            placements, stats = await _speak_all(speak, lines, total, work)
            background = None
            if state.get("background_track"):
                bg = store().get_track(ctx.tenant_id, ctx.user_id, str(state["background_track"]))
                background = work / "background.wav"
                await asyncio.to_thread(
                    background.write_bytes, await caps.storage.get(bg["audio_key"])
                )
            say("Mixing")
            wav = await dubbing.mix(background, placements, total, work / "dub.wav")
        except dubbing.DubError as e:
            return refuse_with(e.code, str(e))
        except (NotFound, FileNotFoundError):
            return refuse_with("unknown_source", "A recording this dub needs is no longer there.")
        except VoiceRequestError as e:
            return refuse_with(e.code, e.message)
        except VoiceEngineError as e:
            raise kit.failed(e) from None
        finally:
            await asyncio.to_thread(shutil.rmtree, work, True)
        name = dubbing.language_name(language)
        title = (state.get("title") or "").strip()[:120] or f"{source.title} ({name})"
        made = await kit.keep(
            wav=wav, rate=44100, seconds=_wav_seconds(wav), title=title, mode="dubbed",
            description=f"{source.title}, dubbed into {name}", model_id=speak.model.id, options={},
            seed=None, parent=source.track_id,
            edit={
                "action": "dub", "language": dubbing.base(language), "voice_from": voice_from,
                "voice": speak.label, "segments": [s.public() for s in lines], "fit": stats,
                "consent": consent.record(str(basis)) if voice_from == "speaker" else None,
                "from": source.kind,
            },
            load_s=0.0, elapsed_s=stats["elapsed_s"],
            lyrics="\n".join(s.text for s in lines),
        )  # fmt: skip
        return {**made, "tracks": [made], "fit": stats, "status": "done"}

    async def _scratch_root() -> Path:
        root = store().root / "tmp"
        await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
        return root

    async def _seconds(source: Source) -> float:
        _, seconds = await audio_input.at_rate(source.wav, "audio.wav", 16000, 1)
        return seconds

    class Speaker:
        """How lines are spoken: the model, a label for the record, and the call."""

        def __init__(self, model: Any, label: str, call: Any):
            self.model, self.label, self.call = model, label, call

    async def _voice(
        voice_from: str,
        state: dict[str, Any],
        language: str,
        lines: list[dubbing.Segment],
        work: Path,
    ) -> Speaker | dict[str, Any]:
        eng = engine()
        ctx = require_context()
        asked = state.get("model") or None
        if voice_from == "speaker":
            clone = _pick("clone", asked, language)
            if isinstance(clone, dict):
                return clone
            model = eng.resolve("clone", clone)
            lo, hi = model.clone["min_seconds"], model.clone["max_seconds"]
            ref = dubbing.pick_reference(lines, lo, hi)
            vocals_id = state.get("vocals_track")
            if ref is None or not vocals_id:
                return refuse_with(
                    "no_reference",
                    f"There is no stretch of {lo:g} to {hi:g} seconds of one person speaking to "
                    "copy the voice from. Separate the voice first, or choose another voice.",
                )
            vocals = store().get_track(ctx.tenant_id, ctx.user_id, str(vocals_id))
            full = work / "vocals.wav"
            assert caps.storage is not None
            data = await caps.storage.get(vocals["audio_key"])
            await asyncio.to_thread(full.write_bytes, data)
            piece = work / "reference.wav"
            await dubbing.cut(full, ref.start, ref.end, piece)

            async def call(text: str) -> Any:
                t, said, opts = check_clone(model, text, ref.source, None)
                return await eng.clone(model, t, piece, said, opts)

            return Speaker(model, "the original speaker", call)
        if voice_from == "saved":
            try:
                saved = store().get_voice(ctx.tenant_id, ctx.user_id, str(state.get("saved_voice")))
            except NotFound:
                return refuse_with("unknown_voice", "That saved voice is no longer there.")
            task = saved["kind"]
            picked = _pick(task, asked, language)
            if isinstance(picked, dict):
                return picked
            model = eng.resolve(task, picked)
            if task == "design":

                async def call(text: str) -> Any:
                    t, d, opts = check_design(model, text, saved["description"], None)
                    return await eng.design(model, t, d, opts)

                return Speaker(model, saved["name"], call)
            reference = store().reference_path(saved["id"])
            if not reference.is_file():
                return refuse_with(
                    "reference_missing", "The recording of this voice is no longer there."
                )

            async def call(text: str) -> Any:  # noqa: F811
                t, said, opts = check_clone(model, text, saved["reference_text"], None)
                return await eng.clone(model, t, reference, said, opts)

            return Speaker(model, saved["name"], call)
        picked = _pick("speak", asked, language)
        if isinstance(picked, dict):
            return picked
        model = eng.resolve("speak", picked)
        voice = state.get("voice") or None

        async def call(text: str) -> Any:  # noqa: F811
            t, v, opts = check_speak(model, text, voice, None)
            return await eng.speak(model, t, v, opts)

        return Speaker(model, voice or model.default_voice or model.title, call)

    def _pick(task: str, asked: str | None, language: str) -> str | dict[str, Any]:
        """The model id to use for a task in a language: the one asked for (it must speak it),
        else the recommended one that does."""
        if asked:
            found = next((m for m in engine().models(task) if m["id"] == asked), None)
            if found is None or dubbing.base(language) not in _langs(found):
                return refuse_with(
                    "no_voice_for_language",
                    f"That model does not speak {dubbing.language_name(language)}. Choose another.",
                )
            return asked
        models = ready_models(task, language)
        if not models:
            return refuse_with(
                "no_voice_for_language",
                f"No model on this computer speaks {dubbing.language_name(language)} that way. "
                "Choose another voice or get a model in Models.",
            )
        return str(models[0]["id"])

    async def _speak_all(
        speak: Speaker, lines: list[dubbing.Segment], total: float, work: Path
    ) -> tuple[list[dubbing.Placement], dict[str, Any]]:
        import time

        t0 = time.monotonic()
        room = dubbing.slots(lines, total)
        placements: list[dubbing.Placement] = []
        sped, over = 0, 0.0
        for i, (line, slot) in enumerate(zip(lines, room, strict=True), 1):
            say(f"Speaking line {i} of {len(lines)}")
            result = await speak.call(line.text)
            path = work / f"line-{i}.wav"
            await asyncio.to_thread(path.write_bytes, result.wav)
            tempo, overflow = dubbing.tempo_for(result.seconds, slot)
            sped += tempo > 1.0
            over = max(over, overflow)
            placements.append(dubbing.Placement(path, line.start, tempo))
        stats = {
            "lines": len(lines), "sped_up": sped, "max_overflow_s": round(over, 2),
            "elapsed_s": round(time.monotonic() - t0, 2),
        }  # fmt: skip
        return placements, stats

    def _wav_seconds(wav: bytes) -> float:
        import io
        import wave

        with wave.open(io.BytesIO(wav)) as w:
            return w.getnframes() / float(w.getframerate())

    return {"dub_script": dub_script, "dub": dub}
