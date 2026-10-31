# ruff: noqa: ASYNC221  (the tests run ffmpeg and ffprobe on purpose)
"""The five Motion graphics templates through the real sandboxed browser (MG1).

Every template is written to a project folder with the shipped fonts, seen by the real pinned
browser, compared with the words that were typed, and drawn to a file. What is proved here and
cannot be on stand-ins: the fonts load, 20 hostile slot cases fit the safe area, a retyped or
clipped word is caught, and the transparent files decode with a real alpha channel.

Skipped unless a component is installed: set `WASIFYAI_VIDEO_BUILDER_HOME` to
`<app data>/components/video-builder` (CI installs it with `scripts/ci-video-builder.py`)."""

import array
import cmath
import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from wasifyai_api import video_builder_runtime as vb
from wasifyai_api.desktop_video_builder import VideoBuilderService
from wasifyai_platform_sdk import (
    EngineServices,
    Identity,
    RouteDeps,
    ScopedStorage,
    memory_storage,
)
from wasifyai_platform_sdk.actions import ActionExecutor, ActionRegistry, builtin_actions
from wasifyai_platform_sdk.actions.testing import FakeActionHost
from wasifyai_platform_sdk.sqlite import create_sqlite_engine
from wasifyai_video.actions import actions, library_kinds
from wasifyai_video.builder import check, media, projects, templates
from wasifyai_video.builder.store import BuilderStore
from wasifyai_video.videos import video_store

INSTALL = vb.find_install(Path("/nonexistent"))
pytestmark = pytest.mark.skipif(
    INSTALL is None or len(vb.find_media_tools(INSTALL)) < len(vb.MEDIA_TOOLS),
    reason="Motion graphics or FFmpeg (with ffprobe) is not installed",
)

SAMPLES: dict[str, dict[str, Any]] = {
    "title": {"title": "Launch day", "subtitle": "Wasify AI is here"},
    "quote": {"quote": "The best way to predict the future is to invent it.", "author": "Alan Kay"},
    "chart": {
        "title": "Sales by region",
        "data": "North, 120\nSouth, $95\nEast, 45%\nWest, 1,200.5",
    },
    "lower_third": {"name": "Maya Chen", "role": "Head of Design"},
    "captions": {"lines": "Hello there\nThis is a caption\nAnd another one"},
}

LONG = "Maximilian Montgomery-Featherstonehaugh of Westmorland"
BENGALI = "মায়া চেন — ডিজাইন প্রধান"
# 20 cases: long names, the characters that break markup, Bengali ink, shapes and letters
CASES: list[tuple[str, dict[str, Any]]] = [
    ("lower_third", {"name": LONG, "role": "Head of Design and Brand Experience at Wasify AI"}),
    ("lower_third", {"name": "Tom & Jerry", "role": '<b>"Chief"</b> > Fun'}),
    ("lower_third", {"name": BENGALI, "role": BENGALI}),
    ("lower_third", {"name": "Maya Chen", "role": "", "shape": "portrait"}),
    ("lower_third", {"name": "Zoë Ñandú Çelik", "role": "Ørsted & Søn", "shape": "square"}),
    ("title", {"title": LONG, "subtitle": "x" * 100}),
    ("title", {"title": '<script>alert("x")</script> & more', "subtitle": "a < b > c"}),
    ("title", {"title": BENGALI, "subtitle": BENGALI, "font": "serif"}),
    ("title", {"title": "Launch day", "subtitle": "", "shape": "portrait"}),
    ("title", {"title": "W" * 80, "subtitle": "", "shape": "square"}),
    ("quote", {"quote": "Make it simple. " * 12, "author": LONG}),
    ("quote", {"quote": 'She said "yes" & left <quickly>.', "author": "O'Neil"}),
    ("quote", {"quote": BENGALI * 4, "author": BENGALI}),
    ("quote", {"quote": "Short.", "author": "", "shape": "portrait"}),
    ("chart", {"title": LONG, "data": "A very long label for it, 1\nB, 2"}),
    ("chart", {"title": "R&D <2026>", "data": 'Q&A, 10\n"Quoted", 20\nA < B, 30'}),
    ("chart", {"title": BENGALI, "data": "ঢাকা, 120\nচট্টগ্রাম, 95"}),
    ("chart", {"title": "Eight", "data": "\n".join(f"Row {n}, {n * 11}" for n in range(1, 9))}),
    ("captions", {"lines": f'{LONG}\n{BENGALI}\nTom & Jerry\n<i>"hi"</i>', "per_line": "4"}),
    ("captions", {"lines": "One\nTwo", "per_line": "2", "shape": "portrait"}),
]


