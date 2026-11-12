"""The cloud models of each product (ADR-0095, amendment of 2026-11-11; ADR-0100): what the model
picker's Cloud tab lists once a key is saved, and what the router reads.

- **A text line** names its vendor and the vendor's model (Claude Haiku 5.5 first). It runs on that
  vendor's key; the price is said in words.
- **A media line** names a model by this app's id and lists its **offers** (`offers.py`): each a
  provider (Runware, WaveSpeed or fal.ai), that provider's endpoint for the model, its price per
  unit, and what it can do beyond making. A job runs on the cheapest offer that has a key and can
  do it (stage CP3); the Cloud tab shows the model once, "from" its lowest price.

Only models whose requests this app builds are here; another model is another line (and, for a new
kind of request, its body in the runner). Prices are as each provider lists them."""

# ruff: noqa: E501 - the catalogue is a table, one model to a line

from dataclasses import dataclass

from wasifyai_platform_sdk.offers import Offer, cheapest_words, offer


@dataclass(frozen=True)
class CloudModel:
    product: str
    provider: str  # a text line's vendor; "" for a media line (its offers name the providers)
    model: str  # text: the vendor's own name for it; media: this app's id for the model
    title: str
    about: str
    price: str = ""  # text: in words; media: from its offers (`price_words`)
    speed: str = ""  # how long it took when measured, in words ("time not measured" for a lip sync model not timed)
    offers: tuple[Offer, ...] = ()

    @property
    def media(self) -> bool:
        return bool(self.offers)

    @property
    def price_words(self) -> str:
        return self.price or cheapest_words(self.offers)

    def providers(self) -> list[str]:
        return [o.provider for o in self.offers] if self.offers else [self.provider]

    def offer_of(self, provider: str) -> Offer | None:
        return next((o for o in self.offers if o.provider == provider), None)


def _m(
    product: str, provider: str, model: str, title: str, about: str, price: str, speed: str = ""
) -> CloudModel:
    return CloudModel(product, provider, model, title, about, price, speed)


def _media(
    product: str, model: str, title: str, about: str, *offers: Offer, speed: str = ""
) -> CloudModel:
    return CloudModel(product, "", model, title, about, "", speed, tuple(offers))


