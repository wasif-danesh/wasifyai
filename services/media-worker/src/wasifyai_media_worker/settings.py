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
    # The talking-head server for Lip Sync (ADR-0044, services/lipsync-musetalk); native on a Mac.
    lipsync_server_url: str = ""
    # A song is minutes of video, about 6 s of compute per second (ADR-0044): a longer limit.
    lipsync_timeout_s: int = 5400
    # Speech engines (ADR-0042): `engine=address` pairs, comma separated.
    speech_servers: str = (
        "kokoro=http://speech:8000,indic-parler=http://speech-indic:8000,"
        "whisper=http://speech:8000,indic-stt=http://stt-indic:8000"
    )
    comfyui_mode: str = "real"  # real | stub (stub returns placeholder files, no GPU needed)
    # Speech has its own switch so a laptop cluster can run the (CPU) speech servers for real while
    # the GPU models are placeholders. Empty: follows `comfyui_mode`.
    speech_mode: str = ""

    media_secrets_key: str = ""  # decrypts the API keys saved in the admin area (ADR-0025)

    ollama_base_url: str = ""  # set to unload LLMs from the GPU before each job
    unload_llm: bool = True

    @property
    def speech_is_stub(self) -> bool:
        return (self.speech_mode or self.comfyui_mode) == "stub"

    @property
    def speech_server_map(self) -> dict[str, str]:
        pairs = (p.split("=", 1) for p in self.speech_servers.split(",") if "=" in p)
        return {k.strip(): v.strip() for k, v in pairs if k.strip() and v.strip()}

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
