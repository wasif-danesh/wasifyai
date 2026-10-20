"""The one question Video Builder asks the chosen chat model (`VideoBuilderService.complete`): it
asks for an answer that follows a schema, turns thinking off, records the tokens, and says what
went wrong in words. The model is a stand-in; nothing is downloaded."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from wasifyai_api import desktop_video_builder as dvb
from wasifyai_platform_sdk import RunError
from wasifyai_platform_sdk.context import RunContext, reset_context, set_context

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}}


class Recorder:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def record(self, event: Any) -> None:
        self.events.append(event)


class FakeClient:
    seen: list[dict[str, Any]] = []
    behave = "ok"

    def __init__(self, **kw: Any) -> None:
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kw: Any) -> Any:
        FakeClient.seen.append(kw)
        if FakeClient.behave == "slow":
            await asyncio.sleep(5)
        if FakeClient.behave == "boom":
            raise ConnectionError("down")
        message = SimpleNamespace(content='{"a": "x"}')
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30),
        )


class FakeLanguage:
    def __init__(self, external: bool = False, tool: str = "") -> None:
        self.selected = SimpleNamespace(name="Gemma", tool=tool, thinking=True)
        self.external = external

    @asynccontextmanager
    async def session(self):
        yield SimpleNamespace(base_url="http://x/v1", model="m", external=self.external)


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(dvb, "AsyncOpenAI", FakeClient)
    FakeClient.seen = []
    FakeClient.behave = "ok"
    svc = dvb.VideoBuilderService(Path("/nonexistent"))
    svc.usage = Recorder()
    token = set_context(RunContext("t1", "wasifyai-video", "u1"))
    yield svc
    reset_context(token)


async def test_it_asks_for_the_schema_with_thinking_off_and_records_the_tokens(service):
    service.language = FakeLanguage()
    assert await service.complete("sys", "hello", SCHEMA) == '{"a": "x"}'
    sent = FakeClient.seen[0]
    assert sent["response_format"]["json_schema"]["schema"] == SCHEMA
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert sent["temperature"] == 0
    assert sent["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    assert sent["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert sorted((e.kind, e.quantity) for e in service.usage.events) == [
        ("llm.input_tokens", 120),
        ("llm.output_tokens", 30),
    ]
    assert {e.product_id for e in service.usage.events} == {"wasifyai-video"}


async def test_another_tools_model_that_can_think_is_told_to_think_little(service):
    service.language = FakeLanguage(external=True, tool="ollama")
    await service.complete("s", "p", SCHEMA)
    assert FakeClient.seen[0]["extra_body"] == {"think": False, "reasoning_effort": "low"}


async def test_without_a_model_it_says_so_and_a_failing_model_is_not_a_stack_trace(service):
    with pytest.raises(RunError, match="no language model"):
        await service.complete("s", "p", SCHEMA)
    service.language = FakeLanguage()
    FakeClient.behave = "boom"
    with pytest.raises(RunError, match="did not answer") as e:
        await service.complete("s", "p", SCHEMA)
    assert e.value.code == "language_failed" and "down" not in e.value.message


async def test_a_model_that_takes_too_long_is_stopped(service, monkeypatch):
    service.language = FakeLanguage()
    FakeClient.behave = "slow"
    real = asyncio.wait_for
    monkeypatch.setattr(dvb.asyncio, "wait_for", lambda coro, timeout: real(coro, 0.05))
    with pytest.raises(RunError, match="too long") as e:
        await service.complete("s", "p", SCHEMA)
    assert e.value.code == "language_timeout"


# ---- what is said when FFmpeg is missing ------------------------------------------------------


def test_without_ffmpeg_the_service_says_what_to_install_and_is_not_ready(monkeypatch, tmp_path):
    svc = dvb.VideoBuilderService(tmp_path)
    monkeypatch.setattr(dvb.vb, "platform_key", lambda: "darwin-arm64")
    monkeypatch.setattr(dvb.vb, "find_media_tools", lambda i=None: {"ffmpeg": "/x/ffmpeg"})
    monkeypatch.setattr(svc, "install", lambda: SimpleNamespace(source="managed"))  # it is there
    assert svc.ready() is False
    assert "brew install ffmpeg" in (svc.problem() or "")
    state = svc.state()
    assert state["installed"] is True
    assert state["tools"]["ready"] is False and "FFmpeg" in state["tools"]["message"]
    monkeypatch.setattr(
        dvb.vb, "find_media_tools", lambda i=None: {"ffmpeg": "/x", "ffprobe": "/y"}
    )
    assert svc.ready() is True and svc.problem() is None
    assert svc.state()["tools"] == {"ready": True, "message": ""}


def test_the_service_says_set_it_up_first_when_the_component_is_missing(monkeypatch, tmp_path):
    svc = dvb.VideoBuilderService(tmp_path)
    monkeypatch.setattr(dvb.vb, "platform_key", lambda: "darwin-arm64")
    monkeypatch.setattr(svc, "install", lambda: None)
    assert svc.problem() == "Video Builder is not set up yet. Set it up first."
