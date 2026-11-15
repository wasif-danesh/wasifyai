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
    result: str = ""  # the project's check: passed, failed, not_checked, could_not_check, or none
    rounds: int = 0  # how many times the check ran in this turn
    needs_you: bool = False  # the check still fails or could not run: a person must decide


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: str = Field(min_length=1, max_length=64, description="The coding session.")
    command: str | None = Field(
        None,
        max_length=2000,
        description=(
            "The project's check command, for example `npm test` or `python3 -m pytest`. "
            "Leave it out to keep the one that is set. An empty text removes the check."
        ),
    )
    run: bool = Field(True, description="Run the check now and wait for its result.")


class CheckOut(BaseModel):
    session_id: str
    command: str
    suggested: list[str]
    ran: bool
    result: str = ""
    exit_code: int | None = None
    seconds: float = 0.0
    output: str = ""


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


class NewIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    parent: str = Field(
        min_length=1,
        max_length=1024,
        description=(
            "The whole path of a folder that exists; the new project's folder is made inside it."
        ),
    )
    name: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "The project's name, which becomes the new folder's name. Letters, digits, spaces, "
            "dots, dashes, underlines."
        ),
    )
    starter: str = Field(
        "web", max_length=32, description="What to start from: web (a small web app)."
    )
    model: str = Field(
        "", max_length=64, description="The model to work with. Empty: the first choice."
    )


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: str = Field(min_length=1, max_length=64, description="The coding session.")
    do: Literal["start", "stop", "state"] = Field(
        "start", description="Start the preview, stop it, or only say where it is."
    )
    command: str | None = Field(
        None,
        max_length=2000,
        description=(
            "The command that starts the project, for example `npm run dev`. Left out, the one "
            "that is set, or the one the project's files suggest."
        ),
    )


class PreviewOut(BaseModel):
    session_id: str
    command: str
    state: str  # none, starting, running, ended
    port: int | None = None
    url: str = ""
    open_to_network: bool = False
    output: str = ""


class ExtListIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: str = Field(
        "",
        max_length=64,
        description="A coding session: says for its project whether each extension is on.",
    )
    extension_id: str = Field(
        "",
        max_length=120,
        description="One extension's id, to read the whole text it gives the agent.",
    )


class ExtRow(BaseModel):
    id: str
    title: str
    source: str
    description: str
    on: bool | None = None


class ExtListOut(BaseModel):
    items: list[ExtRow]
    text: str = ""  # the whole text of the one that was named


class ExtSwitchIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: str = Field(
        min_length=1, max_length=64, description="A coding session of the project."
    )
    extension_id: str = Field(
        min_length=1, max_length=120, description="The extension's id, from code.extension.list."
    )
    on: bool = Field(description="True switches it on for the project, false off.")


class ExtSwitchOut(BaseModel):
    extension_id: str
    title: str
    project: str
    on: bool


class ExtAddIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    folder: str = Field(
        min_length=1,
        max_length=1024,
        description="The whole path of a folder that holds a SKILL.md.",
    )
    session_id: str = Field(
        "", max_length=64, description="A coding session: the skill is switched on for its project."
    )


class ExtAddOut(BaseModel):
    extension_id: str
    title: str
    description: str
    on: bool


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
            else "The agent can read the folder, change its files and run commands inside it."
        )
        + " Send it a message with code.session.send.",
    )


def _workspace_of(sessions: Any, owner: Any, session_id: str) -> tuple[str, str]:
    """The project of a session: its id and its name."""
    seen = sessions.view(owner, session_id)
    found = next((w for w in sessions.workspaces(owner) if w["folder"] == seen["folder"]), None)
    if found is None:
        raise Refused("not_found", "That session's project is gone.")
    return found["id"], found["name"]


async def _ext_list(p: ExtListIn, ctx: ActionContext) -> Outcome:
    owner = owner_of(ctx.actor)
    try:
        sessions = _sessions(ctx)
        workspace = _workspace_of(sessions, owner, p.session_id)[0] if p.session_id else ""
        items = sessions.list_extensions(owner, workspace)
        text = sessions.extension(owner, p.extension_id)["text"] if p.extension_id else ""
    except NotAvailable as e:
        return Outcome.refused(str(e), "unavailable")
    except Refused as e:
        return Outcome.refused(e.message, e.code)
    rows = [
        {
            "id": i["id"], "title": i["title"], "source": i["source"],
            "description": i["description"][:300], "on": i["on"],
        }
        for i in items
    ]  # fmt: skip
    on = sum(1 for i in items if i["on"])
    return Outcome.ok(
        {"items": rows, "text": text[:ANSWER_CHARS]},
        f"{len(rows)} extension{'s are' if len(rows) != 1 else ' is'} offered"
        + (f", {on} on for this project." if workspace else "."),
    )


