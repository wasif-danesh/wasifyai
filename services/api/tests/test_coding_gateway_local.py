"""The coding gateway's model on this computer: the language model chosen in the Model hub
(docs/coding-local-model-plan.md, LM1; what the model button is told of it, LM2). A file runs
in the app's own llama-server (pretended here) at a context of at least 32,768 with the speed
options, and holds the model slot for the call; a model of a running Ollama is called where it
is, by its own name. Either way the call goes out with the model's "thinking off" switch."""

import json
import struct
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from wasifyai_api.coding_gateway import (
    LOCAL_TITLE,
    CodingGateway,
    LocalNotes,
    load_local,
    router,
)
from wasifyai_api.desktop_fit import Machine
from wasifyai_api.desktop_language import (
    CHOOSE_FIRST,
    CODING_CONTEXT,
    NOT_SET_UP,
    LanguageService,
    Selection,
    speed_args,
)
from wasifyai_api.llama_server import LlamaServer
from wasifyai_api.services import ApiServices
from wasifyai_api.settings_store import InMemorySettingsStore
from wasifyai_platform_sdk.secrets import InMemorySecretStore
from wasifyai_platform_sdk.usage import InMemoryUsageRecorder

LOCAL_ID = "this-computer"


class FakeLlama:
    """The app's own llama-server, pretended: what it was asked to run, and an address."""

    def __init__(self, installed: bool = True) -> None:
        self.installed = installed
        self.install = None
        self.started: list[dict[str, Any]] = []

    async def ensure_running(self, model: Path, **how: Any) -> str:
        self.started.append({"model": model, **how})
        return "http://127.0.0.1:7777"

    async def stop(self) -> bool:
        return False


class FakeSlot:
    """The model slot: whether a call holds it now, and how often it was taken."""

    def __init__(self) -> None:
        self.held = 0
        self.taken = 0

    @asynccontextmanager
    async def hold(self, owner: str):
        assert owner == "chat"
        self.held += 1
        self.taken += 1
        try:
            yield
        finally:
            self.held -= 1


class Box:
    def __init__(self, selected: Selection | None, llama: FakeLlama | None = None) -> None:
        self.llama = llama or FakeLlama()
        self.language = LanguageService(InMemorySettingsStore(), self.llama)  # type: ignore[arg-type]
        self.language.selected = selected
        self.language.slot = self.slot = FakeSlot()
        self.sent: list[httpx.Request] = []
        self.stream: list[bytes] | None = None
        self.usage = InMemoryUsageRecorder()
        self.gateway = CodingGateway(
            secrets=InMemorySecretStore(), usage=self.usage,
            base_url=lambda: "http://127.0.0.1:4321", language=self.language,
            transport=httpx.MockTransport(self.answer),
        )  # fmt: skip
        app = FastAPI()
        app.state.services = ApiServices(coding_gateway=self.gateway)
        app.include_router(router)
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
        )

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        assert self.slot.held == (1 if getattr(self.language.selected, "kind", "") == "file" else 0)
        if self.stream is not None:
            parts = list(self.stream)

            async def chunks():
                for part in parts:
                    yield part

            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=chunks()
            )
        said = {"role": "assistant", "content": "Hi"}
        return httpx.Response(
            200,
            json={
                "choices": [{"index": 0, "finish_reason": "stop", "message": said}],
                "usage": {"prompt_tokens": 900, "completion_tokens": 7},
            },
        )

    async def ask(self, body: dict[str, Any] | None = None, session: str = "s1"):
        grant = self.gateway.open(
            tenant_id="t1", product_id="wasifyai-code", user_id="u1", session_id=session,
            model=LOCAL_ID,
        )  # fmt: skip
        body = {"model": "local", "messages": []} if body is None else body
        return await self.http.post(
            "/coding-gateway/v1/chat/completions", json=body,
            headers={"authorization": f"Bearer {grant.token}"},
        )  # fmt: skip

    async def close(self) -> None:
        await self.http.aclose()
        await self.gateway.close()


@pytest.fixture
async def boxes():
    made: list[Box] = []

    def make(selected: Selection | None, **more: Any) -> Box:
        made.append(Box(selected, **more))
        return made[-1]

    yield make
    for b in made:
        await b.close()


def file_choice(path: Path, **more: Any) -> Selection:
    return Selection("file", "Qwen3.8 27B", 8192, path=str(path), thinking=True, **more)


