"""The components of the desktop engine, as `/components` lists them (stage F2): the two engines on
the core's installer, and the services that set up their own parts (`ServiceComponent`)."""

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

from wasifyai_platform_sdk.installer import Step

from wasifyai_api.components.service import ServiceComponent

TRAINER_STEPS = (
    Step("disk", "Checking free space"),
    Step("environment", "Preparing its environment"),
    Step("packages", "Installing its packages"),
    Step("model", "Getting the model it learns on"),
    Step("check", "Checking that it starts"),
)


def _waiter(obj: Any) -> Callable[[], Any] | None:
    """An installer's wait, or one that waits for its task."""
    if callable(getattr(obj, "wait", None)):
        return obj.wait
    if not hasattr(obj, "_task"):
        return None

    async def wait() -> None:
        task = getattr(obj, "_task", None)
        if task is not None:
            with contextlib.suppress(BaseException):
                await asyncio.gather(task, return_exceptions=True)

    return wait


def _cancel(obj: Any) -> Callable[[], bool] | None:
    return obj.cancel if callable(getattr(obj, "cancel", None)) else None


TRAINER_TITLES = {
    "trainer-pictures": "Picture trainer (mflux)",
    "trainer-writing": "Writing trainer (mlx-lm)",
    "trainer-deciding": "Decision trainer (Laya)",
    "trainer-video": "Video trainer (diffusers)",
    "music-analysis": "Song analysis (beat_this)",
}


def trainer_part(cid: str, setup: Any) -> ServiceComponent:
    """A trainer's component (`TrainingSetup` and its kin), here and on an engine worker."""
    return ServiceComponent(
        cid, TRAINER_TITLES[cid], TRAINER_STEPS, setup.state, setup.start, stop=setup.cancel,
        remove=setup.remove, finish=setup.wait,
    )  # fmt: skip


def lipsync_part(sidecar: Any) -> ServiceComponent:
    """The lip sync engine's component (MuseTalk), here and on an engine worker."""
    lip = sidecar.installer
    return ServiceComponent(
        "musetalk", "Lip sync engine (MuseTalk)",
        (Step("source", "Getting MuseTalk"), Step("unpack", "Unpacking it"),
         Step("environment", "Creating its environment"),
         Step("packages", "Installing its packages"), Step("verify", "Checking that it starts")),
        sidecar.state, lip.start, progress_key="install", stop=_cancel(lip), finish=_waiter(lip),
    )  # fmt: skip


def service_components(services: Any, desktop: Any) -> list[ServiceComponent]:
    """The parts the desktop's own services set up, as components."""
    found: list[ServiceComponent] = []
    audio = desktop.audio
    if audio is not None:
        inst = audio.installer
        found.append(ServiceComponent(
            "audiocpp", "Speech runtime (audio.cpp)",
            (Step("download", "Getting the speech runtime"), Step("unpack", "Unpacking it"),
             Step("check", "Checking that it starts")),
            audio.state, inst.start, progress_key="install", version_key="tag",
            accelerator_key="backend", stop=_cancel(inst), finish=_waiter(inst),
        ))  # fmt: skip
        if audio.lipsync_sidecar is not None:
            found.append(lipsync_part(audio.lipsync_sidecar))
    model3d = desktop.model3d
    if model3d is not None:
        inst = model3d.installer
        found.append(ServiceComponent(
            "model3d", "3D engine (Pixal3D)",
            (Step("engine", "Getting the 3D engine"), Step("verify", "Checking that it starts"),
             Step("models", "Getting the 3D models")),
            model3d.state, inst.start, stop=_cancel(inst), remove=model3d.remove,
            finish=_waiter(inst),
        ))  # fmt: skip
    builder = desktop.video_builder
    if builder is not None:
        inst = builder.installer
        found.append(ServiceComponent(
            "video-builder", "Motion graphics engine",
            (Step("node", "Getting Node.js"), Step("browser", "Getting the browser"),
             Step("unpack", "Unpacking"), Step("packages", "Installing its packages"),
             Step("verify", "Checking that it starts")),
            builder.state, inst.start, stop=_cancel(inst), remove=builder.remove,
            finish=_waiter(inst),
        ))  # fmt: skip
    for cid, setup in (
        ("trainer-pictures", desktop.training_setup),
        ("trainer-writing", desktop.language_setup),
        ("trainer-deciding", desktop.decision_setup),
        ("trainer-video", desktop.video_setup),
        ("music-analysis", desktop.music_analysis),
    ):
        if setup is not None:
            found.append(trainer_part(cid, setup))
    found.append(_reader(services))
    return found


def _reader(services: Any) -> ServiceComponent:
    """The notebooks' document reader (Docling), made by the notebooks runtime on first use."""

    def installer() -> Any:
        try:
            from wasifyai_notebooks.runtime import runtime_for
        except ImportError:
            return None
        try:
            return runtime_for(services)
        except Exception:
            return None

    def state() -> dict[str, Any]:
        rt = installer()
        inst = rt.installer if rt is not None else None
        if inst is None:
            problem = (
                rt.installer_problem if rt is not None else "Notebooks are not part of this build."
            )
            return {"installed": False, "problem": problem or "The reader is not available here."}
        return {
            "installed": inst.is_installed(),
            "plan": {"supported": True, "bytes": inst.total_bytes},
            "progress": inst.progress.public(),
        }

    def start(confirm_bytes: int) -> None:
        rt = installer()
        if rt is None or rt.installer is None:
            from wasifyai_platform_sdk.installer import InstallError

            raise InstallError("The reader is not available here.")
        rt.installer.start(confirm_bytes)

    async def finish() -> None:
        rt = installer()
        if rt is not None and rt.installer is not None:
            await rt.installer.wait()

    return ServiceComponent(
        "reader", "Notebooks document reader (Docling)",
        (Step("disk", "Checking free space"), Step("environment", "Preparing its environment"),
         Step("packages", "Installing its packages"), Step("weights", "Getting its models"),
         Step("check", "Checking that it starts")),
        state, start, finish=finish,
    )  # fmt: skip
