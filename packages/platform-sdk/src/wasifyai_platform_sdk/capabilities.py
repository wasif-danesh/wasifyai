"""Capability interfaces. Graphs ask for capabilities, never models (ADR-0010, rule 4).

async for delta in caps.text.stream("lyrics", system, prompt): ...
handle = await caps.music.generate(lyrics=..., style=..., duration_s=60)
key = await caps.storage.put("songs/42/audio.mp3", data)
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncEngine

from wasifyai_platform_sdk.config import CapabilityBinding, ProductConfig
from wasifyai_platform_sdk.context import require_context
from wasifyai_platform_sdk.jobs import JobHandle
from wasifyai_platform_sdk.parts import Prompt, UnsupportedInput, modalities
from wasifyai_platform_sdk.storage import ScopedStorage
from wasifyai_platform_sdk.usage import UsageEvent, UsageRecorder, record_safely

log = logging.getLogger(__name__)


class CapabilityNotConfigured(LookupError):
    pass


class TextProvider(Protocol):
    def stream(
        self,
        capability: str,
        binding: CapabilityBinding,
        system: str,
        prompt: Prompt,
        schema: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]: ...

    async def embed(
        self, capability: str, binding: CapabilityBinding, texts: list[str]
    ) -> list[list[float]]: ...


class MediaProvider(Protocol):
    async def generate(
        self, capability: str, binding: CapabilityBinding, inputs: dict[str, Any]
    ) -> JobHandle: ...


class RagStore(Protocol):
    async def ingest(
        self, collection: str, document_id: str, content: str, metadata: dict[str, Any] | None = ...
    ) -> int: ...

    async def search(self, collection: str, query: str, k: int = ...) -> list[Any]: ...


class TextCapabilities:
    def __init__(self, bound: dict[str, tuple[CapabilityBinding, TextProvider]], product: str = ""):
        self._bound = bound  # "chat" -> (binding for "text.chat", provider)
        self._product = product

    def _get(self, name: str) -> tuple[CapabilityBinding, TextProvider]:
        try:
            return self._bound[name]
        except KeyError:
            raise CapabilityNotConfigured(
                f"capability 'text.{name}' is not configured for product {self._product!r}"
            ) from None

    def stream(
        self, name: str, system: str, prompt: Prompt, schema: dict[str, Any] | None = None
    ) -> AsyncIterator[str]:
        """`prompt` is a string or a list of strings, `Image` and `Audio` parts. With `schema`
        (a JSON Schema) the model is constrained to reply with matching JSON."""
        binding, provider = self._get(name)
        extra = modalities(prompt) - set(binding.inputs)
        if extra:
            raise UnsupportedInput(
                f"capability 'text.{name}' accepts {sorted(binding.inputs)} but the prompt "
                f"contains {sorted(extra)}; bind a model that supports it (inputs: in product.yaml)"
            )
        return provider.stream(f"text.{name}", binding, system, prompt, schema)

    async def complete(
        self, name: str, system: str, prompt: Prompt, schema: dict[str, Any] | None = None
    ) -> str:
        return "".join([d async for d in self.stream(name, system, prompt, schema)])

    async def embed(self, name: str, texts: list[str]) -> list[list[float]]:
        binding, provider = self._get(name)
        return await provider.embed(f"text.{name}", binding, texts)


class MediaCapabilities:
    """`caps.image` / `caps.music` / `caps.video`: generate() enqueues a job, returns a handle."""

    def __init__(
        self,
        family: str,
        bound: dict[str, tuple[CapabilityBinding, MediaProvider]],
        product: str = "",
    ):
        self._family = family
        self._bound = bound
        self._product = product

    async def generate(self, **inputs: Any) -> JobHandle:
        return await self._run("generate", inputs)

    async def edit(self, **inputs: Any) -> JobHandle:
        """Change a picture the user uploaded: pass its storage key as `image_key`."""
        return await self._run("edit", inputs)

    async def synthesize(self, **inputs: Any) -> JobHandle:
        """Say a text aloud (ADR-0042): `text`, `language`, `engine`, `voice` and `model`."""
        return await self._run("synthesize", inputs)

    async def transcribe(self, **inputs: Any) -> JobHandle:
        """Turn an uploaded recording into text (ADR-0043): `audio_key`, `language`, `model`."""
        return await self._run("transcribe", inputs)

    async def lipsync(self, **inputs: Any) -> JobHandle:
        """Make a character picture speak or sing (ADR-0044): `image_key` and `audio_key`."""
        return await self._run("lipsync", inputs)

    async def animate(self, **inputs: Any) -> JobHandle:
        """Make a clip from a picture the user uploaded: pass its storage key as `image_key`."""
        return await self._run("animate", inputs)

    async def _run(self, verb: str, inputs: dict[str, Any]) -> JobHandle:
        name = f"{self._family}.{verb}"
        try:
            binding, provider = self._bound[verb]
        except KeyError:
            raise CapabilityNotConfigured(
                f"capability {name!r} is not configured for product {self._product!r}"
            ) from None
        return await provider.generate(name, binding, inputs)


@dataclass
class Capabilities:
    text: TextCapabilities
    image: MediaCapabilities
    music: MediaCapabilities
    video: MediaCapabilities
    speech: MediaCapabilities
    storage: ScopedStorage | None = None
    rag: RagStore | None = None
    config: ProductConfig | None = None  # this product's validated config (quotas, settings)
    db: AsyncEngine | None = None  # the shared database, for product tables and usage queries
    usage: UsageRecorder | None = None
    indexer: Any = None  # CreationIndexer: makes a creation searchable (ADR-0041); None in tests
    # Says whether the safeguards are on (ADR-0047). None (tests, tools) means on.
    safeguards: Callable[[], Awaitable[bool]] | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    async def safeguards_on(self) -> bool:
        """Whether the safeguards (content moderation and per-user quotas) apply right now. Graphs
        call this when checking, never once at start-up: an admin can flip it at any time."""
        return True if self.safeguards is None else await self.safeguards()

    async def index_creation(self, kind: str, item_id: str, text: str) -> None:
        """Make a saved creation searchable (ADR-0041): call this when a creation is saved. It never
        fails the run: if the embedder is down the item is picked up by the background indexer."""
        if self.indexer is None or not text.strip():
            return
        try:
            await self.indexer.index(kind, item_id, text)
        except Exception:
            log.warning("could not index %s %s; the background indexer will retry", kind, item_id)

    async def record_usage(self, kind: str, quantity: float, unit: str, **meta: Any) -> None:
        """Write a usage event for the current run (tenant, product, user, run from context)."""
        if self.usage is not None:
            await record_safely(
                self.usage, UsageEvent.for_context(require_context(), kind, quantity, unit, **meta)
            )
