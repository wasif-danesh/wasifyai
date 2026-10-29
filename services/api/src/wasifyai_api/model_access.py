"""Model access: which provider and model serve each LiteLLM alias (ADR-0025).

The aliases and their defaults are in model_defaults.yaml. LiteLLM stores the live bindings (and
encrypts the API keys); this module seeds the defaults, shows the current state without secrets,
changes a binding, and tests one."""

import ipaddress
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel

from wasifyai_api.litellm_admin import BackendError, CallResult, ModelBackend, ModelEntry

log = logging.getLogger(__name__)

DEFAULTS_FILE = Path(__file__).with_name("model_defaults.yaml")
BEHAVIOUR_EXCLUDED = ("model", "api_base", "api_key")  # connection fields an admin replaces
STALE_CANDIDATE_MINUTES = 10
NO_KEY = "none"  # what "no API key" is stored as; also what Ollama and local servers get


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    prefix: str  # LiteLLM's provider prefix for chat models
    needs_key: bool
    needs_base: bool
    hint: str  # an example model name, shown as a placeholder only
    embed_prefix: str | None = None  # when embeddings use another prefix


PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in (
        Provider("ollama", "Ollama (local)", "ollama_chat/", False, True, "gemma4:e4b", "ollama/"),
        Provider("gemini", "Google Gemini", "gemini/", True, False, "gemini-2.5-flash"),
        Provider("groq", "Groq", "groq/", True, False, "llama-3.3-70b-versatile"),
        Provider("cerebras", "Cerebras", "cerebras/", True, False, "llama-3.3-70b"),
        Provider("openrouter", "OpenRouter", "openrouter/", True, False, "google/gemma-3-27b-it"),
        Provider(
            "openai_compatible", "OpenAI-compatible server", "openai/", False, True, "model-name"
        ),
        Provider("litellm", "Other (LiteLLM model string)", "", True, False, "provider/model-name"),
    )
}

MODEL_NAME = re.compile(r"^[A-Za-z0-9._:/@+\-]{1,200}$")


class ModelAccessError(Exception):
    """A request that cannot be accepted; the message is meant for the admin."""


class Binding(BaseModel):
    provider: str
    model: str
    api_base: str | None = None
    api_key: str | None = None  # write-only: never stored by us, never returned


class ModelView(BaseModel):
    alias: str
    purpose: str
    kind: str
    source: str  # "default", "custom" or "missing" (not seeded yet)
    provider: str | None
    model: str | None
    api_base: str | None
    key_set: bool
    updated_by: str | None
    updated_at: datetime | None


class ProviderView(BaseModel):
    id: str
    label: str
    needs_key: bool
    needs_base: bool
    model_hint: str


class TestOutcome(BaseModel):
    ok: bool
    latency_ms: int
    sample: str = ""
    error: str = ""


def load_defaults(substitutions: dict[str, str], path: Path = DEFAULTS_FILE) -> dict[str, dict]:
    raw = yaml.safe_load(path.read_text())["aliases"]
    out: dict[str, dict] = {}
    for alias, spec in raw.items():
        params = {
            k: (_fill(v, substitutions) if isinstance(v, str) else v)
            for k, v in spec["litellm_params"].items()
        }
        out[alias] = {**spec, "litellm_params": params}
    return out


def _fill(value: str, substitutions: dict[str, str]) -> str:
    for key, replacement in substitutions.items():
        value = value.replace("{" + key + "}", replacement)
    return value


def describe(params: dict[str, Any]) -> tuple[str, str]:
    """(provider id, model name) for a LiteLLM model string."""
    model = str(params.get("model", ""))
    if model.startswith("openai/") and params.get("api_base"):
        return "openai_compatible", model.removeprefix("openai/")
    for p in PROVIDERS.values():
        for prefix in (p.prefix, p.embed_prefix):
            if prefix and model.startswith(prefix):
                return p.id, model.removeprefix(prefix)
    return "litellm", model


def validate_binding(b: Binding) -> Binding:
    provider = PROVIDERS.get(b.provider)
    if provider is None:
        raise ModelAccessError(f"unknown provider {b.provider!r}")
    model = b.model.strip()
    if not MODEL_NAME.match(model):
        raise ModelAccessError("the model name has characters that are not allowed")
    api_base = (b.api_base or "").strip() or None
    if provider.needs_base and not api_base:
        raise ModelAccessError(f"{provider.label} needs a server address")
    if api_base:
        _check_url(api_base)
    key = (b.api_key or "").strip() or None
    if key and (len(key) > 512 or re.search(r"\s", key)):
        raise ModelAccessError(
            "the API key must be one token without spaces (up to 512 characters)"
        )
    if provider.needs_key and not key:
        raise ModelAccessError(f"{provider.label} needs an API key")
    return Binding(provider=b.provider, model=model, api_base=api_base, api_key=key)


def _check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or len(url) > 300:
        raise ModelAccessError("the server address must be an http(s) URL")
    if "@" in parts.netloc:
        raise ModelAccessError("do not put credentials in the server address")
    try:
        ip = ipaddress.ip_address(parts.hostname)
    except ValueError:
        return
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        raise ModelAccessError("that server address is not allowed")


def build_params(spec: dict, binding: Binding, kind: str) -> dict[str, Any]:
    provider = PROVIDERS[binding.provider]
    prefix = (
        provider.embed_prefix if kind == "embedding" and provider.embed_prefix else provider.prefix
    )
    params = {k: v for k, v in spec["litellm_params"].items() if k not in BEHAVIOUR_EXCLUDED}
    params["model"] = f"{prefix}{binding.model}"
    if binding.api_base:
        params["api_base"] = binding.api_base
    # Always written: LiteLLM merges an update into what is stored, so leaving the key out would
    # keep the previous one and send it to whatever server the binding now points at.
    params["api_key"] = binding.api_key or NO_KEY
    return params


