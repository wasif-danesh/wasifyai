# SPDX-License-Identifier: Apache-2.0
"""What the voice product can do, for the action catalogue (ADR-0068): speech, saved voices, music,
the audio tools, dubbing, audiobooks, lip sync, and the kinds of creation it keeps.

Most actions are child runs of the product's graph (`task` in the graph input), so its checks
and queue are the ones the screens use. A few are direct functions on the
product's own store, the way its routes are (transcribing a recording of the library, saving a
voice). Adding an action is adding to `actions()`."""

import asyncio
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from wasifyai_platform_sdk import (
    VoiceEngineError,
    VoiceRequestError,
    check_speak,
    check_transcribe,
    process_image,
    search_text,
)
from wasifyai_platform_sdk.actions import (
    CHAT,
    Action,
    ActionContext,
    ActionRefused,
    CallBinding,
    LibraryItem,
    LibraryKind,
    Outcome,
    RunBinding,
    need_model,
    need_product,
)
from wasifyai_platform_sdk.actions.helpers import need_deps, save_copy
from wasifyai_platform_sdk.folders import PathRefused
from wasifyai_platform_sdk.media_upload import process_audio
from wasifyai_platform_sdk.uploads import UploadError
from wasifyai_platform_sdk.voice_models import MAX_DESCRIPTION_CHARS, MAX_SPEAK_CHARS

from wasifyai_voice import audio_input, audiobook, dubbing, export, reference
from wasifyai_voice.runtime import PRODUCT_ID, NotAvailable, engine_for, store_for
from wasifyai_voice.store import NotFound, VoiceStore, new_id

log = logging.getLogger(__name__)

