"""Long chains from the chat (docs/chat-does-everything-plan.md, CE7): one ask carried step by
step, each step given the ids of the one before; a long step waited on with its progress; and
Stop stops the step that is running, not only the words."""

import asyncio

import pytest
from assistant_rig import FakeHost, Rig
from pydantic import BaseModel
from wasifyai_platform_sdk.actions import (
    Action,
    ActionExecutor,
    ActionRegistry,
    CallBinding,
    Outcome,
    builtin_actions,
)


class PlanIn(BaseModel):
    text: str


class PlanOut(BaseModel):
    plan_id: str


class MakeIn(BaseModel):
    plan_id: str


class MakeOut(BaseModel):
    track_id: str


def chain_actions(made: list[str], started: asyncio.Event, stopped: list[str], hold: bool):
    async def plan(p: PlanIn, _ctx) -> Outcome:
        return Outcome.ok({"plan_id": "plan-1"}, "Found 3 chapters.")

    async def make(p: MakeIn, ctx) -> Outcome:
        made.append(p.plan_id)
        ctx.emit({"event": "job_progress", "job_id": "j1", "progress": 0.5})
        started.set()
        if hold:
            try:
                await asyncio.sleep(30)  # the person presses Stop here
            except asyncio.CancelledError:
                stopped.append(p.plan_id)
                raise
        return Outcome.ok({"track_id": "track-1"}, "The audiobook was made.")

    common = {"product": "wasifyai-voice", "surfaces": ("assistant",), "ui_exempt": "test"}
    return [
        Action(
            id="test.plan", title="Plan", summary="Plan.", description="Plan.", input=PlanIn,
            output=PlanOut, effect="read", bind=CallBinding(plan), **common,
        ),
        Action(
            id="test.make", title="Make", summary="Make.", description="Make.", input=MakeIn,
            output=MakeOut, effect="make", long=True, bind=CallBinding(make), **common,
        ),
    ]  # fmt: skip


def propose(action_id: str, **params) -> dict:
    return {"name": "propose_action", "arguments": {"action_id": action_id, "params": params}}


def rig_with(tmp_path, replies: list[dict], *, hold: bool = False):
    made: list[str] = []
    stopped: list[str] = []
    started = asyncio.Event()
    host = FakeHost()
    rig = Rig(tmp_path, replies, host)
    rig.caps.extras["actions"] = ActionExecutor(
        ActionRegistry([*builtin_actions(), *chain_actions(made, started, stopped, hold)]), host
    )
    return rig, made, started, stopped


async def test_one_ask_is_carried_step_by_step_with_the_ids_of_each_step(tmp_path, ctx):
    rig, made, _, _ = rig_with(
        tmp_path,
        [
            {"tool_calls": [propose("test.plan", text="Chapter 1. A cold morning.")]},
            {"tool_calls": [propose("test.make", plan_id="plan-1")]},
            {"text": "Your audiobook is ready."},
        ],
    )
    state, events = await rig.turn("make an audiobook of this: Chapter 1. A cold morning.")
    assert state["status"] == "done" and made == ["plan-1"]
    # the model was told the plan's id after the first step, and the track's after the second
    told = [str(m.get("content")) for m in rig.model.chats[1]["messages"] if m["role"] == "tool"]
    assert any("plan-1" in t for t in told)
    told = [str(m.get("content")) for m in rig.model.chats[2]["messages"] if m["role"] == "tool"]
    assert any("track-1" in t for t in told)
    # the long step said where it was
    assert any(e["type"] == "job_progress" for e in events)


async def test_stop_stops_the_long_step_that_is_running(tmp_path, ctx):
    rig, made, started, stopped = rig_with(
        tmp_path, [{"tool_calls": [propose("test.make", plan_id="plan-1")]}], hold=True
    )
    task = asyncio.create_task(rig.turn("make the audiobook"))
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert made == ["plan-1"] and stopped == ["plan-1"]
