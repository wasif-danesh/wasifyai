"""The speech aliases the web voice screens use (W5): seeded, and tested by their own routes."""

import httpx
import pytest
import yaml
from wasifyai_api.litellm_admin import LiteLLMBackend
from wasifyai_api.model_access import DEFAULTS_FILE


def backend(handler) -> LiteLLMBackend:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://gateway")
    return LiteLLMBackend("http://gateway", "key", client=client)


def test_the_defaults_name_both_aliases_the_hosted_models_use():
    aliases = yaml.safe_load(DEFAULTS_FILE.read_text())["aliases"]
    assert aliases["voice-speak"]["kind"] == "speech"
    assert aliases["voice-transcribe"]["kind"] == "transcription"


@pytest.mark.asyncio
async def test_a_speech_alias_is_tested_by_asking_for_a_word_spoken():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content
        return httpx.Response(200, content=b"RIFFxxxxWAVE")

    result = await backend(handler).call("voice-speak", "speech")
    assert result.ok and result.sample == "12 bytes"
    assert seen["path"] == "/v1/audio/speech" and b"voice-speak" in seen["body"]


@pytest.mark.asyncio
async def test_a_transcription_alias_is_tested_with_a_second_of_silence():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["size"] = len(request.content)
        return httpx.Response(200, json={"text": ""})

    result = await backend(handler).call("voice-transcribe", "transcription")
    assert result.ok
    assert seen["path"] == "/v1/audio/transcriptions" and seen["size"] > 32000


@pytest.mark.asyncio
async def test_a_provider_error_is_the_answer():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    result = await backend(handler).call("voice-speak", "speech")
    assert not result.ok and "bad key" in (result.error or "")