TRANSCRIPT_INDEX_CHARS = 2000
OUTPUT_TEXT_CHARS = 2000  # how much of a transcript an action returns: a model reads it
PICTURE_MAX_SIDE = 1024
SourceKind = Literal["track", "speech"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---- what the actions reach -------------------------------------------------------------------


def _state(ctx: ActionContext) -> Any:
    return need_deps(ctx).state


def _store(ctx: ActionContext) -> VoiceStore:
    try:
        return store_for(_state(ctx))
    except NotAvailable as e:
        raise ActionRefused("unavailable", str(e)) from None


def _engine(ctx: ActionContext) -> Any:
    try:
        return engine_for(_state(ctx))
    except NotAvailable as e:
        raise ActionRefused("unavailable", str(e)) from None


def _uri(kind: str, item_id: str) -> str:
    return f"wasify://creation/{kind}/{item_id}"


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def _source(kind: str, item_id: str) -> dict[str, Any]:
    return {"source_track": item_id} if kind == "track" else {"source_speech": item_id}


async def _reindex(ctx: ActionContext, kind: str, item_id: str, text: str) -> None:
    index = getattr(_state(ctx), "creation_index", None)
    if index is None:
        return
    try:
        await index.index(ctx.actor.tenant_id, PRODUCT_ID, ctx.actor.user_id, kind, item_id, text)
    except Exception:  # the periodic check will catch up
        log.warning("the %s could not be added to search", kind, exc_info=True)


def _in_engine(call: Any) -> Any:
    """Run a check that talks to the engine, turning its two kinds of refusal into ours."""

    async def wrapped(p: Any, ctx: ActionContext) -> Any:
        try:
            return await call(p, ctx)
        except VoiceRequestError as e:
            raise ActionRefused(e.code, e.message) from None
        except VoiceEngineError as e:
            raise ActionRefused(e.code, e.message) from None

    return wrapped


# ---- outputs ----------------------------------------------------------------------------------


class SpeechOut(BaseModel):
    speech_id: str
    uri: str
    seconds: float


class TrackRef(BaseModel):
    track_id: str
    title: str
    seconds: float
    uri: str
    stem: str | None = None


class TrackOut(BaseModel):
    track_id: str
    product_id: str
    title: str
    seconds: float
    uri: str


class TracksOut(BaseModel):
    track_id: str
    tracks: list[TrackRef]


def _track_ref(t: dict[str, Any]) -> dict[str, Any]:
    return _clean(
        {
            "track_id": t["track_id"], "title": t.get("title", ""),
            "seconds": float(t.get("seconds", 0)), "uri": _uri("track", t["track_id"]),
            "stem": t.get("stem"),
        }
    )  # fmt: skip


def _tracks_result(noun: str) -> Any:
    def result(outputs: dict[str, Any], p: Any) -> Outcome | None:
        tracks = outputs.get("tracks") or []
        if outputs.get("status") != "done" or not tracks:
            return None
        refs = [_track_ref(t) for t in tracks]
        names = ", ".join(f'"{r["title"]}"' for r in refs[:6])
        return Outcome.ok(
            {"track_id": refs[0]["track_id"], "tracks": refs},
            f"{len(refs)} {noun} saved to the library: {names}.",
        )

    return result


# ---- speech.speak -----------------------------------------------------------------------------


class SpeakIn(Strict):
    text: str = Field(min_length=1, max_length=MAX_SPEAK_CHARS, description="What to say.")
    voice: str | None = Field(None, max_length=100, description="A built-in voice of the model.")
    saved_voice: str | None = Field(
        None, max_length=64, description="The id of a saved voice (voice.list), instead of voice."
    )
    model: str | None = Field(None, max_length=100, description="A model id; the best ready one.")
    options: dict[str, Any] | None = Field(None, description="The model's own options.")

    @model_validator(mode="after")
    def _one_voice(self) -> "SpeakIn":
        if self.voice and self.saved_voice:
            raise ValueError("Give either voice or saved_voice, not both.")
        return self


@_in_engine
async def _check_speak(p: SpeakIn, ctx: ActionContext) -> None:
    eng = _engine(ctx)
    if p.saved_voice:  # the graph checks the voice against its model before any work
        try:
            await asyncio.to_thread(
                _store(ctx).get_voice, ctx.actor.tenant_id, ctx.actor.user_id, p.saved_voice
            )
        except NotFound:
            raise ActionRefused("unknown_voice", "That saved voice is no longer there.") from None
        return
    check_speak(eng.resolve("speak", p.model), p.text, p.voice, p.options)


def _speak_input(p: SpeakIn, ctx: ActionContext) -> dict[str, Any]:
    return _clean(
        {"text": p.text, "voice": p.voice, "saved_voice": p.saved_voice, "model": p.model,
         "options": p.options}
    )  # fmt: skip


def _speak_result(outputs: dict[str, Any], p: SpeakIn) -> Outcome | None:
    if outputs.get("status") != "done" or not outputs.get("speech_id"):
        return None
    seconds = float(outputs.get("seconds", 0))
    return Outcome.ok(
        {"speech_id": outputs["speech_id"], "uri": _uri("speech", outputs["speech_id"]),
         "seconds": seconds},
        f"The speech was made ({seconds:.0f} seconds) and saved to the library.",
    )  # fmt: skip


# ---- speech.transcribe ------------------------------------------------------------------------


class SourceIn(Strict):
    source_kind: SourceKind = Field(
        "track", description="Whether the recording is a track or a speech."
    )
    source_id: str = Field(min_length=1, max_length=64, description="The id of the recording.")


class TranscribeIn(Strict):
    """A recording of the library (`source_kind` and `source_id`), or, for a connection with read
    folders (ADR-0069 decision 6), a file under one of them (`path`)."""

    source_kind: SourceKind = Field(
        "track", description="Whether the recording is a track or a speech."
    )
    source_id: str | None = Field(
        None, min_length=1, max_length=64, description="The id of the recording."
    )
    path: str | None = Field(
        None,
        max_length=4096,
        description=(
            "Instead of a recording of the library: the full path of an audio or video file "
            "inside a folder this connection may read."
        ),
    )
    model: str | None = Field(None, max_length=100)
    title: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def _one_source(self) -> "TranscribeIn":
        if bool(self.source_id) == bool(self.path):
            raise ValueError("give either a recording of the library or a file path, not both")
        return self


MAX_FILE_BYTES = 100 * 1024 * 1024


async def _file_recording(ctx: ActionContext, path: str) -> tuple[bytes, dict[str, Any]]:
    """A file a connection named: inside one of its read folders (spike S2's rules), decoded the
    way an upload is (the first bytes checked, a clean 16 kHz mono WAV made in a limited child
    process), never the person's file itself."""
    allowed = ctx.principal.folders if ctx.principal is not None else None
    if allowed is None:
        raise ActionRefused(
            "not_allowed",
            "Only a connection with read folders can name a file; choose a recording of the "
            "library instead.",
        )
    try:
        real = allowed.resolve(path, "read")
    except PathRefused as e:
        raise ActionRefused(e.code, e.message) from None
    size = real.stat().st_size
    rule: Any = None
    rules = getattr(getattr(ctx.deps, "state", None), "upload_rules", None)
    if callable(rules):
        rule = rules(PRODUCT_ID, "audio")
    max_bytes = rule.max_bytes if rule is not None else MAX_FILE_BYTES
    max_seconds = rule.max_seconds if rule is not None else 1800
    if size > max_bytes:
        raise ActionRefused(
            "too_large", f"That file is too large. The limit is {max_bytes // (1024 * 1024)} MB."
        )
    data = await asyncio.to_thread(real.read_bytes)
    try:
        audio = await asyncio.to_thread(process_audio, data, max_seconds)
    except UploadError as e:
        raise ActionRefused("bad_file", e.message) from None
    return audio.wav, {"title": real.name, "seconds": audio.seconds}


MAX_OUTPUT_SEGMENTS = 400


class TranscriptOut(BaseModel):
    transcript_id: str
    uri: str
    title: str
    seconds: float
    text: str  # the start of it; the whole transcript is in the library
    truncated: bool = False
    segments: list[dict[str, Any]] = Field(
        default_factory=list, description="When each stretch was said: start, end, text."
    )


async def _recording(ctx: ActionContext, kind: str, item_id: str) -> tuple[bytes, dict[str, Any]]:
    """A recording of the library: its WAV and its row."""
    deps = need_deps(ctx)
    store = _store(ctx)
    try:
        if kind == "track":
            row = await asyncio.to_thread(
                store.get_track, ctx.actor.tenant_id, ctx.actor.user_id, item_id
            )
        else:
            row = await asyncio.to_thread(
                store.get_speech, ctx.actor.tenant_id, ctx.actor.user_id, item_id
            )
        with deps.acting_as(ctx.actor, PRODUCT_ID):
            return await deps.storage.get(row["audio_key"]), row
    except (NotFound, FileNotFoundError):
        raise ActionRefused("unknown_source", "That recording is no longer there.") from None


async def _check_source(p: SourceIn, ctx: ActionContext) -> None:
    await _recording(ctx, p.source_kind, p.source_id)


async def _check_transcribe(p: TranscribeIn, ctx: ActionContext) -> None:
    if p.path:
        await _file_recording(ctx, p.path)
    else:
        await _recording(ctx, p.source_kind, str(p.source_id))


@_in_engine
async def _transcribe(p: TranscribeIn, ctx: ActionContext) -> Outcome:
    eng = _engine(ctx)
    if p.path:
        data, row = await _file_recording(ctx, p.path)
    else:
        data, row = await _recording(ctx, p.source_kind, str(p.source_id))
    chosen = eng.resolve("transcribe", p.model)
    options = check_transcribe(chosen, None)
    try:
        wav, _ = await audio_input.at_rate(data, "audio.wav", 16000, 1)
    except audio_input.AudioInputError as e:
        raise ActionRefused(e.code, str(e)) from None
    result = await eng.transcribe(chosen, wav, options)
    name = row.get("title") or row.get("text") or "Recording"
    label = (p.title or "").strip()[:200] or str(name)[:200] or "Transcript"
    saved = await asyncio.to_thread(
        _store(ctx).add_transcript, ctx.actor.tenant_id, ctx.actor.user_id, title=label,
        source_name=str(name)[:200], model_id=chosen.id, text=result.text,
        segments=[{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text}
                  for s in result.segments],
        seconds=round(result.seconds, 2), elapsed_s=round(result.elapsed_s, 2),
    )  # fmt: skip
    await _reindex(
        ctx,
        "transcript",
        saved["id"],
        search_text(saved["title"], saved["text"][:TRANSCRIPT_INDEX_CHARS]),
    )
    text = saved["text"]
    return Outcome.ok(
        {
            "transcript_id": saved["id"], "uri": _uri("transcript", saved["id"]),
            "title": saved["title"], "seconds": float(saved["seconds"]),
            "text": text[:OUTPUT_TEXT_CHARS], "truncated": len(text) > OUTPUT_TEXT_CHARS,
            "segments": [
                {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text}
                for s in result.segments[:MAX_OUTPUT_SEGMENTS]
            ],
        },
        "The recording was written down and saved to the library as a transcript:\n"
        + text[:OUTPUT_TEXT_CHARS],
    )  # fmt: skip


# ---- voice.* ----------------------------------------------------------------------------------


class VoiceListIn(Strict):
    kind: Literal["design", "clone"] | None = Field(
        None, description="Only described or only cloned."
    )


class VoiceRow(BaseModel):
    voice_id: str
    name: str
    kind: str
    description: str = ""
    uri: str


class VoiceListOut(BaseModel):
    voices: list[VoiceRow]


def _voice_row(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "voice_id": v["id"], "name": v["name"], "kind": v["kind"],
        "description": v.get("description") or "", "uri": _uri("voice", v["id"]),
    }  # fmt: skip


async def _voice_list(p: VoiceListIn, ctx: ActionContext) -> Outcome:
    rows = await asyncio.to_thread(
        _store(ctx).list_voices, ctx.actor.tenant_id, ctx.actor.user_id, p.kind
    )
    voices = [_voice_row(v) for v in rows]
    if not voices:
        return Outcome.ok({"voices": []}, "There are no saved voices yet.")
    lines = [f"- {v['name']} ({v['kind']}) id {v['voice_id']}" for v in voices[:20]]
    return Outcome.ok({"voices": voices}, "Saved voices:\n" + "\n".join(lines))


class DesignIn(Strict):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(
        min_length=3, max_length=MAX_DESCRIPTION_CHARS,
        description="The voice in words: age, tone, pace. No brackets.",
    )  # fmt: skip


class VoiceOut(BaseModel):
    voice_id: str
    name: str
    kind: str
    uri: str


async def _voice_design(p: DesignIn, ctx: ActionContext) -> Outcome:
    description = " ".join(p.description.split())
    if "(" in description or ")" in description:
        raise ActionRefused("bad_description", "Leave brackets out of the description.")
    v = await asyncio.to_thread(
        _store(ctx).add_voice, ctx.actor.tenant_id, ctx.actor.user_id, kind="design",
        name=p.name.strip(), description=description,
    )  # fmt: skip
    await _reindex(ctx, "voice", v["id"], search_text(v["name"], v["description"]))
    return Outcome.ok(
        {"voice_id": v["id"], "name": v["name"], "kind": "design", "uri": _uri("voice", v["id"])},
        f'The voice "{v["name"]}" was saved. Use its id to speak in it.',
    )


class CloneIn(SourceIn):
    name: str = Field(min_length=1, max_length=100)
    reference_text: str = Field(
        "", max_length=1000, description="What the recording says, if known."
    )


async def _voice_clone(p: CloneIn, ctx: ActionContext) -> Outcome:
    deps = need_deps(ctx)
    data, _ = await _recording(ctx, p.source_kind, p.source_id)
    try:
        wav, seconds = await reference.prepare(data, "voice.wav")
    except audio_input.AudioInputError as e:
        raise ActionRefused(e.code, str(e)) from None
    store = _store(ctx)
    vid = new_id()
    key = f"voice/{vid}.wav"
    with deps.acting_as(ctx.actor, PRODUCT_ID):
        await deps.storage.put(key, wav, "audio/wav")
    path = store.reference_path(vid)
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, wav)
    v = await asyncio.to_thread(
        store.add_voice, ctx.actor.tenant_id, ctx.actor.user_id, kind="clone",
        name=p.name.strip(), reference_key=key, reference_text=" ".join(p.reference_text.split()),
        reference_seconds=round(seconds, 2), voice_id=vid,
    )  # fmt: skip
    await _reindex(
        ctx, "voice", v["id"], search_text(v["name"], v["description"] or "cloned voice")
    )
    return Outcome.ok(
        {"voice_id": v["id"], "name": v["name"], "kind": "clone", "uri": _uri("voice", v["id"])},
        f'The voice "{v["name"]}" was saved from that recording. Use its id to speak in it.',
    )


