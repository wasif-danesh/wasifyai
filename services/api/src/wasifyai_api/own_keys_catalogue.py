"""The cloud models of each product, by provider (ADR-0095, amendment of 2026-11-11): what the
model picker's Cloud tab lists once a key for that provider is saved under that product. Only models
whose requests this app builds are here; another model is another line (and, for a new kind of
request, its body in the runner). Prices are as each provider lists them, said in words."""

# ruff: noqa: E501 - the catalogue is a table, one model to a line

from dataclasses import dataclass


@dataclass(frozen=True)
class CloudModel:
    product: str
    provider: str
    model: str  # the provider's own name for it: an endpoint, a model id or an AIR id
    title: str
    about: str
    price: str
    speed: str = ""  # how long it took when measured, in words ("time not measured" for a lip sync model not timed)


def _m(
    product: str, provider: str, model: str, title: str, about: str, price: str, speed: str = ""
) -> CloudModel:
    return CloudModel(product, provider, model, title, about, price, speed)


PER_WORD = "per word used"
CATALOGUE: tuple[CloudModel, ...] = (
    # ---- chat and writing (any OpenAI-compatible route)
    _m("chat", "fal", "google/gemini-2.5-flash", "Gemini 2.5 Flash", "Google, through fal.ai.", PER_WORD),
    _m("chat", "fal", "openai/gpt-4o-mini", "GPT-4o mini", "OpenAI, through fal.ai.", PER_WORD),
    _m("chat", "fal", "anthropic/claude-sonnet-4.5", "Claude Sonnet", "Anthropic, through fal.ai.", PER_WORD),
    _m("chat", "wavespeed", "deepseek/deepseek-v4-flash", "DeepSeek V4 Flash", "DeepSeek, through WaveSpeed.", PER_WORD),
    _m("chat", "runware", "minimax:m2.7@0", "MiniMax M2.7", "MiniMax, through Runware.", PER_WORD),
    _m("chat", "openrouter", "google/gemini-2.5-flash", "Gemini 2.5 Flash", "Google.", PER_WORD),
    _m("chat", "openrouter", "openai/gpt-4o-mini", "GPT-4o mini", "OpenAI.", PER_WORD),
    _m("chat", "openrouter", "anthropic/claude-sonnet-4.5", "Claude Sonnet", "Anthropic.", PER_WORD),
    _m("chat", "openrouter", "deepseek/deepseek-chat", "DeepSeek V3", "DeepSeek.", PER_WORD),
    _m("chat", "openai", "gpt-4o-mini", "GPT-4o mini", "Quick and cheap.", PER_WORD),
    _m("chat", "openai", "gpt-4.1", "GPT-4.1", "Stronger, slower.", PER_WORD),
    _m("chat", "anthropic", "claude-sonnet-5-5", "Claude Sonnet 5.5", "Careful writing.", PER_WORD),
    _m("chat", "anthropic", "claude-haiku-5-5", "Claude Haiku 5.5", "Quick.", PER_WORD),
    _m("chat", "gemini", "gemini-2.5-flash", "Gemini 2.5 Flash", "Quick.", PER_WORD),
    _m("chat", "gemini", "gemini-2.5-pro", "Gemini 2.5 Pro", "Stronger, slower.", PER_WORD),
    _m("chat", "groq", "llama-3.3-70b-versatile", "Llama 3.3 70B", "Very quick.", PER_WORD),
    # ---- images
    _m("images", "fal", "fal-ai/flux-2", "FLUX.2", "Makes, changes and combines pictures.", "about $0.012 per picture"),
    _m("images", "wavespeed", "wavespeed-ai/z-image/turbo", "Z-Image Turbo", "Makes pictures quickly.", "$0.005 per picture"),
    _m("images", "runware", "runware:100@1", "FLUX.1 schnell", "Makes pictures quickly.", "about $0.0006 per picture"),
    _m("images", "runware", "runware:101@1", "FLUX.1 dev", "More detail, a little slower.", "about $0.004 per picture"),
    # ---- video
    _m("video", "fal", "fal-ai/ltx-2/text-to-video/fast", "LTX-2 fast", "Makes and animates clips, 6 to 10 s.", "about $0.04 per second"),
    # ---- voice
    _m("voice", "fal", "fal-ai/kokoro", "Kokoro", "Speaks text in American voices.", "$0.02 per 1,000 characters"),
    # ---- music and sound effects
    _m("music", "fal", "fal-ai/minimax-music/v2.6", "MiniMax Music 2.6", "Songs with your lyrics, or it writes them.", "$0.15 per song"),
    _m("music", "fal", "fal-ai/elevenlabs/music", "ElevenLabs Music", "Instrumentals or vocals, 3 s to 10 min.", "$0.60 per minute"),
    _m("music", "wavespeed", "minimax/music-2.6", "MiniMax Music 2.6", "Songs with your lyrics, or it writes them.", "$0.15 per song"),
    _m("music", "runware", "minimax:music@2.6", "MiniMax Music 2.6", "Songs with your lyrics, or it writes them.", "$0.15 per song"),
    _m("sfx", "fal", "fal-ai/elevenlabs/sound-effects/v2", "ElevenLabs Sound Effects", "0.5 to 22 s, can loop.", "$0.002 per second"),
    # lip sync is fal.ai only (owner, 2026-11-12); LongCat Avatar was taken off the same day (a black video)
    # ---- lip sync (speed: seconds of work per second of video, fal.ai, 2026-11-12, docs/spikes/lipsync-cloud-race.md)
    _m("lipsync", "fal", "veed/fabric-1.0/fast", "Fabric 1.0 Fast", "VEED. Quickest; crops to a square. Up to 1 min.", "$0.10 per second at 480p, $0.20 at 720p", "5 to 25 s per second of video at 480p (two runs)"),
    _m("lipsync", "fal", "fal-ai/kling-video/ai-avatar/v2/standard", "Kling Avatar v2", "Keeps the picture's shape; moves the head most. Up to 1 min.", "$0.06 per second", "about 40 s per second of video"),
    _m("lipsync", "fal", "fal-ai/bytedance/omnihuman/v1.5", "OmniHuman 1.5", "ByteDance, turbo. Natural blinks and movement. 720p, up to 1 min.", "$0.16 per second", "about 45 s per second of video"),
    _m("lipsync", "fal", "fal-ai/infinitalk", "InfiniteTalk", "Head and body, speed set to high. Up to 28 s.", "$0.20 per second at 480p, $0.40 at 720p", "about 50 s per second of video at 480p"),
    # ---- 3D
    _m("model3d", "fal", "fal-ai/pixal3d", "Pixal3D", "A textured 3D model from a picture.", "under $1 per model"),
)  # fmt: skip


def models_of(product: str, provider: str | None = None) -> list[CloudModel]:
    return [
        m
        for m in CATALOGUE
        if m.product == product and (provider is None or m.provider == provider)
    ]


def find(product: str, provider: str, model: str) -> CloudModel | None:
    return next(
        (
            m
            for m in CATALOGUE
            if m.product == product and m.provider == provider and m.model == model
        ),
        None,
    )


def providers_of(product: str) -> list[str]:
    """The providers with models for `product`, in the catalogue's order."""
    seen: list[str] = []
    for m in CATALOGUE:
        if m.product == product and m.provider not in seen:
            seen.append(m.provider)
    return seen
