# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""The Shots step at run time (ADR-0090 decisions 6 and 8): making the stills as one job whose children are the image product's
own runs, and joining the preview. Each still is saved the moment it is made, so stopping, a crash or closing the app loses only
the one under way, and going on makes only what is missing. A still is made by the image product's action, so it is a picture of
the Library like any other, tagged with the project and the shot.

The preview is stills with a camera move, cut on the plan's times over the song, joined by ffmpeg. A shot with no still is black,
and the screen says how many."""

import asyncio
import hashlib
import json
import logging
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import imageio_ffmpeg
from wasifyai_platform_sdk import Identity, RouteDeps, RunContext, set_context
from wasifyai_platform_sdk.context import reset_context

from wasifyai_creative import stills
from wasifyai_creative.store import CreativeStore

log = logging.getLogger(__name__)

PRODUCT_ID = "wasifyai-creative"
PREVIEW_FPS = 24
PREVIEW_SIZES = {"landscape": (1280, 720), "portrait": (720, 1280), "square": (960, 960)}
FFMPEG_TIMEOUT_S = 1800
GIVE_UP_AFTER = 3  # stills that fail in a row: something is wrong, so stop and say what


class Refused(Exception):
    """A request that cannot be done now, with the sentence the person is shown."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def view(store: CreativeStore, row: dict[str, Any]) -> dict[str, Any]:
    """Where a project's shots stand: their takes, which are out of date, the run and the preview."""
    item, brief = row["id"], row["brief"]
    shots = (row["plan"] or {}).get("shots", [])
    chosen = store.chosen_of(item)
    takes = store.takes_of(item)
    by_shot: dict[str, list[dict[str, Any]]] = {}
    missing, stale = [], []
    for shot in shots:
        mark = stills.inputs_of(shot, brief)
        found = [
            {
                "id": t["id"], "kind": t["kind"], "item_id": t["item_id"], "mode": t["mode"],
                "seconds": t["seconds"], "prompt": t["prompt"], "created_at": t["created_at"],
                "out_of_date": t["inputs"] != mark, "chosen": chosen.get(shot["id"]) == t["id"],
            }
            for t in takes
            if t["shot_id"] == shot["id"]
        ]  # fmt: skip
        by_shot[shot["id"]] = found
        if not found:
            missing.append(shot["id"])
        elif any(t["chosen"] and t["out_of_date"] for t in found):
            stale.append(shot["id"])
    preview = store.preview_of(item)
    return {
        "takes": by_shot, "missing": missing, "out_of_date": stale, "run": store.run_of(item),
        "preview": {
            **{k: preview[k] for k in ("seconds", "empty_shots", "took_s", "created_at")},
            "rel": preview["rel"], "current": preview["mark"] == preview_mark(row, chosen),
        } if preview else None,
    }  # fmt: skip


def preview_mark(row: dict[str, Any], chosen: dict[str, str]) -> str:
    """Changes when the shots' times, cameras or chosen takes do, so an old preview can say so."""
    shots = (row["plan"] or {}).get("shots", [])
    body = [[s["id"], s["start"], s["end"], s["camera"], chosen.get(s["id"])] for s in shots]
    return hashlib.sha256(json.dumps(body).encode()).hexdigest()[:16]


def free_bytes(folder: Any) -> int:
    return shutil.disk_usage(folder).free


def _measured(takes: list[dict[str, Any]], mode: str) -> float | None:
    """How long a still of this kind takes on this computer, once there are some to go by."""
    made = [t["seconds"] for t in takes if t["mode"] == mode and t["seconds"]][-12:]
    return sum(made) / len(made) if made else None


def camera_filter(camera: str, frames: int, width: int, height: int) -> str:
    """A still with a camera move: a push in, a pan or a very slow drift."""
    z = f"min(1.0+0.10*on/{frames},1.10)" if "push" in camera else "1.04"
    x = f"(iw-iw/zoom)*on/{frames}" if "pan" in camera else "(iw-iw/zoom)/2"
    return (
        f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,crop={width * 2}:{height * 2},"
        f"zoompan=z='{z}':x='{x}':y='(ih-ih/zoom)/2':d={frames}:s={width}x{height}:fps={PREVIEW_FPS},setsar=1"
    )


