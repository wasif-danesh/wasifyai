"""Text on Anthropic's own API (ADR-0100, stage CP2), against a fake of its streaming Messages API:
no temperature, adaptive thinking with an effort per job, thinking blocks replayed unchanged within
a tool loop, a refusal said in words, tokens counted with the provider."""

import json
from typing import Any

import httpx2 as httpx  # the transport the Anthropic SDK 2.x uses
import pytest
from anthropic import AsyncAnthropic
from wasifyai_api.anthropic_text import (
    REFUSED,
    SHAPES,
    AnthropicText,
    ThinkingReplay,
    effort_for,
    shape_of,
    to_anthropic,
)
from wasifyai_platform_sdk import (
    InMemoryUsageRecorder,
    RunContext,
    RunError,
    reset_context,
    set_context,
)
from wasifyai_platform_sdk.parts import Audio, Image

MODEL = "claude-haiku-5-5"


def events(*blocks: dict[str, Any], stop: str = "end_turn") -> httpx.Response:
    """A streamed reply made of `blocks` (thinking, text or tool_use), as Anthropic sends it."""
    out = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_1", "type": "message", "role": "assistant", "model": MODEL, "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 1, "cache_read_input_tokens": 3,
                      "cache_creation_input_tokens": 0}}}),
    ]  # fmt: skip
    for i, b in enumerate(blocks):
        if b["type"] == "thinking":
            start = {"type": "thinking", "thinking": "", "signature": ""}
            deltas = [{"type": "thinking_delta", "thinking": b["thinking"]},
                      {"type": "signature_delta", "signature": b["signature"]}]  # fmt: skip
        elif b["type"] == "text":
            start = {"type": "text", "text": ""}
            deltas = [{"type": "text_delta", "text": b["text"]}]
        else:
            start = {"type": "tool_use", "id": b["id"], "name": b["name"], "input": {}}
            deltas = [{"type": "input_json_delta", "partial_json": json.dumps(b["input"])}]
        out.append(
            (
                "content_block_start",
                {"type": "content_block_start", "index": i, "content_block": start},
            )
        )
        for d in deltas:
            out.append(("content_block_delta",
                        {"type": "content_block_delta", "index": i, "delta": d}))  # fmt: skip
        out.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
    out.append(("message_delta", {"type": "message_delta",
                                  "delta": {"stop_reason": stop, "stop_sequence": None},
                                  "usage": {"output_tokens": 5}}))  # fmt: skip
    out.append(("message_stop", {"type": "message_stop"}))
    body = "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in out)
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def fake(
    *answers: httpx.Response, caps: dict[str, Any] | None = None
) -> tuple[AsyncAnthropic, list[dict[str, Any]]]:
    """Anthropic answering `answers` in turn; the Models API knows the model by `caps`, or not."""
    sent: list[dict[str, Any]] = []
    queue = list(answers)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path.startswith("/v1/models/"):
            model = req.url.path.rsplit("/", 1)[1]
            if caps is None:
                return httpx.Response(
                    404,
                    json={"type": "error", "error": {"type": "not_found_error", "message": "no"}},
                )
            return httpx.Response(200, json={
                "type": "model", "id": model, "display_name": model,
                "created_at": "2026-11-01T00:00:00Z", "capabilities": caps,
            })  # fmt: skip
        sent.append(json.loads(req.content))
        return queue.pop(0)

    client = AsyncAnthropic(
        api_key="sk-ant-test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return client, sent


@pytest.fixture
def assistant():
    token = set_context(RunContext("t1", "wasifyai-assistant", "u1", "run-1", "th-1"))
    yield
    reset_context(token)


@pytest.fixture
def image_product():
    token = set_context(RunContext("t1", "wasifyai-image", "u1", "run-1", "th-1"))
    yield
    reset_context(token)


@pytest.mark.parametrize(
    ("capability", "product", "effort"),
    [("text.enhance", "wasifyai-image", "low"), ("text.lyrics", "wasifyai-voice", "low"),
     ("text.describe_image", "wasifyai-training", "low"),
     ("text.chat", "wasifyai-notebooks", "medium"),
     ("text.chat", "wasifyai-voice", "medium"), ("text.chat", "wasifyai-assistant", "high"),
     ("text.chat", "wasifyai-creative", "high"), ("video_builder.draft", "wasifyai-video", "high")],
)  # fmt: skip
def test_each_job_has_its_effort(capability, product, effort):
    assert effort_for(capability, product) == effort


async def test_a_prompt_goes_with_no_temperature_low_effort_and_caching(image_product):
    client, sent = fake(events({"type": "thinking", "thinking": "", "signature": "s1"},
                               {"type": "text", "text": "A red fox at dawn."}))  # fmt: skip
    usage = InMemoryUsageRecorder()
    claude = AnthropicText("sk-ant-test", MODEL, usage, client=client)
    out = [t async for t in claude.stream("text.enhance", "Rewrite the prompt.", "a fox")]
    assert "".join(out) == "A red fox at dawn."  # the thinking block came first and is not text
    (body,) = sent
    assert body["model"] == MODEL and body["system"] == "Rewrite the prompt."
    assert not {"temperature", "top_p", "top_k"} & set(body)
    assert body["thinking"] == {"type": "adaptive"}  # thinking is not shown here
    assert body["output_config"] == {"effort": "low"} and body["max_tokens"] == 8_000
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["messages"] == [{"role": "user", "content": [{"type": "text", "text": "a fox"}]}]
    kinds = {(e.kind, e.quantity, e.meta["provider"]) for e in usage.events}
    assert kinds == {("llm.input_tokens", 15, "anthropic"), ("llm.output_tokens", 5, "anthropic")}


async def test_a_schema_asks_for_structured_output(image_product):
    client, sent = fake(events({"type": "text", "text": '{"a": 1}'}))
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"],
              "additionalProperties": False}  # fmt: skip
    claude = AnthropicText("k", MODEL, InMemoryUsageRecorder(), client=client)
    assert "".join([t async for t in claude.stream("text.enhance", "s", "p", schema)]) == '{"a": 1}'
    assert sent[0]["output_config"]["format"] == {"type": "json_schema", "schema": schema}