def reset_params(spec: dict) -> dict[str, Any]:
    """The default parameters, with the key explicitly cleared (see build_params)."""
    return {**spec["litellm_params"], "api_key": spec["litellm_params"].get("api_key") or NO_KEY}


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ModelAccess:
    def __init__(
        self,
        backend: ModelBackend,
        defaults: dict[str, dict],
        now: Callable[[], str] = _now,
    ):
        self._backend = backend
        self._defaults = defaults
        self._now = now

    @staticmethod
    def model_id(alias: str) -> str:
        return f"alias:{alias}"

    def aliases(self) -> list[str]:
        return list(self._defaults)

    @staticmethod
    def providers() -> list[ProviderView]:
        return [
            ProviderView(
                id=p.id, label=p.label, needs_key=p.needs_key, needs_base=p.needs_base,
                model_hint=p.hint,
            )
            for p in PROVIDERS.values()
        ]  # fmt: skip

    def _info(
        self, alias: str, source: str, params: dict, key_set: bool, actor: str | None
    ) -> dict:
        spec = self._defaults[alias]
        provider, model = describe(params)
        return {
            "id": self.model_id(alias),
            "wasifyai": {
                "source": source, "provider": provider, "model": model,
                "api_base": params.get("api_base"), "key_set": key_set,
                "purpose": spec["purpose"], "kind": spec["kind"],
                "updated_by": actor, "updated_at": self._now(),
            },
        }  # fmt: skip

    async def seed(self) -> int:
        """Create any default alias LiteLLM does not have yet; drop stale canary leftovers."""
        entries = await self._backend.list()
        have = {e.id for e in entries}
        for e in entries:
            if e.id.startswith("candidate:") and self._is_stale(e):
                await self._backend.delete(e.id)
        created = 0
        for alias, spec in self._defaults.items():
            if self.model_id(alias) in have:
                continue
            info = self._info(alias, "default", spec["litellm_params"], False, None)
            await self._backend.add(alias, spec["litellm_params"], info)
            created += 1
        if created:
            log.info("seeded %d default model alias(es)", created)
        return created

    def _is_stale(self, e: ModelEntry) -> bool:
        try:
            made = datetime.fromisoformat(e.wasifyai["created_at"])
        except (KeyError, ValueError):
            return True
        return (datetime.now(UTC) - made).total_seconds() > STALE_CANDIDATE_MINUTES * 60

    async def list(self) -> list[ModelView]:
        by_id = {e.id: e for e in await self._backend.list()}
        views = []
        for alias, spec in self._defaults.items():
            e = by_id.get(self.model_id(alias))
            meta = e.wasifyai if e else {}
            views.append(
                ModelView(
                    alias=alias, purpose=spec["purpose"], kind=spec["kind"],
                    source=meta.get("source", "missing"),
                    provider=meta.get("provider"), model=meta.get("model"),
                    api_base=meta.get("api_base"),
                    key_set=bool(meta.get("key_set")), updated_by=meta.get("updated_by"),
                    updated_at=meta.get("updated_at"),
                )
            )  # fmt: skip
        return views

    def _spec(self, alias: str) -> dict:
        if alias not in self._defaults:
            raise ModelAccessError(f"unknown alias {alias!r}")
        return self._defaults[alias]

    async def set(self, alias: str, binding: Binding, actor: str) -> ModelView:
        """Point `alias` at a new provider and model."""
        spec = self._spec(alias)
        binding = validate_binding(binding)
        params = build_params(spec, binding, spec["kind"])
        info = self._info(alias, "custom", params, params["api_key"] != NO_KEY, actor)
        await self._backend.update(self.model_id(alias), params, info)
        return next(v for v in await self.list() if v.alias == alias)

    async def reset(self, alias: str, actor: str) -> ModelView:
        spec = self._spec(alias)
        info = self._info(alias, "default", spec["litellm_params"], False, actor)
        await self._backend.update(self.model_id(alias), reset_params(spec), info)
        return next(v for v in await self.list() if v.alias == alias)

    async def _add_candidate(self, alias: str, params: dict, spec: dict) -> str:
        cid = f"candidate:{alias}:{uuid.uuid4().hex[:8]}"
        info = {"id": cid, "wasifyai": {"source": "candidate", "created_at": self._now()}}
        await self._backend.add(cid, params, info)
        return cid

    async def test(self, alias: str, binding: Binding | None = None) -> TestOutcome:
        """Send one tiny request through `alias`, or through a binding that is not saved yet."""
        spec = self._spec(alias)
        target, candidate = alias, None
        if binding is not None:
            binding = validate_binding(binding)
            candidate = await self._add_candidate(
                alias, build_params(spec, binding, spec["kind"]), spec
            )
            target = candidate
        try:
            result: CallResult = await self._backend.call(target, spec["kind"])
        except BackendError as exc:
            return TestOutcome(ok=False, latency_ms=0, error=_redact(str(exc)))
        finally:
            if candidate:
                await self._backend.delete(candidate)
        return TestOutcome(
            ok=result.ok,
            latency_ms=result.latency_ms,
            sample=result.sample,
            error=_redact(result.error),
        )


_TOKEN = re.compile(r"[A-Za-z0-9_\-]{24,}")


def _redact(text: str) -> str:
    """Long token-like strings never leave the server, in case a provider echoes a key."""
    return _TOKEN.sub("…", text)[:400]
