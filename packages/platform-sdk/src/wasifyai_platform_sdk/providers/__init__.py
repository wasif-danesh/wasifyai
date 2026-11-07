"""Provider registry (dispatcher pattern): config names a provider, this builds it."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from wasifyai_platform_sdk.capabilities import Capabilities, MediaCapabilities, TextCapabilities
from wasifyai_platform_sdk.config import CapabilityBinding, ProductConfig
from wasifyai_platform_sdk.jobs import InMemoryJobSink, JobSink
from wasifyai_platform_sdk.providers.comfyui import ComfyUIProvider
from wasifyai_platform_sdk.providers.fake import FakeMediaProvider, FakeTextProvider
from wasifyai_platform_sdk.providers.litellm import LiteLLMTextProvider
from wasifyai_platform_sdk.storage import ScopedStorage
from wasifyai_platform_sdk.usage import InMemoryUsageRecorder, UsageRecorder


@dataclass
class ProviderDeps:
    products_dir: Path
    usage: UsageRecorder = field(default_factory=InMemoryUsageRecorder)
    job_sink: JobSink = field(default_factory=InMemoryJobSink)
    litellm_base_url: str = "http://localhost:4000"
    litellm_api_key: str = ""
    storage: ScopedStorage | None = None
    db: AsyncEngine | None = None
    embedding_dims: int = 768
    # The desktop profile has no gateway: it supplies the text provider (its chosen local model)
    # and every `litellm` text binding of a product uses it.
    text_provider: Any | None = None


# (provider, family) -> factory(deps, config) -> provider instance
Factory = Callable[[ProviderDeps, ProductConfig], Any]
_FACTORIES: dict[tuple[str, str], Factory] = {}


def register_provider(provider: str, family: str, factory: Factory) -> None:
    _FACTORIES[(provider, family)] = factory


register_provider(
    "litellm",
    "text",
    lambda d, c: (
        d.text_provider or LiteLLMTextProvider(d.litellm_base_url, d.litellm_api_key, d.usage)
    ),
)
register_provider("fake", "text", lambda d, c: FakeTextProvider(d.usage, d.embedding_dims))
for _family in ("image", "video"):
    register_provider(
        "comfyui",
        _family,
        lambda d, c: ComfyUIProvider(d.products_dir / c.id / "workflows", d.job_sink),
    )
    register_provider("fake", _family, lambda d, c: FakeMediaProvider(d.job_sink))


def build_capabilities(config: ProductConfig, deps: ProviderDeps) -> Capabilities:
    """Instantiate the providers a product's config binds, and expose them as `caps`."""
    cache: dict[tuple[str, str], Any] = {}
    grouped: dict[str, dict[str, tuple[CapabilityBinding, Any]]] = {
        "text": {},
        "image": {},
        "video": {},
    }

    def provider(name: str, binding: CapabilityBinding) -> Any:
        family = name.partition(".")[0]
        key = (binding.provider, family)
        if key not in _FACTORIES:
            raise ValueError(f"{name}: provider {binding.provider!r} does not support {family!r}")
        if key not in cache:
            cache[key] = _FACTORIES[key](deps, config)
        return cache[key]

    for name, binding in config.capabilities.items():
        family, _, action = name.partition(".")
        grouped[family][action] = (binding, provider(name, binding))
    # each model's own bindings (ADR-0097); the first model answers a request that names none
    per_model: dict[str, dict[str, dict[str, tuple[CapabilityBinding, Any]]]] = {
        "image": {}, "video": {},
    }  # fmt: skip
    for m in config.models:
        for name, binding in m.capabilities.items():
            family, _, action = name.partition(".")
            per_model[family].setdefault(m.id, {})[action] = (binding, provider(name, binding))
    settings = {m.id: dict(m.settings) for m in config.models}
    for family in ("image", "video"):
        first = next(iter(per_model[family].values()), None)
        if first is not None and not grouped[family]:
            grouped[family] = first
    return Capabilities(
        text=TextCapabilities(grouped["text"], config.id),
        image=MediaCapabilities("image", grouped["image"], config.id, per_model["image"], settings),
        video=MediaCapabilities("video", grouped["video"], config.id, per_model["video"], settings),
        storage=deps.storage,
        config=config,
        db=deps.db,
        usage=deps.usage,
    )
