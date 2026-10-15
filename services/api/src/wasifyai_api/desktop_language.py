"""The language model the desktop app talks to (stage D, step D2).

    LanguageService     which model is chosen, and a `session()` that makes it ready to answer:
                        a file runs in the app's own llama-server (holding the `chat` slot, so the
                        image model is unloaded first); a model of a running Ollama or LM Studio is
                        used where it is
    LocalTextProvider   the text provider the product graphs get on the desktop in place of the
                        gateway: the same OpenAI-compatible calls, to whichever model is chosen

Nothing is chosen for the person and nothing is downloaded here. A model can be chosen only if the
engine can run it and the computer can hold it (desktop_fit); an external server is only one that
the engine itself found on a loopback address (desktop_discovery).
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from wasifyai_platform_sdk import ChatChunk, RunError
from wasifyai_platform_sdk.config import CapabilityBinding
from wasifyai_platform_sdk.context import require_context
from wasifyai_platform_sdk.parts import Prompt, counts, to_openai_content
from wasifyai_platform_sdk.providers.litellm import stream_chat
from wasifyai_platform_sdk.usage import (
    LLM_INPUT_TOKENS,
    LLM_OUTPUT_TOKENS,
    UsageEvent,
    UsageRecorder,
    record_safely,
)

from wasifyai_api.desktop_discovery import gguf_has_chat_template
from wasifyai_api.desktop_fit import Fit, Machine, assess_fit, need_of_language
from wasifyai_api.llama_server import LlamaError, LlamaServer
from wasifyai_api.safeguards import SettingsStore

log = logging.getLogger(__name__)

KEY = "desktop.language"
CONTEXTS = (2048, 4096, 8192, 16384, 32768)
DEFAULT_CONTEXT = 8192
NONE_CHOSEN = "No language model is chosen yet. Choose one in Models, under Found on this computer."


@dataclass(frozen=True)
class Selection:
    kind: str  # "file" (run by the app's own engine) or "server" (a model of a running tool)
    name: str  # for the person
    context: int
    path: str | None = None  # kind == "file"
    note: str = ""  # something the person should know about this model, if anything
    tool: str | None = None  # kind == "server"
    url: str | None = None
    model: str | None = None

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Route:
    base_url: str  # an OpenAI-compatible base, ending in /v1
    model: str  # the model name to send ("" for the app's own server: it runs one model)
    external: bool


def language_machine(base: Machine, backend: str | None) -> Machine:
    """The computer as the language engine sees it. The app's own engine runs on the Apple GPU
    only where its build says `metal`; anywhere else it is a processor build, even next to a
    graphics card, so the card's memory does not count."""
    if backend == "metal":
        return replace(base, device="unified") if base.device == "unified" else base
    if backend == "cpu":
        return replace(base, device="cpu", gpu_total_bytes=None, gpu_free_bytes=None)
    return base


