"""A component whose setup lives with the service that runs it (stage F2): the speech runtime, lip
sync, 3D, Motion graphics, the four trainers and the notebooks reader.

Each of them keeps its own screen card (with what only it shows: the fit, the sandbox, the models)
and its own state file; what they share is fetched through the core's steps (`core.download`,
`core.unpack`, `core.make_environment`). Here each is seen the way every component is: one status
in the window's shape, and install, cancel and uninstall, so `/components` and the one Settings
screen cover all of them. `ServiceComponent` reads the service's own state (`installed`, `plan`,
and its progress) and says it in that shape.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from wasifyai_platform_sdk.installer import (
    InstallError,
    Step,
    status_failed,
    status_installed,
    status_missing,
    status_unsupported,
)

NOT_HERE = "This is not available on this computer yet."


@dataclass
class ServiceComponent:
    id: str
    title: str
    steps: Sequence[Step]
    state: Callable[[], dict[str, Any]]  # the service's own state
    start: Callable[[int], None]  # start setting it up, with the size the person was shown
    progress_key: str = "progress"  # where the state keeps its install progress
    version_key: str = ""  # the field that names what is installed ("tag", "tool")
    accelerator_key: str = ""  # the field that says what it runs on ("backend")
    stop: Callable[[], bool] | None = None
    remove: Callable[[], int] | None = None
    finish: Callable[[], Awaitable[None]] | None = None

    @property
    def can_stop(self) -> bool:
        return self.stop is not None

    can_repair = False  # its service sets up what is missing only; Remove, then Set up, starts over

    @property
    def can_remove(self) -> bool:
        return self.remove is not None

    def status(self) -> dict[str, Any]:
        st = self.state()
        prog = st.get(self.progress_key) or {}
        if prog.get("state") == "installing":
            ids = [s.id for s in self.steps]
            step = str(prog.get("step") or (ids[0] if ids else ""))
            index = ids.index(step) if step in ids else 0
            label = next((s.label for s in self.steps if s.id == step), "")
            total = int(prog.get("total_bytes") or 0)
            return {
                "state": "installing",
                "progress": {
                    "component": self.id, "step": step, "label": str(prog.get("message") or label),
                    "index": index + 1, "count": max(1, len(ids)),
                    "bytes_done": int(prog.get("done_bytes") or 0) if total else None,
                    "bytes_total": total or None, "detail": None,
                },
            }  # fmt: skip
        if st.get("installed"):
            version = str(st.get(self.version_key) or "") if self.version_key else ""
            accel = str(st.get(self.accelerator_key) or "") if self.accelerator_key else ""
            return status_installed(version, accel)
        if prog.get("state") == "failed":
            return status_failed(str(prog.get("message") or "It did not set up."), prog.get("step"))
        plan = st.get("plan") or {}
        if plan.get("supported") is False or st.get("problem"):
            return status_unsupported(str(st.get("problem") or NOT_HERE))
        return status_missing(int(plan.get("bytes") or 0))

    def install(self, confirm_bytes: int | None, repair: bool = False) -> None:
        if confirm_bytes is None:  # a repair: what it would fetch now is what was shown
            confirm_bytes = int((self.state().get("plan") or {}).get("bytes") or 0)
        try:
            self.start(confirm_bytes)
        except Exception as e:  # each service's own InstallError: a sentence safe to show
            if type(e).__name__ != "InstallError":
                raise
            raise InstallError(str(e)) from None

    def cancel(self) -> bool:
        return self.stop() if self.stop is not None else False

    def uninstall(self) -> int:
        if self.remove is None:
            raise InstallError("This cannot be removed from here yet.")
        try:
            return self.remove()
        except Exception as e:
            if type(e).__name__ != "InstallError":
                raise
            raise InstallError(str(e)) from None

    async def wait(self) -> None:
        if self.finish is not None:
            await self.finish()
