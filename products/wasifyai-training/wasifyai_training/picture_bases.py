# ruff: noqa: E501  (the measured notes beside each number read better on one line)
"""The picture models that can be taught, one recipe each (ADR-0073, amendments 2026-11-07).

Everything that differs from one picture model to the next lives here and nowhere else: the model files it is
taught from (the image model's own, as the Images screens keep them), what AI Toolkit calls its architecture,
the picture size, the steps, the measured time and memory, and the model it is used with in Create. A trainer
asks for the recipe of the run's base and reads from it; a base with no recipe cannot be taught.

The trainer is AI Toolkit (Ostris), the same on a Mac with Apple silicon and on a computer with an NVIDIA
graphics card: the owner's aim is that teaching works on every platform (2026-11-07). It writes an adapter in
the key names ComfyUI reads, so what it learns is used in Create as it is.

FLUX.2 klein 4B is taught from the image model's own files; its numbers come from the owner's character-lora run of
AI Toolkit on this Mac. The other models are taught the way AI Toolkit loads them, from their Hugging Face repos
(`hub`, pinned to a commit, fetched once by the setup and read offline), with AI Toolkit's own defaults for each
architecture (its `ui.tsx` at the pinned commit). A recipe not run on this computer says so (`measured=False`): its
time and memory are estimates from the model's size until a run measures them."""

from dataclasses import dataclass, field

MAC, NVIDIA = "mps", "cuda"  # where a recipe can be taught: AI Toolkit's device


@dataclass(frozen=True)
class HubFiles:
    """Files of a Hugging Face repository AI Toolkit reads for a recipe, pinned to a commit. The
    setup fetches them into the Hugging Face cache (beside the models); a run reads them offline."""

    repo: str
    revision: str  # a commit, never a branch
    patterns: tuple[str, ...] = ("*",)  # which files (fnmatch), as `allow_patterns`
    bytes: int = 0  # their size, said before they are fetched
    # True: fetched into the models folder in its ComfyUI layout (`diffusion_models/...`), where AI Toolkit
    # finds them through MODELS_PATH and Create can use them too; False: into the Hugging Face cache
    into_models: bool = False


@dataclass(frozen=True)
class PictureBase:
    id: str  # the base's id in the descriptors (`bases.py`) and on a run and a model's card
    title: str
    model: str  # the image model's catalogue id: its files are the ones taught
    use_with: str  # the model the image screens run that reads what it learns
    arch: str  # what AI Toolkit calls the architecture (`model.arch`)
    # which file of the image model is which part: transformer, text_encoder, vae
    files: dict[str, str] = field(default_factory=dict)
    need_gb: float = 0.0  # the most memory a run held when measured, the worst kind
    sides: dict[str, int] = field(default_factory=dict)  # the longest side of a picture, by kind
    seconds_per_step: dict[int, float] = field(default_factory=dict)  # by side
    presets: dict[str, int] = field(default_factory=dict)  # the fewest steps, by kind
    learning_rate: dict[str, float] = field(default_factory=dict)
    quantize: str = (
        ""  # AI Toolkit's `qtype` for the model and its text encoder; "" = not quantised
    )
    quantize_te: bool = True  # whether the text encoder is quantised too
    gradient_checkpointing: bool = False
    guidance: float = 3.5  # of the sample pictures
    sample_steps: int = 4
    note: str = ""
    # a recipe AI Toolkit loads from Hugging Face in its own layout: `name_or_path` (and
    # `extras_name_or_path`) are repos of `hub`, not the image model's `files`
    hub: tuple[HubFiles, ...] = ()
    name_or_path: str = ""
    extras: str = ""
    model_kwargs: dict[str, object] = field(default_factory=dict)
    # AI Toolkit's own defaults for the architecture, merged into its `model`, `train` and
    # `network` sections (`unconditional_lora_path`, `timestep_type`, `ignore_if_contains`, ...)
    model_fields: dict[str, object] = field(default_factory=dict)
    train_fields: dict[str, object] = field(default_factory=dict)
    # for one kind only ("style", ...), merged over `train_fields`
    kind_train_fields: dict[str, dict[str, object]] = field(default_factory=dict)
    network_fields: dict[str, object] = field(default_factory=dict)
    # (the name AI Toolkit looks for, a file it can use), both under the models folder: a link
    # lets AI Toolkit use a file already there instead of copying or fetching it again
    model_links: tuple[tuple[str, str], ...] = ()
    devices: tuple[str, ...] = (
        MAC,
        NVIDIA,
    )  # a recipe whose weights a Mac cannot load: NVIDIA only
    measured: bool = True  # False: the numbers are AI Toolkit's defaults, not measured here

    @property
    def hub_bytes(self) -> int:
        return sum(h.bytes for h in self.hub)

    def side_for(self, kind: str) -> int:
        return self.sides.get(kind, 512)

    def seconds_for(self, steps: int, kind: str) -> int:
        side = self.side_for(kind)
        per = self.seconds_per_step.get(side) or max(self.seconds_per_step.values(), default=10.0)
        return round(steps * per)