OLLAMA = Selection(
    "server", "qwen3.8:27b-mlx (ollama)", 8192, tool="ollama", url="http://127.0.0.1:11434",
    model="qwen3.8:27b-mlx", thinking=True,
)  # fmt: skip


def gguf(path: Path, arch: str, **ints: int) -> Path:
    """A GGUF header with the architecture and the given whole-number keys, and no tensors."""

    def text(s: str) -> bytes:
        return struct.pack("<Q", len(s.encode())) + s.encode()

    keys = text("general.architecture") + struct.pack("<I", 8) + text(arch)
    for key, value in ints.items():
        keys += text(f"{arch}.{key}") + struct.pack("<I", 4) + struct.pack("<I", value)
    path.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, 1 + len(ints)) + keys)
    return path


# ---- the list ------------------------------------------------------------------------------------


def test_the_file_says_how_the_agent_server_names_the_local_model():
    local = load_local()
    assert local is not None and local.local and local.id == LOCAL_ID
    assert (local.engine_model, local.provider_model) == ("openai/local", "local")
    assert local.secret == "" and local.price == {} and local.where == "this-computer"
    assert local.engine_settings["native_tool_calling"] is True
    assert local.engine_settings["max_input_tokens"] == 24000


async def test_without_the_language_service_no_local_model_is_offered():
    gateway = CodingGateway(
        secrets=InMemorySecretStore(), usage=InMemoryUsageRecorder(), base_url=lambda: "x"
    )
    try:
        assert LOCAL_ID not in [m["id"] for m in await gateway.list_models()]
    finally:
        await gateway.close()


async def test_nothing_chosen_is_listed_not_ready_and_a_call_says_so(boxes):
    box = boxes(None)
    models = await box.gateway.list_models()
    local = next(m for m in models if m["id"] == LOCAL_ID)
    assert (local["title"], local["ready"], local["where"]) == (LOCAL_TITLE, False, "this-computer")
    assert [m["id"] for m in models] == ["claude-sonnet-5-5", "claude-haiku-5-5", LOCAL_ID]
    assert await box.gateway.ready(LOCAL_ID) == CHOOSE_FIRST
    r = await box.ask()
    assert r.status_code == 503 and "No language model is chosen" in r.text
    assert box.sent == [] and box.slot.taken == 0


async def test_the_chosen_model_is_listed_by_its_own_name(boxes, tmp_path):
    box = boxes(file_choice(gguf(tmp_path / "q.gguf", "qwen35")))
    local = next(m for m in await box.gateway.list_models() if m["id"] == LOCAL_ID)
    assert local["title"] == "Qwen3.8 27B on this computer" and local["ready"] is True
    assert local["price"] == "" and local["counted_in"] == "usd"


async def test_the_button_is_told_why_not_and_where_it_is_put_right(boxes, tmp_path):
    rows = {m["id"]: m for m in await boxes(None).gateway.list_models()}
    assert (rows[LOCAL_ID]["why"], rows[LOCAL_ID]["fix"]) == (CHOOSE_FIRST, "models")
    assert rows[LOCAL_ID]["model_name"] == "" and rows["claude-sonnet-5-5"]["why"] != ""
    box = boxes(file_choice(gguf(tmp_path / "q.gguf", "qwen3")), llama=FakeLlama(installed=False))
    local = next(m for m in await box.gateway.list_models() if m["id"] == LOCAL_ID)
    assert (local["why"], local["fix"], local["ready"]) == (NOT_SET_UP, "settings", False)
    box = boxes(file_choice(tmp_path / "gone.gguf"))
    local = next(m for m in await box.gateway.list_models() if m["id"] == LOCAL_ID)
    assert "no longer on this computer" in local["why"] and local["fix"] == "models"


async def test_a_model_too_big_at_the_coding_context_is_sent_to_the_model_hub(boxes, tmp_path):
    model = gguf(tmp_path / "q.gguf", "qwen3", block_count=64, context_length=40960)
    model.write_bytes(model.read_bytes() + b"\0" * 4096)
    box = boxes(file_choice(model))

    async def small() -> Machine:
        return Machine("unified", total_bytes=2048, available_bytes=1024)

    box.language.machine = small  # type: ignore[method-assign]
    local = next(m for m in await box.gateway.list_models() if m["id"] == LOCAL_ID)
    assert (
        local["why"].startswith("Coding needs a context of 32,768 tokens")
        and local["fix"] == "models"
    )

    async def big() -> Machine:
        return Machine("unified", total_bytes=64 * 10**9, available_bytes=48 * 10**9)

    box.language.machine = big  # type: ignore[method-assign]
    local = next(m for m in await box.gateway.list_models() if m["id"] == LOCAL_ID)
    assert local["ready"] is True and local["why"] == "" and local["memory_bytes"] > 0


