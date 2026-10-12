# pyright: reportTypedDictNotRequiredAccess=false
# (Graph state is filled in node by node; a node only reads keys that earlier nodes have set.)
"""The lip sync graph: checks, a voice job when needed, the clip job, finish (ADR-0044).

    check_request -> begin -> [ voice_start -> voice_await -> voice_finish ] -> start_job
        |                                                          |             -> await_job
        v                                                          v             -> finalise
      refuse                                                    refuse

The voice comes in two ways. A *script* is made into speech first (text to speech, ADR-0042). An
uploaded or recorded *audio* file is used as it is; while the safeguards are on (ADR-0047) it is
first transcribed (ADR-0043) so that what it says can be moderated. Graph code names capabilities
(`text.moderate_image`, `speech.synthesize`, `speech.transcribe`, `video.lipsync`), never models.

The row is created when the work starts, with status "working", so the site can show "being made" on
any page. The user's picture and voice are deleted as soon as they are no longer needed."""

import json
import logging
import math
import re
import secrets
from typing import Any, Literal, TypedDict, cast
from uuid import uuid4

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from wasifyai_platform_sdk import (
    Capabilities,
    InMemoryUploadStore,
    JobFailed,
    PostgresUploadStore,
    RunError,
    UploadRecord,
    UploadStore,
    await_job,
    require_context,
)
from wasifyai_stt.languages import load_languages
from wasifyai_tts.speeches import SpeechError, wav_seconds
from wasifyai_tts.voices import NoVoice, load_catalog

from wasifyai_lipsync import guardrail
from wasifyai_lipsync.index import index_text
from wasifyai_lipsync.lipsyncs import (
    LIPSYNC_CREATED,
    InMemoryLipSyncStore,
    LipSyncRecord,
    LipSyncStore,
    PosterError,
    PostgresLipSyncStore,
    Quota,
    UsageQuota,
    mark_ai_generated,
    poster_of,
)
from wasifyai_lipsync.schemas import FPS, MAX_SCRIPT_CHARS, MAX_SECONDS, MAX_STYLE_CHARS

log = logging.getLogger(__name__)

Status = Literal["working", "done", "refused", "failed"]
BUSY = "You already have a lip sync being made. It will be in My creations when it's ready."
FAILED = "Your lip sync couldn't be made. Please try again."
TOO_LONG = (
    f"That voice is longer than the limit of {int(MAX_SECONDS // 60)} minutes. "
    "Please use a shorter one."
)
SLACK_SECONDS = 0.5  # a spoken script may run a little over the limit before it is refused


class LipSyncState(TypedDict, total=False):
    # request
    source: str  # "script" | "audio"
    image_key: str
    audio_key: str  # an uploaded or recorded voice
    script: str
    language: str
    gender: str
    voice_id: str
    style: str
    # work in progress
    moderate: bool  # whether the safeguards were on when the request was checked
    lipsync_id: str
    job_id: str
    phase: str  # "synth" | "transcribe" | "clip"
    result_key: str
    voice_key: str  # the voice the clip is made from (storage key, under uploads/)
    seconds: float
    transcript: str
    # result
    video_key: str
    poster_key: str
    video_url: str
    poster_url: str
    width: int
    height: int
    status: Status
    refusal: dict[str, str]


def _clean(value: object, limit: int) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value or ""))
    return re.sub(r"[ \t]+", " ", text).strip()[:limit]


def build_lipsync(caps: Capabilities, checkpointer: Any):
    """Registry entry point: wires the production stores from the capabilities."""
    rows: LipSyncStore = (
        PostgresLipSyncStore(caps.db) if caps.db is not None else InMemoryLipSyncStore()
    )
    uploads: UploadStore = (
        PostgresUploadStore(caps.db) if caps.db is not None else InMemoryUploadStore()
    )
    quota: Quota | None = UsageQuota(caps.db) if caps.db is not None else None
    return build_lipsync_graph(caps, checkpointer, rows, uploads, quota)


