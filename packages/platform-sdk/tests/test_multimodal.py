import base64
from types import SimpleNamespace
from typing import Any, cast

import pytest
from wasifyai_platform_sdk import (
    Audio,
    CapabilityBinding,
    Image,
    InMemoryUsageRecorder,
    InvalidInput,
    ProviderDeps,
    UnsupportedInput,
    build_capabilities,
    load_product_config,
    part_from_file,
)
from wasifyai_platform_sdk.parts import counts, modalities, to_openai_content
from wasifyai_platform_sdk.providers.litellm import LiteLLMTextProvider

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


def test_parts_validate_type_and_size():
    assert Image.from_bytes(PNG, "image/png").media_type == "image/png"
    with pytest.raises(InvalidInput, match="not accepted"):
        Image.from_bytes(PNG, "image/svg+xml")
    with pytest.raises(InvalidInput, match="limit"):
        Image.from_bytes(b"x" * (10 * 1024 * 1024 + 1), "image/png")
    with pytest.raises(InvalidInput):
        Audio.from_bytes(b"x", "ogg")
    with pytest.raises(InvalidInput, match="http"):
        Image.from_url("file:///etc/passwd")


def test_part_from_file_uses_the_extension():
    assert isinstance(part_from_file("uploads/a.PNG", PNG), Image)
    assert part_from_file("uploads/a.jpg", PNG).media_type == "image/jpeg"  # type: ignore[union-attr]
    assert part_from_file("clip.wav", b"RIFF").format == "wav"  # type: ignore[union-attr]
    with pytest.raises(InvalidInput, match="cannot tell"):
        part_from_file("notes.txt", b"hi")


def test_openai_content_shapes():
    assert to_openai_content("plain") == "plain"  # strings stay plain for compatibility
    content = cast(
        list[dict[str, Any]],
        to_openai_content(
            ["look", Image.from_bytes(PNG, "image/png"), Audio.from_bytes(b"RIFF", "wav")]
        ),
    )
    assert content[0] == {"type": "text", "text": "look"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert base64.b64decode(content[2]["input_audio"]["data"]) == b"RIFF"
    assert content[2]["input_audio"]["format"] == "wav"


def test_modalities_and_counts():
    prompt = ["x", Image.from_bytes(PNG, "image/png"), Image.from_url("https://e/x.png")]
    assert modalities(prompt) == {"text", "image"}
    assert counts(prompt) == {"images": 2, "audio": 0}
    assert modalities("just text") == {"text"}


def build(products, inputs):
    (products / "demo" / "product.yaml").write_text(
        "id: demo\ncapabilities:\n"
        f"  text.vision: {{ provider: fake, inputs: {inputs} }}\n"
        "  text.chat: { provider: fake }\n"
    )
    usage = InMemoryUsageRecorder()
    cfg = load_product_config(products, "demo", environ={})
    return build_capabilities(cfg, ProviderDeps(products, usage=usage)), usage


async def test_text_only_binding_rejects_images_early(products, ctx):
    caps, _ = build(products, "[text, image, audio]")
    with pytest.raises(UnsupportedInput, match=r"accepts \['text'\].*\['image'\]"):
        await caps.text.complete("chat", "", ["what is this", Image.from_bytes(PNG, "image/png")])


async def test_declared_modalities_are_accepted_and_counted(products, ctx):
    caps, usage = build(products, "[text, image]")
    await caps.text.complete("vision", "", ["what is this", Image.from_bytes(PNG, "image/png")])
    assert usage.events[0].meta["inputs"] == {"images": 1}
    with pytest.raises(UnsupportedInput, match="audio"):
        await caps.text.complete("vision", "", [Audio.from_bytes(b"RIFF", "wav")])


async def test_litellm_provider_sends_content_parts_and_records_inputs(ctx):
    sent = {}

    async def chunks():
        yield SimpleNamespace(
            usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content="Blue"))]
        )
        yield SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=300, completion_tokens=2), choices=[]
        )

    async def create(**kwargs):
        sent.update(kwargs)
        return chunks()

    usage = InMemoryUsageRecorder()
    provider = LiteLLMTextProvider("http://x", "k", usage)
    provider._client.chat.completions.create = create  # type: ignore[method-assign]
    binding = CapabilityBinding(provider="litellm", model="multimodal", inputs=["text", "image"])
    prompt = ["colour?", Image.from_bytes(PNG, "image/png")]

    out = [d async for d in provider.stream("text.multimodal", binding, "sys", prompt)]

    assert out == ["Blue"]
    user = sent["messages"][1]["content"]
    assert user[0] == {"type": "text", "text": "colour?"} and user[1]["type"] == "image_url"
    assert sent["model"] == "multimodal" and sent["stream_options"] == {"include_usage": True}
    kinds = {e.kind: e for e in usage.events}
    assert kinds["llm.input_tokens"].quantity == 300 and kinds["llm.output_tokens"].quantity == 2
    assert kinds["llm.input_tokens"].meta["inputs"] == {"images": 1}
