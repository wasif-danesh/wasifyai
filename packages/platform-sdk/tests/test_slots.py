import asyncio

import pytest
from wasifyai_platform_sdk import SlotManager


class Unloads:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail: set[str] = set()
        self.delay = 0.0

    def make(self, owner: str):
        async def unload() -> None:
            self.calls.append(owner)
            await asyncio.sleep(self.delay)
            if owner in self.fail:
                raise RuntimeError("the backend did not answer")

        return unload


def slot(idle=None, owners=("image", "chat")) -> tuple[SlotManager, Unloads]:
    u = Unloads()
    return SlotManager({o: u.make(o) for o in owners}, idle_unload_s=idle), u


async def test_holders_run_one_at_a_time_in_order():
    s, _ = slot()
    log: list[str] = []

    async def job(name: str, owner: str = "image"):
        async with s.hold(owner):
            log.append(f"{name} start")
            await asyncio.sleep(0.02)
            log.append(f"{name} end")

    await asyncio.gather(job("a"), job("b"), job("c"))
    assert log == ["a start", "a end", "b start", "b end", "c start", "c end"]


async def test_the_same_owner_keeps_its_model_and_another_owner_evicts_it():
    s, u = slot()
    async with s.hold("image"):
        pass
    async with s.hold("image"):
        pass
    assert u.calls == [] and s.resident_owner == "image"
    async with s.hold("chat"):
        assert u.calls == ["image"]  # unloaded before the chat model's turn
        assert s.resident_owner == "chat"


async def test_an_idle_model_is_unloaded_once_and_memory_is_released():
    s, u = slot(idle=0.05)
    async with s.hold("image"):
        pass
    assert s.resident_owner == "image"
    await asyncio.sleep(0.15)
    assert u.calls == ["image"] and s.resident_owner is None
    await asyncio.sleep(0.1)
    assert u.calls == ["image"]  # not again


async def test_a_job_that_starts_before_the_idle_time_cancels_the_unload():
    s, u = slot(idle=0.1)
    async with s.hold("image"):
        pass
    await asyncio.sleep(0.06)
    async with s.hold("image"):  # arrives just before the timer would fire
        await asyncio.sleep(0.15)  # longer than the idle time, while holding
        assert u.calls == []
    await asyncio.sleep(0.05)
    assert u.calls == []  # the idle time starts again from the end of this job
    await asyncio.sleep(0.15)
    assert u.calls == ["image"]


async def test_a_job_that_arrives_during_an_idle_unload_waits_for_it():
    s, u = slot(idle=0.02)
    u.delay = 0.15
    async with s.hold("image"):
        pass
    await asyncio.sleep(0.06)  # the unload has started and is slow
    assert u.calls == ["image"]
    started = asyncio.get_running_loop().time()
    async with s.hold("image"):
        waited = asyncio.get_running_loop().time() - started
    assert waited > 0.05  # it did not run on top of the unload
    assert u.calls == ["image"]  # and the unload was not interrupted or repeated


async def test_a_failing_unload_is_logged_and_does_not_wedge_the_slot():
    s, u = slot()
    u.fail.add("image")
    async with s.hold("image"):
        pass
    async with s.hold("chat"):  # evicting image fails
        assert s.resident_owner == "chat"
    assert u.calls == ["image"]
    async with s.hold("chat"):
        pass


async def test_a_cancelled_holder_gives_the_slot_back():
    s, _ = slot()
    started = asyncio.Event()

    async def job():
        async with s.hold("image"):
            started.set()
            await asyncio.sleep(10)

    task = asyncio.create_task(job())
    await started.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert not s.holding
    async with asyncio.timeout(1):
        async with s.hold("image"):
            pass


async def test_unload_now_waits_for_the_running_job_then_unloads():
    s, u = slot()
    order: list[str] = []

    async def job():
        async with s.hold("image"):
            await asyncio.sleep(0.1)
            order.append("job done")

    t = asyncio.create_task(job())
    await asyncio.sleep(0.02)
    assert await s.unload_now() is True
    order.append("unloaded")
    await t
    assert order == ["job done", "unloaded"] and u.calls == ["image"]
    assert await s.unload_now() is False  # nothing resident any more


async def test_an_unknown_owner_is_an_error():
    s, _ = slot()
    with pytest.raises(KeyError):
        async with s.hold("video"):
            pass


