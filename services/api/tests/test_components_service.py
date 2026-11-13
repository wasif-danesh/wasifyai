"""The parts the engine's services set up, seen as components (stage F2): one status in the window's
shape, and set up, stop and remove, whatever the service's own state looks like."""

import pytest
from wasifyai_api.components.service import ServiceComponent
from wasifyai_platform_sdk.installer import InstallError, Step

STEPS = (Step("download", "Getting it"), Step("unpack", "Unpacking it"))


class InstallErrorOfItsOwn(Exception):
    pass


InstallErrorOfItsOwn.__name__ = "InstallError"  # each service has a class of this name


class Service:
    def __init__(self) -> None:
        self.installed = False
        self.progress = {"state": "idle"}
        self.started: list[int] = []
        self.removed = 0

    def state(self):
        return {"installed": self.installed, "tag": "v1", "backend": "metal",
                "plan": {"supported": True, "bytes": 500}, "install": self.progress}  # fmt: skip

    def start(self, confirm_bytes: int) -> None:
        if confirm_bytes != 500:
            raise InstallErrorOfItsOwn("The download changed since it was shown.")
        self.started.append(confirm_bytes)

    def remove(self) -> int:
        self.removed += 1
        return 1234


def part(s: Service) -> ServiceComponent:
    return ServiceComponent(
        "audiocpp", "Speech runtime", STEPS, s.state, s.start, progress_key="install",
        version_key="tag", accelerator_key="backend", remove=s.remove,
    )  # fmt: skip


def test_each_state_is_said_in_the_windows_shape():
    s = Service()
    c = part(s)
    assert c.status() == {"state": "not_installed", "needs_bytes": 500}
    s.progress = {"state": "installing", "step": "unpack", "message": "Unpacking",
                  "done_bytes": 200, "total_bytes": 500}  # fmt: skip
    st = c.status()
    assert st["state"] == "installing"
    assert st["progress"] == {"component": "audiocpp", "step": "unpack", "label": "Unpacking",
                              "index": 2, "count": 2, "bytes_done": 200, "bytes_total": 500,
                              "detail": None}  # fmt: skip
    s.progress = {"state": "failed", "step": "download", "message": "It did not match."}
    assert c.status() == {"state": "failed", "message": "It did not match.", "step": "download"}
    s.installed, s.progress = True, {"state": "ready"}
    assert c.status() == {"state": "installed", "version": "v1", "accelerator": "metal"}


def test_a_part_this_computer_cannot_have_says_why():
    c = ServiceComponent("x", "X", STEPS, lambda: {"installed": False,
                         "plan": {"supported": False}}, lambda b: None)  # fmt: skip
    assert c.status()["state"] == "unsupported"
    trainer = ServiceComponent("t", "T", STEPS, lambda: {"installed": False,
                               "problem": "Apple silicon only."}, lambda b: None)  # fmt: skip
    assert trainer.status() == {"state": "unsupported", "reason": "Apple silicon only."}


def test_set_up_passes_the_size_shown_and_its_refusal_is_the_installers():
    s = Service()
    c = part(s)
    c.install(500)
    assert s.started == [500]
    with pytest.raises(InstallError, match="changed since it was shown"):
        c.install(499)
    c.install(None, repair=True)  # try again: the size it shows now
    assert s.started == [500, 500]


def test_only_what_the_service_can_do_is_offered():
    s = Service()
    c = part(s)
    assert (c.can_stop, c.can_repair, c.can_remove) == (False, False, True)
    assert c.uninstall() == 1234 and s.removed == 1
    bare = ServiceComponent("x", "X", STEPS, s.state, s.start)
    assert not bare.can_remove and not bare.cancel()
    with pytest.raises(InstallError, match="cannot be removed"):
        bare.uninstall()
