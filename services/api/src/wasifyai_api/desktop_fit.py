"""Will this model fit on this computer? (ADR-0063, ADR-0056 decision 5)

    read_machine()        memory now: total, available, and the GPU's where it has its own
    need_of_*()           what a model asks for: weights plus what running it adds
    assess_fit()          `fits`, `tight` or `too_big`, with a reason in plain words

The rules, in one place so they can be tuned with measurements:

    device     capacity (more than this cannot work)   budget (what is free to use now)
    unified    90% of the memory (Apple silicon)       75% of it, or what is available if less
    cuda       the card's memory; a language model     the card's free memory; a language model
               may spill into 50% of the RAM           may spill into 50% of the available RAM
    cpu        85% of the memory                       what is available

    need > capacity            too_big   refused with the reason; never started
    need > budget              tight     allowed after a confirmation; may be slow or fail
    otherwise                  fits

What the computer already holds for the app's own loaded model (the slot's resident model) counts as
available: it is the same memory the next model would be loaded into. Estimates for models we have
not measured are marked as such. Measured here: FLUX.2 klein 4B peaks at about 17.6 GB
(docs/spikes).
"""

import os
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Any

GB = 1_000_000_000
LLM_OVERHEAD = int(0.6 * GB)  # the runtime's own buffers
DEFAULT_CONTEXT = 8192  # what a chat is judged at, not the model's largest context


# ---- the computer -----------------------------------------------------------------------------


def physical_memory_bytes() -> int | None:
    try:
        if sys.platform == "win32":
            return _win_memory()[0]
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, AttributeError):
        return None


def _win_memory() -> tuple[int, int]:
    import ctypes

    class Status(ctypes.Structure):
        _fields_ = [  # noqa: RUF012
            ("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
            ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
            ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
            ("total_virt", ctypes.c_ulonglong), ("avail_virt", ctypes.c_ulonglong),
            ("avail_ext", ctypes.c_ulonglong),
        ]  # fmt: skip

    st = Status()
    st.length = ctypes.sizeof(Status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))  # type: ignore[attr-defined]
    return int(st.total_phys), int(st.avail_phys)


def parse_vm_stat(text: str) -> int | None:
    """Bytes a Mac can give a program now: free, inactive and speculative pages."""
    page = 16384
    pages = 0
    for line in text.splitlines():
        if "page size of" in line:
            digits = "".join(c for c in line.split("page size of")[1] if c.isdigit())
            page = int(digits) if digits else page
        name, _, value = line.partition(":")
        if name.strip() in ("Pages free", "Pages inactive", "Pages speculative"):
            pages += int("".join(c for c in value if c.isdigit()) or 0)
    return pages * page if pages else None


def available_memory_bytes() -> int | None:
    try:
        if sys.platform == "win32":
            return _win_memory()[1]
        if sys.platform == "darwin":
            out = subprocess.run(
                ["vm_stat"], capture_output=True, text=True, timeout=3, check=False
            )
            return parse_vm_stat(out.stdout)
        with open("/proc/meminfo") as f:  # noqa: PTH123
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return None


def parse_nvidia_smi(text: str) -> tuple[int, int] | None:
    """(total, free) bytes of the card with the most memory (`--format=csv,noheader,nounits`)."""
    best: tuple[int, int] | None = None
    for line in text.strip().splitlines():
        try:
            total, free = (int(x.strip()) * 1024 * 1024 for x in line.split(",")[:2])
        except ValueError:
            continue
        if best is None or total > best[0]:
            best = (total, free)
    return best


def nvidia_memory() -> tuple[int, int] | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4, check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_nvidia_smi(out.stdout) if out.returncode == 0 else None


@dataclass(frozen=True)
class Machine:
    """What the computer has, now. `device`: unified (Apple silicon), cuda or cpu."""

    device: str
    total_bytes: int | None
    available_bytes: int | None
    gpu_total_bytes: int | None = None
    gpu_free_bytes: int | None = None
    reclaimable_bytes: int = 0  # held by the app's own resident model: free to the next one

    def public(self) -> dict[str, Any]:
        return asdict(self)


def read_machine(reclaimable_bytes: int = 0) -> Machine:
    total, avail = physical_memory_bytes(), available_memory_bytes()
    gpu = nvidia_memory() if sys.platform != "darwin" else None
    if sys.platform == "darwin" and platform.machine() == "arm64":
        device = "unified"
    elif gpu:
        device = "cuda"
    else:
        device = "cpu"
    return Machine(
        device, total, avail, gpu[0] if gpu else None, gpu[1] if gpu else None, reclaimable_bytes
    )