def build_lipsync_graph(
    caps: Capabilities,
    checkpointer: Any,
    rows: LipSyncStore,
    uploads: UploadStore,
    quota: Quota | None,
    catalog: Any = None,
):
    voices = catalog or load_catalog()
    stt = load_languages().engine
    limit = (caps.config.quotas.get("lipsyncs_per_user_per_day") if caps.config else None) or None

    async def over_quota() -> bool:
        if not await caps.safeguards_on():  # ADR-0047: quotas apply only with safeguards
            return False
        return bool(limit and quota and await quota.used_today(require_context()) >= limit)

    def quota_message() -> str:
        return f"You've reached today's limit of {limit} lip syncs. Please try again tomorrow."

    async def busy() -> bool:
        ctx = require_context()
        return await rows.working_count(ctx.tenant_id, ctx.user_id) >= 1

    def refuse_with(code: str, message: str) -> LipSyncState:
        return {"status": "refused", "refusal": {"code": code, "message": message}}

    async def find_upload(key: str) -> UploadRecord | None:
        ctx = require_context()
        return await uploads.find(ctx.tenant_id, ctx.product_id, ctx.user_id, key)

    async def discard_upload(key: str | None) -> None:
        """Delete one of the user's uploads (file and record). Safe when it is already gone."""
        if not key:
            return
        assert caps.storage is not None
        record = await find_upload(key)
        if record is None:
            return
        try:
            await caps.storage.delete(record.key)
        except FileNotFoundError:
            pass
        await uploads.consume(record)

    async def delete_file(key: str | None) -> None:
        if not key:
            return
        assert caps.storage is not None
        try:
            await caps.storage.delete(key)
        except FileNotFoundError:
            pass

    async def discard_inputs(state: LipSyncState) -> None:
        """Do not keep what the user gave: the picture, and the voice (an upload, or the speech made
        from the script, and the worker's temporary files)."""
        await discard_upload(state.get("image_key"))
        if state.get("source") == "audio":
            await discard_upload(state.get("audio_key"))
        else:
            await delete_file(state.get("voice_key"))
        if state.get("phase") in ("synth", "transcribe"):
            await delete_file(state.get("result_key"))

    async def fail_clip(state: LipSyncState, message: str = FAILED) -> None:
        if lipsync_id := state.get("lipsync_id"):
            await rows.fail(require_context().tenant_id, lipsync_id, message)
        await discard_inputs(state)

    # ---- checks -------------------------------------------------------------------------

    async def check_request(state: LipSyncState) -> LipSyncState:
        get_stream_writer()(
            {
                "type": "node",
                "node": "check_request",
                "status": "started",
                "label": "Checking your request",
            }
        )
        source = state.get("source")
        if source not in ("script", "audio"):
            return refuse_with("invalid_request", "Please type a script or add a voice.")
        image_key = str(state.get("image_key") or "")
        if not image_key or await find_upload(image_key) is None:
            return refuse_with("invalid_request", "Please upload your picture again.")
        style = _clean(state.get("style"), MAX_STYLE_CHARS + 1)
        out: LipSyncState = {
            "source": source,
            "image_key": image_key,
            "style": style[:MAX_STYLE_CHARS],
            "status": "working",
        }
        audio_key, script = "", ""
        early: LipSyncState | None = None
        if len(style) > MAX_STYLE_CHARS:
            early = refuse_with(
                "invalid_request", f"Please keep the style under {MAX_STYLE_CHARS} characters."
            )
        elif source == "script":
            script = _clean(state.get("script"), MAX_SCRIPT_CHARS + 1)
            if not script:
                early = refuse_with("invalid_request", "Please type what the character should say.")
            elif len(script) > MAX_SCRIPT_CHARS:
                early = refuse_with(
                    "invalid_request",
                    f"Please keep the script under {MAX_SCRIPT_CHARS} characters.",
                )
            else:
                try:
                    voice = voices.resolve(
                        str(state.get("language") or ""),
                        str(state.get("gender") or ""),
                        state.get("voice_id") or None,
                    )
                except NoVoice as exc:
                    early = refuse_with("no_voice", exc.message)
                else:
                    out.update(
                        script=script,
                        language=str(state["language"]),
                        gender=str(state["gender"]),
                        voice_id=voice.id,
                    )
        else:
            audio_key = str(state.get("audio_key") or "")
            record = await find_upload(audio_key) if audio_key else None
            if record is None:
                early = refuse_with("invalid_request", "Please add your voice again.")
            elif (record.seconds or 0) > MAX_SECONDS + SLACK_SECONDS:
                early = refuse_with("too_long", TOO_LONG)
            else:
                out.update(audio_key=audio_key, seconds=float(record.seconds or 0))

        async def refused(code: str, message: str) -> LipSyncState:
            await discard_inputs({**state, "image_key": image_key, "audio_key": audio_key})
            return refuse_with(code, message)

        if early is not None:
            return await refused(early["refusal"]["code"], early["refusal"]["message"])
        if await busy():  # the GPU does one clip at a time
            return await refused("busy", BUSY)
        if await over_quota():  # before any LLM or GPU work
            return await refused("quota_exceeded", quota_message())

        out["moderate"] = await caps.safeguards_on()  # ADR-0047: no moderation while they are off
        if not out["moderate"]:
            return out
        words = " ".join(p for p in (script, out["style"]) if p)
        if words:
            verdict = await guardrail.judge_words(caps, words)
            if not verdict.allowed:
                return await refused(verdict.category, guardrail.words_refusal(verdict.category))
        assert caps.storage is not None
        picture = await caps.storage.get(image_key)
        shown = await guardrail.judge_picture(caps, picture)
        if not shown.allowed:
            return await refused(shown.category, guardrail.picture_refusal(shown.category))
        return out

    def after_check(state: LipSyncState) -> str:
        return "refuse" if state.get("status") == "refused" else "begin"

    async def refuse(state: LipSyncState) -> LipSyncState:
        return {}

    # ---- the row, and the voice ---------------------------------------------------------

    async def begin(state: LipSyncState) -> LipSyncState:
        if await over_quota():  # again, right before the GPU is used
            await discard_inputs(state)
            raise RunError("quota_exceeded", quota_message())
        if await busy():  # a second run that started while this one was being checked
            await discard_inputs(state)
            raise RunError("busy", BUSY)
        ctx = require_context()
        lipsync_id = str(uuid4())
        await rows.add(
            LipSyncRecord(
                id=lipsync_id,
                tenant_id=ctx.tenant_id,
                product_id=ctx.product_id,
                user_id=ctx.user_id,
                thread_id=ctx.thread_id,
                run_id=ctx.run_id,
                source=state["source"],
                status="working",
                script=state.get("script", ""),
                style=state.get("style", ""),
                transcript="",
                seconds=state.get("seconds", 0.0),
            )
        )
        return {"lipsync_id": lipsync_id}

    def after_begin(state: LipSyncState) -> str:
        if state["source"] == "script" or state.get("moderate"):
            return "voice_start"
        return "start_job"

    async def voice_start(state: LipSyncState) -> LipSyncState:
        write = get_stream_writer()
        try:
            if state["source"] == "script":
                write(
                    {
                        "type": "node",
                        "node": "make_voice",
                        "status": "started",
                        "label": "Making the voice",
                    }
                )
                voice = voices.resolve(state["language"], state["gender"], state["voice_id"])
                engine = voices.engines[voice.engine]
                handle = await caps.speech.synthesize(
                    text=state["script"],
                    language=state["language"],
                    engine=voice.engine,
                    model=engine.model,
                    voice=voice.engine_voice,
                    max_chars=engine.max_chars,
                )
                return {"job_id": handle.job_id, "phase": "synth"}
            write(
                {
                    "type": "node",
                    "node": "check_voice",
                    "status": "started",
                    "label": "Checking what is said",
                }
            )
            handle = await caps.speech.transcribe(
                audio_key=state["audio_key"],
                language="",
                engine="whisper",
                model=stt.model,
                detect_model=stt.detect_model,
                indic_languages=list(load_languages().indic),
                seconds=state.get("seconds", 0.0),
            )
            return {"job_id": handle.job_id, "phase": "transcribe"}
        except Exception:
            await fail_clip(state)
            raise

    async def voice_await(state: LipSyncState) -> LipSyncState:
        try:
            result = await_job(state["job_id"])
        except JobFailed as exc:
            message = exc.result.error.message if exc.result.error else FAILED
            await fail_clip(state, message)
            raise
        key = result.outputs["audio" if state["phase"] == "synth" else "transcript"].key
        return {"result_key": key}

    async def voice_finish(state: LipSyncState) -> LipSyncState:
        assert caps.storage is not None
        tenant = require_context().tenant_id
        if state["phase"] == "synth":
            wav = await caps.storage.get(state["result_key"])
            try:
                seconds = wav_seconds(wav)
            except SpeechError:
                await fail_clip(state)
                raise RunError("voice_failed", FAILED, retryable=True) from None
            if seconds > MAX_SECONDS + SLACK_SECONDS:
                await fail_clip(state, TOO_LONG)
                return refuse_with("too_long", TOO_LONG)
            # the worker reads a job's voice from the user's uploads/ prefix
            voice_key = await caps.storage.move(
                state["result_key"], f"uploads/lipsync-{state['lipsync_id']}.wav"
            )
            await rows.set_voice(tenant, state["lipsync_id"], round(seconds, 2), "")
            return {"voice_key": voice_key, "seconds": round(seconds, 2), "phase": "clip"}
        # the words of an uploaded voice, checked before it is used
        raw = await caps.storage.get(state["result_key"])
        await delete_file(state["result_key"])
        try:
            transcript = str(json.loads(raw).get("text") or "").strip()
        except (ValueError, AttributeError):
            await fail_clip(state)
            raise RunError("voice_failed", FAILED, retryable=True) from None
        if transcript:
            verdict = await guardrail.judge_words(caps, transcript)
            if not verdict.allowed:
                message = guardrail.words_refusal(verdict.category)
                await fail_clip({**state, "phase": "clip"}, message)
                return refuse_with(verdict.category, message)
        await rows.set_voice(tenant, state["lipsync_id"], state.get("seconds", 0.0), transcript)
        return {"voice_key": state["audio_key"], "transcript": transcript, "phase": "clip"}

    def after_voice(state: LipSyncState) -> str:
        return "refuse" if state.get("status") == "refused" else "start_job"

    # ---- the clip -----------------------------------------------------------------------

    async def start_job(state: LipSyncState) -> LipSyncState:
        get_stream_writer()(
            {
                "type": "node",
                "node": "generate_lipsync",
                "status": "started",
                "label": "Making your lip sync",
            }
        )
        voice_key = state.get("voice_key") or state.get("audio_key", "")
        prompt = "a person is talking" + (f", {state['style']}" if state.get("style") else "")
        try:
            handle = await caps.video.lipsync(
                prompt=prompt,
                image_key=state["image_key"],
                audio_key=voice_key,
                length=max(1, math.ceil(state.get("seconds", 1.0) * FPS)),
                seed=secrets.randbelow(2**31),
            )
        except Exception:
            await fail_clip({**state, "phase": "clip"})
            raise
        return {"job_id": handle.job_id, "voice_key": voice_key, "phase": "clip"}

    async def await_job_node(state: LipSyncState) -> LipSyncState:
        try:
            result = await_job(state["job_id"])
        except JobFailed as exc:
            message = exc.result.error.message if exc.result.error else FAILED
            await fail_clip(state, message)
            raise
        return {"result_key": result.outputs["video"].key}

    # ---- finish -------------------------------------------------------------------------

    async def finalise(state: LipSyncState) -> LipSyncState:
        assert caps.storage is not None, "object storage is required"
        ctx = require_context()
        lipsync_id = state["lipsync_id"]
        try:
            mp4 = await caps.storage.get(state["result_key"])
            if await caps.safeguards_on():  # the clip says it is AI-generated (ADR-0044, ADR-0047)
                mp4 = await mark_ai_generated(mp4)
            video_key = f"{lipsync_id}/video.mp4"
            await caps.storage.put(video_key, mp4, "video/mp4")
            await delete_file(state["result_key"])  # the worker's temporary file
            width, height, poster = await poster_of(mp4)
            poster_key = f"{lipsync_id}/poster.jpg"
            await caps.storage.put(poster_key, poster, "image/jpeg")
            await rows.finish(ctx.tenant_id, lipsync_id, width, height, video_key, poster_key)
        except PosterError:
            await fail_clip(state)
            raise RunError("lipsync_failed", FAILED, retryable=True) from None
        await discard_inputs(state)  # the user's originals are not kept
        await caps.index_creation(  # ADR-0041
            "lipsync",
            lipsync_id,
            index_text(
                state.get("script", ""), state.get("transcript", ""), state.get("style", "")
            ),
        )
        await caps.record_usage(
            LIPSYNC_CREATED,
            1,
            "lipsyncs",
            lipsync_id=lipsync_id,
            source=state["source"],
            seconds=state.get("seconds", 0.0),
        )
        return {
            "video_key": video_key,
            "poster_key": poster_key,
            "video_url": await caps.storage.url(video_key),
            "poster_url": await caps.storage.url(poster_key),
            "width": width,
            "height": height,
            "status": "done",
        }

    g = StateGraph(LipSyncState)
    for name, fn in [
        ("check_request", check_request),
        ("refuse", refuse),
        ("begin", begin),
        ("voice_start", voice_start),
        ("voice_await", voice_await),
        ("voice_finish", voice_finish),
        ("start_job", start_job),
        ("await_job", await_job_node),
        ("finalise", finalise),
    ]:
        g.add_node(name, cast(Any, fn))
    g.add_edge(START, "check_request")
    g.add_conditional_edges("check_request", after_check, {"refuse": "refuse", "begin": "begin"})
    g.add_edge("refuse", END)
    g.add_conditional_edges(
        "begin", after_begin, {"voice_start": "voice_start", "start_job": "start_job"}
    )
    g.add_edge("voice_start", "voice_await")
    g.add_edge("voice_await", "voice_finish")
    g.add_conditional_edges(
        "voice_finish", after_voice, {"refuse": "refuse", "start_job": "start_job"}
    )
    g.add_edge("start_job", "await_job")
    g.add_edge("await_job", "finalise")
    g.add_edge("finalise", END)
    return g.compile(checkpointer=checkpointer)
