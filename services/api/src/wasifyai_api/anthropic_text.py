"""Text on Anthropic's own API, for a person's Anthropic key on the desktop (ADR-0100, stage CP2).

Claude Haiku 5.5 is the default text model. Its API is not the OpenAI-compatible one the other
vendors share, and Haiku 5.5 differs from older models in ways the code must follow:

- no `temperature`, `top_p` or `top_k`, and no assistant prefill (each is a 400);
- adaptive thinking is on by default; how much it thinks is `output_config.effort`, chosen per job
  here (`effort_for`): low for prompts, lyrics and picture descriptions, medium for chat and
  Notebook, high for the assistant, Creative Studio's plan and Motion graphics;
- a reply is read by block type (thinking blocks can come first), and the thinking blocks of a turn
  that called tools go back unchanged with the tool results. The graphs keep OpenAI-shaped
  messages, so the blocks are kept here (`ThinkingReplay`, bounded, keyed by the tool calls' ids)
  and put back when the same turn comes round again. When they are gone (the engine restarted
  while a tool waited for an approval), that one request runs with thinking off, which Haiku 5.5
  allows at effort high or below. Anthropic checks that a replayed block belongs to the
  conversation as sent (preserved thinking); if it answers 400 about thinking, before anything has
  run, the request goes once more with thinking off and no replayed blocks, and a warning is logged;
- the model can decline (`stop_reason: "refusal"`); that is said in words, and the app adds no
  refusal of its own (ADR-0094).

The person may choose any model their key lists (owner, 2026-11-13), and older and newer models take
different requests (`Shape`, read once per model from Anthropic's Models API): Haiku 4.5 and the 4.5
models have no adaptive thinking (they are asked for none), Haiku 4.5 has no effort, and Fable, Opus
5.5 and Sonnet 5.5 cannot turn thinking off (a turn whose thinking is gone runs with it on).

The request also asks for prompt caching (`cache_control` at the top level), so a long system
prompt or a notebook's sources cost a tenth on the next turn."""

import base64
import json
import logging
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from anthropic import APIConnectionError, APIStatusError, AsyncAnthropic, transform_schema
from wasifyai_platform_sdk import ChatChunk, RunError, ToolCall
from wasifyai_platform_sdk.context import require_context
from wasifyai_platform_sdk.parts import Audio, Image, Prompt, as_parts
from wasifyai_platform_sdk.usage import (
    LLM_INPUT_TOKENS,
    LLM_OUTPUT_TOKENS,
    UsageEvent,
    UsageRecorder,
    record_safely,
)

log = logging.getLogger(__name__)

Effort = Literal["low", "medium", "high"]

# the products whose text is planning or tool use: they think the most
HIGH_PRODUCTS = ("wasifyai-assistant", "wasifyai-creative")
HIGH_CAPABILITIES = ("video_builder.draft", "motion.edit")
# short, single-purpose writing: a rewritten prompt, lyrics, a description of a picture
LOW_CAPABILITIES = ("enhance", "lyrics", "describe_image", "vision", "multimodal")
MAX_TOKENS: dict[Effort, int] = {"low": 8_000, "medium": 16_000, "high": 32_000}
LONG_PROMPT_TOKENS = 100_000  # above this Haiku 5.5 costs five times as much


def effort_for(capability: str, product: str) -> Effort:
    """How hard the model thinks for this job (ADR-0100)."""
    name = capability.removeprefix("text.")
    if name in HIGH_CAPABILITIES or product in HIGH_PRODUCTS:
        return "high"
    if name in LOW_CAPABILITIES:
        return "low"
    return "medium"


class ThinkingReplay:
    """The content blocks of the turns that called tools, by their calls' ids: the thinking in
    them must go back unchanged with the results. Bounded: the oldest turns are forgotten."""

    def __init__(self, size: int = 256):
        self._size = size
        self._turns: OrderedDict[tuple[str, ...], list[dict[str, Any]]] = OrderedDict()

    def remember(self, call_ids: list[str], blocks: list[dict[str, Any]]) -> None:
        key = tuple(call_ids)
        self._turns[key] = blocks
        self._turns.move_to_end(key)
        while len(self._turns) > self._size:
            self._turns.popitem(last=False)

    def recall(self, call_ids: list[str]) -> list[dict[str, Any]] | None:
        return self._turns.get(tuple(call_ids))