class LanguageService:
    def __init__(
        self,
        store: SettingsStore,
        llama: LlamaServer,
        models: Any = None,
        discovery: Any = None,
    ):
        self._store = store
        self.llama = llama
        self.models = models  # ModelsService: the machine and what the slot holds
        self.discovery = discovery  # DiscoveryService: found models and running servers
        self.slot: Any = None  # the SlotManager, set when the worker is built
        self.selected: Selection | None = None

    # ---- the choice ----------------------------------------------------------------------

    async def load(self) -> None:
        saved = await self._store.get(KEY)
        if not isinstance(saved, dict):
            return
        try:
            self.selected = Selection(**saved)
        except TypeError:
            self.selected = None

    async def _save(self) -> None:
        value = self.selected.public() if self.selected else {}
        await self._store.put(KEY, value, "window")

    async def clear(self) -> None:
        self.selected = None
        await self._save()
        await self.llama.stop()

    async def select_file(self, path: Path, name: str, context: int) -> None:
        has_template = await asyncio.to_thread(gguf_has_chat_template, path)
        note = (
            "This file has no chat template of its own (Ollama keeps templates outside the "
            "file), so answers may look odd. A file from Hugging Face or LM Studio, or the same "
            "model through a running Ollama, works better."
            if has_template is False
            else ""
        )
        self.selected = Selection("file", name, _context(context), path=str(path), note=note)
        await self._save()
        await self.llama.stop()  # the next request starts the new model

    async def select_server(self, tool: str, url: str, model: str, context: int) -> None:
        self.selected = Selection(
            "server", f"{model} ({tool})", _context(context), tool=tool, url=url, model=model
        )
        await self._save()
        await self.llama.stop()

    # ---- the computer --------------------------------------------------------------------

    async def machine(self) -> Machine | None:
        if self.models is None:
            return None
        base = await self.models.machine()
        install = self.llama.install
        backend = install.backend if install else None
        return language_machine(base, backend)

    def fit_for(self, size: int, found: Any, machine: Machine, context: int) -> Fit:
        """Will this file fit, at the context the person would use?"""
        need = need_of_language(
            size, found.layers, found.kv_heads, found.head_dim, found.context, chosen=context
        )
        return assess_fit(need, machine)

    # ---- answering -----------------------------------------------------------------------

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Route]:
        """Make the chosen model ready and say where to ask it. For the app's own engine this holds
        the `chat` slot for as long as the caller keeps it: an image model is unloaded first, and an
        image job started meanwhile waits."""
        sel = self.selected
        if sel is None:
            raise RunError("no_language_model", NONE_CHOSEN)
        if sel.kind == "server":
            assert sel.url and sel.model
            yield Route(sel.url.rstrip("/") + "/v1", sel.model, external=True)
            return
        assert sel.path
        async with AsyncExitStack() as stack:
            if self.slot is not None:
                await stack.enter_async_context(self.slot.hold("chat"))
            try:
                url = await self.llama.ensure_running(Path(sel.path), context=sel.context)
            except LlamaError as exc:
                raise RunError(f"language_{exc.code}", exc.message) from None
            yield Route(url + "/v1", "", external=False)


def _context(value: int) -> int:
    return value if value in CONTEXTS else DEFAULT_CONTEXT


class LocalTextProvider:
    """`TextProvider` for the desktop: the chosen model, through the OpenAI chat API."""

    def __init__(self, language: LanguageService, usage: UsageRecorder):
        self._language = language
        self._usage = usage

    async def stream(
        self,
        capability: str,
        binding: CapabilityBinding,
        system: str,
        prompt: Prompt,
        schema: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        ctx = require_context()
        media = {k: v for k, v in counts(prompt).items() if v}
        if media:
            raise RunError(
                "language_no_pictures",
                "The chosen language model reads text only. Pictures need a model that sees them.",
            )
        in_tokens = out_tokens = 0
        label = ""
        try:
            async with self._language.session() as route:
                label = self._language.selected.name if self._language.selected else ""
                client = AsyncOpenAI(base_url=route.base_url, api_key="none", max_retries=0)
                messages: Any = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": to_openai_content(prompt)},
                ]
                extra: dict[str, Any] = {}
                if schema is not None:
                    extra["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {"name": "reply", "schema": schema, "strict": True},
                    }
                stream = await client.chat.completions.create(
                    model=route.model,
                    stream=True,
                    stream_options={"include_usage": True},
                    messages=messages,
                    **extra,
                )
                async for chunk in stream:
                    if chunk.usage:
                        in_tokens = chunk.usage.prompt_tokens
                        out_tokens = chunk.usage.completion_tokens
                    if chunk.choices and (text := chunk.choices[0].delta.content):
                        yield text
        finally:
            meta: dict[str, Any] = {"capability": capability, "alias": label or binding.model}
            if in_tokens:
                await record_safely(
                    self._usage,
                    UsageEvent.for_context(ctx, LLM_INPUT_TOKENS, in_tokens, "tokens", **meta),
                )
            if out_tokens:
                await record_safely(
                    self._usage,
                    UsageEvent.for_context(ctx, LLM_OUTPUT_TOKENS, out_tokens, "tokens", **meta),
                )

    async def chat(
        self,
        capability: str,
        binding: CapabilityBinding,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ChatChunk]:
        """A conversation turn on the chosen model, with the tools a graph offers it."""
        async with self._language.session() as route:
            label = self._language.selected.name if self._language.selected else ""
            client = AsyncOpenAI(base_url=route.base_url, api_key="none", max_retries=0)
            async for chunk in stream_chat(
                client, route.model, messages, tools, self._usage, capability, label
            ):
                yield chunk

    async def embed(
        self, capability: str, binding: CapabilityBinding, texts: list[str]
    ) -> list[list[float]]:
        raise RunError(
            "language_no_embeddings",
            "Embeddings from a local model arrive with the documents stage.",
        )
