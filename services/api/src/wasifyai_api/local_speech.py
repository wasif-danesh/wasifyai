"""Speech on the web profile from the models on the machine the service runs on (W5 b to e).

`VOICE_ENGINE` picks what answers `app.state.audio`: `hosted` (the gateway's speech and
transcription routes, `hosted_speech.py`), `local` (the same runtime the desktop app uses, over the
models in `DESKTOP_DATA_DIR`), or `both`. A service on a Mac with the models downloaded by the
desktop app serves music, splitting, voice change, speech edit, dubbing, the audiobook and lip sync
to the web app this way, with no GPU host. Setting the runtime up or fetching a model stays with the
desktop app: the web only uses what is ready."""

from pathlib import Path
from typing import Any

from wasifyai_platform_sdk import (
    ConvertRequest,
    LipSyncRequest,
    MusicEditRequest,
    MusicRequest,
    SeparateRequest,
    SpeechEditRequest,
    VoiceEngineError,
    VoiceModel,
)

from wasifyai_api.audio_runtime import AudioEngine, AudioInstaller, AudioServer
from wasifyai_api.config import Settings
from wasifyai_api.desktop_models import ModelsService, load_catalogue
from wasifyai_api.lipsync_runtime import LipSyncSidecar
from wasifyai_api.settings_store import InMemorySettingsStore

HOSTED = "remote"  # the `engine` of a hosted model's descriptor


def build_local_engine(settings: Settings, products: Path) -> AudioEngine:
    """The desktop's speech runtime over the models in the data folder. The image engine's music
    models (ComfyUI) are not part of it: they need the image engine's memory slot."""
    models = ModelsService(
        load_catalogue(products, ["wasifyai-voice"]),
        settings.models_dir,
        settings.extra_model_dirs,
        InMemorySettingsStore(),
    )
    audio = AudioEngine(
        settings.desktop_dir,
        models,
        AudioInstaller(settings.desktop_dir),
        AudioServer(settings.desktop_dir),
        None,
        LipSyncSidecar(settings.desktop_dir),
    )
    models.audio = audio
    return audio


class CombinedSpeechEngine:
    """The local runtime and the hosted models behind one `SpeechEngine`. A model belongs to the
    hosted engine when its descriptor says `engine: remote`; every other call goes to the local
    one."""

    def __init__(self, local: Any, hosted: Any):
        self.local = local
        self.hosted = hosted

    # ---- what is offered ---------------------------------------------------------------------

    def models(self, task: str | None = None) -> list[dict[str, Any]]:
        return [*self.local.models(task), *self.hosted.models(task)]

    def resolve(self, task: str, model_id: str | None) -> VoiceModel:
        if model_id:
            hosted_ids = {m["id"] for m in self.hosted.models()}
            return (self.hosted if model_id in hosted_ids else self.local).resolve(task, model_id)
        try:
            return self.local.resolve(task, None)
        except VoiceEngineError as local_error:
            try:
                return self.hosted.resolve(task, None)
            except VoiceEngineError:
                raise local_error from None

    def _engine(self, model: VoiceModel) -> Any:
        return self.hosted if model.engine == HOSTED else self.local

    # ---- the runtime -------------------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        return self.local.state()

    @property
    def lipsync_sidecar(self) -> Any:
        return self.local.lipsync_sidecar

    async def stop(self) -> bool:
        """Give the local models' memory back (the hosted ones hold none)."""
        return await self.local.stop()

    async def close(self) -> None:
        await self.hosted.stop()
        local_close = getattr(self.local, "close", None)
        if local_close is not None:  # a remote engine closes itself
            await local_close()
            return
        await self.local.server.close()
        if self.local.lipsync_sidecar is not None:
            await self.local.lipsync_sidecar.close()

    # ---- the work ----------------------------------------------------------------------------

    async def speak(
        self,
        model: VoiceModel,
        text: str,
        voice: str | None,
        options: dict[str, Any],
        *,
        beside: bool = False,
    ):
        return await self._engine(model).speak(model, text, voice, options, beside=beside)

    async def design(self, model: VoiceModel, text: str, description: str, options: dict[str, Any]):
        return await self._engine(model).design(model, text, description, options)

    async def clone(
        self,
        model: VoiceModel,
        text: str,
        reference: Path,
        reference_text: str | None,
        options: dict[str, Any],
    ):
        return await self._engine(model).clone(model, text, reference, reference_text, options)

    async def music(self, model: VoiceModel, request: MusicRequest):
        return await self._engine(model).music(model, request)

    async def music_edit(self, model: VoiceModel, request: MusicEditRequest, source: Path):
        return await self._engine(model).music_edit(model, request, source)

    async def transcribe(
        self, model: VoiceModel, wav: bytes, options: dict[str, Any], *, beside: bool = False
    ):
        return await self._engine(model).transcribe(model, wav, options, beside=beside)

    async def separate(self, model: VoiceModel, request: SeparateRequest, source: Path):
        return await self._engine(model).separate(model, request, source)

    async def convert(
        self, model: VoiceModel, request: ConvertRequest, source: Path, reference: Path
    ):
        return await self._engine(model).convert(model, request, source, reference)

    async def speech_edit(self, model: VoiceModel, request: SpeechEditRequest, source: Path):
        return await self._engine(model).speech_edit(model, request, source)

    async def lipsync(self, model: VoiceModel, request: LipSyncRequest, picture: Path, voice: Path):
        return await self._engine(model).lipsync(model, request, picture, voice)
