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
    # ---- images (ADR-0100, CP4: the cheapest offer and one fallback, at 1K; "edit" changes and
    # combines pictures, "mask" paints over part of one; prices as listed 2026-11-12)
    _media("images", "gpt-image-2.5", "GPT Image 2.5", "OpenAI's Sunburst, high quality. Makes, changes, combines and paints over part of a picture.",
           offer("wavespeed", "openai/gpt-image-2.5-sunburst/text-to-image", 0.09, "picture", "edit", "mask",
                 endpoints={"edit": "openai/gpt-image-2.5-sunburst/edit"}),
           offer("fal", "openai/gpt-image-2.5/sunburst/text-to-image", 0.125, "picture", "edit", "mask",
                 endpoints={"edit": "openai/gpt-image-2.5/sunburst/edit"})),
    _media("images", "nano-banana-2.1", "Nano Banana 2.1", "Google. Makes, changes and combines pictures, up to 14 at once.",
           offer("runware", "google:nano-banana@2.1", 0.034, "picture", "edit"),
           offer("wavespeed", "google/nano-banana-2.1/text-to-image", 0.04, "picture", "edit",
                 endpoints={"edit": "google/nano-banana-2.1/edit"})),
    _media("images", "grok-imagine-image-2.0", "Grok Imagine Image 2.0", "xAI. Makes, changes and combines pictures.",
           offer("runware", "xai:grok-imagine@image-2.0", 0.04, "picture", "edit"),
           offer("fal", "xai/grok-imagine-image/v2.0/text-to-image", 0.04, "picture", "edit",
                 endpoints={"edit": "xai/grok-imagine-image/v2.0/edit"})),
    _media("images", "flux-3-klein", "FLUX.3 klein", "Black Forest Labs. Quick and cheap; makes, changes and combines pictures.",
           offer("runware", "bfl:flux@3-image-klein", 0.006, "picture", "edit"),
           offer("fal", "blackforestlabs/flux-3/klein/text-to-image", 0.009, "picture", "edit", "lora",
                 endpoints={"edit": "blackforestlabs/flux-3/klein/edit-image",
                            "lora": "blackforestlabs/flux-3/klein/text-to-image/lora"})),
    _media("images", "z-image-turbo", "Z-Image Turbo", "Tongyi. The cheapest; makes pictures and paints over part of one.",
           offer("runware", "runware:z-image@turbo", 0.002, "picture", "mask"),
           offer("fal", "fal-ai/z-image/turbo", 0.005, "picture", "mask",
                 endpoints={"inpaint": "fal-ai/z-image/turbo/inpaint"})),
    # ---- video (ADR-0100, CP5: per second at 720p, 768p for MiniMax H3, without sound; "animate"
    # starts from a picture, "extend" makes a clip longer; prices as listed 2026-11-12)
    _media("video", "gemini-omni-flash-1.2", "Gemini Omni Flash 1.2", "Google. Makes and animates clips of 3 to 15 s, wide or tall; extends them with a Runware key.",
           offer("runware", "google:gemini@omni-flash-1.2", 0.07, "second", "animate", "extend"),
           offer("wavespeed", "google/gemini-omni-1.2-flash/text-to-video", 0.07, "second", "animate",
                 endpoints={"animate": "google/gemini-omni-1.2-flash/image-to-video"})),
    _media("video", "seedance-2.5", "Seedance 2.5", "ByteDance. The best motion; makes, animates and extends clips of 4 to 30 s.",
           offer("runware", "bytedance:seedance@2.5", 0.23, "second", "animate", "extend"),
           offer("wavespeed", "bytedance/seedance-2.5/text-to-video", 0.36, "second", "animate", "extend",
                 endpoints={"animate": "bytedance/seedance-2.5/image-to-video",
                            "extend": "bytedance/seedance-2.5/video-extend"})),
    _media("video", "minimax-h3-max", "MiniMax H3 Max", "MiniMax. Makes and animates clips of 5 to 10 s; extends them with a fal.ai key.",
           offer("runware", "minimax:h3@max", 0.08, "second", "animate"),
           offer("fal", "minimax/h3-max/text-to-video", 0.08, "second", "animate", "extend",
                 endpoints={"animate": "minimax/h3-max/image-to-video",
                            "extend": "minimax/h3-max/extend-video"})),
    _media("video", "minimax-h3-max-turbo", "MiniMax H3 Max Turbo", "MiniMax, quicker and half the price; extends clips with a fal.ai key.",
           offer("runware", "minimax:h3@max-turbo", 0.04, "second", "animate"),
           offer("fal", "minimax/h3-max-turbo/text-to-video", 0.04, "second", "animate", "extend",
                 endpoints={"animate": "minimax/h3-max-turbo/image-to-video",
                            "extend": "minimax/h3-max-turbo/extend-video"})),
    _media("video", "grok-imagine-video-1.5-lite", "Grok Imagine Video 1.5 lite", "xAI. The cheapest; makes and animates clips of 1 to 15 s.",
           offer("runware", "xai:grok-imagine@video-1.5-lite", 0.03, "second", "animate"),
           offer("fal", "xai/grok-imagine-video/v1.5/lite/text-to-video", 0.03, "second", "animate",
                 endpoints={"animate": "xai/grok-imagine-video/v1.5/lite/image-to-video"})),
    # ---- voice (ADR-0100, CP7: speaking per 1,000 characters; a copied or designed MiniMax voice
    # once, then per character on the provider it was made on; listening and changing per minute)
    _media("voice", "kokoro", "Kokoro", "Speaks text in American voices.",
           offer("fal", "fal-ai/kokoro", 0.02, "1k_chars")),
    _media("voice", "elevenlabs-v4", "ElevenLabs v4", "ElevenLabs. Natural voices in many languages.",
           offer("wavespeed", "elevenlabs/eleven-v4", 0.08, "1k_chars"),
           offer("fal", "elevenlabs/tts/eleven-v4", 0.08, "1k_chars")),
    _media("voice", "gemini-3.8-flash-tts", "Gemini 3.8 Flash TTS", "Google. Thirty voices in many languages.",
           offer("fal", "google/gemini-3.8-flash-tts", 0.045, "1k_chars"),
           offer("wavespeed", "google/gemini-3.8-flash/text-to-speech", 0.05, "1k_chars")),
    _media("voice", "chatterbox", "Chatterbox", "Resemble AI. The cheapest; 23 languages.",
           offer("fal", "fal-ai/chatterbox/text-to-speech/multilingual", 0.025, "1k_chars"),
           offer("wavespeed", "chatterbox/text-to-speech", 0.03, "1k_chars")),
    _media("voice", "minimax-speech-2.8-hd", "MiniMax Speech 2.8 HD", "MiniMax. Many voices in many languages; speaks the voices made with MiniMax.",
           offer("runware", "minimax:speech@2.8", 0.10, "1k_chars"),
           offer("fal", "fal-ai/minimax/speech-2.8-hd", 0.10, "1k_chars"),
           offer("wavespeed", "minimax/speech-2.8-hd", 0.10, "1k_chars")),
    _media("voiceclone", "qwen3-tts", "Qwen3-TTS", "Alibaba. Speaks in a voice copied from a short recording, or described in words; 10 languages.",
           offer("runware", "alibaba:qwen@3-tts-1.7b-base", 0.015, "1k_chars", "clone", "design",
                 endpoints={"design": "alibaba:qwen@3-tts-1.7b-voicedesign"}),
           offer("fal", "fal-ai/qwen-3-tts/voice-design/1.7b", 0.09, "1k_chars", "design")),
    _media("voiceclone", "chatterbox-clone", "Chatterbox", "Resemble AI. Speaks in a voice copied from a recording, cheaply.",
           offer("wavespeed", "chatterbox/text-to-speech", 0.03, "1k_chars", "clone")),
    _media("voiceclone", "minimax-voice", "MiniMax voice", "MiniMax. Copies or designs a voice once and keeps it there; speaking in it again costs per character.",
           offer("fal", "fal-ai/minimax/voice-clone", 1.50, "voice", "clone", "design", setting="task",
                 by={"clone": 1.50, "design": 3.00}, endpoints={"design": "fal-ai/minimax/voice-design"}),
           offer("wavespeed", "minimax/voice-clone", 1.60, "voice", "clone", "design", setting="task",
                 by={"clone": 1.60, "design": 3.10}, endpoints={"design": "minimax/voice-design"})),
    _media("transcribe", "scribe-v2", "Scribe v2", "ElevenLabs. Writes down speech in 90 languages.",
           offer("fal", "fal-ai/elevenlabs/speech-to-text/scribe-v2", 0.008, "minute")),
    _media("transcribe", "whisper", "Whisper", "OpenAI's Whisper large v3, on WaveSpeed.",
           offer("wavespeed", "wavespeed-ai/openai-whisper", 0.06, "minute")),
    _media("voicechange", "chatterbox-sts", "Chatterbox", "Resemble AI. Makes a recording sound like the voice in another.",
           offer("fal", "fal-ai/chatterbox/speech-to-speech", 0.015, "minute"),
           offer("wavespeed", "chatterbox/speech-to-speech", 0.02, "minute")),
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
    # LongCat Avatar was taken off the same day: a black video). ADR-0100, CP6: the cheaper offer beside fal.ai
    _media("lipsync", "fabric-1.0", "Fabric 1.0 Fast", "VEED. Quickest; crops to a square. Up to 1 min.",
           # WaveSpeed lists 480p; its 720p is taken as double, as on fal.ai and Runware (the price refresh checks it)
           offer("wavespeed", "veed/fabric-1.0", 0.07, "second", setting="resolution", by={"480p": 0.07, "720p": 0.14}),
           offer("fal", "veed/fabric-1.0/fast", 0.10, "second", setting="resolution", by={"480p": 0.10, "720p": 0.20}),
           speed="5 to 25 s per second of video at 480p (two runs)"),
    _media("lipsync", "kling-avatar-v2", "Kling Avatar v2", "Keeps the picture's shape; moves the head most. Up to 1 min.",
           offer("runware", "klingai:avatar@2.0-standard", 0.044, "second"),
           offer("fal", "fal-ai/kling-video/ai-avatar/v2/standard", 0.06, "second"),
           speed="about 40 s per second of video"),
    _media("lipsync", "omnihuman-1.5", "OmniHuman 1.5", "ByteDance, turbo. Natural blinks and movement. 720p, up to 1 min.",
           offer("runware", "bytedance:5@2", 0.132, "second"),
           offer("fal", "fal-ai/bytedance/omnihuman/v1.5", 0.16, "second"),
           speed="about 45 s per second of video"),
    _media("lipsync", "infinitalk", "InfiniteTalk", "Head and body, speed set to high. Up to 28 s.",
           offer("wavespeed", "wavespeed-ai/infinitetalk", 0.03, "second", setting="resolution", by={"480p": 0.03, "720p": 0.06}),
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