def preview_command(
    ffmpeg: str,
    shots: list[dict[str, Any]],
    files: dict[str, tuple[str, Path]],
    song: Path,
    shape: str,
    out: Path,
) -> list[str]:
    """The ffmpeg call. Frames are counted from the song's start, so the cuts never drift from it."""
    width, height = PREVIEW_SIZES[shape]
    inputs: list[str] = []
    parts: list[str] = []
    labels: list[str] = []
    n = 0
    for shot in shots:
        frames = max(1, round(shot["end"] * PREVIEW_FPS) - round(shot["start"] * PREVIEW_FPS))
        length = f"{frames / PREVIEW_FPS:.4f}"
        found = files.get(shot["id"])
        label = f"v{len(labels)}"
        end = f"trim=end_frame={frames},setpts=PTS-STARTPTS,format=yuv420p[{label}]"
        if found is None:
            inputs += [
                "-f",
                "lavfi",
                "-t",
                length,
                "-i",
                f"color=c=black:s={width}x{height}:r={PREVIEW_FPS}",
            ]
            parts.append(f"[{n}:v]setsar=1,{end}")
        elif found[0] == "image":
            inputs += [
                "-loop",
                "1",
                "-framerate",
                str(PREVIEW_FPS),
                "-t",
                length,
                "-i",
                str(found[1]),
            ]
            parts.append(f"[{n}:v]{camera_filter(shot['camera'], frames, width, height)},{end}")
        else:
            inputs += ["-stream_loop", "-1", "-t", length, "-i", str(found[1])]
            parts.append(
                f"[{n}:v]fps={PREVIEW_FPS},scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1,{end}"
            )
        labels.append(f"[{label}]")
        n += 1
    graph = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=1:a=0[v]"
    return [
        ffmpeg, "-nostdin", "-v", "error", "-y", *inputs, "-i", str(song), "-filter_complex", graph,
        "-map", "[v]", "-map", f"{n}:a", "-t", f"{shots[-1]['end']:.3f}", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "26", "-r", str(PREVIEW_FPS), "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out),
    ]  # fmt: skip