async def test_counts_and_lengths_it_cannot_enforce_go_into_the_descriptions(image_product):
    """Anthropic refuses minItems above 1 and string lengths (found in CP13); the SDK's
    transform keeps them as words for the model, and the caller checks the answer."""
    client, sent = fake(events({"type": "text", "text": '{"beats": []}'}))
    item = {"type": "string", "minLength": 25, "maxLength": 140}
    schema = {"type": "object", "required": ["beats"], "additionalProperties": False,
              "properties": {"beats": {"type": "array", "minItems": 3, "maxItems": 3,
                                       "items": item}}}  # fmt: skip
    claude = AnthropicText("k", MODEL, InMemoryUsageRecorder(), client=client)
    _ = [t async for t in claude.stream("text.chat", "s", "p", schema)]
    beats = sent[0]["output_config"]["format"]["schema"]["properties"]["beats"]
    assert "minItems" not in beats and "maxItems" not in beats
    assert "minLength" not in beats["items"] and "25" in beats["items"]["description"]
    assert "3" in beats["description"]


async def test_pictures_go_as_image_blocks_and_a_recording_is_refused(image_product):
    client, sent = fake(events({"type": "text", "text": "A cat."}))
    claude = AnthropicText("k", MODEL, InMemoryUsageRecorder(), client=client)
    prompt = ["Describe it.", Image.from_bytes(b"\x89PNG", "image/png"),
              Image.from_url("https://x.test/a.jpg", "image/jpeg")]  # fmt: skip
    assert [t async for t in claude.stream("text.describe_image", "", prompt)] == ["A cat."]
    content = sent[0]["messages"][0]["content"]
    assert content[1] == {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                      "data": "iVBORw=="}}  # fmt: skip
    assert content[2] == {"type": "image", "source": {"type": "url", "url": "https://x.test/a.jpg"}}
    with pytest.raises(RunError, match="cannot listen"):
        async for _ in claude.stream("text.multimodal", "", [Audio.from_bytes(b"x", "wav")]):
            pass