class ConvertIn(SourceIn):
    saved_voice: str = Field(
        min_length=1, max_length=64, description="A cloned voice (voice.list)."
    )
    model: str | None = Field(None, max_length=100)
    title: str | None = Field(None, max_length=120)
    seed: int | None = Field(None, ge=0)


def _convert_input(p: ConvertIn, ctx: ActionContext) -> dict[str, Any]:
    return _clean(
        {"task": "convert", **_source(p.source_kind, p.source_id), "saved_voice": p.saved_voice,
         "model": p.model, "title": p.title, "seed": p.seed}
    )  # fmt: skip


class EditSpeechIn(SourceIn):
    old_text: str = Field(min_length=1, max_length=1000, description="What the recording says now.")
    text: str = Field(min_length=1, max_length=1000, description="What it should say instead.")
    model: str | None = Field(None, max_length=100)
    title: str | None = Field(None, max_length=120)
    seed: int | None = Field(None, ge=0)


def _edit_speech_input(p: EditSpeechIn, ctx: ActionContext) -> dict[str, Any]:
    return _clean(
        {"task": "speech_edit", **_source(p.source_kind, p.source_id), "old_text": p.old_text,
         "text": p.text, "model": p.model, "title": p.title, "seed": p.seed}
    )  # fmt: skip


def _single_track_result(outputs: dict[str, Any], p: Any) -> Outcome | None:
    if outputs.get("status") != "done" or not outputs.get("track_id"):
        return None
    title, secs = str(outputs.get("title", "")), float(outputs.get("seconds", 0))
    return Outcome.ok(
        {"track_id": outputs["track_id"], "product_id": PRODUCT_ID, "title": title,
         "seconds": secs, "uri": _uri("track", outputs["track_id"])},
        f'The recording "{title}" was made ({secs:.0f} seconds) and saved to the library.',
    )  # fmt: skip


