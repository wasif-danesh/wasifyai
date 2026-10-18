"""Stub runner (COMFYUI_MODE=stub): placeholder files and simulated progress, no GPU or models.
For UI work and laptops that cannot run the real models."""

import asyncio
import hashlib
import struct
import tempfile
import zlib
from pathlib import Path

from wasifyai_media_worker.comfy import ProgressFn


def placeholder_png(seed: str, size: int = 256) -> bytes:
    """A deterministic gradient, so repeated jobs differ and are recognisable."""
    h = hashlib.sha256(seed.encode()).digest()
    r0, g0, b0 = h[0], h[1], h[2]
    rows = b"".join(
        b"\x00" + b"".join(bytes(((r0 + x) % 256, (g0 + y) % 256, b0)) for x in range(size))
        for y in range(size)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


async def placeholder_mp4(seconds: float = 3.0) -> bytes:
    """A small test-pattern clip with a tone, made by ffmpeg, so graphs that read a video (the
    poster, the size) work without a model."""
    import imageio_ffmpeg

    with tempfile.TemporaryDirectory(prefix="wasifyai-stub-") as tmp:
        out = Path(tmp) / "stub.mp4"
        proc = await asyncio.create_subprocess_exec(
            imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size=320x320:rate=25:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
        await proc.wait()
        return out.read_bytes() if out.exists() else b""


async def run_stub(
    job_id: str, outputs: dict[str, dict], on_progress: ProgressFn, steps: int = 5
) -> dict[str, tuple[bytes, str, str]]:
    """Returns {output name: (bytes, content type, extension)}."""
    for i in range(1, steps + 1):
        await asyncio.sleep(0.1)
        await on_progress(i / steps)
    made: dict[str, tuple[bytes, str, str]] = {}
    for name, spec in outputs.items():
        kind = spec.get("type", "image")
        if kind == "video":
            made[name] = (await placeholder_mp4(), "video/mp4", "mp4")
        else:
            made[name] = (placeholder_png(job_id), "image/png", "png")
    return made
