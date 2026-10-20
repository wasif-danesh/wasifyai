"""The slot: one large local model in memory at a time (ADR-0056, decision 5).

A computer has memory for one big model. Whoever wants to run (the image engine now; a local chat
model later) takes the slot with `hold(owner)`:

- holders run one at a time, in the order they ask;
- if the model resident in memory belongs to another owner it is unloaded first;
- when nobody holds the slot, the resident model is unloaded after `idle_unload_s`, so memory goes
  back to the rest of the computer;
- an unload that fails is logged and does not wedge the slot;
- a small owner (a speech model, 2.4 GB) may ask to stay *beside* the resident one:
  `hold(owner, beside_bytes=...)`. When `can_share` says the two fit in memory together, the
  resident model is left alone and the small one runs without waiting for it (dictation while the
  chat model is writing); otherwise it takes the slot like any owner, the other model is unloaded
  and the holder is told so (`Held.displaced`) (ADR-0083, decision 5, the "light owner" rule).

Unload is a callable per owner (for ComfyUI: its `/free` endpoint). The behaviours that Unsloth's
`gpu_arbiter.py` had to learn the hard way are tests here: an idle timer that fires while a job is
starting, a holder that is cancelled, an unload that is interrupted by a new job.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

log = logging.getLogger(__name__)

Unloader = Callable[[], Awaitable[None]]
# (the small owner, the bytes it needs, the owner already resident) -> do the two fit together?
Sharer = Callable[[str, int, str], Awaitable[bool]]


@dataclass
class Held:
    """What a holder learns when it has the slot."""

    shared: bool = False  # it runs beside another owner's resident model
    displaced: str | None = None  # whose model was unloaded to make room for it


class SlotManager:
    def __init__(
        self,
        unloaders: dict[str, Unloader],
        idle_unload_s: float | None = 600.0,
        can_share: Sharer | None = None,
    ):
        self._unloaders = unloaders
        self._idle = idle_unload_s
        self._can_share = can_share
        self._lock = asyncio.Lock()
        self._owner: str | None = None  # whose model is resident
        self._beside: set[str] = set()  # small owners whose model is in memory beside `_owner`'s
        self._beside_locks: dict[str, asyncio.Lock] = {}  # held while a small owner is running
        self._holding = False
        self._timer: asyncio.Task[None] | None = None
        self._unloading = False

    # ---- state ---------------------------------------------------------------------------

    @property
    def resident_owner(self) -> str | None:
        """Whose model is in memory (None: nothing, as far as the slot knows)."""
        return self._owner

    @property
    def resident_owners(self) -> list[str]:
        """Everyone whose model is in memory: the resident owner, then the small ones beside it."""
        return ([self._owner] if self._owner is not None else []) + sorted(self._beside)

    @property
    def holding(self) -> bool:
        return self._holding

    # ---- taking the slot -----------------------------------------------------------------

    @asynccontextmanager
    async def hold(self, owner: str, beside_bytes: int | None = None) -> AsyncIterator[Held]:
        """Take the slot. `beside_bytes` says this holder is small and may run beside the resident
        model (what it needs, in bytes); `can_share` decides."""
        if owner not in self._unloaders:
            raise KeyError(f"unknown slot owner {owner!r}")
        self._cancel_timer()
        if beside_bytes is not None and await self._shares(owner, beside_bytes):
            async with self._beside_lock(owner):
                self._cancel_timer()
                if self._owner is not None and self._owner != owner:
                    self._beside.add(owner)
                    try:
                        yield Held(shared=True)
                    finally:
                        self._arm_timer()
                    return
            # the resident model went away while this waited: take the slot in the ordinary way
        async with self._lock:
            self._cancel_timer()
            held = Held()
            if self._owner != owner:  # a new resident model: nothing stays beside the old one
                if self._owner is not None:
                    held.displaced = self._owner
                    await self._unload(self._owner)
                for other in sorted(self._beside - {owner}):
                    await self._unload(other)
            self._beside.discard(owner)
            self._owner = owner  # from here the owner's model may be in memory
            self._holding = True
            try:
                yield held
            finally:
                self._holding = False
                self._arm_timer()

    def lock_for(self, owner: str) -> "OwnerLock":
        """An object with the `hold()` the media worker's job processor expects."""
        return OwnerLock(self, owner)

    async def unload_now(self) -> bool:
        """Unload every resident model now, waiting for a running job to finish first. Returns
        whether anything was unloaded."""
        self._cancel_timer()
        async with self._lock:
            owners = self.resident_owners
            for owner in owners:
                await self._unload(owner)
            return bool(owners)

    # ---- internals -----------------------------------------------------------------------

    async def _shares(self, owner: str, need: int) -> bool:
        resident = self._owner
        if self._can_share is None or resident is None or resident == owner:
            return False
        try:
            return bool(await self._can_share(owner, need, resident))
        except Exception:
            log.warning("could not tell whether %s fits beside %s", owner, resident, exc_info=True)
            return False

    def _beside_lock(self, owner: str) -> asyncio.Lock:
        return self._beside_locks.setdefault(owner, asyncio.Lock())

    async def _unload(self, owner: str) -> None:
        """Called with the lock held. A small owner that is running finishes first."""
        self._unloading = True
        try:
            if owner in self._beside:
                async with self._beside_lock(owner):
                    await self._unloaders[owner]()
            else:
                await self._unloaders[owner]()
        except Exception:
            log.warning("could not unload the %s model", owner, exc_info=True)
        finally:
            self._unloading = False
            # whatever happened, do not count on it being resident
            if self._owner == owner:
                self._owner = None
            self._beside.discard(owner)

    def _arm_timer(self) -> None:
        if self._idle is None or not self.resident_owners:
            return
        self._cancel_timer()
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
            if not self._holding:
                for owner in self.resident_owners:
                    await self._unload(owner)


class OwnerLock:
    """`GpuLock` for the media worker's `JobProcessor`: its `hold()` takes the slot as one owner."""

    def __init__(self, slot: SlotManager, owner: str):
        self._slot = slot
        self._owner = owner

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[None]:
        async with self._slot.hold(self._owner):
            yield
