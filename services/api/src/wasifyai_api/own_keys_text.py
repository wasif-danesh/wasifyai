"""Chat and every text product on the person's own key (ADR-0095, stage K2; ADR-0100, stage CP2).

`KeyedTextProvider` is the text provider the product graphs get on the desktop. While Chat and
writing is set to a cloud model, a chat, a lyric, an enhanced prompt, a notebook answer, the
assistant, a picture description or a training judge goes to that vendor with that key: Anthropic
through its own Messages API (`anthropic_text.py`; Claude Haiku 5.5 is the default), every other
vendor through the same OpenAI-compatible calls the local model gets. Otherwise everything goes to
the model chosen on this computer (`LocalTextProvider`), as before. Embeddings always stay on this
computer (ADR-0100, decision 4).

A provider's refusal is said in words (`said_of`); the app adds no refusal of its own (ADR-0094)."""

from collections.abc import AsyncIterator
from typing import Any

from openai import APIConnectionError, APIStatusError, AsyncOpenAI
from wasifyai_platform_sdk import ChatChunk, RunError
from wasifyai_platform_sdk.config import CapabilityBinding
from wasifyai_platform_sdk.context import require_context
from wasifyai_platform_sdk.parts import Prompt, to_openai_content
from wasifyai_platform_sdk.providers.litellm import stream_chat
from wasifyai_platform_sdk.usage import (
    LLM_INPUT_TOKENS,
    LLM_OUTPUT_TOKENS,
    UsageEvent,
    UsageRecorder,
    record_safely,
)

from wasifyai_api.anthropic_text import AnthropicText
from wasifyai_api.own_keys import KeyRoute, OwnKeysService, said_of, text_client

PRODUCT = "chat"  # the one setting every text product follows


class KeyedTextProvider:
    def __init__(self, local: Any, keys: OwnKeysService, usage: UsageRecorder):
        self._local = local  # LocalTextProvider: the model chosen on this computer
        self._keys = keys
        self._usage = usage

    async def _route(self) -> KeyRoute | None:
        return await self._keys.route(PRODUCT)

    def _anthropic(self, route: KeyRoute) -> AnthropicText | None:
        if route.provider.id != "anthropic":
            return None
        return AnthropicText(route.key, route.model, self._usage)

    @staticmethod
    def _client(route: KeyRoute) -> AsyncOpenAI:
        return text_client(
            route.provider, route.base_url, route.key, factory=AsyncOpenAI, max_retries=0
        )

    @staticmethod
    def _refused(route: KeyRoute, e: Exception) -> RunError:
        said = said_of(route.provider, route.model, e) or f"{route.provider.title} did not answer."
        return RunError("provider_refused", said, retryable=True)

    async def stream(
        self,
        capability: str,
        binding: CapabilityBinding,
        system: str,
        prompt: Prompt,
        schema: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        route = await self._route()
        if route is None:
            async for text in self._local.stream(capability, binding, system, prompt, schema):
                yield text
            return
        if (claude := self._anthropic(route)) is not None:
            async for text in claude.stream(capability, system, prompt, schema):
                yield text
            return
        ctx = require_context()
        in_tokens = out_tokens = 0
        client = self._client(route)
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
        try:
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
        except (APIConnectionError, APIStatusError) as e:
            raise self._refused(route, e) from None
        finally:
            await client.close()
            meta = {"capability": capability, "alias": route.model, "provider": route.provider.id}
            for kind, n in ((LLM_INPUT_TOKENS, in_tokens), (LLM_OUTPUT_TOKENS, out_tokens)):
                if n:
                    await record_safely(
                        self._usage, UsageEvent.for_context(ctx, kind, n, "tokens", **meta)
                    )

    async def chat(
        self,
        capability: str,
        binding: CapabilityBinding,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        thinking: bool = False,
    ) -> AsyncIterator[ChatChunk]:
        """A conversation turn, with the tools a graph offers. With a key, the provider decides
        whether its model thinks; nothing extra is sent for it."""
        route = await self._route()
        if route is None:
            async for chunk in self._local.chat(capability, binding, messages, tools, thinking):
                yield chunk
            return
        if (claude := self._anthropic(route)) is not None:
            async for chunk in claude.chat(capability, messages, tools, thinking):
                yield chunk
            return
        client = self._client(route)
        try:
            async for chunk in stream_chat(
                client, route.model, messages, tools, self._usage, capability, route.model
            ):
                yield chunk
        except (APIConnectionError, APIStatusError) as e:
            raise self._refused(route, e) from None
        finally:
            await client.close()

    async def embed(
        self, capability: str, binding: CapabilityBinding, texts: list[str]
    ) -> list[list[float]]:
        return await self._local.embed(capability, binding, texts)