async def _ext_switch(p: ExtSwitchIn, ctx: ActionContext) -> Outcome:
    owner = owner_of(ctx.actor)
    try:
        sessions = _sessions(ctx)
        workspace, project = _workspace_of(sessions, owner, p.session_id)
        done = await sessions.switch_extension(owner, p.extension_id, workspace, p.on)
    except NotAvailable as e:
        return Outcome.refused(str(e), "unavailable")
    except Refused as e:
        return Outcome.refused(e.message, e.code)
    return Outcome.ok(
        {"extension_id": done["id"], "title": done["title"], "project": project, "on": p.on},
        f'"{done["title"]}" is now {"on" if p.on else "off"} for {project}. It holds from the '
        "session's next message.",
    )


async def _ext_add(p: ExtAddIn, ctx: ActionContext) -> Outcome:
    owner = owner_of(ctx.actor)
    try:
        sessions = _sessions(ctx)
        workspace = _workspace_of(sessions, owner, p.session_id)[0] if p.session_id else ""
        made = await sessions.add_extension(owner, p.folder, workspace)
    except NotAvailable as e:
        return Outcome.refused(str(e), "unavailable")
    except Refused as e:
        return Outcome.refused(e.message, e.code)
    return Outcome.ok(
        {
            "extension_id": made["id"], "title": made["title"],
            "description": made["description"][:300], "on": bool(made["on"]),
        },
        f'The skill "{made["title"]}" was copied into Wasify AI'
        + (" and switched on for the project." if made["on"] else "; it is off until switched on."),
    )  # fmt: skip


async def _new(p: NewIn, ctx: ActionContext) -> Outcome:
    try:
        made = await _sessions(ctx).start_new(
            owner_of(ctx.actor), parent=p.parent, name=p.name, starter=p.starter, model=p.model
        )
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
        f'The project "{made["project"]}" was made in {made["folder"]}, with a check '
        f"({made['check_command']}) and a preview ({made['preview_command']}). Send the agent a "
        "message with code.session.send, or start the preview with code.session.preview.",
    )


async def _preview(p: PreviewIn, ctx: ActionContext) -> Outcome:
    import asyncio

    owner = owner_of(ctx.actor)
    try:
        sessions = _sessions(ctx)
        if p.do == "stop":
            seen = await sessions.stop_preview(owner, p.session_id)
        elif p.do == "start":
            seen = sessions.preview(owner, p.session_id)
            command = (
                p.command
                or seen["command"]
                or (seen["suggested"][0]["command"] if seen["suggested"] else "")
            )
            if not command:
                return Outcome.refused(
                    "Nothing in the project's files says how to start it. Give the command.",
                    "no_command",
                )
            seen = await sessions.start_preview(owner, p.session_id, command)
            for _ in range(120):  # up to a minute for it to listen
                if not seen["running"] or seen["running"]["state"] != "starting":
                    break
                await asyncio.sleep(0.5)
                seen = sessions.preview(owner, p.session_id)
        else:
            seen = sessions.preview(owner, p.session_id)
    except NotAvailable as e:
        return Outcome.refused(str(e), "unavailable")
    except Refused as e:
        return Outcome.refused(e.message, e.code)
    running = seen["running"]
    out = {
        "session_id": p.session_id,
        "command": seen["command"],
        "state": running["state"] if running else "none",
        "port": running["port"] if running else None,
        "url": running["url"] if running else "",
        "open_to_network": bool(running and running["open_to_network"]),
        "output": (running["output"] if running else "")[-ANSWER_CHARS:],
    }
    if running is None:
        return Outcome.ok(out, "No preview is running.")
    if running["state"] == "running":
        return Outcome.ok(
            out,
            f"The preview runs at {running['url']} on this computer. The person sees it in the "
            "Preview tab of the session."
            + (
                " It listens on every address, so other computers on the network can open it."
                if running["open_to_network"]
                else ""
            ),
        )
    if running["state"] == "ended":
        return Outcome.ok(
            out, f"The preview ended (exit code {running['exit_code']}). Its output says why."
        )
    return Outcome.ok(out, "The preview has started and listens on no port yet.")


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
            "result": turn["result"],
            "rounds": int(turn["rounds"]),
            "needs_you": bool(turn["needs_you"]),
        },
        f"{said} It took {turn['steps']} step{'s' if turn['steps'] != 1 else ''}; "
        + (
            f"{turn['changed']} file{'s were' if turn['changed'] != 1 else ' was'} changed. "
            "code.session.undo puts them back."
            if turn["changed"]
            else "nothing in the folder was changed."
        )
        + _checked(turn),
    )


