from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Secrets and environment wiring. Read only from env vars (see docs/configuration.md)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The deployment profile (ADR-0056). `web`: Postgres, Redis Streams, S3 storage. `desktop`: one
    # SQLite file, an in-process queue and event log, local files, loopback only; the shell passes
    # DESKTOP_DATA_DIR, DESKTOP_PUBLIC_URL and a per-launch API_AUTH_SECRET.
    deployment_profile: str = "web"
    desktop_data_dir: str = ""  # database and files live here (the app data directory)
    desktop_public_url: str = ""  # this engine's own URL, as the window reaches it (file links)
    desktop_allowed_origins: str = "tauri://localhost,http://tauri.localhost,http://localhost:1420"
    # stub: placeholder files | comfyui: the real engine (fails until it is set up) | auto: the real
    # engine once it is installed, placeholders until then (the desktop's default)
    desktop_image_engine: str = "stub"
    desktop_models_dir: str = ""  # where downloaded models go; empty: <data dir>/models
    # more model roots ComfyUI may read (never written), separated by the platform's path separator:
    # for example an existing ComfyUI models folder, so 16 GB are not copied
    desktop_extra_model_dirs: str = ""
    desktop_idle_unload_s: int = 600  # unload the model after this long without a job
    # extra ComfyUI arguments, space separated (for example `--gpu-only`): memory modes, for tuning
    desktop_comfyui_args: str = ""
    # comma-separated product ids; empty: all (desktop: image, video, assistant, notebooks, voice)
    products_enabled: str = ""

    database_url: str = "postgresql+asyncpg://wasifyai:wasifyai@localhost:5432/wasifyai"
    redis_url: str = "redis://localhost:6379/0"
    litellm_base_url: str = "http://localhost:4000"
    litellm_api_key: str = ""
    comfyui_base_url: str = "http://host.containers.internal:8188"
    comfyui_video_base_url: str = ""  # the ComfyUI video runs on (ADR-0037); empty: the one above
    ollama_base_url: str = "http://host.containers.internal:11434"
    log_level: str = "INFO"
    metrics_port: int = 9464  # Prometheus scrapes this port (ADR-0048); 0 turns the listener off
    media_secrets_key: str = ""  # encrypts media provider API keys saved in the admin area

    # Search over My creations (ADR-0041). The embedder is the `creation-embedder` alias; the index
    # records which model made each row, and a row made by another model is re-embedded.
    search_min_similarity: float = 0.57  # the floor under which a meaning match is not shown
    # What made each index row: the embedder and the text format. Change it when an admin changes
    # the alias's model or when `search_text` changes: the background indexer re-embeds everything.
    search_index_model: str = "bge-m3/v2"
    search_reconcile_every_s: int = 300
    search_reconcile_batch: int = 200  # items embedded per check: about 3 seconds of work

    # ADR-0047: true in production: the safeguards are always on and the admin cannot turn them off.
    safeguards_force_on: bool = False

    products_dir: str = "products"
    product_env: str = ""  # selects products/<id>/product.<env>.yaml overlays

    # S3-compatible object storage (SeaweedFS in dev and staging; S3/GCS in the clouds).
    storage_endpoint: str = "http://localhost:8333"
    storage_public_endpoint: str = ""  # browser-facing URL if it differs from storage_endpoint
    storage_bucket: str = "wasifyai"
    storage_region: str = "us-east-1"
    storage_access_key: str = ""
    storage_secret_key: str = ""

    # Notebooks on the web (docs/phase3-web-parity-plan.md, W4): off until a reading worker is
    # deployed, because a source waits for it. The models and the reader are on the worker's
    # machine; the engine needs the search model's folder only to answer about what was read.
    notebooks_enabled: bool = False
    notebooks_models_dir: str = ""
    notebooks_reader_dir: str = ""
    notebooks_schema: str = "notebooks"
    notebooks_embed_model: str = "creation-embedder"  # the gateway alias that serves the search
    notebooks_embed_dimension: int = 1024

    # Speech on the web (docs/phase3-web-parity-plan.md, W5): the hosted models of
    # `products/wasifyai-voice/hosted-models.yaml`, asked through the gateway by alias. Off until
    # the gateway has the aliases (`voice-speak`, `voice-transcribe`) pointed at provider models.
    voice_enabled: bool = False
    voice_schema: str = "voice"
    # what answers speech: hosted (the gateway's speech routes), local (the models in
    # DESKTOP_DATA_DIR, as the desktop app runs them) or both; local and both are for a service on a
    # machine that has the models
    voice_engine: Literal["hosted", "local", "both"] = "hosted"
    voice_models_file: str = ""  # your own descriptors; default: the product's file

    @model_validator(mode="after")
    def _desktop_defaults(self) -> "Settings":
        """Values that only make sense for one profile, unless the environment sets them."""
        if self.deployment_profile not in ("web", "desktop"):
            raise ValueError("DEPLOYMENT_PROFILE must be 'web' or 'desktop'")
        if self.deployment_profile == "desktop":
            if "litellm_base_url" not in self.model_fields_set:
                self.litellm_base_url = ""  # no gateway yet: search and enhance wait for one
            if "metrics_port" not in self.model_fields_set:
                self.metrics_port = 0  # a desktop app opens no extra port
            if "default_tenant_id" not in self.model_fields_set:
                self.default_tenant_id = "local"  # one person, one tenant
            if not self.products_enabled:
                self.products_enabled = (
                    "wasifyai-image,wasifyai-video,wasifyai-assistant,wasifyai-notebooks,"
                    "wasifyai-voice"
                )
        return self

    @property
    def desktop_dir(self) -> Path:
        return Path(self.desktop_data_dir).expanduser()

    @property
    def models_dir(self) -> Path:
        return (
            Path(self.desktop_models_dir).expanduser()
            if self.desktop_models_dir
            else (self.desktop_dir / "models")
        )

    @property
    def extra_model_dirs(self) -> tuple[Path, ...]:
        import os

        parts = [p for p in self.desktop_extra_model_dirs.split(os.pathsep) if p.strip()]
        return tuple(Path(p).expanduser() for p in parts)

    @property
    def enabled_product_set(self) -> frozenset[str]:
        return frozenset(p.strip() for p in self.products_enabled.split(",") if p.strip())

    @property
    def checkpoint_url(self) -> str:
        """psycopg-style DSN for the LangGraph Postgres checkpointer."""
        return self.database_url.replace("+asyncpg", "")

    default_tenant_id: str = "dev-tenant"
    dev_user_id: str = "dev-user"

    # Authentication (ADR-0030). "jwt" is the default; "stub" is for local work and tests only.
    auth_mode: str = "jwt"
    api_auth_secret: str = ""  # shared with the web app, at least 32 bytes
    admin_emails: str = ""  # comma-separated; only a verified email can become admin

    @property
    def admin_email_set(self) -> frozenset[str]:
        return frozenset(e.strip().lower() for e in self.admin_emails.split(",") if e.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