KLEIN_4B = PictureBase(
    id="flux2-klein-4b",
    title="FLUX.2 klein 4B",
    model="flux2-klein-4b",
    use_with="FLUX.2 klein 4B",
    arch="flux2_klein_4b",
    files={
        "transformer": "flux-2-klein-4b.safetensors",
        "text_encoder": "qwen_3_4b.safetensors",
        "vae": "flux2-vae.safetensors",
    },
    # 39.7 GB held by a run through the app at 512 pixels, the model and text encoder quantised to 8 bits
    # (convrot8), on the owner's M5 Pro, 64 GB (2026-11-07)
    need_gb=40.0,
    # the character-lora run taught at 512 pixels and drew Ena well in Create (2026-10-14); style and object
    # are taught at the same size until one is measured larger
    sides={"character": 512, "style": 512, "object": 512},
    # 500 steps at 512 pixels in about 41 minutes, the model load and four sample pictures every 100 steps
    # included, on the owner's M5 Pro, 64 GB (character-lora, 2026-10-14); a 30-step run through the app
    # learnt at 4.3 s a step (413 s in all with the load and ten samples, 2026-11-07)
    seconds_per_step={512: 4.9},
    # a character and an object bound their magic word in 150 to 200 steps on 10 to 15 pictures; a style learnt
    # the scenes it was shown by 250 steps (measured with mflux, 2026-10-25; the Ena run used 500)
    presets={"character": 200, "style": 250, "object": 150},
    # style at 4e-4: with shifted noise levels (below), 21 collage pictures at 1e-4 for 250 steps gave the palette and flat
    # shapes on new scenes in Create but washed out; 4e-4 for 300 steps gave torn paper on card on all four (2026-11-09)
    learning_rate={"character": 1e-4, "object": 1e-4, "style": 4e-4},
    quantize="convrot8",
    # a style: noise levels drawn as the sampler's own shifted schedule. AI Toolkit's default (sigmoid, centred on the
    # middle) barely trains the high noise levels where klein's four steps decide the look: a style taught with it never
    # left photographs (500 steps, 1e-4 and 4e-4, the distilled and the base weights; the loss at each noise level flat),
    # and the same run with "shift" drew the style in 300 steps. A character keeps the default: Ena taught with "shift"
    # (37 pictures, 500 steps) matched the sigmoid-taught Ena in a portrait and a saree but lost her on a rainy street
    # where the sigmoid one kept her (2026-11-09, ADR-0073 "Style recipe fixed")
    kind_train_fields={"style": {"timestep_type": "shift"}},
    note="The model Create image uses, taught as it is. Learns a character, a style or an object from 15 to 25 pictures.",
)

_SIDES = {"character": 512, "style": 512, "object": 512}
_RATE = {"character": 1e-4, "object": 1e-4, "style": 1e-4}
_PRESETS = {"character": 200, "style": 250, "object": 150}
_GUESS = (
    "Not measured on this computer yet: the time and memory are estimates from the model's size."
)