class ShotJobs:
    """One stills run or preview at a time for a person; a plan being written waits for it too."""

    def __init__(
        self,
        deps: RouteDeps,
        store: Callable[[], CreativeStore],
        plan_busy: Callable[[Identity], str | None],
    ):
        self._deps = deps
        self._store = store
        self._plan_busy = plan_busy
        self._jobs: dict[str, tuple[str, asyncio.Task[None]]] = {}

    @staticmethod
    def _who(identity: Identity) -> str:
        return f"{identity.tenant_id}/{identity.user_id}"

    def active(self, identity: Identity) -> str | None:
        job = self._jobs.get(self._who(identity))
        return job[0] if job and not job[1].done() else None

    async def wait(self, identity: Identity, item: str) -> None:
        job = self._jobs.get(self._who(identity))
        if job and job[0] == item and not job[1].done():
            await asyncio.shield(job[1])

    async def stop_and_wait(self, identity: Identity, item: str) -> None:
        job = self._jobs.get(self._who(identity))
        if job and job[0] == item and not job[1].done():
            job[1].cancel()
            await asyncio.gather(job[1], return_exceptions=True)

    def _begin(
        self, identity: Identity, item: str, kind: str, stage: str, total: int, work: Any
    ) -> None:
        if self.active(identity) is not None:
            raise Refused(
                "busy", "Something is being made for a project. Wait for it, or stop it first."
            )
        if self._plan_busy(identity) is not None:
            raise Refused("busy", "A plan is being written. Wait for it, or stop it first.")
        store = self._store()
        store.begin_run(item, kind, stage, total)

        async def run() -> None:
            token = set_context(RunContext(identity.tenant_id, PRODUCT_ID, identity.user_id))
            try:
                await work()
                run = store.run_of(item)
                if run and run["status"] == "running":
                    store.end_run(item, "done", None)
            except asyncio.CancelledError:
                if not getattr(self._deps.state, "closing", False):
                    store.end_run(item, "stopped", None)
                raise
            except Refused as e:
                store.end_run(item, "failed", e.message)
            except Exception:
                log.exception("a run of shots failed")
                store.end_run(item, "failed", "It stopped on a problem. What was made is kept.")
            finally:
                reset_context(token)

        self._jobs[self._who(identity)] = (item, asyncio.create_task(run()))

    def _executor(self) -> Any:
        executor = self._deps.state.actions
        if executor is None:
            raise Refused("unavailable", "Pictures cannot be made here.")
        return executor

    async def readiness(self) -> dict[str, Any]:
        """Whether the picture model is here: the same words the image screen gives."""
        executor = self._executor()
        action = executor.registry.get("image.generate")
        if action is None:
            return {"ready": False, "step": "Pictures cannot be made here."}
        found = await executor.readiness(action)
        return {"ready": found.state == "ready", "step": found.step or found.reason or None}

    async def estimate(self, row: dict[str, Any], mode: str, redo: bool) -> dict[str, Any]:
        """The honest panel: how many shots at each motion level, the time as a range, the disk, whether it fits."""
        store = self._store()
        now = view(store, row)
        shots = (row["plan"] or {}).get("shots", [])
        count = len(now["missing"]) + (len(now["out_of_date"]) if redo else 0)
        portraits = (
            len(stills.needs_portraits(row["plan"], row["brief"]))
            if mode == stills.REFERENCE and row["plan"]
            else 0
        )
        folder = self._deps.state.desktop_dir or "."
        made = stills.estimate(
            count, portraits, mode, _measured(store.takes_of(row["id"]), mode),
            float(row["facts"].get("seconds", 0)), free_bytes(folder),
        )  # fmt: skip
        motions = {
            m: sum(1 for s in shots if s["motion"] == m) for m in ("Hold", "Animate", "Sing")
        }
        return {
            **made, "count": count, "portraits": portraits, "motions": motions,
            "missing": len(now["missing"]), "out_of_date": len(now["out_of_date"]),
            **await self.readiness(),
        }  # fmt: skip

    async def start_stills(
        self, identity: Identity, row: dict[str, Any], mode: str, redo: bool
    ) -> None:
        """Make what is missing, and what is out of date when `redo` says so. A step that cannot fit is refused."""
        if not row["plan"]:
            raise Refused("no_plan", "There is no plan yet.")
        ask = await self.estimate(row, mode, redo)
        if not ask["ready"]:
            raise Refused("needs_setup", ask["step"] or "The picture model is not set up yet.")
        if ask["fit"] == "too_big":
            raise Refused("too_big", "There is not enough room on the disk for these pictures.")
        now = view(self._store(), row)
        wanted = [*now["missing"], *(now["out_of_date"] if redo else [])]
        if not wanted:
            raise Refused("nothing", "Every shot has its still.")
        self._begin(
            identity, row["id"], "stills", "Getting ready", len(wanted),
            lambda: self._stills(identity, row["id"], wanted, mode, choose=True),
        )  # fmt: skip

    async def start_redo(
        self, identity: Identity, row: dict[str, Any], shot: str, mode: str
    ) -> None:
        """Another take of one shot. The old take stays, and the new one is chosen: the person asked for it."""
        if not any(s["id"] == shot for s in (row["plan"] or {}).get("shots", [])):
            raise Refused("not_found", "There is no such shot in this plan.")
        self._begin(
            identity, row["id"], "stills", "Getting ready", 1,
            lambda: self._stills(identity, row["id"], [shot], mode, choose=True),
        )  # fmt: skip

    async def _portraits(self, identity: Identity, item: str, mode: str) -> None:
        """People with words but no pictures get two, so every shot starts from the same face."""
        store = self._store()
        row = store.get(identity.tenant_id, identity.user_id, item)
        for person in stills.needs_portraits(row["plan"], row["brief"]):
            store.run_progress(item, f"Making pictures of {person['name']}", 0, 0)
            ids: list[str] = []
            for prompt in stills.portrait_prompts(person, row["brief"].get("style", "")):
                done = await self._executor().run_action(
                    "image.generate", {"prompt": prompt, "size": "square"}, "window", actor=identity, person_approved=True,
                )  # fmt: skip
                if done.status != "ok":
                    raise Refused("not_made", done.text or "A picture could not be made.")
                ids.append(done.output["image_id"])
                store.add_media(item, "image", done.output["image_id"], None, made=True)
            fresh = store.get(identity.tenant_id, identity.user_id, item)
            cast = [
                {**p, "pictures": ids} if p["name"] == person["name"] else p
                for p in fresh["brief"]["cast"]
            ]
            store.set_brief(item, fresh["title"], {**fresh["brief"], "cast": cast})
            store.keep_characters(identity.tenant_id, identity.user_id, cast)

    async def _stills(
        self, identity: Identity, item: str, wanted: list[str], mode: str, *, choose: bool
    ) -> None:
        store = self._store()
        if mode == stills.REFERENCE:
            await self._portraits(identity, item, mode)
        finished = failed = in_a_row = 0
        problem = ""
        for shot_id in wanted:
            row = store.get(
                identity.tenant_id, identity.user_id, item
            )  # afresh: the plan can change meanwhile
            shot = next((s for s in row["plan"]["shots"] if s["id"] == shot_id), None)
            if shot is None:
                finished += 1
                continue
            number = row["plan"]["shots"].index(shot) + 1
            store.run_progress(item, f"Making the still of shot {number}", finished, failed)
            ask = stills.still_for(shot, row["brief"], mode)
            started = time.monotonic()
            done = await self._executor().run_action(
                ask.action, ask.params, "window", actor=identity, person_approved=True
            )
            if done.status == "ok" and done.output.get("image_id"):
                in_a_row = 0
                image = done.output["image_id"]
                store.add_media(item, "image", image, shot_id, made=True)
                store.add_take(
                    item, shot_id, "image", image, stills.inputs_of(shot, row["brief"]), ask.prompt, ask.mode,
                    round(time.monotonic() - started, 1), row["revision"], choose=choose,
                )  # fmt: skip
            else:
                failed += 1
                in_a_row += 1
                problem = done.text or "A still could not be made."
                if done.status == "needs_setup" or in_a_row >= GIVE_UP_AFTER:
                    store.end_run(item, "failed", f"{problem} What was made is kept.")
                    return
            finished += 1
            store.run_progress(item, "", finished, failed)
        if failed:
            store.end_run(item, "failed", f"{failed} could not be made: {problem} Try those again.")

    def start_preview(self, identity: Identity, row: dict[str, Any]) -> None:
        if not row["plan"]:
            raise Refused("no_plan", "There is no plan yet.")
        if not self._store().chosen_of(row["id"]):
            raise Refused("nothing", "There are no stills to join yet.")
        self._begin(
            identity, row["id"], "preview", "Joining the shots over the song", 1,
            lambda: self._preview(identity, row["id"]),
        )  # fmt: skip

    async def _preview(self, identity: Identity, item: str) -> None:
        store = self._store()
        storage = self._deps.storage
        executor = self._executor()
        if storage is None:
            raise Refused("unavailable", "File storage is not available.")
        row = store.get(identity.tenant_id, identity.user_id, item)
        shots = row["plan"]["shots"]
        chosen = store.chosen_of(item)
        takes = {t["id"]: t for t in store.takes_of(item)}
        ctx = SimpleNamespace(deps=self._deps, actor=identity, executor=executor)
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="wasifyai-preview-") as tmp:
            folder = Path(tmp)
            files: dict[str, tuple[str, Path]] = {}
            for shot in shots:
                take = takes.get(chosen.get(shot["id"], ""))
                kind = executor.library.get(take["kind"]) if take else None
                data = (
                    await kind.read(ctx, take["item_id"]) if take and kind and kind.read else None
                )
                if data is None or take is None:
                    continue  # no still yet, or it was deleted from the Library: this shot is black
                path = folder / f"{shot['id']}.{'png' if take['kind'] == 'image' else 'mp4'}"
                await asyncio.to_thread(path.write_bytes, data)
                files[shot["id"]] = (take["kind"], path)
            tracks = executor.library.get("track")
            song = (
                await tracks.read(ctx, row["brief"]["track_id"]) if tracks and tracks.read else None
            )
            if song is None:
                raise Refused("no_song", "The song is not in Your music any more.")
            song_path = folder / "song"
            await asyncio.to_thread(song_path.write_bytes, song)
            out = folder / "preview.mp4"
            command = preview_command(
                imageio_ffmpeg.get_ffmpeg_exe(),
                shots,
                files,
                song_path,
                row["brief"].get("shape", "landscape"),
                out,
            )
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
            try:
                _, err = await asyncio.wait_for(process.communicate(), FFMPEG_TIMEOUT_S)
            except BaseException:
                process.kill()
                await process.wait()
                raise
            if process.returncode != 0:
                log.warning(
                    "the preview could not be joined: %s", err.decode(errors="replace")[-800:]
                )
                raise Refused("not_made", "The shots could not be joined.")
            data = await asyncio.to_thread(out.read_bytes)
        owner = (identity.tenant_id, PRODUCT_ID, identity.user_id)
        rel = f"previews/{item}/{int(time.time())}.mp4"
        old = store.preview_of(item)
        await storage.put_for(owner, rel, data, "video/mp4")
        store.set_preview(
            item, rel, preview_mark(row, chosen), float(shots[-1]["end"]), len(shots) - len(files),
            round(time.monotonic() - started, 1),
        )  # fmt: skip
        if old and old["rel"] != rel:
            await storage.delete_for(owner, old["rel"])
