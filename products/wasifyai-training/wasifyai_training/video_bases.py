# ruff: noqa: E501  (the notes beside each number read better on one line)
"""The video models taught with AI Toolkit, one recipe each (ADR-0097, stage MV5).

LTX-Video 2B is taught by the app's own diffusers trainer (`desktop_video_training.py`). The video models added by
ADR-0097 are taught the way AI Toolkit loads them, with its own defaults for each architecture (its `ui.tsx` at the
pinned commit): files AI Toolkit reads in ComfyUI's layout are found in the models folder (MODELS_PATH), so what
Create already keeps is not fetched again; the rest is pinned here (`hub`), fetched once by the setup and read
offline. A recipe not run on this computer says so (`measured=False`)."""

from dataclasses import dataclass, field

from wasifyai_training.picture_bases import MAC, NVIDIA, HubFiles


@dataclass(frozen=True)
class VideoBase:
    id: str  # the base's id in the descriptors (`bases.py`) and on a run and a model's card
    title: str
    model: str  # the video model's catalogue id (Create's files, found through MODELS_PATH)
    use_with: str
    arch: str  # AI Toolkit's `model.arch`
    name_or_path: str
    hub: tuple[HubFiles, ...] = ()
    extras: str = ""
    quantize: str = ""
    quantize_te: str = ""  # the text encoder's `qtype_te`; "" = not quantised
    model_kwargs: dict[str, object] = field(default_factory=dict)
    model_fields: dict[str, object] = field(default_factory=dict)
    train_fields: dict[str, object] = field(default_factory=dict)
    network_fields: dict[str, object] = field(default_factory=dict)
    dataset_fields: dict[str, object] = field(default_factory=dict)
    fps: int = 24
    frames: int = 49  # a clip's frames in a training window
    side: int = 512
    need_gb: float = 0.0
    seconds_per_step: float = 30.0
    devices: tuple[str, ...] = (MAC, NVIDIA)
    measured: bool = False
    note: str = ""

    @property
    def hub_bytes(self) -> int:
        return sum(h.bytes for h in self.hub)


_GUESS = (
    "Not measured on this computer yet: the time and memory are estimates from the model's size."
)

LTX_25 = VideoBase(
    id="ltx-2.5",
    title="LTX-2.5 (22B)",
    model="ltx-2.5",
    use_with="LTX-2.5",
    arch="ltx2.5",
    name_or_path="Lightricks/LTX-2.5",
    # the dev transformer is taught (Create runs the distilled one) and AI Toolkit's VAE has the conv decoder;
    # the text encoder and the audio VAE are Create's own files
    hub=(
        HubFiles(
            "Lightricks/LTX-2.5",
            "49b093a39c19169a8a81721dcc541e07e945232f",
            (
                "diffusion_models/ltx-2.5-22b-dev-transformer-comfy-int8-convrot.safetensors",
                "vae/ltx-2.5-video-vae-conv-bf16.safetensors",
            ),
            22_956_304_146,
            into_models=True,
        ),
    ),
    quantize="convrot8",
    quantize_te="convrot8",
    train_fields={"timestep_type": "weighted", "audio_loss_multiplier": 1.0},
    dataset_fields={"do_i2v": False, "do_audio": False, "fps": 24, "auto_frame_count": False},
    fps=24,
    frames=49,
    # a 30-step run through the app on 21 pictures at 512 pixels (2026-11-08, the owner's M5 Pro, 64 GB): 51.5 GB at
    # its highest, 206 s to load, about 19 s a step (12 to 28), a 674 MB adapter; clips (49 frames) were not measured,
    # so the time and memory below stay estimates for a set with clips
    need_gb=56.0,
    seconds_per_step=40.0,
    note="Learns a look, a motion or a subject from pictures and short clips. " + _GUESS,
)

WAN_22 = VideoBase(
    id="wan2.2-14b",
    title="Wan 2.2 14B",
    model="wan2.2-14b",
    use_with="Wan 2.2 14B",
    arch="wan22_14b",
    name_or_path="ai-toolkit/Wan2.2-T2V-A14B-Diffusers-bf16",
    hub=(
        HubFiles(
            "ai-toolkit/Wan2.2-T2V-A14B-Diffusers-bf16",
            "fe9c6303ddfdefcae7f06ec7fc7c244bada46cc3",
            ("*",),
            57_154_388_624,
        ),
        HubFiles(
            "ai-toolkit/umt5_xxl_encoder",
            "0dc787b18485f27e1eb5a678127868becc2401ef",
            ("*",),
            11_366_501_535,
        ),
        HubFiles(
            "ai-toolkit/wan2.1-vae", "1ec3f48e1ac74941bb0b9b61cb107de654c7af4b", ("*",), 253_809_469
        ),
    ),
    quantize="qfloat8",
    quantize_te="qfloat8",
    model_kwargs={"train_high_noise": True, "train_low_noise": True},
    train_fields={"timestep_type": "linear"},
    dataset_fields={"fps": 16},
    fps=16,
    frames=41,
    need_gb=80.0,
    seconds_per_step=60.0,
    # two 14B halves in 16-bit: far more memory than a Mac has for teaching; an NVIDIA card with 24 GB or more
    devices=(NVIDIA,),
    note="Learns a look, a motion or a subject from pictures and short clips. " + _GUESS,
)

MINIMAX_H3 = VideoBase(
    id="minimax-h3",
    title="MiniMax-H3",
    model="minimax-h3",
    use_with="MiniMax-H3",
    arch="minimax_h3",
    name_or_path="Comfy-Org/MiniMax-H3",
    # the transformer and the VAEs are Create's own files; AI Toolkit teaches with the 4-bit text encoder
    hub=(
        HubFiles(
            "Comfy-Org/MiniMax-H3",
            "54472221d27c695fca9621b0c3ed52f06c4af707",
            ("text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",),
            15_687_142_551,
            into_models=True,
        ),
        HubFiles(
            "ostris/minimax_h3_training_adapter",
            "647b94be639cfdc32b61a0c46e5ee7c8c08196f2",
            ("minimax_h3_training_adapter_v3.safetensors",),
            310_168_800,
        ),
    ),
    quantize="convrot8",
    quantize_te="nvfp4",
    model_fields={
        "assistant_lora_path": "ostris/minimax_h3_training_adapter/minimax_h3_training_adapter_v3.safetensors"
    },
    train_fields={
        "timestep_type": "shift",
        "audio_loss_multiplier": 1.0,
        "cache_text_embeddings": True,
    },
    network_fields={"network_kwargs": {"ignore_if_contains": ["adaln_proj"]}},
    dataset_fields={"do_i2v": False, "do_audio": False, "fps": 24, "auto_frame_count": True},
    fps=24,
    frames=39,
    need_gb=64.0,
    seconds_per_step=45.0,
    # its text encoder for teaching is 4-bit (nvfp4): only an NVIDIA card has that number format
    devices=(NVIDIA,),
    note="Learns a look, a motion or a subject from pictures and short clips. " + _GUESS,
)

VIDEO_BASES: dict[str, VideoBase] = {b.id: b for b in (LTX_25, WAN_22, MINIMAX_H3)}
