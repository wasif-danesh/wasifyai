"""The media backends an admin can choose from (ADR-0025), what each needs, and a light check.

The worker runs jobs on them; this module only describes them, validates a configuration and tests
reachability, so the API can do the same without importing the worker."""

import ipaddress
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

LOCAL = "comfyui-local"
COMFY_API = "comfy-api"
OPENAI_IMAGES = "openai-images"


class InvalidBackendConfig(ValueError):
    """The configuration cannot be accepted; the message is meant for the admin."""


@dataclass(frozen=True)
class Field_:
    name: str
    label: str
    required: bool = False
    secret: bool = False  # write-only, kept encrypted, never shown again
    placeholder: str = ""
    help: str = ""


@dataclass(frozen=True)
class BackendSpec:
    id: str
    label: str
    description: str
    families: frozenset[str]  # capability families it can serve: "image", "music", ...
    fields: tuple[Field_, ...] = field(default_factory=tuple)
    local_gpu: bool = False  # runs on this machine's GPU: the worker takes the GPU lock


BACKENDS: dict[str, BackendSpec] = {
    b.id: b
    for b in (
        BackendSpec(
            LOCAL,
            "ComfyUI (local or self-hosted)",
            "Runs the product's ComfyUI workflow on a ComfyUI server you operate.",
            frozenset({"image", "music", "video"}),
            (
                Field_(
                    "base_url",
                    "Server address",
                    placeholder="http://host.containers.internal:8188",
                    help="Leave empty to use the server the platform is configured with.",
                ),
            ),
            local_gpu=True,
        ),
        BackendSpec(
            COMFY_API,
            "Comfy Cloud / Comfy API (v2)",
            "Runs the same workflow on Comfy Cloud, a serverless deployment or a comfy-api-proxy.",
            frozenset({"image", "music", "video"}),
            (
                Field_(
                    "base_url",
                    "API address",
                    placeholder="https://cloud.comfy.org",
                    help="Leave empty for Comfy Cloud.",
                ),
                Field_("api_key", "API key", required=True, secret=True),
            ),
        ),
        BackendSpec(
            OPENAI_IMAGES,
            "OpenAI-compatible image API",
            "Sends the prompt to /images/generations. The product's ComfyUI workflow is not used.",
            frozenset({"image"}),
            (
                Field_(
                    "base_url",
                    "API address",
                    placeholder="https://api.openai.com/v1",
                    help="Leave empty for OpenAI.",
                ),
                Field_("model", "Model", required=True, placeholder="gpt-image-1"),
                Field_(
                    "size",
                    "Image size",
                    placeholder="1024x1024",
                    help="Leave empty to use the size the product asks for.",
                ),
                Field_(
                    "api_key", "API key", secret=True, help="Optional for servers without a key."
                ),
            ),
        ),
    )
}

_NAME = re.compile(r"^[A-Za-z0-9._:/@+\-]{1,200}$")
_SIZE = re.compile(r"^\d{2,5}x\d{2,5}$")


def family(capability: str) -> str:
    """`image.generate` -> `image`."""
    return capability.split(".", 1)[0]


def backends_for(capability: str) -> list[BackendSpec]:
    return [b for b in BACKENDS.values() if family(capability) in b.families]


