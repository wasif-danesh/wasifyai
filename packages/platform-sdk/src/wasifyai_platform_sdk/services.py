"""What the engine is made of, as one typed object (stage F1 of the 2026-10-27 plan).

The engine used to hang every store and service on FastAPI's `app.state` as loose attributes and
read them back by name; a missing one was a `None` found at run time. Now `app.state.services` is
the only attribute, and it is an `EngineServices`: a field for each service, `None` where this
deployment does not have it (a desktop service on the web, a web service on the desktop, anything in
a test app that does not need it). The fields keep the names the attributes had, so a product that
reads `deps.state.audio` reads this object, and pyright knows every name.

Products see this class: it holds what a product's routes and graphs may reach. The engine's own
services (the MCP server, the approval desk, the admin stores) are in the API's `ApiServices`, a
subclass. A field typed `Any` holds a type the SDK cannot import (a product's store, the API's
run manager); its comment names the type.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncEngine

from wasifyai_platform_sdk.secrets import SecretStore
from wasifyai_platform_sdk.storage import ScopedStorage
from wasifyai_platform_sdk.uploads import UploadLimiter, UploadStore
from wasifyai_platform_sdk.usage import UsageRecorder

if TYPE_CHECKING:
    from wasifyai_platform_sdk.actions.executor import ActionExecutor
    from wasifyai_platform_sdk.jobpolicy import JobPolicy
    from wasifyai_platform_sdk.registry import GraphRegistry


@dataclass(eq=False)
class EngineServices:
    # ---- every deployment ----------------------------------------------------------------
    engine: AsyncEngine | None = None  # the database: Postgres on the web, SQLite on the desktop
    storage: ScopedStorage | None = None  # files, under each person's own prefix (ADR-0010)
    usage: UsageRecorder | None = None
    uploads: UploadStore | None = None
    upload_limiter: UploadLimiter | None = None
    enhance_limiter: UploadLimiter | None = None  # prompt enhancements per hour (ADR-0038)
    search_limiter: UploadLimiter | None = None  # searches of My creations per hour (ADR-0041)
    secrets: SecretStore | None = None  # keys and tokens (ADR-0092)
    registry: "GraphRegistry | None" = None
    products_dir: Path | None = None
    heartbeat_s: float = 15.0
    runs: Any = None  # wasifyai_api.runs.RunManager
    actions: "ActionExecutor | None" = None  # the one executor of the catalogue (ADR-0068)
    job_policy: "JobPolicy | None" = None  # one job per person (ADR-0088)
    creation_index: Any = None  # wasifyai_api.creation_index.CreationIndex (ADR-0041)
    caps: dict[str, Any] = field(default_factory=dict)  # product id -> its capabilities
    # what a product accepts as an upload (ADR-0035): (product id, kind) -> its rule or None
    upload_rules: Callable[..., Any] | None = None
    web: Any = None  # wasifyai_api.web_search.WebService: web search, when allowed (ADR-0083)
    audio: Any = None  # a SpeechEngine: the desktop's runtime, or hosted and worker speech
    video_builder: Any = None  # the Motion graphics render engine (ADR-0077)
    model3d: Any = None  # the 3D engine (ADR-0080)
    training: Any = None  # the picture trainer (ADR-0073)
    video_training: Any = None
    language_training: Any = None  # the writing trainer (ADR-0074)
    decision_training: Any = None  # the deciding trainer (ADR-0075)

    # ---- the web only ----------------------------------------------------------------------
    engine_workers: Any = None  # wasifyai_api.engine_workers.WorkerDirectory (ADR-0087)
    voice_store: Any = None  # wasifyai_voice's store (Postgres on the web)
    notebooks_web: Any = None  # wasifyai_notebooks.runtime.WebSetup
    model3d_store: Any = None
    model3d_blobs: Any = None
    builder_store: Any = None  # wasifyai_video.builder's store
    builder_scratch: Path | None = None
    training_store: Any = None
    training_files: Any = None

    # ---- the desktop only ------------------------------------------------------------------
    desktop_dir: Path | None = None  # the app's data folder
    export_dir: Path | None = None  # where "Save" copies a file when no path is chosen
    local_files: Any = None
    desktop_models: Any = None
    desktop_discovery: Any = None
    desktop_styles: Any = None  # the image screens' styles (ADR-0091)
    llama_server: Any = None
    desktop_language: Any = None  # the local language model
    desktop_vision: Any = None
    desktop_hub: Any = None
    training_setup: Any = None  # the trainers' components, set up on request
    language_setup: Any = None
    decision_setup: Any = None
    video_setup: Any = None

    # ---- what products keep for themselves, made on first use --------------------------------
    notebooks_runtime: Any = None
    builder_renders: Any = None
    model3d_jobs: Any = None
    model3d_notices: Any = None
    training_runs: Any = None
    training_captions: Any = None
    video_runs: Any = None
    writing_runs: Any = None
    decision_runs: Any = None


def need[T](service: T | None, what: str = "that") -> T:
    """A service the engine always has once it has started: a `None` here is a request that
    arrived before the start finished (or a test app that did not build it), said in words."""
    if service is None:
        raise RuntimeError(f"The engine has not set up {what} yet.")
    return service