async def test_lock_for_has_the_hold_the_job_processor_uses():
    s, _ = slot()
    lock = s.lock_for("image")
    async with lock.hold():
        assert s.holding and s.resident_owner == "image"


# ---- a small owner beside the resident one (ADR-0083, decision 5) -------------------------------


def sharing(answer: bool | Exception, owners=("image", "chat", "audio")):
    u = Unloads()
    asked: list[tuple[str, int, str]] = []

    async def can_share(owner: str, need: int, resident: str) -> bool:
        asked.append((owner, need, resident))
        if isinstance(answer, Exception):
            raise answer
        return answer

    return SlotManager({o: u.make(o) for o in owners}, None, can_share), u, asked


async def test_a_small_owner_that_fits_runs_beside_the_resident_model_and_evicts_nothing():
    s, u, asked = sharing(True)
    async with s.hold("chat"):
        pass
    async with s.hold("audio", beside_bytes=2_400_000_000) as held:
        assert held.shared and held.displaced is None
    assert u.calls == [] and s.resident_owner == "chat" and s.resident_owners == ["chat", "audio"]
    assert asked == [("audio", 2_400_000_000, "chat")]


async def test_a_small_owner_does_not_wait_for_the_model_that_is_answering():
    s, _, _ = sharing(True)
    answering = asyncio.Event()
    release = asyncio.Event()

    async def chat():
        async with s.hold("chat"):
            answering.set()
            await release.wait()

    t = asyncio.create_task(chat())
    await answering.wait()
    async with asyncio.timeout(1):  # would never come back if it queued behind the chat turn
        async with s.hold("audio", beside_bytes=1) as held:
            assert held.shared
    release.set()
    await t


async def test_when_they_do_not_fit_the_small_owner_takes_the_slot_and_says_what_it_unloaded():
    s, u, _ = sharing(False)
    async with s.hold("chat"):
        pass
    async with s.hold("audio", beside_bytes=1) as held:
        assert not held.shared and held.displaced == "chat"
    assert u.calls == ["chat"] and s.resident_owners == ["audio"]


async def test_a_check_that_fails_means_they_do_not_fit():
    s, u, _ = sharing(RuntimeError("memory could not be read"))
    async with s.hold("chat"):
        pass
    async with s.hold("audio", beside_bytes=1) as held:
        assert held.displaced == "chat"
    assert u.calls == ["chat"]


async def test_nothing_resident_or_its_own_model_means_no_question_and_no_displacing():
    s, u, asked = sharing(True)
    async with s.hold("audio", beside_bytes=1) as held:
        assert not held.shared and held.displaced is None
    async with s.hold("audio", beside_bytes=1) as held:
        assert not held.shared and held.displaced is None
    assert asked == [] and u.calls == []


async def test_an_ordinary_owner_arriving_unloads_the_small_one_beside_the_chat_model():
    s, u, _ = sharing(True)
    async with s.hold("chat"):
        pass
    async with s.hold("audio", beside_bytes=1):
        pass
    async with s.hold("image"):
        assert sorted(u.calls) == ["audio", "chat"]
        assert s.resident_owners == ["image"]


async def test_the_chat_model_staying_resident_keeps_the_small_one_beside_it():
    s, u, _ = sharing(True)
    async with s.hold("chat"):
        pass
    async with s.hold("audio", beside_bytes=1):
        pass
    async with s.hold("chat"):  # the next message
        pass
    assert u.calls == [] and s.resident_owners == ["chat", "audio"]


async def test_the_idle_time_unloads_both_and_a_running_dictation_finishes_first():
    u = Unloads()
    s = SlotManager({o: u.make(o) for o in ("chat", "audio")}, 0.05, lambda *a: _yes())
    async with s.hold("chat"):
        pass
    async with s.hold("audio", beside_bytes=1):
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.15)
    assert sorted(u.calls) == ["audio", "chat"] and s.resident_owners == []

    async with s.hold("chat"):
        pass
    done = []

    async def dictate():
        async with s.hold("audio", beside_bytes=1):
            await asyncio.sleep(0.2)  # longer than the idle time
            done.append(1)

    t = asyncio.create_task(dictate())
    await asyncio.sleep(0.01)
    assert await s.unload_now() is True
    assert done == [1]  # the clip was transcribed before its model went away
    await t


async def _yes() -> bool:
    return True