def check_server_url(url: str) -> str:
    """http(s) only, no credentials in the URL, and never a link-local or unspecified address."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or len(url) > 300:
        raise InvalidBackendConfig("the address must be an http(s) URL")
    if "@" in parts.netloc:
        raise InvalidBackendConfig("do not put credentials in the address")
    try:
        ip = ipaddress.ip_address(parts.hostname)
    except ValueError:
        return url.rstrip("/")
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        raise InvalidBackendConfig("that address is not allowed")
    return url.rstrip("/")


def validate_config(
    backend: str, capability: str, config: dict[str, Any], api_key: str | None, has_saved_key: bool
) -> dict[str, Any]:
    """The cleaned non-secret config, or InvalidBackendConfig. The key is checked, not returned."""
    spec = BACKENDS.get(backend)
    if spec is None:
        raise InvalidBackendConfig(f"unknown backend {backend!r}")
    if family(capability) not in spec.families:
        raise InvalidBackendConfig(f"{spec.label} cannot serve {capability}")
    known = {f.name for f in spec.fields if not f.secret}
    extra = set(config) - known
    if extra:
        raise InvalidBackendConfig(f"unknown setting(s): {', '.join(sorted(extra))}")
    clean: dict[str, Any] = {}
    for f in spec.fields:
        if f.secret:
            if f.required and not (api_key or has_saved_key):
                raise InvalidBackendConfig(f"{spec.label} needs an {f.label.lower()}")
            continue
        value = str(config.get(f.name) or "").strip()
        if not value:
            if f.required:
                raise InvalidBackendConfig(f"{f.label} is required")
            continue
        if f.name == "base_url":
            value = check_server_url(value)
        elif f.name == "model" and not _NAME.match(value):
            raise InvalidBackendConfig("the model name has characters that are not allowed")
        elif f.name == "size" and not _SIZE.match(value):
            raise InvalidBackendConfig("the size must look like 1024x1024")
        clean[f.name] = value
    if api_key and not any(f.secret for f in spec.fields):
        raise InvalidBackendConfig(f"{spec.label} does not use an API key")
    if api_key and (len(api_key) > 512 or re.search(r"\s", api_key)):
        raise InvalidBackendConfig("the API key must be one token without spaces")
    return clean


@dataclass(frozen=True)
class CheckOutcome:
    ok: bool
    message: str
    latency_ms: int = 0


DEFAULT_BASES = {COMFY_API: "https://cloud.comfy.org", OPENAI_IMAGES: "https://api.openai.com/v1"}


async def check_backend(
    backend: str,
    config: dict[str, Any],
    api_key: str | None,
    local_url: str,
    http: httpx.AsyncClient | None = None,
) -> CheckOutcome:
    """A light reachability and credentials check. It never starts a generation (those cost money
    on hosted backends)."""
    base = (config.get("base_url") or DEFAULT_BASES.get(backend) or local_url).rstrip("/")
    client = http or httpx.AsyncClient(timeout=15)
    started = time.monotonic()
    headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        if backend == LOCAL:
            r = await client.get(f"{base}/system_stats")
            ok, msg = (
                r.status_code == 200,
                "ComfyUI answered" if r.status_code == 200 else f"answered {r.status_code}",
            )
        elif backend == COMFY_API:
            r = await client.get(
                f"{base}/api/v2/jobs/00000000-0000-0000-0000-000000000000", headers=headers
            )
            ok, msg = _judge_cloud(r.status_code)
        elif backend == OPENAI_IMAGES:
            r = await client.get(f"{base}/models", headers=headers)
            ok, msg = _judge_models(r.status_code)
        else:
            return CheckOutcome(False, "unknown backend")
    except httpx.HTTPError as exc:
        return CheckOutcome(False, f"unreachable ({type(exc).__name__})")
    finally:
        if http is None:
            await client.aclose()
    return CheckOutcome(ok, msg, round((time.monotonic() - started) * 1000))


def _judge_cloud(status: int) -> tuple[bool, str]:
    if status in (200, 404):
        return True, "reachable, and the key was accepted"
    if status in (401, 403):
        return False, "the key was rejected"
    if status == 402:
        return False, "the account has no credits left"
    if status == 429:
        return False, "the subscription is not active"
    return False, f"answered {status}"


def _judge_models(status: int) -> tuple[bool, str]:
    if status == 200:
        return True, "reachable, and the key was accepted"
    if status == 404:
        return True, "reachable (this server does not list models)"
    if status in (401, 403):
        return False, "the key was rejected"
    return False, f"answered {status}"
