"""Changing a project of scenes (ADR-0096): add, change, move, duplicate and remove one scene. Each
takes a document and gives back a new one, checked again. The actions call these; so will the
editor's assistant. A project made from a template becomes a document on its first change."""

from typing import Any

from wasifyai_video.builder import templates
from wasifyai_video.builder.templates import SlotError


def find(document: dict[str, Any], scene_id: str) -> int:
    for n, scene in enumerate(document["scenes"]):
        if scene["id"] == scene_id:
            return n
    raise SlotError("That scene is not in this project.")


def _with(document: dict[str, Any], scenes: list[dict[str, Any]]) -> dict[str, Any]:
    return templates.normalize_slots(templates.SCENES, {**document, "scenes": scenes})


def _unused_id(document: dict[str, Any]) -> str:
    scene_id = templates.new_scene_id()
    while any(s["id"] == scene_id for s in document["scenes"]):
        scene_id = templates.new_scene_id()
    return scene_id


def add(
    document: dict[str, Any], kind: str, fields: dict[str, Any], name: str = "",
    at: int | None = None, more: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:  # fmt: skip
    """A new scene at position `at` (from 0; the end if not given), and its id."""
    scene_id = _unused_id(document)
    scenes = list(document["scenes"])
    where = len(scenes) if at is None else max(0, min(at, len(scenes)))
    scenes.insert(
        where,
        {"id": scene_id, "kind": kind, "name": name, "fields": fields, **(more or {})},
    )
    return _with(document, scenes), scene_id


def change(
    document: dict[str, Any], scene_id: str, fields: dict[str, Any], name: str | None = None,
    **more: Any,
) -> dict[str, Any]:  # fmt: skip
    """Change the given fields of one scene; the rest stay. `more` is its caption or transition
    or where its parts go (None leaves it as it is)."""
    n = find(document, scene_id)
    scenes = list(document["scenes"])
    scene = scenes[n]
    scenes[n] = {
        **scene,
        **{k: v for k, v in more.items() if v is not None},
        "name": scene["name"] if name is None else name,
        "fields": {**scene["fields"], **fields},
    }
    return _with(document, scenes)


def move(document: dict[str, Any], scene_id: str, to: int) -> dict[str, Any]:
    scenes = list(document["scenes"])
    scene = scenes.pop(find(document, scene_id))
    scenes.insert(max(0, min(to, len(scenes))), scene)
    return _with(document, scenes)


def duplicate(document: dict[str, Any], scene_id: str) -> tuple[dict[str, Any], str]:
    """A copy right after the scene, and the copy's id."""
    n = find(document, scene_id)
    copy = {**document["scenes"][n], "id": _unused_id(document)}
    scenes = list(document["scenes"])
    scenes.insert(n + 1, copy)
    return _with(document, scenes), copy["id"]


def remove(document: dict[str, Any], scene_id: str) -> dict[str, Any]:
    n = find(document, scene_id)
    if len(document["scenes"]) == 1:
        raise SlotError("A project needs at least one scene.")
    return _with(document, [s for i, s in enumerate(document["scenes"]) if i != n])
