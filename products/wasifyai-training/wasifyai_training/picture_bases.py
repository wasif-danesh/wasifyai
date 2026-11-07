# ruff: noqa: E501  (the measured notes beside each number read better on one line)
"""The picture models that can be taught, one recipe each (ADR-0073, amendments 2026-11-07).

Everything that differs from one picture model to the next lives here and nowhere else: the model files it is
taught from (the image model's own, as the Images screens keep them), what AI Toolkit calls its architecture,
the picture size, the steps, the measured time and memory, and the model it is used with in Create. A trainer
asks for the recipe of the run's base and reads from it; a base with no recipe cannot be taught.

The trainer is AI Toolkit (Ostris), the same on a Mac with Apple silicon and on a computer with an NVIDIA
graphics card: the owner's aim is that teaching works on every platform (2026-11-07). It writes an adapter in
the key names ComfyUI reads, so what it learns is used in Create as it is.

Only FLUX.2 klein 4B has a recipe for now: its numbers come from the owner's character-lora run of AI Toolkit on
this Mac. A second model gets its own entry, measured on this computer; nothing else changes."""

from dataclasses import dataclass, field


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
    quantize: str = ""  # AI Toolkit's `qtype` for the model and its text encoder; "" = not quantised
    gradient_checkpointing: bool = False
    guidance: float = 3.5  # of the sample pictures
    sample_steps: int = 4
    note: str = ""

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
    learning_rate={"character": 1e-4, "object": 1e-4, "style": 1e-4},
    quantize="convrot8",
    note="The model Create image uses, taught as it is. Learns a character, a style or an object from 15 to 25 pictures.",
)

PICTURE_BASES: dict[str, PictureBase] = {KLEIN_4B.id: KLEIN_4B}
DEFAULT = KLEIN_4B.id
# a run started before the trainer changed names the model it was taught on by its old id
OLD_IDS = {"flux2-klein-base-4b": KLEIN_4B.id}


def picture_base(base: str | None) -> PictureBase:
    """The recipe of `base` (the default when it is None); a `KeyError` when it has none."""
    key = base or DEFAULT
    return PICTURE_BASES[OLD_IDS.get(key, key)]
