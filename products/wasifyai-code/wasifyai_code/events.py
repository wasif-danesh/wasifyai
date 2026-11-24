"""The Agent Server's events, said in the place's own words (ADR-0101, decision 5).

The Agent Server sends many kinds of event. The product reads a few of them and gives them the
seven plain kinds of `place.py`. Everything else is passed over. The shapes read here are the ones
in `agent_types.py`, which is generated from the Agent Server's API description at the pinned
version (`scripts/coding-engine-types.py`): when a version changes one of them, the generated
file changes, and the contract test and pyright say so before a screen does.

    ConversationStateUpdateEvent   -> state (running or idle), and, in `Reader`, the turn's end
    MessageEvent (from the agent)  -> text
    MessageEvent (from the person) -> skills, when the message switched skills on
    ActionEvent "finish"           -> text (the agent's last message is what it finished with)
    ActionEvent, any other tool    -> step
    ConversationStateUpdateEvent   -> confirm, when it says the conversation waits for a yes or
                                      no: one event naming every step that waits
    ObservationEvent               -> result (ok)
    AgentErrorEvent                -> result (not ok): a tool failed and the agent was told
    UserRejectObservation          -> result (not ok): the person said no
    StreamingDeltaEvent            -> piece (words as they are written; never kept)
    ConversationErrorEvent         -> remembered as why the turn ended

A session on a harness (ADR-0107) is an `acp` conversation; its program's steps come as

    ACPToolCallEvent               -> step when it begins (or first shows), result when it is
                                      completed or failed; the kind of tool is said in our
                                      tools' names (a command is `terminal`, an edit or a look
                                      at a file is `file_editor`)
    ConversationStateUpdateEvent   -> "stats": what the program reports it used so far, kept
                                      for `take_usage`

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
    # the steps said and not yet answered by a result: what waits when the conversation waits
    _open: dict[str, dict[str, Any]] = field(default_factory=dict)
    # a harness's steps that were said: their tool call's id -> what was said
    _acp: dict[str, dict[str, Any]] = field(default_factory=dict)
    # what a harness's program reported it used in the whole conversation, and what was given
    _used: dict[str, Any] = field(default_factory=dict)
    _given: dict[str, float] = field(default_factory=dict)

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
            kind, data = self._result(r.get("tool_call_id"), r.get("tool_name"), False, said)
            return [(kind, {**data, "refused": True})]
        if kind == "StreamingDeltaEvent":
            return self._piece(cast(StreamingDeltaEvent, event))
        if kind == "ACPToolCallEvent":
            return self._acp_call(event)
        if kind == "ConversationErrorEvent":
            c = cast(ConversationErrorEvent, event)
            self.last_error = (str(c.get("code") or ""), str(c.get("detail") or ""))
        return []

    def waiting(self) -> list[dict[str, Any]]:
        """The steps that were said and have no result yet."""
        return list(self._open.values())

    # ---- each kind -----------------------------------------------------------------------------

    def _state(self, event: ConversationStateUpdateEvent) -> list[tuple[str, dict[str, Any]]]:
        key, value = event.get("key"), event.get("value")
        if key == "stats" and isinstance(value, Mapping):
            self._stats(value)
            return []
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
                self._open.clear()
            self.was_running, self.over = True, False
            return [(places.STATE, {"state": "running"})]
        if value in RESTING and self.was_running:
            self.was_running, self.over = False, True
            self.rest_id = str(event.get("id") or "")
        out: list[tuple[str, dict[str, Any]]] = [(places.STATE, {"state": "idle", "engine": value})]
        if value == WAITING and self._open:
            steps = list(self._open.values())
            what = str(steps[0].get("path") or steps[0].get("command") or steps[0].get("tool"))
            ask = str(event.get("id") or steps[0]["id"])
            out.append((places.CONFIRM, {"id": ask, "what": what, "steps": steps}))
        return out

    def _message(self, event: MessageEvent) -> list[tuple[str, dict[str, Any]]]:
        if event.get("source") != "agent":
            # the person's own message: nothing to say of it but the skills it switched on
            used = [str(n) for n in event.get("activated_skills") or [] if n]
            return [(places.SKILLS, {"names": used})] if used else []
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
        self._open[call] = data
        return [(places.STEP, data)]

    def _observation(self, event: ObservationEvent) -> list[tuple[str, dict[str, Any]]]:
        tool = str(event.get("tool_name") or "")
        if tool == FINISH_TOOL or tool in QUIET_TOOLS:
            return []
        observation = cast(Mapping[str, Any], event.get("observation") or {})
        failed = bool(observation.get("is_error"))
        text = text_of(observation.get("content"))
        return [self._result(event.get("tool_call_id"), tool, not failed, text)]

    def _result(
        self, call: Any, tool: Any, ok: bool, text: Any, given: dict[str, Any] | None = None
    ) -> tuple[str, dict[str, Any]]:
        call = str(call or "")
        self._open.pop(call, None)
        name = str(tool or self._tools.get(call, ""))
        data = {"id": call, "tool": name, "ok": ok, "text": _cut(str(text or ""), MAX_TEXT)}
        if given:
            data["given"] = given  # what the step was given, known only now
        return places.RESULT, data

    # ---- a harness's program (ADR-0107) --------------------------------------------------------

    def _acp_call(self, event: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        call = str(event.get("tool_call_id") or event.get("id") or "")
        status = str(event.get("status") or "")
        out: list[tuple[str, dict[str, Any]]] = []
        given: dict[str, Any] = {}
        if call not in self._acp:
            data = acp_step(event)
            data["id"] = call
            self._acp[call] = data
            self._tools[call] = data["tool"]
            self._open[call] = data
            self.steps += 1
            out.append((places.STEP, data))
        elif event.get("raw_input"):
            # Claude Code says a call first with no input ("Terminal"), and what it ran only when
            # it ends: what is known now goes out with its result
            known, later = self._acp[call], acp_step(event)
            given = {k: v for k, v in later.items() if k != "tool" and known.get(k) != v}
            known.update(given)
        if status in ("completed", "failed"):
            failed = status == "failed" or bool(event.get("is_error"))
            out.append(
                self._result(call, self._acp[call]["tool"], not failed, acp_text(event), given)
            )
        return out

    def _stats(self, value: Mapping[str, Any]) -> None:
        """The program's own report, summed over what it names (one entry, usually)."""
        metrics = value.get("usage_to_metrics")
        if not isinstance(metrics, Mapping):
            return
        usd = tokens_in = tokens_out = 0.0
        model = ""
        for entry in metrics.values():
            if not isinstance(entry, Mapping):
                continue
            usd += float(entry.get("accumulated_cost") or 0)
            used = entry.get("accumulated_token_usage") or {}
            if isinstance(used, Mapping):
                tokens_in += sum(
                    float(used.get(k) or 0)
                    for k in ("prompt_tokens", "cache_read_tokens", "cache_write_tokens")
                )
                tokens_out += float(used.get("completion_tokens") or 0)
            named = str(entry.get("model_name") or "")
            if named and named != "acp-managed":
                model = named
        self._used = {"usd": usd, "tokens_in": tokens_in, "tokens_out": tokens_out, "model": model}

    def take_usage(self) -> dict[str, Any] | None:
        """What the program used since this was last asked, or None when nothing new."""
        if not self._used:
            return None
        delta = {
            k: max(0.0, float(self._used[k]) - self._given.get(k, 0.0))
            for k in ("usd", "tokens_in", "tokens_out")
        }
        if not any(delta.values()):
            return None
        self._given = {k: float(self._used[k]) for k in ("usd", "tokens_in", "tokens_out")}
        return {
            "usd": round(delta["usd"], 6),
            "tokens_in": int(delta["tokens_in"]),
            "tokens_out": int(delta["tokens_out"]),
            "model": self._used.get("model", ""),
        }

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


