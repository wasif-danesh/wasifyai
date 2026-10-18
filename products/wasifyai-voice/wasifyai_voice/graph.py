# SPDX-License-Identifier: Apache-2.0
# pyright: reportTypedDictNotRequiredAccess=false
"""The audio graph (ADR-0066, stages V1 to V4): one run makes one speech (in a built-in voice, in a
voice described in words, or in a voice cloned from a recording the person saved), one piece of
music (a song or a sound effect), or works on a recording the person has (tools.py: split it into
stems, change whose voice it is, change its words).

    check_request -> speak -> finalise
        |
        v
      refuse

The graph names a task and, optionally, a model id; the engine's descriptors decide what is possible
(`wasifyai_platform_sdk.voice_models`). A request the model cannot take is refused in words before
anything is loaded; the engine's own failures end the run with a typed error."""

import asyncio
import logging
import re
from typing import Any, Literal, TypedDict, cast

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from wasifyai_platform_sdk import (
    Capabilities,
    RunError,
    VoiceEngineError,
    VoiceRequestError,
    check_clone,
    check_design,
    check_music,
    check_music_edit,
    check_speak,
    require_context,
)

from wasifyai_voice.book import build_book
from wasifyai_voice.dub import build_dub
from wasifyai_voice.runtime import NotAvailable, engine_for, store_for
from wasifyai_voice.safeguards import SONGS, SPEECHES, Guard
from wasifyai_voice.store import NotFound, new_id
from wasifyai_voice.tools import build_tools

log = logging.getLogger(__name__)

Status = Literal["working", "done", "refused"]
SPEECH_CREATED = "voice.speech"
MUSIC_CREATED = (
    "voice.music"  # a song, a sound effect or a change to one: what the daily limit counts
)


class SpeakState(TypedDict, total=False):
    # request
    text: str
    model: str  # a model id; the recommended one for speaking otherwise
    voice: str
    options: dict[str, Any]
    saved_voice: str  # the id of a saved voice (described or cloned); `voice` is for built-in ones
    # music (`task: "music"`), changing a clip (`"music_edit"`), writing lyrics (`"lyrics"`)
    task: str  # "speak" (the default), "music", "music_edit", "lyrics", or an audio tool (V4)
    source_track: str  # music_edit and the audio tools: the track to work on
    source_speech: str  # the audio tools: a speech to work on instead of a track
    stems: list[str]  # separate: the parts to keep (all when empty)
    old_text: str  # speech_edit: what the recording says now; `text` is what it should say
    tracks: list[dict[str, Any]]  # the audio tools: every track made
    picture: str  # lipsync: the id of an added picture
    picture_basis: str  # lipsync: what the person said the picture is
    voice_basis: str  # lipsync: whose voice they said it is (a script is always `generated`)
    clip_id: str
    video_url: str
    language: str  # dubbing: the language to dub into
    segments: list[
        dict[str, Any]
    ]  # dubbing: the script, a line with its times, words and translation
    background: bool  # dub_script: separate the voice from the background first
    voice_from: str  # dub: speaker | saved | builtin
    speaker_basis: str  # dub: the person's word about copying the speaker's voice
    vocals_track: str
    background_track: str
    transcribe_model: str
    separate_model: str
    fit: dict[str, Any]
    transcriber: str
    chapters: list[dict[str, Any]]  # audiobook: the approved chapters, title and text
    whole: bool  # audiobook: also one track of the whole book
    read_titles: bool  # audiobook: speak each chapter's title first (the default)
    book: dict[str, Any] | None
    edit_action: str
    edit_ranges: list[list[float]]
    strength: float
    extend_s: float
    style: str  # lyrics: the kind of music the words are for
    language: str  # lyrics: the language to write in
    music_mode: str  # song | sfx
    lyrics: str
    instrumental: bool
    duration: float
    seed: int
    title: str
    track_id: str
    # resolved
    mode: str  # speak | design | clone
    description: str
    reference_text: str
    model_id: str
    voice_id: str
    # result
    speech_id: str
    audio_url: str
    seconds: float
    sample_rate: int
    load_s: float
    elapsed_s: float
    status: Status
    refusal: dict[str, str]


LYRICS_SYSTEM = (
    "You write song lyrics. Write about {lines} lines in {language}, in sections marked on "
    "their own line with [verse], [chorus] or [bridge] (lower case, in square brackets), "
    "starting with a verse. Short singable lines, no more than about eight words each, with a "
    "repeated chorus. Answer with the lyrics only: no title, no notes, no explanation."
)


