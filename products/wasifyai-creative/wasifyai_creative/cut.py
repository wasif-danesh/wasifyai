# ruff: noqa: E501  (prose and test data are easier to read on one line)
"""The Cut step (ADR-0090 decision 7): a small, real timeline. One picture track (the shots in order, each showing its chosen version,
or something of the project's put in by hand), the song, and a caption track (the song's lines, and titles). The person can reorder,
lengthen or shorten by beats, split, fade, move a caption, undo and redo. The document refers to media and never changes it; making the
video always writes a new file.

Everything here is pure: the document, its edits, the captions file and the ffmpeg call, so all of it is tested without a model."""

import hashlib
import json
import re
from bisect import bisect_left
from pathlib import Path
from typing import Any

SHORTEST_S = 0.5
FADE_S = 0.3
FPS = 24
SIZES = {"landscape": (1920, 1080), "portrait": (1080, 1920), "square": (1080, 1080)}
CAPTION_KINDS = ("line", "title", "lower")
MAX_CAPTION = 160


class CutRefused(ValueError):
    """An edit that cannot be made, with the sentence the person is shown."""


def _new_id(prefix: str, taken: list[dict[str, Any]]) -> str:
    numbers = [int(x["id"][1:]) for x in taken if re.fullmatch(rf"{prefix}\d+", x["id"])]
    return f"{prefix}{max(numbers, default=0) + 1}"