def process_rss_bytes(pid: int | None) -> int:
    """Resident memory of a process, 0 when unknown. Used for the app's own model server."""
    if not pid:
        return 0
    try:
        if sys.platform == "linux":
            with open(f"/proc/{pid}/statm") as f:  # noqa: PTH123
                return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        if sys.platform == "darwin":
            out = subprocess.run(
                ["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=3,
                check=False,
            )  # fmt: skip
            return int(out.stdout.strip() or 0) * 1024
        if sys.platform == "win32":
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5, check=False,
            )  # fmt: skip
            digits = "".join(c for c in out.stdout.split('","')[-1] if c.isdigit())
            return int(digits) * 1024 if digits else 0
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return 0
    return 0


# ---- what a model asks for --------------------------------------------------------------------


@dataclass(frozen=True)
class Need:
    bytes: int
    estimate: bool  # False only for a figure we measured or the catalogue declares
    spills: bool = False  # a language model can run partly on the processor


def kv_cache_bytes(layers: int, kv_heads: int, head_dim: int, context: int) -> int:
    """Keys and values, 16-bit, for `context` tokens."""
    return 2 * layers * kv_heads * head_dim * context * 2


def need_of_language(
    weights: int,
    layers: int = 0,
    kv_heads: int = 0,
    head_dim: int = 0,
    context: int = 0,
    chosen: int | None = None,
) -> Need:
    """`context` is what the model supports (judged at the chat default); `chosen` is the
    context the person set, used as it is."""
    ctx = chosen or (min(context, DEFAULT_CONTEXT) if context else 4096)
    kv = (
        kv_cache_bytes(layers, kv_heads, head_dim, ctx)
        if layers and kv_heads and head_dim
        else int(weights * 0.1)
    )  # without the shape, a tenth of the weights is a fair guess for a chat
    return Need(weights + kv + LLM_OVERHEAD, estimate=True, spills=True)


def need_of_image(weights: int, video: bool = False) -> Need:
    """One file or repo of an image or video model: weights plus working memory at about 1 MP / a
    short clip. A guess; the catalogue's declared figure is used where there is one."""
    return Need(int(weights * 1.15) + (6 if video else 3) * GB, estimate=True)


def need_declared(gb: float) -> Need:
    return Need(int(gb * GB), estimate=False)


# ---- the verdict ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fit:
    verdict: str  # fits, tight, too_big
    reason: str
    needed_bytes: int
    budget_bytes: int | None
    capacity_bytes: int | None
    estimate: bool
    partly_on_cpu: bool = False

    def public(self) -> dict[str, Any]:
        return asdict(self)


def _gb(n: int | float) -> str:
    v = n / GB
    return f"{v:.0f} GB" if v >= 10 else f"{v:.1f} GB"


def limits(machine: Machine, spills: bool) -> tuple[int | None, int | None, bool]:
    """(capacity, budget, runs partly on the processor) for this computer."""
    total, avail = machine.total_bytes, machine.available_bytes
    free = (avail or 0) + machine.reclaimable_bytes if avail is not None else None
    if machine.device == "cuda" and machine.gpu_total_bytes:
        capacity = machine.gpu_total_bytes
        budget = (machine.gpu_free_bytes or 0) + machine.reclaimable_bytes
        if spills and total:
            capacity += int(0.5 * total)
            budget += int(0.5 * (free if free is not None else total))
        return capacity, budget, spills
    if total is None:
        return None, None, False
    if machine.device == "unified":
        capacity = int(0.9 * total)
        budget = min(int(0.75 * total), free) if free is not None else int(0.75 * total)
        return capacity, budget, False
    capacity = int(0.85 * total)
    return capacity, (min(capacity, free) if free is not None else capacity), False


def assess_fit(need: Need, machine: Machine) -> Fit:
    capacity, budget, partly = limits(machine, need.spills)
    about = "about " if need.estimate else ""
    if capacity is None:
        return Fit("fits", "This computer's memory could not be read, so the fit is not checked.",
                   need.bytes, None, None, need.estimate)  # fmt: skip
    if need.bytes > capacity:
        return Fit(
            "too_big",
            f"It needs {about}{_gb(need.bytes)} and this computer can give it {_gb(capacity)} at "
            "most. It will not run here. Choose a smaller model or a smaller version of it.",
            need.bytes, budget, capacity, need.estimate, partly,
        )  # fmt: skip
    if budget is not None and need.bytes > budget:
        return Fit(
            "tight",
            f"It needs {about}{_gb(need.bytes)} and about {_gb(budget)} is free right now. It may "
            "run slowly or fail; closing other apps helps.",
            need.bytes, budget, capacity, need.estimate, partly,
        )  # fmt: skip
    where = (
        " and part of it will run on the processor, which is slower"
        if partly and (machine.gpu_total_bytes and need.bytes > machine.gpu_total_bytes)
        else ""
    )
    return Fit(
        "fits",
        f"It needs {about}{_gb(need.bytes)}{where}"
        + (f"; {_gb(budget)} is free." if budget is not None else "."),
        need.bytes, budget, capacity, need.estimate, partly,
    )  # fmt: skip