KLEIN_9B = PictureBase(
    id="flux2-klein-9b",
    title="FLUX.2 klein 9B",
    model="flux2-klein-9b",
    use_with="FLUX.2 klein 9B",
    arch="flux2_klein_9b",
    name_or_path="black-forest-labs/FLUX.2-klein-base-9B",
    hub=(
        HubFiles(
            "black-forest-labs/FLUX.2-klein-base-9B",
            "32773329fbe7e81a90ef971740e8ba4b0364ecf3",
            ("flux-2-klein-base-9b.safetensors",),
            18_157_185_168,
        ),
        HubFiles(
            "Qwen/Qwen3-8B",
            "b968826d9c46dd6066d109eabc6255188de91218",
            ("*.json", "*.safetensors", "merges.txt", "vocab.json"),
            16_397_431_693,
        ),
        HubFiles(
            "ai-toolkit/flux2_vae",
            "3f679cf232e6d91d28396522d9502c31e8f7ccbe",
            ("ae.safetensors", "*.json"),
            336_211_292,
        ),
    ),
    # 30.1 GB held by a 294-step style run through the app at 512 pixels with gradient checkpointing; without it
    # the trainer held 76 GB on the owner's 64 GB Mac and swapped, two minutes a step (2026-11-09)
    need_gb=32.0,
    sides=_SIDES,
    # 294 steps in 68 minutes, the model load and the sample pictures included, on the owner's M5 Pro, 64 GB
    # (2026-11-09)
    seconds_per_step={512: 13.9},
    presets=_PRESETS,
    # a style as on klein 4B, 4e-4 with shifted noise levels: 21 collage pictures at 1e-4 with "weighted" for 294 steps
    # drew torn paper in the trainer's own samples but only photographs in Create's 9B workflow; 4e-4 with "shift"
    # put new scenes on torn card at strength 1.0 and drew three of four as full collage at 1.5, photographs without
    # the word (2026-11-09)
    learning_rate={**_RATE, "style": 4e-4},
    quantize="convrot8",
    model_kwargs={"match_target_res": False},
    gradient_checkpointing=True,
    train_fields={"timestep_type": "weighted"},
    kind_train_fields={"style": {"timestep_type": "shift"}},
    measured=True,
    note="Sharper than klein 4B and slower to teach. Learns a character, a style or an object from 15 to 25 pictures. "
    "A style shows most at a strength of 1.5.",
)

FLUX3_KLEIN = PictureBase(
    id="flux3-image-klein",
    title="FLUX.3 Image Klein",
    model="flux3-image-klein",
    use_with="FLUX.3 Image Klein",
    arch="flux3",
    name_or_path="black-forest-labs/flux-3-image-klein-base",
    hub=(
        HubFiles(
            "black-forest-labs/flux-3-image-klein-base",
            "a83ce283b1daa2f3d782645ae7b06c8e73af1b41",
            # the VAE is FLUX.2's, which Create keeps (vae/flux2-vae.safetensors)
            ("model.safetensors", "config.json", "manifest.json", "modular_model_index.json"),
            11_076_960_398,
        ),
        HubFiles(
            "Qwen/Qwen3-VL-4B-Instruct",
            "ebb281ec70b05090aa6165b016eac8ec08e71b17",
            ("*.json", "*.safetensors", "merges.txt", "vocab.json"),
            8_887_284_080,
        ),
    ),
    # On the owner's M5 Pro, 64 GB, 512 pixels, through the app (2026-11-08): 10 steps with two
    # sample pictures every 2 steps in 1348 s, peak 51.5 GB, an 80 MB adapter; a learning step took
    # 4 to 11 s, each round of samples about 215 s.
    need_gb=52.0,
    sides=_SIDES,
    seconds_per_step={512: 7.0},  # the middle of the measured 4 to 11 s
    presets=_PRESETS,
    learning_rate=_RATE,
    quantize="convrot8",
    model_kwargs={"match_target_res": True},
    train_fields={"timestep_type": "shift"},
    # Create's int8 file is the step-distilled model, which is not taught: the base package's bf16
    # weights are. AI Toolkit looks for them under the repack's name in the models folder and would
    # otherwise copy the 11 GB file there; a link to the fetched file is enough. An adapter taught
    # on the base is used with the distilled model in Create, as klein's are.
    # AI Toolkit's text encoder loader looks for a ComfyUI file of Qwen3-VL 4B (not kept) and would
    # fetch one; given the fetched repo's folder it reads that instead
    model_fields={
        "te_name_or_path": "{models}/huggingface/hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots/"
        "ebb281ec70b05090aa6165b016eac8ec08e71b17",
    },
    model_links=(
        (
            "diffusion_models/flux3_image_klein_bf16.safetensors",
            "huggingface/hub/models--black-forest-labs--flux-3-image-klein-base/snapshots/"
            "a83ce283b1daa2f3d782645ae7b06c8e73af1b41/model.safetensors",
        ),
    ),
    guidance=3.5,
    sample_steps=28,
    note="Learns a character, a style or an object from 15 to 25 pictures.",
)

