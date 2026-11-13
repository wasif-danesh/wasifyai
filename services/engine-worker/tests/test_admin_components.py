"""`admin.fetch_engine` on an engine worker (stage F2): the lip sync engine and the trainers are set
up through the one installer's components, the same ones the desktop's Settings lists."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from wasifyai_engine_worker.admin import AdminComponent
from wasifyai_engine_worker.handlers import Failed


class Installer:
    """A lip sync installer that sets up in two steps (`total` bytes) or fails at the second."""

    def __init__(self, fail: bool = False, supported: bool = True) -> None:
        self.fail, self.supported = fail, supported
        self.installed = False
        self.progress = SimpleNamespace(
            public=lambda: dict(self.now), state="idle", message=""
        )  # fmt: skip
        self.now: dict[str, Any] = {"state": "idle"}
        self._task: asyncio.Task[None] | None = None

    def plan(self) -> dict[str, Any]:
        return {"supported": self.supported, "bytes": 100}

    def start(self, confirm_bytes: int) -> None:
        assert confirm_bytes == 100  # the size the plan shows
        # as the real ones: installing from the moment it is asked, then the work as a task
        self.now = {"state": "installing", "step": "source", "message": "Getting MuseTalk",
                    "done_bytes": 50, "total_bytes": 100}  # fmt: skip
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        await asyncio.sleep(0.02)
        if self.fail:
            self.now = {"state": "failed", "step": "packages", "message": "Are you online?"}
            return
        self.installed = True
        self.now = {"state": "ready"}


class Sidecar:
    def __init__(self, installer: Installer) -> None:
        self.installer = installer

    def state(self) -> dict[str, Any]:
        i = self.installer
        return {"installed": i.installed, "plan": i.plan(), "install": i.progress.public()}


def admin(installer: Installer | None) -> AdminComponent:
    speech = SimpleNamespace(lipsync_sidecar=Sidecar(installer) if installer else None)
    return AdminComponent(speech, poll_s=0.005)


async def test_the_lip_sync_engine_is_set_up_and_its_progress_is_told():
    told: list[tuple[float, str]] = []

    async def report(f: float, label: str) -> None:
        told.append((f, label))

    inst = Installer()
    done = await admin(inst).fetch_engine("lipsync-engine", report)
    assert done == {"name": "lipsync-engine", "already": False} and inst.installed
    assert told and told[0][1] == "Getting MuseTalk" and 0 < told[0][0] < 1
    again = await admin(inst).fetch_engine("lipsync-engine", report)
    assert again["already"] is True


async def _nothing(f: float, label: str) -> None:
    return None


@pytest.mark.parametrize(
    ("installer", "name", "code"),
    [
        (Installer(), "a-rocket", "unknown_engine"),
        (None, "lipsync-engine", "not_here"),
        (Installer(supported=False), "lipsync-engine", "not_supported"),
        (Installer(fail=True), "lipsync-engine", "install_failed"),
    ],
)
async def test_what_cannot_be_set_up_is_said_in_words(installer, name, code):
    with pytest.raises(Failed) as e:
        await admin(installer).fetch_engine(name, _nothing)
    assert e.value.code == code
