"""Audio and video uploads (ADR-0043): an untrusted file in, a clean 16 kHz mono WAV out.

The file is never trusted. Its type is decided by its first bytes, never by its name or the type the
client declared, and ffmpeg is told to read exactly that type (it never guesses another format). It
is decoded in a child process with a time limit and, where the system allows it, a memory limit;
only the `file` protocol is allowed, so nothing can fetch a URL, and the one path it can open is a
private temporary copy (an MP4 recorded on a phone keeps its index at the end, so it cannot be
streamed through a pipe). Only the audio comes out: the video track, subtitles, data streams and
every tag are dropped, and the original bytes are not kept."""

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass

from wasifyai_platform_sdk.uploads import UploadError

RATE = 16_000
DECODE_TIMEOUT_S = 120
MEMORY_LIMIT = 2 * 1024**3
# the container types we accept, from the first bytes of the file
_SIGNATURES: tuple[tuple[str, bytes, int], ...] = (
    ("wav", b"RIFF", 0),
    ("ogg", b"OggS", 0),
    ("flac", b"fLaC", 0),
    ("mp3", b"ID3", 0),
    ("matroska", b"\x1a\x45\xdf\xa3", 0),  # WebM and Matroska
    ("mp4", b"ftyp", 4),  # MP4, M4A, MOV
)


# the ffmpeg demuxer to use for each container we sniffed
_DEMUXER = {
    "wav": "wav",
    "ogg": "ogg",
    "flac": "flac",
    "mp3": "mp3",
    "matroska": "matroska,webm",
    "mp4": "mov,mp4,m4a,3gp,3g2,mj2",
}


@dataclass(frozen=True)
class ProcessedAudio:
    wav: bytes
    seconds: float
    container: str


def sniff(data: bytes) -> str | None:
    """The container type from the leading bytes, or None when it is not one we accept."""
    head = data[:16]
    for name, magic, offset in _SIGNATURES:
        if head[offset : offset + len(magic)] == magic:
            if name == "wav" and data[8:12] != b"WAVE":
                return None
            return name
    if len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:  # a bare MP3 frame
        return "mp3"
    return None


def _limits() -> None:  # pragma: no cover - runs in the child before ffmpeg starts
    import resource  # Unix only, so imported here: this module must load on Windows (desktop app)

    try:
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, MEMORY_LIMIT))
        resource.setrlimit(resource.RLIMIT_CPU, (DECODE_TIMEOUT_S, DECODE_TIMEOUT_S))
    except (ValueError, OSError):
        pass


def decode(data: bytes, max_seconds: int, container: str = "wav") -> bytes:
    """ffmpeg: the file's audio as 16 kHz mono 16-bit WAV, at most max_seconds + 1 long."""
    import imageio_ffmpeg

    with tempfile.TemporaryDirectory(prefix="wasifyai-upload-") as folder:
        path = os.path.join(folder, "input")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        cmd = [
            imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-protocol_whitelist", "file", "-f", _DEMUXER[container], "-i", path,
            "-vn", "-sn", "-dn", "-map_metadata", "-1", "-fflags", "+bitexact", "-map", "0:a:0",
            "-ac", "1", "-ar", str(RATE), "-t", str(max_seconds + 1), "-f", "wav", "pipe:1",
        ]  # fmt: skip
        try:
            done = subprocess.run(  # noqa: S603 - fixed argument list, a private temporary file
                cmd,
                capture_output=True,
                timeout=DECODE_TIMEOUT_S,
                cwd=folder,
                preexec_fn=_limits if sys.platform.startswith("linux") else None,  # noqa: PLW1509
            )
        except subprocess.TimeoutExpired:
            raise UploadError(422, "That file took too long to read. Try a shorter one.") from None
    if done.returncode != 0 or len(done.stdout) < 100:
        raise UploadError(422, "That file could not be read as audio.")
    return done.stdout


def wav_seconds(wav: bytes) -> float:
    """The length of ffmpeg's WAV. It streams the file, so the header's length field is unknown:
    count the sample bytes after the `data` chunk instead."""
    start = wav.find(b"data", 0, 200)
    body = len(wav) - (start + 8 if start >= 0 else 44)
    return max(0, body) / (RATE * 2)


def with_sizes(wav: bytes) -> bytes:
    """The same WAV with its header lengths filled in (ffmpeg streams it with them unknown), so
    every reader, including Python's `wave`, can open it."""
    start = wav.find(b"data", 0, 200)
    if start < 0:
        return wav
    riff = (len(wav) - 8).to_bytes(4, "little")
    body = (len(wav) - (start + 8)).to_bytes(4, "little")
    return wav[:4] + riff + wav[8 : start + 4] + body + wav[start + 8 :]


def process_audio(data: bytes, max_seconds: int = 1800) -> ProcessedAudio:
    """The clean WAV that is stored in place of the upload."""
    container = sniff(data)
    if container is None:
        raise UploadError(
            415, "Please upload an audio or video file (MP3, WAV, M4A, MP4, WebM...)."
        )
    wav = decode(data, max_seconds, container)
    seconds = wav_seconds(wav)
    if seconds > max_seconds:
        limit = f"{max_seconds // 60} minutes" if max_seconds >= 60 else f"{max_seconds} seconds"
        raise UploadError(422, f"That recording is longer than the limit of {limit}.")
    if seconds < 0.3:
        raise UploadError(422, "That recording is empty or too short.")
    return ProcessedAudio(with_sizes(wav), round(seconds, 2), container)