# ---- a harness's tool calls, in our tools' words -----------------------------------------------

# the ACP protocol's kinds of tool call -> the name our screens know
ACP_TOOLS = {
    "execute": "terminal",
    "edit": "file_editor",
    "delete": "file_editor",
    "move": "file_editor",
    "read": "file_editor",
    "search": "grep",
    "fetch": "fetch",
    "think": "think",
}


def acp_step(event: Mapping[str, Any]) -> dict[str, Any]:
    """What one of a harness's tool calls is, in the shape of our steps."""
    kind = str(event.get("tool_kind") or "other")
    title = str(event.get("title") or "").strip()
    raw = event.get("raw_input")
    raw = raw if isinstance(raw, Mapping) else {}
    data: dict[str, Any] = {"tool": ACP_TOOLS.get(kind, kind or "other")}
    if kind == "execute":
        data["command"] = _cut(str(raw.get("command") or title), MAX_ARG)
    elif kind in ("edit", "delete", "move", "read"):
        path = raw.get("file_path") or raw.get("path") or _first_path(event.get("content"))
        if path:
            data["path"] = _cut(str(path), MAX_ARG)
        data["command"] = "view" if kind == "read" else kind
    if title:
        data["summary"] = _cut(title, MAX_ARG)
    return data


def _first_path(content: Any) -> str:
    if isinstance(content, list):
        for part in content:
            if isinstance(part, Mapping) and part.get("path"):
                return str(part["path"])
    return ""


def acp_text(event: Mapping[str, Any]) -> str:
    """The words a harness's tool call gave back, where it gives any (a command's output stays
    in the program's own terminal and is not sent)."""
    parts = []
    for part in event.get("content") or []:
        if not isinstance(part, Mapping):
            continue
        inner = part.get("content")
        if isinstance(inner, Mapping) and inner.get("text"):
            parts.append(str(inner["text"]))
        elif part.get("text"):
            parts.append(str(part["text"]))
    if not parts and event.get("status") == "failed":
        return "It did not work."
    return _cut("\n".join(parts), MAX_TEXT)
