"""The wire format of speech jobs (ADR-0087): how a `SpeechEngine` call becomes an engine job's JSON
and back. The API (`RemoteSpeechEngine`) and the worker both import it, so they cannot disagree.

Audio, pictures and videos are files in object storage, named by key; everything else is JSON."""

import dataclasses
from typing import Any

from wasifyai_platform_sdk.voice_models import (
    ConvertRequest,
    LipSyncRequest,
    LipSyncResult,
    MusicEditRequest,
    MusicRequest,
    MusicResult,
    SeparateRequest,
    SeparateResult,
    SpeechEditRequest,
    SpeechResult,
    Stem,
    TranscriptResult,
    TranscriptSegment,
)

# job kinds: one per `SpeechEngine` method that does work
SPEAK = "speech.speak"
DESIGN = "speech.design"
CLONE = "speech.clone"
MUSIC = "speech.music"
MUSIC_EDIT = "speech.music_edit"
TRANSCRIBE = "speech.transcribe"
SEPARATE = "speech.separate"
CONVERT = "speech.convert"
SPEECH_EDIT = "speech.speech_edit"
LIPSYNC = "speech.lipsync"
KINDS = [
    SPEAK, DESIGN, CLONE, MUSIC, MUSIC_EDIT, TRANSCRIBE, SEPARATE, CONVERT, SPEECH_EDIT, LIPSYNC,
]  # fmt: skip

# the task a kind asks the engine to resolve a model for
TASK = {
    SPEAK: "speak", DESIGN: "design", CLONE: "clone", MUSIC: "music", MUSIC_EDIT: "music",
    TRANSCRIBE: "transcribe", SEPARATE: "separate", CONVERT: "convert", SPEECH_EDIT: "edit",
    LIPSYNC: "lipsync",
}  # fmt: skip


def request_json(request: Any) -> dict[str, Any]:
    """A request dataclass as JSON (tuples become lists)."""
    return dataclasses.asdict(request)


def music_request(d: dict[str, Any]) -> MusicRequest:
    return MusicRequest(**d)


def music_edit_request(d: dict[str, Any]) -> MusicEditRequest:
    return MusicEditRequest(**{**d, "ranges": tuple((float(a), float(b)) for a, b in d["ranges"])})


def separate_request(d: dict[str, Any]) -> SeparateRequest:
    return SeparateRequest(**d)


def convert_request(d: dict[str, Any]) -> ConvertRequest:
    return ConvertRequest(**d)


def speech_edit_request(d: dict[str, Any]) -> SpeechEditRequest:
    return SpeechEditRequest(**d)


def lipsync_request(d: dict[str, Any]) -> LipSyncRequest:
    # a job queued by an older engine may still carry `consent` and `mark`: they are not used now
    return LipSyncRequest(fps=int(d["fps"]), voice_seconds=float(d["voice_seconds"]))


# ---- results: the audio or video is a file, the rest is `meta` ---------------------------------


def speech_meta(r: SpeechResult) -> dict[str, Any]:
    return {k: v for k, v in dataclasses.asdict(r).items() if k != "wav"}


def speech_result(wav: bytes, meta: dict[str, Any]) -> SpeechResult:
    return SpeechResult(wav=wav, **meta)


def music_meta(r: MusicResult) -> dict[str, Any]:
    return {k: v for k, v in dataclasses.asdict(r).items() if k != "wav"}


def music_result(wav: bytes, meta: dict[str, Any]) -> MusicResult:
    return MusicResult(wav=wav, **meta)


def lipsync_meta(r: LipSyncResult) -> dict[str, Any]:
    return {k: v for k, v in dataclasses.asdict(r).items() if k != "mp4"}


def lipsync_result(mp4: bytes, meta: dict[str, Any]) -> LipSyncResult:
    return LipSyncResult(mp4=mp4, **meta)


def transcript_meta(r: TranscriptResult) -> dict[str, Any]:
    return dataclasses.asdict(r)


def transcript_result(meta: dict[str, Any]) -> TranscriptResult:
    segments = tuple(TranscriptSegment(**s) for s in meta["segments"])
    return TranscriptResult(**{**meta, "segments": segments})


def separate_meta(r: SeparateResult) -> dict[str, Any]:
    """The stems' names and numbers in order; their audio is the files `stem_0`, `stem_1`, ..."""
    return {
        "model_id": r.model_id,
        "load_s": r.load_s,
        "elapsed_s": r.elapsed_s,
        "stems": [
            {"name": s.name, "sample_rate": s.sample_rate, "seconds": s.seconds} for s in r.stems
        ],
    }


def separate_result(wavs: list[bytes], meta: dict[str, Any]) -> SeparateResult:
    stems = tuple(Stem(name=s["name"], wav=w, sample_rate=s["sample_rate"], seconds=s["seconds"])
                  for s, w in zip(meta["stems"], wavs, strict=True))  # fmt: skip
    return SeparateResult(
        stems=stems, model_id=meta["model_id"], load_s=meta["load_s"], elapsed_s=meta["elapsed_s"]
    )
