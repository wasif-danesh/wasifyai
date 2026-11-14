"""What coding can do, for the action catalogue (ADR-0068; ADR-0101, decision 4): start a session
on a folder, send it a message, stop it, undo a turn. The window calls these and never the coding
engine.

A session started here only reads unless a mode that changes files is asked for (`mode`). In
"ask" and "own" the agent changes files of the folder with a file editor and runs nothing; every
turn that changed files can be undone with `code.session.undo`. `code.session.send` is the one
that costs: it reads the person's own folder and, on a cloud model, sends what it reads to that
model's provider.

They are offered to the assistant and not to outside apps (`surfaces`): an outside app that could
open a session on any folder would be handed that folder's content."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from wasifyai_platform_sdk.actions import (
    Action,
    ActionContext,
    CallBinding,
    Outcome,
    need_product,
    need_runtime,
)
from wasifyai_platform_sdk.actions.helpers import need_deps

from wasifyai_code import PRODUCT_ID
from wasifyai_code import place as places
from wasifyai_code.runtime import KIND, NotAvailable, Refused, owner_of, sessions_for

ENGINE = need_runtime("coding")
SAMPLE_ID = "0b7c1f9e000040008000000000000000"
ANSWER_CHARS = 8000  # of the agent's answer in an action's result; the session keeps all of it
ENDINGS = {
    places.FINISHED: "The agent finished.",
    places.STOPPED: "The turn was stopped.",
    places.STEP_LIMIT: "The agent used every step it was allowed and stopped.",
    places.REFUSED: "The model declined this request.",
    places.ERROR: "The turn ended with an error.",
}


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    folder: str = Field(
        min_length=1, max_length=1024,
        description="The project's folder on this computer, as a whole path. The agent may "
        "read this folder and nothing else of the person's.",
    )  # fmt: skip
    title: str = Field("", max_length=200, description="A name for the session.")
    model: str = Field(
        "", max_length=64,
        description="The model to work with. Leave empty for the first choice.",
    )  # fmt: skip
    cost_limit_usd: float = Field(
        0, ge=0, le=100,
        description="The most this session may cost, in US dollars. 0 uses the usual limit.",
    )  # fmt: skip
    mode: Literal["plan", "ask", "own"] = Field(
        "plan",
        description="How much the agent may do. plan: it only reads. ask: it changes files, "
        "and a change Undo cannot put back waits for the person's yes on the Code screen. "
        "own: it changes files and asks nothing.",
    )


class StartOut(BaseModel):
    session_id: str
    product_id: str
    uri: str
    title: str
    folder: str
    mode: str
    model: str


class SendIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: str = Field(min_length=1, max_length=64, description="The coding session.")
    text: str = Field(
        min_length=1, max_length=20000,
        description="What to ask the agent, in plain words: a question about the code, or a "
        "plan to make.",
    )  # fmt: skip


class SendOut(BaseModel):
    session_id: str
    turn_id: str
    ended: str
    answer: str
    truncated: bool
    steps: int
    cost_usd: float
    changed: int = 0


class UndoIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: str = Field(min_length=1, max_length=64, description="The coding session.")
    turn_id: str = Field(
        "", max_length=64,
        description="The turn to undo. Leave empty for the newest turn that changed files.",
    )  # fmt: skip


class UndoOut(BaseModel):
    session_id: str
    turn_id: str
    files: int
    own_changes: bool
    notes: list[str]


class StopIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: str = Field(min_length=1, max_length=64, description="The coding session.")


class StopOut(BaseModel):
    session_id: str
    stopped: bool
    state: str


def _sessions(ctx: ActionContext) -> Any:
    return sessions_for(need_deps(ctx).state)


async def _start(p: StartIn, ctx: ActionContext) -> Outcome:
    try:
        made = await _sessions(ctx).start(
            owner_of(ctx.actor), folder=p.folder, title=p.title, model=p.model,
            cost_limit_usd=p.cost_limit_usd, mode=p.mode,
        )  # fmt: skip
    except NotAvailable as e:
        return Outcome.refused(str(e), "unavailable")
    except Refused as e:
        return Outcome.refused(e.message, e.code)
    return Outcome.ok(
        {
            "session_id": made["id"],
            "product_id": PRODUCT_ID,
            "uri": f"wasify://creation/{KIND}/{made['id']}",
            "title": made["title"],
            "folder": made["folder"],
            "mode": made["mode"],
            "model": made["model"],
        },
        f'A coding session on "{made["project"]}" is ready. '
        + (
            "The agent can read the folder and cannot change it."
            if made["mode"] == "plan"
            else "The agent can read the folder and change its files; it runs no command."
        )
        + " Send it a message with code.session.send.",
    )


async def _send(p: SendIn, ctx: ActionContext) -> Outcome:
    import asyncio

    owner = owner_of(ctx.actor)
    try:
        sessions = _sessions(ctx)
        turn = await sessions.send(owner, p.session_id, p.text)
        try:
            turn = await sessions.wait(owner, p.session_id)
        except asyncio.CancelledError:  # the job was cancelled: the turn is stopped with it
            await asyncio.shield(sessions.stop(owner, p.session_id))
            raise
        seen = sessions.view(owner, p.session_id)
    except NotAvailable as e:
        return Outcome.refused(str(e), "unavailable")
    except Refused as e:
        return Outcome.refused(e.message, e.code)
    ended, answer = turn["why"], turn["answer"]
    if ended == places.ERROR:
        why = (turn["notes"] or ["The coding engine reported an error."])[-1]
        return Outcome.error(why, "turn_failed")
    said = ENDINGS.get(ended, "The turn ended.")
    return Outcome.ok(
        {
            "session_id": p.session_id,
            "turn_id": turn["id"],
            "ended": ended,
            "answer": answer[:ANSWER_CHARS],
            "truncated": len(answer) > ANSWER_CHARS,
            "steps": turn["steps"],
            "cost_usd": seen["cost_usd"],
            "changed": int(turn["changed"]),
        },
        f"{said} It took {turn['steps']} step{'s' if turn['steps'] != 1 else ''}; "
        + (
            f"{turn['changed']} file{'s were' if turn['changed'] != 1 else ' was'} changed. "
            "code.session.undo puts them back."
            if turn["changed"]
            else "nothing in the folder was changed."
        ),
    )


async def _undo(p: UndoIn, ctx: ActionContext) -> Outcome:
    owner = owner_of(ctx.actor)
    try:
        sessions = _sessions(ctx)
        turn_id = p.turn_id
        if not turn_id:
            able = [t for t in sessions.turns(owner, p.session_id) if t["can_undo"]]
            if not able:
                return Outcome.refused("No turn of this session can be undone.", "nothing_to_undo")
            turn_id = able[-1]["id"]
        done = await sessions.undo(owner, p.session_id, turn_id)
    except NotAvailable as e:
        return Outcome.refused(str(e), "unavailable")
    except Refused as e:
        return Outcome.refused(e.message, e.code)
    return Outcome.ok(
        {
            "session_id": p.session_id,
            "turn_id": turn_id,
            "files": done["files"],
            "own_changes": done["own_changes"],
            "notes": done["notes"],
        },
        f"{done['files']} file{'s are' if done['files'] != 1 else ' is'} back to how "
        f"{'they were' if done['files'] != 1 else 'it was'} before the turn. It can be "
        "brought back on the Code screen.",
    )


async def _stop(p: StopIn, ctx: ActionContext) -> Outcome:
    owner = owner_of(ctx.actor)
    try:
        sessions = _sessions(ctx)
        stopped = await sessions.stop(owner, p.session_id)
        seen = sessions.view(owner, p.session_id)
    except NotAvailable as e:
        return Outcome.refused(str(e), "unavailable")
    except Refused as e:
        return Outcome.refused(e.message, e.code)
    return Outcome.ok(
        {"session_id": p.session_id, "stopped": stopped, "state": seen["state"]},
        "The turn was stopped. Nothing was changed."
        if stopped
        else "Nothing was running in that session.",
    )


def actions() -> list[Action]:
    return [
        Action(
            id="code.session.start",
            title="Start a coding session",
            summary="Open a project's folder for the coding agent to read.",
            description=(
                "Start a coding session on one folder of this computer. By default the session "
                "only reads (mode plan): the agent can find and read the files of that folder "
                "and cannot change a file. With mode ask or own it can also change files of "
                "that folder; it can never run a command, and every turn can be undone. "
                "Nothing runs yet and nothing is read until a message is sent with "
                "code.session.send. Give the folder's whole path. "
                "The home folder, a whole disk and the app's own folders are refused. It "
                "returns the session's id."
            ),
            input=StartIn,
            output=StartOut,
            examples=({"folder": "/Users/me/Projects/bakery-site"},),
            effect="make",
            requires=(need_product(PRODUCT_ID), ENGINE),
            product=PRODUCT_ID,
            bind=CallBinding(_start),
            ui="code.projects",
            surfaces=("assistant",),
        ),
        Action(
            id="code.session.send",
            title="Ask the coding agent",
            summary="Send a coding session a message and get the agent's answer.",
            description=(
                "Send a message to a coding session and wait for the agent's answer. Use it for "
                'questions about a project ("analyse this codebase", "where is the login '
                'handled?"), for a plan of a change and, in a session whose mode is ask or own, '
                "for the change itself. The agent reads the files it needs; in a plan session "
                "it changes nothing. It can take from seconds to several minutes. With a cloud "
                "model, the parts of the files the agent reads are sent to that model's "
                "provider, and the session's cost is counted and limited. It returns how the "
                "turn ended (finished, stopped, step_limit, refused), the answer, the number "
                "of steps, how many files were changed and the cost so far."
            ),
            input=SendIn,
            output=SendOut,
            examples=({"session_id": SAMPLE_ID, "text": "Analyse this codebase."},),
            effect="make",
            flags=("costly", "leaves_device", "private"),
            requires=(need_product(PRODUCT_ID), ENGINE),
            long=True,
            product=PRODUCT_ID,
            bind=CallBinding(_send),
            ui="code.projects",
            surfaces=("assistant",),
        ),
        Action(
            id="code.session.stop",
            title="Stop the coding agent",
            summary="Stop what a coding session is doing.",
            description=(
                "Stop the turn a coding session is working on. It takes effect at once, "
                "whatever the agent is doing. The session stays and can be sent another "
                "message. Stopping a session that is not working does nothing."
            ),
            input=StopIn,
            output=StopOut,
            examples=({"session_id": SAMPLE_ID},),
            effect="change",
            requires=(need_product(PRODUCT_ID), ENGINE),
            product=PRODUCT_ID,
            bind=CallBinding(_stop),
            ui="code.projects",
            surfaces=("assistant",),
        ),
        Action(
            id="code.session.undo",
            title="Undo a coding turn",
            summary="Put a project's files back to how they were before the agent's turn.",
            description=(
                "Undo what a turn of a coding session changed: every file it changed, added or "
                "deleted goes back to how it was before that turn. Only the newest turn that "
                "changed files can be undone; leave turn_id empty for that one. Files the "
                "project ignores (such as .env) and changes the person made themselves since "
                "the turn are part of what goes back or stays; the result says so. An undo can "
                "be brought back on the Code screen."
            ),
            input=UndoIn,
            output=UndoOut,
            examples=({"session_id": SAMPLE_ID},),
            effect="change",
            requires=(need_product(PRODUCT_ID), ENGINE),
            product=PRODUCT_ID,
            bind=CallBinding(_undo),
            ui="code.projects",
            surfaces=("assistant",),
        ),
    ]


__all__ = ["actions"]
