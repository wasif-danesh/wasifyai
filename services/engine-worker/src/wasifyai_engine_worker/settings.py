import socket

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    """Environment wiring only (rule 13). What the engine itself reads (`DESKTOP_DATA_DIR`,
    `DESKTOP_MODELS_DIR`, ...) is the API's settings, because the worker runs the same runtime."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    storage_endpoint: str = "http://localhost:8333"
    storage_bucket: str = "wasifyai"
    storage_region: str = "us-east-1"
    storage_access_key: str = ""
    storage_secret_key: str = ""

    worker_id: str = ""  # default: the machine's name and the process id
    job_timeout_s: int = 3600  # a song on a slow machine takes minutes
    heartbeat_s: int = 10
    log_level: str = "INFO"

    @property
    def name(self) -> str:
        import os

        return self.worker_id or f"{socket.gethostname()}-{os.getpid()}"