def default_cut(plan: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    """The cut a plan starts as: every shot for its planned length, and the song's lines where they were sung."""
    items = [
        {
            "id": f"c{i + 1}",
            "shot_id": s["id"],
            "length": round(s["end"] - s["start"], 3),
            "fade": False,
            "source": None,
        }
        for i, s in enumerate(plan["shots"])
    ]
    lines = [
        x
        for x in ((facts.get("lines") or []) if facts.get("lines_timed", True) else [])
        if x.get("start") is not None and x.get("end") is not None and x.get("text")
    ]
    captions = [
        {
            "id": f"t{i + 1}",
            "kind": "line",
            "text": x["text"][:MAX_CAPTION],
            "start": round(float(x["start"]), 3),
            "end": round(float(x["end"]), 3),
        }
        for i, x in enumerate(lines)
    ]
    return {
        "items": items,
        "captions": captions,
        "captions_on": bool(captions),
        "from_plan": plan_key(plan),
    }


def plan_key(plan: dict[str, Any]) -> list[list[Any]]:
    """The shots and their lengths a cut was made from, so the screen can say when the plan has changed since."""
    return [[s["id"], round(s["end"] - s["start"], 3)] for s in plan["shots"]]


def captions_of(cut: dict[str, Any] | None) -> str:
    """The cut's titles and captions as typed (CS3): what the person wrote is searchable too."""
    return " ".join(c["text"] for c in (cut or {}).get("captions", []) if c.get("kind") != "line")


def timeline(cut: dict[str, Any]) -> list[dict[str, Any]]:
    """Each item with where it starts: one after another from the start of the song."""
    at, out = 0.0, []
    for item in cut["items"]:
        out.append({**item, "start": round(at, 3), "end": round(at + item["length"], 3)})
        at += item["length"]
    return out


def _snap(t: float, beats: list[float]) -> float:
    if not beats:
        return round(t, 3)
    i = bisect_left(beats, t)
    near = [b for b in beats[max(0, i - 1) : i + 1]]
    return round(min(near, key=lambda b: abs(b - t)), 3)


def _beat_moved(t: float, by: int, beats: list[float]) -> float:
    """`t` moved by whole beats, from the beat nearest it."""
    if not beats:
        return round(t + 0.5 * by, 3)
    i = min(range(len(beats)), key=lambda k: abs(beats[k] - t))
    return round(beats[max(0, min(len(beats) - 1, i + by))], 3)


def _item(cut: dict[str, Any], item_id: str) -> int:
    for i, x in enumerate(cut["items"]):
        if x["id"] == item_id:
            return i
    raise CutRefused("There is no such piece in the cut.")


def _caption(cut: dict[str, Any], caption_id: str) -> int:
    for i, x in enumerate(cut["captions"]):
        if x["id"] == caption_id:
            return i
    raise CutRefused("There is no such caption.")


def apply_cut_edits(
    cut: dict[str, Any],
    edits: list[dict[str, Any]],
    beats: list[float],
    song_s: float,
    song_lines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The cut after `edits`, in order. One edit that cannot be made refuses them all, and nothing changes."""
    new = json.loads(json.dumps(cut))
    for e in edits:
        op = e.get("op")
        items = new["items"]
        if op == "move":
            i = _item(new, e["item_id"])
            to = int(e["to"])
            if not 0 <= to < len(items):
                raise CutRefused("It cannot move there.")
            items.insert(to, items.pop(i))
        elif op == "length":
            i = _item(new, e["item_id"])
            start = timeline(new)[i]["start"]
            end = start + items[i]["length"]
            if "by_beats" in e:
                end = _beat_moved(end, int(e["by_beats"]), beats)
            else:
                end = _snap(start + float(e["seconds"]), beats)
            if end - start < SHORTEST_S:
                raise CutRefused(f"A piece is at least {SHORTEST_S} seconds long.")
            items[i]["length"] = round(end - start, 3)
        elif op == "split":
            i = _item(new, e["item_id"])
            start = timeline(new)[i]["start"]
            at = _snap(start + float(e.get("at", items[i]["length"] / 2)), beats) - start
            if at < SHORTEST_S or items[i]["length"] - at < SHORTEST_S:
                at = items[i]["length"] / 2
            if at < SHORTEST_S:
                raise CutRefused("That piece is too short to split.")
            second = {
                **items[i],
                "id": _new_id("c", items),
                "length": round(items[i]["length"] - at, 3),
                "fade": False,
            }
            items[i]["length"] = round(at, 3)
            items.insert(i + 1, second)
        elif op == "fade":
            items[_item(new, e["item_id"])]["fade"] = bool(e["fade"])
        elif op == "remove":
            if len(items) == 1:
                raise CutRefused("The cut needs at least one piece.")
            items.pop(_item(new, e["item_id"]))
        elif op == "insert":
            at = _item(new, e["after"]) + 1 if e.get("after") else 0
            if e.get("kind") not in ("image", "video"):
                raise CutRefused("Only a picture or a clip can go on the picture track.")
            length = max(SHORTEST_S, float(e.get("length", 2.0)))
            items.insert(at, {"id": _new_id("c", items), "shot_id": None, "length": round(length, 3), "fade": False,
                              "source": {"kind": e["kind"], "item_id": str(e["item_id"])}})  # fmt: skip
        # the shot's chosen version again, or something of the project in its place
        elif op == "use":
            i = _item(new, e["item_id"])
            items[i]["source"] = (
                {"kind": e["kind"], "item_id": str(e["source_id"])} if e.get("source_id") else None
            )
        elif op == "caption":
            i = _caption(new, e["caption_id"])
            c = new["captions"][i]
            if "text" in e:
                c["text"] = str(e["text"]).strip()[:MAX_CAPTION]
            if "by_beats" in e:
                length = c["end"] - c["start"]
                c["start"] = _beat_moved(c["start"], int(e["by_beats"]), beats)
                c["end"] = round(c["start"] + length, 3)
            if "start" in e:
                c["start"] = round(float(e["start"]), 3)
            if "end" in e:
                c["end"] = round(float(e["end"]), 3)
        elif op == "add_caption":
            kind = e.get("kind", "line")
            if kind not in CAPTION_KINDS:
                raise CutRefused("A caption is a line, a title or a lower third.")
            new["captions"].append({
                "id": _new_id("t", new["captions"]), "kind": kind, "text": str(e.get("text", "")).strip()[:MAX_CAPTION],
                "start": round(float(e["start"]), 3), "end": round(float(e["end"]), 3),
            })  # fmt: skip
            new["captions"].sort(key=lambda c: c["start"])
            if kind == "line":
                new["captions_on"] = True
        elif op == "remove_caption":
            new["captions"].pop(_caption(new, e["caption_id"]))
        elif op == "captions":
            new["captions_on"] = bool(e["on"])
        elif op == "song_lines":  # the song's words where they were sung, again; titles stay
            if not song_lines:
                raise CutRefused("The times of the song's words are not known.")
            kept = [c for c in new["captions"] if c["kind"] != "line"]
            lines = default_cut({"shots": []}, {"lines": song_lines})["captions"]
            for c in lines:
                c["id"] = _new_id("t", kept)
                kept.append(c)
            new["captions"] = sorted(kept, key=lambda c: c["start"])
            new["captions_on"] = True
        else:
            raise CutRefused(f"Unknown change: {op}.")
    wrong = cut_problems(new, song_s)
    if wrong:
        raise CutRefused(wrong[0])
    return new


def cut_problems(cut: dict[str, Any], song_s: float) -> list[str]:
    found = []
    for item in cut["items"]:
        if item["length"] < SHORTEST_S - 1e-6:
            found.append(f"A piece is at least {SHORTEST_S} seconds long.")
    for c in cut["captions"]:
        if not c["text"]:
            found.append("A caption needs some words.")
        if not 0 <= c["start"] < c["end"] <= song_s + 0.01:
            found.append("A caption must start before it ends, inside the song.")
    return found


def summary(cut: dict[str, Any], plan: dict[str, Any], song_s: float) -> dict[str, Any]:
    """What the screen says about the cut as a whole."""
    end = sum(x["length"] for x in cut["items"])
    return {
        "pictures_end": round(end, 3),
        "song_s": song_s,
        "black_tail": round(max(0.0, song_s - end), 3),
        "cut_short": round(max(0.0, end - song_s), 3),
        "plan_changed": cut.get("from_plan") != plan_key(plan),
    }


# ---- captions as a subtitles file -------------------------------------------------------------


def _clock(t: float) -> str:
    cs = max(0, round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _escape(text: str) -> str:
    """Words as words: braces start an override in this format, and a backslash a command."""
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def ass_of(cut: dict[str, Any], shape: str) -> str:
    width, height = SIZES[shape]
    big = round(height * (0.06 if shape == "landscape" else 0.04))
    rows = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: line,Helvetica Neue,{big},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,{max(2, big // 20)},1,2,{width // 12},{width // 12},{height // 14},1",
        f"Style: title,Helvetica Neue,{big * 2},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,{max(2, big // 12)},2,5,{width // 10},{width // 10},0,1",
        f"Style: lower,Helvetica Neue,{round(big * 0.9)},&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,1,0,0,0,100,100,0,0,3,{max(6, big // 4)},0,1,{width // 16},{width // 16},{height // 8},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]  # fmt: skip
    for c in cut["captions"]:
        if c["kind"] == "line" and not cut.get("captions_on", True):
            continue
        rows.append(
            f"Dialogue: 0,{_clock(c['start'])},{_clock(c['end'])},{c['kind']},,0,0,0,,{_escape(c['text'])}"
        )
    return "\n".join(rows) + "\n"


# ---- the video ----------------------------------------------------------------------------------


def mark_of(pieces: list[dict[str, Any]], cut: dict[str, Any], shape: str) -> str:
    """Changes when anything that is drawn changes, so an old video can say so."""
    body: list[Any] = [
        [p["start"], p["end"], p.get("kind"), p.get("item_id"), p.get("camera"), p.get("fade")]
        for p in pieces
    ]
    body.append(ass_of(cut, shape))
    return hashlib.sha256(json.dumps(body).encode()).hexdigest()[:16]


def camera_filter(camera: str, frames: int, width: int, height: int) -> str:
    """A still with a camera move: a push in, a pan or a very slow drift."""
    z = f"min(1.0+0.10*on/{frames},1.10)" if "push" in camera else "1.04"
    x = f"(iw-iw/zoom)*on/{frames}" if "pan" in camera else "(iw-iw/zoom)/2"
    return (
        f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,crop={width * 2}:{height * 2},"
        f"zoompan=z='{z}':x='{x}':y='(ih-ih/zoom)/2':d={frames}:s={width}x{height}:fps={FPS},setsar=1"
    )


def render_command(
    ffmpeg: str,
    pieces: list[dict[str, Any]],
    song: Path,
    song_s: float,
    captions: Path | None,
    size: tuple[int, int],
    out: Path,
    draft: bool = False,
) -> list[str]:
    """The ffmpeg call. `pieces` is the timeline with each piece's file: a picture gets its camera move, a clip is
    trimmed (looped if short), a piece with no file is black. Frames are counted from the song's start, so the cuts
    cannot drift; the pictures end where the song does, with black after the last piece if they are shorter. A
    draft (the Shots step's preview) is quicker and smaller."""
    width, height = size
    preset, crf, audio = ("veryfast", "26", "160k") if draft else ("medium", "20", "192k")
    inputs: list[str] = []
    parts: list[str] = []
    labels: list[str] = []
    shown = [p for p in pieces if p["start"] < song_s - 1 / FPS]
    if shown and shown[-1]["end"] < song_s:
        shown.append(
            {
                "start": shown[-1]["end"],
                "end": song_s,
                "kind": None,
                "path": None,
                "fade": False,
                "camera": "",
            }
        )
    for n, p in enumerate(shown):
        end = min(p["end"], song_s)
        frames = max(1, round(end * FPS) - round(p["start"] * FPS))
        length = f"{frames / FPS:.4f}"
        fade = ""
        if p.get("fade"):
            fade += f",fade=t=in:st=0:d={FADE_S}"
        if n + 1 < len(shown) and shown[n + 1].get("fade"):
            fade += f",fade=t=out:st={max(0.0, frames / FPS - FADE_S):.4f}:d={FADE_S}"
        tail = f"trim=end_frame={frames},setpts=PTS-STARTPTS{fade},format=yuv420p[v{n}]"
        if not p.get("path"):
            inputs += [
                "-f",
                "lavfi",
                "-t",
                length,
                "-i",
                f"color=c=black:s={width}x{height}:r={FPS}",
            ]
            parts.append(f"[{n}:v]setsar=1,{tail}")
        elif p["kind"] == "image":
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", length, "-i", str(p["path"])]
            parts.append(
                f"[{n}:v]{camera_filter(p.get('camera') or '', frames, width, height)},{tail}"
            )
        else:
            inputs += ["-stream_loop", "-1", "-t", length, "-i", str(p["path"])]
            parts.append(
                f"[{n}:v]fps={FPS},scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,{tail}"
            )
        labels.append(f"[v{n}]")
    graph = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=1:a=0[joined]"
    graph += f";[joined]ass=filename={captions.name}[v]" if captions else ";[joined]null[v]"
    return [
        ffmpeg, "-nostdin", "-v", "error", "-y", *inputs, "-i", str(song), "-filter_complex", graph,
        "-map", "[v]", "-map", f"{len(shown)}:a", "-t", f"{song_s:.3f}", "-c:v", "libx264", "-preset", preset,
        "-crf", crf, "-r", str(FPS), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", audio, "-movflags", "+faststart", str(out),
    ]  # fmt: skip
