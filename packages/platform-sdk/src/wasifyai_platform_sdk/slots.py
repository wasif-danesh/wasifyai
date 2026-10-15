"""The slot: one large local model in memory at a time (ADR-0056, decision 5).

A computer has memory for one big model. Whoever wants to run (the image engine now; a local chat
model later) takes the slot with `hold(owner)`:

- holders run one at a time, in the order they ask;
- if the model resident in memory belongs to another owner it is unloaded first;
- when nobody holds the slot, the resident model is unloaded after `idle_unload_s`, so memory goes
  back to the rest of the computer;
- an unload that fails is logged and does not wedge the slot.

Unload is a callable per owner (for ComfyUI: its `/free` endpoint). The behaviours that Unsloth's
`gpu_arbiter.py` had to learn the hard way are tests here: an idle timer that fires while a job is
starting, a holder that is cancelled, an unload that is interrupted by a new job.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

log = logging.getLogger(__name__)

Unloader = Callable[[], Awaitable[None]]


class SlotManager:
    def __init__(self, unloaders: dict[str, Unloader], idle_unload_s: float | None = 600.0):
        self._unloaders = unloaders
        self._idle = idle_unload_s
        self._lock = asyncio.Lock()
        self._owner: str | None = None  # whose model is resident
        self._holding = False
        self._timer: asyncio.Task[None] | None = None
        self._unloading = False

    # ---- state ---------------------------------------------------------------------------

    @property
    def resident_owner(self) -> str | None:
        """Whose model is in memory (None: nothing, as far as the slot knows)."""
        return self._owner

    @property
    def holding(self) -> bool:
        return self._holding

    # ---- taking the slot -----------------------------------------------------------------

    @asynccontextmanager
    async def hold(self, owner: str) -> AsyncIterator[None]:
        if owner not in self._unloaders:
            raise KeyError(f"unknown slot owner {owner!r}")
        self._cancel_timer()
        async with self._lock:
            self._cancel_timer()
            if self._owner is not None and self._owner != owner:
                await self._unload(self._owner)
            self._owner = owner  # from here the owner's model may be in memory
            self._holding = True
            try:
                yield
            finally:
                self._holding = False
                self._arm_timer()

    def lock_for(self, owner: str) -> "OwnerLock":
        """An object with the `hold()` the media worker's job processor expects."""
        return OwnerLock(self, owner)

    async def unload_now(self) -> bool:
        """Unload the resident model now, waiting for a running job to finish first. Returns whether
        anything was unloaded."""
        self._cancel_timer()
        async with self._lock:
            if self._owner is None:
                return False
            await self._unload(self._owner)
            return True

    # ---- internals -----------------------------------------------------------------------

    async def _unload(self, owner: str) -> None:
        """Called with the lock held."""
        self._unloading = True
        try:
            await self._unloaders[owner]()
        except Exception:
            log.warning("could not unload the %s model", owner, exc_info=True)
        finally:
            self._unloading = False
            self._owner = None  # whatever happened, do not count on it being resident

    def _arm_timer(self) -> None:
        if self._idle is None or self._owner is None:
            return
        self._timer = asyncio.get_running_loop().create_task(self._idle_unload())

    def _cancel_timer(self) -> None:
        # An unload already under way is not interrupted: it finishes and the new holder waits.
        if self._timer is not None and not self._unloading:
            self._timer.cancel()
        self._timer = None if not self._unloading else self._timer

    async def _idle_unload(self) -> None:
        assert self._idle is not None
        await asyncio.sleep(self._idle)
        async with self._lock:  # a job that started meanwhile holds it, and cancelled this timer
            if self._owner is not None and not self._holding:
                await self._unload(self._owner)


class OwnerLock:
    """`GpuLock` for the media worker's `JobProcessor`: its `hold()` takes the slot as one owner."""

    def __init__(self, slot: SlotManager, owner: str):
        self._slot = slot
        self._owner = owner

    def hold(self):
        return self._slot.hold(self._owner)
