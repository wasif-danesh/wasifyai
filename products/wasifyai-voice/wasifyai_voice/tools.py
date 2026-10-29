# SPDX-License-Identifier: Apache-2.0
"""The audio tools of the graph (ADR-0066, stage V4): split a recording into stems, make a
recording sound like another voice, change words in a recording.

Each tool reads a recording the person already has in the library (a track, or a speech), makes a
copy at the rate its model reads, runs the model, and keeps every result as a track whose
`parent_id` points at the recording it came from, so the library shows where it came from and
search finds it. A voice is changed only into a saved voice made from a recording, never into a
file the run was handed."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langgraph.config import get_stream_writer
from wasifyai_platform_sdk import (
    Capabilities,
    RunError,
    VoiceEngineError,
    VoiceRequestError,
    check_convert,
    check_lipsync,
    check_separate,
    check_speak,
    check_speech_edit,
    require_context,
)

from wasifyai_voice import audio_input
from wasifyai_voice.runtime import store_for
from wasifyai_voice.store import NotFound, new_id
from wasifyai_voice.usage import TOOLS, metered

log = logging.getLogger(__name__)

TRACK_CREATED = "voice.track"
CLIP_CREATED = "voice.lipsync"
Refuse = Callable[[str, str], Any]


class Source:
    """A recording of the library: its WAV, its name and the id of the track it is (or None)."""

    def __init__(self, kind: str, id: str, wav: bytes, title: str, track_id: str | None):
        self.kind, self.id, self.wav, self.title, self.track_id = kind, id, wav, title, track_id


class SourceMissing(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class Kit:
    """What the tools share, for the tasks built on them (dubbing): the library, scratch files,
    keeping a result as a track."""

    def __init__(self, **fns: Any):
        self.__dict__.update(fns)

    # filled in by build_tools; named here so the type checker knows them
    load_source: Callable[[dict[str, Any]], Awaitable[Source]]
    scratch_file: Callable[..., Awaitable[Path]]
    at_rate: Callable[[Source, int, int], Awaitable[tuple[Path, float]]]
    keep: Callable[..., Awaitable[dict[str, Any]]]
    failed: Callable[[VoiceEngineError], RunError]


def build_tools(
    caps: Capabilities,
    app_state: Any,
    engine: Callable[[], Any],
    refuse_with: Refuse,
) -> dict[str, Any]:
    async def load_source(state: dict[str, Any]) -> Source:
        """The recording a run was pointed at: `source_track` or `source_speech`."""
        assert caps.storage is not None, "storage is required"
        ctx = require_context()
        store = store_for(app_state)
        try:
            if state.get("source_track"):
                t = store.get_track(ctx.tenant_id, ctx.user_id, str(state["source_track"]))
                return Source(
                    "track", t["id"], await caps.storage.get(t["audio_key"]), t["title"], t["id"]
                )
            if state.get("source_speech"):
                s = store.get_speech(ctx.tenant_id, ctx.user_id, str(state["source_speech"]))
                return Source(
                    "speech", s["id"], await caps.storage.get(s["audio_key"]), s["text"][:60], None
                )
        except (NotFound, FileNotFoundError):
            raise SourceMissing("That recording is no longer there.") from None
        raise SourceMissing("Choose the recording to work on.")

    async def scratch_file(data: bytes, suffix: str = ".wav") -> Path:
        scratch = store_for(app_state).root / "tmp"
        await asyncio.to_thread(scratch.mkdir, parents=True, exist_ok=True)
        path = scratch / f"{new_id()}{suffix}"
        await asyncio.to_thread(path.write_bytes, data)
        return path

    async def at_rate(source: Source, rate: int, channels: int) -> tuple[Path, float]:
        try:
            wav, seconds = await audio_input.at_rate(source.wav, "audio.wav", rate, channels)
        except audio_input.AudioInputError as e:
            raise SourceMissing(str(e)) from None
        return await scratch_file(wav), seconds

    async def keep(
        *, wav: bytes, rate: int, seconds: float, title: str, mode: str, description: str,
        model_id: str, options: dict[str, Any], seed: int | None, parent: str | None,
        edit: dict[str, Any], load_s: float, elapsed_s: float, lyrics: str = "",
    ) -> dict[str, Any]:  # fmt: skip
        """One result as a track in the library, searchable, with its usage recorded."""
        assert caps.storage is not None, "storage is required"
        ctx = require_context()
        track_id = new_id()
        key = f"music/{track_id}.wav"
        await caps.storage.put(key, wav, "audio/wav")
        store_for(app_state).add_track(
            ctx.tenant_id, ctx.user_id, title=title[:120], mode=mode, description=description,
            lyrics=lyrics, instrumental=False, model_id=model_id, options=options, seed=seed,
            seconds=round(seconds, 2), sample_rate=rate, audio_key=key,
            load_s=round(load_s, 2), elapsed_s=round(elapsed_s, 2), track_id=track_id,
            parent_id=parent, edit=edit,
        )  # fmt: skip
        await caps.index_creation("track", track_id, f"{title}. {description}. {lyrics[:2000]}")
        await caps.record_usage(
            TRACK_CREATED, 1, "tracks", track_id=track_id, model=model_id, mode=mode,
            seconds=round(seconds, 2),
        )  # fmt: skip
        return {
            "track_id": track_id, "title": title[:120], "audio_url": await caps.storage.url(key),
            "seconds": round(seconds, 2), "sample_rate": rate,
        }  # fmt: skip

    def failed(e: VoiceEngineError) -> RunError:
        return RunError(e.code, e.message, retryable=e.code in ("busy", "engine_stopped"))

    # ---- split into stems ------------------------------------------------------------------

    async def separate(state: dict[str, Any]) -> dict[str, Any]:
        write = get_stream_writer()
        write({"type": "node", "node": "check_request", "status": "started", "label": "Checking"})
        eng = engine()
        try:
            model = eng.resolve("separate", state.get("model") or None)
            source = await load_source(state)
        except VoiceEngineError as e:
            raise failed(e) from None
        except SourceMissing as e:
            return refuse_with("unknown_source", e.message)
        wanted = [str(x) for x in state.get("stems") or []]
        unknown = [x for x in wanted if x not in model.separate["stems"]]
        if unknown:
            return refuse_with(
                "unknown_stem", f"{model.title} does not make a part called '{unknown[0]}'."
            )
        clip = None
        try:
            clip, seconds = await at_rate(source, int(model.separate["input_rate"]), 2)
            req = check_separate(model, seconds, state.get("options"))
            write({"type": "node", "node": "separate", "status": "started", "label": "Splitting"})
            result = await eng.separate(model, req, clip)
        except SourceMissing as e:
            return refuse_with("unreadable_audio", e.message)
        except VoiceRequestError as e:
            return refuse_with(e.code, e.message)
        except VoiceEngineError as e:
            raise failed(e) from None
        finally:
            if clip is not None:
                await asyncio.to_thread(clip.unlink, True)
        kept = []
        for stem in result.stems:
            if wanted and stem.name not in wanted:
                continue
            kept.append(
                await keep(
                    wav=stem.wav,
                    rate=stem.sample_rate,
                    seconds=stem.seconds,
                    title=f"{source.title} ({stem.name})",
                    mode="stem",
                    description=f"The {stem.name} of {source.title}",
                    model_id=model.id,
                    options=req.options,
                    seed=None,
                    parent=source.track_id,
                    edit={"action": "separate", "stem": stem.name, "from": source.kind},
                    load_s=result.load_s,
                    elapsed_s=result.elapsed_s,
                )
                | {"stem": stem.name}
            )
        if not kept:
            return refuse_with("no_parts", "None of the parts you asked for came out of that.")
        return {
            "tracks": kept, "track_id": kept[0]["track_id"], "status": "done",
            "elapsed_s": round(result.elapsed_s, 2), "load_s": round(result.load_s, 2),
        }  # fmt: skip

    # ---- change whose voice it is ---------------------------------------------------------

    async def convert(state: dict[str, Any]) -> dict[str, Any]:
        write = get_stream_writer()
        write({"type": "node", "node": "check_request", "status": "started", "label": "Checking"})
        eng = engine()
        ctx = require_context()
        store = store_for(app_state)
        try:
            voice = store.get_voice(ctx.tenant_id, ctx.user_id, str(state.get("saved_voice")))
        except NotFound:
            return refuse_with("unknown_voice", "Choose a saved voice to sound like.")
        if voice["kind"] != "clone":
            return refuse_with(
                "voice_needs_recording",
                "A voice described in words has no recording to match. Choose a voice cloned "
                "from a recording.",
            )
        reference = store.reference_path(voice["id"])
        if not reference.is_file():
            return refuse_with(
                "reference_missing", "The recording of this voice is no longer there."
            )
        try:
            model = eng.resolve("convert", state.get("model") or None)
            source = await load_source(state)
        except VoiceEngineError as e:
            raise failed(e) from None
        except SourceMissing as e:
            return refuse_with("unknown_source", e.message)
        rate = int(model.convert["input_rate"])
        clip = ref = None
        try:
            clip, seconds = await at_rate(source, rate, 1)
            ref_wav = await asyncio.to_thread(reference.read_bytes)
            ref_audio, ref_seconds = await audio_input.at_rate(ref_wav, "voice.wav", rate, 1)
            ref = await scratch_file(ref_audio)
            req = check_convert(
                model, seconds, ref_seconds, state.get("options"), state.get("seed")
            )
            write({"type": "node", "node": "convert", "status": "started", "label": "Changing"})
            result = await eng.convert(model, req, clip, ref)
        except SourceMissing as e:
            return refuse_with("unreadable_audio", e.message)
        except audio_input.AudioInputError as e:
            return refuse_with(e.code, str(e))
        except VoiceRequestError as e:
            return refuse_with(e.code, e.message)
        except VoiceEngineError as e:
            raise failed(e) from None
        finally:
            for path in (clip, ref):
                if path is not None:
                    await asyncio.to_thread(path.unlink, True)
        name = voice["name"]
        title = (state.get("title") or "").strip() or f"{source.title} (as {name})"
        made = await keep(
            wav=result.wav, rate=result.sample_rate, seconds=result.seconds, title=title,
            mode="converted", description=f"{source.title}, changed to sound like {name}",
            model_id=model.id, options=req.options, seed=req.seed, parent=source.track_id,
            edit={
                "action": "convert", "voice_id": voice["id"], "voice": name,
                "from": source.kind,
            },
            load_s=result.load_s, elapsed_s=result.elapsed_s,
        )  # fmt: skip
        return {
            **made, "tracks": [made], "status": "done", "load_s": round(result.load_s, 2),
            "elapsed_s": round(result.elapsed_s, 2),
        }  # fmt: skip

    # ---- change the words -------------------------------------------------------------------

    async def speech_edit(state: dict[str, Any]) -> dict[str, Any]:
        write = get_stream_writer()
        write({"type": "node", "node": "check_request", "status": "started", "label": "Checking"})
        eng = engine()
        try:
            model = eng.resolve("edit", state.get("model") or None)
            source = await load_source(state)
        except VoiceEngineError as e:
            raise failed(e) from None
        except SourceMissing as e:
            return refuse_with("unknown_source", e.message)
        clip = None
        try:
            clip, seconds = await at_rate(source, int(model.speech_edit["input_rate"]), 1)
            req = check_speech_edit(
                model, seconds, state.get("old_text", ""), state.get("text", ""),
                state.get("options"), state.get("seed"),
            )  # fmt: skip
            write({"type": "node", "node": "speech_edit", "status": "started", "label": "Editing"})
            result = await eng.speech_edit(model, req, clip)
        except SourceMissing as e:
            return refuse_with("unreadable_audio", e.message)
        except VoiceRequestError as e:
            return refuse_with(e.code, e.message)
        except VoiceEngineError as e:
            raise failed(e) from None
        finally:
            if clip is not None:
                await asyncio.to_thread(clip.unlink, True)
        title = (state.get("title") or "").strip() or f"{source.title} (edited)"
        made = await keep(
            wav=result.wav, rate=result.sample_rate, seconds=result.seconds, title=title,
            mode="edited", description=req.new_text, model_id=model.id, options=req.options,
            seed=req.seed, parent=source.track_id,
            edit={
                "action": "speech_edit", "old_text": req.old_text, "new_text": req.new_text,
                "instruction": req.instruction, "from": source.kind,
            },
            load_s=result.load_s, elapsed_s=result.elapsed_s,
        )  # fmt: skip
        return {
            **made, "tracks": [made], "status": "done", "load_s": round(result.load_s, 2),
            "elapsed_s": round(result.elapsed_s, 2),
        }  # fmt: skip

    # ---- a talking video --------------------------------------------------------------------

    async def lipsync(state: dict[str, Any]) -> dict[str, Any]:
        write = get_stream_writer()
        write({"type": "node", "node": "check_request", "status": "started", "label": "Checking"})
        assert caps.storage is not None, "storage is required"
        eng = engine()
        ctx = require_context()
        store = store_for(app_state)
        try:
            model = eng.resolve("lipsync", state.get("model") or None)
        except VoiceEngineError as e:
            raise failed(e) from None
        try:
            picture = store.get_picture(ctx.tenant_id, ctx.user_id, str(state.get("picture")))
            png = await caps.storage.get(picture["key"])
        except (NotFound, FileNotFoundError):
            return refuse_with("unknown_picture", "Choose a picture first.")
        script = " ".join(str(state.get("text", "")).split())
        say: dict[str, Any] | None = None
        source: Source | None = None
        if script:  # words are made into speech here, so the voice is never somebody's recording
            try:
                speaker = eng.resolve("speak", None)
                text, voice_id, options = check_speak(speaker, script, state.get("voice"), None)
                write({"type": "node", "node": "speak", "status": "started", "label": "Speaking"})
                say = {"text": text, "model": speaker, "voice": voice_id, "options": options}
                spoken = await eng.speak(speaker, text, voice_id, options)
            except VoiceRequestError as e:
                return refuse_with(e.code, e.message)
            except VoiceEngineError as e:
                raise failed(e) from None
            source = Source("speech", "", spoken.wav, script[:60], None)
        else:
            try:
                source = await load_source(state)
            except SourceMissing as e:
                return refuse_with("unknown_source", e.message)
        pic = voice_wav = None
        try:
            voice_audio, seconds = await audio_input.at_rate(source.wav, "voice.wav", 16000, 1)
            req = check_lipsync(model, seconds)
            pic = await scratch_file(png, ".png")
            voice_wav = await scratch_file(voice_audio)
            write(
                {
                    "type": "node",
                    "node": "lipsync",
                    "status": "started",
                    "label": "Making the video",
                }
            )
            result = await eng.lipsync(model, req, pic, voice_wav)
        except audio_input.AudioInputError as e:
            return refuse_with(e.code, str(e))
        except VoiceRequestError as e:
            return refuse_with(e.code, e.message)
        except VoiceEngineError as e:
            raise failed(e) from None
        finally:
            for path in (pic, voice_wav):
                if path is not None:
                    await asyncio.to_thread(path.unlink, True)
        speech_id = None
        if say is not None:  # the speech is kept, as any speech made here is
            speech_id = new_id()
            key = f"speech/{speech_id}.wav"
            await caps.storage.put(key, source.wav, "audio/wav")
            store.add_speech(
                ctx.tenant_id, ctx.user_id, text=say["text"], model_id=say["model"].id,
                voice=say["voice"], options=say["options"], seconds=round(seconds, 2),
                sample_rate=say["model"].sample_rate, audio_key=key, load_s=0, elapsed_s=0,
                speech_id=speech_id,
            )  # fmt: skip
            await caps.index_creation("speech", speech_id, say["text"])
        clip_id = new_id()
        video_key = f"lipsync/{clip_id}.mp4"
        await caps.storage.put(video_key, result.mp4, "video/mp4")
        title = (
            (state.get("title") or "").strip()[:120]
            or (script or source.title)[:60]
            or "Talking video"
        )
        voice_ref = (
            {"kind": "speech", "id": speech_id}
            if speech_id
            else {"kind": source.kind, "id": source.id}
        )
        store.add_clip(
            ctx.tenant_id, ctx.user_id, title=title, model_id=model.id, picture_key=picture["key"],
            video_key=video_key, voice=voice_ref, script=script, seconds=round(result.seconds, 2),
            fps=result.fps, width=result.width, height=result.height,
            load_s=round(result.load_s, 2), elapsed_s=round(result.elapsed_s, 2), clip_id=clip_id,
        )  # fmt: skip
        store.delete_picture(
            ctx.tenant_id, ctx.user_id, picture["id"]
        )  # it belongs to the clip now
        await caps.index_creation("lipsync", clip_id, f"{title}. {script}")
        await caps.record_usage(
            CLIP_CREATED, 1, "clips", clip_id=clip_id, model=model.id,
            seconds=round(result.seconds, 2),
        )  # fmt: skip
        return {
            "clip_id": clip_id, "title": title, "video_url": await caps.storage.url(video_key),
            "seconds": round(result.seconds, 2), "elapsed_s": round(result.elapsed_s, 2),
            "load_s": round(result.load_s, 2), "status": "done",
        }  # fmt: skip

    kit = Kit(
        load_source=load_source,
        scratch_file=scratch_file,
        at_rate=at_rate,
        keep=keep,
        failed=failed,
    )

    def limited(name: str, node: Any) -> Any:
        return metered(caps, TOOLS, node, tool=name)

    return {
        "separate": limited("separate", separate),
        "convert": limited("convert", convert),
        "speech_edit": limited("speech_edit", speech_edit),
        "lipsync": lipsync,
        "kit": kit,
    }