# ---- music ------------------------------------------------------------------------------------

MAX_MUSIC_SECONDS = 120


class MusicIn(Strict):
    description: str = Field(
        min_length=1, max_length=500,
        description="The style and mood in a few words, in English: genre, mood, instruments.",
    )  # fmt: skip
    lyrics: str | None = Field(None, max_length=5000, description="The words to sing, if any.")
    instrumental: bool = Field(False, description="No singing.")
    seconds: float = Field(30, ge=5, le=MAX_MUSIC_SECONDS, description="Length in seconds.")
    mode: Literal["song", "sfx"] = Field("song", description="A song, or a sound effect.")
    title: str | None = Field(None, max_length=120)
    seed: int | None = Field(None, ge=0)
    model: str | None = Field(None, max_length=100)


def _music_input(p: MusicIn, ctx: ActionContext) -> dict[str, Any]:
    out: dict[str, Any] = {"task": "music", "text": p.description, "duration": p.seconds}
    if p.lyrics:
        out["lyrics"] = p.lyrics
    elif p.instrumental:
        out["instrumental"] = True
    if p.mode != "song":
        out["music_mode"] = p.mode
    return out | _clean({"title": p.title, "seed": p.seed, "model": p.model})


def _music_result(outputs: dict[str, Any], p: MusicIn) -> Outcome | None:
    if outputs.get("status") != "done" or not outputs.get("track_id"):
        return None
    title, secs = str(outputs.get("title", "")), float(outputs.get("seconds", 0))
    return Outcome.ok(
        {"track_id": outputs["track_id"], "product_id": PRODUCT_ID, "title": title,
         "seconds": secs, "uri": _uri("track", outputs["track_id"])},
        f'The music "{title}" was made ({secs:.0f} seconds) and saved to the library.',
    )  # fmt: skip


class LyricsIn(Strict):
    idea: str = Field(min_length=3, max_length=500, description="What the song is about.")
    style: str | None = Field(None, max_length=200, description="The kind of music it is for.")
    language: str | None = Field(None, max_length=40, description="The language to write in.")
    seconds: float | None = Field(
        None, ge=5, le=MAX_MUSIC_SECONDS, description="How long the song is."
    )


class LyricsOut(BaseModel):
    lyrics: str


def _lyrics_input(p: LyricsIn, ctx: ActionContext) -> dict[str, Any]:
    return _clean(
        {"task": "lyrics", "text": p.idea, "style": p.style, "language": p.language,
         "duration": p.seconds}
    )  # fmt: skip


def _lyrics_result(outputs: dict[str, Any], p: LyricsIn) -> Outcome | None:
    lyrics = str(outputs.get("lyrics") or "")
    if outputs.get("status") != "done" or not lyrics:
        return None
    return Outcome.ok({"lyrics": lyrics}, f"The lyrics:\n{lyrics}")


class SeparateIn(SourceIn):
    stems: list[str] | None = Field(
        None, max_length=8, description="Which parts to keep; all if omitted."
    )
    model: str | None = Field(None, max_length=100)


def _separate_input(p: SeparateIn, ctx: ActionContext) -> dict[str, Any]:
    return _clean(
        {"task": "separate", **_source(p.source_kind, p.source_id), "stems": p.stems,
         "model": p.model}
    )  # fmt: skip


# ---- dubbing ----------------------------------------------------------------------------------


class DubScriptIn(SourceIn):
    language: str = Field(
        min_length=2, max_length=10, description="The language to dub into (en, fr ...)."
    )
    background: bool = Field(
        False, description="Separate the voice from the music behind it first."
    )


