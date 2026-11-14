# ruff: noqa: E501  (test data is easier to read on one line)
"""The coding sessions' model gateway (ADR-0102, decision 4; stage C1b): a token in place of a key,
the key from the secret store, each call's tokens as usage events, a session's cost counted and
limited, the body passed on byte for byte, streaming passed through, and a refusal by the model
turned into a plain message that ends the turn. The provider is pretended here (an HTTP transport
the test holds); the real one is the opt-in run of `tests/integration/test_coding_session_real.py`."""

import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from wasifyai_api.coding_gateway import (
    ANTHROPIC,
    DECLINED,
    OPENAI,
    Call,
    CodingGateway,
    GatewayError,
    ModelRoute,
    anthropic_usage,
    cost_of,
    load_models,
    router,
)
from wasifyai_api.services import ApiServices
from wasifyai_platform_sdk.secrets import InMemorySecretStore
from wasifyai_platform_sdk.usage import LLM_INPUT_TOKENS, LLM_OUTPUT_TOKENS, InMemoryUsageRecorder

KEY = "sk-ant-the-real-key-never-leaves"
CLOUD = ModelRoute(
    id="cloud", title="Cloud model", where="cloud", shape=ANTHROPIC, provider="anthropic",
    engine_model="anthropic/cloud-1", provider_model="cloud-1", upstream="https://provider.test",
    secret="keys.chat.anthropic",
    price={"input": 2.0, "output": 10.0, "cache_read": 0.1, "cache_write": 2.5, "cache_write_1h": 4.0},
    engine_settings={},
)  # fmt: skip
LOCAL = ModelRoute(
    id="local", title="Local model", where="this-computer", shape=OPENAI, provider="ollama",
    engine_model="openai/local-1", provider_model="local-1", upstream="http://127.0.0.1:1/v1",
    secret="", price={}, engine_settings={"temperature": 0.2},
)  # fmt: skip


