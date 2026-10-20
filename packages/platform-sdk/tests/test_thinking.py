"""Thinking in the text providers (ADR-0083, stage CO1): the switch a hosted alias declares, and the
field a server names its thinking in."""

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI
from wasifyai_platform_sdk import InMemoryUsageRecorder, RunContext, reset_context, set_context
from wasifyai_platform_sdk.config import CapabilityBinding
from wasifyai_platform_sdk.providers.litellm import LiteLLMTextProvider, reasoning_of


@pytest.fixture
def ctx():
    token = set_context(RunContext("t1", "p", "u1", run_id="r1", thread_id="th"))
    yield
    reset_context(token)


def test_the_thinking_field_is_read_by_whichever_name_the_server_gives_it():
    assert (
        reasoning_of(SimpleNamespace(model_extra={"reasoning_content": "llama.cpp"})) == "llama.cpp"
    )
    assert reasoning_of(SimpleNamespace(model_extra={"reasoning": "ollama"})) == "ollama"
    assert reasoning_of(SimpleNamespace(model_extra={})) == ""
    assert reasoning_of(SimpleNamespace(model_extra=None)) == ""
    assert reasoning_of(SimpleNamespace(model_extra={"reasoning": 5})) == ""


def sse(*deltas: dict[str, Any]) -> str:
    body = ""
    for d in deltas:
        chunk = {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "m",
                 "choices": [{"index": 0, "delta": d}]}  # fmt: skip
        body += "data: " + json.dumps(chunk) + "\n\n"
    return body + "data: [DONE]\n\n"


async def test_a_hosted_alias_says_what_it_needs_to_think_or_not_and_its_thinking_is_passed_on(ctx):
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=sse({"reasoning_content": "hmm "}, {"content": "Hi."}),
        )

    provider = LiteLLMTextProvider("http://x/v1", "k", InMemoryUsageRecorder())
    provider._client = AsyncOpenAI(
        base_url="http://x/v1",
        api_key="k",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),  # pyright: ignore[reportArgumentType]
    )
    binding = CapabilityBinding(
        provider="litellm",
        model="big",
        defaults={
            "thinking_options": {"on": {"enable_thinking": True}, "off": {"enable_thinking": False}}
        },
    )
    messages = [{"role": "user", "content": "hi"}]
    on = [c async for c in provider.chat("text.chat", binding, messages, None, True)]
    off = [c async for c in provider.chat("text.chat", binding, messages, None, False)]
    assert seen[0]["enable_thinking"] is True and seen[1]["enable_thinking"] is False
    assert [c.reasoning for c in on if c.reasoning] == ["hmm "]
    assert "".join(c.text for c in on) == "Hi."
    assert "".join(c.text for c in off) == "Hi."

    plain = CapabilityBinding(provider="litellm", model="plain")  # an alias that declares nothing
    seen.clear()
    _ = [c async for c in provider.chat("text.chat", plain, messages, None, True)]
    assert "enable_thinking" not in seen[0]