QWEN_IMAGE = PictureBase(
    id="qwen-image-2.1",
    title="Qwen-Image 2.1",
    model="qwen-image-2.1",
    use_with="Qwen-Image 2.1",
    arch="qwen_image_2",
    name_or_path="Comfy-Org/Qwen-Image-2.1",
    extras="Qwen/Qwen-Image-2.1",
    hub=(
        HubFiles(
            "Comfy-Org/Qwen-Image-2.1",
            "aacf31a6d48e707f352ecba714cee0680da3479b",
            (
                "diffusion_models/qwen_image_2.1_int8_convrot.safetensors",
                "text_encoders/qwen3vl_8b_int8_convrot.safetensors",
                "vae/qwen_image_2.1_vae_bf16.safetensors",
            ),
            17_283_091_112,
        ),
        HubFiles(
            "Qwen/Qwen-Image-2.1",
            "d26bb61231c349cf6b7896fa83353113880e1ba3",
            ("*.json", "processor/*", "scheduler/*", "text_encoder/*", "vae/*"),
            18_901_317_185,
        ),
    ),
    need_gb=56.0,
    sides=_SIDES,
    seconds_per_step={512: 12.0},
    presets=_PRESETS,
    learning_rate=_RATE,
    quantize="convrot8",  # the Comfy-Org weights are int8 convrot already
    model_kwargs={"rgba": False},
    train_fields={"timestep_type": "shift"},
    guidance=3.0,
    sample_steps=25,
    measured=False,
    note="Strong with writing in pictures. Learns a character, a style or an object from 15 to 25 pictures. "
    + _GUESS,
)

Z_IMAGE = PictureBase(
    id="z-image",
    title="Z-Image",
    model="z-image-turbo",
    use_with="Z-Image Turbo",
    arch="zimage:deturbo",
    name_or_path="ostris/Z-Image-De-Turbo",
    extras="Tongyi-MAI/Z-Image-Turbo",
    hub=(
        HubFiles(
            "ostris/Z-Image-De-Turbo",
            "9da355082d6374634080361054e712a08cc54af1",
            ("transformer/*",),
            12_309_923_425,
        ),
        HubFiles(
            "Tongyi-MAI/Z-Image-Turbo",
            "f332072aa78be7aecdf3ee76d5c247082da564a6",
            ("*.json", "scheduler/*", "text_encoder/*", "tokenizer/*", "vae/*"),
            8_228_614_645,
        ),
    ),
    # On the owner's M5 Pro, 64 GB, 512 pixels, the model and text encoder quantised to 8 bits (qfloat8):
    # learning alone held 21.0 GB, 5.8 s a step (10 steps in 130 s with the load, sampling off); the
    # app's own run, which draws two sample pictures every few steps, peaked at 50.5 GB and took
    # 1474 s for 10 steps with a sample every 2 (2026-11-08). The need is the app's run.
    need_gb=51.0,
    sides=_SIDES,
    seconds_per_step={512: 5.8},
    presets=_PRESETS,
    learning_rate=_RATE,
    quantize="qfloat8",
    train_fields={"timestep_type": "weighted"},
    guidance=3.0,
    sample_steps=25,
    note="Taught on the de-distilled model, used with the quick Turbo model. Learns a character, a style or an "
    "object from 15 to 25 pictures.",
)

