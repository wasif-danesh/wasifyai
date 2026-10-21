# ruff: noqa: ASYNC221  (the tests run ffmpeg and ffprobe on purpose)
"""The five Video Builder templates through the real sandboxed browser (MG1).

Every template is written to a project folder with the shipped fonts, seen by the real pinned
browser, compared with the words that were typed, and drawn to a file. What is proved here and
cannot be on stand-ins: the fonts load, 20 hostile slot cases fit the safe area, a retyped or
clipped word is caught, and the transparent files decode with a real alpha channel.

Skipped unless a component is installed: set `WASIFYAI_VIDEO_BUILDER_HOME` to
`<app data>/components/video-builder` (CI installs it with `scripts/ci-video-builder.py`)."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from wasifyai_api import video_builder_runtime as vb
from wasifyai_api.desktop_video_builder import VideoBuilderService
from wasifyai_video.builder import check, projects, templates

INSTALL = vb.find_install(Path("/nonexistent"))
pytestmark = pytest.mark.skipif(
    INSTALL is None or len(vb.find_media_tools(INSTALL)) < len(vb.MEDIA_TOOLS),
    reason="Video Builder or FFmpeg (with ffprobe) is not installed",
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