async def test_the_measured_model_is_tested_and_a_small_one_may_not_manage(boxes, tmp_path):
    long = gguf(tmp_path / "q.gguf", "qwen3", context_length=40960)
    local = next(
        m for m in await boxes(file_choice(long)).gateway.list_models() if m["id"] == LOCAL_ID
    )
    assert (local["tested"], local["measured"], local["weak"]) == (True, "33 of 36 tasks", False)
    small = Selection("file", "Qwen3 8B", 8192, path=str(long), thinking=True)
    local = next(m for m in await boxes(small).gateway.list_models() if m["id"] == LOCAL_ID)
    assert (local["tested"], local["measured"], local["weak"]) == (False, "", True)
    # a model whose own longest context is under the coding context may not manage either
    short = gguf(tmp_path / "s.gguf", "llama", context_length=8192)
    other = Selection("file", "Some 70B", 8192, path=str(short), thinking=False)
    local = next(m for m in await boxes(other).gateway.list_models() if m["id"] == LOCAL_ID)
    assert local["weak"] is True
    # an Ollama model is matched on its own name
    local = next(m for m in await boxes(OLLAMA).gateway.list_models() if m["id"] == LOCAL_ID)
    assert local["measured"] == "33 of 36 tasks" and local["model_name"].startswith("qwen3.8")


def test_names_are_matched_with_the_words_joined():
    notes = LocalNotes({"qwen3.8-27b": "33 of 36 tasks"}, ("qwen3-8b",))
    for name in ("Qwen3.8 27B", "Qwen3.8-27B-Q4_0.gguf", "qwen3.8:27b-mlx"):
        assert notes.result(name) == "33 of 36 tasks"
    for name in ("Qwen3 8B", "Qwen3-8B-Q4_K_M.gguf", "qwen3:8b"):
        assert notes.is_weak(name) and not notes.result(name)
    assert not notes.is_weak("qwen3-80b") and not notes.is_weak("Qwen3.8 27B")


# ---- a model of a running Ollama ---------------------------------------------------------------


async def test_a_model_of_ollama_is_called_where_it_is_by_its_own_name_with_thinking_off(boxes):
    box = boxes(OLLAMA)
    r = await box.ask({"model": "local", "messages": [], "tools": []})
    assert r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "Hi"
    sent = box.sent[0]
    assert str(sent.url) == "http://127.0.0.1:11434/v1/chat/completions"
    body = json.loads(sent.content)
    assert body["model"] == "qwen3.8:27b-mlx"
    assert (body["think"], body["reasoning_effort"]) == (False, "low")
    assert sent.headers["authorization"] == "Bearer none"
    assert box.llama.started == [] and box.slot.taken == 0  # nothing of the app's own is started
    assert (box.gateway.spent("s1")["input_tokens"], box.gateway.spent("s1")["usd"]) == (900, 0.0)
    assert {e.meta["provider"] for e in box.usage.events} == {"this-computer"}


async def test_only_the_local_name_is_let_through(boxes):
    box = boxes(OLLAMA)
    r = await box.ask({"model": "qwen3.8:27b-mlx", "messages": []})
    assert r.status_code == 400 and box.sent == []


# ---- a file in the app's own llama-server ------------------------------------------------------


async def test_a_file_runs_at_the_coding_context_with_the_speed_options_and_thinking_off(
    boxes, tmp_path
):
    model = gguf(tmp_path / "q.gguf", "qwen35", nextn_predict_layers=1)
    box = boxes(file_choice(model, projector=str(tmp_path / "mmproj.gguf"), vision=True))
    (tmp_path / "mmproj.gguf").write_bytes(b"GGUF")
    body = {"model": "local", "messages": [], "chat_template_kwargs": {"keep": 1}}
    r = await box.ask(body)
    assert r.status_code == 200
    assert box.llama.started == [
        {
            "model": model,
            "context": CODING_CONTEXT,
            "extra_args": (),
            "at_least": True,
            "speed_args": ("--spec-type", "draft-mtp,ngram-mod"),
        }
    ]  # fmt: skip  (no picture reader: a coding session sends none)
    sent = box.sent[0]
    assert str(sent.url) == "http://127.0.0.1:7777/v1/chat/completions"
    got = json.loads(sent.content)
    assert got["model"] == "local"  # llama-server runs one model and ignores the name
    assert got["chat_template_kwargs"] == {"keep": 1, "enable_thinking": False}
    assert box.slot.taken == 1 and box.slot.held == 0  # held for the call, then let go


