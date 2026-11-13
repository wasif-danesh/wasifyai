# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""The Cut step at run time (ADR-0090 decision 7): the cut a project has, where it stands, and making its video. The video is
made with ffmpeg from the chosen versions, the song and the captions, at the full size of the project's shape, and kept as the
project's latest video; keeping it in Your videos is the video product's own action, so it is a video like any other."""

import asyncio
import logging
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import imageio_ffmpeg
from wasifyai_platform_sdk import Identity, RouteDeps

from wasifyai_creative import cut as cuts
from wasifyai_creative.store import CreativeStore

log = logging.getLogger(__name__)

PRODUCT_ID = "wasifyai-creative"
FROM_THE_PLAN = "The cut from the plan"
RENDER_TIMEOUT_S = 3600


class CutFailed(Exception):
    """The video could not be made, with the sentence the person is shown."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def song_s(row: dict[str, Any]) -> float:
    return float(
        row["facts"].get("seconds") or (row["plan"] or {}).get("shots", [{}])[-1].get("end", 0)
    )


def song_lines(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The song's words with the times they were sung, or none when the times are not known."""
    return row["facts"].get("lines", []) if row["facts"].get("lines_timed") else []


def current(store: CreativeStore, row: dict[str, Any]) -> dict[str, Any] | None:
    """The cut, made from the plan the first time it is asked for. None while there is no plan."""
    found = store.cut_of(row["id"])
    if found and found["cut"]:
        return found
    if not row["plan"]:
        return None
    store.save_cut(row["id"], cuts.default_cut(row["plan"], row["facts"]), FROM_THE_PLAN)
    return store.cut_of(row["id"])


def pieces_of(
    store: CreativeStore, row: dict[str, Any], cut: dict[str, Any]
) -> list[dict[str, Any]]:
    """The timeline with what each piece shows: the shot's chosen version, or what was put there by hand."""
    shots = {s["id"]: s for s in (row["plan"] or {}).get("shots", [])}
    chosen = store.chosen_of(row["id"])
    takes = {t["id"]: t for t in store.takes_of(row["id"])}
    out = []
    for p in cuts.timeline(cut):
        source = p.get("source")
        take = takes.get(chosen.get(p["shot_id"] or "", ""))
        kind, item_id = (
            (source["kind"], source["item_id"])
            if source
            else (take["kind"], take["item_id"])
            if take
            else (None, None)
        )
        shot = shots.get(p["shot_id"] or "")
        out.append(
            {
                **p,
                "kind": kind,
                "item_id": item_id,
                "camera": shot["camera"] if shot else "",
                "number": list(shots).index(p["shot_id"]) + 1 if shot else None,
            }
        )
    return out


def view(store: CreativeStore, row: dict[str, Any]) -> dict[str, Any] | None:
    """Where the cut stands: its pieces and captions, undo and redo, what the screen should say, its video and what was kept."""
    found = current(store, row)
    if found is None:
        return None
    cut, shape = found["cut"], row["brief"].get("shape", "landscape")
    pieces = pieces_of(store, row, cut)
    render = store.render_of(row["id"])
    mark = cuts.mark_of(pieces, cut, shape)
    return {
        "items": pieces, "captions": cut["captions"], "captions_on": cut.get("captions_on", True),
        "can_undo": found["can_undo"], "can_redo": found["can_redo"],
        "summary": {**cuts.summary(cut, row["plan"], song_s(row)), "empty": sum(1 for p in pieces if not p["item_id"])},
        "render": {**{k: render[k] for k in ("shape", "seconds", "bytes", "took_s", "created_at")}, "rel": render["rel"], "current": render["mark"] == mark} if render else None,
        "exports": store.exports_of(row["id"]),
        "mark": mark,
    }  # fmt: skip


async def render(
    deps: RouteDeps,
    executor: Any,
    store: CreativeStore,
    identity: Identity,
    item: str,
    progress: Any,
) -> str:
    """Make the cut's video and keep it as the project's latest. Returns its mark."""
    storage = deps.storage
    if storage is None:
        raise CutFailed("unavailable", "File storage is not available.")
    row = store.get(identity.tenant_id, identity.user_id, item)
    found = current(store, row)
    if found is None:
        raise CutFailed("no_plan", "There is no plan yet.")
    cut, shape = found["cut"], row["brief"].get("shape", "landscape")
    pieces = pieces_of(store, row, cut)
    if not any(p["item_id"] for p in pieces):
        raise CutFailed("nothing", "There are no pictures in the cut yet. Make the stills first.")
    mark = cuts.mark_of(pieces, cut, shape)
    ctx = SimpleNamespace(deps=deps, actor=identity, executor=executor)
    started = time.monotonic()
    length = song_s(row)
    with tempfile.TemporaryDirectory(prefix="wasifyai-cut-") as tmp:
        folder = Path(tmp)
        files: dict[tuple[str, str], Path] = {}
        for n, p in enumerate(pieces):
            progress(f"Getting piece {n + 1} of {len(pieces)}")
            if not p["item_id"] or (p["kind"], p["item_id"]) in files:
                continue
            kind = executor.library.get(p["kind"])
            data = await kind.read(ctx, p["item_id"]) if kind and kind.read else None
            if data is None:
                continue  # deleted from the Library since: that piece is black, and the screen says so
            path = folder / f"{len(files)}.{'png' if p['kind'] == 'image' else 'mp4'}"
            await asyncio.to_thread(path.write_bytes, data)
            files[(p["kind"], p["item_id"])] = path
        for p in pieces:
            p["path"] = files.get((p["kind"], p["item_id"])) if p["item_id"] else None
        tracks = executor.library.get("track")
        song = await tracks.read(ctx, row["brief"]["track_id"]) if tracks and tracks.read else None
        if song is None:
            raise CutFailed("no_song", "The song is not in Your music any more.")
        song_path = folder / "song"
        await asyncio.to_thread(song_path.write_bytes, song)
        captions = folder / "captions.ass"
        await asyncio.to_thread(captions.write_text, cuts.ass_of(cut, shape), "utf-8")
        out = folder / "cut.mp4"
        command = cuts.render_command(
            imageio_ffmpeg.get_ffmpeg_exe(),
            pieces,
            song_path,
            length,
            captions,
            cuts.SIZES[shape],
            out,
        )
        progress("Making the video")
        process = await asyncio.create_subprocess_exec(
            *command, cwd=folder, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        try:
            _, err = await asyncio.wait_for(process.communicate(), RENDER_TIMEOUT_S)
        except BaseException:
            process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            log.warning("the cut could not be made: %s", err.decode(errors="replace")[-800:])
            raise CutFailed("not_made", "The video could not be made.")
        data = await asyncio.to_thread(out.read_bytes)
    owner = (identity.tenant_id, PRODUCT_ID, identity.user_id)
    rel = f"cuts/{item}/{int(time.time() * 1000)}.mp4"
    old = store.render_of(item)
    await storage.put_for(owner, rel, data, "video/mp4")
    store.set_render(
        item, rel, mark, shape, length, len(data), round(time.monotonic() - started, 1)
    )
    if old and old["rel"] != rel:
        await storage.delete_for(owner, old["rel"])
    return mark


async def read_render(
    deps: RouteDeps, store: CreativeStore, identity: Identity, item: str
) -> bytes | None:
    """The project's latest video, for the video product to keep."""
    found = store.render_of(item)
    if found is None or deps.storage is None:
        return None
    return await deps.storage.get_for(
        (identity.tenant_id, PRODUCT_ID, identity.user_id), found["rel"]
    )
