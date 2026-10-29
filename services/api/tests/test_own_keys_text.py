"""Chat and every text product on the person's key (ADR-0095, stage K2): with Chat and writing set
to "With my key" the requests go to that provider with that key; otherwise to this computer's
model. Embeddings stay here. A refusal is said in the provider's name."""

import json
from typing import Any

import httpx
import pytest
from wasifyai_api import own_keys_text
from wasifyai_api.own_keys import OwnKeysService, Provider, Tried
from wasifyai_api.own_keys_text import KeyedTextProvider
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_platform_sdk import (
    ChatChunk,
    InMemorySecretStore,
    InMemoryUsageRecorder,
    RunContext,
    RunError,
    reset_context,
    set_context,
)
from wasifyai_platform_sdk.config import CapabilityBinding

KEY = "sk-or-good-123"
BINDING = CapabilityBinding(provider="litellm", model="default-chat")


class Local:
    """This computer's model: says where an answer came from."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def stream(self, capability, binding, system, prompt, schema=None):
        self.asked.append(capability)
        yield "from this computer"

    async def chat(self, capability, binding, messages, tools=None, thinking=False):
        self.asked.append(capability)
        yield ChatChunk(text="from this computer")

    async def embed(self, capability, binding, texts):
        self.asked.append("embed")
        return [[0.0] for _ in texts]


async def accept(provider: Provider, model: str, key: str, base: str) -> Tried:
    return Tried(True, 1)


def sse(*chunks: dict[str, Any]) -> httpx.Response:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def delta(text: str) -> dict[str, Any]:
    return {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "m",
            "choices": [{"index": 0, "delta": {"content": text},
                         "finish_reason": None}]}  # fmt: skip


USAGE = {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "m", "choices": [],
         "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}  # fmt: skip


@pytest.fixture
def ctx():
    token = set_context(RunContext("t1", "wasifyai-voice", "u1", "run-1", "th-1"))
    yield
    reset_context(token)


async def rig(monkeypatch, answer=None):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return answer(req) if answer else sse(delta("Blue"), delta(" sky."), USAGE)

    real = own_keys_text.AsyncOpenAI
    monkeypatch.setattr(
        own_keys_text,
        "AsyncOpenAI",
        lambda **kw: real(
            **kw,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),  # pyright: ignore[reportArgumentType]
        ),
    )
    keys = OwnKeysService(
        InMemorySettingsStore(), InMemorySecretStore(), {"text": accept, "media": accept}
    )
    local, usage = Local(), InMemoryUsageRecorder()
    return KeyedTextProvider(local, keys, usage), keys, local, usage, seen


async def with_key(keys: OwnKeysService) -> None:
    await keys.save("chat", "key", "openrouter", "openai/gpt-4o-mini", None, KEY)


async def text(it) -> str:
    return "".join([t async for t in it])


async def test_on_this_computer_everything_goes_to_the_local_model(monkeypatch, ctx):
    p, _, local, _, seen = await rig(monkeypatch)
    assert await text(p.stream("lyrics", BINDING, "sys", "hi")) == "from this computer"
    assert [c async for c in p.chat("chat", BINDING, [{"role": "user", "content": "hi"}])]
    assert local.asked == ["lyrics", "chat"] and seen == []


async def test_with_a_key_a_text_product_goes_to_the_provider_and_its_tokens_are_counted(
    monkeypatch, ctx
):
    p, keys, local, usage, seen = await rig(monkeypatch)
    await with_key(keys)
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    assert await text(p.stream("enhance", BINDING, "Be brief.", "a fox", schema)) == "Blue sky."
    assert local.asked == []
    (req,) = seen
    assert str(req.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(req.content)
    assert body["model"] == "openai/gpt-4o-mini" and body["stream"] is True
    assert body["messages"][0] == {"role": "system", "content": "Be brief."}
    assert body["response_format"]["json_schema"]["schema"] == schema
    tokens = {(e.kind, e.quantity, e.meta["provider"]) for e in usage.events}
    assert tokens == {("llm.input_tokens", 7, "openrouter"), ("llm.output_tokens", 3, "openrouter")}


async def test_a_chat_turn_with_tools_goes_to_the_provider(monkeypatch, ctx):
    p, keys, local, _, seen = await rig(monkeypatch)
    await with_key(keys)
    tools = [{"type": "function", "function": {"name": "image_generate", "parameters": {}}}]
    chunks = [c async for c in p.chat("chat", BINDING, [{"role": "user", "content": "hi"}], tools)]
    assert "".join(c.text for c in chunks) == "Blue sky."
    assert local.asked == []
    assert json.loads(seen[0].content)["tools"] == tools


async def test_embeddings_stay_on_this_computer(monkeypatch, ctx):
    p, keys, local, _, seen = await rig(monkeypatch)
    await with_key(keys)
    assert await p.embed("embed", BINDING, ["a", "b"]) == [[0.0], [0.0]]
    assert local.asked == ["embed"] and seen == []


@pytest.mark.parametrize(
    ("status", "words"),
    [(401, "OpenRouter did not accept the key."), (404, "no model called openai/gpt-4o-mini"),
     (429, "too many requests"), (500, "OpenRouter answered 500.")],
)  # fmt: skip
async def test_a_refusal_is_said_in_the_providers_name(monkeypatch, ctx, status, words):
    answer = lambda req: httpx.Response(status, json={"error": {"message": "no"}})  # noqa: E731
    p, keys, _, _, _ = await rig(monkeypatch, answer)
    await with_key(keys)
    with pytest.raises(RunError) as e:
        await text(p.stream("chat", BINDING, "s", "hi"))
    assert e.value.code == "provider_refused" and words in e.value.message
    assert KEY not in e.value.message
    with pytest.raises(RunError):
        [c async for c in p.chat("chat", BINDING, [{"role": "user", "content": "hi"}])]


async def test_back_to_this_computer_or_removing_the_key_is_followed_at_once(monkeypatch, ctx):
    p, keys, local, _, seen = await rig(monkeypatch)
    await with_key(keys)
    await text(p.stream("chat", BINDING, "s", "hi"))
    await keys.save("chat", "here", None, None, None, None)
    assert await text(p.stream("chat", BINDING, "s", "hi")) == "from this computer"
    await with_key(keys)
    await keys.remove("chat")
    assert await text(p.stream("chat", BINDING, "s", "hi")) == "from this computer"
    assert len(seen) == 1 and local.asked == ["chat", "chat"]


async def test_only_chat_and_writing_decides_where_text_goes(monkeypatch, ctx):
    p, keys, local, _, seen = await rig(monkeypatch)
    await keys.save("images", "key", "fal", "fal-ai/flux-2", None, KEY)
    assert await text(p.stream("chat", BINDING, "s", "hi")) == "from this computer"
    assert seen == []
