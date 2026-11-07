"""Product configuration (ADR-0010). Precedence, later wins:

1. defaults in code
2. products/<id>/product.yaml
3. products/<id>/product.<env>.yaml   (optional, e.g. a lighter workflow in dev)
4. env vars <PRODUCT_ID>__<PATH>      e.g. WASIFYAI_MUSIC__CAPABILITIES__MUSIC_GENERATE__WORKFLOW

The merged result is validated at startup, including that every referenced workflow and map file
exists and every mapped node ID is in the workflow JSON. A bad config fails the deploy, not a
user's request.
"""

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from wasifyai_platform_sdk.workflows import workflow_problems

CAPABILITY_NAME = re.compile(r"^(text|image|video)\.[a-z0-9_]+$")


class ConfigError(Exception):
    """Raised with every problem found, so one deploy attempt shows them all."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("invalid product config:\n  - " + "\n  - ".join(problems))


class CapabilityBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["litellm", "comfyui", "fake"]
    model: str | None = None  # litellm: a LiteLLM alias, never a raw model name
    workflow: str | None = None  # comfyui: workflow name under products/<id>/workflows/
    defaults: dict[str, Any] = Field(default_factory=dict)
    # Input modalities the bound model accepts. Graphs that pass anything else fail early.
    inputs: list[Literal["text", "image", "audio"]] = Field(default_factory=lambda: ["text"])

    @model_validator(mode="after")
    def _provider_fields(self) -> "CapabilityBinding":
        if self.provider == "litellm" and not self.model:
            raise ValueError("provider 'litellm' requires 'model' (a LiteLLM alias)")
        if self.provider == "comfyui" and not self.workflow:
            raise ValueError("provider 'comfyui' requires 'workflow'")
        return self


class UploadRule(BaseModel):
    """What a product accepts from a user's browser (ADR-0035). Absent: nothing is accepted."""

    model_config = ConfigDict(extra="forbid")

    max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    max_seconds: int = Field(default=1800, ge=1, le=7200)  # audio only: the decoded length


class EnhanceRule(BaseModel):
    """One kind of prompt the user can have rewritten (ADR-0038)."""

    model_config = ConfigDict(extra="forbid")

    prompt: str  # the enhancer instructions: a file stem under the product's prompts/
    max_chars: int = Field(default=500, ge=50, le=4000)  # the longest result (and input) allowed
    needs_picture: bool = False  # the user's uploaded picture is described first


MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9.-]{0,63}$")