class Provider:
    """A pretended provider: it keeps what it was sent and answers what the test says."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.answer: Any = {
            "id": "msg_1", "type": "message", "role": "assistant", "model": "cloud-1",
            "content": [{"type": "text", "text": "hello"}], "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }  # fmt: skip
        self.status = 200
        self.stream: list[bytes] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.stream is not None:
            parts = list(self.stream)

            async def chunks():
                for part in parts:
                    yield part

            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=chunks()
            )
        return httpx.Response(self.status, json=self.answer)


class Box:
    def __init__(self) -> None:
        self.provider = Provider()
        self.secrets = InMemorySecretStore()
        self.usage = InMemoryUsageRecorder()
        self.calls: list[Call] = []
        self.gateway = CodingGateway(
            secrets=self.secrets, usage=self.usage, base_url=lambda: "http://127.0.0.1:4321",
            models=("cloud", {"cloud": CLOUD, "local": LOCAL}),
            transport=httpx.MockTransport(self.provider),
        )  # fmt: skip
        app = FastAPI()
        app.state.services = ApiServices(coding_gateway=self.gateway)
        app.include_router(router)
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
        )

    def open(self, session: str = "s1", model: str | None = None, **more: Any):
        return self.gateway.open(
            tenant_id="t1", product_id="wasifyai-code", user_id="u1", session_id=session,
            model=model, on_call=self.calls.append, **more,
        )  # fmt: skip

    async def ask(self, token: str, body: dict | bytes | None = None, **headers: str):
        body = {"model": "cloud-1", "max_tokens": 10, "messages": []} if body is None else body
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        return await self.http.post(
            "/coding-gateway/v1/messages", content=raw,
            headers={"x-api-key": token, "content-type": "application/json", **headers},
        )  # fmt: skip


@pytest.fixture
async def box():
    b = Box()
    await b.secrets.put("keys.chat.anthropic", KEY)
    yield b
    await b.http.aclose()
    await b.gateway.close()


def sse(*events: dict) -> list[bytes]:
    return [f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events]


# ---- the token and the key -----------------------------------------------------------------------


async def test_a_session_gets_a_token_and_an_address_and_never_the_key(box):
    grant = box.open()
    assert grant.token.startswith("wcg-") and KEY not in repr(grant)
    assert grant.base_url == "http://127.0.0.1:4321/coding-gateway"  # the library adds /v1/messages
    assert grant.engine_model == "anthropic/cloud-1"
    local = box.open("s2", "local")
    assert local.base_url == "http://127.0.0.1:4321/coding-gateway/v1"  # ... /chat/completions
    assert local.engine_settings == {"temperature": 0.2}


async def test_the_key_is_put_on_the_call_and_the_token_is_not_passed_on(box):
    grant = box.open()
    r = await box.ask(
        grant.token, **{"anthropic-beta": "some-beta", "anthropic-version": "2023-06-01"}
    )
    assert r.status_code == 200 and r.json()["content"][0]["text"] == "hello"
    sent = box.provider.requests[0]
    assert str(sent.url) == "https://provider.test/v1/messages"
    assert sent.headers["x-api-key"] == KEY and grant.token not in str(sent.headers)
    assert sent.headers["anthropic-beta"] == "some-beta"
    assert sent.headers["accept-encoding"] == "identity"  # a compressed stream cannot be read
    assert KEY not in r.text and KEY not in str(r.headers)


async def test_an_unknown_token_a_closed_session_and_no_token_are_refused(box):
    grant = box.open()
    assert (await box.ask("wcg-made-up")).status_code == 401
    assert (await box.ask(KEY)).status_code == 401  # the real key opens nothing here
    r = await box.http.post("/coding-gateway/v1/messages", json={"model": "cloud-1"})
    assert r.status_code == 401 and r.json()["error"]["type"] == "authentication_error"
    box.gateway.close_session("s1")
    assert (await box.ask(grant.token)).status_code == 401
    assert box.provider.requests == []


async def test_a_new_grant_for_the_same_session_ends_the_old_token_and_keeps_the_count(box):
    first = box.open()
    await box.ask(first.token)
    second = box.open()
    assert (await box.ask(first.token)).status_code == 401
    assert (await box.ask(second.token)).status_code == 200
    assert box.gateway.spent("s1")["calls"] == 2


async def test_only_the_sessions_own_model_is_let_through(box):
    grant = box.open()
    r = await box.ask(grant.token, {"model": "another-model", "messages": []})
    assert r.status_code == 400 and "cloud-1" in r.json()["error"]["message"]
    wrong_door = await box.http.post(
        "/coding-gateway/v1/chat/completions", json={"model": "cloud-1"},
        headers={"authorization": f"Bearer {grant.token}"},
    )  # fmt: skip
    assert wrong_door.status_code == 404
    assert box.provider.requests == []


async def test_no_key_saved_is_said_in_words_and_nothing_is_sent(box):
    await box.secrets.delete("keys.chat.anthropic")
    assert "No key is saved" in (await box.gateway.ready("cloud") or "")
    assert await box.gateway.ready("local") is None  # a model on this computer needs none
    r = await box.ask(box.open().token)
    assert r.status_code == 401 and "No key is saved" in r.json()["error"]["message"]
    assert box.provider.requests == []
    listed = {m["id"]: m for m in await box.gateway.list_models()}
    assert listed["cloud"]["ready"] is False and listed["local"]["ready"] is True
    assert listed["cloud"]["default"] and KEY not in json.dumps(listed)


def test_a_model_that_is_not_in_the_list_is_refused():
    gateway = CodingGateway(
        secrets=InMemorySecretStore(), usage=InMemoryUsageRecorder(), base_url=lambda: "",
        models=("cloud", {"cloud": CLOUD}),
    )  # fmt: skip
    with pytest.raises(GatewayError):
        gateway.model("gpt-something")


# ---- the body ------------------------------------------------------------------------------------


async def test_the_body_is_passed_on_byte_for_byte_with_its_cache_marks(box):
    raw = (
        b'{"model":"cloud-1","max_tokens":64,  "system":[{"type":"text","text":"long rules",'
        b'"cache_control":{"type":"ephemeral"}}],"messages":[{"role":"user","content":[{"type":'
        b'"text","text":"hi \\u00e9","cache_control":{"type":"ephemeral","ttl":"1h"}}]}]}'
    )
    r = await box.ask(box.open().token, raw)
    assert r.status_code == 200
    assert box.provider.requests[0].content == raw  # spacing, escapes and marks untouched


# ---- tokens, cost and the limit --------------------------------------------------------------------


def test_cost_is_counted_from_the_price_list_with_both_kinds_of_cache_write():
    usage: dict[str, int] = {}
    anthropic_usage(
        {
            "input_tokens": 1000, "output_tokens": 500, "cache_read_input_tokens": 20000,
            "cache_creation_input_tokens": 3000,
            "cache_creation": {"ephemeral_5m_input_tokens": 2000, "ephemeral_1h_input_tokens": 1000},
        },
        usage,
    )  # fmt: skip
    # 1000 x 2 + 500 x 10 + 20000 x 0.1 + 2000 x 2.5 + 1000 x 4, per million
    assert cost_of(usage, CLOUD.price) == pytest.approx(0.018)
    assert cost_of(usage, {}) == 0.0  # a model on this computer costs nothing


async def test_each_call_writes_usage_events_and_adds_to_the_sessions_cost(box):
    box.provider.answer["usage"] = {
        "input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 900,
        "cache_creation_input_tokens": 50,
    }  # fmt: skip
    await box.ask(box.open().token)
    kinds = {e.kind: e for e in box.usage.events}
    assert set(kinds) == {LLM_INPUT_TOKENS, LLM_OUTPUT_TOKENS}
    spent = kinds[LLM_INPUT_TOKENS]
    assert (spent.tenant_id, spent.product_id, spent.user_id) == ("t1", "wasifyai-code", "u1")
    assert spent.quantity == 1050 and kinds[LLM_OUTPUT_TOKENS].quantity == 20
    assert spent.meta["cached_tokens"] == 900 and spent.meta["session_id"] == "s1"
    assert spent.meta["capability"] == "code.agent" and spent.meta["alias"] == "cloud"
    expected = (100 * 2.0 + 20 * 10.0 + 900 * 0.1 + 50 * 2.5) / 1e6
    assert box.gateway.spent("s1")["usd"] == pytest.approx(expected, abs=1e-6)
    (call,) = box.calls
    assert call.session_id == "s1" and call.usd == pytest.approx(expected)
    assert (call.input_tokens, call.output_tokens) == (1050, 20)


async def test_a_session_at_its_limit_is_refused_in_words_and_the_refusal_is_remembered(box):
    box.provider.answer["usage"] = {"input_tokens": 400_000, "output_tokens": 0}  # $0.80 a call
    grant = box.open(limit_usd=1.0)
    assert (await box.ask(grant.token)).status_code == 200
    assert (await box.ask(grant.token)).status_code == 200  # the call that crosses the limit
    refused = await box.ask(grant.token)
    assert (
        refused.status_code == 429 and "cost limit of $1.00" in refused.json()["error"]["message"]
    )
    assert len(box.provider.requests) == 2
    assert "cost limit" in box.gateway.take_note("s1")["over_limit"]
    assert box.gateway.take_note("s1") == {}  # said once
    box.gateway.set_limit("s1", 5.0)
    assert (await box.ask(grant.token)).status_code == 200


async def test_what_was_spent_before_counts_towards_the_limit(box):
    grant = box.open(spent_usd=4.99, limit_usd=5.0)
    box.provider.answer["usage"] = {"input_tokens": 10_000, "output_tokens": 0}  # $0.02
    assert (await box.ask(grant.token)).status_code == 200
    assert (await box.ask(grant.token)).status_code == 429


async def test_counting_tokens_is_passed_on_and_costs_nothing(box):
    box.provider.answer = {"input_tokens": 1234}
    r = await box.http.post(
        "/coding-gateway/v1/messages/count_tokens", json={"model": "cloud-1", "messages": []},
        headers={"x-api-key": box.open().token},
    )  # fmt: skip
    assert r.json() == {"input_tokens": 1234}
    assert str(box.provider.requests[0].url).endswith("/v1/messages/count_tokens")
    assert box.usage.events == [] and box.gateway.spent("s1")["calls"] == 0


async def test_a_providers_error_is_passed_on_and_a_provider_that_is_down_is_said(box):
    box.provider.status = 529
    box.provider.answer = {
        "type": "error",
        "error": {"type": "overloaded_error", "message": "busy"},
    }
    r = await box.ask(box.open().token)
    assert r.status_code == 529 and r.json()["error"]["type"] == "overloaded_error"

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    box.gateway._http = httpx.AsyncClient(transport=httpx.MockTransport(down))
    r = await box.ask(box.open().token)
    assert r.status_code == 502 and "could not be reached" in r.json()["error"]["message"]


# ---- a refusal -----------------------------------------------------------------------------------


async def test_a_refusal_becomes_a_plain_message_that_ends_the_turn(box):
    box.provider.answer = {
        "id": "msg_2", "type": "message", "role": "assistant", "model": "cloud-1", "content": [],
        "stop_reason": "refusal",
        "stop_details": {"type": "refusal", "category": "cyber", "explanation": "I can't help with that."},
        "usage": {"input_tokens": 50, "output_tokens": 0},
    }  # fmt: skip
    r = await box.ask(box.open().token)
    answer = r.json()
    assert answer["stop_reason"] == "end_turn" and "stop_details" not in answer
    assert answer["content"] == [
        {"type": "text", "text": f"{DECLINED} I can't help with that."}
    ]  # no tool call: the Agent Server's turn ends here
    note = box.gateway.take_note("s1")
    assert note["refusal"] == {
        "message": f"{DECLINED} I can't help with that.",
        "category": "cyber",
    }
    assert box.calls[0].refused and box.gateway.take_note("s1") == {}


async def test_a_refusal_with_no_explanation_and_half_an_answer_is_still_a_plain_message(box):
    box.provider.answer = {
        "type": "message", "role": "assistant", "content": [{"type": "text", "text": "Sure, fir"}],
        "stop_reason": "refusal", "stop_details": None, "usage": {},
    }  # fmt: skip
    answer = (await box.ask(box.open().token)).json()
    assert answer["content"] == [{"type": "text", "text": DECLINED}]


async def test_a_streamed_refusal_becomes_one_more_text_block_and_an_ordinary_end(box):
    box.provider.stream = sse(
        {"type": "message_start", "message": {"id": "m", "usage": {"input_tokens": 70, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "refusal", "stop_details": {"type": "refusal", "category": "bio", "explanation": None}},
            "usage": {"output_tokens": 3},
        },
        {"type": "message_stop"},
    )  # fmt: skip
    r = await box.ask(box.open().token, {"model": "cloud-1", "stream": True, "messages": []})
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    kinds = [e["type"] for e in events]
    assert kinds == [
        "message_start", "content_block_start", "content_block_stop",
        "content_block_start", "content_block_delta", "content_block_stop",
        "message_delta", "message_stop",
    ]  # fmt: skip
    assert events[3]["index"] == 1 and events[3]["content_block"]["type"] == "text"
    assert events[4]["delta"] == {"type": "text_delta", "text": DECLINED}
    assert events[6]["delta"] == {"stop_reason": "end_turn"}
    assert box.gateway.take_note("s1")["refusal"]["category"] == "bio"
    assert box.gateway.spent("s1")["input_tokens"] == 70 and box.calls[0].refused


# ---- streaming -------------------------------------------------------------------------------------


async def test_a_stream_is_passed_through_event_for_event_and_its_tokens_are_counted(box):
    events = sse(
        {"type": "message_start", "message": {"id": "m", "usage": {"input_tokens": 30, "cache_read_input_tokens": 500, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hel"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 42}},
        {"type": "message_stop"},
    )  # fmt: skip
    # the provider's chunks do not end where events do
    whole = b"".join(events)
    box.provider.stream = [whole[:37], whole[37:210], whole[210:]]
    r = await box.ask(box.open().token, {"model": "cloud-1", "stream": True, "messages": []})
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.content == whole  # nothing added, nothing changed
    spent = box.gateway.spent("s1")
    assert (spent["input_tokens"], spent["output_tokens"]) == (530, 42)
    assert spent["usd"] == pytest.approx((30 * 2.0 + 500 * 0.1 + 42 * 10.0) / 1e6, abs=1e-6)


async def test_a_local_model_is_called_without_a_key_and_its_stream_reports_its_tokens(box):
    chunks = [
        b'data: {"choices":[{"index":0,"delta":{"content":"Hi"},"finish_reason":null}]}\n\n',
        b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n',
        b'data: {"choices":[],"usage":{"prompt_tokens":800,"completion_tokens":12}}\n\n',
        b"data: [DONE]\n\n",
    ]
    box.provider.stream = chunks
    grant = box.open("s2", "local")
    r = await box.http.post(
        "/coding-gateway/v1/chat/completions",
        json={"model": "local-1", "stream": True, "messages": []},
        headers={"authorization": f"Bearer {grant.token}"},
    )
    assert r.content == b"".join(chunks)
    sent = box.provider.requests[0]
    assert str(sent.url) == "http://127.0.0.1:1/v1/chat/completions"
    assert KEY not in str(sent.headers) and grant.token not in str(sent.headers)
    assert json.loads(sent.content)["stream_options"] == {"include_usage": True}
    spent = box.gateway.spent("s2")
    assert (spent["input_tokens"], spent["output_tokens"], spent["usd"]) == (800, 12, 0.0)
    assert {e.meta["provider"] for e in box.usage.events} == {"ollama"}


async def test_a_refusal_in_a_chat_completions_answer_is_a_plain_message_too(box):
    box.provider.answer = {
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": None, "refusal": "No."}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 1},
    }  # fmt: skip
    grant = box.open("s2", "local")
    r = await box.http.post(
        "/coding-gateway/v1/chat/completions", json={"model": "local-1", "messages": []},
        headers={"authorization": f"Bearer {grant.token}"},
    )  # fmt: skip
    assert r.json()["choices"][0]["message"]["content"] == f"{DECLINED} No."
    assert box.gateway.take_note("s2")["refusal"]["message"] == f"{DECLINED} No."


# ---- the list of models ----------------------------------------------------------------------------


def test_the_shipped_list_names_sonnet_first_and_the_local_model_second():
    default, models = load_models(ollama_url="http://127.0.0.1:11434")
    assert default == "claude-sonnet-5-5"
    first = models[default]
    assert first.shape == ANTHROPIC and first.secret == "keys.chat.anthropic"
    assert first.upstream == "https://api.anthropic.com" and first.price["output"] == 10.0
    local = models["qwen-27b-ollama"]
    assert local.shape == OPENAI and local.secret == "" and local.price == {}
    assert local.upstream == "http://127.0.0.1:11434/v1"