def clean_lyrics(text: str) -> str:
    """The lyrics as the music models want them: no code fences, no thinking, no preamble, section
    tags in lower case on their own lines."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"^```[a-z]*\n|\n```$", "", text.strip())
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    for i, ln in enumerate(lines):  # drop a line of preamble before the first section
        if ln.strip().startswith("["):
            lines = lines[i:]
            break
    out = [ln.lower() if re.fullmatch(r"\s*\[[A-Za-z0-9 ]+\]\s*", ln) else ln for ln in lines]
    return "\n".join(out).strip()[:5000]


def _title(description: str) -> str:
    """A name for a new track: the first words of what it was asked to be."""
    words = description.split()
    text = " ".join(words[:6])
    return (text[:60].rstrip(" ,.;") or "Untitled").capitalize()


def build_speak(caps: Capabilities, checkpointer: Any):
    app_state = caps.extras.get("app_state")

    def engine():
        try:
            return engine_for(app_state)
        except NotAvailable as e:
            raise RunError("not_available", str(e)) from None

    def refuse_with(code: str, message: str) -> SpeakState:
        return {"status": "refused", "refusal": {"code": code, "message": message}}

    guard = Guard(caps)  # ADR-0047: moderation and daily limits, only while the safeguards are on

    async def blocked(
        texts: list[str], meter: Any = None, kind: str = "text to read aloud"
    ) -> SpeakState | None:
        """A refusal when the daily limit is reached or the moderator will not allow the words."""
        refusal = (await guard.over_limit(meter) if meter else None) or await guard.words(
            *texts, kind=kind
        )
        return refuse_with(*refusal) if refusal else None

    async def check_request(state: SpeakState) -> SpeakState:
        out = await check_speech_request(state)
        if out.get("status") == "refused":
            return out
        # before any model work; the description of a designed voice is words the model will follow
        return await blocked([out.get("text", ""), out.get("description", "")], SPEECHES) or out

    async def check_speech_request(state: SpeakState) -> SpeakState:
        get_stream_writer()(
            {"type": "node", "node": "check_request", "status": "started", "label": "Checking"}
        )
        eng = engine()
        saved: dict[str, Any] | None = None
        if state.get("saved_voice"):
            ctx = require_context()
            try:
                saved = store_for(app_state).get_voice(
                    ctx.tenant_id, ctx.user_id, str(state["saved_voice"])
                )
            except NotFound:
                return refuse_with("unknown_voice", "That saved voice is no longer there.")
        task = saved["kind"] if saved else "speak"
        try:
            model = eng.resolve(task, state.get("model") or None)
        except VoiceEngineError as e:
            raise RunError(e.code, e.message) from None
        try:
            if saved and saved["kind"] == "design":
                text, description, options = check_design(
                    model, state.get("text", ""), saved["description"], state.get("options")
                )
                return {
                    "text": text, "model_id": model.id, "options": options, "mode": "design",
                    "description": description, "voice_id": "", "status": "working",
                }  # fmt: skip
            if saved:
                ref = store_for(app_state).reference_path(saved["id"])
                if not ref.is_file():
                    return refuse_with(
                        "reference_missing", "The recording of this voice is no longer there."
                    )
                seconds = float(saved["reference_seconds"] or 0)
                lo, hi = model.clone["min_seconds"], model.clone["max_seconds"]
                if not lo <= seconds <= hi:
                    return refuse_with(
                        "reference_length",
                        f"{model.title} needs a recording of {lo:g} to {hi:g} seconds.",
                    )
                text, said, options = check_clone(
                    model, state.get("text", ""), saved["reference_text"], state.get("options")
                )
                return {
                    "text": text, "model_id": model.id, "options": options, "mode": "clone",
                    "reference_text": said or "", "voice_id": "", "status": "working",
                }  # fmt: skip
            text, voice, options = check_speak(
                model, state.get("text", ""), state.get("voice") or None, state.get("options")
            )
        except VoiceRequestError as e:
            return refuse_with(e.code, e.message)
        return {
            "text": text, "model_id": model.id, "voice_id": voice or "", "options": options,
            "mode": "speak", "status": "working",
        }  # fmt: skip

    def after_check(state: SpeakState) -> str:
        return "refuse" if state.get("status") == "refused" else "speak"

    async def refuse(state: SpeakState) -> SpeakState:
        return {}

    async def speak(state: SpeakState) -> SpeakState:
        if refusal := await guard.over_limit(SPEECHES):  # again, right before the model is used
            raise RunError(*refusal)
        eng = engine()
        get_stream_writer()(
            {"type": "node", "node": "speak", "status": "started", "label": "Making the speech"}
        )
        mode = state.get("mode", "speak")
        model = eng.resolve(mode, state["model_id"])
        options = state.get("options") or {}
        try:
            if mode == "design":
                result = await eng.design(model, state["text"], state["description"], options)
            elif mode == "clone":
                path = store_for(app_state).reference_path(state["saved_voice"])
                result = await eng.clone(
                    model, state["text"], path, state.get("reference_text") or None, options
                )
            else:
                result = await eng.speak(
                    model, state["text"], state.get("voice_id") or None, options
                )
        except VoiceEngineError as e:
            raise RunError(
                e.code, e.message, retryable=e.code in ("busy", "engine_stopped")
            ) from None
        assert caps.storage is not None, "storage is required"
        speech_id = new_id()
        key = f"speech/{speech_id}.wav"
        await caps.storage.put(key, result.wav, "audio/wav")
        ctx = require_context()
        store_for(app_state).add_speech(
            ctx.tenant_id, ctx.user_id, text=state["text"], model_id=model.id,
            voice=state.get("voice_id") or None, options=options,
            seconds=round(result.seconds, 2), sample_rate=result.sample_rate, audio_key=key,
            load_s=round(result.load_s, 2), elapsed_s=round(result.elapsed_s, 2),
            speech_id=speech_id, mode=mode, saved_voice_id=state.get("saved_voice") or None,
        )  # fmt: skip
        await caps.index_creation("speech", speech_id, state["text"])  # ADR-0041
        await caps.record_usage(
            SPEECH_CREATED, 1, "speeches", speech_id=speech_id, model=model.id, mode=mode,
            seconds=round(result.seconds, 2), characters=len(state["text"]),
        )  # fmt: skip
        return {
            "speech_id": speech_id, "audio_url": await caps.storage.url(key),
            "seconds": round(result.seconds, 2), "sample_rate": result.sample_rate,
            "load_s": round(result.load_s, 2), "elapsed_s": round(result.elapsed_s, 2),
            "status": "done",
        }  # fmt: skip

    # ---- music ---------------------------------------------------------------------------

    async def check_music_request(state: SpeakState) -> SpeakState:
        out = await check_music_input(state)
        if out.get("status") == "refused":
            return out
        words = [out.get("text", ""), out.get("lyrics") or ""]
        return await blocked(words, SONGS, "description of music or song lyrics") or out

    async def check_music_input(state: SpeakState) -> SpeakState:
        get_stream_writer()(
            {"type": "node", "node": "check_request", "status": "started", "label": "Checking"}
        )
        eng = engine()
        try:
            model = eng.resolve("music", state.get("model") or None)
        except VoiceEngineError as e:
            raise RunError(e.code, e.message) from None
        try:
            req = check_music(
                model, state.get("music_mode") or "song", state.get("text", ""),
                state.get("lyrics"), bool(state.get("instrumental")), state.get("duration"),
                state.get("options"), state.get("seed"),
            )  # fmt: skip
        except VoiceRequestError as e:
            return refuse_with(e.code, e.message)
        out: SpeakState = {
            "model_id": model.id, "music_mode": req.mode, "text": req.description,
            "lyrics": req.lyrics, "instrumental": req.instrumental, "duration": req.duration,
            "options": req.options, "status": "working",
        }  # fmt: skip
        if req.seed is not None:
            out["seed"] = req.seed
        return out

    def after_music_check(state: SpeakState) -> str:
        return "refuse" if state.get("status") == "refused" else "make_music"

    async def make_music(state: SpeakState) -> SpeakState:
        if refusal := await guard.over_limit(SONGS):
            raise RunError(*refusal)
        eng = engine()
        get_stream_writer()(
            {"type": "node", "node": "make_music", "status": "started", "label": "Making the music"}
        )
        model = eng.resolve("music", state["model_id"])
        req = check_music(
            model, state["music_mode"], state["text"], state.get("lyrics"),
            bool(state.get("instrumental")), state.get("duration"), state.get("options"),
            state.get("seed"),
        )  # fmt: skip
        try:
            result = await eng.music(model, req)
        except VoiceEngineError as e:
            raise RunError(
                e.code, e.message, retryable=e.code in ("busy", "engine_stopped")
            ) from None
        assert caps.storage is not None, "storage is required"
        track_id = new_id()
        key = f"music/{track_id}.wav"
        await caps.storage.put(key, result.wav, "audio/wav")
        ctx = require_context()
        title = (state.get("title") or "").strip()[:120] or _title(req.description)
        store_for(app_state).add_track(
            ctx.tenant_id, ctx.user_id, title=title, mode=req.mode, description=req.description,
            lyrics=req.lyrics, instrumental=req.instrumental, model_id=model.id,
            options=req.options, seed=result.seed, seconds=round(result.seconds, 2),
            sample_rate=result.sample_rate, audio_key=key, load_s=round(result.load_s, 2),
            elapsed_s=round(result.elapsed_s, 2), track_id=track_id,
        )  # fmt: skip
        await caps.index_creation("track", track_id, f"{title}. {req.description}. {req.lyrics}")
        await caps.record_usage(
            MUSIC_CREATED, 1, "tracks", track_id=track_id, model=model.id, mode=req.mode,
            seconds=round(result.seconds, 2),
        )  # fmt: skip
        return {
            "track_id": track_id, "audio_url": await caps.storage.url(key), "title": title,
            "seconds": round(result.seconds, 2), "sample_rate": result.sample_rate,
            "seed": result.seed or 0, "load_s": round(result.load_s, 2),
            "elapsed_s": round(result.elapsed_s, 2), "status": "done",
        }  # fmt: skip

    # ---- changing a clip -------------------------------------------------------------------

    async def edit_music(state: SpeakState) -> SpeakState:
        eng = engine()
        get_stream_writer()(
            {
                "type": "node",
                "node": "edit_music",
                "status": "started",
                "label": "Changing the music",
            }
        )
        if stopped := await blocked(
            [str(state.get("text", ""))], SONGS, "description of music or song lyrics"
        ):
            return stopped
        ctx = require_context()
        store = store_for(app_state)
        try:
            source = store.get_track(ctx.tenant_id, ctx.user_id, str(state.get("source_track")))
        except NotFound:
            return refuse_with("unknown_track", "The music to change is no longer there.")
        try:
            model = eng.resolve("music", state.get("model") or None)
        except VoiceEngineError as e:
            raise RunError(e.code, e.message) from None
        try:
            req = check_music_edit(
                model, state.get("edit_action", ""), state.get("text", ""), source["seconds"],
                [(float(a), float(b)) for a, b in state.get("edit_ranges") or []],
                state.get("strength"), state.get("extend_s"), state.get("options"),
                state.get("seed"),
            )  # fmt: skip
        except VoiceRequestError as e:
            return refuse_with(e.code, e.message)
        assert caps.storage is not None, "storage is required"
        try:
            wav = await caps.storage.get(source["audio_key"])
        except FileNotFoundError:
            return refuse_with("unknown_track", "The sound of that music is no longer there.")
        scratch = store.root / "tmp"
        await asyncio.to_thread(scratch.mkdir, parents=True, exist_ok=True)
        clip = scratch / f"{new_id()}.wav"
        await asyncio.to_thread(clip.write_bytes, wav)
        try:
            result = await eng.music_edit(model, req, clip)
        except VoiceEngineError as e:
            raise RunError(
                e.code, e.message, retryable=e.code in ("busy", "engine_stopped")
            ) from None
        finally:
            await asyncio.to_thread(clip.unlink, missing_ok=True)
        track_id = new_id()
        key = f"music/{track_id}.wav"
        await caps.storage.put(key, result.wav, "audio/wav")
        title = (state.get("title") or "").strip()[:120] or f"{source['title']} ({req.action})"[
            :120
        ]
        edit = {
            "action": req.action, "ranges": [list(r) for r in req.ranges],
            "strength": req.strength, "extend_s": req.extend_s,
        }  # fmt: skip
        store.add_track(
            ctx.tenant_id, ctx.user_id, title=title, mode="edit", description=req.description,
            lyrics=source["lyrics"], instrumental=source["instrumental"], model_id=model.id,
            options=req.options, seed=result.seed, seconds=round(result.seconds, 2),
            sample_rate=result.sample_rate, audio_key=key, load_s=round(result.load_s, 2),
            elapsed_s=round(result.elapsed_s, 2), track_id=track_id, parent_id=source["id"],
            edit=edit,
        )  # fmt: skip
        await caps.index_creation("track", track_id, f"{title}. {req.description}")
        await caps.record_usage(
            MUSIC_CREATED, 1, "tracks", track_id=track_id, model=model.id, mode="edit",
            seconds=round(result.seconds, 2),
        )  # fmt: skip
        return {
            "track_id": track_id, "audio_url": await caps.storage.url(key), "title": title,
            "seconds": round(result.seconds, 2), "sample_rate": result.sample_rate,
            "seed": result.seed or 0, "load_s": round(result.load_s, 2),
            "elapsed_s": round(result.elapsed_s, 2), "status": "done",
        }  # fmt: skip

    # ---- writing lyrics ------------------------------------------------------------------

    async def write_lyrics(state: SpeakState) -> SpeakState:
        write = get_stream_writer()
        write({"type": "node", "node": "write_lyrics", "status": "started", "label": "Writing"})
        idea = " ".join(str(state.get("text", "")).split())[:500]
        if len(idea) < 3:
            return refuse_with("description_too_short", "Say what the song is about.")
        style_hint = " ".join(str(state.get("style", "")).split())[:200]
        if stopped := await blocked(
            [idea, style_hint], None, "description of music or song lyrics"
        ):
            return stopped
        seconds = float(state.get("duration") or 60)
        lines = int(max(8, min(40, round(seconds / 4))))
        style = " ".join(str(state.get("style", "")).split())[:200]
        language = " ".join(str(state.get("language", "") or "English").split())[:40]
        system = LYRICS_SYSTEM.format(lines=lines, language=language)
        user = f"What the song is about: {idea}" + (f"\nThe music: {style}" if style else "")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        text = ""
        for _ in range(2):
            text = ""
            try:
                async for chunk in caps.text.chat("chat", messages, None):
                    if chunk.text:
                        text += chunk.text
                        write({"type": "token", "node": "write_lyrics", "text": chunk.text})
            except RunError:
                raise
            except Exception:
                log.exception("the language model failed")
                raise RunError(
                    "language_failed",
                    "The language model did not answer. Check it in Models and try again.",
                    retryable=True,
                ) from None
            text = clean_lyrics(text)
            if len([x for x in text.splitlines() if x.strip() and not x.startswith("[")]) >= 4:
                return {"lyrics": text, "status": "done"}
            messages = [
                *messages,
                {"role": "assistant", "content": text or "(nothing)"},
                {"role": "user", "content": "That was too short. Write the full lyrics now."},
            ]
        raise RunError(
            "lyrics_failed", "The words could not be written. Try again.", retryable=True
        )

    tools = build_tools(caps, app_state, engine, refuse_with, guard)
    dubs = build_dub(caps, app_state, engine, refuse_with, tools["kit"])
    books = build_book(caps, app_state, engine, refuse_with, tools["kit"])

    def route(state: SpeakState) -> str:
        return {
            "music": "check_music", "music_edit": "edit_music", "lyrics": "write_lyrics",
            "separate": "separate", "convert": "convert", "speech_edit": "speech_edit",
            "lipsync": "lipsync", "dub_script": "dub_script", "dub": "dub",
            "audiobook": "audiobook",
        }.get(state.get("task", ""), "check_request")  # fmt: skip

    g = StateGraph(SpeakState)
    for name, fn in [
        ("check_request", check_request),
        ("check_music", check_music_request),
        ("refuse", refuse),
        ("speak", speak),
        ("make_music", make_music),
        ("edit_music", edit_music),
        ("write_lyrics", write_lyrics),
        ("separate", tools["separate"]),
        ("convert", tools["convert"]),
        ("speech_edit", tools["speech_edit"]),
        ("lipsync", tools["lipsync"]),
        ("dub_script", dubs["dub_script"]),
        ("dub", dubs["dub"]),
        ("audiobook", books["audiobook"]),
    ]:
        g.add_node(name, cast(Any, fn))
    g.add_conditional_edges(
        START,
        route,
        {
            "check_music": "check_music",
            "check_request": "check_request",
            "edit_music": "edit_music",
            "write_lyrics": "write_lyrics",
            "separate": "separate",
            "convert": "convert",
            "speech_edit": "speech_edit",
            "lipsync": "lipsync",
            "dub_script": "dub_script",
            "dub": "dub",
            "audiobook": "audiobook",
        },
    )
    for tool in (
        "separate",
        "convert",
        "speech_edit",
        "lipsync",
        "dub_script",
        "dub",
        "audiobook",
    ):
        g.add_edge(tool, END)
    g.add_edge("edit_music", END)
    g.add_edge("write_lyrics", END)
    g.add_conditional_edges(
        "check_music", after_music_check, {"refuse": "refuse", "make_music": "make_music"}
    )
    g.add_edge("make_music", END)
    g.add_conditional_edges("check_request", after_check, {"refuse": "refuse", "speak": "speak"})
    g.add_edge("refuse", END)
    g.add_edge("speak", END)
    return g.compile(checkpointer=checkpointer)
