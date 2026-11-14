"""The place interface and its pretended place (ADR-0101, decision 5)."""

import asyncio
from pathlib import Path

import pytest
from wasifyai_code import place as places
from wasifyai_code.place import (
    Busy,
    FakePlace,
    FakeTurn,
    NoSuchSession,
    Place,
    PlaceError,
    PlaceEvent,
    SessionSpec,
    scripted,
)


async def until_ended(place: Place, session: str, after: str | None = None) -> list[PlaceEvent]:
    seen = []
    async for event in place.follow(session, after):
        seen.append(event)
        if event.kind == places.ENDED:
            break
    return seen


def kinds(events: list[PlaceEvent]) -> list[str]:
    return [e.kind for e in events]


async def test_a_session_is_started_sent_to_followed_and_ends(tmp_path: Path):
    async def agent(turn: FakeTurn) -> None:
        turn.piece("I will ")
        turn.piece("write it.")
        turn.say("I will write it.")
        turn.write("src/app.py", f"# {turn.text}\n")

    place: Place = FakePlace(agent)  # the pretended place is a Place
    session = await place.start(SessionSpec(tmp_path))
    await place.send(session, "add a file")
    events = await until_ended(place, session)

    assert kinds(events) == ["state", "piece", "piece", "text", "step", "state", "ended"]
    assert events[0].data == {"state": "running"} and events[-2].data == {"state": "idle"}
    assert events[-1].data == {"why": "finished", "detail": "", "steps": 1}
    assert (tmp_path / "src" / "app.py").read_text() == "# add a file\n"  # a real file
    assert len({e.id for e in events}) == len(events) and all(
        e.at.endswith("+00:00") for e in events
    )
    assert set(kinds(events)) <= set(places.EVENT_KINDS)


async def test_following_from_an_event_gives_only_what_came_after(tmp_path):
    place = FakePlace(scripted(lambda t: _say(t, "one"), lambda t: _say(t, "two")))
    session = await place.start(SessionSpec(tmp_path))
    await place.send(session, "first")
    first = await until_ended(place, session)
    await place.send(session, "second")
    second = await until_ended(place, session, after=first[-1].id)

    assert [e.data.get("text") for e in second if e.kind == "text"] == ["two"]
    assert not {e.id for e in first} & {e.id for e in second}
    everything = await until_ended(place, session)  # from the start: the kept ones, in order
    assert everything == first
    with pytest.raises(PlaceError):
        await until_ended(place, session, after="no-such-event")


async def _say(turn: FakeTurn, text: str) -> None:
    turn.say(text)


async def test_a_message_can_be_sent_without_running_and_run_later(tmp_path):
    heard = []

    async def agent(turn: FakeTurn) -> None:
        heard.append(turn.text)

    place = FakePlace(agent)
    session = await place.start(SessionSpec(tmp_path))
    await place.send(session, "first part", run=False)
    await place.send(session, "second part", run=False)
    assert not place.running(session) and heard == []
    await place.run(session)
    await until_ended(place, session)
    assert heard == ["first part\n\nsecond part"]
    assert place.sent(session) == ["first part", "second part"]


async def test_stop_interrupts_a_turn_and_the_session_can_go_on(tmp_path):
    async def agent(turn: FakeTurn) -> None:
        if turn.number == 1:
            turn.write("half.txt", "half")
            await asyncio.Event().wait()
        turn.say("the second turn")

    place = FakePlace(agent)
    session = await place.start(SessionSpec(tmp_path))
    await place.stop(session)  # stopping an idle session is allowed
    await place.send(session, "go")
    await asyncio.sleep(0.01)
    with pytest.raises(Busy):
        await place.send(session, "more")
    with pytest.raises(Busy):
        await place.run(session)
    await place.stop(session)

    first = await until_ended(place, session)
    assert first[-1].data["why"] == "stopped" and not place.running(session)
    await place.send(session, "again")
    second = await until_ended(place, session, after=first[-1].id)
    assert second[-1].data["why"] == "finished"


async def test_a_confirmation_waits_for_its_answer(tmp_path):
    async def agent(turn: FakeTurn) -> None:
        turn.say("allowed" if await turn.confirm("rm -rf build") else "refused")

    place = FakePlace(agent)
    session = await place.start(SessionSpec(tmp_path))
    for allow, said in ((True, "allowed"), (False, "refused")):
        last = place.events(session)[-1].id if place.events(session) else None
        await place.send(session, "clean up")
        async for event in place.follow(session, last):
            if event.kind == places.CONFIRM:
                assert event.data["what"] == "rm -rf build" and place.running(session)
                await place.answer(session, event.data["id"], allow, "because")
                with pytest.raises(PlaceError):
                    await place.answer(session, event.data["id"], allow)  # once only
            if event.kind == places.ENDED:
                break
        assert place.events(session, "text")[-1].data["text"] == said


async def test_the_step_limit_an_error_and_a_refusal_each_end_the_turn_their_own_way(tmp_path):
    async def many(turn: FakeTurn) -> None:
        for n in range(10):
            turn.step("terminal", command=f"echo {n}")

    async def breaks(turn: FakeTurn) -> None:
        raise RuntimeError("no answer from the model")

    async def refuses(turn: FakeTurn) -> str:
        return places.REFUSED

    async def exactly(turn: FakeTurn) -> None:
        for n in range(3):
            turn.step("terminal", command=f"echo {n}")

    place = FakePlace(scripted(many, breaks, refuses, exactly))
    session = await place.start(SessionSpec(tmp_path, step_limit=3))
    ends, last = [], None
    for _ in range(4):
        await place.send(session, "go")
        events = await until_ended(place, session, last)
        last = events[-1].id
        ends.append((events[-1].data["why"], events[-1].data["detail"], events[-1].data["steps"]))

    assert ends == [
        ("step_limit", "", 3),
        ("error", "no answer from the model", 0),
        ("refused", "", 0),
        ("finished", "", 3),  # a finish on the last allowed step is a finish
    ]
    assert {e[0] for e in ends} <= set(places.ENDINGS)


async def test_an_unknown_session_is_refused_everywhere(tmp_path):
    place = FakePlace()
    for call in (
        place.send("nope", "x"),
        place.run("nope"),
        place.stop("nope"),
        place.answer("nope", "c", True),
    ):
        with pytest.raises(NoSuchSession):
            await call
    with pytest.raises(NoSuchSession):
        await until_ended(place, "nope")


async def test_what_a_session_was_started_with_is_kept(tmp_path):
    place = FakePlace()
    spec = SessionSpec(
        tmp_path, model="first-model", step_limit=7, unattended=True, ask=(r"rm -rf",)
    )
    session = await place.start(spec)
    assert place.calls == [("start", session, spec)]