@pytest.fixture(scope="module")
def engine() -> VideoBuilderService:
    return VideoBuilderService(Path("/nonexistent"))


def write(tmp: Path, engine: VideoBuilderService, template: str, fields: dict[str, Any]):
    slots = templates.normalize_slots(template, fields)
    folder = projects.project_dir(tmp, "t", "u", "a" * 32)
    gsap = engine.gsap()
    assert gsap is not None
    fonts = engine.fonts(templates.FONT_FILES)
    assert set(fonts) == set(templates.FONT_FILES)
    projects.write_project(folder, template, slots, gsap, fonts)
    return folder, slots


async def checked(engine, folder: Path, template: str, slots: dict[str, Any]) -> dict[str, Any]:
    return await check.run_check(engine, folder, template, slots)


def tool(name: str) -> str:
    """The component's own ffmpeg or ffprobe, as a render uses it (never the computer's)."""
    assert INSTALL is not None
    return vb.find_media_tools(INSTALL)[name]


def probe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        [tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=codec_name,width,height,pix_fmt,nb_read_frames:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return json.loads(out)


def first_frame_rgba(path: Path, decoder: str | None = None) -> tuple[int, int, bytes]:
    info = probe(path)["streams"][0]
    cmd = [tool("ffmpeg"), "-v", "error"]
    if decoder:
        cmd += ["-c:v", decoder]
    cmd += ["-i", str(path), "-frames:v", "1", "-pix_fmt", "rgba", "-f", "rawvideo", "-"]
    data = subprocess.run(cmd, capture_output=True, check=True).stdout
    return info["width"], info["height"], data


def alpha_of(width: int, height: int, data: bytes) -> list[int]:
    assert len(data) == width * height * 4
    return list(data[3::4])


# ---- every template: the words are checked, then drawn ---------------------------------------


@pytest.mark.parametrize("template", list(SAMPLES))
async def test_each_template_passes_the_check_and_is_drawn(tmp_path, engine, template):
    folder, slots = write(tmp_path, engine, template, SAMPLES[template])
    assert engine.lint(folder) == []
    report = await checked(engine, folder, template, slots)
    assert report["ok"], report["message"]
    assert report["checked"] == len(templates.expected(template, slots))
    out = tmp_path / "out.mp4"
    result = await engine.render(folder, out, extra_args=("--format", "mp4"))
    assert result.ok, result.message
    info = probe(out)
    seconds = float(info["format"]["duration"])
    assert abs(seconds - slots["seconds"]) < 0.5
    assert info["streams"][0]["codec_name"] == "h264"


async def test_the_shipped_fonts_actually_load(tmp_path, engine):
    folder, slots = write(tmp_path, engine, "quote", {**SAMPLES["quote"], "font": "serif"})
    report = await engine.inspect(folder, check.spec_for("quote", slots))
    assert report["ok"], report["message"]
    loaded = " ".join(report["fonts"])
    assert "Source Serif 4" in loaded and ":loaded" in loaded
    assert ":error" not in loaded


# ---- 20 hostile slot cases --------------------------------------------------------------------


@pytest.mark.parametrize(
    "case", range(len(CASES)), ids=[f"{t}-{i}" for i, (t, _) in enumerate(CASES)]
)
async def test_hostile_slots_are_shown_exactly_and_inside_the_safe_area(tmp_path, engine, case):
    template, fields = CASES[case]
    folder, slots = write(tmp_path, engine, template, fields)
    assert engine.lint(folder) == []
    report = await checked(engine, folder, template, slots)
    assert report["ok"], report["message"]


# ---- the check catches what it is for ------------------------------------------------------------


async def test_a_retyped_name_is_caught_and_said_in_words(tmp_path, engine):
    folder, slots = write(tmp_path, engine, "lower_third", SAMPLES["lower_third"])
    page = folder / "index.html"
    page.write_text(page.read_text().replace(">Maya Chen<", ">Maya Chan<"))
    report = await checked(engine, folder, "lower_third", slots)
    assert report["ok"] is False
    assert {p["code"] for p in report["problems"]} == {"text_mismatch"}
    assert "Maya Chan" in report["message"] and "Maya Chen" in report["message"]


async def test_a_word_that_is_cut_off_or_pushed_out_of_the_frame_is_caught(tmp_path, engine):
    folder, slots = write(tmp_path, engine, "title", SAMPLES["title"])
    page = folder / "index.html"
    squeeze = "<style>[data-slot]{max-width:40px;overflow:hidden;white-space:nowrap}</style>"
    page.write_text(page.read_text().replace("</head>", squeeze + "</head>"))
    report = await checked(engine, folder, "title", slots)
    assert report["ok"] is False
    assert {p["code"] for p in report["problems"]} & {"clipped", "outside_safe_area"}


async def test_a_word_that_is_never_drawn_is_caught(tmp_path, engine):
    folder, slots = write(tmp_path, engine, "title", SAMPLES["title"])
    page = folder / "index.html"
    page.write_text(
        page.read_text().replace(
            "</head>", "<style>[data-slot]{opacity:0!important}</style></head>"
        )
    )
    report = await checked(engine, folder, "title", slots)
    assert report["ok"] is False
    assert {p["code"] for p in report["problems"]} & {"hidden", "not_drawn"}


# ---- transparent files carry a real alpha channel ----------------------------------------


async def test_the_lower_third_webm_decodes_with_real_alpha(tmp_path, engine):
    folder, slots = write(tmp_path, engine, "lower_third", SAMPLES["lower_third"])
    out = tmp_path / "third.webm"
    result = await engine.render(folder, out, extra_args=("--format", "webm"))
    assert result.ok, result.message
    # the default decoder drops the alpha of a VP9 file; libvpx-vp9 keeps it
    width, height, data = first_frame_rgba(out, "libvpx-vp9")
    alpha = alpha_of(width, height, data)
    assert min(alpha) == 0 and max(alpha) == 255
    assert alpha[0] == 0 and alpha[-1] == 0  # the corners are clear
    assert 0.001 < sum(1 for a in alpha if a) / len(alpha) < 0.5  # a bar, not the whole frame


async def test_the_lower_third_mov_decodes_with_real_alpha(tmp_path, engine):
    folder, slots = write(tmp_path, engine, "lower_third", SAMPLES["lower_third"])
    out = tmp_path / "third.mov"
    result = await engine.render(folder, out, extra_args=("--format", "mov"))
    assert result.ok, result.message
    width, height, data = first_frame_rgba(out)
    alpha = alpha_of(width, height, data)
    assert min(alpha) == 0 and max(alpha) == 255 and alpha[0] == 0
    assert probe(out)["streams"][0]["codec_name"] == "prores"


async def test_the_opaque_templates_have_no_clear_pixels(tmp_path, engine):
    folder, slots = write(tmp_path, engine, "title", SAMPLES["title"])
    out = tmp_path / "title.mp4"
    result = await engine.render(folder, out, extra_args=("--format", "mp4"))
    assert result.ok, result.message
    width, height, data = first_frame_rgba(out)
    assert min(alpha_of(width, height, data)) == 255


# ---- the longest video ----------------------------------------------------------


@pytest.mark.parametrize(("template", "fmt"), [("title", "mp4"), ("lower_third", "webm")])
async def test_a_90_second_video_is_made_in_a_minute_and_holds_the_same_memory(
    tmp_path, engine, template, fmt
):
    folder, slots = write(tmp_path, engine, template, {**SAMPLES[template], "seconds": 90})
    out = tmp_path / f"long.{fmt}"
    result = await engine.render(folder, out, extra_args=("--format", fmt))
    assert result.ok, result.message
    assert abs(float(probe(out)["format"]["duration"]) - 90) < 0.5
    # 14 to 33 s on an M5 Pro (a slower Mac has room); a CI runner has no GPU: about 7 minutes
    assert result.seconds < (900 if os.environ.get("CI") else 120)
    assert result.peak_rss_bytes < 3.5 * 2**30  # 2.0 to 2.3 GB measured at 30, 60 and 90 seconds


# ---- a project of scenes (ADR-0096): one page through the same sandbox and check ----------------

FILM: dict[str, Any] = {
    "name": "Northbean launch",
    "scenes": [
        {"kind": "title", "fields": {"title": "Mornings are hard.", "theme": "forest",
                                     "seconds": 3}},
        {"kind": "quote", "fields": {"quote": "Smooth, not bitter.", "author": "A customer",
                                     "theme": "sunrise", "seconds": 4}},
        {"kind": "chart", "fields": {"title": "Sales", "data": "North, 120\nSouth, 95",
                                     "theme": "paper", "seconds": 5}},
        {"kind": "lower_third", "fields": {"name": "Maya Chen", "role": "Founder", "seconds": 3}},
        {"kind": "captions", "fields": {"lines": "One line\nAnother line", "per_line": "2",
                                        "theme": "paper"}},
    ],
}  # fmt: skip


def frame_at(path: Path, at: float) -> tuple[int, int, bytes]:
    info = probe(path)["streams"][0]
    data = subprocess.run(
        [tool("ffmpeg"), "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1",
         "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    return info["width"], info["height"], data


def corner(frame: tuple[int, int, bytes]) -> tuple[int, ...]:
    """The colour just inside the top left: the scene's background, away from any words."""
    width, _, data = frame
    at = (8 * width + 8) * 3
    return tuple(data[at : at + 3])


async def test_a_film_passes_the_check_and_each_scene_is_drawn_in_its_own_time(tmp_path, engine):
    folder, slots = write(tmp_path, engine, templates.SCENES, FILM)
    assert engine.lint(folder) == []
    report = await checked(engine, folder, templates.SCENES, slots)
    assert report["ok"], report["message"]
    assert report["checked"] == len(templates.expected(templates.SCENES, slots)) > 8
    out = tmp_path / "film.mp4"
    result = await engine.render(folder, out, extra_args=("--format", "mp4"))
    assert result.ok, result.message
    assert result.blocked == []
    assert abs(float(probe(out)["format"]["duration"]) - slots["seconds"]) < 0.5
    colours = [corner(frame_at(out, t)) for t in (1.5, 5.0, 9.5, 13.5, 16.0)]
    assert len(set(colours)) >= 4, (
        colours
    )  # each scene shows its own background, not the last one's


async def test_the_check_catches_a_wrong_word_in_a_later_scene(tmp_path, engine):
    folder, slots = write(tmp_path, engine, templates.SCENES, FILM)
    page = projects.read_page(folder)
    (folder / "index.html").write_text(page.replace("Smooth, not bitter.", "Smooth and bitter."))
    report = await checked(engine, folder, templates.SCENES, slots)
    assert not report["ok"] and "Smooth and bitter." in report["message"]


@pytest.mark.parametrize("case", range(len(CASES)))
async def test_each_hard_case_passes_as_a_scene_of_a_film(tmp_path, engine, case):
    kind, fields = CASES[case]
    fields = dict(fields)
    shape, font = fields.pop("shape", "landscape"), fields.pop("font", "sans")
    film = {"shape": shape, "font": font, "scenes": [
        {"kind": "title", "fields": {"title": "First", "seconds": 3}},
        {"kind": kind, "fields": fields},
    ]}  # fmt: skip
    folder, slots = write(tmp_path, engine, templates.SCENES, film)
    report = await checked(engine, folder, templates.SCENES, slots)
    assert report["ok"], report["message"]


@pytest.mark.parametrize("template", list(SAMPLES))
async def test_a_template_looks_the_same_as_one_scene(tmp_path, engine, template):
    folder, slots = write(tmp_path / "a", engine, template, {**SAMPLES[template], "seconds": 5})
    one = templates.as_scenes(template, slots)
    scene_folder, scene_slots = write(tmp_path / "b", engine, templates.SCENES, one)
    report = await checked(engine, scene_folder, templates.SCENES, scene_slots)
    assert report["ok"], report["message"]
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    assert (await engine.render(folder, a, extra_args=("--format", "mp4"))).ok
    assert (await engine.render(scene_folder, b, extra_args=("--format", "mp4"))).ok
    at = templates.preview_times(template, slots)[2]
    _, _, x = frame_at(a, at)
    _, _, y = frame_at(b, at)
    assert len(x) == len(y)
    far = sum(abs(p - q) > 24 for p, q in zip(x, y, strict=True))
    assert far / len(x) < 0.005, f"{far} of {len(x)} values differ"


def _reachable_postgres() -> str | None:
    """The deployment's Postgres, when there is one to test on (`make dev`)."""
    url = os.environ.get("BUILDER_TEST_DATABASE_URL")
    return url or None


@pytest.fixture(params=["sqlite", "postgres"])
def film_store(request, tmp_path):
    if request.param == "sqlite":
        store = BuilderStore.in_folder(tmp_path / "builder")
        yield store
        store.close()
        return
    url = _reachable_postgres()
    if url is None:
        pytest.skip("set BUILDER_TEST_DATABASE_URL to run this on Postgres")
    store = BuilderStore.on_postgres(url, schema="builder_t_" + uuid4().hex[:8])
    yield store
    store.drop_schema()
    store.close()


async def test_a_film_is_written_changed_and_made_through_the_actions_in_the_real_sandbox(
    tmp_path, engine, film_store
):
    database = create_sqlite_engine(tmp_path / "wasifyai.db")
    me = Identity("t1", "u1")
    state = EngineServices(
        engine=database, storage=ScopedStorage(memory_storage()), desktop_dir=tmp_path,
        video_builder=engine, creation_index=None, builder_store=film_store,
    )  # fmt: skip
    host = FakeActionHost(RouteDeps(state, lambda: me))
    run = ActionExecutor(
        ActionRegistry([*builtin_actions(), *actions()]), host,
        library={k.kind: k for k in library_kinds()},
    ).run_action  # fmt: skip
    try:
        made = await run(
            "motion.write_scenes",
            {"name": "Three scenes", "shape": "portrait", "scenes": FILM["scenes"][:2]},
            "window", actor=me,
        )  # fmt: skip
        assert made.status == "ok", made
        cid = made.output["composition_id"]
        added = await run(
            "motion.add_scene",
            {"composition_id": cid, "kind": "title", "fields": {"title": "Try it", "seconds": 3}},
            "window", actor=me,
        )  # fmt: skip
        assert added.status == "ok", added
        done = await run("video_builder.render", {"composition_id": cid}, "window", actor=me)
        assert done.status == "ok", done
        assert done.output["checked"] is True and done.output["seconds"] == 10
        clip = await video_store(database).get("t1", "u1", done.output["video_id"])
        assert clip is not None and clip.status == "done" and clip.mode == "composition"
        assert (clip.width, clip.height) == templates.SHAPES["portrait"]
    finally:
        await database.dispose()


async def test_a_part_placed_on_the_picture_is_there_in_the_video_and_passes_the_check(
    tmp_path, engine
):
    film = {
        "scenes": [
            {
                "kind": "title",
                "fields": {"title": "Moved here", "theme": "midnight", "seconds": 3},
                "arrange": {"title": {"x": 10, "y": 20, "w": 40, "scale": 0.8}},
            },
            {
                "kind": "quote",
                "caption": "Up top",
                "fields": {
                    "quote": "Words",
                    "author": "Someone",
                    "theme": "midnight",
                    "seconds": 4,
                },
                "arrange": {
                    "quote": {"x": 50, "y": 60, "w": 40, "scale": 1.5},
                    "caption": {"x": 20, "y": 15, "w": 60},
                },
            },
        ]
    }
    folder, slots = write(tmp_path, engine, templates.SCENES, film)
    report = await checked(engine, folder, templates.SCENES, slots)
    assert report["ok"], report["message"]
    out = tmp_path / "placed.mp4"
    assert (await engine.render(folder, out, extra_args=("--format", "mp4"))).ok

    def bright(at: float) -> tuple[float, float, float, float]:
        width, height, data = frame_at(out, at)
        xs, ys = [], []
        for y in range(height):
            for x in range(width):
                at_ = (y * width + x) * 3
                if data[at_] > 200 and data[at_ + 1] > 200 and data[at_ + 2] > 200:
                    xs.append(x)
                    ys.append(y)
        assert xs, "nothing bright in the frame"
        w, h = width / 100, height / 100
        return min(xs) / w, min(ys) / h, max(xs) / w, max(ys) / h

    left, top, right, bottom = bright(2.5)
    # the box is 10% to 50% across, and a title is centred in its box
    assert left > 9.5 and right < 50.5 and 20 < top < 30 and bottom < 35, (left, top, right, bottom)
    left, top, right, bottom = bright(6.5)
    # the quote and its caption are in the places given, not the template's
    assert top < 25 and bottom > 60, (top, bottom)


# ---- a film with its files (ADR-0096 MX5) --------------------------------------------------------


@pytest.fixture(scope="module")
def media_files(tmp_path_factory) -> dict[str, dict[str, Any]]:
    """A picture, a clip with a 440 Hz sound, sounds of 220 and 880 Hz, checked as uploads are."""
    folder = tmp_path_factory.mktemp("media")
    ffmpeg = tool("ffmpeg")

    def make(name: str, *args: str) -> bytes:
        path = folder / name
        subprocess.run([ffmpeg, "-v", "error", "-y", *args, str(path)], check=True)
        return path.read_bytes()

    made = {
        "pic": make(
            "pic.png", "-f", "lavfi", "-i", "color=c=0xd9925a:s=200x400:d=1", "-frames:v", "1"
        ),
        "clip": make(
            "clip.mp4", "-f", "lavfi", "-i", "color=c=0x00ff00:s=640x360:r=30:d=6",
            "-f", "lavfi", "-i", "sine=f=440:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
        ),
        "music": make("music.wav", "-f", "lavfi", "-i", "sine=f=220:d=4"),
        "voice": make("voice.wav", "-f", "lavfi", "-i", "sine=f=880:d=2"),
    }  # fmt: skip
    return {k: {"data": v, "checked": media.check_upload(v, f"{k}.bin")} for k, v in made.items()}


def media_film(files: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ids = {k: v["checked"].asset["id"] for k, v in files.items()}
    return {
        "assets": [v["checked"].asset for v in files.values()],
        "soundtrack": {"asset": ids["music"], "volume": 0.4, "loop": True},
        "scenes": [
            {"kind": "title", "fields": {"title": "A picture", "seconds": 3},
             "images": [{"asset": ids["pic"]}],
             "arrange": {"image-0": {"x": 70, "y": 20, "w": 15}}},
            {"kind": "title", "fields": {"title": "A clip", "seconds": 3},
             "background": {"asset": ids["clip"], "trim": 1, "volume": 0.5}},
            {"kind": "title", "fields": {"title": "A sound", "seconds": 3},
             "sound": {"asset": ids["voice"], "volume": 0.8}},
        ],
    }  # fmt: skip


def power(path: Path, start: float, hertz: int) -> float:
    """How loud one tone is in a stretch of the video's sound (dB; about -100 when it is absent)."""
    raw = subprocess.run(
        [tool("ffmpeg"), "-v", "error", "-ss", str(start), "-t", "0.5", "-i", str(path), "-ac", "1",
         "-ar", "8000", "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    samples = array.array("f")
    samples.frombytes(raw[: len(raw) // 4 * 4])
    total = sum(v * cmath.exp(-2j * math.pi * hertz * i / 8000) for i, v in enumerate(samples))
    return 20 * math.log10(max(abs(total) / max(1, len(samples)) * 2, 1e-5))


def pixel(path: Path, at: float, x: float, y: float) -> tuple[int, ...]:
    width, height, data = frame_at(path, at)
    i = (int(y * height) * width + int(x * width)) * 3
    return tuple(data[i : i + 3])


def assert_media_film(out: Path) -> None:
    r, g, b = pixel(out, 1.5, 0.77, 0.3)
    assert r > 180 and b < 140, ("the picture, where it was placed", r, g, b)
    r, g, b = pixel(out, 4.5, 0.9, 0.9)
    assert g > 180 and r < 100, ("the clip behind the second scene", r, g, b)
    assert power(out, 1, 220) > -40, "the soundtrack plays from the start"
    assert power(out, 1, 440) < -60 and power(out, 1, 880) < -60
    assert power(out, 4, 440) > -40, "the clip's own sound, in its scene only"
    assert power(out, 7, 880) > -40, "the scene's sound, in its scene only"
    assert power(out, 7, 440) < -60
    assert power(out, 7, 220) > -40, "the soundtrack goes on, repeating"


@pytest.mark.parametrize("shape", ["landscape", "portrait", "square"])
async def test_a_typed_caption_where_it_starts_is_inside_the_picture(tmp_path, engine, shape):
    film = {
        "shape": shape,
        "scenes": [{"kind": "title", "fields": {"title": "Words"}, "caption": "A typed caption"}],
    }
    folder, slots = write(tmp_path, engine, templates.SCENES, film)
    report = await checked(engine, folder, templates.SCENES, slots)
    assert report["ok"], report["message"]


async def test_timed_captions_are_each_on_the_screen_when_said_and_gone_after(
    tmp_path, engine, media_files
):
    voice = media_files["voice"]["checked"].asset
    film = {
        "assets": [voice],
        "scenes": [
            {"kind": "title", "fields": {"title": "Words", "seconds": 4},
             "sound": {"asset": voice["id"]},
             "cues": [{"text": "Mornings are hard.", "start": 0.5, "end": 1.5},
                      {"text": "We steep it slowly.", "start": 1.5, "end": 3.0}]},
        ],
    }  # fmt: skip
    folder, slots = write(tmp_path, engine, templates.SCENES, film)
    (folder / "assets").mkdir()
    (folder / "assets" / voice["file"]).write_bytes(media_files["voice"]["checked"].data)
    assert engine.lint(folder) == []
    report = await checked(engine, folder, templates.SCENES, slots)
    assert report["ok"], report["message"]
    out = tmp_path / "film.mp4"
    result = await engine.render(folder, out, extra_args=("--format", "mp4", "--quality", "draft"))
    assert result is not None and out.stat().st_size > 0
    # the caption's band is there while a line is said, and the picture is plain before and after
    before, said, after = (pixel(out, at, 0.5, 0.855) for at in (0.2, 1.0, 3.6))
    assert before == after and sum(abs(a - b) for a, b in zip(said, after, strict=True)) > 20


async def test_a_film_with_a_picture_a_clip_and_sounds_is_all_in_the_video(
    tmp_path, engine, media_files
):
    folder, slots = write(tmp_path, engine, templates.SCENES, media_film(media_files))
    (folder / "assets").mkdir()
    for f in media_files.values():
        (folder / "assets" / f["checked"].asset["file"]).write_bytes(f["checked"].data)
    assert engine.lint(folder) == []
    report = await checked(engine, folder, templates.SCENES, slots)
    assert report["ok"], report["message"]
    out = tmp_path / "film.mp4"
    result = await engine.render(folder, out, extra_args=("--format", "mp4", "--quality", "draft"))
    assert result.ok, result.message
    assert result.blocked == []
    assert_media_film(out)


async def test_a_worker_makes_the_same_film_from_files_in_storage(tmp_path, engine, media_files):
    """The web's path, for real: the worker's own handler, the real sandbox, the files in storage
    under the job's prefix, as `remote_builder` puts them there."""
    handlers = pytest.importorskip("wasifyai_engine_worker.handlers")
    from wasifyai_platform_sdk import memory_storage
    from wasifyai_platform_sdk.engine_jobs import EngineJob

    slots = templates.normalize_slots(templates.SCENES, media_film(media_files))
    storage = memory_storage()
    prefix = "t1/wasifyai-video/u1/engine/job-1"
    files = {}
    for f in media_files.values():
        name = f["checked"].asset["file"]
        await storage.put(f"{prefix}/in/{name}", f["checked"].data)
        files[f"project/assets/{name}"] = f"{prefix}/in/{name}"
    job = EngineJob(
        id="job-1", kind="builder.render", tenant_id="t1", product_id="wasifyai-video",
        user_id="u1", prefix=prefix, files=files,
        params={"template": templates.SCENES, "slots": slots, "format": "mp4", "quality": "draft"},
    )  # fmt: skip
    work = handlers.Work(job, storage, tmp_path / "work")
    (tmp_path / "work").mkdir()
    numbers = await handlers._render(engine, work)
    assert numbers["ok"], numbers["message"]
    out = tmp_path / "from-worker.mp4"
    out.write_bytes(await storage.get(work.outputs["video"]))
    assert_media_film(out)
    # a file outside the job's prefix is refused, whatever a job names
    other = EngineJob(
        id="job-2", kind="builder.render", tenant_id="t1", product_id="wasifyai-video",
        user_id="u1", prefix=prefix, files={"project/assets/x.png": "t2/secret/x.png"},
        params={},
    )  # fmt: skip
    with pytest.raises(handlers.Refused):
        await handlers.Work(other, storage, tmp_path / "work2").file("project/assets/x.png")