async def test_a_stream_holds_the_slot_until_its_end(boxes, tmp_path):
    box = boxes(file_choice(gguf(tmp_path / "q.gguf", "qwen3")))
    box.stream = [
        b'data: {"choices":[{"index":0,"delta":{"content":"Hi"},"finish_reason":null}]}\n\n',
        b'data: {"choices":[],"usage":{"prompt_tokens":800,"completion_tokens":12}}\n\n',
        b"data: [DONE]\n\n",
    ]
    r = await box.ask({"model": "local", "stream": True, "messages": []})
    assert r.status_code == 200 and r.content == b"".join(box.stream)
    assert box.slot.taken == 1 and box.slot.held == 0
    assert box.llama.started[0]["speed_args"] == ("--spec-type", "ngram-mod")  # no MTP layers
    assert box.gateway.spent("s1")["output_tokens"] == 12


async def test_a_model_the_app_cannot_reach_lets_the_slot_go(boxes, tmp_path):
    box = boxes(file_choice(gguf(tmp_path / "q.gguf", "qwen3")))

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    box.gateway._http = httpx.AsyncClient(transport=httpx.MockTransport(down))
    r = await box.ask()
    assert r.status_code == 502 and "could not be reached" in r.text
    assert box.slot.taken == 1 and box.slot.held == 0


async def test_a_taught_writing_model_runs_without_drafting(boxes, tmp_path):
    adapter = tmp_path / "style.safetensors"
    adapter.write_bytes(b"x")
    model = gguf(tmp_path / "q.gguf", "qwen35", nextn_predict_layers=1)
    box = boxes(file_choice(model, lora=str(adapter), style="mine"))
    await box.ask()
    assert box.llama.started[0]["extra_args"] == ("--lora", str(adapter))
    assert box.llama.started[0]["speed_args"] == ()


async def test_why_a_file_is_not_ready_is_said_in_words(boxes, tmp_path):
    box = boxes(file_choice(tmp_path / "gone.gguf"))
    assert "no longer on this computer" in (await box.gateway.ready(LOCAL_ID) or "")
    box = boxes(file_choice(gguf(tmp_path / "q.gguf", "qwen3")), llama=FakeLlama(installed=False))
    assert await box.gateway.ready(LOCAL_ID) == NOT_SET_UP


def test_drafting_uses_the_models_own_next_token_layers_when_it_has_them(tmp_path):
    with_mtp = gguf(tmp_path / "a.gguf", "qwen35", nextn_predict_layers=1)
    assert speed_args(with_mtp) == ("--spec-type", "draft-mtp,ngram-mod")
    assert speed_args(gguf(tmp_path / "b.gguf", "llama")) == ("--spec-type", "ngram-mod")
    (tmp_path / "c.gguf").write_bytes(b"not a gguf")
    assert speed_args(tmp_path / "c.gguf") == ("--spec-type", "ngram-mod")


# ---- llama-server: "at least this context" -----------------------------------------------------


def test_a_running_server_is_kept_for_a_smaller_context_and_for_a_caller_without_speed(tmp_path):
    server = LlamaServer(tmp_path)
    model = tmp_path / "m.gguf"
    speed = ("--spec-type", "ngram-mod")
    server._started_with = (model, 32768, False, (), speed)  # coding started it
    # chat at its own context, asking no speed options: the coding server will do
    assert server._serves((model, 8192, False, (), ()), at_least=True)
    # but not without "at least", nor with a picture reader, nor for another file
    assert not server._serves((model, 8192, False, (), ()), at_least=False)
    assert not server._serves((model, 8192, False, ("--mmproj", "p"), ()), at_least=True)
    assert not server._serves((tmp_path / "n.gguf", 8192, False, (), ()), at_least=True)
    # a larger context, or the speed options on a server started without them: started again
    server._started_with = (model, 8192, False, (), ())  # chat started it
    assert not server._serves((model, 32768, False, (), speed), at_least=True)
    assert not server._serves((model, 8192, False, (), speed), at_least=True)
    assert server._serves((model, 8192, False, (), ()), at_least=False)