CHECKED = {
    "passed": " The project's check passed.",
    "failed": " The project's check still fails; the person must decide what to do.",
    "could_not_check": " The project's check could not run, which is not a pass.",
}


def _checked(turn: dict[str, Any]) -> str:
    if not turn["changed"]:
        return ""
    if turn["result"] == "not_checked" and turn.get("check_why") == "no_command":
        return " It was not checked: the project has no check. code.session.check sets one."
    return CHECKED.get(turn["result"], " It was not checked.")


async def _check(p: CheckIn, ctx: ActionContext) -> Outcome:
    owner = owner_of(ctx.actor)
    try:
        sessions = _sessions(ctx)
        seen = sessions.check(owner, p.session_id)
        if p.command is not None:
            seen = sessions.set_check(owner, p.session_id, p.command)
        out: dict[str, Any] = {
            "session_id": p.session_id,
            "command": seen["command"],
            "suggested": [s["command"] for s in seen["suggested"]],
            "ran": False,
        }
        if not p.run or not seen["command"]:
            said = (
                f"The project's check is `{seen['command']}`."
                if seen["command"]
                else "The project has no check. "
                + (
                    f"Its files suggest `{out['suggested'][0]}`."
                    if out["suggested"]
                    else "Nothing in its files suggests one."
                )
            )
            return Outcome.ok(out, said)
        row = await sessions.check_now(owner, p.session_id)
        whole = sessions.check_output(owner, p.session_id, row["id"])
    except NotAvailable as e:
        return Outcome.refused(str(e), "unavailable")
    except Refused as e:
        return Outcome.refused(e.message, e.code)
    out.update(
        ran=True, result=row["result"], exit_code=row["exit_code"], seconds=row["seconds"],
        output=whole["output"][-ANSWER_CHARS:],
    )  # fmt: skip
    words = {
        "passed": "passed",
        "failed": f"failed (exit code {row['exit_code']})",
        "could_not_check": "could not run, which is not a pass",
        "not_checked": "was stopped",
    }
    return Outcome.ok(out, f"The check `{row['command']}` {words[row['result']]}.")


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
                "that folder and run commands there, inside a sandbox that keeps it to that "
                "folder; every turn can be undone. "
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
                "provider, and the session's cost is counted and limited. After a turn that "
                "changed files the app runs the project's check and sends a failure back to "
                "the agent, up to three rounds. It returns how the turn ended (finished, "
                "stopped, step_limit, refused), the answer, the number of steps, how many "
                "files were changed, the check's result and the cost so far."
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
            id="code.session.check",
            title="Set or run a project's check",
            summary="Set the command that checks a coding project, and run it.",
            description=(
                "A coding project's check is one command (for example `npm test`) that the app "
                "runs after every turn that changed files; when it fails the agent is told and "
                "fixes it, up to three rounds. This action reads the check, sets it with "
                "command, and with run (the default) runs it now and gives the result and the "
                "end of its output. The check runs inside the project's sandbox: it can write "
                "only inside the project. Without command and with run false it only says "
                "which check is set and what the project's files suggest."
            ),
            input=CheckIn,
            output=CheckOut,
            examples=(
                {"session_id": SAMPLE_ID, "command": "npm test"},
                {"session_id": SAMPLE_ID, "run": False},
            ),
            effect="change",
            requires=(need_product(PRODUCT_ID), ENGINE),
            long=True,
            product=PRODUCT_ID,
            bind=CallBinding(_check),
            ui="code.projects",
            surfaces=("assistant",),
        ),
        Action(
            id="code.extension.list",
            title="List the coding agent's extensions",
            summary="Say which skills the coding agent can be taught, and which are on.",
            description=(
                "List the extensions offered for coding: skills that teach the agent a way of "
                "working (Wasify AI's own, a few of the public OpenHands catalogue, and the "
                "ones the person added). With session_id it says for that session's project "
                "whether each is on. With extension_id it also returns the whole text that "
                "skill gives the agent, so the person can read it before switching it on."
            ),
            input=ExtListIn,
            output=ExtListOut,
            examples=({}, {"session_id": SAMPLE_ID}),
            effect="read",
            requires=(need_product(PRODUCT_ID), ENGINE),
            product=PRODUCT_ID,
            bind=CallBinding(_ext_list),
            ui="code.extensions",
            surfaces=("assistant",),
        ),
        Action(
            id="code.extension.switch",
            title="Switch an extension on or off",
            summary="Switch a skill on or off for one coding project.",
            description=(
                "Switch an extension on or off for the project of a coding session. A skill "
                "that is on is offered to the agent in that project and used when a message "
                "is about it. A skill is text: it can steer how the agent works and cannot "
                "widen what the agent may do. The change holds from the session's next message."
            ),
            input=ExtSwitchIn,
            output=ExtSwitchOut,
            examples=(
                {"session_id": SAMPLE_ID, "extension_id": "catalogue:code-review", "on": True},
            ),
            effect="change",
            requires=(need_product(PRODUCT_ID), ENGINE),
            product=PRODUCT_ID,
            bind=CallBinding(_ext_switch),
            ui="code.extensions",
            surfaces=("assistant",),
        ),
        Action(
            id="code.extension.add",
            title="Add an extension from a folder",
            summary="Copy a skill from a folder of this computer into Wasify AI.",
            description=(
                "Add a skill the person has in a folder: a folder with a SKILL.md that names "
                "the skill, says what it is for, and holds the text for the agent. The folder "
                "is copied into Wasify AI; the person's folder is not changed and nothing "
                "comes from the internet. With session_id it is switched on for that "
                "session's project. A plugin (a folder with .plugin/plugin.json) is refused."
            ),
            input=ExtAddIn,
            output=ExtAddOut,
            examples=({"folder": "/Users/me/Documents/house-style"},),
            effect="make",
            requires=(need_product(PRODUCT_ID), ENGINE),
            product=PRODUCT_ID,
            bind=CallBinding(_ext_add),
            ui="code.extensions",
            surfaces=("assistant",),
        ),
        Action(
            id="code.project.new",
            title="Start a new coding project",
            summary="Make a new project from a starter in a new folder, with a session on it.",
            description=(
                "Make a new project in a new, empty folder and open a coding session on it. The "
                "starter `web` is a small web app with no build step: one page with its script "
                "and styles, tests, and a preview that loads again when a file changes. Give "
                "the folder the new one is made in (parent) and the project's name. Nothing is "
                "written anywhere else, and a folder that already holds files is refused. The "
                "project's check and preview commands are set. It returns the session's id."
            ),
            input=NewIn,
            output=StartOut,
            examples=({"parent": "/Users/me/Projects", "name": "bakery-site"},),
            effect="make",
            requires=(need_product(PRODUCT_ID), ENGINE),
            product=PRODUCT_ID,
            bind=CallBinding(_new),
            ui="code.projects",
            surfaces=("assistant",),
        ),
        Action(
            id="code.session.preview",
            title="Start or stop a project's preview",
            summary="Run a coding project on this computer and say where it can be seen.",
            description=(
                "Start a coding project's own run command (for example `npm run dev`) inside "
                "the project's sandbox, and say on which port of this computer it listens; the "
                "person sees the page in the session's Preview tab. With do stop it ends the "
                "preview and everything it started; with do state it only says where it is. "
                "The preview reaches the internet only to install packages."
            ),
            input=PreviewIn,
            output=PreviewOut,
            examples=(
                {"session_id": SAMPLE_ID},
                {"session_id": SAMPLE_ID, "do": "stop"},
            ),
            effect="change",
            requires=(need_product(PRODUCT_ID), ENGINE),
            long=True,
            product=PRODUCT_ID,
            bind=CallBinding(_preview),
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
