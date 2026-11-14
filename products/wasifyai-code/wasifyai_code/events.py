"""The Agent Server's events, said in the place's own words (ADR-0101, decision 5).

The Agent Server sends many kinds of event. The product reads a few of them and gives them the
seven plain kinds of `place.py`. Everything else is passed over. The shapes read here are the ones
in `agent_types.py`, which is generated from the Agent Server's API description at the pinned
version (`scripts/coding-engine-types.py`): when a version changes one of them, the generated
file changes, and the contract test and pyright say so before a screen does.

    ConversationStateUpdateEvent   -> state (running or idle), and, in `Reader`, the turn's end
    MessageEvent (from the agent)  -> text
    ActionEvent "finish"           -> text (the agent's last message is what it finished with)
    ActionEvent, any other tool    -> step
    ObservationEvent               -> result (ok)
    AgentErrorEvent                -> result (not ok): a tool failed and the agent was told
    UserRejectObservation          -> result (not ok): the person said no
    StreamingDeltaEvent            -> piece (words as they are written; never kept)
    ConversationErrorEvent         -> remembered as why the turn ended

A turn's end is not an event of the Agent Server. `Reader.end` works it out from the state the
conversation came to rest in, the last error, and what the model gateway saw (a refusal by the
model, a call refused at the cost limit), and gives one of the five endings of `place.py`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from wasifyai_code import place as places
from wasifyai_code.agent_types import (
    ActionEvent,
    AgentErrorEvent,
    ConversationErrorEvent,
    ConversationStateUpdateEvent,
    MessageEvent,
    ObservationEvent,
    StreamingDeltaEvent,
    UserRejectObservation,
)

# the Agent Server's words for where a conversation is
RUNNING, IDLE, PAUSED, WAITING = "running", "idle", "paused", "waiting_for_confirmation"
FINISHED, ERROR, STUCK = "finished", "error", "stuck"
RESTING = (FINISHED, PAUSED, ERROR, STUCK)  # a turn that was running has ended
STEP_LIMIT_CODE = "MaxIterationsReached"
FINISH_TOOL = "finish"
QUIET_TOOLS = ("think",)  # the agent talking to itself: not a step a person needs to see

MAX_TEXT = 4000  # of a tool's result, for the person; the agent has all of it
MAX_ARG = 400  # of one thing a tool was given


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def text_of(content: Any) -> str:
    """The words of a message's or an observation's content (a list of parts)."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = [str(p.get("text") or "") for p in content if isinstance(p, Mapping)]
    return "\n".join(p for p in parts if p)


def given(action: Mapping[str, Any]) -> dict[str, Any]:
    """What a tool was given, short enough to show: a path, a pattern, a command. Never a
    file's whole content."""
    out: dict[str, Any] = {}
    for key, value in action.items():
        if key in ("kind", "file_text", "old_str", "new_str") or value in (None, "", [], {}):
            continue
        if isinstance(value, str):
            out[key] = _cut(value, MAX_ARG)
        elif isinstance(value, int | float | bool):
            out[key] = value
        elif isinstance(value, list) and all(isinstance(v, int | str) for v in value):
            out[key] = value[:20]
    return out


