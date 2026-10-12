# pyright: reportTypedDictNotRequiredAccess=false
# (Graph state is filled in node by node; a node only reads keys that earlier nodes have set.)
"""The speech to text graph: check, one job, finish (ADR-0043).

    check_request -> start_job -> await_job -> finalise
        |
        v
      refuse

The user's recording was uploaded and cleaned first (a 16 kHz mono WAV under their `uploads/`
prefix); the run names it by key. The transcript's row is created when the job starts, with status
"working", so the site can show "being made" on any page. The finished transcript, a failure or a
refusal ends it. The recording is deleted as soon as it is no longer needed: when the request is
refused, when the job fails, and when the transcript is saved. Only the words are kept.

A transcript is the user's own content, not generated content, so nothing is moderated. The words
are never written to the log."""

import json
import logging
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

from wasifyai_stt.formats import title_of
from wasifyai_stt.index import index_text
from wasifyai_stt.languages import Languages, load_languages
from wasifyai_stt.transcripts import (
    TRANSCRIPT_CREATED,
    InMemoryTranscriptStore,
    PostgresTranscriptStore,
    Quota,
    TranscriptRecord,
    TranscriptStore,
    UsageQuota,
)

log = logging.getLogger(__name__)

Status = Literal["working", "done", "refused", "failed"]
AUTO = "auto"
BUSY = "You already have a recording being transcribed. It will be in My creations when it's ready."
FAILED = "Your recording couldn't be transcribed. Please try again."
NO_SPEECH = "No speech was found in that recording."


class TranscribeState(TypedDict, total=False):
    # request
    audio_key: str
    language: str  # a language code, or "auto"
    seconds: float
    # job and result
    transcript_id: str
    job_id: str
    result_key: str
    # outcome
    status: Status
    refusal: dict[str, str]
    title: str
    detected: str


def build_transcribe(caps: Capabilities, checkpointer: Any):
    """Registry entry point: wires the production stores from the capabilities."""
    transcripts: TranscriptStore = (
        PostgresTranscriptStore(caps.db) if caps.db is not None else InMemoryTranscriptStore()
    )
    uploads: UploadStore = (
        PostgresUploadStore(caps.db) if caps.db is not None else InMemoryUploadStore()
    )
    quota: Quota | None = UsageQuota(caps.db) if caps.db is not None else None
    return build_transcribe_graph(caps, checkpointer, transcripts, uploads, quota, load_languages())