REPLAY = ThinkingReplay()


@dataclass
class Converted:
    system: str
    messages: list[dict[str, Any]]
    replay_missing: bool  # a turn with tool calls whose thinking blocks are not kept any more


def _image_block(url: str) -> dict[str, Any]:
    if url.startswith("data:"):
        head, _, data = url.partition(",")
        media_type = head.removeprefix("data:").split(";")[0] or "image/png"
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data},
        }
    return {"type": "image", "source": {"type": "url", "url": url}}


def _no_audio() -> RunError:
    return RunError(
        "provider_refused",
        "Claude cannot listen to recordings. Choose another model for this, or one on this "
        "computer.",
    )


def _user_content(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    out: list[dict[str, Any]] = []
    for part in content or []:
        kind = part.get("type")
        if kind == "text":
            if part.get("text"):
                out.append({"type": "text", "text": part["text"]})
        elif kind == "image_url":
            url = (
                part["image_url"]["url"]
                if isinstance(part["image_url"], dict)
                else part["image_url"]
            )
            out.append(_image_block(str(url)))
        elif kind == "input_audio":
            raise _no_audio()
    return out


def _tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return json.dumps(content)


def to_anthropic(
    messages: list[dict[str, Any]], replay: ThinkingReplay | None = REPLAY
) -> Converted:
    """OpenAI-shaped messages (system, user, assistant with tool calls, tool) as Anthropic's: the
    system text apart, tool results as user turns, and turns of one role joined."""
    system: list[str] = []
    out: list[dict[str, Any]] = []
    missing = False

    def add(role: str, blocks: list[dict[str, Any]]) -> None:
        if not blocks:
            return
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": list(blocks)})

    last_person = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    for i, m in enumerate(messages):
        role = m.get("role")
        if role == "system":
            text = _tool_result_text(m.get("content"))
            if text:
                system.append(text)
        elif role == "user":
            add("user", _user_content(m.get("content")))
        elif role == "assistant":
            calls = m.get("tool_calls") or []
            ids = [str(c.get("id")) for c in calls]
            kept = replay.recall(ids) if calls and replay is not None else None
            if kept is not None:
                add("assistant", [dict(b) for b in kept])
                continue
            blocks: list[dict[str, Any]] = []
            text = _tool_result_text(m.get("content") or "")
            if text.strip():
                blocks.append({"type": "text", "text": text})
            for c in calls:
                fn = c.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                blocks.append(
                    {"type": "tool_use", "id": str(c.get("id")), "name": fn.get("name", ""),
                     "input": args if isinstance(args, dict) else {}}
                )  # fmt: skip
            if calls and i > last_person:
                missing = True  # the turn under way needs its thinking; an older one does not
            add("assistant", blocks)
        elif role == "tool":
            add(
                "user",
                [{"type": "tool_result", "tool_use_id": str(m.get("tool_call_id")),
                  "content": _tool_result_text(m.get("content"))}],
            )  # fmt: skip
    if out and out[-1]["role"] == "assistant":
        # Haiku 5.5 takes no prefill: a conversation always ends with the person (or a result)
        out.append({"role": "user", "content": [{"type": "text", "text": "Continue."}]})
    return Converted("\n\n".join(system), out, missing)


def to_anthropic_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out = []
    for t in tools or []:
        fn = t.get("function", t)
        out.append(
            {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return out


def prompt_content(prompt: Prompt) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in as_parts(prompt):
        if isinstance(p, str):
            if p:
                out.append({"type": "text", "text": p})
        elif isinstance(p, Image):
            if p.data is not None:
                data = base64.standard_b64encode(p.data).decode()
                out.append(
                    {"type": "image",
                     "source": {"type": "base64", "media_type": p.media_type, "data": data}}
                )  # fmt: skip
            elif p.url:
                out.append(_image_block(p.url))
        elif isinstance(p, Audio):
            raise _no_audio()
    return out


def said_of(e: Exception, model: str) -> str:
    if isinstance(e, APIConnectionError):
        return "Anthropic could not be reached."
    if isinstance(e, APIStatusError):
        if e.status_code in (401, 403):
            return "Anthropic did not accept the key."
        if e.status_code == 404:
            return f"Anthropic has no model called {model}."
        if e.status_code == 429:
            return "Anthropic says too many requests. Try again soon."
        if e.status_code == 529:
            return "Anthropic is busy. Try again soon."
        if e.status_code == 400 and "credit" in str(e).lower():
            return "Anthropic says the account has no credit left."
        body = e.body if isinstance(e.body, dict) else {}
        error = body.get("error")
        said = error.get("message") if isinstance(error, dict) else None
        if isinstance(said, str) and said.strip():  # its own words say what to fix (CP13)
            return f"Anthropic answered {e.status_code}: {said.strip()[:300]}"
        return f"Anthropic answered {e.status_code}."
    return "Anthropic did not answer."


# models whose thinking cannot be turned off: `disabled` is a 400 (the claude-api notes, 2026-11)
THINKING_STAYS_ON = ("claude-fable", "claude-mythos", "claude-opus-5-5", "claude-sonnet-5-5")


@dataclass(frozen=True)
class Shape:
    """What a model's requests may carry."""

    adaptive: bool = True  # adaptive thinking; without it no thinking is asked for
    effort: bool = True  # `output_config.effort`
    can_turn_off: bool = True  # `thinking: {"type": "disabled"}`


def shape_of(model: str, capabilities: dict[str, Any] | None = None) -> Shape:
    """`model`'s shape from the capabilities Anthropic lists for it, or, when they could not be
    read, from its name (the 4.5 models are the ones before adaptive thinking)."""
    stays_on = model.startswith(THINKING_STAYS_ON)
    if capabilities:
        thinking = (capabilities.get("thinking") or {}).get("types") or {}
        adaptive = bool((thinking.get("adaptive") or {}).get("supported", True))
        effort = bool((capabilities.get("effort") or {}).get("supported", True))
        return Shape(adaptive, effort, not stays_on)
    old = "-4-5" in model
    return Shape(
        not old, not model.startswith(("claude-haiku-4-5", "claude-sonnet-4-5")), not stays_on
    )


SHAPES: dict[str, Shape] = {}  # read once per model, for every key


class _ThinkingRejected(Exception):
    """Anthropic refused a request over its thinking blocks before running it."""


REFUSED = "Claude declined this request. Try different words, or another model."


class AnthropicText:
    """One person's key and model on Anthropic's Messages API."""

    def __init__(
        self,
        key: str,
        model: str,
        usage: UsageRecorder,
        client: AsyncAnthropic | None = None,
        replay: ThinkingReplay = REPLAY,
    ):
        self._key = key
        self._model = model
        self._usage = usage
        self._client = client
        self._replay = replay

    def _make(self) -> AsyncAnthropic:
        return self._client or AsyncAnthropic(api_key=self._key, max_retries=0)

    def _request(
        self,
        capability: str,
        system: str,
        messages: list[dict[str, Any]],
        *,
        show_thinking: bool,
        thinking_off: bool = False,
        tools: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx = require_context()
        effort = effort_for(capability, ctx.product_id)
        shape = SHAPES.get(self._model) or shape_of(self._model)
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": MAX_TOKENS[effort],
            "messages": messages,
            "output_config": {"effort": effort} if shape.effort else {},
            "cache_control": {"type": "ephemeral"},
        }
        if not shape.adaptive:
            pass  # a model before adaptive thinking runs without thinking
        elif thinking_off and shape.can_turn_off:
            body["thinking"] = {"type": "disabled"}
        else:
            body["thinking"] = (
                {"type": "adaptive", "display": "summarized"}
                if show_thinking
                else {"type": "adaptive"}
            )
        if system:
            body["system"] = system
        if tools:
            body["tools"] = tools
        if schema is not None:
            # Anthropic refuses counts and lengths it cannot enforce (minItems above 1, minLength,
            # found in CP13); the SDK moves them into the descriptions, and callers check answers
            strict = transform_schema(schema)
            body["output_config"]["format"] = {"type": "json_schema", "schema": strict}
        if not body["output_config"]:
            del body["output_config"]
        return body

    async def _learn_shape(self) -> None:
        """Read this model's capabilities once (`SHAPES`); when they cannot be read, its name
        says enough (`shape_of`), and it is asked again next time."""
        if self._model in SHAPES:
            return
        client = self._make()
        try:
            found = await client.models.retrieve(self._model)
            caps = getattr(found, "capabilities", None)
            if caps is not None and not isinstance(caps, dict):  # the SDK's typed tree
                caps = caps.model_dump(exclude_none=True)
            if isinstance(caps, dict) and caps:
                SHAPES[self._model] = shape_of(self._model, caps)
        except Exception:  # the request goes as its name says; Anthropic's answer will say more
            log.info("could not read the capabilities of %s", self._model)
        finally:
            if self._client is None:
                await client.close()

    async def _run(
        self, capability: str, body: dict[str, Any], thinking_retry: bool = False
    ) -> AsyncIterator[ChatChunk]:
        """Stream one request. With `thinking_retry`, a 400 about thinking is raised as
        `_ThinkingRejected` (nothing has run) so the caller can send it again without."""
        ctx = require_context()
        client = self._make()
        usage: Any = None
        try:
            async with client.messages.stream(**body) as stream:
                async for event in stream:
                    if event.type != "content_block_delta":
                        continue
                    delta = event.delta
                    if delta.type == "text_delta" and delta.text:
                        yield ChatChunk(text=delta.text)
                    elif delta.type == "thinking_delta" and delta.thinking:
                        yield ChatChunk(reasoning=delta.thinking)
                final = await stream.get_final_message()
            usage = final.usage
            if final.stop_reason == "refusal":
                raise RunError("provider_refused", REFUSED, retryable=False)
            calls = [b for b in final.content if b.type == "tool_use"]
            if calls:
                blocks = [b.model_dump(exclude_none=True) for b in final.content]
                self._replay.remember([b.id for b in calls], blocks)
                yield ChatChunk(
                    tool_calls=[ToolCall(b.id, b.name, json.dumps(b.input)) for b in calls]
                )
        except APIStatusError as e:
            if thinking_retry and e.status_code == 400 and "thinking" in str(e).lower():
                raise _ThinkingRejected from None
            raise RunError("provider_refused", said_of(e, self._model), retryable=True) from None
        except APIConnectionError as e:
            raise RunError("provider_refused", said_of(e, self._model), retryable=True) from None
        finally:
            if self._client is None:
                await client.close()
            if usage is not None:
                await self._record(ctx, capability, usage)

    async def _record(self, ctx: Any, capability: str, usage: Any) -> None:
        cached = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        written = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        prompt = int(usage.input_tokens or 0) + cached + written
        meta = {
            "capability": capability, "alias": self._model, "provider": "anthropic",
            "cached_tokens": cached, "long_prompt": prompt > LONG_PROMPT_TOKENS,
        }  # fmt: skip
        for kind, n in ((LLM_INPUT_TOKENS, prompt), (LLM_OUTPUT_TOKENS, usage.output_tokens)):
            if n:
                await record_safely(
                    self._usage, UsageEvent.for_context(ctx, kind, n, "tokens", **meta)
                )

    async def stream(
        self, capability: str, system: str, prompt: Prompt, schema: dict[str, Any] | None = None
    ) -> AsyncIterator[str]:
        messages = [{"role": "user", "content": prompt_content(prompt)}]
        await self._learn_shape()
        body = self._request(capability, system, messages, show_thinking=False, schema=schema)
        async for chunk in self._run(capability, body):
            if chunk.text:
                yield chunk.text

    async def chat(
        self,
        capability: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        thinking: bool = False,
    ) -> AsyncIterator[ChatChunk]:
        conv = to_anthropic(messages, self._replay)
        await self._learn_shape()
        # thinking can be turned off at effort high or below, which is all this module asks for
        body = self._request(
            capability, conv.system, conv.messages, show_thinking=thinking,
            thinking_off=conv.replay_missing, tools=to_anthropic_tools(tools),
        )  # fmt: skip
        try:
            async for chunk in self._run(capability, body, thinking_retry=True):
                yield chunk
            return
        except _ThinkingRejected:
            log.warning("Anthropic refused the replayed thinking; this turn runs without it")
        bare = to_anthropic(messages, None)
        body = self._request(
            capability, bare.system, bare.messages, show_thinking=False,
            thinking_off=True, tools=to_anthropic_tools(tools),
        )  # fmt: skip
        async for chunk in self._run(capability, body):
            yield chunk