class DubLine(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    source: str = Field("", max_length=2000, description="What was said.")
    text: str = Field(
        min_length=1, max_length=2000, description="What it becomes in the new language."
    )


class DubScriptOut(BaseModel):
    language: str
    segments: list[DubLine]
    vocals_track: str | None = None
    background_track: str | None = None


def _dub_script_input(p: DubScriptIn, ctx: ActionContext) -> dict[str, Any]:
    return {"task": "dub_script", **_source(p.source_kind, p.source_id), "language": p.language,
            "background": p.background}  # fmt: skip


def _dub_script_result(outputs: dict[str, Any], p: DubScriptIn) -> Outcome | None:
    segments = outputs.get("segments") or []
    if outputs.get("status") != "done" or not segments:
        return None
    lines = [{k: s[k] for k in ("start", "end", "source", "text")} for s in segments]
    shown = "\n".join(f"{s['start']:.1f}-{s['end']:.1f}: {s['text']}" for s in lines[:30])
    return Outcome.ok(
        _clean(
            {"language": outputs.get("language", p.language), "segments": lines,
             "vocals_track": outputs.get("vocals_track"),
             "background_track": outputs.get("background_track")}
        ),
        f"The script for the dub, {len(lines)} lines. Change any line, then make the dub:\n{shown}",
    )  # fmt: skip


class DubMakeIn(SourceIn):
    language: str = Field(min_length=2, max_length=10)
    segments: list[DubLine] = Field(min_length=1, max_length=dubbing.MAX_SEGMENTS)
    voice_from: Literal["builtin", "saved"] = Field(
        "builtin", description="A built-in voice, or a saved voice (saved_voice)."
    )
    voice: str | None = Field(None, max_length=100)
    saved_voice: str | None = Field(None, max_length=64)
    vocals_track: str | None = Field(None, max_length=64, description="From dub.script.")
    background_track: str | None = Field(None, max_length=64, description="From dub.script.")
    title: str | None = Field(None, max_length=120)

    @model_validator(mode="after")
    def _saved(self) -> "DubMakeIn":
        if self.voice_from == "saved" and not self.saved_voice:
            raise ValueError("Say which saved voice to use (saved_voice).")
        return self


def _dub_make_input(p: DubMakeIn, ctx: ActionContext) -> dict[str, Any]:
    return _clean(
        {"task": "dub", **_source(p.source_kind, p.source_id), "language": p.language,
         "segments": [s.model_dump() for s in p.segments], "voice_from": p.voice_from,
         "voice": p.voice, "saved_voice": p.saved_voice, "vocals_track": p.vocals_track,
         "background_track": p.background_track, "title": p.title}
    )  # fmt: skip


# ---- audiobooks -------------------------------------------------------------------------------


class BookPlanIn(Strict):
    text: str = Field(min_length=1, max_length=audiobook.MAX_BOOK_CHARS * 2)
    target: int = Field(
        audiobook.TARGET_CHAPTER_CHARS, ge=1000, le=audiobook.MAX_CHAPTER_CHARS // 2
    )


class ChapterRow(BaseModel):
    title: str
    chars: int
    estimated_seconds: int


class BookPlanOut(BaseModel):
    chapters: list[ChapterRow]
    chars: int
    estimated_seconds: int


async def _book_plan(p: BookPlanIn, ctx: ActionContext) -> Outcome:
    try:
        chapters = audiobook.plan_chapters(p.text, p.target)
    except audiobook.BookError as e:
        raise ActionRefused(e.code, str(e)) from None
    rows: list[dict[str, Any]] = []
    for ch in chapters:
        pub = ch.public()
        rows.append(
            {
                "title": ch.title,
                "chars": int(str(pub["chars"])),
                "estimated_seconds": int(str(pub["estimated_seconds"])),
            }
        )
    total = sum(int(r["estimated_seconds"]) for r in rows)
    return Outcome.ok(
        {
            "chapters": rows,
            "chars": sum(int(r["chars"]) for r in rows),
            "estimated_seconds": total,
        },
        f"{len(rows)} chapters, about {total // 60} minutes spoken. Nothing was made yet.",
    )


class BookMakeIn(Strict):
    text: str = Field(
        min_length=1, max_length=audiobook.MAX_BOOK_CHARS * 2,
        description="The book. The chapters are found in it as audiobook.plan shows.",
    )  # fmt: skip
    title: str = Field("Audiobook", max_length=120)
    whole: bool = Field(False, description="Also make one track of the whole book.")
    read_titles: bool = Field(True, description="Speak each chapter's title first.")
    voice: str | None = Field(None, max_length=100)
    saved_voice: str | None = Field(None, max_length=64)
    model: str | None = Field(None, max_length=100)


async def _book_input(p: BookMakeIn, ctx: ActionContext) -> dict[str, Any]:
    try:
        chapters = audiobook.plan_chapters(p.text)
    except audiobook.BookError as e:
        raise ActionRefused(e.code, str(e)) from None
    return _clean(
        {"task": "audiobook", "chapters": [{"title": c.title, "text": c.text} for c in chapters],
         "title": p.title, "whole": p.whole, "read_titles": p.read_titles, "voice": p.voice,
         "saved_voice": p.saved_voice, "model": p.model}
    )  # fmt: skip


def _book_result(outputs: dict[str, Any], p: BookMakeIn) -> Outcome | None:
    return _tracks_result("tracks of the audiobook")(outputs, p)


# ---- lip sync ---------------------------------------------------------------------------------


class LipSyncIn(Strict):
    image_id: str = Field(min_length=1, max_length=64, description="The picture, from the library.")
    text: str | None = Field(None, max_length=1000, description="Words for the face to say.")
    source_kind: SourceKind | None = Field(None, description="Or a recording of the library.")
    source_id: str | None = Field(None, max_length=64)
    voice: str | None = Field(None, max_length=100, description="A built-in voice for the words.")
    title: str | None = Field(None, max_length=120)
    model: str | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def _one_voice(self) -> "LipSyncIn":
        if bool(self.text) == bool(self.source_id):
            raise ValueError("Give either text for the face to say, or a recording (source_id).")
        if self.source_id and not self.source_kind:
            raise ValueError("Say whether the recording is a track or a speech (source_kind).")
        return self


class ClipOut(BaseModel):
    clip_id: str
    title: str
    seconds: float
    uri: str


async def _lipsync_input(p: LipSyncIn, ctx: ActionContext) -> dict[str, Any]:
    deps = need_deps(ctx)
    picture = ctx.library.get("image")
    data = await picture.read(ctx, p.image_id) if picture and picture.read else None
    if data is None:
        raise ActionRefused("not_found", "That picture is not in the library.")
    try:
        clean = await asyncio.to_thread(process_image, data, PICTURE_MAX_SIDE)
    except UploadError as e:
        raise ActionRefused("bad_picture", e.message) from None
    pid = new_id()
    key = f"lipsync/pictures/{pid}.png"
    with deps.acting_as(ctx.actor, PRODUCT_ID):
        await deps.storage.put(key, clean.png, "image/png")
    await asyncio.to_thread(
        _store(ctx).add_picture, ctx.actor.tenant_id, ctx.actor.user_id, key=key,
        width=clean.width, height=clean.height, picture_id=pid,
    )  # fmt: skip
    graph: dict[str, Any] = {"task": "lipsync", "picture": pid}
    if p.text:
        graph["text"] = p.text
        if p.voice:
            graph["voice"] = p.voice
    else:
        assert p.source_kind and p.source_id
        graph |= _source(p.source_kind, p.source_id)
    return graph | _clean({"title": p.title, "model": p.model})


async def _lipsync_check(p: LipSyncIn, ctx: ActionContext) -> None:
    picture = ctx.library.get("image")
    if picture is None or picture.get is None or await picture.get(ctx, p.image_id) is None:
        raise ActionRefused("not_found", "That picture is not in the library.")
    if p.source_id and p.source_kind:
        await _recording(ctx, p.source_kind, p.source_id)


def _lipsync_result(outputs: dict[str, Any], p: LipSyncIn) -> Outcome | None:
    if outputs.get("status") != "done" or not outputs.get("clip_id"):
        return None
    secs = float(outputs.get("seconds", 0))
    title = str(outputs.get("title", ""))
    return Outcome.ok(
        {"clip_id": outputs["clip_id"], "title": title, "seconds": secs,
         "uri": _uri("lipsync", outputs["clip_id"])},
        f'The talking video "{title}" was made ({secs:.0f} seconds) and saved to the library.',
    )  # fmt: skip


# ---- the catalogue ----------------------------------------------------------------------------

HERE = need_product(PRODUCT_ID)
SAMPLE_ID = "0b7c1f9e-0000-4000-8000-000000000000"  # for the examples
SAMPLE_VOICE = "5c1d0e2a-0000-4000-8000-000000000000"


def _run(noun: str, build: Any, result: Any, check: Any = None) -> RunBinding:
    return RunBinding(PRODUCT_ID, noun, build, result, check=check)


def actions() -> list[Action]:
    return [
        Action(
            id="speech.speak", title="Text to speech",
            summary="Read a text aloud in a voice and save it.",
            description=(
                "Read a text aloud and save the recording to the person's library. Use it when "
                "the person asks to hear a text, read something aloud, or make a voice-over. "
                "Choose a built-in voice (voice), a saved voice (saved_voice, from voice.list), "
                "or leave both out. Takes a few seconds to a minute; returns the speech id."
            ),
            input=SpeakIn, output=SpeechOut,
            examples=({"text": "Hello, and welcome."},
                      {"text": "Good evening.", "saved_voice": SAMPLE_VOICE}),
            effect="make", requires=(HERE, need_model("speak")), long=True, product=PRODUCT_ID,
            bind=_run("speech", _speak_input, _speak_result, _check_speak), ui="voice.speak",
        ),
        Action(
            id="speech.transcribe", title="Speech to text",
            summary="Write down what a recording of the library says.",
            description=(
                "Write down what a recording in the library says (a track or a speech) and save "
                "it as a transcript. Returns the start of the text and the transcript's id."
            ),
            input=TranscribeIn, output=TranscriptOut,
            examples=({"source_kind": "track", "source_id": SAMPLE_ID},),
            effect="make", flags=("private",), requires=(HERE, need_model("transcribe")), long=True,
            product=PRODUCT_ID, bind=CallBinding(_transcribe, check=_check_transcribe),
            ui="voice.transcribe",
        ),
        Action(
            id="voice.list", title="My saved voices",
            summary="List the voices the person saved.",
            description=(
                "List the saved voices (described in words, or cloned from a recording) with "
                "their ids, to use as saved_voice in speech.speak, audiobook.make and the others."
            ),
            input=VoiceListIn, output=VoiceListOut, examples=({}, {"kind": "clone"}),
            effect="read", flags=("private",), requires=(HERE,), product=PRODUCT_ID,
            bind=CallBinding(_voice_list), ui="voice.voices",
        ),
        Action(
            id="voice.design", title="Describe a voice",
            summary="Save a voice described in words.",
            description=(
                "Save a new voice described in words (age, tone, pace) so it can be used again. "
                "No recording is involved. Returns the voice id."
            ),
            input=DesignIn, output=VoiceOut,
            examples=({"name": "Calm narrator", "description": "a calm woman, slow and warm"},),
            effect="make", requires=(HERE,), product=PRODUCT_ID, bind=CallBinding(_voice_design),
            ui="voice.voices",
        ),
        Action(
            id="voice.clone", title="Copy a voice",
            summary="Save a voice cloned from a recording.",
            description=(
                "Save a voice cloned from a recording of the library (2 to 30 seconds of one "
                "person speaking clearly). Returns the voice id."
            ),
            input=CloneIn, output=VoiceOut,
            examples=({"source_kind": "speech", "source_id": SAMPLE_ID,
                       "name": "My voice"},),
            effect="make", flags=("private",), requires=(HERE,), product=PRODUCT_ID,
            bind=CallBinding(_voice_clone, check=_check_source),
            ui="voice.voices",
        ),
        Action(
            id="voice.convert", title="Change a voice",
            summary="Make a recording sound like a saved cloned voice.",
            description=(
                "Make a recording of the library sound like one of the person's cloned voices "
                "(voice.list, kind clone). Keeps the original and saves the result as a new track."
            ),
            input=ConvertIn, output=TrackOut,
            examples=({"source_kind": "track", "source_id": SAMPLE_ID,
                       "saved_voice": SAMPLE_VOICE},),
            effect="make", flags=("private",), requires=(HERE, need_model("convert")), long=True,
            product=PRODUCT_ID, ui="voice.convert",
            bind=_run("recording", _convert_input, _single_track_result, _check_source),
        ),
        Action(
            id="voice.edit_speech", title="Edit speech",
            summary="Change some words in a recording.",
            description=(
                "Change some of the words a recording says, keeping the voice: give what it says "
                "now (old_text) and what it should say (text). Saves the result as a new track."
            ),
            input=EditSpeechIn, output=TrackOut,
            examples=({"source_kind": "speech", "source_id": SAMPLE_ID,
                       "old_text": "meet at noon", "text": "meet at one"},),
            effect="make", flags=("private",), requires=(HERE, need_model("edit")), long=True,
            product=PRODUCT_ID, ui="voice.edit",
            bind=_run("recording", _edit_speech_input, _single_track_result, _check_source),
        ),
        Action(
            id="music.generate", title="Make music",
            summary="Make a piece of music, a song or a sound effect.",
            description=(
                "Make a piece of music or a song and save it to the person's library. Use it "
                "when the person asks you to compose, make or write music, a song or a tune. "
                "Describe the style in a few words in English (genre, mood, instruments). Add "
                "lyrics only if the person gave them or asked for a song with words. Takes about "
                "a minute for 30 seconds."
            ),
            input=MusicIn, output=TrackOut,
            examples=({"description": "calm piano, rainy evening"},
                      {"description": "upbeat pop", "lyrics": "[verse]\nSun", "seconds": 60}),
            effect="make", flags=("costly",), requires=(HERE, need_model("music")), long=True,
            product=PRODUCT_ID, bind=_run("music", _music_input, _music_result), ui="music.create",
        ),
        Action(
            id="music.lyrics", title="Write lyrics",
            summary="Write song lyrics from an idea.",
            description=(
                "Write song lyrics in sections ([verse], [chorus]) from an idea, to read or to "
                "give to music.generate. Nothing is saved."
            ),
            input=LyricsIn, output=LyricsOut,
            examples=({"idea": "a song about a lighthouse keeper", "style": "folk"},),
            effect="make", requires=(HERE, CHAT), long=True, product=PRODUCT_ID,
            bind=_run("lyrics", _lyrics_input, _lyrics_result), ui="music.lyrics",
        ),
        Action(
            id="music.separate", title="Split into parts",
            summary="Split a recording into its voice, drums, bass and so on.",
            description=(
                "Split a recording of the library into parts (vocals, drums, bass, other). Each "
                "part is saved as a new track."
            ),
            input=SeparateIn, output=TracksOut,
            examples=({"source_kind": "track", "source_id": SAMPLE_ID,
                       "stems": ["vocals"]},),
            effect="make", flags=("private",), requires=(HERE, need_model("separate")), long=True,
            product=PRODUCT_ID, ui="music.separate",
            bind=_run("parts", _separate_input, _tracks_result("parts"), _check_source),
        ),
        Action(
            id="dub.script", title="Write the dub script",
            summary="Write down a recording and translate it, line by line, for a dub.",
            description=(
                "The first step of dubbing a recording into another language: writes down what "
                "is said and translates it line by line with the times. Check or change the "
                "lines, then call dub.make with them. Nothing is spoken yet."
            ),
            input=DubScriptIn, output=DubScriptOut,
            examples=({"source_kind": "track", "source_id": SAMPLE_ID,
                       "language": "fr"},),
            effect="make", flags=("private",), requires=(HERE, need_model("transcribe"), CHAT),
            long=True, product=PRODUCT_ID, ui="voice.dub",
            bind=_run("script", _dub_script_input, _dub_script_result, _check_source),
        ),
        Action(
            id="dub.make", title="Dub a recording",
            summary="Speak the script in the new language and mix it with the background.",
            description=(
                "The second step of dubbing: speaks the (checked) lines of dub.script in the new "
                "language and saves the dub as a new track. Copying the original speaker's voice "
                "is not offered here: use a built-in or a saved voice."
            ),
            input=DubMakeIn, output=TrackOut,
            examples=({"source_kind": "track", "source_id": SAMPLE_ID,
                       "language": "fr",
                       "segments": [{"start": 0.0, "end": 2.5, "text": "Bonjour à tous."}]},),
            effect="make", flags=("private",), requires=(HERE, need_model("speak")), long=True,
            product=PRODUCT_ID, ui="voice.dub",
            bind=_run("dub", _dub_make_input, _single_track_result, _check_source),
        ),
        Action(
            id="audiobook.plan", title="Find the chapters",
            summary="Split a long text into chapters and estimate the time.",
            description=(
                "Find the chapters of a long text and how long each takes to read aloud. Nothing "
                "is spoken or kept. Use it before audiobook.make."
            ),
            input=BookPlanIn, output=BookPlanOut,
            examples=({"text": "Chapter 1\nOnce upon a time..."},),
            effect="read", requires=(HERE,), product=PRODUCT_ID, bind=CallBinding(_book_plan),
            ui="voice.audiobook",
        ),
        Action(
            id="audiobook.make", title="Make an audiobook",
            summary="Read a whole book aloud, one track per chapter.",
            description=(
                "Read a long text aloud as an audiobook: one track per chapter, optionally one "
                "track of the whole. It can take a long time; it returns a job handle."
            ),
            input=BookMakeIn, output=TracksOut,
            examples=({"text": "Chapter 1\nOnce upon a time...", "title": "Story"},),
            effect="make", flags=("costly",), requires=(HERE, need_model("speak")), long=True,
            product=PRODUCT_ID, ui="voice.audiobook",
            bind=_run("audiobook", _book_input, _book_result),
        ),
        Action(
            id="lipsync.make", title="Lip sync",
            summary="Make a picture talk.",
            description=(
                "Make a picture of the library talk: a video of the face saying words (made into "
                "speech here) or a recording."
            ),
            input=LipSyncIn, output=ClipOut,
            examples=({"image_id": SAMPLE_ID,
                       "text": "Hello, I am your guide."},),
            effect="make", flags=("costly", "private"),
            requires=(HERE, need_model("lipsync")), long=True, product=PRODUCT_ID,
            ui="voice.lipsync",
            bind=_run("talking video", _lipsync_input, _lipsync_result, _lipsync_check),
        ),
    ]  # fmt: skip


# ---- what the voice product keeps -------------------------------------------------------------


def _when(value: Any) -> str | None:
    return str(value) if value else None


def _speech_item(s: dict[str, Any]) -> LibraryItem:
    return LibraryItem(
        kind="speech", id=s["id"], title=str(s["text"])[:120],
        created_at=_when(s.get("created_at")),
        detail={"seconds": s["seconds"], "model": s["model_id"]},
    )  # fmt: skip


def _track_item(t: dict[str, Any]) -> LibraryItem:
    return LibraryItem(
        kind="track", id=t["id"], title=t["title"], created_at=_when(t.get("created_at")),
        detail={"seconds": t["seconds"], "mode": t["mode"], "favourite": bool(t["favourite"])},
    )  # fmt: skip


def _transcript_item(t: dict[str, Any]) -> LibraryItem:
    return LibraryItem(
        kind="transcript", id=t["id"], title=t["title"], created_at=_when(t.get("created_at")),
        detail={"seconds": t["seconds"], "chars": len(t.get("text") or "")},
    )  # fmt: skip


def _voice_item(v: dict[str, Any]) -> LibraryItem:
    return LibraryItem(
        kind="voice", id=v["id"], title=v["name"], created_at=_when(v.get("created_at")),
        detail={"voice_kind": v["kind"]},
    )  # fmt: skip


def _clip_item(c: dict[str, Any]) -> LibraryItem:
    return LibraryItem(
        kind="lipsync", id=c["id"], title=c["title"], created_at=_when(c.get("created_at")),
        detail={"seconds": c["seconds"], "width": c["width"], "height": c["height"]},
    )  # fmt: skip


def _lister(method: str, to_item: Any) -> Any:
    async def list_(ctx: ActionContext, limit: int) -> list[LibraryItem]:
        rows = await asyncio.to_thread(
            getattr(_store(ctx), method), ctx.actor.tenant_id, ctx.actor.user_id, None, limit
        )
        return [to_item(r) for r in rows]

    return list_


def _getter(method: str, to_item: Any) -> Any:
    async def get(ctx: ActionContext, item_id: str) -> LibraryItem | None:
        try:
            row = await asyncio.to_thread(
                getattr(_store(ctx), method), ctx.actor.tenant_id, ctx.actor.user_id, item_id
            )
        except NotFound:
            return None
        return to_item(row)

    return get


async def _list_voices(ctx: ActionContext, limit: int) -> list[LibraryItem]:
    rows = await asyncio.to_thread(_store(ctx).list_voices, ctx.actor.tenant_id, ctx.actor.user_id)
    return [_voice_item(v) for v in rows[:limit]]


def _deleter(method: str, keys: tuple[str, ...]) -> Any:
    """Delete a row, then its files, then its place in search: what the route does."""

    async def delete(ctx: ActionContext, item_id: str) -> bool:
        deps = need_deps(ctx)
        try:
            gone = await asyncio.to_thread(
                getattr(_store(ctx), method), ctx.actor.tenant_id, ctx.actor.user_id, item_id
            )
        except NotFound:
            return False
        if isinstance(gone, dict):
            with deps.acting_as(ctx.actor, PRODUCT_ID):
                for key in (gone.get(k) for k in keys):
                    if not key:
                        continue
                    try:
                        await deps.storage.delete(key)
                    except FileNotFoundError:
                        pass
        await deps.unindex(ctx.actor, PRODUCT_ID, item_id)
        return True

    return delete


async def _rename_track(ctx: ActionContext, item_id: str, title: str) -> bool:
    try:
        t = await asyncio.to_thread(
            _store(ctx).rename_track, ctx.actor.tenant_id, ctx.actor.user_id, item_id, title
        )
    except NotFound:
        return False
    await _reindex(
        ctx,
        "track",
        t["id"],
        search_text(t["title"], t["description"], t["lyrics"][:TRANSCRIPT_INDEX_CHARS]),
    )
    return True


async def _rename_transcript(ctx: ActionContext, item_id: str, title: str) -> bool:
    try:
        t = await asyncio.to_thread(
            _store(ctx).rename_transcript, ctx.actor.tenant_id, ctx.actor.user_id, item_id, title
        )
    except NotFound:
        return False
    await _reindex(
        ctx, "transcript", t["id"], search_text(t["title"], t["text"][:TRANSCRIPT_INDEX_CHARS])
    )
    return True


async def _rename_voice(ctx: ActionContext, item_id: str, title: str) -> bool:
    try:
        v = await asyncio.to_thread(
            _store(ctx).update_voice, ctx.actor.tenant_id, ctx.actor.user_id, item_id, name=title
        )
    except NotFound:
        return False
    await _reindex(
        ctx, "voice", v["id"], search_text(v["name"], v["description"] or "cloned voice")
    )
    return True


async def _rename_clip(ctx: ActionContext, item_id: str, title: str) -> bool:
    try:
        c = await asyncio.to_thread(
            _store(ctx).update_clip, ctx.actor.tenant_id, ctx.actor.user_id, item_id, title=title
        )
    except NotFound:
        return False
    await _reindex(
        ctx, "lipsync", c["id"], search_text(c["title"], c["script"][:TRANSCRIPT_INDEX_CHARS])
    )
    return True


def _reader(getter: str, key: str) -> Any:
    """A recording's bytes, for what brings it somewhere else (a project of scenes, ADR-0096)."""

    async def read(ctx: ActionContext, item_id: str) -> bytes | None:
        deps = need_deps(ctx)
        try:
            row = await asyncio.to_thread(
                getattr(_store(ctx), getter), ctx.actor.tenant_id, ctx.actor.user_id, item_id
            )
            with deps.acting_as(ctx.actor, PRODUCT_ID):
                return await deps.storage.get(row[key])
        except (KeyError, LookupError, FileNotFoundError):
            return None

    return read


def _exporter(method: str, key: str, ext: str, name: str) -> Any:
    async def export_(ctx: ActionContext, item_id: str, folder: Path) -> Path | None:
        deps = need_deps(ctx)
        try:
            row = await asyncio.to_thread(
                getattr(_store(ctx), method), ctx.actor.tenant_id, ctx.actor.user_id, item_id
            )
            with deps.acting_as(ctx.actor, PRODUCT_ID):
                data = await deps.storage.get(row[key])
        except (NotFound, FileNotFoundError):
            return None
        stem = export.file_name(str(row[name]), "x").rsplit(".", 1)[0]
        return await asyncio.to_thread(save_copy, folder, stem, ext, data)

    return export_


async def _export_transcript(ctx: ActionContext, item_id: str, folder: Path) -> Path | None:
    try:
        t = await asyncio.to_thread(
            _store(ctx).get_transcript, ctx.actor.tenant_id, ctx.actor.user_id, item_id
        )
    except NotFound:
        return None
    stem = export.file_name(t["title"], "x").rsplit(".", 1)[0]
    return await asyncio.to_thread(save_copy, folder, stem, "txt", export.render(t, "txt").encode())


def library_kinds() -> list[LibraryKind]:
    return [
        LibraryKind(
            "speech", PRODUCT_ID, "speech", _lister("list_speeches", _speech_item),
            _getter("get_speech", _speech_item), _deleter("delete_speech", ("audio_key",)),
            None, _exporter("get_speech", "audio_key", "wav", "text"),
            _reader("get_speech", "audio_key"),
        ),
        LibraryKind(
            "track", PRODUCT_ID, "song", _lister("list_tracks", _track_item),
            _getter("get_track", _track_item), _deleter("delete_track", ("audio_key",)),
            _rename_track, _exporter("get_track", "audio_key", "wav", "title"),
            _reader("get_track", "audio_key"),
        ),
        LibraryKind(
            "transcript", PRODUCT_ID, "transcript", _lister("list_transcripts", _transcript_item),
            _getter("get_transcript", _transcript_item),
            _deleter("delete_transcript", ()), _rename_transcript, _export_transcript,
        ),
        LibraryKind(
            "voice", PRODUCT_ID, "voice", _list_voices, _getter("get_voice", _voice_item),
            _deleter("delete_voice", ("reference_key",)), _rename_voice, None,
        ),
        LibraryKind(
            "lipsync", PRODUCT_ID, "talking video", _lister("list_clips", _clip_item),
            _getter("get_clip", _clip_item),
            _deleter("delete_clip", ("video_key", "picture_key")), _rename_clip,
            _exporter("get_clip", "video_key", "mp4", "title"),
        ),
    ]  # fmt: skip


__all__ = ["actions", "library_kinds"]