def build_transcribe_graph(
    caps: Capabilities,
    checkpointer: Any,
    transcripts: TranscriptStore,
    uploads: UploadStore,
    quota: Quota | None,
    languages: Languages,
):
    limit = (caps.config.quotas.get("minutes_per_user_per_day") if caps.config else None) or None

    async def over_quota(extra_minutes: float = 0.0) -> bool:
        if not (limit and quota) or not await caps.safeguards_on():  # ADR-0047
            return False
        used = await quota.used_minutes_today(require_context())
        return used + extra_minutes > limit

    def quota_message() -> str:
        return f"That would go over today's limit of {limit} minutes. Please try again tomorrow."

    async def busy() -> bool:
        ctx = require_context()
        return await transcripts.working_count(ctx.tenant_id, ctx.user_id) >= 1

    def refuse_with(code: str, message: str) -> TranscribeState:
        return {"status": "refused", "refusal": {"code": code, "message": message}}

    async def find_upload(key: str) -> UploadRecord | None:
        ctx = require_context()
        record = await uploads.find(ctx.tenant_id, ctx.product_id, ctx.user_id, key)
        return record if record and record.kind == "audio" else None

    async def discard_upload(key: str | None) -> None:
        """Delete the user's recording (file and record). Safe to call when it is already gone."""
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

    async def fail_transcript(state: TranscribeState, message: str = FAILED) -> None:
        """The transcript will not be made: tell the row, and do not keep the recording."""
        if transcript_id := state.get("transcript_id"):
            await transcripts.fail(require_context().tenant_id, transcript_id, message)
        await discard_upload(state.get("audio_key"))

    # ---- checks ---------------------------------------------------------------------------

    async def check_request(state: TranscribeState) -> TranscribeState:
        write = get_stream_writer()
        write(
            {
                "type": "node",
                "node": "check_request",
                "status": "started",
                "label": "Checking your recording",
            }
        )
        language = str(state.get("language") or AUTO)
        if language != AUTO and languages.get(language) is None:
            return refuse_with("invalid_request", "Please choose one of the languages in the list.")
        key = str(state.get("audio_key") or "")
        upload = await find_upload(key) if key else None
        if upload is None:
            return refuse_with("invalid_request", "Please upload your recording again.")
        seconds = float(upload.seconds or 0)

        async def refused(code: str, message: str) -> TranscribeState:
            await discard_upload(key)
            return refuse_with(code, message)

        if await busy():  # the speech server does one recording at a time
            return await refused("busy", BUSY)
        if await over_quota(seconds / 60):  # before any compute is used
            return await refused("quota_exceeded", quota_message())
        return {"audio_key": key, "language": language, "seconds": seconds, "status": "working"}

    def after_check(state: TranscribeState) -> str:
        return "refuse" if state.get("status") == "refused" else "start_job"

    async def refuse(state: TranscribeState) -> TranscribeState:
        return {}

    # ---- the job --------------------------------------------------------------------------

    async def start_job(state: TranscribeState) -> TranscribeState:
        if await over_quota(state["seconds"] / 60):  # again, right before the compute is used
            await discard_upload(state.get("audio_key"))
            raise RunError("quota_exceeded", quota_message())
        if await busy():  # a second run that started while this one was being checked
            await discard_upload(state.get("audio_key"))
            raise RunError("busy", BUSY)
        ctx = require_context()
        transcript_id = str(uuid4())
        await transcripts.add(
            TranscriptRecord(
                id=transcript_id,
                tenant_id=ctx.tenant_id,
                product_id=ctx.product_id,
                user_id=ctx.user_id,
                thread_id=ctx.thread_id,
                run_id=ctx.run_id,
                status="working",
                seconds=state["seconds"],
            )
        )
        write = get_stream_writer()
        write(
            {
                "type": "node",
                "node": "transcribe",
                "status": "started",
                "label": "Transcribing your recording",
            }
        )
        engine = languages.engine
        try:
            handle = await caps.speech.transcribe(
                audio_key=state["audio_key"],
                language="" if state["language"] == AUTO else state["language"],
                engine="whisper",
                model=engine.model,
                detect_model=engine.detect_model,
                indic_languages=list(languages.indic),
                seconds=state["seconds"],
            )
        except Exception:
            await fail_transcript(
                {"transcript_id": transcript_id, "audio_key": state.get("audio_key", "")}
            )
            raise
        return {"transcript_id": transcript_id, "job_id": handle.job_id}

    async def await_job_node(state: TranscribeState) -> TranscribeState:
        try:
            result = await_job(state["job_id"])
        except JobFailed as exc:
            message = exc.result.error.message if exc.result.error else FAILED
            await fail_transcript(state, message)
            raise
        return {"result_key": result.outputs["transcript"].key}

    # ---- finish ---------------------------------------------------------------------------

    async def finalise(state: TranscribeState) -> TranscribeState:
        assert caps.storage is not None, "object storage is required"
        ctx = require_context()
        transcript_id = state["transcript_id"]
        try:
            raw = await caps.storage.get(state["result_key"])
            await caps.storage.delete(state["result_key"])  # the worker's jobs/ file is temporary
            out = json.loads(raw)
            words = str(out.get("text") or "").strip()
            detected = str(out.get("language") or "")
            segments = [
                {"start": float(s["start"]), "end": float(s["end"]), "text": str(s["text"]).strip()}
                for s in out.get("segments") or []
                if str(s.get("text", "")).strip()
            ]
        except (ValueError, KeyError, TypeError, FileNotFoundError):
            log.error("the transcription result could not be read")
            await fail_transcript(state)
            raise RunError("transcript_failed", FAILED, retryable=True) from None
        if not words:
            await fail_transcript(state, NO_SPEECH)
            raise RunError("no_speech", NO_SPEECH)
        language = state["language"] if state["language"] != AUTO else detected
        title = title_of(words)
        await transcripts.finish(
            ctx.tenant_id, transcript_id, title, language, "whisper", words, segments
        )
        await discard_upload(state.get("audio_key"))  # the recording is private: it is not kept
        await caps.index_creation(
            "transcript", transcript_id, index_text(title, language, words)
        )  # ADR-0041
        await caps.record_usage(
            TRANSCRIPT_CREATED,
            round(state["seconds"] / 60, 3),
            "minutes",
            transcript_id=transcript_id,
            language=language,
            characters=len(words),
        )
        return {"title": title, "detected": language, "status": "done"}

    g = StateGraph(TranscribeState)
    for name, fn in [
        ("check_request", check_request),
        ("refuse", refuse),
        ("start_job", start_job),
        ("await_job", await_job_node),
        ("finalise", finalise),
    ]:
        g.add_node(name, cast(Any, fn))
    g.add_edge(START, "check_request")
    g.add_conditional_edges(
        "check_request", after_check, {"refuse": "refuse", "start_job": "start_job"}
    )
    g.add_edge("refuse", END)
    g.add_edge("start_job", "await_job")
    g.add_edge("await_job", "finalise")
    g.add_edge("finalise", END)
    return g.compile(checkpointer=checkpointer)