PER_WORD = "per word used"
CATALOGUE: tuple[CloudModel, ...] = (
    # ---- chat and writing (ADR-0100: the vendors directly, Haiku 5.5 the default; prices per
    # million tokens in / out, checked 2026-11-12, docs/spikes/cloud-v1-cp0.md)
    _m("chat", "anthropic", "claude-haiku-5-5", "Claude Haiku 5.5", "Anthropic. Quick and cheap; the default.", "$0.10 in / $0.50 out per million tokens"),
    _m("chat", "anthropic", "claude-sonnet-5-5", "Claude Sonnet 5.5", "Anthropic. For harder work.", "$2 in / $10 out per million tokens"),
    _m("chat", "openai", "gpt-6-luna", "GPT-6 Luna", "OpenAI.", "$0.10 in / $0.50 out per million tokens"),
    _m("chat", "gemini", "gemini-3.8-flash", "Gemini 3.8 Flash", "Google.", "$0.75 in / $3.75 out per million tokens"),
    _m("chat", "deepseek", "deepseek-flash", "DeepSeek V4.1 Flash", "DeepSeek, in China.", "$0.30 in / $1.20 out per million tokens"),
    _m("chat", "zai", "glm-5.3-flash", "GLM-5.3 Flash", "Z.ai, in China.", "$0.15 in / $0.50 out per million tokens"),
    _m("chat", "openrouter", "anthropic/claude-haiku-5.5", "Claude Haiku 5.5", "Anthropic, through OpenRouter.", PER_WORD),
    _m("chat", "openrouter", "anthropic/claude-sonnet-5.5", "Claude Sonnet 5.5", "Anthropic, through OpenRouter.", PER_WORD),
    _m("chat", "openrouter", "openai/gpt-6-luna", "GPT-6 Luna", "OpenAI, through OpenRouter.", PER_WORD),
    _m("chat", "openrouter", "google/gemini-3.8-flash", "Gemini 3.8 Flash", "Google, through OpenRouter.", PER_WORD),
    _m("chat", "openrouter", "deepseek/deepseek-v4.1-flash", "DeepSeek V4.1 Flash", "DeepSeek, through OpenRouter.", PER_WORD),
    _m("chat", "openrouter", "z-ai/glm-5.3-flash", "GLM-5.3 Flash", "Z.ai, through OpenRouter.", PER_WORD),
    # ---- images
    _media("images", "flux-2", "FLUX.2", "Makes, changes and combines pictures.",
           offer("fal", "fal-ai/flux-2", 0.012, "picture", "edit", endpoints={"edit": "fal-ai/flux-2/edit"})),
    _media("images", "z-image-turbo", "Z-Image Turbo", "Makes pictures quickly.",
           offer("wavespeed", "wavespeed-ai/z-image/turbo", 0.005, "picture")),
    _media("images", "flux-1-schnell", "FLUX.1 schnell", "Makes pictures quickly.",
           offer("runware", "runware:100@1", 0.0006, "picture")),
    _media("images", "flux-1-dev", "FLUX.1 dev", "More detail, a little slower.",
           offer("runware", "runware:101@1", 0.004, "picture")),
    # ---- video
    _media("video", "ltx-2-fast", "LTX-2 fast", "Makes and animates clips, 6 to 10 s.",
           offer("fal", "fal-ai/ltx-2/text-to-video/fast", 0.04, "second", "animate",
                 endpoints={"animate": "fal-ai/ltx-2/image-to-video/fast"})),
    # ---- voice
    _media("voice", "kokoro", "Kokoro", "Speaks text in American voices.",
           offer("fal", "fal-ai/kokoro", 0.02, "1k_chars")),
    # ---- music and sound effects
    _media("music", "minimax-music-2.6", "MiniMax Music 2.6", "Songs with your lyrics, or it writes them.",
           offer("runware", "minimax:music@2.6", 0.15, "song"),
           offer("wavespeed", "minimax/music-2.6", 0.15, "song"),
           offer("fal", "fal-ai/minimax-music/v2.6", 0.15, "song")),
    _media("music", "elevenlabs-music", "ElevenLabs Music", "Instrumentals or vocals, 3 s to 10 min.",
           offer("fal", "fal-ai/elevenlabs/music", 0.60, "minute")),
    _media("sfx", "elevenlabs-sfx-v2", "ElevenLabs Sound Effects", "0.5 to 22 s, can loop.",
           offer("fal", "fal-ai/elevenlabs/sound-effects/v2", 0.002, "second")),
    # ---- lip sync (speed: seconds of work per second of video, fal.ai, 2026-11-12, docs/spikes/lipsync-cloud-race.md;
    # LongCat Avatar was taken off the same day: a black video)
    _media("lipsync", "fabric-1.0", "Fabric 1.0 Fast", "VEED. Quickest; crops to a square. Up to 1 min.",
           offer("fal", "veed/fabric-1.0/fast", 0.10, "second", setting="resolution", by={"480p": 0.10, "720p": 0.20}),
           speed="5 to 25 s per second of video at 480p (two runs)"),
    _media("lipsync", "kling-avatar-v2", "Kling Avatar v2", "Keeps the picture's shape; moves the head most. Up to 1 min.",
           offer("fal", "fal-ai/kling-video/ai-avatar/v2/standard", 0.06, "second"),
           speed="about 40 s per second of video"),
    _media("lipsync", "omnihuman-1.5", "OmniHuman 1.5", "ByteDance, turbo. Natural blinks and movement. 720p, up to 1 min.",
           offer("fal", "fal-ai/bytedance/omnihuman/v1.5", 0.16, "second"),
           speed="about 45 s per second of video"),
    _media("lipsync", "infinitalk", "InfiniteTalk", "Head and body, speed set to high. Up to 28 s.",
           offer("fal", "fal-ai/infinitalk", 0.20, "second", setting="resolution", by={"480p": 0.20, "720p": 0.40}),
           speed="about 50 s per second of video at 480p"),
    # ---- 3D
    _media("model3d", "pixal3d", "Pixal3D", "A textured 3D model from a picture.",
           offer("fal", "fal-ai/pixal3d", 0.06, "model")),
)  # fmt: skip


def models_of(product: str, provider: str | None = None) -> list[CloudModel]:
    """The models of `product`; with `provider`, those that run there (a vendor's text models, or
    the media models with an offer on that provider)."""
    return [
        m for m in CATALOGUE
        if m.product == product and (provider is None or provider in m.providers())
    ]  # fmt: skip


def find(product: str, provider: str, model: str) -> CloudModel | None:
    """A text line by vendor and model, or a media line by its id (`provider` "") or by a
    provider's endpoint for it (a choice saved before stage CP3)."""
    for m in CATALOGUE:
        if m.product != product:
            continue
        if m.media:
            if m.model == model and (not provider or m.offer_of(provider)):
                return m
            o = m.offer_of(provider) if provider else None
            if o is not None and o.endpoint == model:
                return m
        elif m.provider == provider and m.model == model:
            return m
    return None


def media_model(product: str, model: str) -> CloudModel | None:
    """A media line by this app's id, or by any provider's endpoint for it."""
    for m in CATALOGUE:
        if (
            m.product == product
            and m.media
            and (m.model == model or any(o.endpoint == model for o in m.offers))
        ):
            return m
    return None


def providers_of(product: str) -> list[str]:
    """The providers with models for `product`, in the catalogue's order."""
    seen: list[str] = []
    for m in CATALOGUE:
        if m.product == product:
            seen.extend(p for p in m.providers() if p not in seen)
    return seen
