"""The approval desk on its own: whose card it is, two answers at once, an action that fails."""

import asyncio
from types import SimpleNamespace

import pytest
from wasifyai_api.mcp_server.approvals import ApprovalDesk, Pending
from wasifyai_platform_sdk.actions import ActionResult


class Executor:
    def __init__(self, fail: bool = False) -> None:
        self.decided = 0
        self.ran = 0
        self.fail = fail

    async def decide_approval(self, actor, approval_id, approved, by="window") -> bool:
        await asyncio.sleep(0.01)  # the store answers after a moment, as a database does
        self.decided += 1
        return self.decided == 1  # the store records one answer only

    async def run_action(self, action_id, params, origin, **kw) -> ActionResult:
        self.ran += 1
        if self.fail:
            raise RuntimeError("boom")
        return ActionResult(status="ok", action_id=action_id, text="Done.")


def card(desk: ApprovalDesk) -> Pending:
    who = SimpleNamespace(tenant_id="t1", user_id="u1", identity=None, origin="mcp")
    return desk.ask(
        Pending("a1", "library.delete", {}, who, None, "c1", "Claude Code", "Delete", "")  # type: ignore[arg-type]
    )


async def test_someone_elses_card_says_nothing_even_when_decided():
    desk = ApprovalDesk(Executor())  # type: ignore[arg-type]
    card(desk)
    assert (await desk.decide("t1", "u1", "a1", True)).status == "approved"  # type: ignore[union-attr]
    assert await desk.decide("t1", "u2", "a1", True) is None
    assert await desk.decide("t2", "u1", "a1", True) is None


async def test_a_double_click_runs_the_action_once_and_keeps_it_approved():
    ex = Executor()
    desk = ApprovalDesk(ex)  # type: ignore[arg-type]
    card(desk)
    first, second = await asyncio.gather(
        desk.decide("t1", "u1", "a1", True), desk.decide("t1", "u1", "a1", True)
    )
    assert ex.decided == 1 and ex.ran == 1
    assert first is second and first.status == "approved"  # type: ignore[union-attr]


async def test_an_action_that_fails_still_ends_the_wait_with_an_error():
    desk = ApprovalDesk(Executor(fail=True))  # type: ignore[arg-type]
    p = card(desk)
    with pytest.raises(RuntimeError):
        await desk.decide("t1", "u1", "a1", True)
    assert p.done.is_set() and p.result is not None and p.result.status == "error"