TOOLS = [{"type": "function", "function": {"name": "find", "description": "Find a creation.",
          "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}}]  # fmt: skip
THOUGHT = {"type": "thinking", "thinking": "They want the fox.", "signature": "sig-1"}
CALL = {"type": "tool_use", "id": "toolu_1", "name": "find", "input": {"q": "fox"}}


async def test_a_tool_loop_sends_the_thinking_back_unchanged(assistant):
    client, sent = fake(
        events(THOUGHT, {"type": "text", "text": "Looking."}, CALL, stop="tool_use"),
        events({"type": "text", "text": "Found it."}),
    )
    claude = AnthropicText("k", MODEL, InMemoryUsageRecorder(), client=client,
                           replay=ThinkingReplay())  # fmt: skip
    first = [c async for c in claude.chat("text.chat", [
        {"role": "system", "content": "You are the assistant."},
        {"role": "user", "content": "Find my fox."}], TOOLS, thinking=True)]  # fmt: skip
    assert [c.reasoning for c in first if c.reasoning] == ["They want the fox."]
    (calls,) = [c.tool_calls for c in first if c.tool_calls]
    assert [(t.id, t.name, json.loads(t.arguments)) for t in calls] == [
        ("toolu_1", "find", {"q": "fox"})
    ]
    body = sent[0]
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["output_config"] == {"effort": "high"} and body["max_tokens"] == 32_000
    assert body["tools"] == [{"name": "find", "description": "Find a creation.",
                              "input_schema": TOOLS[0]["function"]["parameters"]}]  # fmt: skip
    assert body["system"] == "You are the assistant."
    # the graph sends its own OpenAI-shaped copy of the turn back with the result
    second = [
        c
        async for c in claude.chat(
            "text.chat",
            [
                {"role": "system", "content": "You are the assistant."},
                {"role": "user", "content": "Find my fox."},
                {
                    "role": "assistant",
                    "content": "Looking.",
                    "tool_calls": [
                        {
                            "id": "toolu_1",
                            "type": "function",
                            "function": {"name": "find", "arguments": '{"q": "fox"}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "toolu_1", "content": '{"found": 1}'},
            ],
            TOOLS,
        )
    ]
    assert "".join(c.text for c in second) == "Found it."
    replayed = sent[1]["messages"][1]
    assert replayed["role"] == "assistant"
    assert replayed["content"][0] == THOUGHT  # first, with its signature, untouched
    assert (
        replayed["content"][2]["type"] == "tool_use" and replayed["content"][2]["id"] == "toolu_1"
    )
    assert sent[1]["messages"][2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"found": 1}'}]}  # fmt: skip
    assert sent[1]["thinking"] == {"type": "adaptive"}


LOOP = [
    {"role": "user", "content": "Find my fox."},
    {"role": "assistant", "content": None, "tool_calls": [
        {"id": "toolu_9", "type": "function", "function": {"name": "find", "arguments": "{}"}}]},
    {"role": "tool", "tool_call_id": "toolu_9", "content": "none"},
]  # fmt: skip


async def test_a_turn_whose_thinking_is_gone_runs_with_thinking_off(assistant):
    client, sent = fake(events({"type": "text", "text": "Nothing found."}))
    claude = AnthropicText("k", MODEL, InMemoryUsageRecorder(), client=client,
                           replay=ThinkingReplay())  # fmt: skip
    assert [c.text async for c in claude.chat("text.chat", LOOP, TOOLS)] == ["Nothing found."]
    assert sent[0]["thinking"] == {"type": "disabled"}
    assert sent[0]["messages"][1]["content"] == [
        {"type": "tool_use", "id": "toolu_9", "name": "find", "input": {}}
    ]


def test_an_older_tool_loop_without_its_thinking_does_not_turn_thinking_off():
    conv = to_anthropic([*LOOP, {"role": "assistant", "content": "Nothing."},
                         {"role": "user", "content": "Try again."}], ThinkingReplay())  # fmt: skip
    assert conv.replay_missing is False


async def test_a_400_over_thinking_is_sent_once_more_without_it(assistant):
    rejected = httpx.Response(400, json={"type": "error", "error": {
        "type": "invalid_request_error",
        "message": "thinking block is bound to a different conversation"}})  # fmt: skip
    client, sent = fake(rejected, events({"type": "text", "text": "Done."}))
    replay = ThinkingReplay()
    replay.remember(["toolu_9"], [THOUGHT, {"type": "tool_use", "id": "toolu_9", "name": "find",
                                            "input": {}}])  # fmt: skip
    claude = AnthropicText("k", MODEL, InMemoryUsageRecorder(), client=client, replay=replay)
    assert [c.text async for c in claude.chat("text.chat", LOOP, TOOLS)] == ["Done."]
    assert sent[0]["messages"][1]["content"][0] == THOUGHT
    assert sent[1]["thinking"] == {"type": "disabled"}
    assert all(b["type"] != "thinking" for b in sent[1]["messages"][1]["content"])


async def test_a_refusal_is_said_in_words(assistant):
    client, _ = fake(events({"type": "text", "text": ""}, stop="refusal"))
    claude = AnthropicText("k", MODEL, InMemoryUsageRecorder(), client=client)
    with pytest.raises(RunError) as e:
        async for _ in claude.chat("text.chat", [{"role": "user", "content": "x"}]):
            pass
    assert e.value.message == REFUSED


@pytest.mark.parametrize(
    ("status", "words"),
    [(401, "Anthropic did not accept the key."), (404, "no model called claude-haiku-5-5"),
     (429, "too many requests"), (529, "busy"),
     (500, "Anthropic answered 500: no")],  # its own words, which say what to fix
)  # fmt: skip
async def test_an_error_is_said_in_anthropics_name(assistant, status, words):
    answer = httpx.Response(status, json={"type": "error", "error": {"type": "x", "message": "no"}})
    client, _ = fake(answer)
    claude = AnthropicText("k", MODEL, InMemoryUsageRecorder(), client=client)
    with pytest.raises(RunError) as e:
        async for _ in claude.chat("text.chat", [{"role": "user", "content": "x"}]):
            pass
    assert words in e.value.message and "sk-" not in e.value.message


def test_a_conversation_never_ends_on_the_assistant():
    conv = to_anthropic(
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hel"}]
    )
    assert conv.messages[-1] == {"role": "user", "content": [{"type": "text", "text": "Continue."}]}


OLD_CAPS = {"thinking": {"supported": True, "types": {"enabled": {"supported": True},
            "adaptive": {"supported": False}}}, "effort": {"supported": False}}  # fmt: skip
NEW_CAPS = {"thinking": {"supported": True, "types": {"enabled": {"supported": False},
            "adaptive": {"supported": True}}}, "effort": {"supported": True}}  # fmt: skip


async def test_an_older_model_is_asked_for_no_thinking_and_no_effort(image_product):
    # Haiku 4.5, chosen from the key's list (owner, 2026-11-13): adaptive thinking, effort are 400s
    SHAPES.clear()
    client, sent = fake(events({"type": "text", "text": "A fox."}), caps=OLD_CAPS)
    claude = AnthropicText("k", "claude-haiku-4-5-20251001", InMemoryUsageRecorder(), client=client)
    assert "".join([t async for t in claude.stream("text.enhance", "", "a fox")]) == "A fox."
    (body,) = sent
    assert "thinking" not in body and "output_config" not in body
    assert "claude-haiku-4-5-20251001" in SHAPES  # read once, for every key


async def test_a_model_whose_thinking_stays_on_is_never_sent_disabled(assistant):
    SHAPES.clear()
    for model in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-2"):
        client, sent = fake(events({"type": "text", "text": "Nothing found."}), caps=NEW_CAPS)
        claude = AnthropicText("k", model, InMemoryUsageRecorder(), client=client,
                               replay=ThinkingReplay())  # fmt: skip
        assert [c.text async for c in claude.chat("text.chat", LOOP, TOOLS)] == ["Nothing found."]
        assert sent[0]["thinking"] == {"type": "adaptive"}, model
        assert sent[0]["output_config"] == {"effort": "high"}


def test_without_its_capabilities_a_model_is_known_by_its_name():
    assert shape_of("claude-haiku-4-5-20251001") == shape_of("claude-x", OLD_CAPS)
    assert not shape_of("claude-opus-4-5-20251101").adaptive
    assert shape_of("claude-opus-4-5-20251101").effort
    assert shape_of("claude-haiku-5-5").can_turn_off
    assert not shape_of("claude-fable-5-1").can_turn_off