HIDREAM_O1 = PictureBase(
    id="hidream-o1",
    title="HiDream-O1",
    model="hidream-o1",
    use_with="HiDream-O1",
    arch="hidream_o1",
    name_or_path="HiDream-ai/HiDream-O1-Image",
    hub=(
        HubFiles(
            "HiDream-ai/HiDream-O1-Image",
            "0b0901d99f200389e138c61946af1185f5f49a13",
            ("*",),
            35_246_982_415,
        ),
    ),
    need_gb=56.0,
    sides=_SIDES,
    seconds_per_step={512: 14.0},
    presets=_PRESETS,
    learning_rate=_RATE,
    quantize="qfloat8",
    quantize_te=False,
    model_kwargs={"noise_scale_inference": 8.0, "noise_scale": 8.0},
    train_fields={"timestep_type": "weighted", "max_loss": 1.0},
    network_fields={
        "network_kwargs": {"ignore_if_contains": ["lm_head", "patch_embed", "visual"]},
        "transformer_only": False,
    },
    measured=False,
    note="Learns a character, a style or an object from 15 to 25 pictures. " + _GUESS,
)

IDEOGRAM_4 = PictureBase(
    id="ideogram-4",
    title="Ideogram 4",
    model="ideogram-4",
    use_with="Ideogram 4",
    arch="ideogram4",
    name_or_path="ideogram-ai/ideogram-4-fp8",
    hub=(
        HubFiles(
            "ideogram-ai/ideogram-4-fp8",
            "ee79a7237b519f1402ceacf952f30c8a31ec5073",
            ("*",),
            27_549_627_282,
        ),
        HubFiles(
            "Qwen/Qwen3-VL-8B-Instruct",
            "0c351dd01ed87e9c1b53cbc748cba10e6187ff3b",
            ("*.json", "*.safetensors", "merges.txt", "vocab.json"),
            17_545_907_231,
        ),
        HubFiles(
            "ostris/ideogram_4_unconditional_lora",
            "f56068df89a06d6ab4668cd39f1aab45dcb300b6",
            ("ideogram_4_unconditional_lora_r16.safetensors",),
            108_966_368,
        ),
    ),
    need_gb=40.0,
    sides=_SIDES,
    seconds_per_step={512: 4.0},
    presets=_PRESETS,
    learning_rate=_RATE,
    quantize="qfloat8",
    model_fields={
        "unconditional_lora_path": "ostris/ideogram_4_unconditional_lora/ideogram_4_unconditional_lora_r16.safetensors"
    },
    train_fields={"timestep_type": "linear"},
    devices=(
        NVIDIA,
    ),  # its fp8 weights need an NVIDIA card: a Mac's graphics chip has no 8-bit floats
    measured=False,
    note="Strong with writing in pictures. Learns a character, a style or an object from 15 to 25 pictures. "
    + _GUESS,
)

PICTURE_BASES: dict[str, PictureBase] = {
    b.id: b for b in (KLEIN_4B, KLEIN_9B, FLUX3_KLEIN, QWEN_IMAGE, Z_IMAGE, HIDREAM_O1, IDEOGRAM_4)
}
DEFAULT = KLEIN_4B.id
# a run started before the trainer changed names the model it was taught on by its old id
OLD_IDS = {"flux2-klein-base-4b": KLEIN_4B.id}


def picture_base(base: str | None) -> PictureBase:
    """The recipe of `base` (the default when it is None); a `KeyError` when it has none."""
    key = base or DEFAULT
    return PICTURE_BASES[OLD_IDS.get(key, key)]
