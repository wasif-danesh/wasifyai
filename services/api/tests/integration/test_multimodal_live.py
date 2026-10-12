"""Real Gemma 4 E4B through LiteLLM: image and audio inputs end to end, files loaded from
storage the way a graph does it."""

import struct
import zlib
from pathlib import Path

from wasifyai_platform_sdk import (
    InMemoryUsageRecorder,
    ProviderDeps,
    ScopedStorage,
    build_capabilities,
    load_product_config,
    memory_storage,
    part_from_file,
)

PRODUCTS = Path(__file__).resolve().parents[4] / "products"
FOX = (
    Path(__file__).parent / "fixtures" / "fox.wav"
)  # "The quick brown fox jumps over the lazy dog"


def solid_png(rgb: tuple[int, int, int], size: int = 64) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


async def test_image_and_audio_inputs_with_the_real_model(run_ctx, litellm_settings):
    s = litellm_settings
    usage = InMemoryUsageRecorder()
    storage = ScopedStorage(memory_storage())
    caps = build_capabilities(
        load_product_config(PRODUCTS, "hello", environ={}),
        ProviderDeps(
            PRODUCTS,
            usage=usage,
            litellm_base_url=s.litellm_base_url,
            litellm_api_key=s.litellm_api_key,
            storage=storage,
        ),
    )
    await storage.put("uploads/blue.png", solid_png((20, 40, 220)), "image/png")
    await storage.put("uploads/fox.wav", FOX.read_bytes(), "audio/wav")

    image = part_from_file("uploads/blue.png", await storage.get("uploads/blue.png"))
    colour = await caps.text.complete(
        "multimodal", "Answer in one word.", ["What single colour is this image?", image]
    )
    assert "blue" in colour.lower()

    audio = part_from_file("uploads/fox.wav", await storage.get("uploads/fox.wav"))
    heard = await caps.text.complete(
        "multimodal", "Transcribe exactly.", ["What is said in this audio?", audio]
    )
    assert "quick brown fox" in heard.lower()

    both = await caps.text.complete(
        "multimodal", "Be brief.", ["Colour, then words spoken:", image, audio]
    )
    assert "blue" in both.lower() and "fox" in both.lower()

    inputs = [e.meta.get("inputs") for e in usage.events if e.kind == "llm.input_tokens"]
    assert (
        {"images": 1} in inputs and {"audio": 1} in inputs and {"images": 1, "audio": 1} in inputs
    )
    # image tokens are billed inside the model's reported prompt tokens
    assert all(e.quantity > 0 for e in usage.events)