@dataclass
class Reader:
    """Reads one session's events in order and gives the place's events. It also keeps what is
    needed to say how a turn ended."""

    steps: int = 0  # tool steps since the turn began
    last_error: tuple[str, str] = ("", "")  # the last conversation error: its code and detail
    status: str = ""  # where the conversation is, as last said
    was_running: bool = False  # a turn is running
    over: bool = False  # a turn that was running came to rest, and its end has not been given
    rest_id: str = ""  # the event at which it came to rest
    _tools: dict[str, str] = field(default_factory=dict)  # a tool call's id -> its tool

    def read(self, event: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        """One event of the Agent Server as zero or more of ours: (kind, data)."""
        kind = event.get("kind")
        if kind == "ConversationStateUpdateEvent":
            return self._state(cast(ConversationStateUpdateEvent, event))
        if kind == "MessageEvent":
            return self._message(cast(MessageEvent, event))
        if kind == "ActionEvent":
            return self._action(cast(ActionEvent, event))
        if kind == "ObservationEvent":
            return self._observation(cast(ObservationEvent, event))
        if kind == "AgentErrorEvent":
            e = cast(AgentErrorEvent, event)
            return [self._result(e.get("tool_call_id"), e.get("tool_name"), False, e.get("error"))]
        if kind == "UserRejectObservation":
            r = cast(UserRejectObservation, event)
            said = r.get("rejection_reason") or "The person said no."
            return [self._result(r.get("tool_call_id"), r.get("tool_name"), False, said)]
        if kind == "StreamingDeltaEvent":
            return self._piece(cast(StreamingDeltaEvent, event))
        if kind == "ConversationErrorEvent":
            c = cast(ConversationErrorEvent, event)
            self.last_error = (str(c.get("code") or ""), str(c.get("detail") or ""))
        return []

    # ---- each kind -----------------------------------------------------------------------------

    def _state(self, event: ConversationStateUpdateEvent) -> list[tuple[str, dict[str, Any]]]:
        key, value = event.get("key"), event.get("value")
        if key == "full_state" and isinstance(value, Mapping):
            # the whole state, sent when a listener connects: only where the conversation is
            status = value.get("execution_status")
            if isinstance(status, str):
                self.status = status
            return []
        if key != "execution_status" or not isinstance(value, str):
            return []
        self.status = value
        if value == RUNNING:
            if not self.was_running:  # a new turn begins
                self.steps, self.last_error = 0, ("", "")
            self.was_running, self.over = True, False
            return [(places.STATE, {"state": "running"})]
        if value in RESTING and self.was_running:
            self.was_running, self.over = False, True
            self.rest_id = str(event.get("id") or "")
        return [(places.STATE, {"state": "idle", "engine": value})]

    def _message(self, event: MessageEvent) -> list[tuple[str, dict[str, Any]]]:
        if event.get("source") != "agent":
            return []  # the person's own message, or the engine's
        message = event.get("llm_message") or {}
        text = text_of(message.get("content"))
        return [(places.TEXT, {"text": text})] if text.strip() else []

    def _action(self, event: ActionEvent) -> list[tuple[str, dict[str, Any]]]:
        tool = str(event.get("tool_name") or "")
        action = event.get("action") or {}
        call = str(event.get("tool_call_id") or event.get("id") or "")
        if tool == FINISH_TOOL:
            said = str(cast(Mapping[str, Any], action).get("message") or "")
            return [(places.TEXT, {"text": said})] if said.strip() else []
        if tool in QUIET_TOOLS:
            return []
        self.steps += 1
        self._tools[call] = tool
        data: dict[str, Any] = {
            "tool": tool,
            "id": call,
            **given(cast(Mapping[str, Any], action)),
        }
        summary = event.get("summary")
        if isinstance(summary, str) and summary.strip():
            data["summary"] = _cut(summary.strip(), MAX_ARG)
        return [(places.STEP, data)]

    def _observation(self, event: ObservationEvent) -> list[tuple[str, dict[str, Any]]]:
        tool = str(event.get("tool_name") or "")
        if tool == FINISH_TOOL or tool in QUIET_TOOLS:
            return []
        observation = cast(Mapping[str, Any], event.get("observation") or {})
        failed = bool(observation.get("is_error"))
        text = text_of(observation.get("content"))
        return [self._result(event.get("tool_call_id"), tool, not failed, text)]

    def _result(self, call: Any, tool: Any, ok: bool, text: Any) -> tuple[str, dict[str, Any]]:
        call = str(call or "")
        name = str(tool or self._tools.get(call, ""))
        return (
            places.RESULT,
            {"id": call, "tool": name, "ok": ok, "text": _cut(str(text or ""), MAX_TEXT)},
        )

    def _piece(self, event: StreamingDeltaEvent) -> list[tuple[str, dict[str, Any]]]:
        out: list[tuple[str, dict[str, Any]]] = []
        if event.get("reasoning_content"):
            out.append((places.PIECE, {"text": event.get("reasoning_content"), "thinking": True}))
        if event.get("content"):
            out.append((places.PIECE, {"text": event.get("content")}))
        return out

    # ---- the end of a turn ---------------------------------------------------------------------

    def end(self, note: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """How the turn ended, for the `ended` event. `note` is what the model gateway saw that
        the Agent Server cannot say: `refusal` (the model declined) and `over_limit` (a call was
        refused at the session's cost limit)."""
        note = note or {}
        code, detail = self.last_error
        refusal = note.get("refusal")
        if isinstance(refusal, Mapping):
            why, said = places.REFUSED, str(refusal.get("message") or "")
        elif self.status == PAUSED:
            why, said = places.STOPPED, ""
        elif code == STEP_LIMIT_CODE:
            why, said = places.STEP_LIMIT, ""
        elif note.get("over_limit"):
            why, said = places.ERROR, str(note["over_limit"])
        elif self.status == FINISHED:
            why, said = places.FINISHED, ""
        elif self.status == STUCK:
            why, said = places.ERROR, "The agent went round in circles and was stopped."
        else:
            why, said = places.ERROR, detail or "The coding engine reported an error."
        return {"why": why, "detail": _cut(said, MAX_TEXT), "steps": self.steps}
