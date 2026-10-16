# SPDX-License-Identifier: Apache-2.0
# pyright: reportTypedDictNotRequiredAccess=false
"""The Speak graph (ADR-0066, stages V1 and V2): one run makes one speech, in a built-in voice, in a
voice described in words, or in a voice cloned from a recording the person saved.

    check_request -> speak -> finalise
        |
        v
      refuse

The graph names a task and, optionally, a model id; the engine's descriptors decide what is possible
(`wasifyai_platform_sdk.voice_models`). A request the model cannot take is refused in words before
anything is loaded; the engine's own failures end the run with a typed error."""

import logging
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
    check_speak,
    require_context,
)

from wasifyai_voice.runtime import NotAvailable, engine_for, store_for
from wasifyai_voice.store import NotFound, new_id

log = logging.getLogger(__name__)

Status = Literal["working", "done", "refused"]
SPEECH_CREATED = "voice.speech"


class SpeakState(TypedDict, total=False):
    # request
    text: str
    model: str  # a model id; the recommended one for speaking otherwise
    voice: str
    options: dict[str, Any]
    saved_voice: str  # the id of a saved voice (described or cloned); `voice` is for built-in ones
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


def build_speak(caps: Capabilities, checkpointer: Any):
    app_state = caps.extras.get("app_state")

    def engine():
        try:
            return engine_for(app_state)
        except NotAvailable as e:
            raise RunError("not_available", str(e)) from None

    def refuse_with(code: str, message: str) -> SpeakState:
        return {"status": "refused", "refusal": {"code": code, "message": message}}

    async def check_request(state: SpeakState) -> SpeakState:
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

    g = StateGraph(SpeakState)
    for name, fn in [("check_request", check_request), ("refuse", refuse), ("speak", speak)]:
        g.add_node(name, cast(Any, fn))
    g.add_edge(START, "check_request")
    g.add_conditional_edges("check_request", after_check, {"refuse": "refuse", "speak": "speak"})
    g.add_edge("refuse", END)
    g.add_edge("speak", END)
    return g.compile(checkpointer=checkpointer)
