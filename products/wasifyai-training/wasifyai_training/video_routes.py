# ruff: noqa: E501  (the sentences shown to people, and made-up media in a test, are easier to read on one line)
"""The routes of video training (ADR-0073, video amendment), added to the training router.

GET /video/status      whether the video model can be taught here, what it needs and the model choices

Sets of pictures and clips, their descriptions and runs use the routes of pictures
(`/datasets`, `/runs`): a set made with `family: "video"` is taught to the video model."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from wasifyai_platform_sdk import Identity, RouteDeps

from wasifyai_training import bases, clips
from wasifyai_training.runtime import NotAvailable
from wasifyai_training.video import (
    MAX_WINDOWS,
    MIN_ITEMS,
    WINDOW_FRAMES,
    engine_for,
    manager_for,
)


async def video_status_of(deps: RouteDeps, kind: str = "character") -> dict[str, Any]:
    """Whether the video model can be taught here, what it needs and the model choices."""
    try:
        engine = engine_for(deps.state)
    except NotAvailable:
        raise HTTPException(404, "Teaching the video model is not available here.") from None
    setup = deps.state.video_setup
    base = bases.descriptors("video")[0]
    ready = engine.ready()
    return {
        "ready": ready,
        "problem": engine.problem(),
        "needs": setup.plan().get("needs", []) if setup is not None else [],
        "engine": engine.state(),
        "fit": engine.fit(base.need_gb) if ready else None,
        "preflight": engine.preflight(base.need_gb) if hasattr(engine, "preflight") else None,
        "busy": manager_for(deps).busy() or manager_for(deps).others_busy(),
        "active_run": manager_for(deps).active(),
        "place": getattr(engine, "place", "device"),
        "min_items": MIN_ITEMS,
        "window_frames": WINDOW_FRAMES,
        "windows_per_clip": MAX_WINDOWS,
        "min_clip_seconds": clips.MIN_SECONDS,
        "choices": bases.choices(
            kind, engine.fit(base.need_gb) if ready else None, ready, [], family="video"
        ),
    }


def add_video_routes(router: APIRouter, deps: RouteDeps) -> None:
    @router.get("/video/status")
    async def video_status(
        kind: str = Query("character", max_length=20), identity: Identity = Depends(deps.identity)
    ) -> dict[str, Any]:
        return await video_status_of(deps, kind)