class ModelChoice(BaseModel):
    """One model a person can choose for a media product (ADR-0097): its id in the product's
    `models.yaml` and the image or video capabilities it answers, each with its own workflow. A
    model binds only what it can do; a capability it lacks is not offered while it is chosen."""

    model_config = ConfigDict(extra="forbid")

    id: str
    capabilities: dict[str, CapabilityBinding] = Field(default_factory=dict)
    # what a graph needs to know about the model to ask for the right amounts, by name, for example
    # `frames_per_second` of a video model; a graph reads them with `caps.video.setting(...)`
    settings: dict[str, int | float | str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _media_only(self) -> "ModelChoice":
        if not MODEL_ID.match(self.id):
            raise ValueError(f"invalid model id {self.id!r}")
        bad = [n for n in self.capabilities if not re.match(r"^(image|video)\.[a-z0-9_]+$", n)]
        if bad:
            raise ValueError(f"model {self.id!r}: only image and video capabilities, not {bad}")
        if not self.capabilities:
            raise ValueError(f"model {self.id!r} binds no capability")
        return self


class ProductConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    capabilities: dict[str, CapabilityBinding] = Field(default_factory=dict)
    # The models a person can choose between (ADR-0097); the first is used when a request names
    # none. A product with this list binds its image and video capabilities here, not in
    # `capabilities`.
    models: list[ModelChoice] = Field(default_factory=list)
    # Kinds of file a user may upload to this product: `uploads: { image: { max_bytes: ... } }`.
    uploads: dict[Literal["image", "audio"], UploadRule] = Field(default_factory=dict)
    # Prompts the user can have rewritten, by kind (ADR-0038). Absent: no Enhance button.
    enhance: dict[str, EnhanceRule] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _names(self) -> "ProductConfig":
        bad = [n for n in self.capabilities if not CAPABILITY_NAME.match(n)]
        if bad:
            raise ValueError(f"invalid capability name(s) {bad}: expected e.g. 'text.chat'")
        ids = [m.id for m in self.models]
        if len(ids) != len(set(ids)):
            raise ValueError(f"a model is listed twice in {ids}")
        if self.models:
            media = [n for n in self.capabilities if n.startswith(("image.", "video."))]
            if media:
                raise ValueError(f"{media}: bind these under `models`, not `capabilities`")
        return self

    def model(self, model_id: str | None) -> ModelChoice | None:
        """The chosen model, the first when `model_id` is None; None when there is no such model."""
        if not self.models:
            return None
        if model_id is None:
            return self.models[0]
        return next((m for m in self.models if m.id == model_id), None)


def _deep_merge(base: dict[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        out[k] = (
            _deep_merge(out[k], v) if isinstance(v, Mapping) and isinstance(out.get(k), dict) else v
        )
    return out


def _norm(s: str) -> str:
    return s.lower().replace(".", "_")


def _apply_env_overrides(data: dict[str, Any], product_id: str, environ: Mapping[str, str]) -> None:
    prefix = product_id.upper().replace("-", "_") + "__"
    for name, raw in environ.items():
        if not name.startswith(prefix):
            continue
        node: dict[str, Any] = data
        parts = name[len(prefix) :].split("__")
        for i, part in enumerate(parts):
            key = next((k for k in node if _norm(k) == _norm(part)), None)
            if key is None:
                # unknown capability names need dots restored; other keys stay snake_case
                key = (
                    part.lower().replace("_", ".", 1)
                    if (i == 1 and parts[0].lower() == "capabilities")
                    else part.lower()
                )
            if i == len(parts) - 1:
                node[key] = yaml.safe_load(raw)
            else:
                node = node.setdefault(key, {})


def load_product_config(
    products_dir: Path,
    product_id: str,
    env: str = "",
    environ: Mapping[str, str] | None = None,
    check_files: bool = True,
) -> ProductConfig:
    product_dir = products_dir / product_id
    base_path = product_dir / "product.yaml"
    if not base_path.is_file():
        raise ConfigError([f"product config not found: {base_path}"])
    data: dict[str, Any] = yaml.safe_load(base_path.read_text()) or {}
    if env and (env_path := product_dir / f"product.{env}.yaml").is_file():
        data = _deep_merge(data, yaml.safe_load(env_path.read_text()) or {})
    _apply_env_overrides(data, product_id, os.environ if environ is None else environ)
    problems: list[str] = []
    raw_caps = data.get("capabilities")
    if isinstance(raw_caps, dict):  # checked on raw data so it is reported alongside field errors
        problems += [
            f"capabilities.{n}: invalid capability name, expected e.g. 'text.chat'"
            for n in raw_caps
            if not CAPABILITY_NAME.match(str(n))
        ]
    config: ProductConfig | None = None
    try:
        config = ProductConfig.model_validate(data)
    except ValidationError as e:
        for x in e.errors():
            msg = f"{'.'.join(map(str, x['loc'])) or 'config'}: {x['msg']}"
            if "invalid capability name" not in msg:
                problems.append(msg)
    if config is not None:
        if config.id != product_id:
            problems.append(f"id {config.id!r} does not match folder {product_id!r}")
        if check_files and not problems:
            problems += config_file_problems(config, product_dir)
    if problems or config is None:
        raise ConfigError(problems or ["invalid config"])
    return config


def config_file_problems(config: ProductConfig, product_dir: Path) -> list[str]:
    out: list[str] = []
    bound = [(cap, b) for cap, b in config.capabilities.items()]
    bound += [
        (f"models.{m.id}.{cap}", b) for m in config.models for cap, b in m.capabilities.items()
    ]
    for cap, binding in bound:
        if binding.provider == "comfyui" and binding.workflow:
            out += [
                f"{cap}: {p}"
                for p in workflow_problems(product_dir / "workflows", binding.workflow)
            ]
    return out
