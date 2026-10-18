from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    """Environment wiring and secrets only (rule 13); product config never lands here."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    database_url: str = ""  # usage events; unset = do not record (local experiments only)

    comfyui_base_url: str = "http://localhost:8188"
    # Video runs on its own ComfyUI (ADR-0037): the model needs fp32 weights on a Mac, a
    # process-wide setting that would slow the image and music models. Empty: COMFYUI_BASE_URL.
    comfyui_video_base_url: str = ""
    comfyui_mode: str = "real"  # real | stub (stub returns placeholder files, no GPU needed)

    media_secrets_key: str = ""  # decrypts the API keys saved in the admin area (ADR-0025)

    ollama_base_url: str = ""  # set to unload LLMs from the GPU before each job
    unload_llm: bool = True

    gpu_id: str = "gpu0"  # workers sharing one GPU share this id and take turns
    job_timeout_s: int = 1200  # a 5 s clip takes about 8 minutes on a Mac (ADR-0037)
    max_attempts: int = 3
    log_level: str = "INFO"
    metrics_port: int = 9464  # Prometheus scrapes this port (ADR-0048); 0 turns the listener off

    storage_endpoint: str = "http://localhost:8333"
    storage_bucket: str = "wasifyai"
    storage_region: str = "us-east-1"
    storage_access_key: str = ""
    storage_secret_key: str = ""
